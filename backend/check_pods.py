import asyncio
import json
from services.runpod_api import RunPodClient

async def check():
    client = RunPodClient()
    pods = await client.list_pods()

    print(f"Found {len(pods)} pods:\n")
    for p in pods:
        print(f"ID: {p.get('id')}")
        print(f"  Name: {p.get('name')}")
        print(f"  Status: {p.get('desiredStatus')}")
        print(f"  Volume: {p.get('networkVolumeId')}")
        runtime = p.get('runtime')
        if runtime:
            print(f"  SSH: {runtime.get('ports', [])}")
        else:
            print(f"  SSH: No runtime (pod not running)")
        print()

asyncio.run(check())
