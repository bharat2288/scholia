"""
Council Router
==============
API endpoints for the LLM Council system.

Provides multi-model analysis of document content with:
- Presets (customizable analysis prompts)
- Single model queries
- Council deliberation (3 models + synthesis)
- SSE streaming for real-time progress
- Conversation persistence
- Save to notes integration

Endpoints:
- GET    /council/presets              - List all presets
- POST   /council/presets              - Create new preset
- GET    /council/presets/:id          - Get single preset
- PUT    /council/presets/:id          - Update preset
- DELETE /council/presets/:id          - Delete preset
- POST   /council/presets/:id/duplicate - Duplicate preset

- GET    /council/models               - List available models

- POST   /council/query                - Non-streaming query
- GET    /council/query/stream         - SSE streaming query

- GET    /council/conversations        - List conversations for source
- GET    /council/conversations/:id    - Get conversation with messages
- DELETE /council/conversations/:id    - Delete conversation
- POST   /council/messages/:id/save    - Save message as note
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional, List
from datetime import datetime
import uuid
import json
import asyncio

from database import get_db
from models.council import (
    Preset, PresetCreate, PresetUpdate,
    Conversation, ConversationCreate, ConversationSummary, ConversationWithMessages,
    Message, MessageCreate, MessageRole,
    QueryRequest, QueryResponse, QueryMode, ContextType,
    ModelInfo
)
from services.council import CouncilService, get_available_models

router = APIRouter()


# ============================================================
# Presets
# ============================================================

@router.get("/presets", response_model=List[Preset])
async def list_presets(source_type: Optional[str] = Query(None)):
    """
    List all presets, ordered by sort_order.
    System presets first, then user presets.

    Optional source_type filter: only returns presets applicable to that source type.
    Presets with source_types=NULL are shown for all source types.
    """
    db = await get_db()
    cursor = await db.execute("""
        SELECT id, name, description, prompt, model, max_tokens,
               is_system, sort_order, show_as_quick_action, source_types,
               prompt_full_doc, created_at, updated_at
        FROM council_presets
        ORDER BY is_system DESC, sort_order ASC, name ASC
    """)
    rows = await cursor.fetchall()

    presets = []
    for row in rows:
        # Parse source_types JSON
        source_types_raw = row[9]
        source_types = json.loads(source_types_raw) if source_types_raw else None

        # Filter by source_type if provided
        if source_type and source_types is not None:
            if source_type not in source_types:
                continue

        presets.append(Preset(
            id=row[0],
            name=row[1],
            description=row[2],
            prompt=row[3],
            model=row[4],
            max_tokens=row[5],
            is_system=bool(row[6]),
            sort_order=row[7],
            show_as_quick_action=bool(row[8]),
            source_types=source_types,
            prompt_full_doc=row[10],
            created_at=datetime.fromisoformat(row[11]),
            updated_at=datetime.fromisoformat(row[12])
        ))

    return presets


@router.post("/presets", response_model=Preset)
async def create_preset(data: PresetCreate):
    """Create a new user preset."""
    db = await get_db()

    preset_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Get max sort_order for user presets
    cursor = await db.execute(
        "SELECT MAX(sort_order) FROM council_presets WHERE is_system = 0"
    )
    row = await cursor.fetchone()
    sort_order = (row[0] or 0) + 1

    await db.execute("""
        INSERT INTO council_presets
        (id, name, description, prompt, model, max_tokens, is_system, sort_order,
         show_as_quick_action, source_types, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?, ?)
    """, [
        preset_id,
        data.name,
        data.description,
        data.prompt,
        data.model,
        data.max_tokens,
        sort_order,
        None,  # source_types: NULL = all types
        now,
        now
    ])
    await db.commit()

    return Preset(
        id=preset_id,
        name=data.name,
        description=data.description,
        prompt=data.prompt,
        model=data.model,
        max_tokens=data.max_tokens,
        is_system=False,
        sort_order=sort_order,
        show_as_quick_action=False,
        source_types=None,
        prompt_full_doc=None,
        created_at=datetime.fromisoformat(now),
        updated_at=datetime.fromisoformat(now)
    )


@router.get("/presets/{preset_id}", response_model=Preset)
async def get_preset(preset_id: str):
    """Get a single preset by ID."""
    db = await get_db()
    cursor = await db.execute("""
        SELECT id, name, description, prompt, model, max_tokens,
               is_system, sort_order, show_as_quick_action, source_types,
               prompt_full_doc, created_at, updated_at
        FROM council_presets WHERE id = ?
    """, [preset_id])
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")

    source_types = json.loads(row[9]) if row[9] else None

    return Preset(
        id=row[0],
        name=row[1],
        description=row[2],
        prompt=row[3],
        model=row[4],
        max_tokens=row[5],
        is_system=bool(row[6]),
        sort_order=row[7],
        show_as_quick_action=bool(row[8]),
        source_types=source_types,
        prompt_full_doc=row[10],
        created_at=datetime.fromisoformat(row[11]),
        updated_at=datetime.fromisoformat(row[12])
    )


@router.put("/presets/{preset_id}", response_model=Preset)
async def update_preset(preset_id: str, data: PresetUpdate):
    """
    Update a preset.
    System presets: only show_as_quick_action can be changed.
    User presets: all fields can be changed.
    """
    db = await get_db()

    # Check if preset exists
    cursor = await db.execute(
        "SELECT is_system FROM council_presets WHERE id = ?",
        [preset_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")

    is_system = bool(row[0])

    # Build update query
    updates = []
    values = []

    # For system presets, only allow show_as_quick_action
    if is_system:
        if data.show_as_quick_action is not None:
            updates.append("show_as_quick_action = ?")
            values.append(1 if data.show_as_quick_action else 0)
        # Check if user tried to update other fields
        if any([data.name, data.description, data.prompt, data.model, data.max_tokens]):
            raise HTTPException(
                status_code=403,
                detail="System presets cannot be edited. Only quick action toggle can be changed."
            )
    else:
        # User presets: allow all fields
        if data.name is not None:
            updates.append("name = ?")
            values.append(data.name)
        if data.description is not None:
            updates.append("description = ?")
            values.append(data.description)
        if data.prompt is not None:
            updates.append("prompt = ?")
            values.append(data.prompt)
        if data.model is not None:
            updates.append("model = ?")
            values.append(data.model)
        if data.max_tokens is not None:
            updates.append("max_tokens = ?")
            values.append(data.max_tokens)
        if data.show_as_quick_action is not None:
            updates.append("show_as_quick_action = ?")
            values.append(1 if data.show_as_quick_action else 0)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(preset_id)

    await db.execute(
        f"UPDATE council_presets SET {', '.join(updates)} WHERE id = ?",
        values
    )
    await db.commit()

    return await get_preset(preset_id)


@router.delete("/presets/{preset_id}")
async def delete_preset(preset_id: str):
    """
    Delete a preset.
    System presets cannot be deleted.
    """
    db = await get_db()

    # Check if preset exists and is not system
    cursor = await db.execute(
        "SELECT is_system FROM council_presets WHERE id = ?",
        [preset_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")
    if row[0]:
        raise HTTPException(status_code=403, detail="System presets cannot be deleted")

    await db.execute("DELETE FROM council_presets WHERE id = ?", [preset_id])
    await db.commit()

    return {"status": "deleted", "id": preset_id}


@router.post("/presets/{preset_id}/duplicate", response_model=Preset)
async def duplicate_preset(preset_id: str, name: Optional[str] = Query(None)):
    """
    Duplicate a preset (system or user).
    Creates an editable copy with a new ID.
    """
    db = await get_db()

    # Get original preset
    cursor = await db.execute("""
        SELECT name, description, prompt, model, max_tokens, show_as_quick_action,
               source_types, prompt_full_doc
        FROM council_presets WHERE id = ?
    """, [preset_id])
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")

    # Create duplicate
    new_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    new_name = name or f"{row[0]} (Copy)"
    show_quick = row[5] if row[5] is not None else 0
    source_types_raw = row[6]
    source_types = json.loads(source_types_raw) if source_types_raw else None

    # Get max sort_order
    cursor = await db.execute(
        "SELECT MAX(sort_order) FROM council_presets WHERE is_system = 0"
    )
    sort_row = await cursor.fetchone()
    sort_order = (sort_row[0] or 0) + 1

    await db.execute("""
        INSERT INTO council_presets
        (id, name, description, prompt, prompt_full_doc, model, max_tokens,
         is_system, sort_order, show_as_quick_action, source_types, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
    """, [
        new_id,
        new_name,
        row[1],  # description
        row[2],  # prompt
        row[7],  # prompt_full_doc
        row[3],  # model
        row[4],  # max_tokens
        sort_order,
        show_quick,
        source_types_raw,  # Keep raw JSON
        now,
        now
    ])
    await db.commit()

    return Preset(
        id=new_id,
        name=new_name,
        description=row[1],
        prompt=row[2],
        model=row[3],
        max_tokens=row[4],
        is_system=False,
        sort_order=sort_order,
        show_as_quick_action=bool(show_quick),
        source_types=source_types,
        prompt_full_doc=row[7],
        created_at=datetime.fromisoformat(now),
        updated_at=datetime.fromisoformat(now)
    )


# ============================================================
# Models
# ============================================================

@router.get("/models", response_model=List[ModelInfo])
async def list_models():
    """List available models and their status."""
    return [ModelInfo(**m) for m in get_available_models()]


# ============================================================
# Query
# ============================================================

@router.post("/query", response_model=QueryResponse)
async def query(data: QueryRequest):
    """
    Execute a council query (non-streaming).

    - mode='single': Query one model
    - mode='council': All 3 models deliberate, chairman synthesizes
    """
    council = CouncilService(verbose=True)
    db = await get_db()

    # Get or create conversation
    conversation_id = data.conversation_id
    if not conversation_id and data.source_id:
        conversation_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        await db.execute("""
            INSERT INTO conversations (id, source_id, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, [conversation_id, data.source_id, now, now])
        await db.commit()

    # Save user message
    user_message_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    await db.execute("""
        INSERT INTO council_messages
        (id, conversation_id, role, content, mode, model, preset_id, context_type, context_offsets, created_at)
        VALUES (?, ?, 'user', ?, ?, ?, ?, ?, ?, ?)
    """, [
        user_message_id,
        conversation_id,
        data.query,
        data.mode.value,
        data.model if data.mode == QueryMode.SINGLE else None,
        data.preset_id,
        data.context_type.value if data.context_type else None,
        json.dumps(data.context_offsets) if data.context_offsets else None,
        now
    ])
    await db.commit()

    # Execute query
    if data.mode == QueryMode.COUNCIL:
        result = await council.deliberate(data.query, data.context)
        content = result.get("synthesis")
        perspectives = result.get("perspectives")
    else:
        result = await council.query_single(data.query, data.context, data.model)
        content = result.get("content")
        perspectives = None

    # Save assistant message
    assistant_message_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    await db.execute("""
        INSERT INTO council_messages
        (id, conversation_id, role, content, mode, model, preset_id, perspectives, usage, created_at)
        VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?)
    """, [
        assistant_message_id,
        conversation_id,
        content or "",
        data.mode.value,
        data.model if data.mode == QueryMode.SINGLE else None,
        data.preset_id,
        json.dumps(perspectives) if perspectives else None,
        json.dumps(result.get("usage")) if result.get("usage") else None,
        now
    ])

    # Update conversation timestamp
    await db.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        [now, conversation_id]
    )
    await db.commit()

    return QueryResponse(
        query=data.query,
        context=data.context,
        mode=data.mode,
        model=data.model if data.mode == QueryMode.SINGLE else None,
        content=content if data.mode == QueryMode.SINGLE else None,
        synthesis=content if data.mode == QueryMode.COUNCIL else None,
        perspectives=perspectives,
        success=result.get("success", False),
        error=result.get("error"),
        failed_providers=result.get("failed_providers"),
        timestamp=datetime.fromisoformat(result.get("timestamp", now)),
        usage=result.get("usage"),
        conversation_id=conversation_id,
        message_id=assistant_message_id
    )


@router.get("/query/stream")
async def query_stream(
    context: str,
    query: str,
    source_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    preset_id: Optional[str] = None,
    context_type: Optional[str] = "selection"
):
    """
    Execute a council deliberation with SSE streaming.
    Returns real-time progress as models complete.
    """
    async def event_generator():
        council = CouncilService(verbose=True)
        db = await get_db()

        # Get or create conversation
        conv_id = conversation_id
        if not conv_id and source_id:
            conv_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()
            await db.execute("""
                INSERT INTO conversations (id, source_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, [conv_id, source_id, now, now])
            await db.commit()

        # Save user message
        user_message_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        await db.execute("""
            INSERT INTO council_messages
            (id, conversation_id, role, content, mode, preset_id, context_type, created_at)
            VALUES (?, ?, 'user', ?, 'council', ?, ?, ?)
        """, [
            user_message_id,
            conv_id,
            query,
            preset_id,
            context_type,
            now
        ])
        await db.commit()

        # Stream deliberation
        async for event in council.deliberate_streaming(query, context):
            yield f"event: {event['event']}\n"
            yield f"data: {json.dumps(event['data'])}\n\n"

            # On complete, save assistant message
            if event["event"] == "complete":
                data = event["data"]
                assistant_message_id = str(uuid.uuid4())[:8]
                now = datetime.now().isoformat()

                await db.execute("""
                    INSERT INTO council_messages
                    (id, conversation_id, role, content, mode, perspectives, usage, created_at)
                    VALUES (?, ?, 'assistant', ?, 'council', ?, ?, ?)
                """, [
                    assistant_message_id,
                    conv_id,
                    data.get("synthesis") or "",
                    json.dumps(data.get("perspectives")),
                    json.dumps(data.get("usage")),
                    now
                ])

                await db.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    [now, conv_id]
                )
                await db.commit()

                # Send final message with IDs
                yield f"event: saved\n"
                yield f"data: {json.dumps({'conversation_id': conv_id, 'message_id': assistant_message_id})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ============================================================
# Conversations
# ============================================================

@router.get("/conversations")
async def list_conversations(source_id: Optional[str] = Query(None)):
    """
    List conversations.

    When source_id is provided: returns conversations for that source (Conversation model).
    When omitted: returns ALL conversations with source info and preview (ConversationSummary model).
    """
    db = await get_db()

    if source_id:
        # Per-source listing with first message preview
        cursor = await db.execute("""
            SELECT c.id, c.source_id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM council_messages WHERE conversation_id = c.id) as message_count,
                   (SELECT content FROM council_messages
                    WHERE conversation_id = c.id AND role = 'user'
                    ORDER BY created_at ASC LIMIT 1) as first_message
            FROM conversations c
            WHERE c.source_id = ?
            ORDER BY c.updated_at DESC
        """, [source_id])
        rows = await cursor.fetchall()

        return [
            Conversation(
                id=row[0],
                source_id=row[1],
                title=row[2],
                created_at=datetime.fromisoformat(row[3]),
                updated_at=datetime.fromisoformat(row[4]),
                message_count=row[5],
                first_message_preview=row[6][:100] + "..." if row[6] and len(row[6]) > 100 else row[6],
            )
            for row in rows
        ]
    else:
        # Cross-source listing — join with sources for title/author, include preview
        cursor = await db.execute("""
            SELECT c.id, c.source_id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM council_messages WHERE conversation_id = c.id) as message_count,
                   s.title as source_title,
                   s.author_display as source_author,
                   (SELECT content FROM council_messages
                    WHERE conversation_id = c.id AND role = 'user'
                    ORDER BY created_at ASC LIMIT 1) as first_message
            FROM conversations c
            LEFT JOIN sources s ON c.source_id = s.id
            ORDER BY c.updated_at DESC
        """)
        rows = await cursor.fetchall()

        return [
            ConversationSummary(
                id=row[0],
                source_id=row[1],
                title=row[2],
                created_at=datetime.fromisoformat(row[3]),
                updated_at=datetime.fromisoformat(row[4]),
                message_count=row[5],
                source_title=row[6],
                source_author=row[7],
                first_message_preview=row[8][:100] + "..." if row[8] and len(row[8]) > 100 else row[8],
            )
            for row in rows
        ]


@router.get("/conversations/{conversation_id}", response_model=ConversationWithMessages)
async def get_conversation(conversation_id: str):
    """Get a conversation with all its messages."""
    db = await get_db()

    # Get conversation
    cursor = await db.execute("""
        SELECT id, source_id, title, created_at, updated_at
        FROM conversations WHERE id = ?
    """, [conversation_id])
    conv_row = await cursor.fetchone()

    if not conv_row:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Get messages
    cursor = await db.execute("""
        SELECT id, conversation_id, role, content, mode, model, preset_id,
               context_type, context_offsets, perspectives, usage, created_at
        FROM council_messages
        WHERE conversation_id = ?
        ORDER BY created_at ASC
    """, [conversation_id])
    msg_rows = await cursor.fetchall()

    messages = [
        Message(
            id=row[0],
            conversation_id=row[1],
            role=MessageRole(row[2]),
            content=row[3],
            mode=QueryMode(row[4]) if row[4] else None,
            model=row[5],
            preset_id=row[6],
            context_type=ContextType(row[7]) if row[7] else None,
            context_offsets=json.loads(row[8]) if row[8] else None,
            perspectives=json.loads(row[9]) if row[9] else None,
            usage=json.loads(row[10]) if row[10] else None,
            created_at=datetime.fromisoformat(row[11])
        )
        for row in msg_rows
    ]

    return ConversationWithMessages(
        id=conv_row[0],
        source_id=conv_row[1],
        title=conv_row[2],
        created_at=datetime.fromisoformat(conv_row[3]),
        updated_at=datetime.fromisoformat(conv_row[4]),
        message_count=len(messages),
        messages=messages
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation and all its messages."""
    db = await get_db()

    # Check exists
    cursor = await db.execute(
        "SELECT id FROM conversations WHERE id = ?",
        [conversation_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Messages will cascade delete
    await db.execute("DELETE FROM conversations WHERE id = ?", [conversation_id])
    await db.commit()

    return {"status": "deleted", "id": conversation_id}


# ============================================================
# Save as Note
# ============================================================

@router.post("/messages/{message_id}/save")
async def save_message_as_note(
    message_id: str,
    source_id: Optional[str] = Query(None)
):
    """
    Save a council message as a gluon (note).
    Creates a note linked to the source.
    """
    db = await get_db()

    # Get message with mode info
    cursor = await db.execute("""
        SELECT m.content, c.source_id, m.mode, m.model
        FROM council_messages m
        JOIN conversations c ON m.conversation_id = c.id
        WHERE m.id = ? AND m.role = 'assistant'
    """, [message_id])
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Message not found or not an assistant message")

    content = row[0]
    msg_source_id = source_id or row[1]
    mode = row[2]
    model = row[3]

    if not content:
        raise HTTPException(status_code=400, detail="Message has no content")

    # Create gluon
    gluon_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Prefix based on message source type
    if mode == 'council':
        note_content = f"[Council Analysis]\n\n{content}"
    elif mode == 'chat' and model:
        note_content = f"[AI Analysis - {model}]\n\n{content}"
    else:
        note_content = f"[AI Analysis]\n\n{content}"

    await db.execute("""
        INSERT INTO gluons (id, type, content, source_id, created_at, updated_at)
        VALUES (?, 'note', ?, ?, ?, ?)
    """, [gluon_id, note_content, msg_source_id, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [gluon_id])

    await db.commit()

    return {
        "status": "saved",
        "gluon_id": gluon_id,
        "source_id": msg_source_id
    }
