"""
Start 4 RunPod pods for dots-ocr + coordinator workflow.
Creates pods, waits for them to be ready, and provides SSH commands.
"""

import asyncio
import json
import sys
from pathlib import Path
from services.runpod_api import RunPodClient

# Configuration
NUM_PODS = 4
GPU_TYPE = "NVIDIA GeForce RTX 4090"  # Best price/performance for dots-ocr
NETWORK_VOLUME_ID = "rxfyzj7m42"  # Texas volume (better availability)
POD_NAME_PREFIX = "scholia-dots"
IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"


async def create_pods(count: int = NUM_PODS):
    """Create multiple pods for parallel processing."""
    client = RunPodClient()

    # Check current pods first
    existing = await client.list_pods(NETWORK_VOLUME_ID)
    print(f"Found {len(existing)} existing pods on volume {NETWORK_VOLUME_ID}")

    if existing:
        print("\nExisting pods:")
        for p in existing:
            status = p.get('desiredStatus', 'unknown')
            print(f"  - {p.get('name')} ({p.get('id')}): {status}")

        # Check if any are stopped that we can resume
        stopped = [p for p in existing if p.get('desiredStatus') == 'STOPPED']
        if stopped:
            print(f"\n{len(stopped)} stopped pods found. Resuming them...")
            for pod in stopped:
                try:
                    await client.resume_pod(pod['id'])
                    print(f"  Resumed: {pod['name']}")
                except Exception as e:
                    print(f"  Failed to resume {pod['name']}: {e}")

    # Calculate how many more pods we need
    running_or_resuming = [p for p in existing if p.get('desiredStatus') in ('RUNNING', 'STARTING')]
    need_to_create = count - len(running_or_resuming) - len([p for p in existing if p.get('desiredStatus') == 'STOPPED'])

    if need_to_create <= 0:
        print(f"\nAlready have enough pods. No new pods needed.")
    else:
        print(f"\nCreating {need_to_create} new pods...")

        # Find next available number
        existing_numbers = set()
        for p in existing:
            name = p.get('name', '')
            if name.startswith(POD_NAME_PREFIX):
                try:
                    num = int(name.split('-')[-1])
                    existing_numbers.add(num)
                except ValueError:
                    pass

        next_num = 1
        created = []

        for i in range(need_to_create):
            while next_num in existing_numbers:
                next_num += 1

            pod_name = f"{POD_NAME_PREFIX}-{next_num}"
            print(f"  Creating {pod_name}...")

            try:
                result = await client.create_pod(
                    name=pod_name,
                    gpu_type=GPU_TYPE,
                    network_volume_id=NETWORK_VOLUME_ID,
                    image=IMAGE,
                    container_disk_gb=20,
                    volume_mount_path="/workspace"  # Must match router paths
                )
                created.append(result)
                print(f"    Created: {result.get('id')}")
                existing_numbers.add(next_num)
                next_num += 1
            except Exception as e:
                print(f"    Failed: {e}")

    # Wait for pods to be ready
    print("\nWaiting for pods to be ready...")
    await asyncio.sleep(5)  # Give API time to update

    max_wait = 120  # seconds
    waited = 0

    while waited < max_wait:
        all_pods = await client.list_pods(NETWORK_VOLUME_ID)
        ready = [p for p in all_pods if p.get('desiredStatus') == 'RUNNING' and p.get('runtime')]
        starting = [p for p in all_pods if p.get('desiredStatus') in ('STARTING', 'RUNNING') and not p.get('runtime')]

        print(f"  Ready: {len(ready)}, Starting: {len(starting)}")

        if len(ready) >= count or (len(starting) == 0 and len(ready) > 0):
            break

        await asyncio.sleep(10)
        waited += 10

    # Get final pod list with SSH details
    print("\n" + "=" * 60)
    print("PODS READY")
    print("=" * 60)

    final_pods = await client.list_pods(NETWORK_VOLUME_ID)
    pods_info = []

    for pod in final_pods:
        if pod.get('desiredStatus') != 'RUNNING':
            continue

        pod_id = pod.get('id')
        name = pod.get('name')

        # Get detailed info for SSH
        details = await client.get_pod(pod_id)
        runtime = details.get('runtime', {})

        # Find SSH port
        ssh_host = None
        ssh_port = None

        ports = runtime.get('ports', [])
        for p in ports:
            if p.get('privatePort') == 22:
                ssh_host = p.get('ip')
                ssh_port = p.get('publicPort')
                break

        pods_info.append({
            'id': pod_id,
            'name': name,
            'ssh_host': ssh_host,
            'ssh_port': ssh_port,
            'gpu': pod.get('gpuType')
        })

        print(f"\n{name} ({pod_id})")
        print(f"  GPU: {pod.get('gpuType')}")
        if ssh_host and ssh_port:
            print(f"  SSH: ssh root@{ssh_host} -p {ssh_port} -i ~/.ssh/id_ed25519")
        else:
            print(f"  SSH: Not ready yet (check dashboard)")

    # Save pod info
    pods_file = Path(__file__).parent.parent / "data" / "runpod_active_pods.json"
    pods_file.parent.mkdir(exist_ok=True)
    with open(pods_file, 'w') as f:
        json.dump({
            'network_volume_id': NETWORK_VOLUME_ID,
            'pods': pods_info
        }, f, indent=2)
    print(f"\nPod info saved to: {pods_file}")

    # Print setup instructions
    print("\n" + "=" * 60)
    print("SETUP INSTRUCTIONS")
    print("=" * 60)
    print("""
For EACH pod, SSH in and run:

    # Install dependencies
    pip install tqdm pymupdf --quiet
    cd /workspace/dots_ocr_repo && pip install -e . --quiet

    # Start coordinator (runs in background)
    cd /workspace && nohup python /workspace/scripts/coordinator.py > /workspace/logs/pod_$(hostname).log 2>&1 &

    # Check it's running
    ps aux | grep coordinator

To monitor progress from any pod:
    python /workspace/scripts/coordinator.py --status
    cat /workspace/status.json
""")

    return pods_info


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else NUM_PODS
    asyncio.run(create_pods(count))
