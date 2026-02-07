"""Quick script to check if pods are ready and update config."""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from services.runpod_api import RunPodClient

CONFIG_FILE = Path(__file__).parent.parent / "data" / "runpod_connection.json"
VOLUME_ID = "eb6o7x47ip"  # Montreal


async def check_and_update():
    client = RunPodClient()
    pods = await client.list_pods(VOLUME_ID)

    ready = []
    waiting = []

    for pod in pods:
        details = await client.get_pod(pod["id"])
        runtime = details.get("runtime", {})
        ports = runtime.get("ports", [])

        ssh_info = None
        for p in ports:
            if p.get("privatePort") == 22:
                ssh_info = {"host": p["ip"], "port": p["publicPort"]}
                break

        if ssh_info:
            ready.append({"name": pod["name"], "id": pod["id"], **ssh_info})
        else:
            waiting.append(pod["name"])

    print(f"Ready: {len(ready)}/4")

    if ready:
        # Update config with first ready pod
        first = ready[0]
        config = {
            "host": first["host"],
            "port": first["port"],
            "pod_id": first["id"],
            "ssh_key_path": r"C:\Users\bhara\.ssh\id_ed25519",
            "last_updated": datetime.now().isoformat(),
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        print("\nReady pods:")
        for rp in ready:
            print(f"  {rp['name']}: ssh root@{rp['host']} -p {rp['port']} -i ~/.ssh/id_ed25519")
        print(f"\nConfig updated! You can use Lit Processor now.")

    if waiting:
        print(f"\nStill waiting: {', '.join(waiting)}")


if __name__ == "__main__":
    asyncio.run(check_and_update())
