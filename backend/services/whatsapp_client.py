"""
WhatsApp Cloud API Client
=========================
Handles sending messages via WhatsApp Cloud API.
"""

import os
import httpx
from typing import Optional


# WhatsApp Cloud API base URL
GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class WhatsAppClient:
    """Client for WhatsApp Cloud API."""

    def __init__(self):
        self.access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
        self.phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

    @property
    def is_configured(self) -> bool:
        """Check if WhatsApp credentials are configured."""
        return bool(self.access_token and self.phone_number_id)

    async def send_text_message(self, to: str, text: str) -> dict:
        """
        Send a text message via WhatsApp.

        Args:
            to: Recipient phone number (with country code, no + prefix)
            text: Message content

        Returns:
            API response dict
        """
        if not self.is_configured:
            return {"error": True, "message": "WhatsApp not configured"}

        url = f"{GRAPH_API_BASE}/{self.phone_number_id}/messages"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text
            }
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                return {
                    "error": True,
                    "status_code": e.response.status_code,
                    "message": e.response.text
                }
            except Exception as e:
                return {
                    "error": True,
                    "message": str(e)
                }

    async def send_confirmation(self, to: str, category: str, original_text: str) -> dict:
        """
        Send a confirmation message after processing a capture.

        Args:
            to: Recipient phone number
            category: The classified category
            original_text: The original message (truncated for preview)

        Returns:
            API response dict
        """
        # Emoji map for categories
        emoji_map = {
            "task": "✅",
            "idea": "💡",
            "people": "👤",
            "admin": "📋",
            "inbox": "📥"
        }

        emoji = emoji_map.get(category, "📝")

        # Truncate original text for preview
        preview = original_text[:50] + "..." if len(original_text) > 50 else original_text

        message = f"{emoji} Saved as #{category}\n\n\"{preview}\""

        return await self.send_text_message(to, message)


# Singleton instance
_client: Optional[WhatsAppClient] = None


def get_whatsapp_client() -> WhatsAppClient:
    """Get or create the WhatsApp client singleton."""
    global _client
    if _client is None:
        _client = WhatsAppClient()
    return _client
