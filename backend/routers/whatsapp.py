"""
WhatsApp Webhook Router
=======================
Handles incoming WhatsApp messages via Cloud API webhook.

Endpoints:
- GET  /webhook/whatsapp - Webhook verification (Meta challenge)
- POST /webhook/whatsapp - Receive incoming messages
- POST /webhook/capture  - Manual capture (testing without WhatsApp)

Flow:
1. User sends message to WhatsApp number
2. Meta sends webhook POST to this endpoint
3. Classify using Gemini Flash (structured output)
4. Match person refs to existing person gluons
5. Create a journal entry with category tag + person links
6. Send confirmation reply
"""

import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from database import get_db
from services.classifier import classify_structured
from services.whatsapp_client import get_whatsapp_client
from routers.gluons import get_or_create_tag, process_links_in_content
from routers.journal import match_person_refs

import re

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

    return {"status": "ok", "processed": len(messages)}


async def _resolve_unclosed_refs(content: str) -> str:
    """
    Find unclosed [[ref patterns and resolve them via fuzzy DB match.

    Examples:
      "Finish [[moom audit today"  → "Finish [[Moom]] audit today"
      "Read [[Hinton paper"        → "Read [[Hinton, Geoffrey E.]] paper"
      "Look into [[spaced rep"     → "Look into [[spaced rep]]"  (no match, close as-is)
    """
    # Find unclosed [[ patterns: [[ followed by text without a closing ]]
    # We look for [[ not followed by any ]] before the next [[ or ## or end-of-string
    pattern = r'\[\[(?![^\[\]]*\]\])([^\[\]#]*)'
    matches = list(re.finditer(pattern, content))
    if not matches:
        return content

    db = await get_db()
    result = content

    # Process in reverse order so replacements don't shift offsets
    for match in reversed(matches):
        raw_text = match.group(1).strip()
        if not raw_text:
            continue

        # Progressive matching: try full phrase, then progressively shorter
        words = raw_text.split()
        resolved_name = None

        for length in range(len(words), 0, -1):
            candidate = " ".join(words[:length])
            cursor = await db.execute(
                "SELECT content FROM gluons WHERE type = 'note' AND content LIKE ? COLLATE NOCASE LIMIT 1",
                [f"%{candidate}%"]
            )
            row = await cursor.fetchone()
            if row:
                resolved_name = row[0]
                # The remainder after the matched words goes back into the text
                remainder = " ".join(words[length:])
                break

        if resolved_name:
            # Replace [[raw_text with [[ResolvedName]] + remainder
            replacement = f"[[{resolved_name}]]"
            if remainder:
                replacement += " " + remainder
            result = result[:match.start()] + replacement + result[match.end():]
        else:
            # No match at all — close with the first word as the ref
            if len(words) == 1:
                result = result[:match.start()] + f"[[{words[0]}]]" + result[match.end():]
            else:
                # Take the full phrase
                result = result[:match.start()] + f"[[{raw_text}]]" + result[match.end():]

    return result


def _extract_tag_override(content: str) -> str | None:
    """
    If content contains ##tags, return the highest-priority one as category override.
    Returns None if no ##tags found.
    """
    tag_matches = re.findall(r'##(\w+)', content)
    if not tag_matches:
        return None
    tags = [t.lower() for t in tag_matches]
    priority = ['task', 'idea', 'social', 'admin', 'inbox']
    return next((t for t in tags if t in priority), tags[0])


async def _create_journal_from_classification(
    classification, captured_via: str = "whatsapp"
) -> dict:
    """
    Create a single journal entry from a StructuredClassification.

    Shared by WhatsApp capture and manual capture endpoints.
    Returns dict with entry details for response/logging.
    """
    category = classification.effective_category
    header = classification.header or ""
    details = classification.details
    is_task = classification.is_task

    # Resolve unclosed [[refs via fuzzy DB match
    content = await _resolve_unclosed_refs(header)

    # Override category from ##tags in content (user-specified tags take priority)
    tag_override = _extract_tag_override(content)
    if tag_override:
        category = tag_override
        is_task = category == "task"

    # Match person refs to existing person gluons
    matched_persons = await match_person_refs(classification.person_refs)

    # Inject [[Person Name]] into content for linking (only if not already present)
    for person in matched_persons:
        ref_str = f"[[{person['name']}]]"
        if ref_str not in content:
            content += f" {ref_str}"

    # Create the journal entry gluon
    db = await get_db()
    now = datetime.now().isoformat()
    completed = 0 if is_task else None
    body = "\n".join(details) if details else None

    entry_id = str(uuid.uuid4())[:8]
    await db.execute("""
        INSERT INTO gluons (id, type, content, body, completed, captured_via, created_at, updated_at)
        VALUES (?, 'journal_entry', ?, ?, ?, ?, ?, ?)
    """, [entry_id, content, body, completed, captured_via, now, now])

    # Index in FTS (content + body combined)
    fts_text = content
    if body:
        fts_text += " " + body
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        VALUES ((SELECT rowid FROM gluons WHERE id = ?), ?)
    """, [entry_id, fts_text])

    await db.commit()

    # Process [[refs]] and ##tags in content (wipes all links, recreates from content)
    await process_links_in_content(entry_id, content)

    # Add category tag only if not already linked by process_links_in_content
    tag_id = await get_or_create_tag(category)
    cursor = await db.execute(
        "SELECT 1 FROM links WHERE source_id = ? AND target_id = ? AND link_type = 'tag'",
        [entry_id, tag_id]
    )
    if not await cursor.fetchone():
        link_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO links (id, source_id, target_id, link_type, created_at)
            VALUES (?, ?, ?, 'tag', ?)
        """, [link_id, entry_id, tag_id, now])
    await db.commit()

    print(f"[{captured_via} → Journal] {category}: {header[:60]}")

    return {
        "id": entry_id,
        "content": content,
        "body": body,
        "category": category,
        "header": header,
        "details": details,
        "is_task": is_task,
        "person_refs": classification.person_refs,
        "matched_persons": matched_persons,
        "confidence": classification.confidence,
        "tag_id": tag_id,
    }


async def process_capture(from_number: str, text: str):
    """
    Process a captured note from WhatsApp.

    Classifies the message (may produce multiple items), creates journal
    entries for each, and sends a confirmation reply.
    """
    if not text.strip():
        return

    # Classify — returns a list (one or more items)
    classifications = await classify_structured(text)

    print(f"[WhatsApp] Classified into {len(classifications)} item(s)")

    # Create a journal entry for each classified item
    created = []
    for cls in classifications:
        entry = await _create_journal_from_classification(cls, captured_via="whatsapp")
        created.append(entry)

    # Send confirmation reply
    client = get_whatsapp_client()
    if client.is_configured and created:
        if len(created) == 1:
            e = created[0]
            reply = f"✓ {e['category']}: {e['header']}"
            if e["details"]:
                reply += "\n" + "\n".join(f"  • {d}" for d in e["details"][:3])
        else:
            lines = [f"✓ {len(created)} items saved:"]
            for e in created:
                lines.append(f"  #{e['category']}: {e['header']}")
            reply = "\n".join(lines)
        await client.send_confirmation(from_number, created[0]["category"], reply)


# --- Manual Capture Endpoint (for testing without WhatsApp) ---

class ManualCaptureRequest(BaseModel):
    text: str


@router.post("/capture")
async def manual_capture(request: ManualCaptureRequest):
    """
    Manual capture endpoint for testing classification without WhatsApp.

    Uses the structured classifier (Gemini Flash) and creates journal entries.
    May return multiple entries if the input contains distinct items.
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    classifications = await classify_structured(request.text)

    entries = []
    for cls in classifications:
        entry = await _create_journal_from_classification(cls, captured_via="web")
        entries.append(entry)

    return {"entries": entries, "count": len(entries)}
