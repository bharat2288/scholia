"""
Journal Router
==============
API endpoints for the Daily Journal system.

Journal entries are gluons with type='journal_entry'. They have:
- content: Header/title text (imperative for tasks, descriptive for ideas)
- body: Sub-bullets/details (TEXT, stored as newline-separated lines)
- completed: NULL=not a task, 0=pending, 1=done

Entries are categorized via tags (task, idea, social, admin, inbox).
Person mentions use [[Person Name]] refs resolved through the links table.

Endpoints:
- GET    /journal              - List entries grouped by date then category
- POST   /journal              - Create entry
- PATCH  /journal/:id          - Update content/body/tags
- PATCH  /journal/:id/complete - Toggle task completion
- DELETE /journal/:id          - Delete entry
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from collections import defaultdict
import uuid

import re
import aiosqlite

from database import get_db
from routers.gluons import get_or_create_tag, process_links_in_content

router = APIRouter()


# --- Person Matching ---

async def match_person_refs(names: list[str]) -> list[dict]:
    """
    Match person names from classifier output to existing person gluons.

    Tries:
    1. Exact match (COLLATE NOCASE) on person gluon content
    2. Fuzzy match (LIKE %lastname%) where lastname is the last word

    Returns list of {"id": str, "name": str} for matched persons.
    """
    if not names:
        return []

    db = await get_db()

    # Get the 'person' tag ID
    cursor = await db.execute(
        "SELECT id FROM gluons WHERE type = 'tag' AND content = 'person'"
    )
    person_tag = await cursor.fetchone()
    if not person_tag:
        return []

    person_tag_id = person_tag[0]
    matched = []

    for name in names:
        name = name.strip()
        if not name:
            continue

        # Try exact match (case-insensitive)
        cursor = await db.execute("""
            SELECT g.id, g.content
            FROM gluons g
            JOIN links l ON l.source_id = g.id AND l.target_id = ?
            WHERE g.type = 'note' AND l.link_type = 'tag'
              AND g.content = ? COLLATE NOCASE
            LIMIT 1
        """, [person_tag_id, name])
        row = await cursor.fetchone()

        if row:
            matched.append({"id": row[0], "name": row[1]})
            continue

        # Try fuzzy: match on last name (last word in the name string)
        parts = name.split()
        if len(parts) >= 1:
            # Try last word (could be "Rabinow" from "Rabinow, Paul")
            last_part = parts[0].rstrip(",") if "," in name else parts[-1]
            cursor = await db.execute("""
                SELECT g.id, g.content
                FROM gluons g
                JOIN links l ON l.source_id = g.id AND l.target_id = ?
                WHERE g.type = 'note' AND l.link_type = 'tag'
                  AND g.content LIKE ?
                LIMIT 1
            """, [person_tag_id, f"%{last_part}%"])
            row = await cursor.fetchone()

            if row:
                matched.append({"id": row[0], "name": row[1]})

    return matched


# --- Pydantic Models ---

class JournalEntryCreate(BaseModel):
    """Create a new journal entry."""
    content: str = Field(..., min_length=1, description="Header/title text")
    body: Optional[str] = Field(None, description="Sub-bullets/details (newline-separated)")
    category: str = Field("inbox", description="Category: task, idea, social, admin, inbox")
    is_task: bool = Field(False, description="Whether this is a task (gets checkbox)")


class JournalEntryUpdate(BaseModel):
    """Update a journal entry."""
    content: Optional[str] = Field(None, min_length=1)
    body: Optional[str] = None
    category: Optional[str] = None


class JournalCompleteToggle(BaseModel):
    """Toggle task completion."""
    completed: bool


# --- Routes ---

@router.get("/categories")
async def list_journal_categories():
    """
    Return all distinct category tags used by journal entries, with counts.

    Always includes the 5 default categories even if unused.
    """
    db = await get_db()
    defaults = ["task", "idea", "social", "admin", "inbox"]

    cursor = await db.execute("""
        SELECT t.content as name, t.id, COUNT(DISTINCT l.source_id) as count
        FROM links l
        JOIN gluons t ON l.target_id = t.id AND t.type = 'tag'
        JOIN gluons g ON l.source_id = g.id AND g.type = 'journal_entry'
        WHERE l.link_type = 'tag'
        GROUP BY t.id
        ORDER BY count DESC
    """)
    rows = await cursor.fetchall()

    # Build result: defaults first (even if count=0), then any custom tags
    result = []
    seen = set()
    for name, tag_id, count in rows:
        result.append({"name": name, "id": tag_id, "count": count})
        seen.add(name)

    # Ensure defaults appear even with 0 entries
    for d in defaults:
        if d not in seen:
            result.append({"name": d, "id": None, "count": 0})

    return result


@router.get("")
async def list_journal_entries(
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    category: Optional[str] = Query(None, description="Filter by category tag"),
    include_open_tasks: bool = Query(False, description="Include all open tasks regardless of date")
):
    """
    List journal entries grouped by date then category.

    Returns a dict of date -> category -> entries[], sorted reverse chronological.
    When include_open_tasks is True, also returns tasks with completed=0 from any date.
    """
    db = await get_db()

    # Calculate cutoff date
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    # Fetch journal entries with their category tags
    query = """
        SELECT g.id, g.content, g.body, g.completed, g.captured_via,
               g.created_at, g.updated_at,
               GROUP_CONCAT(t.content, ',') as categories,
               GROUP_CONCAT(t.id, ',') as category_ids
        FROM gluons g
        LEFT JOIN links l ON l.source_id = g.id AND l.link_type = 'tag'
        LEFT JOIN gluons t ON l.target_id = t.id AND t.type = 'tag'
        WHERE g.type = 'journal_entry'
          AND g.created_at >= ?
    """
    params: list = [cutoff]

    query += " GROUP BY g.id ORDER BY g.created_at DESC"

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]

    # Fetch person refs (outgoing reference links) for each entry
    entry_ids = [row[0] for row in rows]
    person_refs_map: dict[str, list] = {}
    if entry_ids:
        placeholders = ','.join(['?' for _ in entry_ids])
        ref_cursor = await db.execute(f"""
            SELECT l.source_id, g.id as person_id, g.content as person_name
            FROM links l
            JOIN gluons g ON l.target_id = g.id
            WHERE l.source_id IN ({placeholders})
              AND l.link_type = 'reference'
              AND g.type = 'note'
        """, entry_ids)
        for src_id, person_id, person_name in await ref_cursor.fetchall():
            if src_id not in person_refs_map:
                person_refs_map[src_id] = []
            person_refs_map[src_id].append({"id": person_id, "name": person_name})

    # Group by date then category
    entries: dict[str, dict[str, list]] = {}
    tag_map: dict[str, str] = {}  # category name → tag gluon ID
    ids_to_fix_task: list[str] = []  # entries retagged to task, need completed=0
    ids_to_fix_nontask: list[str] = []  # entries retagged away from task, need completed=NULL

    for row in rows:
        entry = dict(zip(columns, row))

        # Parse categories and their IDs from GROUP_CONCAT
        cats_str = entry.pop("categories", None)
        ids_str = entry.pop("category_ids", None)
        cat_list = [c.strip() for c in cats_str.split(",")] if cats_str else ["inbox"]
        id_list = [i.strip() for i in ids_str.split(",")] if ids_str else []

        entry["tags"] = cat_list
        entry["person_refs"] = person_refs_map.get(entry["id"], [])

        # Build tag_map (category name → gluon ID) for frontend linking
        for name, tid in zip(cat_list, id_list):
            if name not in tag_map:
                tag_map[name] = tid

        # Determine primary category for grouping
        # Priority: task > idea > social > admin > inbox
        priority = ["task", "idea", "social", "admin", "inbox"]
        primary_cat = "inbox"
        for p in priority:
            if p in cat_list:
                primary_cat = p
                break

        # Auto-fix: if tagged 'task' but completed is NULL, set to pending (0)
        # This handles entries retagged to 'task' via the Gluon view
        if primary_cat == "task" and entry["completed"] is None:
            entry["completed"] = 0
            ids_to_fix_task.append(entry["id"])

        # Auto-fix: if NOT tagged 'task' but completed is not NULL, clear it
        if primary_cat != "task" and entry["completed"] is not None:
            entry["completed"] = None
            ids_to_fix_nontask.append(entry["id"])

        # Filter by category if requested
        if category and primary_cat != category:
            continue

        # Extract date (YYYY-MM-DD) from created_at
        date_str = entry["created_at"][:10]

        if date_str not in entries:
            entries[date_str] = {}
        if primary_cat not in entries[date_str]:
            entries[date_str][primary_cat] = []
        entries[date_str][primary_cat].append(entry)

    # Persist auto-fixes to DB (fire-and-forget on GET — keeps data consistent)
    if ids_to_fix_task:
        placeholders = ','.join(['?' for _ in ids_to_fix_task])
        await db.execute(
            f"UPDATE gluons SET completed = 0 WHERE id IN ({placeholders})",
            ids_to_fix_task
        )
        await db.commit()
    if ids_to_fix_nontask:
        placeholders = ','.join(['?' for _ in ids_to_fix_nontask])
        await db.execute(
            f"UPDATE gluons SET completed = NULL WHERE id IN ({placeholders})",
            ids_to_fix_nontask
        )
        await db.commit()

    # Fetch open tasks separately when requested (all pending tasks, any date)
    open_tasks_list: list = []
    if include_open_tasks:
        ot_cursor = await db.execute("""
            SELECT g.id, g.content, g.body, g.completed, g.captured_via,
                   g.created_at, g.updated_at,
                   GROUP_CONCAT(t.content, ',') as categories,
                   GROUP_CONCAT(t.id, ',') as category_ids
            FROM gluons g
            LEFT JOIN links l ON l.source_id = g.id AND l.link_type = 'tag'
            LEFT JOIN gluons t ON l.target_id = t.id AND t.type = 'tag'
            WHERE g.type = 'journal_entry' AND g.completed = 0
            GROUP BY g.id
            ORDER BY g.created_at DESC
        """)
        ot_rows = await ot_cursor.fetchall()
        ot_columns = [desc[0] for desc in ot_cursor.description]

        for row in ot_rows:
            ot_entry = dict(zip(ot_columns, row))
            cats_str = ot_entry.pop("categories", None)
            ids_str = ot_entry.pop("category_ids", None)
            ot_entry["tags"] = [c.strip() for c in cats_str.split(",")] if cats_str else ["task"]
            ot_entry["person_refs"] = person_refs_map.get(ot_entry["id"], [])

            # Build tag_map entries for any tags in open tasks
            if ids_str:
                for name, tid in zip(ot_entry["tags"], ids_str.split(",")):
                    if name not in tag_map:
                        tag_map[name] = tid.strip()

            open_tasks_list.append(ot_entry)

    return {"entries": entries, "tag_map": tag_map, "open_tasks": open_tasks_list}


@router.post("")
async def create_journal_entry(entry: JournalEntryCreate):
    """
    Create a new journal entry.

    1. Creates gluon with type='journal_entry'
    2. Links to category tag
    3. Processes [[refs]] in content
    4. Indexes in FTS (content + body combined)
    """
    db = await get_db()
    now = datetime.now().isoformat()

    # Determine completed value: 0 if task, NULL if not
    completed = 0 if entry.is_task else None

    # Create the journal entry gluon
    entry_id = str(uuid.uuid4())[:8]
    await db.execute("""
        INSERT INTO gluons (id, type, content, body, completed, created_at, updated_at)
        VALUES (?, 'journal_entry', ?, ?, ?, ?, ?)
    """, [entry_id, entry.content, entry.body, completed, now, now])

    # Index in FTS (content + body combined for searchability)
    fts_text = entry.content
    if entry.body:
        fts_text += " " + entry.body
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        VALUES ((SELECT rowid FROM gluons WHERE id = ?), ?)
    """, [entry_id, fts_text])

    await db.commit()

    # Process [[refs]] and ##tags in content (wipes existing links, recreates from content)
    await process_links_in_content(entry_id, entry.content)

    # Add category tag only if not already linked by process_links_in_content
    tag_id = await get_or_create_tag(entry.category)
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

    return {
        "id": entry_id,
        "type": "journal_entry",
        "content": entry.content,
        "body": entry.body,
        "completed": completed,
        "category": entry.category,
        "created_at": now,
        "updated_at": now,
    }


@router.patch("/{entry_id}")
async def update_journal_entry(entry_id: str, update: JournalEntryUpdate):
    """
    Update a journal entry's content, body, or category.
    """
    db = await get_db()

    # Verify entry exists and is a journal_entry
    cursor = await db.execute(
        "SELECT id, type, content, body FROM gluons WHERE id = ?",
        [entry_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    if row[1] != "journal_entry":
        raise HTTPException(status_code=400, detail="Not a journal entry")

    now = datetime.now().isoformat()
    current_content = row[2]
    current_body = row[3]

    # Read existing category BEFORE any link changes (process_links_in_content wipes links)
    category_tags = ["task", "idea", "social", "admin", "inbox"]
    cat_placeholders = ','.join(['?' for _ in category_tags])
    cursor = await db.execute(f"""
        SELECT t.content FROM links l
        JOIN gluons t ON l.target_id = t.id
        WHERE l.source_id = ? AND l.link_type = 'tag' AND t.type = 'tag'
          AND t.content IN ({cat_placeholders})
    """, [entry_id] + category_tags)
    cat_row = await cursor.fetchone()
    existing_category = cat_row[0] if cat_row else "inbox"

    # Update content if provided
    new_content = update.content if update.content is not None else current_content
    new_body = update.body if update.body is not None else current_body

    await db.execute("""
        UPDATE gluons SET content = ?, body = ?, updated_at = ? WHERE id = ?
    """, [new_content, new_body, now, entry_id])

    # Update FTS (content + body)
    fts_text = new_content or ""
    if new_body:
        fts_text += " " + new_body
    await db.execute(
        "DELETE FROM gluons_fts WHERE rowid = (SELECT rowid FROM gluons WHERE id = ?)",
        [entry_id]
    )
    await db.execute("""
        INSERT INTO gluons_fts (rowid, content)
        VALUES ((SELECT rowid FROM gluons WHERE id = ?), ?)
    """, [entry_id, fts_text])

    await db.commit()

    # Re-process [[refs]] and ##tags in content (wipes all links, recreates from content)
    if update.content:
        await process_links_in_content(entry_id, new_content)

    # Derive category from ##tags in content (or explicit override, or fallback to inbox)
    if update.category:
        cat = update.category
    elif update.content is not None:
        # Content was edited — derive category entirely from ##tags
        tag_matches = re.findall(r'##(\w+)', new_content)
        if tag_matches:
            tags = [t.lower() for t in tag_matches]
            priority = ["task", "idea", "social", "admin", "inbox"]
            cat = next((t for t in tags if t in priority), tags[0])
        else:
            cat = "inbox"
    else:
        # Only body changed — keep existing category
        cat = existing_category
    tag_id = await get_or_create_tag(cat)
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

    # Sync completed state when category changes to/from "task"
    if cat == "task" and existing_category != "task":
        await db.execute(
            "UPDATE gluons SET completed = 0 WHERE id = ? AND completed IS NULL",
            [entry_id]
        )
    elif cat != "task" and existing_category == "task":
        await db.execute(
            "UPDATE gluons SET completed = NULL WHERE id = ?",
            [entry_id]
        )

    await db.commit()

    return {
        "id": entry_id,
        "content": new_content,
        "body": new_body,
        "category": cat,
        "updated_at": now,
    }


@router.patch("/{entry_id}/complete")
async def toggle_complete(entry_id: str, body: JournalCompleteToggle):
    """
    Toggle task completion status.
    """
    db = await get_db()

    # Verify entry exists and is a task (completed is not NULL)
    cursor = await db.execute(
        "SELECT id, type, completed FROM gluons WHERE id = ?",
        [entry_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    if row[1] != "journal_entry":
        raise HTTPException(status_code=400, detail="Not a journal entry")
    if row[2] is None:
        raise HTTPException(status_code=400, detail="Not a task entry")

    now = datetime.now().isoformat()
    new_val = 1 if body.completed else 0

    await db.execute(
        "UPDATE gluons SET completed = ?, updated_at = ? WHERE id = ?",
        [new_val, now, entry_id]
    )
    await db.commit()

    return {"id": entry_id, "completed": new_val, "updated_at": now}


@router.delete("/{entry_id}")
async def delete_journal_entry(entry_id: str):
    """
    Delete a journal entry and its links.
    """
    db = await get_db()

    # Verify entry exists
    cursor = await db.execute(
        "SELECT id, type, rowid FROM gluons WHERE id = ?",
        [entry_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    if row[1] != "journal_entry":
        raise HTTPException(status_code=400, detail="Not a journal entry")

    gluon_rowid = row[2]

    # Delete FTS entry
    try:
        await db.execute("DELETE FROM gluons_fts WHERE rowid = ?", [gluon_rowid])
    except (aiosqlite.OperationalError, ValueError):
        pass

    # Delete links (both directions)
    await db.execute(
        "DELETE FROM links WHERE source_id = ? OR target_id = ?",
        [entry_id, entry_id]
    )

    # Delete the gluon
    await db.execute("DELETE FROM gluons WHERE id = ?", [entry_id])

    await db.commit()

    return {"deleted": entry_id}
