"""
Setup Montreal volume with latest coordinator script.
Run this once a pod is SSH-ready.
"""

import asyncio
import subprocess
import json
from pathlib import Path
from services.runpod_api import RunPodClient

CONFIG_FILE = Path(__file__).parent.parent / "data" / "runpod_connection.json"
COORDINATOR_SCRIPT = Path(__file__).parent / "services" / "runpod_scripts" / "coordinator.py"
SSH_KEY = Path.home() / ".ssh" / "id_ed25519"


def get_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return None


def ssh_command(config, command, timeout=30):
    """Run SSH command on pod."""
    host = config["host"]
    port = config["port"]
    key = config.get("ssh_key_path", str(SSH_KEY))

    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-i", key,
        "-p", str(port),
        f"root@{host}",
        command
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode == 0, result.stdout


def scp_upload(config, local_path, remote_path):
    """Upload file via SCP."""
    host = config["host"]
    port = config["port"]
    key = config.get("ssh_key_path", str(SSH_KEY))

    cmd = [
        "scp",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-i", key,
        "-P", str(port),
        str(local_path),
        f"root@{host}:{remote_path}"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.returncode == 0, result.stderr


async def setup():
    config = get_config()
    if not config:
        print("No config found. Run check_ready.py first.")
        return

    print(f"Setting up pod at {config['host']}:{config['port']}...")

    # Test connection
    print("1. Testing SSH connection...")
    success, output = ssh_command(config, "echo 'SSH OK'")
    if not success:
        print("   SSH connection failed. Pod may not be ready yet.")
        print("   Run: python check_ready.py")
        return
    print("   Connected!")

    # Create directories
    print("2. Creating directories...")
    ssh_command(config, "mkdir -p /workspace/input /workspace/output /workspace/processing /workspace/logs /workspace/scripts /workspace/archive")
    print("   Done")

    # Upload coordinator script
    print("3. Uploading coordinator.py...")
    if not COORDINATOR_SCRIPT.exists():
        print(f"   ERROR: {COORDINATOR_SCRIPT} not found!")
        return

    success, error = scp_upload(config, COORDINATOR_SCRIPT, "/workspace/scripts/coordinator.py")
    if success:
        print("   Uploaded!")
    else:
        print(f"   Failed: {error}")
        return

    # Check if dots-ocr repo exists
    print("4. Checking dots-ocr setup...")
    success, output = ssh_command(config, "test -d /workspace/dots_ocr_repo && echo 'exists'")
    if "exists" in output:
        print("   dots-ocr repo already present")
    else:
        print("   dots-ocr repo not found - needs manual setup:")
        print("   cd /workspace && git clone https://github.com/diT-organization/dots.ocr.git dots_ocr_repo")
        print("   cd /workspace/dots_ocr_repo && pip install -e . --quiet")

    # Install dependencies
    print("5. Installing dependencies...")
    ssh_command(config, "pip install tqdm pymupdf --quiet 2>/dev/null", timeout=120)
    print("   Done")

    print()
    print("=" * 60)
    print("SETUP COMPLETE!")
    print("=" * 60)
    print()
    print("To start coordinator on this pod:")
    print(f"  ssh root@{config['host']} -p {config['port']} -i ~/.ssh/id_ed25519")
    print("  cd /workspace && nohup python /workspace/scripts/coordinator.py > /workspace/logs/coordinator.log 2>&1 &")
    print()
    print("Or you can upload PDFs via the Lit Processor UI now!")


if __name__ == "__main__":
    asyncio.run(setup())
