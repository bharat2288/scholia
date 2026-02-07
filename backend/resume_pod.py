import asyncio
import httpx
import os
from pathlib import Path
from dotenv import load_dotenv

# Load API key
local_env = Path(__file__).parent / ".env"
dev_env = Path(r"C:\Users\bhara\dev\.env")
if local_env.exists():
    load_dotenv(local_env, override=True)
elif dev_env.exists():
    load_dotenv(dev_env, override=True)

api_key = os.getenv("RUNPOD_API_KEY")

async def resume_pod_graphql(pod_id: str):
    """Try to resume pod via GraphQL API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # GraphQL mutation to resume pod
    query = """
    mutation resumePod($podId: String!) {
        podResume(input: { podId: $podId }) {
            id
            desiredStatus
            lastStatusChange
        }
    }
    """

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.runpod.io/graphql",
            headers=headers,
            json={"query": query, "variables": {"podId": pod_id}}
        )
        print(f"Status: {response.status_code}")
        print(response.json())

asyncio.run(resume_pod_graphql("k3daex483c5emk"))
