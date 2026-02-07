"""
Highlights Router
=================
API endpoints for highlight management.

Highlights are stored in the gluons table with type='highlight'.
They use character offsets for reliable positioning.

Endpoints:
- GET    /highlights              - List highlights (optionally by source)
- GET    /highlights/:id          - Get single highlight
- POST   /highlights              - Create new highlight
- PATCH  /highlights/:id          - Update highlight (color, note)
- DELETE /highlights/:id          - Delete highlight
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from datetime import datetime
import uuid

from database import get_db
from models.highlight import (
    Highlight, HighlightCreate, HighlightUpdate,
    HighlightColor, HighlightWithContext, HIGHLIGHT_COLORS
)

router = APIRouter()


@router.get("", response_model=List[Highlight])
async def list_highlights(
    source_id: Optional[str] = Query(None, description="Filter by source"),
    color: Optional[HighlightColor] = Query(None, description="Filter by color"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    List highlights, optionally filtered by source or color.
    Returns highlights ordered by position in source.
    """
    db = await get_db()

    query = """
        SELECT g.id, g.source_id, g.section_id, g.start_offset, g.end_offset,
               g.color, g.content, g.created_at, g.updated_at,
               s.title as source_title
        FROM gluons g
        LEFT JOIN sources s ON g.source_id = s.id
        WHERE g.type = 'highlight'
    """
    params = []

    if source_id:
        query += " AND g.source_id = ?"
        params.append(source_id)

    if color:
        query += " AND g.color = ?"
        params.append(color.value)

    query += " ORDER BY g.source_id, g.start_offset LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    columns = [desc[0] for desc in cursor.description]
    highlights = [dict(zip(columns, row)) for row in rows]

    return highlights


@router.get("/colors")
async def get_highlight_colors():
    """
    Get available highlight colors with their display values.
    """
    return {
        color.value: info
        for color, info in HIGHLIGHT_COLORS.items()
    }


@router.get("/{highlight_id}", response_model=HighlightWithContext)
async def get_highlight(highlight_id: str, context_chars: int = Query(50, ge=0, le=500)):
    """
    Get a single highlight with surrounding context.
    """
    db = await get_db()

    cursor = await db.execute("""
        SELECT r.id, r.source_id, r.section_id, r.start_offset, r.end_offset,
               r.color, r.content, r.created_at, r.updated_at,
               src.content_path, sec.title as section_title
        FROM gluons r
        JOIN sources src ON r.source_id = src.id
        LEFT JOIN sections sec ON r.section_id = sec.id
        WHERE r.id = ? AND r.type = 'highlight'
    """, [highlight_id])

    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Highlight not found")

    columns = [desc[0] for desc in cursor.description]
    data = dict(zip(columns, row))

    # Get context from the source content
    context_before = ""
    context_after = ""

    content_path = data.pop("content_path", None)
    if content_path:
        from pathlib import Path
        try:
            full_text = Path(content_path).read_text(encoding="utf-8")
            start = data["start_offset"]
            end = data["end_offset"]

            context_start = max(0, start - context_chars)
            context_end = min(len(full_text), end + context_chars)

            context_before = full_text[context_start:start]
            context_after = full_text[end:context_end]
        except Exception:
            pass

    return {
        **data,
        "context_before": context_before,
        "context_after": context_after,
        "notes": []  # TODO: fetch attached notes
    }


@router.post("", response_model=Highlight)
async def create_highlight(highlight: HighlightCreate):
    """
    Create a new highlight.

    The highlight is stored as a gluon with type='highlight'.
    Character offsets are used for positioning.
    """
    db = await get_db()

    # Verify source exists
    cursor = await db.execute(
        "SELECT id FROM sources WHERE id = ?",
        [highlight.source_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Source not found")

    # Verify section if provided
    if highlight.section_id:
        cursor = await db.execute(
            "SELECT id FROM sections WHERE id = ? AND source_id = ?",
            [highlight.section_id, highlight.source_id]
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Section not found")

    # Generate ID
    highlight_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Insert into gluons table
    await db.execute("""
        INSERT INTO gluons (id, type, content, source_id, section_id,
                         start_offset, end_offset, color, created_at, updated_at)
        VALUES (?, 'highlight', ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        highlight_id,
        highlight.content,
        highlight.source_id,
        highlight.section_id,
        highlight.start_offset,
        highlight.end_offset,
        highlight.color.value,
        now,
        now
    ])

    # Index in FTS for searchability
    if highlight.content:
        await db.execute("""
            INSERT INTO gluons_fts (rowid, content)
            SELECT rowid, content FROM gluons WHERE id = ?
        """, [highlight_id])

    await db.commit()

    return {
        "id": highlight_id,
        "source_id": highlight.source_id,
        "section_id": highlight.section_id,
        "start_offset": highlight.start_offset,
        "end_offset": highlight.end_offset,
        "color": highlight.color,
        "content": highlight.content,
        "created_at": now,
        "updated_at": now,
        "notes": []
    }


@router.patch("/{highlight_id}", response_model=Highlight)
async def update_highlight(highlight_id: str, updates: HighlightUpdate):
    """
    Update a highlight's color.
    """
    db = await get_db()

    # Verify highlight exists
    cursor = await db.execute(
        "SELECT id FROM gluons WHERE id = ? AND type = 'highlight'",
        [highlight_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Highlight not found")

    # Build update
    update_fields = []
    params = []

    if updates.color is not None:
        update_fields.append("color = ?")
        params.append(updates.color.value)

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    update_fields.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(highlight_id)

    query = f"UPDATE gluons SET {', '.join(update_fields)} WHERE id = ?"
    await db.execute(query, params)
    await db.commit()

    # Return updated highlight
    return await get_highlight_basic(highlight_id)


@router.delete("/{highlight_id}")
async def delete_highlight(highlight_id: str):
    """
    Delete a highlight and any attached notes.
    """
    db = await get_db()

    # Verify highlight exists
    cursor = await db.execute(
        "SELECT id FROM gluons WHERE id = ? AND type = 'highlight'",
        [highlight_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Highlight not found")

    # Delete from FTS first
    await db.execute("""
        DELETE FROM gluons_fts WHERE rowid IN
        (SELECT rowid FROM gluons WHERE id = ? OR parent_gluon_id = ?)
    """, [highlight_id, highlight_id])

    # Delete attached notes (cascade)
    await db.execute(
        "DELETE FROM gluons WHERE parent_gluon_id = ?",
        [highlight_id]
    )

    # Delete the highlight
    await db.execute(
        "DELETE FROM gluons WHERE id = ?",
        [highlight_id]
    )

    await db.commit()

    return {"deleted": highlight_id}


async def get_highlight_basic(highlight_id: str) -> dict:
    """Helper to get highlight without context."""
    db = await get_db()

    cursor = await db.execute("""
        SELECT id, source_id, section_id, start_offset, end_offset,
               color, content, created_at, updated_at
        FROM gluons
        WHERE id = ? AND type = 'highlight'
    """, [highlight_id])

    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Highlight not found")

    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))
