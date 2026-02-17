"""
Research Sessions Router
========================
Chat-centric research with multiple sources as context.

Phase 1: Basic CRUD for sessions and sources, simple context assembly.
Future: RLM integration, Python REPL, sub-LLM calls.

Endpoints:
- POST /sessions                           - Create research session
- GET  /sessions                           - List sessions
- GET  /sessions/{id}                      - Get session with sources
- PATCH /sessions/{id}                     - Update session (title, description)
- DELETE /sessions/{id}                    - Delete session
- POST /sessions/{id}/sources              - Add source to session
- DELETE /sessions/{id}/sources/{source_id} - Remove source from session
- POST /sessions/{id}/chat                 - Send message to session
- GET  /sessions/{id}/messages             - Get conversation history
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from pathlib import Path
import uuid
import json

from database import get_db
from services.chat import ChatService, get_chat_models
from services.rlm_agent import RLMAgent, run_rlm_query, run_rlm_query_streaming
from services.rlm_v2_engine import run_rlm_v2_streaming

router = APIRouter()


# ============================================================
# Models (Pydantic)
# ============================================================

class SessionCreate(BaseModel):
    """Request to create a new research session."""
    title: str
    description: Optional[str] = None


class SessionUpdate(BaseModel):
    """Request to update a session."""
    title: Optional[str] = None
    description: Optional[str] = None


class SessionSummary(BaseModel):
    """Summary of a research session for list view."""
    id: str
    title: str
    description: Optional[str] = None
    source_count: int
    message_count: int
    created_at: datetime
    updated_at: datetime


class SourceBrief(BaseModel):
    """Brief source info for session context."""
    id: str
    title: str
    source_type: str
    author_display: Optional[str] = None
    year: Optional[int] = None
    context_type: str  # 'full', 'excerpt', 'highlights', 'notes'
    added_at: datetime


class SessionDetail(BaseModel):
    """Full session detail with sources."""
    id: str
    title: str
    description: Optional[str] = None
    sources: List[SourceBrief]
    message_count: int
    created_at: datetime
    updated_at: datetime


class AddSourceRequest(BaseModel):
    """Request to add a source to a session."""
    source_id: str
    context_type: str = "full"  # 'full', 'excerpt', 'highlights', 'notes'


class ChatMessage(BaseModel):
    """A single message in conversation history."""
    role: str  # 'user' | 'assistant'
    content: str


class SessionChatRequest(BaseModel):
    """Request to send a message in a session."""
    model_id: str = "claude-sonnet"
    messages: List[ChatMessage]
    max_tokens: int = 12288


class SessionChatResponse(BaseModel):
    """Response from session chat endpoint."""
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    model_id: str
    model: Optional[str] = None
    usage: Optional[dict] = None
    message_id: Optional[str] = None
    context_snapshot: Optional[dict] = None  # Which sources were in context
    timestamp: datetime


class MessageDetail(BaseModel):
    """A message from session history."""
    id: str
    role: str
    content: str
    model_id: Optional[str] = None
    usage: Optional[dict] = None
    context_snapshot: Optional[dict] = None
    created_at: datetime


# ============================================================
# Session CRUD Endpoints
# ============================================================

@router.post("", response_model=SessionDetail)
async def create_session(request: SessionCreate):
    """Create a new research session."""
    db = await get_db()
    now = datetime.now().isoformat()
    session_id = str(uuid.uuid4())[:8]

    await db.execute("""
        INSERT INTO research_sessions (id, title, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
    """, [session_id, request.title, request.description, now, now])
    await db.commit()

    return SessionDetail(
        id=session_id,
        title=request.title,
        description=request.description,
        sources=[],
        message_count=0,
        created_at=datetime.fromisoformat(now),
        updated_at=datetime.fromisoformat(now)
    )


@router.get("", response_model=List[SessionSummary])
async def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """List all research sessions, ordered by most recent activity."""
    db = await get_db()

    cursor = await db.execute("""
        SELECT
            rs.id,
            rs.title,
            rs.description,
            rs.created_at,
            rs.updated_at,
            (SELECT COUNT(*) FROM session_sources WHERE session_id = rs.id) as source_count,
            (SELECT COUNT(*) FROM session_messages WHERE session_id = rs.id) as message_count
        FROM research_sessions rs
        ORDER BY rs.updated_at DESC
        LIMIT ? OFFSET ?
    """, [limit, offset])
    rows = await cursor.fetchall()

    return [
        SessionSummary(
            id=row[0],
            title=row[1],
            description=row[2],
            created_at=datetime.fromisoformat(row[3]),
            updated_at=datetime.fromisoformat(row[4]),
            source_count=row[5],
            message_count=row[6]
        )
        for row in rows
    ]


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str):
    """Get a session with its sources."""
    db = await get_db()

    # Get session
    cursor = await db.execute("""
        SELECT id, title, description, created_at, updated_at
        FROM research_sessions WHERE id = ?
    """, [session_id])
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get sources
    cursor = await db.execute("""
        SELECT
            s.id, s.title, s.source_type, s.author_display, s.year,
            ss.context_type, ss.added_at
        FROM session_sources ss
        JOIN sources s ON s.id = ss.source_id
        WHERE ss.session_id = ?
        ORDER BY ss.added_at ASC
    """, [session_id])
    source_rows = await cursor.fetchall()

    # Get message count
    cursor = await db.execute(
        "SELECT COUNT(*) FROM session_messages WHERE session_id = ?",
        [session_id]
    )
    message_count = (await cursor.fetchone())[0]

    return SessionDetail(
        id=row[0],
        title=row[1],
        description=row[2],
        sources=[
            SourceBrief(
                id=s[0],
                title=s[1],
                source_type=s[2],
                author_display=s[3],
                year=s[4],
                context_type=s[5],
                added_at=datetime.fromisoformat(s[6])
            )
            for s in source_rows
        ],
        message_count=message_count,
        created_at=datetime.fromisoformat(row[3]),
        updated_at=datetime.fromisoformat(row[4])
    )


@router.patch("/{session_id}", response_model=SessionDetail)
async def update_session(session_id: str, request: SessionUpdate):
    """Update session title or description."""
    db = await get_db()

    # Check exists
    cursor = await db.execute(
        "SELECT id FROM research_sessions WHERE id = ?",
        [session_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Session not found")

    # Build update
    updates = []
    params = []
    if request.title is not None:
        updates.append("title = ?")
        params.append(request.title)
    if request.description is not None:
        updates.append("description = ?")
        params.append(request.description)

    if updates:
        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(session_id)

        await db.execute(f"""
            UPDATE research_sessions
            SET {', '.join(updates)}
            WHERE id = ?
        """, params)
        await db.commit()

    # Return updated session
    return await get_session(session_id)


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and all its data (sources links, messages)."""
    db = await get_db()

    # Check exists
    cursor = await db.execute(
        "SELECT id FROM research_sessions WHERE id = ?",
        [session_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Session not found")

    # Delete (cascades to session_sources and session_messages)
    await db.execute("DELETE FROM research_sessions WHERE id = ?", [session_id])
    await db.commit()

    return {"status": "deleted", "id": session_id}


# ============================================================
# Session Sources Endpoints
# ============================================================

@router.post("/{session_id}/sources", response_model=SourceBrief)
async def add_source_to_session(session_id: str, request: AddSourceRequest):
    """Add a source to a session."""
    db = await get_db()

    # Check session exists
    cursor = await db.execute(
        "SELECT id FROM research_sessions WHERE id = ?",
        [session_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Session not found")

    # Check source exists
    cursor = await db.execute(
        "SELECT id, title, source_type, author_display, year FROM sources WHERE id = ?",
        [request.source_id]
    )
    source_row = await cursor.fetchone()
    if not source_row:
        raise HTTPException(status_code=404, detail="Source not found")

    # Check not already added
    cursor = await db.execute(
        "SELECT session_id FROM session_sources WHERE session_id = ? AND source_id = ?",
        [session_id, request.source_id]
    )
    if await cursor.fetchone():
        raise HTTPException(status_code=400, detail="Source already in session")

    # Add link
    now = datetime.now().isoformat()
    await db.execute("""
        INSERT INTO session_sources (session_id, source_id, context_type, added_at)
        VALUES (?, ?, ?, ?)
    """, [session_id, request.source_id, request.context_type, now])

    # Update session timestamp
    await db.execute(
        "UPDATE research_sessions SET updated_at = ? WHERE id = ?",
        [now, session_id]
    )
    await db.commit()

    return SourceBrief(
        id=source_row[0],
        title=source_row[1],
        source_type=source_row[2],
        author_display=source_row[3],
        year=source_row[4],
        context_type=request.context_type,
        added_at=datetime.fromisoformat(now)
    )


@router.delete("/{session_id}/sources/{source_id}")
async def remove_source_from_session(session_id: str, source_id: str):
    """Remove a source from a session."""
    db = await get_db()

    # Check link exists
    cursor = await db.execute(
        "SELECT session_id FROM session_sources WHERE session_id = ? AND source_id = ?",
        [session_id, source_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Source not in session")

    # Remove link
    await db.execute(
        "DELETE FROM session_sources WHERE session_id = ? AND source_id = ?",
        [session_id, source_id]
    )

    # Update session timestamp
    await db.execute(
        "UPDATE research_sessions SET updated_at = ? WHERE id = ?",
        [datetime.now().isoformat(), session_id]
    )
    await db.commit()

    return {"status": "removed", "session_id": session_id, "source_id": source_id}


# ============================================================
# Session Chat Endpoints
# ============================================================

async def _assemble_context(db, session_id: str) -> tuple[str, dict]:
    """
    Assemble context from all sources in a session.

    Phase 1: Simple concatenation of source content.
    Future: Smart extraction (highlights, notes), token budgeting.

    Returns:
        (context_text, context_snapshot)
    """
    # Get all sources with their content paths
    cursor = await db.execute("""
        SELECT s.id, s.title, s.author_display, s.year, s.content_path, ss.context_type
        FROM session_sources ss
        JOIN sources s ON s.id = ss.source_id
        WHERE ss.session_id = ?
        ORDER BY ss.added_at ASC
    """, [session_id])
    sources = await cursor.fetchall()

    if not sources:
        return "", {"sources": []}

    context_parts = []
    context_snapshot = {"sources": []}

    for source in sources:
        source_id, title, author, year, content_path, context_type = source

        # Build source header
        header_parts = [title]
        if author:
            header_parts.append(f"by {author}")
        if year:
            header_parts.append(f"({year})")
        header = " ".join(header_parts)

        # Get content
        content = ""
        if content_path:
            content_file = Path(content_path)
            # content_path might be a file directly or a folder with content.txt
            if content_file.is_file():
                content = content_file.read_text(encoding="utf-8")[:50000]
            elif content_file.is_dir():
                # Try content.txt inside folder (document format)
                txt_file = content_file / "content.txt"
                if txt_file.exists():
                    content = txt_file.read_text(encoding="utf-8")[:50000]

        if content:
            context_parts.append(f"=== SOURCE: {header} ===\n{content}")
            context_snapshot["sources"].append({
                "id": source_id,
                "title": title,
                "context_type": context_type,
                "chars": len(content)
            })

    context_text = "\n\n".join(context_parts)
    return context_text, context_snapshot


@router.post("/{session_id}/chat", response_model=SessionChatResponse)
async def session_chat(session_id: str, request: SessionChatRequest):
    """
    Send a message in a research session context.

    Assembles context from all session sources, sends to LLM,
    and persists the conversation.
    """
    db = await get_db()
    chat = ChatService(verbose=True)

    # Check session exists
    cursor = await db.execute(
        "SELECT id FROM research_sessions WHERE id = ?",
        [session_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate model
    models = {m["id"]: m for m in get_chat_models()}
    if request.model_id not in models:
        raise HTTPException(status_code=400, detail=f"Unknown model: {request.model_id}")

    if not models[request.model_id]["available"]:
        raise HTTPException(
            status_code=400,
            detail=f"Model {request.model_id} not available (API key not configured)"
        )

    # Assemble context from session sources
    context_text, context_snapshot = await _assemble_context(db, session_id)

    # Build system prompt for research sessions
    system_prompt = """You are a research assistant helping analyze multiple sources.
You have access to the full text of each source in the session.
When answering questions:
- Reference specific sources by name when making claims
- Quote relevant passages when helpful
- Note agreements and disagreements between sources
- Be thorough but concise"""

    # Convert messages
    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    # Call LLM
    result = await chat.chat(
        model_id=request.model_id,
        messages=messages,
        system=system_prompt,
        context=context_text if context_text else None,
        max_tokens=request.max_tokens
    )

    # Persist messages
    now = datetime.now().isoformat()
    message_id = None

    if result.get("success"):
        # Save user message
        if messages:
            last_user_msg = messages[-1]
            user_msg_id = str(uuid.uuid4())[:8]
            await db.execute("""
                INSERT INTO session_messages
                (id, session_id, role, content, context_snapshot, model_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                user_msg_id,
                session_id,
                last_user_msg["role"],
                last_user_msg["content"],
                json.dumps(context_snapshot),
                request.model_id,
                now
            ])

        # Save assistant response
        message_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO session_messages
            (id, session_id, role, content, context_snapshot, model_id, usage, created_at)
            VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?)
        """, [
            message_id,
            session_id,
            result.get("content") or "",
            json.dumps(context_snapshot),
            request.model_id,
            json.dumps(result.get("usage")) if result.get("usage") else None,
            now
        ])

        # Update session timestamp
        await db.execute(
            "UPDATE research_sessions SET updated_at = ? WHERE id = ?",
            [now, session_id]
        )
        await db.commit()

    return SessionChatResponse(
        success=result.get("success", False),
        content=result.get("content"),
        error=result.get("error"),
        model_id=request.model_id,
        model=result.get("model"),
        usage=result.get("usage"),
        message_id=message_id,
        context_snapshot=context_snapshot,
        timestamp=datetime.fromisoformat(result.get("timestamp", now))
    )


@router.get("/{session_id}/messages", response_model=List[MessageDetail])
async def get_session_messages(
    session_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """Get conversation history for a session."""
    db = await get_db()

    # Check session exists
    cursor = await db.execute(
        "SELECT id FROM research_sessions WHERE id = ?",
        [session_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Session not found")

    # Get messages
    cursor = await db.execute("""
        SELECT id, role, content, model_id, usage, context_snapshot, created_at
        FROM session_messages
        WHERE session_id = ?
        ORDER BY created_at ASC
        LIMIT ? OFFSET ?
    """, [session_id, limit, offset])
    rows = await cursor.fetchall()

    return [
        MessageDetail(
            id=row[0],
            role=row[1],
            content=row[2],
            model_id=row[3],
            usage=json.loads(row[4]) if row[4] else None,
            context_snapshot=json.loads(row[5]) if row[5] else None,
            created_at=datetime.fromisoformat(row[6])
        )
        for row in rows
    ]


# ============================================================
# RLM (Recursive Language Model) Endpoints
# ============================================================

class RLMChatRequest(BaseModel):
    """Request for RLM-powered research query."""
    query: str
    model_id: str = "claude-opus"
    conversation_history: Optional[List[ChatMessage]] = None
    max_iterations: int = 20
    max_tokens: int = 12288  # Higher default for research responses


class RLMChatResponse(BaseModel):
    """Response from RLM query."""
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    model_id: str
    tool_calls: int
    iterations: int
    iteration_log: Optional[List[dict]] = None
    usage: Optional[dict] = None
    message_id: Optional[str] = None
    timestamp: datetime


@router.post("/{session_id}/rlm", response_model=RLMChatResponse)
async def session_rlm_chat(session_id: str, request: RLMChatRequest):
    """
    Send a research query using the RLM (Recursive Language Model) agent.

    The RLM agent has access to tools for:
    - Searching and filtering the library
    - Navigating document structure (TOC, sections)
    - Searching within sources (regex, find_all, find_mentions)
    - Reading source text (peek, read_section, read_around)
    - Accessing annotations (highlights, notes)
    - Storing state across turns
    - Synthesis operations (sub_query, summarize, extract_claims)

    The agent will autonomously explore sources to answer the query,
    providing grounded responses with citations.
    """
    db = await get_db()

    # Check session exists
    cursor = await db.execute(
        "SELECT id FROM research_sessions WHERE id = ?",
        [session_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate model
    models = {m["id"]: m for m in get_chat_models()}
    if request.model_id not in models:
        raise HTTPException(status_code=400, detail=f"Unknown model: {request.model_id}")

    if not models[request.model_id]["available"]:
        raise HTTPException(
            status_code=400,
            detail=f"Model {request.model_id} not available (API key not configured)"
        )

    # Convert conversation history if provided
    conversation_history = None
    if request.conversation_history:
        conversation_history = [
            {"role": m.role, "content": m.content}
            for m in request.conversation_history
        ]

    # Run RLM agent
    result = await run_rlm_query(
        session_id=session_id,
        query=request.query,
        model_id=request.model_id,
        conversation_history=conversation_history,
        max_iterations=request.max_iterations,
        max_tokens=request.max_tokens,
        verbose=True
    )

    now = datetime.now().isoformat()
    message_id = None

    # Persist messages if successful
    if result.get("success"):
        # Save user query
        user_msg_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO session_messages
            (id, session_id, role, content, model_id, created_at)
            VALUES (?, ?, 'user', ?, ?, ?)
        """, [user_msg_id, session_id, request.query, request.model_id, now])

        # Save assistant response with RLM metadata
        message_id = str(uuid.uuid4())[:8]
        rlm_metadata = {
            "type": "rlm",
            "tool_calls": result.get("tool_calls", 0),
            "iterations": result.get("iterations", 0)
        }
        await db.execute("""
            INSERT INTO session_messages
            (id, session_id, role, content, model_id, usage, context_snapshot, created_at)
            VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?)
        """, [
            message_id,
            session_id,
            result.get("content") or "",
            request.model_id,
            json.dumps(result.get("usage")) if result.get("usage") else None,
            json.dumps(rlm_metadata),
            now
        ])

        # Update session timestamp
        await db.execute(
            "UPDATE research_sessions SET updated_at = ? WHERE id = ?",
            [now, session_id]
        )
        await db.commit()

    return RLMChatResponse(
        success=result.get("success", False),
        content=result.get("content"),
        error=result.get("error"),
        model_id=request.model_id,
        tool_calls=result.get("tool_calls", 0),
        iterations=result.get("iterations", 0),
        iteration_log=result.get("iteration_log"),
        usage=result.get("usage"),
        message_id=message_id,
        timestamp=datetime.fromisoformat(now)
    )


@router.get("/{session_id}/rlm/stream")
async def session_rlm_stream(
    session_id: str,
    query: str,
    model_id: str = "claude-opus",
    max_iterations: int = 20,
    max_tokens: int = 12288
):
    """
    Stream an RLM query with real-time tool call visibility.

    Returns SSE events:
    - start: {query} - Query begins
    - iteration_start: {iteration} - New loop iteration
    - tool_start: {id, name, input} - Tool execution begins
    - tool_complete: {id, name, success, preview} - Tool finished
    - complete: {content, tool_calls, iterations, usage} - Final answer
    - error: {error} - Failure
    - saved: {message_id} - Message persisted to database
    """
    async def event_generator():
        db = await get_db()

        # Check session exists
        cursor = await db.execute(
            "SELECT id FROM research_sessions WHERE id = ?",
            [session_id]
        )
        if not await cursor.fetchone():
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
            return

        # Validate model
        models = {m["id"]: m for m in get_chat_models()}
        if model_id not in models:
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': f'Unknown model: {model_id}'})}\n\n"
            return

        if not models[model_id]["available"]:
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': f'Model {model_id} not available'})}\n\n"
            return

        # Save user query
        now = datetime.now().isoformat()
        user_msg_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO session_messages
            (id, session_id, role, content, model_id, created_at)
            VALUES (?, ?, 'user', ?, ?, ?)
        """, [user_msg_id, session_id, query, model_id, now])
        await db.commit()

        # Stream RLM query
        final_content = None
        final_tool_calls = 0
        final_iterations = 0
        final_usage = None
        had_error = False

        async for event in run_rlm_query_streaming(
            session_id=session_id,
            query=query,
            model_id=model_id,
            max_iterations=max_iterations,
            max_tokens=max_tokens,
            verbose=True
        ):
            # Forward the event as SSE
            yield f"event: {event['event']}\n"
            yield f"data: {json.dumps(event['data'])}\n\n"

            # Capture final state from complete event
            if event["event"] == "complete":
                final_content = event["data"].get("content")
                final_tool_calls = event["data"].get("tool_calls", 0)
                final_iterations = event["data"].get("iterations", 0)
                final_usage = event["data"].get("usage")
            elif event["event"] == "error":
                had_error = True

        # Save assistant response if successful
        if final_content is not None and not had_error:
            message_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()
            rlm_metadata = {
                "type": "rlm",
                "tool_calls": final_tool_calls,
                "iterations": final_iterations
            }
            await db.execute("""
                INSERT INTO session_messages
                (id, session_id, role, content, model_id, usage, context_snapshot, created_at)
                VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?)
            """, [
                message_id,
                session_id,
                final_content,
                model_id,
                json.dumps(final_usage) if final_usage else None,
                json.dumps(rlm_metadata),
                now
            ])

            # Update session timestamp
            await db.execute(
                "UPDATE research_sessions SET updated_at = ? WHERE id = ?",
                [now, session_id]
            )
            await db.commit()

            # Send saved event with message ID
            yield f"event: saved\n"
            yield f"data: {json.dumps({'message_id': message_id})}\n\n"

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
# RLM-v2 (Code Execution) Endpoint
# ============================================================

@router.get("/{session_id}/rlm-v2/stream")
async def session_rlm_v2_stream(
    session_id: str,
    query: str,
    orchestrator_model: str = "claude-sonnet",
    sub_model: str = "claude-haiku",
    synthesis_model: str = "claude-opus",
    max_iterations: int = 20,
    max_tokens: int = 4096
):
    """
    Stream an RLM-v2 query using the code-execution engine.

    Three-tier architecture:
    - Orchestrator (Sonnet): writes Python code to explore documents — fast
    - Sub-LLM (Haiku): independent semantic reasoning on passages — cheap
    - Synthesis (Opus): polished final answer from collected findings — quality

    Returns SSE events:
    - start: {query} - Query begins
    - thinking: {iteration} - New iteration starting
    - code_block: {code, iteration} - Code being executed
    - exec_result: {stdout, stderr, duration_ms} - Execution output
    - sub_llm_done: {count, duration_ms} - Sub-LLM calls completed
    - synthesizing: {model} - Opus synthesis starting
    - complete: {content, iterations, sub_llm_calls, usage} - Final answer
    - error: {error} - Failure
    - saved: {message_id} - Message persisted to database
    """
    async def event_generator():
        db = await get_db()

        # Check session exists
        cursor = await db.execute(
            "SELECT id FROM research_sessions WHERE id = ?",
            [session_id]
        )
        if not await cursor.fetchone():
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
            return

        # Validate all three models
        models = {m["id"]: m for m in get_chat_models()}
        for param_name, model_id in [
            ("orchestrator_model", orchestrator_model),
            ("sub_model", sub_model),
            ("synthesis_model", synthesis_model),
        ]:
            if model_id not in models:
                yield f"event: error\n"
                yield f"data: {json.dumps({'error': f'Unknown {param_name}: {model_id}'})}\n\n"
                return
            if not models[model_id]["available"]:
                yield f"event: error\n"
                yield f"data: {json.dumps({'error': f'{param_name} {model_id} not available (API key not configured)'})}\n\n"
                return

        # Save user query
        now = datetime.now().isoformat()
        user_msg_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO session_messages
            (id, session_id, role, content, model_id, created_at)
            VALUES (?, ?, 'user', ?, ?, ?)
        """, [user_msg_id, session_id, query, orchestrator_model, now])
        await db.commit()

        # Stream RLM-v2 query
        final_content = None
        final_iterations = 0
        final_sub_llm_calls = 0
        final_usage = None
        had_error = False

        try:
            async for event in run_rlm_v2_streaming(
                session_id=session_id,
                query=query,
                orchestrator_model=orchestrator_model,
                sub_model=sub_model,
                synthesis_model=synthesis_model,
                max_iterations=max_iterations,
                max_tokens=max_tokens,
                verbose=True
            ):
                # Forward the event as SSE
                yield f"event: {event['event']}\n"
                yield f"data: {json.dumps(event['data'], default=str)}\n\n"

                # Capture final state from complete event
                if event["event"] == "complete":
                    final_content = event["data"].get("content")
                    final_iterations = event["data"].get("iterations", 0)
                    final_sub_llm_calls = event["data"].get("sub_llm_calls", 0)
                    final_usage = event["data"].get("usage")
                    final_raw_findings = event["data"].get("raw_findings")
                    final_stored_evidence = event["data"].get("stored_evidence")
                    final_doc_reads = event["data"].get("doc_reads", 0)
                elif event["event"] == "error":
                    had_error = True
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': f'Stream crashed: {type(e).__name__}: {e}'})}\n\n"
            had_error = True

        # Save assistant response if successful
        if final_content is not None and not had_error:
            message_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()
            rlm_v2_metadata = {
                "type": "rlm-v2",
                "iterations": final_iterations,
                "sub_llm_calls": final_sub_llm_calls,
                "orchestrator_model": orchestrator_model,
                "sub_model": sub_model,
                "synthesis_model": synthesis_model,
                "raw_findings": final_raw_findings,
                "stored_evidence": final_stored_evidence,
                "doc_reads": final_doc_reads,
            }
            await db.execute("""
                INSERT INTO session_messages
                (id, session_id, role, content, model_id, usage, context_snapshot, created_at)
                VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?)
            """, [
                message_id,
                session_id,
                final_content,
                orchestrator_model,
                json.dumps(final_usage) if final_usage else None,
                json.dumps(rlm_v2_metadata),
                now
            ])

            # Update session timestamp
            await db.execute(
                "UPDATE research_sessions SET updated_at = ? WHERE id = ?",
                [now, session_id]
            )
            await db.commit()

            # Send saved event with message ID
            yield f"event: saved\n"
            yield f"data: {json.dumps({'message_id': message_id})}\n\n"

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
# Save Message as Note
# ============================================================

@router.post("/messages/{message_id}/save")
async def save_session_message_as_note(message_id: str):
    """
    Save a session message as a gluon (note).
    Works for both regular chat and RLM messages.
    """
    db = await get_db()

    # Get message with session info
    cursor = await db.execute("""
        SELECT m.content, m.context_snapshot, m.model_id, rs.title
        FROM session_messages m
        JOIN research_sessions rs ON m.session_id = rs.id
        WHERE m.id = ? AND m.role = 'assistant'
    """, [message_id])
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Message not found or not an assistant message")

    content = row[0]
    context_snapshot = json.loads(row[1]) if row[1] else {}
    model_id = row[2]
    session_title = row[3]

    if not content:
        raise HTTPException(status_code=400, detail="Message has no content")

    # Create gluon
    gluon_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Prefix based on message type (RLM or regular chat)
    is_rlm = context_snapshot.get("type") == "rlm"
    if is_rlm:
        tool_calls = context_snapshot.get("tool_calls", 0)
        note_content = f"[Research Analysis - {tool_calls} tool calls]\nFrom session: {session_title}\n\n{content}"
    elif model_id:
        note_content = f"[AI Analysis - {model_id}]\nFrom session: {session_title}\n\n{content}"
    else:
        note_content = f"[AI Analysis]\nFrom session: {session_title}\n\n{content}"

    await db.execute("""
        INSERT INTO gluons (id, type, content, created_at, updated_at)
        VALUES (?, 'note', ?, ?, ?)
    """, [gluon_id, note_content, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [gluon_id])

    await db.commit()

    return {
        "status": "saved",
        "gluon_id": gluon_id
    }
