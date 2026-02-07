"""
Rems Router
===========
API endpoints for the Rems knowledge system.

Rems are universal linkable objects. While highlights have their own router,
this router handles:
- Notes (freestanding or attached to documents)
- Tags (categorical labels)
- References ([[links]] between rems)
- Backlinks (what links to a given rem)

Endpoints:
- GET    /rems              - List rems (with filters)
- GET    /rems/search       - Search rems by content
- GET    /rems/tags         - List all tags
- GET    /rems/:id          - Get single rem with links
- POST   /rems              - Create new rem (note or tag)
- PATCH  /rems/:id          - Update rem content
- DELETE /rems/:id          - Delete rem

Link management:
- POST   /rems/:id/link     - Create link from rem to target
- DELETE /rems/:id/link/:target_id - Remove link
- GET    /rems/:id/backlinks - Get all rems that link to this one
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid
import re

from database import get_db

router = APIRouter()


# --- Pydantic Models ---

class NoteCreate(BaseModel):
    """Create a new note."""
    content: str = Field(..., min_length=1, description="Note content (can contain [[refs]] and ##tags)")
    document_id: Optional[str] = Field(None, description="Associated document")
    parent_rem_id: Optional[str] = Field(None, description="Parent rem (e.g., attach note to highlight)")


class NoteUpdate(BaseModel):
    """Update a note."""
    content: Optional[str] = Field(None, min_length=1)


class TagCreate(BaseModel):
    """Create a new tag."""
    name: str = Field(..., min_length=1, max_length=100, description="Tag name (without ##)")


class LinkCreate(BaseModel):
    """Create a link between rems."""
    target_id: str = Field(..., description="ID of rem to link to")
    link_type: str = Field("reference", pattern="^(reference|tag)$")


class RemResponse(BaseModel):
    """Response model for a rem."""
    id: str
    type: str
    content: Optional[str]
    document_id: Optional[str]
    section_id: Optional[str]
    parent_rem_id: Optional[str]
    created_at: str
    updated_at: str


class RemWithLinks(RemResponse):
    """Rem with its connections."""
    outgoing_refs: List[RemResponse] = []
    tags: List[RemResponse] = []
    backlinks: List[RemResponse] = []
    notes: List[RemResponse] = []


# --- Helper Functions ---

def parse_links(content: str) -> tuple[List[str], List[str]]:
    """
    Parse [[references]] and ##tags from content.
    Returns (reference_names, tag_names)
    """
    # Match [[anything]] - the reference text
    refs = re.findall(r'\[\[([^\]]+)\]\]', content)

    # Match ##tag - word characters after ##
    tags = re.findall(r'##(\w+)', content)

    return refs, tags


async def get_or_create_tag(name: str) -> str:
    """Get tag by name or create if doesn't exist. Returns tag id."""
    db = await get_db()

    # Normalize tag name (lowercase, no spaces)
    normalized = name.lower().strip()

    # Check if tag exists
    cursor = await db.execute(
        "SELECT id FROM rems WHERE type = 'tag' AND content = ?",
        [normalized]
    )
    row = await cursor.fetchone()
    if row:
        return row[0]

    # Create new tag
    tag_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO rems (id, type, content, created_at, updated_at)
        VALUES (?, 'tag', ?, ?, ?)
    """, [tag_id, normalized, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO rems_fts (rowid, content)
        SELECT rowid, content FROM rems WHERE id = ?
    """, [tag_id])

    await db.commit()
    return tag_id


async def find_rem_by_content(content: str) -> Optional[str]:
    """Find a rem by its content (for [[reference]] resolution). Returns rem id."""
    db = await get_db()

    # First try exact match on content
    cursor = await db.execute(
        "SELECT id FROM rems WHERE content = ? LIMIT 1",
        [content]
    )
    row = await cursor.fetchone()
    if row:
        return row[0]

    # Try matching document title
    cursor = await db.execute(
        "SELECT id FROM rems WHERE type = 'highlight' AND content LIKE ? LIMIT 1",
        [f"%{content}%"]
    )
    row = await cursor.fetchone()
    if row:
        return row[0]

    return None


async def get_or_create_ref(content: str) -> str:
    """
    Get ref by content or create a new note gluon if doesn't exist.
    Returns gluon id.
    """
    db = await get_db()

    # First try to find existing gluon with this content
    target_id = await find_rem_by_content(content)
    if target_id:
        return target_id

    # Create new note gluon with this content
    new_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO rems (id, type, content, created_at, updated_at)
        VALUES (?, 'note', ?, ?, ?)
    """, [new_id, content, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO rems_fts (rowid, content)
        SELECT rowid, content FROM rems WHERE id = ?
    """, [new_id])

    await db.commit()
    return new_id


async def process_links_in_content(rem_id: str, content: str):
    """
    Parse content for [[refs]] and ##tags, create corresponding links.
    This is called when creating or updating a note.

    - ##tags: get or create the tag, then link
    - [[refs]]: get or create a note gluon with that content, then link
    """
    db = await get_db()
    refs, tags = parse_links(content)
    now = datetime.now().isoformat()

    # Remove existing links from this rem (we'll recreate)
    await db.execute("DELETE FROM links WHERE source_id = ?", [rem_id])

    # Process ##tags
    for tag_name in tags:
        tag_id = await get_or_create_tag(tag_name)
        link_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO links (id, source_id, target_id, link_type, created_at)
            VALUES (?, ?, ?, 'tag', ?)
        """, [link_id, rem_id, tag_id, now])

    # Process [[references]] - get or create gluon, then link
    for ref_text in refs:
        target_id = await get_or_create_ref(ref_text)
        link_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO links (id, source_id, target_id, link_type, created_at)
            VALUES (?, ?, ?, 'reference', ?)
        """, [link_id, rem_id, target_id, now])

    await db.commit()


# --- Routes ---

@router.get("")
async def list_rems(
    type: Optional[str] = Query(None, description="Filter by type: 'note', 'tag'"),
    document_id: Optional[str] = Query(None, description="Filter by document"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    List rems. Excludes highlights (use /highlights endpoint for those).
    Includes document_title for notes associated with documents.
    """
    db = await get_db()

    query = """
        SELECT r.id, r.type, r.content, r.document_id, r.section_id, r.parent_rem_id,
               r.created_at, r.updated_at,
               d.title as document_title
        FROM rems r
        LEFT JOIN documents d ON r.document_id = d.id
        WHERE r.type IN ('note', 'tag')
    """
    params = []

    if type:
        query += " AND r.type = ?"
        params.append(type)

    if document_id:
        query += " AND r.document_id = ?"
        params.append(document_id)

    query += " ORDER BY r.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


@router.get("/search")
async def search_rems(
    q: str = Query(..., min_length=1, description="Search query"),
    type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Full-text search across all rems.
    """
    db = await get_db()

    # Search using FTS5
    query = """
        SELECT r.id, r.type, r.content, r.document_id, r.created_at, r.updated_at
        FROM rems r
        JOIN rems_fts fts ON r.rowid = fts.rowid
        WHERE rems_fts MATCH ?
    """
    params = [q]

    if type:
        query += " AND r.type = ?"
        params.append(type)

    query += " ORDER BY rank LIMIT ?"
    params.append(limit)

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


@router.get("/tags")
async def list_tags():
    """
    List all tags with usage count.
    """
    db = await get_db()

    cursor = await db.execute("""
        SELECT r.id, r.content as name,
               COUNT(l.id) as usage_count
        FROM rems r
        LEFT JOIN links l ON l.target_id = r.id AND l.link_type = 'tag'
        WHERE r.type = 'tag'
        GROUP BY r.id
        ORDER BY usage_count DESC, r.content
    """)
    rows = await cursor.fetchall()

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


@router.get("/{rem_id}", response_model=RemWithLinks)
async def get_rem(rem_id: str):
    """
    Get a rem with all its connections (outgoing refs, tags, backlinks, notes).
    """
    db = await get_db()

    # Get the rem
    cursor = await db.execute("""
        SELECT id, type, content, document_id, section_id, parent_rem_id,
               created_at, updated_at
        FROM rems WHERE id = ?
    """, [rem_id])
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Rem not found")

    columns = [desc[0] for desc in cursor.description]
    rem = dict(zip(columns, row))

    # Get outgoing references
    cursor = await db.execute("""
        SELECT r.id, r.type, r.content, r.document_id, r.section_id,
               r.parent_rem_id, r.created_at, r.updated_at
        FROM rems r
        JOIN links l ON l.target_id = r.id
        WHERE l.source_id = ? AND l.link_type = 'reference'
    """, [rem_id])
    rows = await cursor.fetchall()
    rem["outgoing_refs"] = [dict(zip(columns, r)) for r in rows]

    # Get tags
    cursor = await db.execute("""
        SELECT r.id, r.type, r.content, r.document_id, r.section_id,
               r.parent_rem_id, r.created_at, r.updated_at
        FROM rems r
        JOIN links l ON l.target_id = r.id
        WHERE l.source_id = ? AND l.link_type = 'tag'
    """, [rem_id])
    rows = await cursor.fetchall()
    rem["tags"] = [dict(zip(columns, r)) for r in rows]

    # Get backlinks (what references this rem) - include link_type to distinguish tag vs reference
    cursor = await db.execute("""
        SELECT r.id, r.type, r.content, r.document_id, r.section_id,
               r.parent_rem_id, r.created_at, r.updated_at,
               l.link_type,
               d.title as document_title
        FROM rems r
        JOIN links l ON l.source_id = r.id
        LEFT JOIN documents d ON r.document_id = d.id
        WHERE l.target_id = ?
    """, [rem_id])
    rows = await cursor.fetchall()
    backlink_cols = [desc[0] for desc in cursor.description]
    rem["backlinks"] = [dict(zip(backlink_cols, r)) for r in rows]

    # Get child notes (if this is a highlight)
    cursor = await db.execute("""
        SELECT id, type, content, document_id, section_id, parent_rem_id,
               created_at, updated_at
        FROM rems
        WHERE parent_rem_id = ? AND type = 'note'
        ORDER BY created_at
    """, [rem_id])
    rows = await cursor.fetchall()
    rem["notes"] = [dict(zip(columns, r)) for r in rows]

    return rem


@router.post("/notes", response_model=RemResponse)
async def create_note(note: NoteCreate):
    """
    Create a new note.

    Content can contain:
    - [[references]] to link to other rems
    - ##tags to categorize

    Notes can be:
    - Attached to a document (document_id)
    - Attached to a highlight (parent_rem_id)
    - Freestanding (neither)
    """
    db = await get_db()

    # Verify document exists if provided
    if note.document_id:
        cursor = await db.execute(
            "SELECT id FROM documents WHERE id = ?",
            [note.document_id]
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Document not found")

    # Verify parent rem exists if provided
    if note.parent_rem_id:
        cursor = await db.execute(
            "SELECT id FROM rems WHERE id = ?",
            [note.parent_rem_id]
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Parent rem not found")

    # Create note
    note_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO rems (id, type, content, document_id, parent_rem_id, created_at, updated_at)
        VALUES (?, 'note', ?, ?, ?, ?, ?)
    """, [note_id, note.content, note.document_id, note.parent_rem_id, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO rems_fts (rowid, content)
        SELECT rowid, content FROM rems WHERE id = ?
    """, [note_id])

    await db.commit()

    # Process [[refs]] and ##tags
    await process_links_in_content(note_id, note.content)

    return {
        "id": note_id,
        "type": "note",
        "content": note.content,
        "document_id": note.document_id,
        "section_id": None,
        "parent_rem_id": note.parent_rem_id,
        "created_at": now,
        "updated_at": now
    }


@router.post("/tags", response_model=RemResponse)
async def create_tag(tag: TagCreate):
    """
    Create a new tag. If tag already exists, returns the existing one.
    """
    db = await get_db()

    normalized = tag.name.lower().strip()

    # Check if exists
    cursor = await db.execute(
        "SELECT id, type, content, document_id, section_id, parent_rem_id, created_at, updated_at FROM rems WHERE type = 'tag' AND content = ?",
        [normalized]
    )
    row = await cursor.fetchone()
    if row:
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    # Create
    tag_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO rems (id, type, content, created_at, updated_at)
        VALUES (?, 'tag', ?, ?, ?)
    """, [tag_id, normalized, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO rems_fts (rowid, content)
        SELECT rowid, content FROM rems WHERE id = ?
    """, [tag_id])

    await db.commit()

    return {
        "id": tag_id,
        "type": "tag",
        "content": normalized,
        "document_id": None,
        "section_id": None,
        "parent_rem_id": None,
        "created_at": now,
        "updated_at": now
    }


@router.patch("/{rem_id}", response_model=RemResponse)
async def update_rem(rem_id: str, update: NoteUpdate):
    """
    Update a rem's content. Re-parses [[refs]] and ##tags.
    """
    db = await get_db()

    # Verify rem exists
    cursor = await db.execute(
        "SELECT id, type FROM rems WHERE id = ?",
        [rem_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rem not found")

    if row[1] == 'tag':
        raise HTTPException(status_code=400, detail="Cannot update tag content directly")

    now = datetime.now().isoformat()

    # Update content
    await db.execute("""
        UPDATE rems SET content = ?, updated_at = ? WHERE id = ?
    """, [update.content, now, rem_id])

    # Update FTS
    await db.execute("""
        DELETE FROM rems_fts WHERE rowid = (SELECT rowid FROM rems WHERE id = ?)
    """, [rem_id])
    await db.execute("""
        INSERT INTO rems_fts (rowid, content)
        SELECT rowid, content FROM rems WHERE id = ?
    """, [rem_id])

    await db.commit()

    # Re-process links
    if update.content:
        await process_links_in_content(rem_id, update.content)

    # Return updated
    cursor = await db.execute("""
        SELECT id, type, content, document_id, section_id, parent_rem_id,
               created_at, updated_at
        FROM rems WHERE id = ?
    """, [rem_id])
    row = await cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


@router.delete("/{rem_id}")
async def delete_rem(rem_id: str):
    """
    Delete a rem and all its links.
    """
    db = await get_db()

    # Verify rem exists
    cursor = await db.execute(
        "SELECT id, type FROM rems WHERE id = ?",
        [rem_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rem not found")

    # Don't delete highlights through this endpoint
    if row[1] == 'highlight':
        raise HTTPException(
            status_code=400,
            detail="Use DELETE /highlights/:id for highlights"
        )

    # Delete from FTS
    await db.execute("""
        DELETE FROM rems_fts WHERE rowid = (SELECT rowid FROM rems WHERE id = ?)
    """, [rem_id])

    # Delete links (both directions)
    await db.execute("DELETE FROM links WHERE source_id = ? OR target_id = ?", [rem_id, rem_id])

    # Delete the rem
    await db.execute("DELETE FROM rems WHERE id = ?", [rem_id])

    await db.commit()

    return {"deleted": rem_id}


@router.post("/{rem_id}/link")
async def create_link(rem_id: str, link: LinkCreate):
    """
    Create a link from this rem to another rem.
    """
    db = await get_db()

    # Verify source exists
    cursor = await db.execute("SELECT id FROM rems WHERE id = ?", [rem_id])
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Source rem not found")

    # Verify target exists
    cursor = await db.execute("SELECT id FROM rems WHERE id = ?", [link.target_id])
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Target rem not found")

    # Check if link already exists
    cursor = await db.execute("""
        SELECT id FROM links
        WHERE source_id = ? AND target_id = ? AND link_type = ?
    """, [rem_id, link.target_id, link.link_type])
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail="Link already exists")

    # Create link
    link_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO links (id, source_id, target_id, link_type, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, [link_id, rem_id, link.target_id, link.link_type, now])

    await db.commit()

    return {"id": link_id, "source_id": rem_id, "target_id": link.target_id, "link_type": link.link_type}


@router.delete("/{rem_id}/link/{target_id}")
async def delete_link(rem_id: str, target_id: str):
    """
    Remove a link between rems.
    """
    db = await get_db()

    result = await db.execute("""
        DELETE FROM links WHERE source_id = ? AND target_id = ?
    """, [rem_id, target_id])

    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Link not found")

    return {"deleted": True}


@router.get("/{rem_id}/backlinks")
async def get_backlinks(rem_id: str):
    """
    Get all rems that link to this one, grouped by link type.
    """
    db = await get_db()

    # Verify rem exists
    cursor = await db.execute("SELECT id FROM rems WHERE id = ?", [rem_id])
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Rem not found")

    # Get all backlinks with source rem details
    cursor = await db.execute("""
        SELECT r.id, r.type, r.content, r.document_id, r.created_at,
               l.link_type,
               d.title as document_title
        FROM rems r
        JOIN links l ON l.source_id = r.id
        LEFT JOIN documents d ON r.document_id = d.id
        WHERE l.target_id = ?
        ORDER BY l.link_type, r.created_at DESC
    """, [rem_id])
    rows = await cursor.fetchall()

    columns = [desc[0] for desc in cursor.description]
    backlinks = [dict(zip(columns, row)) for row in rows]

    # Group by type
    references = [b for b in backlinks if b["link_type"] == "reference"]
    tagged_with = [b for b in backlinks if b["link_type"] == "tag"]

    return {
        "references": references,
        "tagged_with": tagged_with,
        "total": len(backlinks)
    }
