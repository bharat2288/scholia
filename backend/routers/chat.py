"""
Chat Router
===========
Simple single-model chat API for document analysis.

Simpler alternative to the Council for quick Q&A with documents.
Uses stateless API - client sends full conversation history with each request.

Endpoints:
- GET  /chat/models                    - List available models
- POST /chat/message                   - Send message (stateless)
- GET  /chat/conversations/{source_id} - List chats for source
- GET  /chat/conversation/{id}         - Get chat with messages
- DELETE /chat/conversation/{id}       - Delete chat
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid
import json

from database import get_db
from services.chat import ChatService, get_chat_models

router = APIRouter()


# ============================================================
# Models (Pydantic)
# ============================================================

class ChatMessage(BaseModel):
    """A single message in conversation history."""
    role: str  # 'user' | 'assistant'
    content: str


class ChatRequest(BaseModel):
    """Request to send a chat message."""
    model_id: str = "claude-sonnet"
    messages: List[ChatMessage]
    context: Optional[str] = None  # Document context
    context_type: Optional[str] = None  # 'selection' | 'full'
    source_id: Optional[str] = None  # Source being discussed
    source_type: Optional[str] = None  # 'document' | 'web' | 'thread' | 'media'
    conversation_id: Optional[str] = None  # Existing conversation to continue
    max_tokens: int = 12288


class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    model_id: str
    model: Optional[str] = None
    usage: Optional[dict] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    gluon_id: Optional[str] = None
    timestamp: datetime


class ModelInfo(BaseModel):
    """Information about an available model."""
    id: str
    name: str
    description: str
    model: str
    provider: str
    available: bool
    default: bool
    pricing: dict
    tier_hints: list[str] = []


class ConversationSummary(BaseModel):
    """Summary of a chat conversation."""
    id: str
    source_id: str
    title: Optional[str] = None
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationDetail(BaseModel):
    """Full conversation with messages."""
    id: str
    source_id: str
    title: Optional[str] = None
    messages: List[dict]
    created_at: datetime
    updated_at: datetime


# ============================================================
# Auto-Save Helper
# ============================================================

async def _auto_save_chat_gluon(
    db,
    conversation_id: str,
    source_id: Optional[str],
    user_question: str,
    assistant_response: str,
) -> Optional[str]:
    """
    Auto-save a chat exchange as a gluon note.

    On first exchange: creates a new gluon and links it to the conversation.
    On subsequent exchanges: appends the new Q&A to the existing gluon.

    Returns the gluon_id.
    """
    # Check if conversation already has a gluon_id
    cursor = await db.execute(
        "SELECT gluon_id FROM conversations WHERE id = ?",
        [conversation_id]
    )
    row = await cursor.fetchone()
    existing_gluon_id = row[0] if row else None

    # Get document title for the note prefix
    doc_title = "Document"
    if source_id:
        cursor = await db.execute(
            "SELECT title FROM sources WHERE id = ?",
            [source_id]
        )
        title_row = await cursor.fetchone()
        if title_row and title_row[0]:
            doc_title = title_row[0]

    # Format the new Q&A exchange
    new_exchange = f"**Q:** {user_question}\n\n{assistant_response}"

    now = datetime.now().isoformat()

    if not existing_gluon_id:
        # First exchange: create a new gluon
        gluon_id = str(uuid.uuid4())[:8]
        note_content = f"[Chat — {doc_title}]\n\n{new_exchange}"

        await db.execute("""
            INSERT INTO gluons (id, type, content, source_id, captured_via, created_at, updated_at)
            VALUES (?, 'note', ?, ?, 'chat', ?, ?)
        """, [gluon_id, note_content, source_id, now, now])

        # Index in FTS
        await db.execute("""
            INSERT INTO gluons_fts (rowid, content)
            SELECT rowid, content FROM gluons WHERE id = ?
        """, [gluon_id])

        # Link gluon to conversation
        await db.execute(
            "UPDATE conversations SET gluon_id = ? WHERE id = ?",
            [gluon_id, conversation_id]
        )
        await db.commit()
        return gluon_id

    else:
        # Subsequent exchange: append to existing gluon
        cursor = await db.execute(
            "SELECT content FROM gluons WHERE id = ?",
            [existing_gluon_id]
        )
        gluon_row = await cursor.fetchone()
        if not gluon_row:
            return existing_gluon_id

        updated_content = f"{gluon_row[0]}\n\n---\n\n{new_exchange}"

        await db.execute("""
            UPDATE gluons SET content = ?, updated_at = ? WHERE id = ?
        """, [updated_content, now, existing_gluon_id])

        # Update FTS (delete + re-insert)
        await db.execute("""
            DELETE FROM gluons_fts WHERE rowid = (SELECT rowid FROM gluons WHERE id = ?)
        """, [existing_gluon_id])
        await db.execute("""
            INSERT INTO gluons_fts (rowid, content)
            SELECT rowid, content FROM gluons WHERE id = ?
        """, [existing_gluon_id])

        await db.commit()
        return existing_gluon_id


# ============================================================
# Models Endpoint
# ============================================================

@router.get("/models", response_model=List[ModelInfo])
async def list_models():
    """
    List available chat models.
    Returns model info including availability (API key configured).
    """
    return [ModelInfo(**m) for m in get_chat_models()]


# ============================================================
# Chat Message Endpoint
# ============================================================

@router.post("/message", response_model=ChatResponse)
async def send_message(request: ChatRequest):
    """
    Send a chat message and get a response.

    This is a stateless API - the client sends the full conversation
    history with each request. The conversation is persisted on the
    server for history/retrieval but the API itself is stateless.
    """
    chat = ChatService(verbose=True)
    db = await get_db()

    # Validate model exists
    models = {m["id"]: m for m in get_chat_models()}
    if request.model_id not in models:
        raise HTTPException(status_code=400, detail=f"Unknown model: {request.model_id}")

    if not models[request.model_id]["available"]:
        raise HTTPException(
            status_code=400,
            detail=f"Model {request.model_id} not available (API key not configured)"
        )

    # Get or create conversation
    conversation_id = request.conversation_id
    now = datetime.now().isoformat()

    if not conversation_id and request.source_id:
        # Create new conversation
        conversation_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO conversations (id, source_id, conversation_type, created_at, updated_at)
            VALUES (?, ?, 'chat', ?, ?)
        """, [conversation_id, request.source_id, now, now])
        await db.commit()

    # Convert messages for the service
    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    # Look up source metadata for context-aware system prompt
    source_type = request.source_type
    source_title = None
    if request.source_id:
        cursor = await db.execute(
            "SELECT source_type, title FROM sources WHERE id = ?",
            [request.source_id]
        )
        source_row = await cursor.fetchone()
        if source_row:
            source_type = source_type or source_row[0]
            source_title = source_row[1]

    # Call the chat service
    result = await chat.chat(
        model_id=request.model_id,
        messages=messages,
        context=request.context,
        max_tokens=request.max_tokens,
        source_type=source_type,
        source_title=source_title,
    )

    # Save messages to database if we have a conversation
    message_id = None
    gluon_id = None
    if conversation_id and result.get("success"):
        # Save the last user message
        if messages:
            last_user_msg = messages[-1]
            user_msg_id = str(uuid.uuid4())[:8]
            await db.execute("""
                INSERT INTO council_messages
                (id, conversation_id, role, content, mode, model, context_type, created_at)
                VALUES (?, ?, ?, ?, 'chat', ?, ?, ?)
            """, [
                user_msg_id,
                conversation_id,
                last_user_msg["role"],
                last_user_msg["content"],
                request.model_id,
                request.context_type,
                now
            ])

        # Save assistant response
        message_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO council_messages
            (id, conversation_id, role, content, mode, model, usage, created_at)
            VALUES (?, ?, 'assistant', ?, 'chat', ?, ?, ?)
        """, [
            message_id,
            conversation_id,
            result.get("content") or "",
            request.model_id,
            json.dumps(result.get("usage")) if result.get("usage") else None,
            now
        ])

        # Update conversation timestamp
        await db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            [now, conversation_id]
        )
        await db.commit()

        # Auto-save conversation as gluon note
        gluon_id = await _auto_save_chat_gluon(
            db, conversation_id, request.source_id,
            messages[-1]["content"] if messages else "",
            result.get("content") or ""
        )

    return ChatResponse(
        success=result.get("success", False),
        content=result.get("content"),
        error=result.get("error"),
        model_id=request.model_id,
        model=result.get("model"),
        usage=result.get("usage"),
        conversation_id=conversation_id,
        message_id=message_id,
        gluon_id=gluon_id,
        timestamp=datetime.fromisoformat(result.get("timestamp", now))
    )


# ============================================================
# Conversation Endpoints
# ============================================================

@router.get("/conversations/{source_id}", response_model=List[ConversationSummary])
async def list_conversations(source_id: str):
    """List all chat conversations for a source."""
    db = await get_db()

    cursor = await db.execute("""
        SELECT c.id, c.source_id, c.title, c.created_at, c.updated_at,
               (SELECT COUNT(*) FROM council_messages WHERE conversation_id = c.id) as message_count
        FROM conversations c
        WHERE c.source_id = ?
          AND (c.conversation_type = 'chat' OR c.conversation_type IS NULL)
        ORDER BY c.updated_at DESC
    """, [source_id])
    rows = await cursor.fetchall()

    return [
        ConversationSummary(
            id=row[0],
            source_id=row[1],
            title=row[2],
            created_at=datetime.fromisoformat(row[3]),
            updated_at=datetime.fromisoformat(row[4]),
            message_count=row[5]
        )
        for row in rows
    ]


@router.get("/conversation/{conversation_id}", response_model=ConversationDetail)
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
        SELECT id, role, content, model, usage, created_at
        FROM council_messages
        WHERE conversation_id = ?
        ORDER BY created_at ASC
    """, [conversation_id])
    msg_rows = await cursor.fetchall()

    messages = [
        {
            "id": row[0],
            "role": row[1],
            "content": row[2],
            "model": row[3],
            "usage": json.loads(row[4]) if row[4] else None,
            "created_at": row[5]
        }
        for row in msg_rows
    ]

    return ConversationDetail(
        id=conv_row[0],
        source_id=conv_row[1],
        title=conv_row[2],
        messages=messages,
        created_at=datetime.fromisoformat(conv_row[3]),
        updated_at=datetime.fromisoformat(conv_row[4])
    )


@router.delete("/conversation/{conversation_id}")
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

    # Delete (messages cascade)
    await db.execute("DELETE FROM conversations WHERE id = ?", [conversation_id])
    await db.commit()

    return {"status": "deleted", "id": conversation_id}
