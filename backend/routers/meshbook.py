"""
Meshbook Router
===============
Proxy endpoints for Meshbook integration from the Scholia UI.
"""

import os

import httpx
from fastapi import APIRouter


DEFAULT_MESHBOOK_BASE_URL = "http://127.0.0.1:8420"
MESHBOOK_TIMEOUT_SECONDS = 2.0


router = APIRouter()


def _meshbook_base_url() -> str:
    return (
        os.getenv("MESHBOOK_API_BASE_URL")
        or os.getenv("MESHBOOK_OPERATOR_SHELL_BASE_URL")
        or os.getenv("MESHBOOK_BASE_URL")
        or DEFAULT_MESHBOOK_BASE_URL
    ).rstrip("/")


@router.get("/facet/{source_id}")
async def get_meshbook_facet(source_id: str):
    """
    Proxy Meshbook's compact facet payload for a Scholia source.

    This keeps browser calls same-origin with Scholia and degrades cleanly
    when the Meshbook server is offline or the source is unknown there.
    """
    url = f"{_meshbook_base_url()}/api/scholia-facet"

    try:
        async with httpx.AsyncClient(timeout=MESHBOOK_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params={"source_id": source_id})
            if response.status_code == 404:
                return {
                    "available": False,
                    "reason": "not_found",
                    "source_id": source_id,
                }
            response.raise_for_status()
    except httpx.TimeoutException:
        return {
            "available": False,
            "reason": "timeout",
            "source_id": source_id,
        }
    except httpx.RequestError:
        return {
            "available": False,
            "reason": "offline",
            "source_id": source_id,
        }
    except httpx.HTTPStatusError as exc:
        return {
            "available": False,
            "reason": "upstream_error",
            "source_id": source_id,
            "status_code": exc.response.status_code,
        }

    return {
        "available": True,
        "facet": response.json(),
    }
