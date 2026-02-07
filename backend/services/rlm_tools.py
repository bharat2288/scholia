"""
RLM Tools Service
=================
Tool implementations for the Recursive Language Model agent.

Tools are organized into categories:
1. Library - Search and filter full source collection
2. Session - Manage active sources for research
3. Navigate - Document structure
4. Search - Find content within sources
5. Read - Access source text
6. Cross-Reference - Connect across sources
7. Synthesis - Sub-LLM operations
8. Scholia - Access annotations
9. State - Persist data across turns

Each tool returns a dict with either:
- Success: {"result": ...}
- Error: {"error": True, "error_type": "...", "message": "..."}
"""

import re
import json
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

from database import get_db

# Data directory (relative to backend)
DATA_DIR = Path(__file__).parent.parent.parent / "data"
SOURCES_DIR = DATA_DIR / "sources"


# =============================================================================
# Helper Functions
# =============================================================================

def _estimate_tokens(char_count: int) -> int:
    """Estimate tokens from character count (~4 chars per token for English)."""
    return char_count // 4


def _get_source_text(content_path: str) -> Optional[str]:
    """
    Load source text from content_path.
    Handles both direct file paths and folder paths with extracted.txt.
    """
    if not content_path:
        return None

    path = Path(content_path)

    # Direct file
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None

    # Folder - look for extracted.txt or content.txt
    if path.is_dir():
        # Try various patterns
        patterns = [
            "*--extracted.txt",
            "content.txt",
            "*.txt"
        ]
        for pattern in patterns:
            matches = list(path.glob(pattern))
            if matches:
                try:
                    return matches[0].read_text(encoding="utf-8")
                except Exception:
                    continue

    return None


def _find_page_for_offset(text: str, offset: int) -> Optional[int]:
    """
    Find page number for a character offset using [PAGE n] markers.
    Returns None if no page markers found.
    """
    # Find all page markers with their positions
    page_pattern = r'\[PAGE (\d+)\]'
    pages = [(m.start(), int(m.group(1))) for m in re.finditer(page_pattern, text)]

    if not pages:
        return None

    # Find the page that contains this offset
    current_page = pages[0][1]  # Default to first page
    for pos, page_num in pages:
        if pos > offset:
            break
        current_page = page_num

    return current_page


def _get_section_for_offset(sections: list, offset: int) -> Optional[dict]:
    """Find section containing the given offset."""
    for section in sections:
        if section["start_offset"] <= offset <= section["end_offset"]:
            return section
    return None


def _extract_context(text: str, start: int, end: int, context_chars: int = 50) -> dict:
    """Extract text with surrounding context."""
    context_start = max(0, start - context_chars)
    context_end = min(len(text), end + context_chars)

    return {
        "match": text[start:end],
        "context_before": text[context_start:start],
        "context_after": text[end:context_end]
    }


# =============================================================================
# 1. Library Tools
# =============================================================================

async def library_search(query: str, limit: int = 20) -> dict:
    """
    Search the entire Scholia library using FTS5 full-text search.

    Args:
        query: Search query (keywords)
        limit: Max results (default 20)

    Returns: List of matching sources with relevance scores.
    """
    db = await get_db()

    try:
        # Use FTS5 for full-text search if available
        # First try gluons_fts (searches annotations), then fall back to source metadata
        results = []

        # Search source metadata (title, author)
        cursor = await db.execute("""
            SELECT id, title, source_type, author_display, year, content_path
            FROM sources
            WHERE title LIKE ? OR author_display LIKE ?
            ORDER BY year DESC NULLS LAST
            LIMIT ?
        """, [f"%{query}%", f"%{query}%", limit])

        rows = await cursor.fetchall()

        for row in rows:
            source_id, title, source_type, author, year, content_path = row

            # Get a snippet if we can search the content
            snippet = None
            if content_path:
                text = _get_source_text(content_path)
                if text:
                    # Find first occurrence of query terms
                    for term in query.split():
                        idx = text.lower().find(term.lower())
                        if idx != -1:
                            start = max(0, idx - 50)
                            end = min(len(text), idx + len(term) + 50)
                            snippet = f"...{text[start:end]}..."
                            break

            results.append({
                "id": source_id,
                "title": title,
                "author_display": author,
                "year": year,
                "source_type": source_type,
                "snippet": snippet,
                "score": 1.0  # Basic scoring for now
            })

        return {"result": results}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def library_filter(
    source_type: str = None,
    author: str = None,
    tags: list[str] = None,
    year_min: int = None,
    year_max: int = None,
    limit: int = 50
) -> dict:
    """
    Filter library by metadata criteria.

    Args:
        source_type: 'document', 'web', 'thread', 'video'
        author: Partial match on author_display
        tags: Sources with these tags
        year_min: Published after
        year_max: Published before
        limit: Max results

    Returns: List of matching sources.
    """
    db = await get_db()

    try:
        conditions = []
        params = []

        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)

        if author:
            conditions.append("author_display LIKE ?")
            params.append(f"%{author}%")

        if year_min:
            conditions.append("year >= ?")
            params.append(year_min)

        if year_max:
            conditions.append("year <= ?")
            params.append(year_max)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor = await db.execute(f"""
            SELECT id, title, source_type, author_display, year, content_path
            FROM sources
            WHERE {where_clause}
            ORDER BY year DESC NULLS LAST, title
            LIMIT ?
        """, params + [limit])

        rows = await cursor.fetchall()

        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "title": row[1],
                "source_type": row[2],
                "author_display": row[3],
                "year": row[4]
            })

        # Filter by tags if specified (requires join with gluon links)
        if tags:
            # TODO: Implement tag filtering via source_gluon_links
            pass

        return {"result": results}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def library_stats() -> dict:
    """
    Get overview statistics of the library.

    Returns: Library overview with counts and date range.
    """
    db = await get_db()

    try:
        # Total count
        cursor = await db.execute("SELECT COUNT(*) FROM sources")
        total = (await cursor.fetchone())[0]

        # By type
        cursor = await db.execute("""
            SELECT source_type, COUNT(*)
            FROM sources
            GROUP BY source_type
        """)
        by_type = dict(await cursor.fetchall())

        # Date range
        cursor = await db.execute("""
            SELECT MIN(year), MAX(year) FROM sources WHERE year IS NOT NULL
        """)
        year_row = await cursor.fetchone()

        return {
            "result": {
                "total_sources": total,
                "by_type": by_type,
                "date_range": {
                    "min": year_row[0] if year_row else None,
                    "max": year_row[1] if year_row else None
                }
            }
        }

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def add_to_session(session_id: str, source_id: str, context_type: str = "full") -> dict:
    """
    Load a library source into the active research session.

    Args:
        session_id: Research session ID
        source_id: Source to add
        context_type: 'full', 'excerpt', 'highlights', 'notes'

    Returns: Confirmation with source info and session token total.
    """
    db = await get_db()

    try:
        # Check session exists
        cursor = await db.execute(
            "SELECT id FROM research_sessions WHERE id = ?",
            [session_id]
        )
        if not await cursor.fetchone():
            return {"error": True, "error_type": "not_found", "message": f"Session {session_id} not found"}

        # Check source exists
        cursor = await db.execute(
            "SELECT id, title, content_path FROM sources WHERE id = ?",
            [source_id]
        )
        source_row = await cursor.fetchone()
        if not source_row:
            return {"error": True, "error_type": "not_found", "message": f"Source {source_id} not found"}

        # Check not already in session
        cursor = await db.execute(
            "SELECT session_id FROM session_sources WHERE session_id = ? AND source_id = ?",
            [session_id, source_id]
        )
        if await cursor.fetchone():
            return {"error": True, "error_type": "invalid_params", "message": "Source already in session"}

        # Add to session
        now = datetime.now().isoformat()
        await db.execute("""
            INSERT INTO session_sources (session_id, source_id, context_type, added_at)
            VALUES (?, ?, ?, ?)
        """, [session_id, source_id, context_type, now])

        # Update session timestamp
        await db.execute(
            "UPDATE research_sessions SET updated_at = ? WHERE id = ?",
            [now, session_id]
        )
        await db.commit()

        # Calculate token estimate
        _, title, content_path = source_row
        token_estimate = 0
        if content_path:
            text = _get_source_text(content_path)
            if text:
                token_estimate = _estimate_tokens(len(text))

        # Get session total
        cursor = await db.execute("""
            SELECT s.content_path FROM session_sources ss
            JOIN sources s ON s.id = ss.source_id
            WHERE ss.session_id = ?
        """, [session_id])
        session_total = 0
        for row in await cursor.fetchall():
            if row[0]:
                text = _get_source_text(row[0])
                if text:
                    session_total += _estimate_tokens(len(text))

        return {
            "result": {
                "success": True,
                "source": {
                    "id": source_id,
                    "title": title,
                    "token_estimate": token_estimate
                },
                "session_token_total": session_total
            }
        }

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


# =============================================================================
# 2. Session Tools
# =============================================================================

async def session_sources(session_id: str) -> dict:
    """
    List all sources currently in the active session.

    Args:
        session_id: Research session ID

    Returns: List of session sources with details.
    """
    db = await get_db()

    try:
        cursor = await db.execute("""
            SELECT
                s.id, s.title, s.author_display, s.year, s.source_type,
                s.content_path, ss.context_type, ss.added_at
            FROM session_sources ss
            JOIN sources s ON s.id = ss.source_id
            WHERE ss.session_id = ?
            ORDER BY ss.added_at ASC
        """, [session_id])

        rows = await cursor.fetchall()
        results = []

        for row in rows:
            source_id, title, author, year, source_type, content_path, context_type, added_at = row

            # Calculate token estimate
            token_estimate = 0
            if content_path:
                text = _get_source_text(content_path)
                if text:
                    token_estimate = _estimate_tokens(len(text))

            # Check for annotations
            cursor = await db.execute(
                "SELECT COUNT(*) FROM gluons WHERE source_id = ? AND type = 'highlight'",
                [source_id]
            )
            highlight_count = (await cursor.fetchone())[0]

            cursor = await db.execute(
                "SELECT COUNT(*) FROM gluons WHERE source_id = ? AND type = 'note'",
                [source_id]
            )
            note_count = (await cursor.fetchone())[0]

            results.append({
                "id": source_id,
                "title": title,
                "author_display": author,
                "year": year,
                "source_type": source_type,
                "context_type": context_type,
                "token_estimate": token_estimate,
                "has_highlights": highlight_count > 0,
                "has_notes": note_count > 0,
                "added_at": added_at
            })

        return {"result": results}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def session_stats(session_id: str) -> dict:
    """
    Get statistics for the current session.

    Args:
        session_id: Research session ID

    Returns: Session overview with counts and totals.
    """
    db = await get_db()

    try:
        # Get source count and types
        cursor = await db.execute("""
            SELECT s.source_type, COUNT(*), s.content_path
            FROM session_sources ss
            JOIN sources s ON s.id = ss.source_id
            WHERE ss.session_id = ?
            GROUP BY s.source_type
        """, [session_id])

        type_rows = await cursor.fetchall()
        by_type = {row[0]: row[1] for row in type_rows}
        source_count = sum(by_type.values())

        # Calculate total tokens
        cursor = await db.execute("""
            SELECT s.content_path FROM session_sources ss
            JOIN sources s ON s.id = ss.source_id
            WHERE ss.session_id = ?
        """, [session_id])

        total_tokens = 0
        for row in await cursor.fetchall():
            if row[0]:
                text = _get_source_text(row[0])
                if text:
                    total_tokens += _estimate_tokens(len(text))

        # Count annotations in session sources
        cursor = await db.execute("""
            SELECT COUNT(*) FROM gluons g
            JOIN session_sources ss ON g.source_id = ss.source_id
            WHERE ss.session_id = ? AND g.type = 'highlight'
        """, [session_id])
        highlights_count = (await cursor.fetchone())[0]

        cursor = await db.execute("""
            SELECT COUNT(*) FROM gluons g
            JOIN session_sources ss ON g.source_id = ss.source_id
            WHERE ss.session_id = ? AND g.type = 'note'
        """, [session_id])
        notes_count = (await cursor.fetchone())[0]

        return {
            "result": {
                "source_count": source_count,
                "total_tokens": total_tokens,
                "by_type": by_type,
                "highlights_count": highlights_count,
                "notes_count": notes_count
            }
        }

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def source_info(source_id: str) -> dict:
    """
    Get detailed information about a specific source.

    Args:
        source_id: Source ID

    Returns: Detailed source information.
    """
    db = await get_db()

    try:
        cursor = await db.execute("""
            SELECT id, title, source_type, author_display, year, url,
                   content_path, metadata, created_at
            FROM sources WHERE id = ?
        """, [source_id])

        row = await cursor.fetchone()
        if not row:
            return {"error": True, "error_type": "not_found", "message": f"Source {source_id} not found"}

        source_id, title, source_type, author, year, url, content_path, metadata_json, created_at = row

        # Parse metadata
        metadata = json.loads(metadata_json) if metadata_json else {}

        # Get text stats
        char_count = 0
        token_estimate = 0
        has_toc = False

        if content_path:
            text = _get_source_text(content_path)
            if text:
                char_count = len(text)
                token_estimate = _estimate_tokens(char_count)

        # Count sections
        cursor = await db.execute(
            "SELECT COUNT(*) FROM sections WHERE source_id = ?",
            [source_id]
        )
        section_count = (await cursor.fetchone())[0]
        has_toc = section_count > 0

        # Count annotations
        cursor = await db.execute(
            "SELECT COUNT(*) FROM gluons WHERE source_id = ? AND type = 'highlight'",
            [source_id]
        )
        highlight_count = (await cursor.fetchone())[0]

        cursor = await db.execute(
            "SELECT COUNT(*) FROM gluons WHERE source_id = ? AND type = 'note'",
            [source_id]
        )
        note_count = (await cursor.fetchone())[0]

        return {
            "result": {
                "id": source_id,
                "title": title,
                "source_type": source_type,
                "author_display": author,
                "year": year,
                "url": url,
                "content_path": content_path,
                "token_estimate": token_estimate,
                "char_count": char_count,
                "section_count": section_count,
                "has_toc": has_toc,
                "metadata": metadata,
                "annotations": {
                    "highlights": highlight_count,
                    "notes": note_count
                },
                "created_at": created_at
            }
        }

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def remove_from_session(session_id: str, source_id: str) -> dict:
    """
    Remove a source from the active session.

    Args:
        session_id: Research session ID
        source_id: Source to remove

    Returns: Confirmation with new session token total.
    """
    db = await get_db()

    try:
        # Check link exists
        cursor = await db.execute(
            "SELECT session_id FROM session_sources WHERE session_id = ? AND source_id = ?",
            [session_id, source_id]
        )
        if not await cursor.fetchone():
            return {"error": True, "error_type": "not_found", "message": "Source not in session"}

        # Remove
        await db.execute(
            "DELETE FROM session_sources WHERE session_id = ? AND source_id = ?",
            [session_id, source_id]
        )

        # Update timestamp
        await db.execute(
            "UPDATE research_sessions SET updated_at = ? WHERE id = ?",
            [datetime.now().isoformat(), session_id]
        )
        await db.commit()

        # Calculate new total
        cursor = await db.execute("""
            SELECT s.content_path FROM session_sources ss
            JOIN sources s ON s.id = ss.source_id
            WHERE ss.session_id = ?
        """, [session_id])

        session_total = 0
        for row in await cursor.fetchall():
            if row[0]:
                text = _get_source_text(row[0])
                if text:
                    session_total += _estimate_tokens(len(text))

        return {
            "result": {
                "success": True,
                "removed": source_id,
                "session_token_total": session_total
            }
        }

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


# =============================================================================
# 3. Navigate Tools
# =============================================================================

async def toc(source_id: str) -> dict:
    """
    Get the table of contents / document structure.

    Args:
        source_id: Source ID

    Returns: Hierarchical structure of sections.
    """
    db = await get_db()

    try:
        cursor = await db.execute("""
            SELECT id, title, level, start_offset, end_offset, order_index, parent_id
            FROM sections
            WHERE source_id = ?
            ORDER BY order_index
        """, [source_id])

        rows = await cursor.fetchall()

        if not rows:
            return {"result": []}

        # Get source text for page mapping
        cursor = await db.execute(
            "SELECT content_path FROM sources WHERE id = ?",
            [source_id]
        )
        source_row = await cursor.fetchone()
        text = _get_source_text(source_row[0]) if source_row and source_row[0] else None

        # Build flat list first
        sections = []
        for row in rows:
            sec_id, title, level, start, end, order_idx, parent_id = row

            page_start = _find_page_for_offset(text, start) if text else None

            sections.append({
                "id": sec_id,
                "title": title,
                "level": level,
                "start_offset": start,
                "end_offset": end,
                "page_start": page_start,
                "parent_id": parent_id
            })

        # Build hierarchy
        def build_tree(parent_id=None):
            children = [s for s in sections if s.get("parent_id") == parent_id]
            for child in children:
                child["children"] = build_tree(child["id"])
            return children

        hierarchy = build_tree()

        return {"result": hierarchy}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def sections(source_id: str) -> dict:
    """
    Get flat list of all sections with offsets.

    Args:
        source_id: Source ID

    Returns: Flat section list.
    """
    db = await get_db()

    try:
        cursor = await db.execute("""
            SELECT id, title, level, start_offset, end_offset
            FROM sections
            WHERE source_id = ?
            ORDER BY order_index
        """, [source_id])

        rows = await cursor.fetchall()

        result = [
            {
                "id": row[0],
                "title": row[1],
                "level": row[2],
                "start": row[3],
                "end": row[4]
            }
            for row in rows
        ]

        return {"result": result}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def section_titles(source_id: str) -> dict:
    """
    Get just the section titles (for quick overview).

    Args:
        source_id: Source ID

    Returns: List of section titles in order.
    """
    db = await get_db()

    try:
        cursor = await db.execute("""
            SELECT title FROM sections
            WHERE source_id = ?
            ORDER BY order_index
        """, [source_id])

        rows = await cursor.fetchall()
        titles = [row[0] for row in rows if row[0]]

        return {"result": titles}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


# =============================================================================
# 4. Search Tools
# =============================================================================

async def search(
    pattern: str,
    source_id: str = None,
    session_id: str = None,
    case_sensitive: bool = False,
    limit: int = 50
) -> dict:
    """
    Regex search within source(s).

    Args:
        pattern: Regex pattern
        source_id: Specific source, or None for all session sources
        session_id: Session to search within (if source_id is None)
        case_sensitive: Case sensitive matching
        limit: Max results

    Returns: List of matches with context.
    """
    db = await get_db()

    try:
        # Determine which sources to search
        sources_to_search = []

        if source_id:
            cursor = await db.execute(
                "SELECT id, title, content_path FROM sources WHERE id = ?",
                [source_id]
            )
            row = await cursor.fetchone()
            if row:
                sources_to_search.append(row)
        elif session_id:
            cursor = await db.execute("""
                SELECT s.id, s.title, s.content_path
                FROM session_sources ss
                JOIN sources s ON s.id = ss.source_id
                WHERE ss.session_id = ?
            """, [session_id])
            sources_to_search = await cursor.fetchall()

        if not sources_to_search:
            return {"result": []}

        # Compile regex
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return {"error": True, "error_type": "invalid_params", "message": f"Invalid regex: {e}"}

        # Get sections for context
        async def get_sections_for_source(sid):
            cursor = await db.execute("""
                SELECT id, title, start_offset, end_offset FROM sections WHERE source_id = ?
            """, [sid])
            return [{"id": r[0], "title": r[1], "start_offset": r[2], "end_offset": r[3]} for r in await cursor.fetchall()]

        results = []
        for src_id, src_title, content_path in sources_to_search:
            if not content_path:
                continue

            text = _get_source_text(content_path)
            if not text:
                continue

            sections_list = await get_sections_for_source(src_id)

            for match in regex.finditer(text):
                if len(results) >= limit:
                    break

                start, end = match.start(), match.end()
                page = _find_page_for_offset(text, start)
                section = _get_section_for_offset(sections_list, start)
                context = _extract_context(text, start, end)

                results.append({
                    "source_id": src_id,
                    "source_title": src_title,
                    "match": match.group(),
                    "start_offset": start,
                    "end_offset": end,
                    "page": page,
                    "context_before": context["context_before"],
                    "context_after": context["context_after"],
                    "section": section["title"] if section else None
                })

            if len(results) >= limit:
                break

        return {"result": results}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def find_all(
    term: str,
    source_id: str = None,
    session_id: str = None,
    context_chars: int = 100
) -> dict:
    """
    Find all occurrences of a term with full context.

    Args:
        term: Exact term or phrase
        source_id: Specific source or None for session sources
        session_id: Session to search within
        context_chars: Context characters on each side

    Returns: All occurrences with context.
    """
    # Use search with escaped term as pattern
    escaped_term = re.escape(term)
    return await search(
        pattern=escaped_term,
        source_id=source_id,
        session_id=session_id,
        case_sensitive=False,
        limit=200  # Higher limit for find_all
    )


async def find_mentions(
    concept: str,
    source_ids: list[str] = None,
    session_id: str = None
) -> dict:
    """
    Find where a concept is mentioned across multiple sources.

    Args:
        concept: Term or phrase
        source_ids: Specific sources, or None for all session sources
        session_id: Session to search within

    Returns: Mentions grouped by source.
    """
    db = await get_db()

    try:
        # Determine sources
        if source_ids:
            cursor = await db.execute(f"""
                SELECT id, title, content_path FROM sources
                WHERE id IN ({','.join('?' * len(source_ids))})
            """, source_ids)
        elif session_id:
            cursor = await db.execute("""
                SELECT s.id, s.title, s.content_path
                FROM session_sources ss
                JOIN sources s ON s.id = ss.source_id
                WHERE ss.session_id = ?
            """, [session_id])
        else:
            return {"error": True, "error_type": "invalid_params", "message": "Must provide source_ids or session_id"}

        sources = await cursor.fetchall()

        result = {
            "concept": concept,
            "total_mentions": 0,
            "by_source": {}
        }

        pattern = re.compile(re.escape(concept), re.IGNORECASE)

        for src_id, src_title, content_path in sources:
            if not content_path:
                continue

            text = _get_source_text(content_path)
            if not text:
                continue

            matches = list(pattern.finditer(text))
            if not matches:
                continue

            # Get sections
            cursor = await db.execute("""
                SELECT title, start_offset, end_offset FROM sections WHERE source_id = ?
            """, [src_id])
            sections_list = [{"title": r[0], "start_offset": r[1], "end_offset": r[2]} for r in await cursor.fetchall()]

            # Find sections containing mentions
            sections_with_mentions = set()
            first_match = matches[0]

            for match in matches:
                section = _get_section_for_offset(sections_list, match.start())
                if section:
                    sections_with_mentions.add(section["title"])

            first_context = _extract_context(text, first_match.start(), first_match.end())
            first_page = _find_page_for_offset(text, first_match.start())

            result["by_source"][src_id] = {
                "title": src_title,
                "count": len(matches),
                "first_mention": {
                    "offset": first_match.start(),
                    "page": first_page,
                    "context": f"{first_context['context_before']}{first_context['match']}{first_context['context_after']}"
                },
                "sections_with_mentions": list(sections_with_mentions)
            }
            result["total_mentions"] += len(matches)

        return {"result": result}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


# =============================================================================
# 5. Read Tools
# =============================================================================

async def peek(source_id: str, start: int, end: int) -> dict:
    """
    Read a specific character range from a source.

    Args:
        source_id: Source ID
        start: Start offset (characters)
        end: End offset (characters)

    Returns: Text content with metadata.
    """
    db = await get_db()

    try:
        cursor = await db.execute(
            "SELECT content_path FROM sources WHERE id = ?",
            [source_id]
        )
        row = await cursor.fetchone()

        if not row or not row[0]:
            return {"error": True, "error_type": "not_found", "message": f"Source {source_id} not found or has no content"}

        text = _get_source_text(row[0])
        if not text:
            return {"error": True, "error_type": "internal", "message": "Could not read source text"}

        # Validate range
        start = max(0, start)
        end = min(len(text), end)

        if start >= end:
            return {"error": True, "error_type": "invalid_params", "message": "Invalid range"}

        excerpt = text[start:end]

        # Get page and section info
        page_start = _find_page_for_offset(text, start)
        page_end = _find_page_for_offset(text, end)

        cursor = await db.execute("""
            SELECT title, start_offset, end_offset FROM sections WHERE source_id = ?
        """, [source_id])
        sections_list = [{"title": r[0], "start_offset": r[1], "end_offset": r[2]} for r in await cursor.fetchall()]
        section = _get_section_for_offset(sections_list, start)

        return {
            "result": {
                "source_id": source_id,
                "start": start,
                "end": end,
                "text": excerpt,
                "char_count": len(excerpt),
                "page_start": page_start,
                "page_end": page_end,
                "section": section["title"] if section else None
            }
        }

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def read_section(source_id: str, section_id: str) -> dict:
    """
    Read an entire section by ID.

    Args:
        source_id: Source ID
        section_id: Section ID

    Returns: Full section content.
    """
    db = await get_db()

    try:
        # Get section info
        cursor = await db.execute("""
            SELECT id, title, level, start_offset, end_offset
            FROM sections WHERE id = ? AND source_id = ?
        """, [section_id, source_id])

        section_row = await cursor.fetchone()
        if not section_row:
            return {"error": True, "error_type": "not_found", "message": f"Section {section_id} not found"}

        sec_id, title, level, start, end = section_row

        # Get text
        cursor = await db.execute(
            "SELECT content_path FROM sources WHERE id = ?",
            [source_id]
        )
        source_row = await cursor.fetchone()

        if not source_row or not source_row[0]:
            return {"error": True, "error_type": "not_found", "message": "Source has no content"}

        text = _get_source_text(source_row[0])
        if not text:
            return {"error": True, "error_type": "internal", "message": "Could not read source text"}

        section_text = text[start:end]

        # Get page info
        page_start = _find_page_for_offset(text, start)
        page_end = _find_page_for_offset(text, end)

        # Get subsections
        cursor = await db.execute("""
            SELECT id FROM sections WHERE parent_id = ?
        """, [section_id])
        subsections = [r[0] for r in await cursor.fetchall()]

        return {
            "result": {
                "source_id": source_id,
                "section_id": sec_id,
                "section_title": title,
                "level": level,
                "text": section_text,
                "char_count": len(section_text),
                "page_start": page_start,
                "page_end": page_end,
                "subsections": subsections
            }
        }

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def read_around(source_id: str, offset: int, context_chars: int = 500) -> dict:
    """
    Read text surrounding a specific offset.

    Args:
        source_id: Source ID
        offset: Center point
        context_chars: Characters before and after

    Returns: Text centered on offset.
    """
    start = max(0, offset - context_chars)
    end = offset + context_chars

    result = await peek(source_id, start, end)

    if "result" in result:
        result["result"]["center_offset"] = offset

    return result


async def page_for_offset(source_id: str, offset: int) -> dict:
    """
    Convert character offset to page number.

    Args:
        source_id: Source ID
        offset: Character offset

    Returns: Page information.
    """
    db = await get_db()

    try:
        cursor = await db.execute(
            "SELECT content_path FROM sources WHERE id = ?",
            [source_id]
        )
        row = await cursor.fetchone()

        if not row or not row[0]:
            return {"error": True, "error_type": "not_found", "message": f"Source {source_id} not found"}

        text = _get_source_text(row[0])
        if not text:
            return {"error": True, "error_type": "internal", "message": "Could not read source text"}

        page = _find_page_for_offset(text, offset)

        # Get section
        cursor = await db.execute("""
            SELECT title, start_offset, end_offset FROM sections WHERE source_id = ?
        """, [source_id])
        sections_list = [{"title": r[0], "start_offset": r[1], "end_offset": r[2]} for r in await cursor.fetchall()]
        section = _get_section_for_offset(sections_list, offset)

        return {
            "result": {
                "offset": offset,
                "page": page,
                "section": section["title"] if section else None
            }
        }

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


# =============================================================================
# 6. Scholia Tools (Annotations)
# =============================================================================

async def get_highlights(source_id: str, color: str = None) -> dict:
    """
    Get user's highlights for a source.

    Args:
        source_id: Source ID
        color: Filter by color ('yellow', 'blue', 'green', 'pink')

    Returns: List of highlights.
    """
    db = await get_db()

    try:
        conditions = ["source_id = ?", "type = 'highlight'"]
        params = [source_id]

        if color:
            conditions.append("color = ?")
            params.append(color)

        cursor = await db.execute(f"""
            SELECT id, content, start_offset, end_offset, color, created_at
            FROM gluons
            WHERE {' AND '.join(conditions)}
            ORDER BY start_offset
        """, params)

        rows = await cursor.fetchall()

        # Get source text for page mapping
        cursor = await db.execute(
            "SELECT content_path FROM sources WHERE id = ?",
            [source_id]
        )
        source_row = await cursor.fetchone()
        text = _get_source_text(source_row[0]) if source_row and source_row[0] else None

        results = []
        for row in rows:
            hl_id, content, start, end, hl_color, created_at = row

            page = _find_page_for_offset(text, start) if text else None

            # Check for attached note
            cursor = await db.execute(
                "SELECT content FROM gluons WHERE parent_gluon_id = ? AND type = 'note'",
                [hl_id]
            )
            note_row = await cursor.fetchone()

            results.append({
                "id": hl_id,
                "text": content,
                "color": hl_color,
                "start_offset": start,
                "end_offset": end,
                "page": page,
                "note": note_row[0] if note_row else None,
                "created_at": created_at
            })

        return {"result": results}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def get_notes(source_id: str) -> dict:
    """
    Get user's notes (gluons) for a source.

    Args:
        source_id: Source ID

    Returns: List of notes.
    """
    db = await get_db()

    try:
        cursor = await db.execute("""
            SELECT g.id, g.content, g.parent_gluon_id, g.created_at
            FROM gluons g
            WHERE g.source_id = ? AND g.type = 'note'
            ORDER BY g.created_at DESC
        """, [source_id])

        rows = await cursor.fetchall()

        results = []
        for row in rows:
            note_id, content, parent_id, created_at = row

            # Get tags for this note
            cursor = await db.execute("""
                SELECT g.content FROM links l
                JOIN gluons g ON l.target_id = g.id
                WHERE l.source_id = ? AND l.link_type = 'tag' AND g.type = 'tag'
            """, [note_id])
            tags = [r[0] for r in await cursor.fetchall()]

            results.append({
                "id": note_id,
                "content": content,
                "type": "note",
                "tags": tags,
                "parent_highlight_id": parent_id,
                "created_at": created_at
            })

        return {"result": results}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def get_tags(session_id: str) -> dict:
    """
    Get all tags used in session sources.

    Args:
        session_id: Research session ID

    Returns: Tags with usage counts.
    """
    db = await get_db()

    try:
        cursor = await db.execute("""
            SELECT DISTINCT g.id, g.content
            FROM gluons g
            JOIN links l ON g.id = l.target_id
            JOIN gluons note ON l.source_id = note.id
            JOIN session_sources ss ON note.source_id = ss.source_id
            WHERE ss.session_id = ? AND g.type = 'tag' AND l.link_type = 'tag'
        """, [session_id])

        tag_rows = await cursor.fetchall()

        results = []
        for tag_id, tag_content in tag_rows:
            # Count usage
            cursor = await db.execute("""
                SELECT COUNT(DISTINCT l.source_id)
                FROM links l
                WHERE l.target_id = ? AND l.link_type = 'tag'
            """, [tag_id])
            usage_count = (await cursor.fetchone())[0]

            # Get sources using this tag
            cursor = await db.execute("""
                SELECT DISTINCT note.source_id
                FROM links l
                JOIN gluons note ON l.source_id = note.id
                WHERE l.target_id = ? AND l.link_type = 'tag'
            """, [tag_id])
            source_ids = [r[0] for r in await cursor.fetchall()]

            results.append({
                "id": tag_id,
                "name": tag_content,
                "usage_count": usage_count,
                "sources": source_ids
            })

        return {"result": results}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


# =============================================================================
# 7. State Tools
# =============================================================================

# In-memory state per session (could be persisted to DB later)
_session_state: dict[str, dict] = {}


async def store(session_id: str, key: str, value: Any) -> dict:
    """
    Save a value for later retrieval.

    Args:
        session_id: Research session ID
        key: Identifier
        value: JSON-serializable value

    Returns: Confirmation.
    """
    try:
        if session_id not in _session_state:
            _session_state[session_id] = {}

        _session_state[session_id][key] = {
            "value": value,
            "stored_at": datetime.now().isoformat()
        }

        return {
            "result": {
                "success": True,
                "key": key,
                "type": type(value).__name__,
                "size": len(value) if hasattr(value, "__len__") else 1
            }
        }

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def recall(session_id: str, key: str) -> dict:
    """
    Retrieve a previously stored value.

    Args:
        session_id: Research session ID
        key: Identifier

    Returns: Stored value or not found.
    """
    try:
        if session_id not in _session_state or key not in _session_state[session_id]:
            return {
                "result": {
                    "key": key,
                    "found": False
                }
            }

        data = _session_state[session_id][key]
        return {
            "result": {
                "key": key,
                "found": True,
                "value": data["value"],
                "stored_at": data["stored_at"]
            }
        }

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def quote_save(
    session_id: str,
    source_id: str,
    start_offset: int,
    end_offset: int,
    context_note: str = None,
    deployment_note: str = None
) -> dict:
    """
    Save a quote for later synthesis.

    Args:
        session_id: Research session ID
        source_id: Source ID
        start_offset: Quote start
        end_offset: Quote end
        context_note: Why this quote matters
        deployment_note: How to use this quote

    Returns: Saved quote with metadata.
    """
    db = await get_db()

    try:
        # Get source info and text
        cursor = await db.execute(
            "SELECT title, content_path FROM sources WHERE id = ?",
            [source_id]
        )
        row = await cursor.fetchone()

        if not row:
            return {"error": True, "error_type": "not_found", "message": f"Source {source_id} not found"}

        title, content_path = row
        text = _get_source_text(content_path) if content_path else None

        if not text:
            return {"error": True, "error_type": "internal", "message": "Could not read source text"}

        quote_text = text[start_offset:end_offset]
        page = _find_page_for_offset(text, start_offset)

        # Store in session state
        if session_id not in _session_state:
            _session_state[session_id] = {}

        if "quotes" not in _session_state[session_id]:
            _session_state[session_id]["quotes"] = []

        quote_id = f"quote_{len(_session_state[session_id]['quotes']) + 1}"

        quote_data = {
            "id": quote_id,
            "source_id": source_id,
            "source_title": title,
            "text": quote_text,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "page": page,
            "context_note": context_note,
            "deployment_note": deployment_note,
            "saved_at": datetime.now().isoformat()
        }

        _session_state[session_id]["quotes"].append(quote_data)

        return {"result": quote_data}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def quotes_get(session_id: str, source_id: str = None, concept: str = None) -> dict:
    """
    Retrieve saved quotes.

    Args:
        session_id: Research session ID
        source_id: Filter by source
        concept: Filter by deployment_note content

    Returns: List of saved quotes.
    """
    try:
        if session_id not in _session_state or "quotes" not in _session_state[session_id]:
            return {"result": []}

        quotes = _session_state[session_id]["quotes"]

        # Apply filters
        if source_id:
            quotes = [q for q in quotes if q["source_id"] == source_id]

        if concept:
            quotes = [q for q in quotes if concept.lower() in (q.get("deployment_note") or "").lower()]

        return {"result": quotes}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


# =============================================================================
# 8. Synthesis Tools (Sub-LLM Operations)
# =============================================================================

async def sub_query(prompt: str, context: str, model: str = "haiku") -> dict:
    """
    Delegate a question to a sub-LLM with specific context.

    Args:
        prompt: Question or instruction
        context: Text to analyze
        model: 'haiku', 'sonnet', 'opus' — defaults to cheap/fast

    Returns: Sub-LLM response.
    """
    from services.chat import ChatService

    try:
        chat = ChatService(verbose=False)

        # Map model names
        model_map = {
            "haiku": "claude-haiku",
            "sonnet": "claude-sonnet",
            "opus": "claude-opus"
        }
        model_id = model_map.get(model, "claude-haiku")

        messages = [{"role": "user", "content": prompt}]

        result = await chat.chat(
            model_id=model_id,
            messages=messages,
            context=context,
            max_tokens=2000
        )

        if result.get("success"):
            return {
                "result": {
                    "response": result.get("content"),
                    "model_used": result.get("model"),
                    "input_tokens": result.get("usage", {}).get("input_tokens"),
                    "output_tokens": result.get("usage", {}).get("output_tokens")
                }
            }
        else:
            return {"error": True, "error_type": "internal", "message": result.get("error")}

    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}


async def summarize(source_id: str, section_id: str = None, max_length: int = 500) -> dict:
    """
    Create a summary of a source or section.

    Args:
        source_id: Source ID
        section_id: Specific section, or None for full source
        max_length: Target summary length in words

    Returns: Summary with metadata.
    """
    # Get text
    if section_id:
        result = await read_section(source_id, section_id)
        if "error" in result:
            return result
        text = result["result"]["text"]
        section_title = result["result"]["section_title"]
    else:
        result = await source_info(source_id)
        if "error" in result:
            return result

        db = await get_db()
        cursor = await db.execute(
            "SELECT content_path FROM sources WHERE id = ?",
            [source_id]
        )
        row = await cursor.fetchone()
        text = _get_source_text(row[0]) if row and row[0] else None
        section_title = None

    if not text:
        return {"error": True, "error_type": "internal", "message": "No text to summarize"}

    # Truncate if too long (keep first and last parts)
    max_chars = 50000
    if len(text) > max_chars:
        half = max_chars // 2
        text = text[:half] + "\n\n[...content truncated...]\n\n" + text[-half:]

    # Use sub_query for summarization
    prompt = f"""Summarize the following text in about {max_length} words.
Include:
1. A brief summary paragraph
2. 3-5 key points as bullet points

Focus on the main arguments and conclusions."""

    result = await sub_query(prompt, text, model="sonnet")

    if "error" in result:
        return result

    return {
        "result": {
            "source_id": source_id,
            "section": section_title,
            "summary": result["result"]["response"],
            "word_count": len(result["result"]["response"].split())
        }
    }


async def extract_claims(
    source_id: str,
    section_id: str = None,
    start_offset: int = None,
    end_offset: int = None
) -> dict:
    """
    Extract assertions and claims from a passage.

    Args:
        source_id: Source ID
        section_id: Specific section
        start_offset: Start of passage
        end_offset: End of passage

    Returns: List of claims with citations.
    """
    # Get text
    if section_id:
        result = await read_section(source_id, section_id)
        if "error" in result:
            return result
        text = result["result"]["text"]
    elif start_offset is not None and end_offset is not None:
        result = await peek(source_id, start_offset, end_offset)
        if "error" in result:
            return result
        text = result["result"]["text"]
    else:
        return {"error": True, "error_type": "invalid_params", "message": "Must provide section_id or start/end offsets"}

    prompt = """Extract the main claims and assertions from this text.
For each claim, provide:
1. The claim itself (as a concise statement)
2. The type: 'empirical' (data-backed), 'theoretical' (conceptual), or 'methodological'
3. A brief context quote that supports it

Format as a JSON array:
[{"claim": "...", "type": "...", "supporting_quote": "..."}]"""

    result = await sub_query(prompt, text, model="sonnet")

    if "error" in result:
        return result

    # Try to parse JSON from response
    try:
        response_text = result["result"]["response"]
        # Find JSON array in response
        json_match = re.search(r'\[[\s\S]*\]', response_text)
        if json_match:
            claims = json.loads(json_match.group())
            return {"result": claims}
        else:
            return {"result": [{"raw_response": response_text}]}
    except json.JSONDecodeError:
        return {"result": [{"raw_response": result["result"]["response"]}]}


async def extract_examples(source_id: str, concept: str = None) -> dict:
    """
    Find empirical examples in a source.

    Args:
        source_id: Source ID
        concept: Optional: examples of specific concept

    Returns: List of examples.
    """
    result = await source_info(source_id)
    if "error" in result:
        return result

    db = await get_db()
    cursor = await db.execute(
        "SELECT content_path FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()
    text = _get_source_text(row[0]) if row and row[0] else None

    if not text:
        return {"error": True, "error_type": "internal", "message": "No text to analyze"}

    # Truncate if needed
    if len(text) > 50000:
        text = text[:25000] + "\n[...]\n" + text[-25000:]

    concept_clause = f" related to '{concept}'" if concept else ""

    prompt = f"""Find concrete examples and case studies{concept_clause} in this text.
For each example, provide:
1. A brief description
2. The type: 'empirical' (real data/study), 'illustrative' (hypothetical), or 'historical'
3. A brief quote that introduces it

Format as JSON array:
[{{"description": "...", "type": "...", "quote": "..."}}]"""

    result = await sub_query(prompt, text, model="sonnet")

    if "error" in result:
        return result

    try:
        response_text = result["result"]["response"]
        json_match = re.search(r'\[[\s\S]*\]', response_text)
        if json_match:
            examples = json.loads(json_match.group())
            return {"result": examples}
        else:
            return {"result": [{"raw_response": response_text}]}
    except json.JSONDecodeError:
        return {"result": [{"raw_response": result["result"]["response"]}]}


# =============================================================================
# Tool Registry
# =============================================================================

TOOLS = {
    # Library
    "library_search": library_search,
    "library_filter": library_filter,
    "library_stats": library_stats,
    "add_to_session": add_to_session,

    # Session
    "session_sources": session_sources,
    "session_stats": session_stats,
    "source_info": source_info,
    "remove_from_session": remove_from_session,

    # Navigate
    "toc": toc,
    "sections": sections,
    "section_titles": section_titles,

    # Search
    "search": search,
    "find_all": find_all,
    "find_mentions": find_mentions,

    # Read
    "peek": peek,
    "read_section": read_section,
    "read_around": read_around,
    "page_for_offset": page_for_offset,

    # Scholia
    "get_highlights": get_highlights,
    "get_notes": get_notes,
    "get_tags": get_tags,

    # State
    "store": store,
    "recall": recall,
    "quote_save": quote_save,
    "quotes_get": quotes_get,

    # Synthesis
    "sub_query": sub_query,
    "summarize": summarize,
    "extract_claims": extract_claims,
    "extract_examples": extract_examples,
}


async def execute_tool(tool_name: str, session_id: str, **kwargs) -> dict:
    """
    Execute a tool by name with given arguments.

    Args:
        tool_name: Name of the tool
        session_id: Current session ID (injected into tools that need it)
        **kwargs: Tool-specific arguments

    Returns: Tool result or error.
    """
    if tool_name not in TOOLS:
        return {"error": True, "error_type": "not_found", "message": f"Unknown tool: {tool_name}"}

    tool_fn = TOOLS[tool_name]

    # Inject session_id for tools that need it
    import inspect
    sig = inspect.signature(tool_fn)
    if "session_id" in sig.parameters:
        kwargs["session_id"] = session_id

    try:
        return await tool_fn(**kwargs)
    except TypeError as e:
        return {"error": True, "error_type": "invalid_params", "message": str(e)}
    except Exception as e:
        return {"error": True, "error_type": "internal", "message": str(e)}
