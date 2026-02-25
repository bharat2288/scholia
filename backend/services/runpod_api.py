"""
RunPod API Client
=================
Wraps RunPod REST API for pod and volume management.

Used for multi-pod parallel processing pipeline.
"""

import os
import httpx
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load API key from .env
local_env = Path(__file__).parent.parent / ".env"
dev_env = Path(r"C:\Users\bhara\dev\.env")

if local_env.exists():
    load_dotenv(local_env, override=True)
elif dev_env.exists():
    load_dotenv(dev_env, override=True)


class RunPodClient:
    """
    Client for RunPod REST API.

    Handles pod creation, listing, termination, and volume operations.
    """

    BASE_URL = "https://rest.runpod.io/v1"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize client with API key.

        Args:
            api_key: RunPod API key. If not provided, reads from RUNPOD_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("RUNPOD_API_KEY")
        if not self.api_key:
            raise ValueError("RUNPOD_API_KEY not found in environment or not provided")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    # =========================================================================
    # Pod Operations
    # =========================================================================

    async def create_pod(
        self,
        name: str,
        gpu_type: str,
        network_volume_id: str,
        image: str = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
        container_disk_gb: int = 20,
        volume_mount_path: str = "/data",
        env_vars: Optional[dict] = None
    ) -> dict:
        """
        Create a pod with network volume attached.

        Args:
            name: Display name for the pod
            gpu_type: GPU type string (e.g., "NVIDIA GeForce RTX 4090", "NVIDIA A40")
            network_volume_id: ID of network volume to attach
            image: Docker image to use
            container_disk_gb: Ephemeral disk size in GB
            volume_mount_path: Where to mount the network volume
            env_vars: Optional environment variables dict

        Returns:
            Pod creation response with id, status, etc.
        """
        payload = {
            "name": name,
            "imageName": image,
            "gpuTypeIds": [gpu_type],
            "networkVolumeId": network_volume_id,
            "volumeMountPath": volume_mount_path,
            "containerDiskInGb": container_disk_gb
            # Note: startSsh not supported by REST API
        }

        if env_vars:
            # env is a plain dict, not an array of {key, value} pairs
            payload["env"] = env_vars

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.BASE_URL}/pods",
                headers=self.headers,
                json=payload
            )
            # API returns 201 for successful creation
            if response.status_code not in (200, 201):
                # Include response body in error for better debugging
                try:
                    error_body = response.json()
                    error_msg = error_body.get("error", response.text)
                except (ValueError, KeyError):
                    error_msg = response.text
                raise RuntimeError(f"RunPod API error ({response.status_code}): {error_msg}")
            return response.json()

    async def list_pods(self, network_volume_id: Optional[str] = None) -> list:
        """
        List pods, optionally filtered by network volume.

        Args:
            network_volume_id: If provided, only return pods using this volume

        Returns:
            List of pod objects
        """
        params = {}
        # Note: networkVolumeId filter may not work on REST API - filter client-side
        # if network_volume_id:
        #     params["networkVolumeId"] = network_volume_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.BASE_URL}/pods",
                headers=self.headers,
                params=params
            )
            response.raise_for_status()
            data = response.json()
            # API returns list directly, not {"pods": [...]}
            pods = data if isinstance(data, list) else data.get("pods", [])

            # Client-side filter by network volume if requested
            if network_volume_id:
                pods = [p for p in pods if p.get("networkVolumeId") == network_volume_id]

            return pods

    async def get_pod(self, pod_id: str) -> dict:
        """
        Get detailed pod info including SSH connection details.

        Args:
            pod_id: The pod ID

        Returns:
            Pod details including runtime info, SSH host/port
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.BASE_URL}/pods/{pod_id}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def stop_pod(self, pod_id: str) -> bool:
        """
        Stop (pause) a pod. Can be resumed later.

        Args:
            pod_id: The pod ID

        Returns:
            True if successful
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.BASE_URL}/pods/{pod_id}/stop",
                headers=self.headers
            )
            return response.status_code == 200

    async def resume_pod(self, pod_id: str) -> dict:
        """
        Resume a stopped pod.

        Args:
            pod_id: The pod ID

        Returns:
            Pod info after resume
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.BASE_URL}/pods/{pod_id}/resume",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def terminate_pod(self, pod_id: str) -> bool:
        """
        Terminate a pod permanently. All ephemeral data is lost.
        Network volume data persists.

        Args:
            pod_id: The pod ID

        Returns:
            True if successful
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(
                f"{self.BASE_URL}/pods/{pod_id}",
                headers=self.headers
            )
            return response.status_code == 200

    # =========================================================================
    # Volume Operations (uses GraphQL - REST doesn't support volumes)
    # =========================================================================

    GRAPHQL_URL = "https://api.runpod.io/graphql"

    async def list_volumes(self) -> list:
        """
        List all network volumes using GraphQL API.

        Returns:
            List of volume objects with id, name, size, datacenter
        """
        query = """
        query {
            myself {
                networkVolumes {
                    id
                    name
                    size
                    dataCenterId
                }
            }
        }
        """

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.GRAPHQL_URL,
                headers=self.headers,
                json={"query": query}
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", {}).get("myself", {}).get("networkVolumes", [])

    async def get_volume(self, volume_id: str) -> Optional[dict]:
        """
        Get a specific network volume by ID.

        Args:
            volume_id: The volume ID

        Returns:
            Volume details or None if not found
        """
        volumes = await self.list_volumes()
        for vol in volumes:
            if vol.get("id") == volume_id:
                return vol
        return None

    # =========================================================================
    # GPU Availability (uses GraphQL - REST API doesn't support this)
    # =========================================================================

    async def get_gpu_types(self) -> list:
        """
        Get available GPU types with pricing.

        Uses GraphQL because REST API doesn't have a gpuTypes endpoint.

        Returns:
            List of GPU type objects with id, displayName, securePrice, communityPrice
        """
        query = """
        query {
            gpuTypes {
                id
                displayName
                securePrice
                communityPrice
                maxGpuCount
            }
        }
        """

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.GRAPHQL_URL,
                headers=self.headers,
                json={"query": query}
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", {}).get("gpuTypes", [])

    # =========================================================================
    # Utility
    # =========================================================================

    async def test_connection(self) -> dict:
        """
        Test API connection by listing pods.

        Returns:
            Dict with success status and pod count
        """
        try:
            pods = await self.list_pods()
            return {
                "success": True,
                "pod_count": len(pods),
                "message": f"Connected. Found {len(pods)} pod(s)."
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# Convenience function for quick access
def get_runpod_client(api_key: Optional[str] = None) -> RunPodClient:
    """Get a RunPod client instance."""
    return RunPodClient(api_key)
