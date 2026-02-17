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
    button_responses = []

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
                elif message.get("type") == "interactive":
                    # User clicked a button
                    button_id = message.get("interactive", {}).get("button_reply", {}).get("id", "")
                    button_responses.append({
                        "from": message.get("from"),
                        "button_id": button_id,
                        "timestamp": message.get("timestamp")
                    })

    # Process button responses first
    for btn in button_responses:
        await handle_button_response(btn["from"], btn["button_id"])

    # Process text messages
    for msg in messages:
        text = msg["text"].strip()
        from_number = msg["from"]

        # Detect intent and route accordingly
        if text.startswith("?"):
            await handle_query_intent(from_number, text)
        elif text.startswith("done:") or text.lower().startswith("done "):
            query_text = text[5:].strip() if text.startswith("done:") else text[4:].strip()
            await handle_mark_done(from_number, query_text)
        elif text.startswith("add:") or text.lower().startswith("add "):
            query_text = text[4:].strip() if text.startswith("add:") else text[3:].strip()
            await handle_add_detail(from_number, query_text)
        elif text.startswith("delete:") or text.lower().startswith("delete "):
            query_text = text[7:].strip() if text.startswith("delete:") else text[6:].strip()
            await handle_delete_entry(from_number, query_text)
        else:
            # Default: new capture
            await process_capture(from_number, text)

    return {"status": "ok", "processed": len(messages) + len(button_responses)}


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


# --- Shared Intent Logic ---
# Each _do_* function performs the action and returns a result dict.
# Used by both WhatsApp webhook handlers and the manual /capture endpoint.


async def _fts_search_journal(search_text: str, extra_joins: str = "",
                               extra_where: str = "", extra_params: list | None = None,
                               limit: int = 5) -> list[tuple]:
    """
    Search journal entries via FTS5.

    Uses rowid subquery to bridge FTS results to gluons table (FTS stores
    integer rowids, g.id is a UUID string). Search text is quoted for phrase
    matching (matching the pattern in gluons.py search).
    """
    db = await get_db()

    # Quote for FTS5 phrase search and escape any internal double-quotes
    escaped = search_text.replace('"', '""')
    fts_term = f'"{escaped}"'

    # extra_params go first (they bind to ? in extra_joins),
    # then fts_term binds to the MATCH ? in the WHERE clause
    params = list(extra_params or []) + [fts_term]

    cursor = await db.execute(f"""
        SELECT g.id, g.content, g.body
        FROM gluons g
        {extra_joins}
        WHERE g.type = 'journal_entry'
          AND g.rowid IN (SELECT rowid FROM gluons_fts WHERE gluons_fts MATCH ?)
          {extra_where}
        ORDER BY g.created_at DESC
        LIMIT {limit}
    """, params)
    return await cursor.fetchall()


async def _do_query(query_text: str) -> dict:
    """
    Query journal entries by category, optionally filtered to today.

    Input format: ?<category> [today]
    Returns: {intent, category, time_filter, entries, count} or {intent, error}
    """
    query_lower = query_text.lower().strip()
    parts = query_lower[1:].split()  # Remove the '?' prefix

    if not parts:
        return {"intent": "query", "error": "Usage: ?tasks, ?ideas, ?social, ?admin, ?inbox"}

    category = parts[0]
    time_filter = "today" if len(parts) > 1 and "today" in parts else "all"

    # Validate and normalize category
    valid_categories = ["task", "tasks", "idea", "ideas", "social", "admin", "inbox"]
    if category not in valid_categories:
        return {"intent": "query", "error": f"Unknown category: {category}"}

    if category == "tasks":
        category = "task"
    elif category == "ideas":
        category = "idea"

    db = await get_db()

    # Build time filter clause
    if time_filter == "today":
        today = datetime.now().date().isoformat()
        time_clause = "AND g.created_at >= ?"
        time_param = today
    else:
        time_clause = ""
        time_param = None

    query = f"""
        SELECT g.id, g.content, g.body, g.completed, g.created_at
        FROM gluons g
        JOIN links l ON l.source_id = g.id AND l.link_type = 'tag'
        JOIN gluons t ON l.target_id = t.id AND t.type = 'tag' AND t.content = ?
        WHERE g.type = 'journal_entry'
        {time_clause}
        ORDER BY g.created_at DESC
        LIMIT 10
    """

    params = [category, time_param] if time_param else [category]
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    entries = []
    for entry_id, content, body, completed, created_at in rows:
        entries.append({
            "id": entry_id, "content": content, "body": body,
            "completed": completed, "created_at": created_at,
        })

    return {
        "intent": "query", "category": category,
        "time_filter": time_filter, "entries": entries, "count": len(entries),
    }


async def _do_mark_done(query_text: str) -> dict:
    """
    Mark a task as complete via FTS search.

    Returns: {intent, completed, entry} or {intent, matches, entries} for disambiguation.
    """
    if not query_text:
        return {"intent": "mark_done", "error": "Usage: done: <task description>"}

    db = await get_db()

    cursor = await db.execute(
        "SELECT id FROM gluons WHERE type = 'tag' AND content = 'task'"
    )
    task_tag_row = await cursor.fetchone()
    if not task_tag_row:
        return {"intent": "mark_done", "error": "No tasks found"}

    task_tag_id = task_tag_row[0]

    matches = await _fts_search_journal(
        query_text,
        extra_joins="JOIN links l ON l.source_id = g.id AND l.target_id = ? AND l.link_type = 'tag'",
        extra_where="AND g.completed = 0",
        extra_params=[task_tag_id],
    )

    if not matches:
        return {"intent": "mark_done", "query": query_text, "matches": 0}

    if len(matches) == 1:
        entry_id, content, body = matches[0]
        now = datetime.now().isoformat()
        await db.execute(
            "UPDATE gluons SET completed = 1, updated_at = ? WHERE id = ?",
            [now, entry_id]
        )
        await db.commit()
        return {"intent": "mark_done", "query": query_text, "completed": True,
                "entry": {"id": entry_id, "content": content}}

    return {
        "intent": "mark_done", "query": query_text,
        "matches": len(matches),
        "entries": [{"id": m[0], "content": m[1]} for m in matches],
    }


async def _do_add_detail(query_text: str) -> dict:
    """
    Append a detail line to an existing journal entry via FTS search.

    Input format: <entry description> | <detail to add>
    """
    if not query_text or '|' not in query_text:
        return {"intent": "add_detail", "error": "Format: add: <entry> | <detail>"}

    header_query, detail_to_add = [p.strip() for p in query_text.split('|', 1)]

    matches = await _fts_search_journal(header_query)

    if not matches:
        return {"intent": "add_detail", "query": header_query, "matches": 0}

    if len(matches) == 1:
        entry_id, content, body = matches[0]
        now = datetime.now().isoformat()
        new_body = (body or '') + '\n' + detail_to_add

        db = await get_db()
        await db.execute(
            "UPDATE gluons SET body = ?, updated_at = ? WHERE id = ?",
            [new_body, now, entry_id]
        )

        # Update FTS index
        fts_text = content + ' ' + new_body
        await db.execute(
            "DELETE FROM gluons_fts WHERE rowid = (SELECT rowid FROM gluons WHERE id = ?)",
            [entry_id]
        )
        await db.execute("""
            INSERT INTO gluons_fts (rowid, content)
            VALUES ((SELECT rowid FROM gluons WHERE id = ?), ?)
        """, [entry_id, fts_text])

        await db.commit()
        return {"intent": "add_detail", "added": True,
                "entry": {"id": entry_id, "content": content}, "detail": detail_to_add}

    return {
        "intent": "add_detail", "query": header_query,
        "matches": len(matches),
        "entries": [{"id": m[0], "content": m[1]} for m in matches],
    }


async def _do_delete(query_text: str) -> dict:
    """
    Find journal entries matching query for deletion.

    Single match returns confirmation_needed; multiple returns disambiguation list.
    """
    if not query_text:
        return {"intent": "delete", "error": "Usage: delete: <entry description>"}

    matches = await _fts_search_journal(query_text)

    if not matches:
        return {"intent": "delete", "query": query_text, "matches": 0}

    if len(matches) == 1:
        entry_id, content, body = matches[0]
        return {"intent": "delete", "query": query_text,
                "confirmation_needed": True,
                "entry": {"id": entry_id, "content": content}}

    return {
        "intent": "delete", "query": query_text,
        "matches": len(matches),
        "entries": [{"id": m[0], "content": m[1]} for m in matches],
    }


async def _do_confirm_delete(entry_id: str) -> dict:
    """Actually delete a journal entry by ID."""
    db = await get_db()

    cursor = await db.execute(
        "SELECT content, rowid FROM gluons WHERE id = ? AND type = 'journal_entry'",
        [entry_id]
    )
    row = await cursor.fetchone()
    if not row:
        return {"intent": "delete", "error": "Entry not found"}

    content, gluon_rowid = row

    try:
        await db.execute("DELETE FROM gluons_fts WHERE rowid = ?", [gluon_rowid])
    except Exception:
        pass

    await db.execute(
        "DELETE FROM links WHERE source_id = ? OR target_id = ?",
        [entry_id, entry_id]
    )
    await db.execute("DELETE FROM gluons WHERE id = ?", [entry_id])
    await db.commit()

    return {"intent": "delete", "deleted": True, "content": content}


async def _do_capture(text: str, captured_via: str = "web") -> dict:
    """Classify text and create journal entries."""
    classifications = await classify_structured(text)

    entries = []
    for cls in classifications:
        entry = await _create_journal_from_classification(cls, captured_via=captured_via)
        entries.append(entry)

    return {"intent": "capture", "entries": entries, "count": len(entries)}


def _parse_intent(text: str) -> tuple[str, str]:
    """
    Parse intent prefix from text. Returns (intent, remaining_text).

    Intents: query (?), done, add, delete, or capture (default).
    """
    if text.startswith("?"):
        return "query", text
    elif text.startswith("done:") or text.lower().startswith("done "):
        remainder = text[5:].strip() if text.startswith("done:") else text[4:].strip()
        return "done", remainder
    elif text.startswith("add:") or text.lower().startswith("add "):
        remainder = text[4:].strip() if text.startswith("add:") else text[3:].strip()
        return "add", remainder
    elif text.startswith("delete:") or text.lower().startswith("delete "):
        remainder = text[7:].strip() if text.startswith("delete:") else text[6:].strip()
        return "delete", remainder
    else:
        return "capture", text


# --- WhatsApp Reply Formatting ---
# These functions format _do_* results into WhatsApp messages.


def _format_query_reply(result: dict) -> str:
    """Format query result as a WhatsApp message."""
    if "error" in result:
        return f"❓ {result['error']}\nTry: ?tasks, ?ideas, ?social, ?admin, ?inbox"

    entries = result["entries"]
    category = result["category"]

    if not entries:
        time_desc = "today" if result["time_filter"] == "today" else "in your journal"
        return f"📭 No {category} entries {time_desc}"

    lines = [f"📋 {category.capitalize()} entries ({len(entries)}):\n"]

    for e in entries:
        if category == "task":
            # Parse sub-tasks for progress display
            sub_done, sub_total = 0, 0
            if e.get("body"):
                for line in e["body"].split('\n'):
                    trimmed = line.strip()
                    if trimmed.startswith('[ ]'):
                        sub_total += 1
                    elif trimmed.startswith('[x]'):
                        sub_done += 1
                        sub_total += 1
                    elif trimmed == '---':
                        break

            if e["completed"] == 1:
                status = "✅"
            elif sub_total:
                status = f"[{sub_done}/{sub_total}]"
            else:
                status = "☐"
            lines.append(f"{status} {e['content']}")
        else:
            lines.append(f"• {e['content']}")

    reply = "\n".join(lines[:15])
    if len(entries) > 10:
        reply += f"\n\n... and {len(entries) - 10} more"
    return reply


def _format_mark_done_reply(result: dict) -> str:
    if "error" in result:
        return f"❌ {result['error']}"
    if result.get("matches") == 0:
        return f"❌ No incomplete tasks matching: {result['query']}"
    if result.get("completed"):
        return f"✅ Marked complete: {result['entry']['content']}"
    # Disambiguation
    lines = ["❓ Multiple tasks found. Which one?\n"]
    for i, e in enumerate(result["entries"], 1):
        lines.append(f"{i}. {e['content']}")
    return "\n".join(lines)


def _format_add_detail_reply(result: dict) -> str:
    if "error" in result:
        return f"❓ {result['error']}"
    if result.get("matches") == 0:
        return f"❌ No entries matching: {result['query']}"
    if result.get("added"):
        return f"✅ Added detail to: {result['entry']['content']}\n• {result['detail']}"
    lines = ["❓ Multiple entries found. Which one?\n"]
    for i, e in enumerate(result["entries"], 1):
        lines.append(f"{i}. {e['content']}")
    return "\n".join(lines)


def _format_delete_reply(result: dict) -> str:
    if "error" in result:
        return f"❌ {result['error']}"
    if result.get("matches") == 0:
        return f"❌ No entries matching: {result['query']}"
    if result.get("deleted"):
        return f"✅ Deleted: {result['content']}"
    if result.get("confirmation_needed"):
        return f"⚠️ Delete: {result['entry']['content']}?\nReply 'yes' to confirm"
    lines = ["❓ Multiple entries found. Which one to delete?\n"]
    for i, e in enumerate(result["entries"], 1):
        lines.append(f"{i}. {e['content']}")
    return "\n".join(lines)


# --- WhatsApp Handlers ---
# Thin wrappers: call _do_*, format reply, send via WhatsApp.


async def _send_reply(to: str, message: str):
    """Helper to send a WhatsApp reply."""
    client = get_whatsapp_client()
    if client.is_configured:
        await client.send_text_message(to, message)
    else:
        print(f"[WhatsApp REPLY (not sent)] {to}: {message}")


async def handle_query_intent(from_number: str, query_text: str):
    result = await _do_query(query_text)
    await _send_reply(from_number, _format_query_reply(result))


async def handle_mark_done(from_number: str, query_text: str):
    result = await _do_mark_done(query_text)
    await _send_reply(from_number, _format_mark_done_reply(result))


async def handle_add_detail(from_number: str, query_text: str):
    result = await _do_add_detail(query_text)
    await _send_reply(from_number, _format_add_detail_reply(result))


async def handle_delete_entry(from_number: str, query_text: str):
    result = await _do_delete(query_text)

    # Single match → use interactive buttons if available
    if result.get("confirmation_needed"):
        client = get_whatsapp_client()
        if client.is_configured:
            await client.send_interactive_buttons(
                to=from_number,
                body_text=f"⚠️ Delete this entry?\n\n{result['entry']['content']}",
                buttons=[
                    {"id": f"delete_confirm_{result['entry']['id']}", "title": "Yes, delete"},
                    {"id": "delete_cancel", "title": "Cancel"},
                ],
            )
            return

    await _send_reply(from_number, _format_delete_reply(result))


async def handle_button_response(from_number: str, button_id: str):
    """Handle interactive button clicks from WhatsApp."""
    if button_id.startswith("delete_confirm_"):
        entry_id = button_id.replace("delete_confirm_", "")
        result = await _do_confirm_delete(entry_id)
        await _send_reply(from_number, _format_delete_reply(result))

    elif button_id == "delete_cancel":
        await _send_reply(from_number, "❌ Deletion cancelled")

    else:
        print(f"[WhatsApp] Unknown button ID: {button_id}")


async def process_capture(from_number: str, text: str):
    """
    Process a captured note from WhatsApp.

    Classifies the message (may produce multiple items), creates journal
    entries for each, and sends a confirmation reply.
    """
    if not text.strip():
        return

    result = await _do_capture(text, captured_via="whatsapp")
    created = result["entries"]

    print(f"[WhatsApp] Classified into {len(created)} item(s)")

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
    Manual capture endpoint for testing all WhatsApp intents without WhatsApp.

    Supports the same intent routing as WhatsApp webhook:
    - ?tasks, ?ideas today → query entries
    - done: <query> → mark task complete
    - add: <query> | <detail> → append detail
    - delete: <query> → find entry for deletion
    - anything else → classify and create journal entries
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    text = request.text.strip()

    intent, remainder = _parse_intent(text)

    if intent == "query":
        return await _do_query(remainder)
    elif intent == "done":
        return await _do_mark_done(remainder)
    elif intent == "add":
        return await _do_add_detail(remainder)
    elif intent == "delete":
        return await _do_delete(remainder)
    else:
        return await _do_capture(remainder, captured_via="web")
