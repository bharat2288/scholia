"""
Gluons Router
=============
API endpoints for the Gluons knowledge system.

Gluons are universal linkable objects (named after the particle that binds quarks).
While highlights have their own router, this router handles:
- Notes (freestanding or attached to sources)
- Tags (categorical labels)
- References ([[links]] between gluons)
- Backlinks (what links to a given gluon)

Endpoints:
- GET    /gluons              - List gluons (with filters)
- GET    /gluons/search       - Search gluons by content
- GET    /gluons/tags         - List all tags
- GET    /gluons/:id          - Get single gluon with links
- POST   /gluons              - Create new gluon (note or tag)
- PATCH  /gluons/:id          - Update gluon content
- DELETE /gluons/:id          - Delete gluon

Link management:
- POST   /gluons/:id/link     - Create link from gluon to target
- DELETE /gluons/:id/link/:target_id - Remove link
- GET    /gluons/:id/backlinks - Get all gluons that link to this one
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid
import re
import aiosqlite

from database import get_db

router = APIRouter()


# --- Pydantic Models ---

class NoteCreate(BaseModel):
    """Create a new note."""
    content: str = Field(..., min_length=1, description="Note content (can contain [[refs]] and ##tags)")
    source_id: Optional[str] = Field(None, description="Associated source")
    parent_gluon_id: Optional[str] = Field(None, description="Parent gluon (e.g., attach note to highlight)")


class NoteUpdate(BaseModel):
    """Update a note."""
    content: Optional[str] = Field(None, min_length=1)


class TagCreate(BaseModel):
    """Create a new tag."""
    name: str = Field(..., min_length=1, max_length=100, description="Tag name (without ##)")


class LinkCreate(BaseModel):
    """Create a link between gluons."""
    target_id: str = Field(..., description="ID of gluon to link to")
    link_type: str = Field("reference", pattern="^(reference|tag)$")


class BatchTagsRequest(BaseModel):
    """Request to find or create multiple tags."""
    names: List[str] = Field(..., min_items=1, description="List of tag names to find or create")


class BatchPeopleRequest(BaseModel):
    """Request to find or create multiple people."""
    names: List[str] = Field(..., min_items=1, description="List of person names to find or create")


class BatchTagResult(BaseModel):
    """Result of batch tag creation."""
    name: str
    id: str


class BatchPersonResult(BaseModel):
    """Result of batch person creation."""
    name: str
    id: str


class GluonRename(BaseModel):
    """Rename a tag or person gluon."""
    name: str = Field(..., min_length=1, max_length=200, description="New name")


class GluonMerge(BaseModel):
    """Merge this gluon into a target gluon."""
    target_id: str = Field(..., description="ID of the gluon to merge into")


class GluonResponse(BaseModel):
    """Response model for a gluon."""
    id: str
    type: str
    content: Optional[str]
    source_id: Optional[str]
    section_id: Optional[str]
    parent_gluon_id: Optional[str]
    created_at: str
    updated_at: str
    source_title: Optional[str] = None


class BacklinkResponse(GluonResponse):
    """Gluon that links back, with link type info."""
    link_type: Optional[str] = None


class GluonWithLinks(GluonResponse):
    """Gluon with its connections."""
    outgoing_refs: List[GluonResponse] = []
    tags: List[GluonResponse] = []
    backlinks: List[BacklinkResponse] = []
    notes: List[GluonResponse] = []
    parent_gluon: Optional[GluonResponse] = None  # For notes attached to highlights


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
        "SELECT id FROM gluons WHERE type = 'tag' AND content = ?",
        [normalized]
    )
    row = await cursor.fetchone()
    if row:
        return row[0]

    # Create new tag
    tag_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO gluons (id, type, content, created_at, updated_at)
        VALUES (?, 'tag', ?, ?, ?)
    """, [tag_id, normalized, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [tag_id])

    await db.commit()
    return tag_id


async def find_gluon_by_content(content: str) -> Optional[str]:
    """Find a gluon by its content (for [[reference]] resolution). Returns gluon id."""
    db = await get_db()

    # First try exact match on content
    cursor = await db.execute(
        "SELECT id FROM gluons WHERE content = ? LIMIT 1",
        [content]
    )
    row = await cursor.fetchone()
    if row:
        return row[0]

    # Try matching document title
    cursor = await db.execute(
        "SELECT id FROM gluons WHERE type = 'highlight' AND content LIKE ? LIMIT 1",
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
    target_id = await find_gluon_by_content(content)
    if target_id:
        return target_id

    # Create new note gluon with this content
    new_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO gluons (id, type, content, created_at, updated_at)
        VALUES (?, 'note', ?, ?, ?)
    """, [new_id, content, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [new_id])

    await db.commit()
    return new_id


async def process_links_in_content(gluon_id: str, content: str):
    """
    Parse content for [[refs]] and ##tags, create corresponding links.
    This is called when creating or updating a note.

    - ##tags: get or create the tag, then link
    - [[refs]]: get or create a note gluon with that content, then link

    IMPORTANT: Preserves "system" tag links (like 'person') that were created
    programmatically rather than from content parsing.
    """
    db = await get_db()
    refs, tags = parse_links(content)
    now = datetime.now().isoformat()

    # System tags that should be preserved even if not in content
    # These are tags added programmatically (e.g., person gluons tagged with ##person)
    SYSTEM_TAGS = {'person'}

    # Find existing system tag links to preserve
    cursor = await db.execute("""
        SELECT l.id, l.target_id, t.content as tag_name
        FROM links l
        JOIN gluons t ON l.target_id = t.id
        WHERE l.source_id = ?
          AND l.link_type = 'tag'
          AND t.type = 'tag'
          AND t.content IN ({})
    """.format(','.join(['?' for _ in SYSTEM_TAGS])), [gluon_id] + list(SYSTEM_TAGS))
    system_links = await cursor.fetchall()

    # Remove existing links from this gluon (we'll recreate content-based ones)
    await db.execute("DELETE FROM links WHERE source_id = ?", [gluon_id])

    # Restore system tag links
    for link_id, target_id, tag_name in system_links:
        # Only restore if this tag isn't also in content (avoid duplicates)
        if tag_name.lower() not in [t.lower() for t in tags]:
            await db.execute("""
                INSERT INTO links (id, source_id, target_id, link_type, created_at)
                VALUES (?, ?, ?, 'tag', ?)
            """, [link_id, gluon_id, target_id, now])

    # Process ##tags
    for tag_name in tags:
        tag_id = await get_or_create_tag(tag_name)
        link_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO links (id, source_id, target_id, link_type, created_at)
            VALUES (?, ?, ?, 'tag', ?)
        """, [link_id, gluon_id, tag_id, now])

    # Process [[references]] - get or create gluon, then link
    for ref_text in refs:
        target_id = await get_or_create_ref(ref_text)
        link_id = str(uuid.uuid4())[:8]
        await db.execute("""
            INSERT INTO links (id, source_id, target_id, link_type, created_at)
            VALUES (?, ?, ?, 'reference', ?)
        """, [link_id, gluon_id, target_id, now])

    await db.commit()


# --- Routes ---

@router.get("")
async def list_gluons(
    type: Optional[str] = Query(None, description="Filter by type: 'note', 'tag'"),
    source_id: Optional[str] = Query(None, description="Filter by source"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    List gluons. Excludes highlights (use /highlights endpoint for those).
    Includes source_title for notes associated with sources.
    """
    db = await get_db()

    query = """
        SELECT g.id, g.type, g.content, g.source_id, g.section_id, g.parent_gluon_id,
               g.created_at, g.updated_at,
               s.title as source_title
        FROM gluons g
        LEFT JOIN sources s ON g.source_id = s.id
        WHERE g.type IN ('note', 'tag')
    """
    params = []

    if type:
        query += " AND g.type = ?"
        params.append(type)

    if source_id:
        query += " AND g.source_id = ?"
        params.append(source_id)

    query += " ORDER BY g.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    columns = [desc[0] for desc in cursor.description]
    gluons = [dict(zip(columns, row)) for row in rows]

    # For notes, fetch their tags from the links table
    if gluons:
        gluon_ids = [g['id'] for g in gluons]
        placeholders = ','.join(['?' for _ in gluon_ids])

        # Get all tag links for these gluons
        tag_cursor = await db.execute(f"""
            SELECT l.source_id, t.id as tag_id, t.content as tag_name
            FROM links l
            JOIN gluons t ON l.target_id = t.id
            WHERE l.source_id IN ({placeholders})
              AND l.link_type = 'tag'
              AND t.type = 'tag'
        """, gluon_ids)
        tag_rows = await tag_cursor.fetchall()

        # Group tags by source gluon
        gluon_tags = {}
        for source_id, tag_id, tag_name in tag_rows:
            if source_id not in gluon_tags:
                gluon_tags[source_id] = []
            gluon_tags[source_id].append({'id': tag_id, 'name': tag_name})

        # Attach tags to each gluon
        for g in gluons:
            g['tags'] = gluon_tags.get(g['id'], [])

    return gluons


@router.get("/search")
async def search_gluons(
    q: str = Query(..., min_length=1, description="Search query"),
    type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Full-text search across all gluons.
    """
    db = await get_db()

    # Escape special FTS5 characters and wrap each word with * for prefix matching
    # This makes "Discussion points" match "Discussion points" exactly
    escaped_q = q.replace('"', '""')
    search_term = f'"{escaped_q}"'

    # Search using FTS5
    query = """
        SELECT g.id, g.type, g.content, g.source_id, g.created_at, g.updated_at
        FROM gluons g
        JOIN gluons_fts fts ON g.rowid = fts.rowid
        WHERE gluons_fts MATCH ?
    """
    params = [search_term]

    if type:
        query += " AND g.type = ?"
        params.append(type)

    query += " ORDER BY rank LIMIT ?"
    params.append(limit)

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    columns = [desc[0] for desc in cursor.description]
    gluons = [dict(zip(columns, row)) for row in rows]

    # For notes in search results, fetch their tags from the links table
    if gluons:
        gluon_ids = [g['id'] for g in gluons]
        placeholders = ','.join(['?' for _ in gluon_ids])

        tag_cursor = await db.execute(f"""
            SELECT l.source_id, t.id as tag_id, t.content as tag_name
            FROM links l
            JOIN gluons t ON l.target_id = t.id
            WHERE l.source_id IN ({placeholders})
              AND l.link_type = 'tag'
              AND t.type = 'tag'
        """, gluon_ids)
        tag_rows = await tag_cursor.fetchall()

        gluon_tags = {}
        for source_id, tag_id, tag_name in tag_rows:
            if source_id not in gluon_tags:
                gluon_tags[source_id] = []
            gluon_tags[source_id].append({'id': tag_id, 'name': tag_name})

        for g in gluons:
            g['tags'] = gluon_tags.get(g['id'], [])

    return gluons


@router.get("/by-content")
async def find_by_content(
    content: str = Query(..., min_length=1, description="Exact content to match")
):
    """
    Find a gluon by exact content match. Used for [[ref]] resolution.
    Returns the gluon ID if found, null otherwise.
    """
    db = await get_db()

    cursor = await db.execute(
        "SELECT id FROM gluons WHERE content = ? LIMIT 1",
        [content]
    )
    row = await cursor.fetchone()

    if row:
        return {"id": row[0], "found": True}
    return {"id": None, "found": False}


@router.get("/tags")
async def list_tags(
    q: Optional[str] = Query(None, min_length=1, description="Search query for filtering")
):
    """
    List all tags with usage count.
    Counts both note references (##hashtag) and source tags.
    Optionally filter by search query.
    """
    db = await get_db()

    # Count from both links table (note hashtags) and source_gluon_links (source tags)
    if q:
        cursor = await db.execute("""
            SELECT g.id, g.content as name,
                   (SELECT COUNT(*) FROM links l WHERE l.target_id = g.id AND l.link_type = 'tag') +
                   (SELECT COUNT(*) FROM source_gluon_links sgl WHERE sgl.gluon_id = g.id AND sgl.relationship_type = 'tag')
                   as usage_count
            FROM gluons g
            WHERE g.type = 'tag' AND g.content LIKE ?
            ORDER BY usage_count DESC, g.content
            LIMIT 20
        """, [f"%{q}%"])
    else:
        cursor = await db.execute("""
            SELECT g.id, g.content as name,
                   (SELECT COUNT(*) FROM links l WHERE l.target_id = g.id AND l.link_type = 'tag') +
                   (SELECT COUNT(*) FROM source_gluon_links sgl WHERE sgl.gluon_id = g.id AND sgl.relationship_type = 'tag')
                   as usage_count
            FROM gluons g
            WHERE g.type = 'tag'
            ORDER BY usage_count DESC, g.content
        """)
    rows = await cursor.fetchall()

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


# --- Person (Author) Endpoints ---

class PersonCreate(BaseModel):
    """Create a new person gluon."""
    name: str = Field(..., min_length=1, max_length=200, description="Person's name")


@router.get("/people")
async def list_people(
    q: Optional[str] = Query(None, min_length=1, description="Search query for filtering"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    List all Person gluons (authors, editors, etc.).
    People are note gluons tagged with ##person.

    Args:
        q: Optional search query to filter by name
        limit: Maximum number of results

    Returns:
        List of person gluons with name and id
    """
    db = await get_db()

    # Get the 'person' tag ID
    cursor = await db.execute(
        "SELECT id FROM gluons WHERE type = 'tag' AND content = 'person'"
    )
    person_tag = await cursor.fetchone()

    if not person_tag:
        # No person tag exists yet, return empty list
        return []

    person_tag_id = person_tag[0]

    # Find all gluons linked to the 'person' tag
    query = """
        SELECT g.id, g.content as name, g.created_at
        FROM gluons g
        JOIN links l ON l.source_id = g.id AND l.target_id = ?
        WHERE l.link_type = 'tag' AND g.type = 'note'
    """
    params = [person_tag_id]

    if q:
        query += " AND g.content LIKE ?"
        params.append(f"%{q}%")

    query += " ORDER BY g.content LIMIT ?"
    params.append(limit)

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


@router.post("/person", response_model=GluonResponse)
async def create_person(person: PersonCreate):
    """
    Create a new Person gluon.

    A Person is a note gluon with content=name, tagged with ##person.
    Used to represent authors, editors, etc.

    Args:
        person: PersonCreate with name field

    Returns:
        The created person gluon
    """
    db = await get_db()
    now = datetime.now().isoformat()

    # Check if person already exists
    cursor = await db.execute("""
        SELECT g.id, g.content as name
        FROM gluons g
        JOIN links l ON l.source_id = g.id
        JOIN gluons t ON l.target_id = t.id
        WHERE g.type = 'note'
          AND t.type = 'tag' AND t.content = 'person'
          AND g.content = ?
        LIMIT 1
    """, [person.name])
    existing = await cursor.fetchone()

    if existing:
        # Return existing person
        cursor = await db.execute("""
            SELECT id, type, content, source_id, section_id, parent_gluon_id,
                   created_at, updated_at
            FROM gluons WHERE id = ?
        """, [existing[0]])
        row = await cursor.fetchone()
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    # Create new person gluon
    person_id = str(uuid.uuid4())[:8]

    await db.execute("""
        INSERT INTO gluons (id, type, content, created_at, updated_at)
        VALUES (?, 'note', ?, ?, ?)
    """, [person_id, person.name, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [person_id])

    # Get or create 'person' tag and link
    person_tag_id = await get_or_create_tag("person")

    link_id = str(uuid.uuid4())[:8]
    await db.execute("""
        INSERT INTO links (id, source_id, target_id, link_type, created_at)
        VALUES (?, ?, ?, 'tag', ?)
    """, [link_id, person_id, person_tag_id, now])

    await db.commit()

    return {
        "id": person_id,
        "type": "note",
        "content": person.name,
        "source_id": None,
        "section_id": None,
        "parent_gluon_id": None,
        "created_at": now,
        "updated_at": now
    }


@router.get("/person/{name}")
async def find_person_by_name(name: str):
    """
    Find a person gluon by exact name match.
    Returns the person ID if found, null otherwise.
    """
    db = await get_db()

    cursor = await db.execute("""
        SELECT g.id
        FROM gluons g
        JOIN links l ON l.source_id = g.id
        JOIN gluons t ON l.target_id = t.id
        WHERE g.type = 'note'
          AND t.type = 'tag' AND t.content = 'person'
          AND g.content = ?
        LIMIT 1
    """, [name])
    row = await cursor.fetchone()

    if row:
        return {"id": row[0], "found": True, "name": name}
    return {"id": None, "found": False, "name": name}


@router.get("/{gluon_id}")
async def get_gluon(gluon_id: str):
    """
    Get a gluon with all its connections (outgoing refs, tags, backlinks, notes).
    """
    db = await get_db()

    # Get the gluon with source title
    cursor = await db.execute("""
        SELECT g.id, g.type, g.content, g.body, g.completed, g.source_id, g.section_id,
               g.parent_gluon_id, g.created_at, g.updated_at, s.title as source_title
        FROM gluons g
        LEFT JOIN sources s ON g.source_id = s.id
        WHERE g.id = ?
    """, [gluon_id])
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Gluon not found")

    columns = [desc[0] for desc in cursor.description]
    gluon = dict(zip(columns, row))

    # Get outgoing references
    cursor = await db.execute("""
        SELECT g.id, g.type, g.content, g.source_id, g.section_id,
               g.parent_gluon_id, g.created_at, g.updated_at
        FROM gluons g
        JOIN links l ON l.target_id = g.id
        WHERE l.source_id = ? AND l.link_type = 'reference'
    """, [gluon_id])
    rows = await cursor.fetchall()
    gluon["outgoing_refs"] = [dict(zip(columns, r)) for r in rows]

    # Get tags
    cursor = await db.execute("""
        SELECT g.id, g.type, g.content, g.source_id, g.section_id,
               g.parent_gluon_id, g.created_at, g.updated_at
        FROM gluons g
        JOIN links l ON l.target_id = g.id
        WHERE l.source_id = ? AND l.link_type = 'tag'
    """, [gluon_id])
    rows = await cursor.fetchall()
    gluon["tags"] = [dict(zip(columns, r)) for r in rows]

    # Get backlinks (what references this gluon) - include link_type to distinguish tag vs reference
    # Also include body + completed for journal_entry rendering
    cursor = await db.execute("""
        SELECT g.id, g.type, g.content, g.source_id, g.section_id,
               g.parent_gluon_id, g.created_at, g.updated_at,
               l.link_type,
               s.title as source_title,
               g.body, g.completed
        FROM gluons g
        JOIN links l ON l.source_id = g.id
        LEFT JOIN sources s ON g.source_id = s.id
        WHERE l.target_id = ?
    """, [gluon_id])
    rows = await cursor.fetchall()
    backlink_cols = [desc[0] for desc in cursor.description]
    backlinks = [dict(zip(backlink_cols, r)) for r in rows]

    # Fetch tags for each backlink (batch query for efficiency)
    backlink_ids = [b["id"] for b in backlinks]
    backlink_tags = {}  # gluon_id -> [{id, content}, ...]
    if backlink_ids:
        placeholders = ",".join("?" for _ in backlink_ids)
        cursor = await db.execute(f"""
            SELECT l.source_id, t.id, t.content
            FROM links l
            JOIN gluons t ON l.target_id = t.id AND t.type = 'tag'
            WHERE l.source_id IN ({placeholders}) AND l.link_type = 'tag'
        """, backlink_ids)
        for src_id, tag_id, tag_content in await cursor.fetchall():
            backlink_tags.setdefault(src_id, []).append({"id": tag_id, "content": tag_content})

    for b in backlinks:
        b["tags"] = backlink_tags.get(b["id"], [])

    gluon["backlinks"] = backlinks

    # Get child notes (if this is a highlight)
    cursor = await db.execute("""
        SELECT id, type, content, source_id, section_id, parent_gluon_id,
               created_at, updated_at
        FROM gluons
        WHERE parent_gluon_id = ? AND type = 'note'
        ORDER BY created_at
    """, [gluon_id])
    rows = await cursor.fetchall()
    gluon["notes"] = [dict(zip(columns, r)) for r in rows]

    # Get parent gluon (if this note is attached to a highlight)
    if gluon.get("parent_gluon_id"):
        cursor = await db.execute("""
            SELECT g.id, g.type, g.content, g.source_id, g.section_id, g.parent_gluon_id,
                   g.created_at, g.updated_at, s.title as source_title
            FROM gluons g
            LEFT JOIN sources s ON g.source_id = s.id
            WHERE g.id = ?
        """, [gluon["parent_gluon_id"]])
        row = await cursor.fetchone()
        if row:
            parent_cols = [desc[0] for desc in cursor.description]
            gluon["parent_gluon"] = dict(zip(parent_cols, row))

    # Get source relationships (author_of, editor_of, etc.)
    # Uses source_gluon_links table for proper queryable relationships
    cursor = await db.execute("""
        SELECT s.id, s.title, s.author_display, s.year, s.source_type,
               sgl.relationship_type, sgl.position
        FROM source_gluon_links sgl
        JOIN sources s ON sgl.source_id = s.id
        WHERE sgl.gluon_id = ?
        ORDER BY sgl.relationship_type, sgl.position
    """, [gluon_id])
    rows = await cursor.fetchall()
    source_rel_cols = [desc[0] for desc in cursor.description]

    # Group by relationship type
    source_relationships = {}
    for row in rows:
        rel = dict(zip(source_rel_cols, row))
        rel_type = rel.pop("relationship_type")
        rel.pop("position", None)  # Remove position from output
        key = f"{rel_type}_of"  # e.g., "author_of", "editor_of"
        if key not in source_relationships:
            source_relationships[key] = []
        source_relationships[key].append(rel)

    # Add each relationship type as a separate field
    for key, sources in source_relationships.items():
        gluon[key] = sources

    return gluon


@router.post("/notes", response_model=GluonResponse)
async def create_note(note: NoteCreate):
    """
    Create a new note.

    Content can contain:
    - [[references]] to link to other gluons
    - ##tags to categorize

    Notes can be:
    - Attached to a source (source_id)
    - Attached to a highlight (parent_gluon_id)
    - Freestanding (neither)
    """
    db = await get_db()

    # Verify source exists if provided
    if note.source_id:
        cursor = await db.execute(
            "SELECT id FROM sources WHERE id = ?",
            [note.source_id]
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Source not found")

    # Verify parent gluon exists if provided
    if note.parent_gluon_id:
        cursor = await db.execute(
            "SELECT id FROM gluons WHERE id = ?",
            [note.parent_gluon_id]
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Parent gluon not found")

    # Create note
    note_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Strip ##tags from content for storage (tags are stored as links, not in text)
    content_without_tags = re.sub(r'\s*##\w+', '', note.content).strip()

    await db.execute("""
        INSERT INTO gluons (id, type, content, source_id, parent_gluon_id, created_at, updated_at)
        VALUES (?, 'note', ?, ?, ?, ?, ?)
    """, [note_id, content_without_tags, note.source_id, note.parent_gluon_id, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [note_id])

    await db.commit()

    # Process [[refs]] and ##tags to create links (after gluon exists)
    await process_links_in_content(note_id, note.content)

    return {
        "id": note_id,
        "type": "note",
        "content": note.content,
        "source_id": note.source_id,
        "section_id": None,
        "parent_gluon_id": note.parent_gluon_id,
        "created_at": now,
        "updated_at": now
    }


@router.post("/tags", response_model=GluonResponse)
async def create_tag(tag: TagCreate):
    """
    Create a new tag. If tag already exists, returns the existing one.
    """
    db = await get_db()

    normalized = tag.name.lower().strip()

    # Check if exists
    cursor = await db.execute(
        "SELECT id, type, content, source_id, section_id, parent_gluon_id, created_at, updated_at FROM gluons WHERE type = 'tag' AND content = ?",
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
        INSERT INTO gluons (id, type, content, created_at, updated_at)
        VALUES (?, 'tag', ?, ?, ?)
    """, [tag_id, normalized, now, now])

    # Index in FTS
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [tag_id])

    await db.commit()

    return {
        "id": tag_id,
        "type": "tag",
        "content": normalized,
        "source_id": None,
        "section_id": None,
        "parent_gluon_id": None,
        "created_at": now,
        "updated_at": now
    }


@router.post("/{gluon_id}/rename", response_model=GluonResponse)
async def rename_gluon(gluon_id: str, body: GluonRename):
    """
    Rename a tag or person gluon.

    If the new name conflicts with an existing gluon of the same category,
    returns 409 with merge preview information so the frontend can prompt
    the user to merge.
    """
    db = await get_db()

    # Fetch gluon
    cursor = await db.execute(
        "SELECT id, type, content FROM gluons WHERE id = ?",
        [gluon_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Gluon not found")

    gluon_type = row[1]
    old_content = row[2]

    # Determine category and normalize name
    if gluon_type == 'tag':
        category = 'tag'
        new_name = body.name.lower().strip()
    elif gluon_type == 'note':
        # Check if this note is a person (tagged with ##person)
        cursor = await db.execute("""
            SELECT 1 FROM links l
            JOIN gluons t ON l.target_id = t.id
            WHERE l.source_id = ? AND l.link_type = 'tag'
              AND t.type = 'tag' AND t.content = 'person'
        """, [gluon_id])
        if await cursor.fetchone():
            category = 'person'
            new_name = body.name.strip()
        else:
            raise HTTPException(
                status_code=400,
                detail="Only tags and persons can be renamed"
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Only tags and persons can be renamed"
        )

    # No-op if name unchanged
    if new_name == old_content:
        cursor = await db.execute("""
            SELECT id, type, content, source_id, section_id, parent_gluon_id,
                   created_at, updated_at
            FROM gluons WHERE id = ?
        """, [gluon_id])
        row = await cursor.fetchone()
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    # Check for name conflict with another gluon of the same category
    if category == 'tag':
        cursor = await db.execute(
            "SELECT id, content FROM gluons WHERE type = 'tag' AND content = ? AND id != ?",
            [new_name, gluon_id]
        )
    else:
        # Person: case-insensitive match via COLLATE NOCASE
        cursor = await db.execute("""
            SELECT g.id, g.content FROM gluons g
            JOIN links l ON l.source_id = g.id
            JOIN gluons t ON l.target_id = t.id
            WHERE g.type = 'note' AND t.type = 'tag' AND t.content = 'person'
              AND g.content = ? COLLATE NOCASE
              AND g.id != ?
        """, [new_name, gluon_id])

    conflict = await cursor.fetchone()

    if conflict:
        target_id = conflict[0]
        target_content = conflict[1]

        # Compute merge preview counts
        cursor = await db.execute(
            "SELECT COUNT(*) FROM source_gluon_links WHERE gluon_id = ?",
            [gluon_id]
        )
        source_links = (await cursor.fetchone())[0]

        cursor = await db.execute(
            "SELECT COUNT(*) FROM links WHERE target_id = ?",
            [gluon_id]
        )
        note_links = (await cursor.fetchone())[0]

        cursor = await db.execute(
            "SELECT COUNT(*) FROM gluons WHERE parent_gluon_id = ?",
            [gluon_id]
        )
        child_notes = (await cursor.fetchone())[0]

        # Duplicate source links: same source+relationship_type exists for target
        cursor = await db.execute("""
            SELECT COUNT(*) FROM source_gluon_links sgl1
            WHERE sgl1.gluon_id = ?
              AND EXISTS (
                SELECT 1 FROM source_gluon_links sgl2
                WHERE sgl2.gluon_id = ?
                  AND sgl2.source_id = sgl1.source_id
                  AND sgl2.relationship_type = sgl1.relationship_type
              )
        """, [gluon_id, target_id])
        duplicate_links = (await cursor.fetchone())[0]

        raise HTTPException(
            status_code=409,
            detail={
                "detail": "conflict",
                "target": {"id": target_id, "content": target_content},
                "merge_preview": {
                    "source_links": source_links,
                    "note_links": note_links,
                    "child_notes": child_notes,
                    "duplicate_links": duplicate_links,
                }
            }
        )

    # No conflict — update the gluon content
    now = datetime.now().isoformat()

    await db.execute(
        "UPDATE gluons SET content = ?, updated_at = ? WHERE id = ?",
        [new_name, now, gluon_id]
    )

    # Update FTS index
    await db.execute(
        "DELETE FROM gluons_fts WHERE rowid = (SELECT rowid FROM gluons WHERE id = ?)",
        [gluon_id]
    )
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [gluon_id])

    await db.commit()

    # Return updated gluon
    cursor = await db.execute("""
        SELECT id, type, content, source_id, section_id, parent_gluon_id,
               created_at, updated_at
        FROM gluons WHERE id = ?
    """, [gluon_id])
    row = await cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


@router.post("/{gluon_id}/merge")
async def merge_gluon(gluon_id: str, body: GluonMerge):
    """
    Merge this gluon into a target gluon.

    All source links, note links, and child notes transfer to the target.
    Duplicate links (same source + relationship_type) are removed.
    The source gluon is deleted after merge.

    Returns the surviving target gluon with full detail.
    """
    db = await get_db()
    target_id = body.target_id

    # Validate both gluons exist
    cursor = await db.execute(
        "SELECT id, type, content FROM gluons WHERE id = ?",
        [gluon_id]
    )
    source_row = await cursor.fetchone()
    if not source_row:
        raise HTTPException(status_code=404, detail="Source gluon not found")

    cursor = await db.execute(
        "SELECT id, type, content FROM gluons WHERE id = ?",
        [target_id]
    )
    target_row = await cursor.fetchone()
    if not target_row:
        raise HTTPException(status_code=404, detail="Target gluon not found")

    # Validate same type (tag+tag or note+note for persons)
    if source_row[1] != target_row[1]:
        raise HTTPException(
            status_code=400,
            detail="Cannot merge gluons of different types"
        )

    # Step 1: Find and delete duplicate source_gluon_links
    # (same source_id + relationship_type already exists for target)
    cursor = await db.execute("""
        SELECT sgl1.rowid FROM source_gluon_links sgl1
        WHERE sgl1.gluon_id = ?
          AND EXISTS (
            SELECT 1 FROM source_gluon_links sgl2
            WHERE sgl2.gluon_id = ?
              AND sgl2.source_id = sgl1.source_id
              AND sgl2.relationship_type = sgl1.relationship_type
          )
    """, [gluon_id, target_id])
    dup_rowids = [r[0] for r in await cursor.fetchall()]
    if dup_rowids:
        placeholders = ','.join(['?' for _ in dup_rowids])
        await db.execute(
            f"DELETE FROM source_gluon_links WHERE rowid IN ({placeholders})",
            dup_rowids
        )

    # Step 2: Move remaining source_gluon_links to target
    await db.execute(
        "UPDATE source_gluon_links SET gluon_id = ? WHERE gluon_id = ?",
        [target_id, gluon_id]
    )

    # Step 3: Find and delete duplicate note links
    # (same source_id + link_type already points to target)
    cursor = await db.execute("""
        SELECT l1.rowid FROM links l1
        WHERE l1.target_id = ?
          AND EXISTS (
            SELECT 1 FROM links l2
            WHERE l2.target_id = ?
              AND l2.source_id = l1.source_id
              AND l2.link_type = l1.link_type
          )
    """, [gluon_id, target_id])
    dup_rowids = [r[0] for r in await cursor.fetchall()]
    if dup_rowids:
        placeholders = ','.join(['?' for _ in dup_rowids])
        await db.execute(
            f"DELETE FROM links WHERE rowid IN ({placeholders})",
            dup_rowids
        )

    # Step 4: Move remaining incoming links to target
    await db.execute(
        "UPDATE links SET target_id = ? WHERE target_id = ?",
        [target_id, gluon_id]
    )

    # Step 5: Re-parent child notes
    await db.execute(
        "UPDATE gluons SET parent_gluon_id = ? WHERE parent_gluon_id = ?",
        [target_id, gluon_id]
    )

    # Step 6: Delete FTS entry for old gluon
    try:
        await db.execute(
            "DELETE FROM gluons_fts WHERE rowid = (SELECT rowid FROM gluons WHERE id = ?)",
            [gluon_id]
        )
    except (aiosqlite.OperationalError, ValueError):
        pass  # FTS entry may not exist for old data

    # Step 7: Clean up any remaining outgoing links from old gluon
    await db.execute("DELETE FROM links WHERE source_id = ?", [gluon_id])
    await db.execute("DELETE FROM source_gluon_links WHERE gluon_id = ?", [gluon_id])

    # Step 8: Delete old gluon
    await db.execute("DELETE FROM gluons WHERE id = ?", [gluon_id])

    await db.commit()

    # Return the surviving target gluon with full connections
    return await get_gluon(target_id)


@router.patch("/{gluon_id}", response_model=GluonResponse)
async def update_gluon(gluon_id: str, update: NoteUpdate):
    """
    Update a gluon's content. Re-parses [[refs]] and ##tags.
    """
    db = await get_db()

    # Verify gluon exists
    cursor = await db.execute(
        "SELECT id, type FROM gluons WHERE id = ?",
        [gluon_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Gluon not found")

    if row[1] == 'tag':
        raise HTTPException(status_code=400, detail="Cannot update tag content directly")

    now = datetime.now().isoformat()

    # Update content
    await db.execute("""
        UPDATE gluons SET content = ?, updated_at = ? WHERE id = ?
    """, [update.content, now, gluon_id])

    # Update FTS
    await db.execute("""
        DELETE FROM gluons_fts WHERE rowid = (SELECT rowid FROM gluons WHERE id = ?)
    """, [gluon_id])
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        SELECT rowid, content FROM gluons WHERE id = ?
    """, [gluon_id])

    await db.commit()

    # Re-process links
    if update.content:
        await process_links_in_content(gluon_id, update.content)

    # Return updated
    cursor = await db.execute("""
        SELECT id, type, content, source_id, section_id, parent_gluon_id,
               created_at, updated_at
        FROM gluons WHERE id = ?
    """, [gluon_id])
    row = await cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


@router.delete("/{gluon_id}")
async def delete_gluon(gluon_id: str, force: bool = Query(False, description="Force delete even if tag has associations")):
    """
    Delete a gluon and all its links.

    For tags: if the tag has associations (items tagged with it), returns a 409 Conflict
    with association count unless force=true is passed.
    """
    import traceback

    try:
        db = await get_db()

        # Verify gluon exists
        cursor = await db.execute(
            "SELECT id, type, content, rowid FROM gluons WHERE id = ?",
            [gluon_id]
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Gluon not found")

        gluon_id_db, gluon_type, gluon_content, gluon_rowid = row

        # Don't delete highlights through this endpoint
        if gluon_type == 'highlight':
            raise HTTPException(
                status_code=400,
                detail="Use DELETE /highlights/:id for highlights"
            )

        # For tags: check associations unless force=true
        if gluon_type == 'tag' and not force:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM links WHERE target_id = ? AND link_type = 'tag'",
                [gluon_id]
            )
            association_count = (await cursor.fetchone())[0]

            if association_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": f"Tag '{gluon_content}' has {association_count} association(s). Use force=true to delete anyway.",
                        "association_count": association_count,
                        "tag_name": gluon_content
                    }
                )

        # Delete from FTS (use rowid directly, ignore if not in FTS)
        try:
            await db.execute("DELETE FROM gluons_fts WHERE rowid = ?", [gluon_rowid])
        except (aiosqlite.OperationalError, ValueError):
            pass  # FTS entry may not exist for old data

        # Delete links (both directions)
        await db.execute("DELETE FROM links WHERE source_id = ? OR target_id = ?", [gluon_id, gluon_id])

        # Delete the gluon
        await db.execute("DELETE FROM gluons WHERE id = ?", [gluon_id])

        await db.commit()

        return {"deleted": gluon_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"DELETE ERROR for gluon {gluon_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{gluon_id}/link")
async def create_link(gluon_id: str, link: LinkCreate):
    """
    Create a link from this gluon to another gluon.
    """
    db = await get_db()

    # Verify source exists
    cursor = await db.execute("SELECT id FROM gluons WHERE id = ?", [gluon_id])
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Source gluon not found")

    # Verify target exists
    cursor = await db.execute("SELECT id FROM gluons WHERE id = ?", [link.target_id])
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Target gluon not found")

    # Check if link already exists
    cursor = await db.execute("""
        SELECT id FROM links
        WHERE source_id = ? AND target_id = ? AND link_type = ?
    """, [gluon_id, link.target_id, link.link_type])
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail="Link already exists")

    # Create link
    link_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO links (id, source_id, target_id, link_type, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, [link_id, gluon_id, link.target_id, link.link_type, now])

    await db.commit()

    return {"id": link_id, "source_id": gluon_id, "target_id": link.target_id, "link_type": link.link_type}


@router.delete("/{gluon_id}/link/{target_id}")
async def delete_link(gluon_id: str, target_id: str):
    """
    Remove a link between gluons.
    """
    db = await get_db()

    result = await db.execute("""
        DELETE FROM links WHERE source_id = ? AND target_id = ?
    """, [gluon_id, target_id])

    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Link not found")

    return {"deleted": True}


@router.get("/{gluon_id}/backlinks")
async def get_backlinks(gluon_id: str):
    """
    Get all gluons that link to this one, grouped by link type.
    """
    db = await get_db()

    # Verify gluon exists
    cursor = await db.execute("SELECT id FROM gluons WHERE id = ?", [gluon_id])
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Gluon not found")

    # Get all backlinks with source gluon details
    cursor = await db.execute("""
        SELECT g.id, g.type, g.content, g.source_id, g.created_at,
               l.link_type,
               s.title as source_title
        FROM gluons g
        JOIN links l ON l.source_id = g.id
        LEFT JOIN sources s ON g.source_id = s.id
        WHERE l.target_id = ?
        ORDER BY l.link_type, g.created_at DESC
    """, [gluon_id])
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


# --- Batch Operations ---

@router.post("/tags/batch", response_model=List[BatchTagResult])
async def batch_find_or_create_tags(request: BatchTagsRequest):
    """
    Find or create multiple tags at once.

    For each name in the list:
    - If a tag with that name exists (case-insensitive), return its ID
    - If not, create a new tag and return its ID

    Returns array of {name, id} in the same order as input.
    Used by AI suggest to create linked tags from plain text suggestions.
    """
    db = await get_db()
    results = []

    for name in request.names:
        normalized = name.lower().strip()
        if not normalized:
            continue

        # Check if tag exists (case-insensitive)
        cursor = await db.execute(
            "SELECT id, content FROM gluons WHERE type = 'tag' AND LOWER(content) = ?",
            [normalized]
        )
        existing = await cursor.fetchone()

        if existing:
            results.append({"name": existing[1], "id": existing[0]})
        else:
            # Create new tag
            tag_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()

            await db.execute("""
                INSERT INTO gluons (id, type, content, created_at, updated_at)
                VALUES (?, 'tag', ?, ?, ?)
            """, [tag_id, normalized, now, now])

            # Index in FTS
            await db.execute("""
                INSERT INTO gluons_fts (rowid, content)
                SELECT rowid, content FROM gluons WHERE id = ?
            """, [tag_id])

            results.append({"name": normalized, "id": tag_id})

    await db.commit()
    return results


@router.post("/people/batch", response_model=List[BatchPersonResult])
async def batch_find_or_create_people(request: BatchPeopleRequest):
    """
    Find or create multiple people at once.

    For each name in the list:
    - If a person gluon with that name exists, return its ID
    - If not, create a new person gluon (note tagged with ##person) and return its ID

    Returns array of {name, id} in the same order as input.
    Used by AI suggest to create linked authors/editors from plain text suggestions.
    """
    db = await get_db()
    results = []

    # Ensure 'person' tag exists
    person_tag_id = await get_or_create_tag("person")
    now = datetime.now().isoformat()

    for name in request.names:
        trimmed = name.strip()
        if not trimmed:
            continue

        # Check if person already exists (exact match on content, tagged with ##person)
        cursor = await db.execute("""
            SELECT g.id, g.content
            FROM gluons g
            JOIN links l ON l.source_id = g.id
            WHERE g.type = 'note'
              AND l.target_id = ?
              AND l.link_type = 'tag'
              AND g.content = ?
            LIMIT 1
        """, [person_tag_id, trimmed])
        existing = await cursor.fetchone()

        if existing:
            results.append({"name": existing[1], "id": existing[0]})
        else:
            # Create new person gluon
            person_id = str(uuid.uuid4())[:8]

            await db.execute("""
                INSERT INTO gluons (id, type, content, created_at, updated_at)
                VALUES (?, 'note', ?, ?, ?)
            """, [person_id, trimmed, now, now])

            # Index in FTS
            await db.execute("""
                INSERT INTO gluons_fts (rowid, content)
                SELECT rowid, content FROM gluons WHERE id = ?
            """, [person_id])

            # Link to person tag
            link_id = str(uuid.uuid4())[:8]
            await db.execute("""
                INSERT INTO links (id, source_id, target_id, link_type, created_at)
                VALUES (?, ?, ?, 'tag', ?)
            """, [link_id, person_id, person_tag_id, now])

            results.append({"name": trimmed, "id": person_id})

    await db.commit()
    return results
