"""
WhatsApp Webhook Router
=======================
Handles incoming WhatsApp messages via Cloud API webhook.

Endpoints:
- GET  /webhook/whatsapp - Webhook verification (Meta challenge)
- POST /webhook/whatsapp - Receive incoming messages

Flow:
1. User sends message to WhatsApp number
2. Meta sends webhook POST to this endpoint
3. We extract the message text
4. Classify using Claude
5. Create a Gluon (note) with category tag
6. Send confirmation reply
"""

import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse

from database import get_db
from services.classifier import classify_note
from services.whatsapp_client import get_whatsapp_client

router = APIRouter(prefix="/webhook", tags=["whatsapp"])


# --- Webhook Verification ---

@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    """
    Webhook verification endpoint for Meta.

    Meta sends a GET request with:
    - hub.mode: Should be "subscribe"
    - hub.verify_token: Should match our configured token
    - hub.challenge: We echo this back to confirm
    """
    verify_token = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")

    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        # Return the challenge as plain text
        return PlainTextResponse(content=hub_challenge)
    else:
        raise HTTPException(status_code=403, detail="Verification failed")


# --- Message Handler ---

@router.post("/whatsapp")
async def handle_webhook(request: Request):
    """
    Handle incoming WhatsApp messages.

    Webhook payload structure (simplified):
    {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "1234567890",
                        "text": {"body": "message content"},
                        "type": "text"
                    }]
                }
            }]
        }]
    }
    """
    try:
        payload = await request.json()
    except Exception:
        # Meta sometimes sends empty or malformed payloads
        return {"status": "ok"}

    # Extract messages from webhook payload
    messages = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if message.get("type") == "text":
                    messages.append({
                        "from": message.get("from"),
                        "text": message.get("text", {}).get("body", ""),
                        "timestamp": message.get("timestamp")
                    })

    # Process each message
    for msg in messages:
        await process_capture(msg["from"], msg["text"])

    # Always return 200 to acknowledge receipt
    return {"status": "ok", "processed": len(messages)}


async def process_capture(from_number: str, text: str):
    """
    Process a captured note from WhatsApp.

    1. Classify the text
    2. Create a Gluon with appropriate tag
    3. Send confirmation reply
    """
    if not text.strip():
        return

    # 1. Classify
    classification = await classify_note(text)
    category = classification.effective_category

    # 2. Create Gluon (note) with tag
    db = await get_db()
    now = datetime.now().isoformat()

    # Create the note
    note_id = str(uuid.uuid4())[:8]
    await db.execute("""
        INSERT INTO gluons (id, type, content, captured_via, created_at, updated_at)
        VALUES (?, 'note', ?, 'whatsapp', ?, ?)
    """, [note_id, text, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [note_id])

    # Get or create the category tag
    cursor = await db.execute(
        "SELECT id FROM gluons WHERE type = 'tag' AND content = ?",
        [category]
    )
    tag_row = await cursor.fetchone()

    if tag_row:
        tag_id = tag_row[0]
    else:
        # Create the tag
        tag_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO gluons (id, type, content, created_at, updated_at)
            VALUES (?, 'tag', ?, ?, ?)
        """, [tag_id, category, now, now])

        # Index tag in FTS
        await db.execute("""
            INSERT INTO gluons_fts (rowid, content)
            SELECT rowid, content FROM gluons WHERE id = ?
        """, [tag_id])

    # Link note to tag
    link_id = str(uuid.uuid4())[:8]
    await db.execute("""
        INSERT INTO links (id, source_id, target_id, link_type, created_at)
        VALUES (?, ?, ?, 'tag', ?)
    """, [link_id, note_id, tag_id, now])

    await db.commit()

    # 3. Send confirmation reply
    client = get_whatsapp_client()
    if client.is_configured:
        await client.send_confirmation(from_number, category, text)

    print(f"[WhatsApp Capture] {category}: {text[:50]}...")


# --- Manual Capture Endpoint (for testing without WhatsApp) ---

from pydantic import BaseModel

class ManualCaptureRequest(BaseModel):
    text: str


@router.post("/capture")
async def manual_capture(request: ManualCaptureRequest):
    """
    Manual capture endpoint for testing classification without WhatsApp.

    Useful for:
    - Testing the classifier
    - Web-based quick capture
    - Debugging
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    # Classify
    classification = await classify_note(request.text)
    category = classification.effective_category

    # Create Gluon
    db = await get_db()
    now = datetime.now().isoformat()

    note_id = str(uuid.uuid4())[:8]
    await db.execute("""
        INSERT INTO gluons (id, type, content, captured_via, created_at, updated_at)
        VALUES (?, 'note', ?, 'web', ?, ?)
    """, [note_id, request.text, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [note_id])

    # Get or create tag
    cursor = await db.execute(
        "SELECT id FROM gluons WHERE type = 'tag' AND content = ?",
        [category]
    )
    tag_row = await cursor.fetchone()

    if tag_row:
        tag_id = tag_row[0]
    else:
        tag_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO gluons (id, type, content, created_at, updated_at)
            VALUES (?, 'tag', ?, ?, ?)
        """, [tag_id, category, now, now])
        await db.execute("""
            INSERT INTO gluons_fts (rowid, content)
            SELECT rowid, content FROM gluons WHERE id = ?
        """, [tag_id])

    # Link
    link_id = str(uuid.uuid4())[:8]
    await db.execute("""
        INSERT INTO links (id, source_id, target_id, link_type, created_at)
        VALUES (?, ?, ?, 'tag', ?)
    """, [link_id, note_id, tag_id, now])

    await db.commit()

    return {
        "id": note_id,
        "text": request.text,
        "classification": classification.to_dict(),
        "tag_id": tag_id
    }
