"""
Sources Router
==============
API endpoints for source management (documents, web clips, threads, media, notes).

Endpoints:
- GET    /sources          - List all sources
- GET    /sources/:id      - Get single source
- POST   /sources/import   - Import new PDF/EPUB (fresh extraction)
- POST   /sources/import-processed - Import pre-processed files
- POST   /sources/clip-url - Clip content from URL (web sources)
- POST   /sources/clip-tweet - Clip tweet/thread from Twitter/X
- POST   /sources/clip-video - Clip video transcript from YouTube
- GET    /sources/:id/analyses - Get analyses for a source
- GET    /sources/:id/analyze/stream - Run analyses via SSE
- GET    /sources/analysis-types - List available analysis types
- POST   /sources/estimate-analysis-cost - Pre-flight cost estimate
- POST   /sources/scan-documents-folder - Scan documents folder
- POST   /sources/refresh  - Scan and import new sources
- PATCH  /sources/:id      - Update source metadata
- DELETE /sources/:id      - Delete source
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Query, Form
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path
import uuid
import re
import json
import hashlib
import logging
from datetime import datetime

from database import get_db
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# AI metadata suggestion service
from services.metadata_ai import suggest_metadata, format_suggestions_for_review

logger = logging.getLogger(__name__)

router = APIRouter()


def normalize_url(url: str) -> str:
    """
    Normalize URL for de-duplication.

    - Removes www. prefix
    - Removes tracking parameters (utm_*, fbclid, etc.)
    - Removes trailing slashes
    - Lowercases scheme and host
    - Removes fragments (#...)
    """
    parsed = urlparse(url.strip())

    # Lowercase scheme and host
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()

    # Remove www. prefix
    if host.startswith('www.'):
        host = host[4:]

    # Remove tracking parameters
    tracking_params = {
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
        'fbclid', 'gclid', 'ref', 'source', 'mc_cid', 'mc_eid'
    }
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        filtered = {k: v for k, v in params.items() if k.lower() not in tracking_params}
        query = urlencode(filtered, doseq=True) if filtered else ''
    else:
        query = ''

    # Remove trailing slash from path (but keep root /)
    path = parsed.path.rstrip('/') if parsed.path != '/' else '/'

    # Rebuild URL without fragment
    normalized = urlunparse((scheme, host, path, '', query, ''))

    return normalized

# Data paths
DATA_DIR = Path(__file__).parent.parent.parent / "data"
SOURCES_DIR = DATA_DIR / "sources"
DOCUMENTS_DIR = SOURCES_DIR / "documents"
WEB_DIR = SOURCES_DIR / "web"
THREADS_DIR = SOURCES_DIR / "threads"
VIDEOS_DIR = SOURCES_DIR / "videos"
REPOS_DIR = SOURCES_DIR / "repos"
NOTES_DIR = SOURCES_DIR / "notes"

# Legacy path (for migration period - check both locations)
LEGACY_DOCUMENTS_DIR = DATA_DIR / "documents"

# AI metadata suggestion tracking file
SUGGESTIONS_FILE = DATA_DIR / "ai_metadata_suggestions.json"


# =============================================================================
# Suggestion Tracking Utilities
# =============================================================================

def _load_suggestions_history() -> dict:
    """Load the AI metadata suggestions history from JSON file."""
    if not SUGGESTIONS_FILE.exists():
        return {}
    try:
        return json.loads(SUGGESTIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {}


def _save_suggestions_history(history: dict) -> None:
    """Save the AI metadata suggestions history to JSON file."""
    SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUGGESTIONS_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def _record_suggestion(source_id: str, suggestions: dict) -> None:
    """
    Record AI suggestions for a source.

    Args:
        source_id: The source ID
        suggestions: Dict of field -> suggested value
    """
    history = _load_suggestions_history()
    history[source_id] = {
        "suggested_at": datetime.now().isoformat(),
        "suggestions": suggestions
    }
    _save_suggestions_history(history)


def _check_suggestion_applied(
    source_id: str,
    current_metadata: dict,
    history: dict
) -> tuple[bool, list[str]]:
    """
    Check if previous suggestions have been applied (fields are now filled).

    Args:
        source_id: The source ID
        current_metadata: Current metadata from database
        history: The suggestions history dict

    Returns:
        (all_applied, empty_fields) - whether all suggested fields are filled,
        and list of fields that are still empty
    """
    if source_id not in history:
        return False, []

    past_suggestions = history[source_id].get("suggestions", {})
    if not past_suggestions:
        return True, []

    empty_fields = []
    for field in past_suggestions.keys():
        current_value = current_metadata.get(field)
        # Consider field "filled" if it has any non-empty value
        if not current_value or (isinstance(current_value, str) and not current_value.strip()):
            empty_fields.append(field)

    return len(empty_fields) == 0, empty_fields


def _get_documents_dir() -> Path:
    """Get the documents directory, preferring new location but falling back to legacy."""
    if DOCUMENTS_DIR.exists():
        return DOCUMENTS_DIR
    if LEGACY_DOCUMENTS_DIR.exists():
        return LEGACY_DOCUMENTS_DIR
    # Default to new location (will be created)
    return DOCUMENTS_DIR


@router.get("")
async def list_sources(
    source_type: Optional[str] = Query(None, description="Filter by source type: document, web, thread, media"),
    keyword: Optional[str] = Query(None, description="Filter by keyword gluon ID"),
    q: Optional[str] = Query(None, description="Search query (matches title, author, keywords)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    List all sources in the library.
    Optionally filter by source type, keyword, or search query.
    Includes annotation counts (note_count, highlight_count) for filtering.
    Includes keywords array with tag gluon info for display.
    """
    db = await get_db()

    # Query with annotation counts via LEFT JOIN
    query = """
        SELECT s.*,
            COUNT(CASE WHEN g.type = 'note' THEN 1 END) as note_count,
            COUNT(CASE WHEN g.type = 'highlight' THEN 1 END) as highlight_count
        FROM sources s
        LEFT JOIN gluons g ON g.source_id = s.id
    """
    conditions = []
    params = []

    if source_type:
        conditions.append("s.source_type = ?")
        params.append(source_type)

    if keyword:
        # Filter by tag gluon ID (unified tag system)
        conditions.append("""
            s.id IN (
                SELECT source_id FROM source_gluon_links
                WHERE gluon_id = ? AND relationship_type = 'tag'
            )
        """)
        params.append(keyword)

    if q:
        # Search by title, author, or tags
        conditions.append("""
            (s.title LIKE ? OR s.author_display LIKE ? OR s.id IN (
                SELECT sgl.source_id FROM source_gluon_links sgl
                JOIN gluons kg ON sgl.gluon_id = kg.id
                WHERE sgl.relationship_type = 'tag'
                AND kg.content LIKE ?
            ))
        """)
        search_pattern = f"%{q}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " GROUP BY s.id ORDER BY s.updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    # Convert rows to dicts
    columns = [desc[0] for desc in cursor.description]
    source_ids = []
    sources = []
    for row in rows:
        source_dict = dict(zip(columns, row))
        source_ids.append(source_dict["id"])
        # Parse JSON fields
        if source_dict.get("reading_position"):
            try:
                source_dict["reading_position"] = json.loads(source_dict["reading_position"])
            except (json.JSONDecodeError, TypeError):
                pass
        if source_dict.get("metadata"):
            try:
                source_dict["metadata"] = json.loads(source_dict["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        sources.append(source_dict)

    # Fetch tags and authors for all sources in one query each
    if source_ids:
        placeholders = ",".join(["?" for _ in source_ids])

        # Fetch tags
        tag_cursor = await db.execute(f"""
            SELECT sgl.source_id, sgl.gluon_id, g.content, sgl.position
            FROM source_gluon_links sgl
            JOIN gluons g ON sgl.gluon_id = g.id
            WHERE sgl.relationship_type = 'tag'
            AND sgl.source_id IN ({placeholders})
            ORDER BY sgl.source_id, sgl.position
        """, source_ids)
        tag_rows = await tag_cursor.fetchall()

        # Group tags by source_id (both full objects and just IDs)
        tags_by_source = {}
        tag_ids_by_source = {}
        for source_id, gluon_id, content, position in tag_rows:
            if source_id not in tags_by_source:
                tags_by_source[source_id] = []
                tag_ids_by_source[source_id] = []
            tags_by_source[source_id].append({
                "id": gluon_id,
                "content": content,
            })
            tag_ids_by_source[source_id].append(gluon_id)

        # Fetch authors (linked person gluons)
        author_cursor = await db.execute(f"""
            SELECT sgl.source_id, sgl.gluon_id, g.content, sgl.position
            FROM source_gluon_links sgl
            JOIN gluons g ON sgl.gluon_id = g.id
            WHERE sgl.relationship_type = 'author'
            AND sgl.source_id IN ({placeholders})
            ORDER BY sgl.source_id, sgl.position
        """, source_ids)
        author_rows = await author_cursor.fetchall()

        # Group authors by source_id
        authors_by_source = {}
        for source_id, gluon_id, content, position in author_rows:
            if source_id not in authors_by_source:
                authors_by_source[source_id] = []
            authors_by_source[source_id].append({
                "id": gluon_id,
                "content": content,
            })

        # Fetch editors (linked person gluons)
        editor_cursor = await db.execute(f"""
            SELECT sgl.source_id, sgl.gluon_id, g.content, sgl.position
            FROM source_gluon_links sgl
            JOIN gluons g ON sgl.gluon_id = g.id
            WHERE sgl.relationship_type = 'editor'
            AND sgl.source_id IN ({placeholders})
            ORDER BY sgl.source_id, sgl.position
        """, source_ids)
        editor_rows = await editor_cursor.fetchall()

        # Group editors by source_id
        editors_by_source = {}
        for source_id, gluon_id, content, position in editor_rows:
            if source_id not in editors_by_source:
                editors_by_source[source_id] = []
            editors_by_source[source_id].append({
                "id": gluon_id,
                "content": content,
            })

        # Attach tags, authors, and editors to sources
        for source in sources:
            source["tags"] = tags_by_source.get(source["id"], [])
            # Legacy: keep keywords array for backward compatibility, mirrors tags
            source["keywords"] = source["tags"]
            # Include keyword_gluon_ids for MetadataEditModal
            tag_ids = tag_ids_by_source.get(source["id"], [])
            source["keyword_gluon_ids"] = json.dumps(tag_ids) if tag_ids else None
            # Include linked authors array
            source["authors"] = authors_by_source.get(source["id"], [])
            # Include linked editors array (fallback when no authors)
            source["editors"] = editors_by_source.get(source["id"], [])

    return sources


# ============================================================
# Source Analysis (Video Analysis Pipeline)
# ============================================================
# Static routes MUST come before /{source_id} to avoid path capture

class AnalysisCostRequest(BaseModel):
    """Request body for pre-flight cost estimate."""
    transcript_content: str
    analysis_types: List[str] = ["summary", "key_claims"]
    model_id: str = "claude-opus"


@router.get("/analysis-types")
async def get_analysis_types():
    """List available analysis types."""
    from services.analysis_engine import list_available_analyses
    return list_available_analyses()


@router.post("/estimate-analysis-cost")
async def estimate_analysis_cost(request: AnalysisCostRequest):
    """
    Pre-flight cost estimate for running analyses on a transcript.
    Used by the AddSourceModal to show cost before confirming.
    """
    from services.analysis_engine import estimate_cost
    estimate = estimate_cost(
        request.transcript_content,
        request.analysis_types,
        request.model_id,
    )
    return {
        "analyses": estimate.analyses,
        "total_estimated_cost": estimate.total_estimated_cost,
        "model_display_name": estimate.model_display_name,
        "word_count": estimate.word_count,
    }


@router.get("/{source_id}")
async def get_source(source_id: str):
    """Get a single source by ID."""
    db = await get_db()

    cursor = await db.execute(
        "SELECT * FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    columns = [desc[0] for desc in cursor.description]
    source_dict = dict(zip(columns, row))

    # Parse JSON fields
    if source_dict.get("reading_position"):
        try:
            source_dict["reading_position"] = json.loads(source_dict["reading_position"])
        except (json.JSONDecodeError, TypeError):
            pass
    if source_dict.get("metadata"):
        try:
            source_dict["metadata"] = json.loads(source_dict["metadata"])
        except (json.JSONDecodeError, TypeError):
            source_dict["metadata"] = {}
    else:
        source_dict["metadata"] = {}

    # Fetch linked gluon IDs AND content from source_gluon_links
    # This ensures TagInput/PersonInput see tags/authors as linked with their display names
    for rel_type, meta_field, content_field in [
        ("tag", "keyword_gluon_ids", "keywords"),
        ("author", "author_gluon_ids", "authors"),
        ("editor", "editor_gluon_ids", "editors")
    ]:
        cursor = await db.execute("""
            SELECT sgl.gluon_id, g.content
            FROM source_gluon_links sgl
            JOIN gluons g ON g.id = sgl.gluon_id
            WHERE sgl.source_id = ? AND sgl.relationship_type = ?
            ORDER BY sgl.position
        """, [source_id, rel_type])
        rows = await cursor.fetchall()

        if rows:
            gluon_ids = [row[0] for row in rows]
            # Return as array of {id, content} objects for frontend
            content_objects = [{"id": row[0], "content": row[1]} for row in rows]

            source_dict["metadata"][meta_field] = json.dumps(gluon_ids)
            source_dict[meta_field] = json.dumps(gluon_ids)
            # Also provide the content array for display
            source_dict[content_field] = content_objects

    return source_dict


@router.post("/scan-documents-folder")
async def scan_documents_folder():
    """
    Scan the documents folder structure and return available files.
    Structure: documents/{AuthorYear}/AuthorYear--method/AuthorYear--method--extracted.txt
    """
    docs_dir = _get_documents_dir()
    if not docs_dir.exists():
        raise HTTPException(status_code=404, detail=f"Documents folder not found: {docs_dir}")

    available = []
    for doc_folder in docs_dir.iterdir():
        if not doc_folder.is_dir():
            continue

        folder_name = doc_folder.name

        # Find method subfolder (prefer dots-ocr, then marker, then pymupdf, then tesseract)
        method_folder = None
        method = None
        for m in ["dots-ocr", "marker", "pymupdf", "tesseract"]:
            mf = doc_folder / f"{folder_name}--{m}"
            if mf.exists():
                method_folder = mf
                method = m
                break

        if not method_folder:
            continue

        # Find extracted.txt
        extracted_path = method_folder / f"{folder_name}--{method}--extracted.txt"
        if not extracted_path.exists():
            continue

        # Find PDF
        pdf_path = doc_folder / f"{folder_name}.pdf"

        # Parse metadata from folder name (Author_Year_Title)
        metadata = _parse_folder_name(folder_name)

        available.append({
            "folder_name": folder_name,
            "extracted_path": str(extracted_path),
            "pdf_path": str(pdf_path) if pdf_path.exists() else None,
            "method": method,
            **metadata
        })

    return {
        "count": len(available),
        "files": available
    }


@router.post("/import-processed")
async def import_processed(
    txt_path: str,
    pdf_path: Optional[str] = None,
    title: Optional[str] = None,
    author: Optional[str] = None,
    year: Optional[int] = None
):
    """
    Import a pre-processed file.

    Args:
        txt_path: Path to the extracted .txt file
        pdf_path: Optional path to the original PDF
        title, author, year: Optional metadata overrides
    """
    txt_file = Path(txt_path)
    if not txt_file.exists():
        raise HTTPException(status_code=404, detail=f"Text file not found: {txt_path}")

    # Parse metadata from filename if not provided
    metadata = _parse_folder_name(txt_file.stem.replace("--extracted", "").rsplit("--", 1)[0])

    title = title or metadata.get("title", txt_file.stem)
    author = author or metadata.get("author")
    year = year or metadata.get("year")

    # Generate source ID
    source_id = str(uuid.uuid4())[:8]

    # Read the text content to extract sections
    content = txt_file.read_text(encoding="utf-8")
    sections = _parse_sections(content, source_id)

    # Validate PDF path if provided
    original_path = None
    if pdf_path:
        pdf_file = Path(pdf_path)
        if pdf_file.exists():
            original_path = str(pdf_file)

    # Build metadata JSON
    source_metadata = {
        "doc_type": "article",
        "file_type": "pdf",
        "original_path": original_path,
    }

    # Insert into database
    db = await get_db()
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO sources (id, title, source_type, author_display, year,
                            content_path, metadata, created_at, updated_at)
        VALUES (?, ?, 'document', ?, ?, ?, ?, ?, ?)
    """, [
        source_id, title, author, year,
        str(txt_file), json.dumps(source_metadata), now, now
    ])

    # Insert sections
    for i, section in enumerate(sections):
        section_id = f"{source_id}-s{i}"
        await db.execute("""
            INSERT INTO sections (id, source_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, source_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"], i, None
        ])

    # Index in FTS
    await db.execute("""
        INSERT INTO sources_fts (rowid, title, author_display)
        SELECT rowid, title, author_display FROM sources WHERE id = ?
    """, [source_id])

    await db.commit()

    return {
        "id": source_id,
        "title": title,
        "author": author,
        "year": year,
        "sections_count": len(sections),
        "content_path": str(txt_file)
    }


# ============================================================
# Web Clipping
# ============================================================

class ClipUrlRequest(BaseModel):
    """Request body for URL clipping."""
    url: str
    title: Optional[str] = None  # Override extracted title


@router.post("/clip-url")
async def clip_url_endpoint(request: ClipUrlRequest):
    """
    Clip content from a URL and add as a web source.

    Uses trafilatura to extract the main article content,
    stripping navigation, ads, and other non-content elements.

    Args:
        url: The URL to clip
        title: Optional title override (uses extracted title if not provided)

    Returns:
        The created source with id, title, content stats
    """
    from services.web_clipper import clip_url
    import httpx

    # Ensure web directory exists
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    # Normalize URL for de-duplication
    normalized_url = normalize_url(request.url)

    # Check if URL already clipped (prevent duplicates)
    # Check both original and normalized URLs for backwards compatibility
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, title, url FROM sources
           WHERE source_type = 'web'
           AND (url = ? OR url = ?)""",
        [request.url, normalized_url]
    )
    existing = await cursor.fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"URL already clipped as '{existing[1]}' (id: {existing[0]})"
        )

    try:
        # Clip the URL - now returns structured sections
        result = await clip_url(request.url, WEB_DIR)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch URL: HTTP {e.response.status_code}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch URL: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e)
        )

    # Use override title if provided
    title = request.title or result.title

    # Parse year from date if available
    year = None
    if result.date:
        # Try to extract year from date string
        year_match = re.search(r'\b(19|20)\d{2}\b', result.date)
        if year_match:
            year = int(year_match.group())

    # Generate source ID
    source_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Use sections from the clip result (already parsed from XML)
    sections = result.sections

    # Build metadata JSON (keep original URL here for reference)
    source_metadata = {
        "sitename": result.sitename,
        "description": result.description,
        "clipped_at": now,
        "word_count": result.word_count,
        "original_url": request.url,  # Keep original for display if different
    }
    # Remove None values
    source_metadata = {k: v for k, v in source_metadata.items() if v is not None}

    # Insert into database (store normalized URL for de-duplication)
    await db.execute("""
        INSERT INTO sources (id, title, source_type, author_display, year,
                            url, content_path, metadata, created_at, updated_at)
        VALUES (?, ?, 'web', ?, ?, ?, ?, ?, ?, ?)
    """, [
        source_id, title, result.author or result.sitename, year,  # Fallback to sitename if no author
        normalized_url, result.content_path, json.dumps(source_metadata),
        now, now
    ])

    # Insert sections
    for i, section in enumerate(sections):
        section_id = f"{source_id}-s{i}"
        await db.execute("""
            INSERT INTO sections (id, source_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, source_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"], i, None
        ])

    # Index in FTS
    await db.execute("""
        INSERT INTO sources_fts (rowid, title, author_display)
        SELECT rowid, title, author_display FROM sources WHERE id = ?
    """, [source_id])

    await db.commit()

    return {
        "id": source_id,
        "title": title,
        "author": result.author,
        "year": year,
        "url": normalized_url,
        "source_type": "web",
        "sitename": result.sitename,
        "word_count": result.word_count,
        "sections_count": len(sections),
        "content_path": result.content_path
    }


# ============================================================
# Tweet/Thread Clipping
# ============================================================

class ClipTweetRequest(BaseModel):
    """Request body for tweet clipping."""
    url: str


@router.post("/clip-tweet")
async def clip_tweet_endpoint(request: ClipTweetRequest):
    """
    Clip a tweet or thread from Twitter/X.

    Uses FxTwitter API to fetch tweet content without API auth.
    Extracts full thread if the tweet is part of one.
    Detects Twitter Articles (long-form content) and saves as 'web' source type.

    Args:
        url: Twitter/X URL (twitter.com/user/status/123 or x.com/user/status/123)

    Returns:
        The created source with id, title, thread stats
    """
    from services.tweet_clipper import clip_tweet, extract_tweet_info
    import httpx
    import shutil

    # Ensure directories exist
    THREADS_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    # Extract tweet ID for de-duplication
    try:
        tweet_id, username = extract_tweet_info(request.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check if tweet already clipped (by tweet_id, thread_tweet_ids, or URL)
    # For threads, we store root_tweet_id but user may clip with any tweet URL from the thread
    # Check both 'thread' and 'web' source types (articles are saved as 'web')
    db = await get_db()

    # First check by tweet_id (handles root tweet or single tweet)
    cursor = await db.execute("""
        SELECT id, title, source_type FROM sources
        WHERE source_type IN ('thread', 'web')
        AND json_extract(metadata, '$.tweet_id') = ?
    """, [tweet_id])
    existing = await cursor.fetchone()

    # Check if this tweet_id is in any thread's tweet list
    if not existing:
        cursor = await db.execute("""
            SELECT id, title, source_type FROM sources
            WHERE source_type = 'thread'
            AND json_extract(metadata, '$.thread_tweet_ids') LIKE ?
        """, [f'%"{tweet_id}"%'])
        existing = await cursor.fetchone()

    # Also check by URL (handles re-clipping exact same URL)
    if not existing:
        cursor = await db.execute("""
            SELECT id, title, source_type FROM sources
            WHERE source_type IN ('thread', 'web')
            AND url = ?
        """, [request.url])
        existing = await cursor.fetchone()

    if existing:
        source_type_label = "article" if existing[2] == 'web' else "tweet"
        raise HTTPException(
            status_code=409,
            detail=f"Already clipped as {source_type_label}: '{existing[1]}' (id: {existing[0]})"
        )

    try:
        # Clip the tweet/thread (initially saves to THREADS_DIR)
        result = await clip_tweet(request.url, THREADS_DIR)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch tweet: HTTP {e.response.status_code}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch tweet: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e)
        )

    # Determine source type and move files if needed
    source_type = result.source_type  # 'thread' or 'web'
    content_path = result.content_path

    if source_type == 'web' and result.is_article:
        # Move article from threads/ to web/
        source_folder = Path(content_path).parent
        folder_name = source_folder.name
        dest_folder = WEB_DIR / folder_name

        if source_folder.exists() and source_folder.parent == THREADS_DIR:
            # Move the entire folder
            shutil.move(str(source_folder), str(dest_folder))
            # Update content_path to new location
            content_path = str(dest_folder / Path(content_path).name)
            logger.info(f"Moved article to web/: {folder_name}")

    # Parse year from timestamp if available
    year = None
    if result.timestamp:
        year_match = re.search(r'\b(19|20)\d{2}\b', result.timestamp)
        if year_match:
            year = int(year_match.group())

    # Generate source ID
    source_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Build metadata JSON
    source_metadata = {
        "tweet_id": result.tweet_id,
        "author_handle": result.author_handle,
        "thread_length": result.thread_length,
        "thread_tweet_ids": result.thread_tweet_ids if result.thread_tweet_ids else None,
        "is_reply": result.is_reply,
        "parent_tweet_id": result.parent_tweet_id,
        "clipped_at": now,
        "nitter_instance": result.nitter_instance,
        "is_article": result.is_article,
    }
    # Remove None values and empty lists
    source_metadata = {k: v for k, v in source_metadata.items() if v is not None and v != []}

    # Insert into database with appropriate source_type
    await db.execute("""
        INSERT INTO sources (id, title, source_type, author_display, year,
                            url, content_path, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        source_id, result.title, source_type, result.author_display, year,
        request.url, content_path, json.dumps(source_metadata),
        now, now
    ])

    # Insert sections
    for i, section in enumerate(result.sections):
        section_id = f"{source_id}-s{i}"
        await db.execute("""
            INSERT INTO sections (id, source_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, source_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"], i, None
        ])

    # Index in FTS
    await db.execute("""
        INSERT INTO sources_fts (rowid, title, author_display)
        SELECT rowid, title, author_display FROM sources WHERE id = ?
    """, [source_id])

    await db.commit()

    response = {
        "id": source_id,
        "title": result.title,
        "author": result.author_display,
        "author_handle": result.author_handle,
        "year": year,
        "url": request.url,
        "source_type": source_type,
        "is_article": result.is_article,
        "thread_length": result.thread_length,
        "is_reply": result.is_reply,
        "sections_count": len(result.sections),
        "media_count": len([m for m in result.media if m.get('downloaded')]),
        "content_path": content_path
    }

    # Include warning if present (e.g., possible incomplete thread)
    if result.warning:
        response["warning"] = result.warning

    return response


# ============================================================
# Video Clipping
# ============================================================

class ClipVideoRequest(BaseModel):
    """Request body for video clipping."""
    url: str


@router.post("/clip-video")
async def clip_video_endpoint(request: ClipVideoRequest):
    """
    Clip a video transcript from YouTube (or other platforms).

    Uses youtube-transcript-api to fetch transcripts without API auth.
    Uses yt-dlp for metadata (title, channel, duration).

    Args:
        url: Video URL (youtube.com, youtu.be, vimeo.com)

    Returns:
        The created source with id, title, transcript stats
    """
    from services.video_clipper import clip_video, extract_video_id

    # Ensure videos directory exists
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    # Extract video ID for de-duplication
    try:
        video_id, platform = extract_video_id(request.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check if video already clipped (by video_id in metadata)
    db = await get_db()
    cursor = await db.execute("""
        SELECT id, title FROM sources
        WHERE source_type = 'media'
        AND json_extract(metadata, '$.video_id') = ?
    """, [video_id])
    existing = await cursor.fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Video already clipped as '{existing[1]}' (id: {existing[0]})"
        )

    try:
        # Clip the video transcript
        result = await clip_video(request.url, VIDEOS_DIR)
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Missing dependency: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Video clipping failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clip video: {str(e)}"
        )

    # Parse year from publish_date if available
    year = None
    if result.publish_date:
        year_match = re.search(r'\b(19|20)\d{2}\b', result.publish_date)
        if year_match:
            year = int(year_match.group())

    # Generate source ID
    source_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Build metadata JSON
    source_metadata = {
        "video_id": result.video_id,
        "platform": result.platform,
        "channel": result.channel,
        "duration_seconds": result.metadata.duration_seconds,
        "duration_formatted": result.duration_formatted,
        "view_count": result.metadata.view_count,
        "like_count": result.metadata.like_count,
        "thumbnail_url": result.metadata.thumbnail_url,
        "description": result.metadata.description,
        "word_count": result.word_count,
        "segment_count": result.segment_count,
        "clipped_at": now,
    }
    # Remove None values
    source_metadata = {k: v for k, v in source_metadata.items() if v is not None}

    # Insert into database (source_type='media' for videos)
    await db.execute("""
        INSERT INTO sources (id, title, source_type, author_display, year,
                            url, content_path, metadata, created_at, updated_at)
        VALUES (?, ?, 'media', ?, ?, ?, ?, ?, ?, ?)
    """, [
        source_id, result.title, result.channel, year,
        request.url, result.content_path, json.dumps(source_metadata),
        now, now
    ])

    # Insert sections
    for i, section in enumerate(result.sections):
        section_id = f"{source_id}-s{i}"
        await db.execute("""
            INSERT INTO sections (id, source_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, source_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"], i, None
        ])

    # Index in FTS
    await db.execute("""
        INSERT INTO sources_fts (rowid, title, author_display)
        SELECT rowid, title, author_display FROM sources WHERE id = ?
    """, [source_id])

    # Store transcript cues (time → offset mapping for sync playback)
    if result.transcript_cues:
        for cue in result.transcript_cues:
            await db.execute("""
                INSERT INTO transcript_cues
                    (source_id, cue_index, start_time, end_time, text, start_offset, end_offset)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                source_id, cue.cue_index, cue.start_time, cue.end_time,
                cue.text, cue.start_offset, cue.end_offset
            ])

    await db.commit()

    return {
        "id": source_id,
        "title": result.title,
        "channel": result.channel,
        "year": year,
        "url": request.url,
        "source_type": "media",
        "platform": result.platform,
        "duration": result.duration_formatted,
        "word_count": result.word_count,
        "segment_count": result.segment_count,
        "sections_count": len(result.sections),
        "content_path": result.content_path
    }


@router.get("/{source_id}/analyses")
async def get_source_analyses(source_id: str):
    """Get all analyses for a source."""
    db = await get_db()

    cursor = await db.execute(
        "SELECT id FROM sources WHERE id = ?", [source_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Source not found")

    cursor = await db.execute(
        """SELECT id, analysis_type, display_name, content, model,
                  cost_usd, tokens_input, tokens_output, created_at
           FROM source_analyses
           WHERE source_id = ?
           ORDER BY created_at""",
        [source_id]
    )
    rows = await cursor.fetchall()
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


@router.get("/{source_id}/analyze/stream")
async def analyze_source_stream(
    source_id: str,
    types: str = Query("summary,key_claims", description="Comma-separated analysis types"),
    model: str = Query("claude-opus", description="Model ID from CHAT_MODELS"),
):
    """
    Run analyses on a source via Server-Sent Events.

    Streams progress events as each analysis runs. Each completed analysis
    is saved to source_analyses table before the done event is sent.

    SSE event format:
        {stage, status, type, current, total, message, cost_usd?}
    """
    import asyncio
    from fastapi.responses import StreamingResponse
    from services.analysis_engine import run_analysis_sync, ANALYSIS_PROMPTS

    db = await get_db()

    # Verify source exists and get content
    cursor = await db.execute(
        "SELECT content_path, title, source_type, metadata FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    content_path, title, source_type, metadata_str = row

    if not content_path or not Path(content_path).exists():
        raise HTTPException(status_code=404, detail="Source content file not found")

    transcript_content = Path(content_path).read_text(encoding="utf-8")

    # Parse metadata for prompt context
    metadata = {}
    if metadata_str:
        try:
            metadata = json.loads(metadata_str)
        except (json.JSONDecodeError, TypeError):
            pass
    metadata["title"] = title

    # Parse requested analysis types
    analysis_types = [t.strip() for t in types.split(",") if t.strip()]
    analysis_types = [t for t in analysis_types if t in ANALYSIS_PROMPTS]

    if not analysis_types:
        raise HTTPException(status_code=400, detail="No valid analysis types specified")

    async def event_generator():
        def send_event(data: dict):
            return f"data: {json.dumps(data)}\n\n"

        total = len(analysis_types)
        total_cost = 0.0

        for i, analysis_type in enumerate(analysis_types):
            display_name = ANALYSIS_PROMPTS[analysis_type]["display_name"]

            yield send_event({
                "stage": "analysis",
                "status": "running",
                "type": analysis_type,
                "display_name": display_name,
                "current": i + 1,
                "total": total,
                "message": f"Running {display_name}... ({i + 1}/{total})",
            })

            try:
                # Run LLM call in thread pool (synchronous API call)
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda at=analysis_type: run_analysis_sync(
                        at, transcript_content, model, metadata
                    ),
                )

                # Delete any existing analysis of same type (replace on re-run)
                await db.execute(
                    "DELETE FROM source_analyses WHERE source_id = ? AND analysis_type = ?",
                    [source_id, result.analysis_type],
                )

                # Save to database
                analysis_id = str(uuid.uuid4())
                await db.execute("""
                    INSERT INTO source_analyses
                        (id, source_id, analysis_type, display_name, content,
                         model, cost_usd, tokens_input, tokens_output)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    analysis_id, source_id, result.analysis_type,
                    result.display_name, result.content, result.model,
                    result.cost_usd, result.tokens_input, result.tokens_output,
                ])
                await db.commit()

                total_cost += result.cost_usd

                yield send_event({
                    "stage": "analysis",
                    "status": "done",
                    "type": analysis_type,
                    "display_name": display_name,
                    "current": i + 1,
                    "total": total,
                    "cost_usd": result.cost_usd,
                    "tokens_input": result.tokens_input,
                    "tokens_output": result.tokens_output,
                    "message": f"Completed {display_name}",
                })

            except Exception as e:
                logger.error(f"Analysis {analysis_type} failed: {e}", exc_info=True)
                yield send_event({
                    "stage": "analysis",
                    "status": "error",
                    "type": analysis_type,
                    "display_name": display_name,
                    "current": i + 1,
                    "total": total,
                    "message": f"Failed: {str(e)}",
                })

        yield send_event({
            "stage": "complete",
            "status": "success",
            "total_cost_usd": round(total_cost, 4),
            "message": "All analyses complete",
        })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# Transcript Cue Regeneration (backfill for existing videos)
# ============================================================

@router.post("/{source_id}/regenerate-cues")
async def regenerate_cues(source_id: str):
    """
    Re-fetch transcript from YouTube and align cues to existing content.
    Used to backfill transcript_cues for videos clipped before sync was added.
    """
    from services.video_clipper import (
        _fetch_youtube_transcript, align_cues_to_content
    )

    db = await get_db()

    # Get source and verify it's a media type
    cursor = await db.execute(
        "SELECT source_type, metadata, content_path FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    source_type, metadata_json, content_path = row
    if source_type != "media":
        raise HTTPException(status_code=400, detail="Not a media source")

    metadata = json.loads(metadata_json) if metadata_json else {}
    video_id = metadata.get("video_id")
    if not video_id:
        raise HTTPException(status_code=400, detail="No video_id in metadata")

    # Read existing content
    content = Path(content_path).read_text(encoding="utf-8")

    # Re-fetch transcript segments
    segments, _ = _fetch_youtube_transcript(video_id)

    # Align to existing content
    cues = align_cues_to_content(segments, content)

    # Delete old cues and insert new
    await db.execute("DELETE FROM transcript_cues WHERE source_id = ?", [source_id])
    for cue in cues:
        await db.execute("""
            INSERT INTO transcript_cues
                (source_id, cue_index, start_time, end_time, text, start_offset, end_offset)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            source_id, cue.cue_index, cue.start_time, cue.end_time,
            cue.text, cue.start_offset, cue.end_offset
        ])
    await db.commit()

    return {
        "source_id": source_id,
        "cues_generated": len(cues),
        "segments_total": len(segments),
    }


# ============================================================
# GitHub Repository Clipping
# ============================================================

class TriageRepoRequest(BaseModel):
    """Request body for repository triage (stage 1)."""
    url: str
    intent: Optional[str] = None
    model_id: str = "claude-haiku"


class ClipRepoRequest(BaseModel):
    """Request body for repository import (stage 2)."""
    url: str
    selected_files: List[str]
    intent: Optional[str] = None
    summary: Optional[str] = None
    interest_tags: Optional[List[str]] = None


class AppendRepoFilesRequest(BaseModel):
    """Request body for appending files to an existing repo source."""
    file_paths: List[str]


@router.post("/triage-repo")
async def triage_repo_endpoint(request: TriageRepoRequest):
    """
    Stage 1: Analyze a GitHub repository and recommend interesting files.

    Fetches repo metadata, file tree, and README, then uses LLM to
    recommend which files are worth reading.

    Returns: repo metadata, summary, recommended files, interest tags
    """
    from services.repo_clipper import (
        parse_github_url, fetch_repo_metadata, fetch_file_tree,
        fetch_readme, triage_repo,
    )
    import httpx as _httpx

    # Parse URL
    try:
        owner, repo = parse_github_url(request.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check for duplicate
    db = await get_db()
    cursor = await db.execute("""
        SELECT id, title FROM sources
        WHERE source_type = 'repo'
        AND json_extract(metadata, '$.full_name') = ?
    """, [f"{owner}/{repo}"])
    existing = await cursor.fetchone()

    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Already imported: '{existing[1]}' (id: {existing[0]})"
        )

    # Fetch repo data from GitHub
    try:
        repo_meta = await fetch_repo_metadata(owner, repo)
        tree = await fetch_file_tree(owner, repo, repo_meta.default_branch)
        readme = await fetch_readme(owner, repo)
    except _httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Repository not found: {owner}/{repo}")
        if e.response.status_code == 403:
            raise HTTPException(status_code=429, detail="GitHub API rate limit exceeded. Set GITHUB_TOKEN for higher limits.")
        raise HTTPException(status_code=400, detail=f"GitHub API error: {e.response.status_code}")

    # Run LLM triage
    try:
        result = await triage_repo(repo_meta, tree, readme, request.intent, request.model_id)
    except Exception as e:
        logger.error(f"Triage LLM failed: {e}")
        raise HTTPException(status_code=500, detail=f"Triage analysis failed: {str(e)}")

    return {
        "repo": {
            "owner": result.repo.owner,
            "name": result.repo.name,
            "full_name": result.repo.full_name,
            "description": result.repo.description,
            "default_branch": result.repo.default_branch,
            "stars": result.repo.stars,
            "language": result.repo.language,
            "topics": result.repo.topics,
            "license": result.repo.license,
        },
        "summary": result.summary,
        "recommended_files": [
            {
                "path": f.path,
                "reason": f.reason,
                "priority": f.priority,
                "size_bytes": f.size_bytes,
            }
            for f in result.recommended_files
        ],
        "interest_tags": result.interest_tags,
        "total_files": result.total_files,
        "file_tree": result.file_tree,
    }


@router.post("/clip-repo")
async def clip_repo_endpoint(request: ClipRepoRequest):
    """
    Stage 2: Import selected files from a GitHub repository.

    Fetches file contents, assembles extracted.txt, creates source + sections.
    """
    from services.repo_clipper import (
        parse_github_url, fetch_repo_metadata, fetch_readme,
        import_repo_files,
    )
    import httpx as _httpx

    # Parse URL
    try:
        owner, repo = parse_github_url(request.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not request.selected_files:
        raise HTTPException(status_code=400, detail="No files selected")

    # Fetch metadata + README for content assembly
    try:
        repo_meta = await fetch_repo_metadata(owner, repo)
        readme = await fetch_readme(owner, repo)
    except _httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Repository not found: {owner}/{repo}")
        raise HTTPException(status_code=400, detail=f"GitHub API error: {e.response.status_code}")

    # Ensure output directory exists
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    output_dir = REPOS_DIR / f"{owner}_{repo}"

    # Import files and assemble content
    try:
        result = await import_repo_files(
            owner, repo, repo_meta.default_branch,
            request.selected_files, readme, repo_meta, output_dir,
        )
    except Exception as e:
        logger.error(f"Repo import failed: {e}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

    # Insert into database
    source_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    source_metadata = {
        "owner": owner,
        "repo_name": repo,
        "full_name": f"{owner}/{repo}",
        "default_branch": repo_meta.default_branch,
        "stars": repo_meta.stars,
        "language": repo_meta.language,
        "topics": repo_meta.topics,
        "license": repo_meta.license,
        "files_imported": result.files_imported,
        "interest_tags": request.interest_tags or [],
        "clipped_at": now,
    }

    db = await get_db()
    await db.execute("""
        INSERT INTO sources (id, title, source_type, author_display, year,
                            url, content_path, metadata, created_at, updated_at)
        VALUES (?, ?, 'repo', ?, ?, ?, ?, ?, ?, ?)
    """, [
        source_id, result.title, owner, None,
        result.url, result.content_path, json.dumps(source_metadata),
        now, now,
    ])

    # Insert sections
    for i, section in enumerate(result.sections):
        section_id = f"{source_id}-s{i}"
        await db.execute("""
            INSERT INTO sections (id, source_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, source_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"], i, None,
        ])

    # Index in FTS
    await db.execute("""
        INSERT INTO sources_fts (rowid, title, author_display)
        SELECT rowid, title, author_display FROM sources WHERE id = ?
    """, [source_id])

    await db.commit()

    return {
        "id": source_id,
        "title": result.title,
        "owner": owner,
        "repo_name": repo,
        "url": result.url,
        "source_type": "repo",
        "files_imported": len(result.files_imported),
        "sections_count": len(result.sections),
        "content_path": result.content_path,
        "summary": request.summary,
    }


@router.post("/{source_id}/append-repo-files")
async def append_repo_files_endpoint(source_id: str, request: AppendRepoFilesRequest):
    """
    Append additional files to an existing repo source.

    Fetches new file contents and appends as new sections at the end.
    """
    from services.repo_clipper import append_files_to_repo

    if not request.file_paths:
        raise HTTPException(status_code=400, detail="No file paths provided")

    db = await get_db()

    # Fetch source
    cursor = await db.execute("""
        SELECT id, content_path, metadata FROM sources
        WHERE id = ? AND source_type = 'repo'
    """, [source_id])
    source = await cursor.fetchone()

    if not source:
        raise HTTPException(status_code=404, detail="Repo source not found")

    metadata = json.loads(source[2])
    owner = metadata["owner"]
    repo = metadata["repo_name"]
    branch = metadata["default_branch"]
    content_path = source[1]

    # Get existing sections for order_index calculation
    cursor = await db.execute("""
        SELECT id, title, level, start_offset, end_offset, order_index
        FROM sections WHERE source_id = ? ORDER BY order_index
    """, [source_id])
    rows = await cursor.fetchall()
    existing_sections = [
        {"id": r[0], "title": r[1], "level": r[2],
         "start_offset": r[3], "end_offset": r[4], "order_index": r[5]}
        for r in rows
    ]

    # Filter out already-imported files
    already_imported = set(metadata.get("files_imported", []))
    new_paths = [p for p in request.file_paths if p not in already_imported]

    if not new_paths:
        raise HTTPException(status_code=400, detail="All selected files are already imported")

    try:
        _, new_sections = await append_files_to_repo(
            source_id, owner, repo, branch, new_paths,
            content_path, existing_sections,
        )
    except Exception as e:
        logger.error(f"Repo append failed: {e}")
        raise HTTPException(status_code=500, detail=f"Append failed: {str(e)}")

    # Insert new sections
    now = datetime.now().isoformat()
    for section in new_sections:
        section_id = f"{source_id}-s{section['order_index']}"
        await db.execute("""
            INSERT INTO sections (id, source_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, source_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"],
            section["order_index"], None,
        ])

    # Update metadata
    metadata["files_imported"] = list(already_imported | set(new_paths))
    await db.execute("""
        UPDATE sources SET metadata = ?, updated_at = ? WHERE id = ?
    """, [json.dumps(metadata), now, source_id])

    await db.commit()

    return {
        "source_id": source_id,
        "new_sections": len(new_sections),
        "total_files": len(metadata["files_imported"]),
    }


def _normalize_path(path_str: Optional[str]) -> Optional[str]:
    """
    Normalize a path string for consistent comparison.
    Resolves to absolute path with forward slashes.
    """
    if not path_str:
        return None
    try:
        return str(Path(path_str).resolve()).replace("\\", "/")
    except Exception:
        return path_str


def _compute_pdf_hash(pdf_path: Path) -> Optional[str]:
    """
    Compute SHA256 hash of a PDF file for duplicate detection.
    Returns None if file doesn't exist or can't be read.
    """
    if not pdf_path or not pdf_path.exists():
        return None
    try:
        sha256 = hashlib.sha256()
        with open(pdf_path, "rb") as f:
            # Read in chunks to handle large files
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception:
        return None


# ============================================================
# Note Import
# ============================================================

@router.post("/import-note/preview")
async def preview_note_endpoint(file: UploadFile = File(...)):
    """
    Preview a markdown file before importing.

    Extracts title from first heading, counts words, and runs AI metadata
    suggestions so the modal can pre-fill fields before save.

    Returns:
        title, word_count, suggestions (from AI)
    """
    from services.note_importer import preview_note

    # Validate file type
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Read file content
    raw_bytes = await file.read()
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = raw_bytes.decode("latin-1")

    # Cap content for AI suggestions at 100KB
    if len(content) > 100_000:
        ai_content = content[:100_000]
    else:
        ai_content = content

    # Quick preview (title + word count)
    preview = preview_note(content, file.filename)

    # AI metadata suggestions
    suggestions_data = []
    try:
        result = await suggest_metadata(
            ai_content,
            source_id="preview",
            source_type="note",
        )
        suggestions_data = format_suggestions_for_review(result)
    except Exception as e:
        logger.warning(f"AI metadata suggestion failed for note preview: {e}")

    return {
        "title": preview["title"],
        "word_count": preview["word_count"],
        "suggestions": suggestions_data,
    }


@router.post("/import-note")
async def import_note_endpoint(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    year: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    keywords: Optional[str] = Form(None),
    keyword_gluon_ids: Optional[str] = Form(None),
    author_gluon_ids: Optional[str] = Form(None),
):
    """
    Import a markdown file as a note source.

    Converts markdown headings to [SECTION] markers, saves to
    data/sources/notes/, and creates a source row in the database.

    Args:
        file: The .md file to import
        title: Optional title override (extracted from first heading if not provided)
        author: Optional author display string (semicolon-separated)
        year: Optional publication year
        description: Optional description
        keywords: Optional semicolon-separated keyword display string
        keyword_gluon_ids: Optional JSON array of tag gluon IDs
        author_gluon_ids: Optional JSON array of person gluon IDs
    """
    from services.note_importer import import_note

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Read file content
    raw_bytes = await file.read()
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = raw_bytes.decode("latin-1")

    # Dedup: check if a note with the same title already exists
    from services.note_importer import _extract_title
    check_title = title.strip() if title else _extract_title(content, file.filename)
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, title FROM sources WHERE source_type = 'note' AND title = ?",
        [check_title]
    )
    existing = await cursor.fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Note already imported as '{existing[1]}' (id: {existing[0]})"
        )

    # Ensure notes directory exists
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    # Import the note
    result = import_note(
        content=content,
        filename=file.filename,
        notes_dir=NOTES_DIR,
        title_override=title.strip() if title else None,
    )

    # Parse year
    parsed_year = None
    if year:
        try:
            parsed_year = int(year)
        except ValueError:
            pass

    # Build metadata (same structure as MetadataEditModal saves)
    source_metadata = {}
    if description:
        source_metadata["description"] = description
    if keywords:
        source_metadata["keywords"] = keywords
    if keyword_gluon_ids:
        source_metadata["keyword_gluon_ids"] = keyword_gluon_ids
    if author_gluon_ids:
        source_metadata["author_gluon_ids"] = author_gluon_ids
    source_metadata["word_count"] = result.word_count
    source_metadata["original_filename"] = file.filename

    # Generate source ID and insert
    source_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO sources (id, title, source_type, author_display, year,
                            content_path, metadata, created_at, updated_at)
        VALUES (?, ?, 'note', ?, ?, ?, ?, ?, ?)
    """, [
        source_id, result.title, author, parsed_year,
        result.content_path, json.dumps(source_metadata),
        now, now
    ])

    # Insert sections
    for i, section in enumerate(result.sections):
        section_id = f"{source_id}-s{i}"
        await db.execute("""
            INSERT INTO sections (id, source_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, source_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"], i, None
        ])

    # Index in FTS
    await db.execute("""
        INSERT INTO sources_fts (rowid, title, author_display)
        SELECT rowid, title, author_display FROM sources WHERE id = ?
    """, [source_id])

    # Sync gluon links (tags + authors) — same as PATCH endpoint
    await _sync_source_gluon_links(db, source_id, source_metadata)

    await db.commit()

    return {
        "id": source_id,
        "title": result.title,
        "author": author,
        "year": parsed_year,
        "source_type": "note",
        "word_count": result.word_count,
        "sections_count": len(result.sections),
        "content_path": result.content_path,
    }


@router.post("/refresh")
async def refresh_sources():
    """
    Scan all source folders and import new sources without clearing existing ones.

    Scans:
    - data/sources/documents/ - PDF extractions
    - data/sources/web/ - web clips
    - data/sources/threads/ - tweets/threads
    - data/sources/videos/ - video transcripts
    - data/sources/notes/ - markdown notes

    This is the safe way to add sources that exist on disk but not in the library:
    - Imports sources that aren't in the database yet
    - Updates existing document sources if a higher-quality extraction is available
    - Preserves existing highlights and notes
    - Uses normalized paths to prevent duplicates

    Returns:
        imported: list of newly imported sources (by type)
        updated: list of sources updated to better extraction
        skipped: list of sources already up-to-date
    """
    db = await get_db()

    # Aggregate results from all source types
    all_imported = []
    all_updated = []
    all_skipped = []
    all_errors = []

    # 1. Refresh documents
    doc_results = await _refresh_documents(db)
    all_imported.extend(doc_results["imported"])
    all_updated.extend(doc_results["updated"])
    all_skipped.extend(doc_results["skipped"])
    all_errors.extend(doc_results["errors"])

    # 2. Refresh threads
    thread_results = await _refresh_threads(db)
    all_imported.extend(thread_results["imported"])
    all_skipped.extend(thread_results["skipped"])
    all_errors.extend(thread_results["errors"])

    # 3. Refresh videos
    video_results = await _refresh_videos(db)
    all_imported.extend(video_results["imported"])
    all_skipped.extend(video_results["skipped"])
    all_errors.extend(video_results["errors"])

    # 4. Refresh web clips
    web_results = await _refresh_web(db)
    all_imported.extend(web_results["imported"])
    all_skipped.extend(web_results["skipped"])
    all_errors.extend(web_results["errors"])

    # 5. Refresh notes
    note_results = await _refresh_notes(db)
    all_imported.extend(note_results["imported"])
    all_skipped.extend(note_results["skipped"])
    all_errors.extend(note_results["errors"])

    await db.commit()

    return {
        "imported_count": len(all_imported),
        "updated_count": len(all_updated),
        "skipped_count": len(all_skipped),
        "error_count": len(all_errors),
        "imported": all_imported,
        "updated": all_updated,
        "skipped": all_skipped,
        "errors": all_errors
    }


async def _refresh_documents(db) -> dict:
    """Refresh document sources from data/sources/documents/"""
    docs_dir = _get_documents_dir()
    if not docs_dir.exists():
        return {"imported": [], "updated": [], "skipped": [], "errors": []}

    # Tier priority: higher = better quality
    TIER_PRIORITY = {
        "tesseract": 1,
        "pymupdf": 2,
        "marker": 3,
        "dots-ocr": 4,
    }

    # Get existing sources indexed by content_path (normalized)
    cursor = await db.execute("SELECT id, content_path, metadata FROM sources WHERE source_type = 'document'")
    rows = await cursor.fetchall()
    existing_by_content = {}  # normalized content_path -> source info
    existing_by_original = {}  # normalized original_path -> source info
    for source_id, content_path, metadata_json in rows:
        norm_content = _normalize_path(content_path)
        source_info = {"id": source_id, "content_path": content_path}
        if norm_content:
            existing_by_content[norm_content] = source_info

        # Also check original_path in metadata
        if metadata_json:
            try:
                metadata = json.loads(metadata_json)
                orig_path = metadata.get("original_path")
                if orig_path:
                    norm_orig = _normalize_path(orig_path)
                    if norm_orig:
                        existing_by_original[norm_orig] = source_info
            except (json.JSONDecodeError, TypeError):
                pass

    imported = []
    updated = []
    skipped = []
    errors = []

    for doc_folder in docs_dir.iterdir():
        if not doc_folder.is_dir() or doc_folder.name.startswith("_"):
            continue

        folder_name = doc_folder.name

        # Find all available extraction methods
        available_methods = []
        for method in ["dots-ocr", "marker", "pymupdf", "tesseract"]:
            # First try exact match
            method_folder = doc_folder / f"{folder_name}--{method}"
            extracted_file = method_folder / f"{folder_name}--{method}--extracted.txt"
            if extracted_file.exists():
                available_methods.append({
                    "method": method,
                    "priority": TIER_PRIORITY.get(method, 0),
                    "path": str(extracted_file)
                })
            else:
                # Try glob for mismatched names (e.g., subfolder name differs from parent)
                for method_folder in doc_folder.glob(f"*--{method}"):
                    if method_folder.is_dir():
                        for extracted_file in method_folder.glob(f"*--{method}--extracted.txt"):
                            available_methods.append({
                                "method": method,
                                "priority": TIER_PRIORITY.get(method, 0),
                                "path": str(extracted_file)
                            })
                            break  # Take first match
                        break  # Take first matching folder

        if not available_methods:
            continue

        # Sort by priority (highest first) and pick best
        available_methods.sort(key=lambda x: x["priority"], reverse=True)
        best_method = available_methods[0]

        # Find PDF
        pdf_path = doc_folder / f"{folder_name}.pdf"
        pdf_path_str = str(pdf_path) if pdf_path.exists() else None
        norm_pdf_path = _normalize_path(pdf_path_str)
        norm_content_path = _normalize_path(best_method["path"])

        # Parse metadata from folder name
        metadata = _parse_folder_name(folder_name)

        try:
            # Check if source exists by EITHER original_path OR content_path
            existing = None
            if norm_pdf_path and norm_pdf_path in existing_by_original:
                existing = existing_by_original[norm_pdf_path]
            elif norm_content_path and norm_content_path in existing_by_content:
                existing = existing_by_content[norm_content_path]

            if existing:
                # Source exists - check if we should update
                existing_content = existing["content_path"] or ""

                # Determine existing tier
                existing_tier = None
                existing_priority = 0
                for method in TIER_PRIORITY:
                    if f"--{method}--" in existing_content:
                        existing_tier = method
                        existing_priority = TIER_PRIORITY[method]
                        break

                if best_method["priority"] > existing_priority:
                    # Upgrade to better extraction
                    source_id = existing["id"]
                    now = datetime.now().isoformat()

                    # Read content for sections
                    content = Path(best_method["path"]).read_text(encoding="utf-8")
                    sections = _parse_sections(content, source_id)

                    # Update source
                    await db.execute("""
                        UPDATE sources
                        SET content_path = ?, updated_at = ?
                        WHERE id = ?
                    """, [best_method["path"], now, source_id])

                    # Re-index sections
                    await db.execute("DELETE FROM sections WHERE source_id = ?", [source_id])
                    for i, section in enumerate(sections):
                        section_id = f"{source_id}-s{i}"
                        await db.execute("""
                            INSERT INTO sections (id, source_id, title, level, start_offset,
                                                  end_offset, order_index, parent_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, [
                            section_id, source_id, section["title"], section["level"],
                            section["start_offset"], section["end_offset"], i, None
                        ])

                    # Update FTS
                    await db.execute("""
                        DELETE FROM sources_fts WHERE rowid = (SELECT rowid FROM sources WHERE id = ?)
                    """, [source_id])
                    await db.execute("""
                        INSERT INTO sources_fts (rowid, title, author_display)
                        SELECT rowid, title, author_display FROM sources WHERE id = ?
                    """, [source_id])

                    updated.append({
                        "id": source_id,
                        "folder_name": folder_name,
                        "old_method": existing_tier,
                        "new_method": best_method["method"]
                    })
                else:
                    # Already have same or better extraction
                    skipped.append({
                        "folder_name": folder_name,
                        "reason": f"already has {existing_tier} extraction"
                    })
            else:
                # New source - import it
                source_id = str(uuid.uuid4())[:8]
                now = datetime.now().isoformat()

                # Compute PDF hash for future duplicate detection
                pdf_hash = _compute_pdf_hash(pdf_path) if pdf_path.exists() else None

                # Read content for sections
                content = Path(best_method["path"]).read_text(encoding="utf-8")
                sections = _parse_sections(content, source_id)

                # Build metadata
                source_metadata = {
                    "doc_type": "article",
                    "file_type": "pdf",
                    "original_path": pdf_path_str,
                    "pdf_hash": pdf_hash,
                    "extraction_method": best_method["method"],
                }

                await db.execute("""
                    INSERT INTO sources (id, title, source_type, author_display, year,
                                        content_path, metadata, created_at, updated_at)
                    VALUES (?, ?, 'document', ?, ?, ?, ?, ?, ?)
                """, [
                    source_id,
                    metadata.get("title", folder_name),
                    metadata.get("author"),
                    metadata.get("year"),
                    best_method["path"],
                    json.dumps(source_metadata),
                    now,
                    now
                ])

                # Insert sections
                for i, section in enumerate(sections):
                    section_id = f"{source_id}-s{i}"
                    await db.execute("""
                        INSERT INTO sections (id, source_id, title, level, start_offset,
                                              end_offset, order_index, parent_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        section_id, source_id, section["title"], section["level"],
                        section["start_offset"], section["end_offset"], i, None
                    ])

                # Index in FTS
                await db.execute("""
                    INSERT INTO sources_fts (rowid, title, author_display)
                    SELECT rowid, title, author_display FROM sources WHERE id = ?
                """, [source_id])

                imported.append({
                    "id": source_id,
                    "folder_name": folder_name,
                    "title": metadata.get("title", folder_name),
                    "method": best_method["method"]
                })

        except Exception as e:
            errors.append({
                "folder_name": folder_name,
                "error": str(e)
            })

    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "errors": errors
    }


async def _refresh_threads(db) -> dict:
    """Refresh thread sources from data/sources/threads/"""
    if not THREADS_DIR.exists():
        return {"imported": [], "skipped": [], "errors": []}

    imported = []
    skipped = []
    errors = []

    # Get existing thread sources by tweet_id
    cursor = await db.execute("""
        SELECT id, json_extract(metadata, '$.tweet_id') as tweet_id
        FROM sources WHERE source_type = 'thread'
    """)
    rows = await cursor.fetchall()
    existing_by_tweet_id = {row[1]: row[0] for row in rows if row[1]}

    for folder in THREADS_DIR.iterdir():
        if not folder.is_dir():
            continue

        folder_name = folder.name
        thread_json = folder / "thread.json"
        extracted_txt = folder / f"{folder_name}--thread--extracted.txt"

        if not thread_json.exists() or not extracted_txt.exists():
            continue

        try:
            # Parse thread.json
            thread_data = json.loads(thread_json.read_text(encoding="utf-8"))
            tweet_id = thread_data.get("tweet_id")

            if not tweet_id:
                continue

            # Check if already exists
            if tweet_id in existing_by_tweet_id:
                skipped.append({
                    "folder_name": folder_name,
                    "source_type": "thread",
                    "reason": "already in library"
                })
                continue

            # Import new thread
            source_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()

            # Build title from author and first line
            author_display = thread_data.get("author_display", thread_data.get("author_handle", "Unknown"))
            title = f"{author_display}: {thread_data.get('tweet_text', '')[:80]}..."

            # Parse year from timestamp
            year = None
            timestamp = thread_data.get("timestamp", "")
            year_match = re.search(r'\b(19|20)\d{2}\b', timestamp)
            if year_match:
                year = int(year_match.group())

            # Read content for sections
            content = extracted_txt.read_text(encoding="utf-8")
            sections = _parse_sections(content, source_id)

            # Build metadata
            source_metadata = {
                "tweet_id": tweet_id,
                "author_handle": thread_data.get("author_handle"),
                "thread_length": thread_data.get("thread_length", 1),
                "original_url": thread_data.get("original_url"),
                "clipped_at": thread_data.get("clipped_at"),
                "likes": thread_data.get("likes"),
                "retweets": thread_data.get("retweets"),
                "replies": thread_data.get("replies"),
            }

            await db.execute("""
                INSERT INTO sources (id, title, source_type, author_display, year,
                                    url, content_path, metadata, created_at, updated_at)
                VALUES (?, ?, 'thread', ?, ?, ?, ?, ?, ?, ?)
            """, [
                source_id, title, author_display, year,
                thread_data.get("original_url"),
                str(extracted_txt),
                json.dumps(source_metadata),
                now, now
            ])

            # Insert sections
            for i, section in enumerate(sections):
                section_id = f"{source_id}-s{i}"
                await db.execute("""
                    INSERT INTO sections (id, source_id, title, level, start_offset,
                                          end_offset, order_index, parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    section_id, source_id, section["title"], section["level"],
                    section["start_offset"], section["end_offset"], i, None
                ])

            # Index in FTS
            await db.execute("""
                INSERT INTO sources_fts (rowid, title, author_display)
                SELECT rowid, title, author_display FROM sources WHERE id = ?
            """, [source_id])

            imported.append({
                "id": source_id,
                "folder_name": folder_name,
                "source_type": "thread",
                "title": title
            })

        except Exception as e:
            errors.append({
                "folder_name": folder_name,
                "source_type": "thread",
                "error": str(e)
            })

    return {"imported": imported, "skipped": skipped, "errors": errors}


async def _refresh_videos(db) -> dict:
    """Refresh video sources from data/sources/videos/"""
    if not VIDEOS_DIR.exists():
        return {"imported": [], "skipped": [], "errors": []}

    imported = []
    skipped = []
    errors = []

    # Get existing video sources by video_id
    cursor = await db.execute("""
        SELECT id, json_extract(metadata, '$.video_id') as video_id
        FROM sources WHERE source_type = 'media'
    """)
    rows = await cursor.fetchall()
    existing_by_video_id = {row[1]: row[0] for row in rows if row[1]}

    for folder in VIDEOS_DIR.iterdir():
        if not folder.is_dir():
            continue

        folder_name = folder.name
        video_json = folder / "video.json"
        extracted_txt = folder / f"{folder_name}--video--extracted.txt"

        if not video_json.exists() or not extracted_txt.exists():
            continue

        try:
            # Parse video.json
            video_data = json.loads(video_json.read_text(encoding="utf-8"))
            video_id = video_data.get("video_id")

            if not video_id:
                continue

            # Check if already exists
            if video_id in existing_by_video_id:
                skipped.append({
                    "folder_name": folder_name,
                    "source_type": "media",
                    "reason": "already in library"
                })
                continue

            # Import new video
            source_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()

            title = video_data.get("title", folder_name)
            channel = video_data.get("channel", "Unknown")

            # Parse year from publish_date
            year = None
            publish_date = video_data.get("publish_date", "")
            year_match = re.search(r'\b(19|20)\d{2}\b', publish_date)
            if year_match:
                year = int(year_match.group())

            # Read content for sections
            content = extracted_txt.read_text(encoding="utf-8")
            sections = _parse_sections(content, source_id)

            # Build metadata
            source_metadata = {
                "video_id": video_id,
                "platform": video_data.get("platform", "youtube"),
                "channel": channel,
                "channel_id": video_data.get("channel_id"),
                "duration_seconds": video_data.get("duration_seconds"),
                "duration_formatted": video_data.get("duration_formatted"),
                "view_count": video_data.get("view_count"),
                "like_count": video_data.get("like_count"),
                "thumbnail_url": video_data.get("thumbnail_url"),
                "word_count": video_data.get("word_count"),
                "segment_count": video_data.get("segment_count"),
                "clipped_at": video_data.get("clipped_at"),
            }

            await db.execute("""
                INSERT INTO sources (id, title, source_type, author_display, year,
                                    url, content_path, metadata, created_at, updated_at)
                VALUES (?, ?, 'media', ?, ?, ?, ?, ?, ?, ?)
            """, [
                source_id, title, channel, year,
                video_data.get("url"),
                str(extracted_txt),
                json.dumps(source_metadata),
                now, now
            ])

            # Insert sections
            for i, section in enumerate(sections):
                section_id = f"{source_id}-s{i}"
                await db.execute("""
                    INSERT INTO sections (id, source_id, title, level, start_offset,
                                          end_offset, order_index, parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    section_id, source_id, section["title"], section["level"],
                    section["start_offset"], section["end_offset"], i, None
                ])

            # Index in FTS
            await db.execute("""
                INSERT INTO sources_fts (rowid, title, author_display)
                SELECT rowid, title, author_display FROM sources WHERE id = ?
            """, [source_id])

            imported.append({
                "id": source_id,
                "folder_name": folder_name,
                "source_type": "media",
                "title": title
            })

        except Exception as e:
            errors.append({
                "folder_name": folder_name,
                "source_type": "media",
                "error": str(e)
            })

    return {"imported": imported, "skipped": skipped, "errors": errors}


async def _refresh_web(db) -> dict:
    """
    Refresh web sources from data/sources/web/

    Note: Web clips don't have a metadata JSON file, so we parse what we can
    from the folder name and extracted text content.
    """
    if not WEB_DIR.exists():
        return {"imported": [], "skipped": [], "errors": []}

    imported = []
    skipped = []
    errors = []

    # Get existing web sources by content_path (normalized)
    cursor = await db.execute("SELECT id, content_path FROM sources WHERE source_type = 'web'")
    rows = await cursor.fetchall()
    existing_by_content = {_normalize_path(row[1]): row[0] for row in rows if row[1]}

    for folder in WEB_DIR.iterdir():
        if not folder.is_dir():
            continue

        folder_name = folder.name
        extracted_txt = folder / f"{folder_name}--web--extracted.txt"

        if not extracted_txt.exists():
            continue

        norm_content_path = _normalize_path(str(extracted_txt))

        # Check if already exists
        if norm_content_path in existing_by_content:
            skipped.append({
                "folder_name": folder_name,
                "source_type": "web",
                "reason": "already in library"
            })
            continue

        try:
            # Import new web clip
            source_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()

            # Read content and try to extract title from [TITLE] marker
            content = extracted_txt.read_text(encoding="utf-8")
            sections = _parse_sections(content, source_id)

            # Extract title from content (first [TITLE] line or first line)
            title = folder_name  # Default to folder name
            title_match = re.search(r'\[TITLE\]\s*(.+?)(?:\n|$)', content)
            if title_match:
                title = title_match.group(1).strip()
            elif content:
                # Use first non-empty line
                first_line = content.split('\n')[0].strip()
                if first_line and not first_line.startswith('['):
                    title = first_line[:100]

            # Try to parse domain from folder name (format: domain_slug_hash)
            parts = folder_name.split('_')
            sitename = parts[0] if parts else None

            # Build metadata
            source_metadata = {
                "sitename": sitename,
                "clipped_at": now,  # We don't know the original clip time
                "recovered_from_disk": True,  # Flag that this was recovered
            }

            await db.execute("""
                INSERT INTO sources (id, title, source_type, author_display, year,
                                    content_path, metadata, created_at, updated_at)
                VALUES (?, ?, 'web', ?, ?, ?, ?, ?, ?)
            """, [
                source_id, title, sitename, None,  # Use sitename as author fallback for web
                str(extracted_txt),
                json.dumps(source_metadata),
                now, now
            ])

            # Insert sections
            for i, section in enumerate(sections):
                section_id = f"{source_id}-s{i}"
                await db.execute("""
                    INSERT INTO sections (id, source_id, title, level, start_offset,
                                          end_offset, order_index, parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    section_id, source_id, section["title"], section["level"],
                    section["start_offset"], section["end_offset"], i, None
                ])

            # Index in FTS
            await db.execute("""
                INSERT INTO sources_fts (rowid, title, author_display)
                SELECT rowid, title, author_display FROM sources WHERE id = ?
            """, [source_id])

            imported.append({
                "id": source_id,
                "folder_name": folder_name,
                "source_type": "web",
                "title": title
            })

        except Exception as e:
            errors.append({
                "folder_name": folder_name,
                "source_type": "web",
                "error": str(e)
            })

    return {"imported": imported, "skipped": skipped, "errors": errors}


async def _refresh_notes(db) -> dict:
    """
    Refresh note sources from data/sources/notes/.

    Scans for *--note--extracted.txt files and imports any that aren't
    already in the library.
    """
    if not NOTES_DIR.exists():
        return {"imported": [], "skipped": [], "errors": []}

    imported = []
    skipped = []
    errors = []

    # Get existing note sources by content_path
    cursor = await db.execute("SELECT id, content_path FROM sources WHERE source_type = 'note'")
    rows = await cursor.fetchall()
    existing_by_content = {_normalize_path(row[1]): row[0] for row in rows if row[1]}

    for folder in NOTES_DIR.iterdir():
        if not folder.is_dir():
            continue

        folder_name = folder.name
        extracted_txt = folder / f"{folder_name}--note--extracted.txt"

        if not extracted_txt.exists():
            continue

        norm_content_path = _normalize_path(str(extracted_txt))

        if norm_content_path in existing_by_content:
            skipped.append({
                "folder_name": folder_name,
                "source_type": "note",
                "reason": "already in library",
            })
            continue

        try:
            source_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()

            content = extracted_txt.read_text(encoding="utf-8")
            sections = _parse_sections(content, source_id)

            # Extract title from [TITLE] marker
            title = folder_name
            title_match = re.search(r'\[TITLE\]\s*(.+?)(?:\n|$)', content)
            if title_match:
                title = title_match.group(1).strip()

            source_metadata = {
                "recovered_from_disk": True,
            }

            await db.execute("""
                INSERT INTO sources (id, title, source_type, author_display, year,
                                    content_path, metadata, created_at, updated_at)
                VALUES (?, ?, 'note', ?, ?, ?, ?, ?, ?)
            """, [
                source_id, title, None, None,
                str(extracted_txt),
                json.dumps(source_metadata),
                now, now
            ])

            for i, section in enumerate(sections):
                section_id = f"{source_id}-s{i}"
                await db.execute("""
                    INSERT INTO sections (id, source_id, title, level, start_offset,
                                          end_offset, order_index, parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    section_id, source_id, section["title"], section["level"],
                    section["start_offset"], section["end_offset"], i, None
                ])

            await db.execute("""
                INSERT INTO sources_fts (rowid, title, author_display)
                SELECT rowid, title, author_display FROM sources WHERE id = ?
            """, [source_id])

            imported.append({
                "id": source_id,
                "folder_name": folder_name,
                "source_type": "note",
                "title": title,
            })

        except Exception as e:
            errors.append({
                "folder_name": folder_name,
                "source_type": "note",
                "error": str(e),
            })

    return {"imported": imported, "skipped": skipped, "errors": errors}


def _parse_folder_name(folder_name: str) -> dict:
    """
    Parse metadata from folder name.
    Format: Author_Year_Title_Words
    Example: Papadimitriou_2020_Brain_Computation_By_Assemblies
    """
    result = {}
    parts = folder_name.split("_")

    # Find year (4 digits)
    year_idx = None
    for i, part in enumerate(parts):
        if re.match(r"^\d{4}$", part):
            year_idx = i
            result["year"] = int(part)
            break

    if year_idx is not None:
        # Author is everything before year
        author_parts = parts[:year_idx]
        result["author"] = " ".join(author_parts).replace(" Et Al", " et al.").replace(" And ", " & ")

        # Title is everything after year
        title_parts = parts[year_idx + 1:]
        result["title"] = " ".join(title_parts)
    else:
        result["title"] = " ".join(parts)

    return result


@router.patch("/{source_id}")
async def update_source(source_id: str, updates: dict):
    """Update source metadata."""
    db = await get_db()

    # Get current source
    cursor = await db.execute("SELECT * FROM sources WHERE id = ?", [source_id])
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    columns = [desc[0] for desc in cursor.description]
    current = dict(zip(columns, row))

    # Parse current metadata
    current_metadata = {}
    if current.get("metadata"):
        try:
            current_metadata = json.loads(current["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass

    # Separate core fields from metadata fields
    # Note: "author" maps to "author_display" in the database
    core_fields = {"title", "author_display", "author", "year", "url", "content_path", "reading_position", "metadata_skip"}
    metadata_fields = {
        # Document fields
        "doc_type", "file_type", "original_path", "pdf_hash", "publisher",
        "journal", "volume", "issue", "pages", "doi", "isbn", "issn",
        "abstract", "keywords", "editors", "edition", "series",
        "author_gluon_ids", "editor_gluon_ids", "keyword_gluon_ids",
        # Web fields
        "sitename", "original_url", "word_count",
        # Tweet/thread fields
        "tweet_id", "author_handle", "thread_length", "likes", "retweets", "replies",
        # Video/media fields
        "video_id", "platform", "channel", "channel_id", "duration_seconds",
        "duration_formatted", "view_count", "like_count", "thumbnail_url", "description",
    }

    # Build update
    update_fields = []
    params = []

    for field, value in updates.items():
        if field in core_fields and value is not None:
            # Handle author field mapping (author -> author_display)
            db_field = "author_display" if field == "author" else field
            update_fields.append(f"{db_field} = ?")
            params.append(value)
        elif field in metadata_fields:
            # Update in metadata JSON
            current_metadata[field] = value

    # Always update metadata if any metadata fields changed
    if any(f in updates for f in metadata_fields):
        update_fields.append("metadata = ?")
        params.append(json.dumps(current_metadata))

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    update_fields.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(source_id)

    query = f"UPDATE sources SET {', '.join(update_fields)} WHERE id = ?"
    await db.execute(query, params)

    # Sync source_gluon_links for author and editor relationships
    await _sync_source_gluon_links(db, source_id, current_metadata)

    await db.commit()

    return await get_source(source_id)


async def _sync_source_gluon_links(db, source_id: str, metadata: dict):
    """
    Sync source_gluon_links table with author_gluon_ids, editor_gluon_ids, and keyword_gluon_ids from metadata.
    This creates proper queryable links between sources and person/tag gluons.
    """
    # Mapping of metadata field to relationship type
    gluon_id_fields = {
        "author_gluon_ids": "author",
        "editor_gluon_ids": "editor",
        "keyword_gluon_ids": "tag",  # Keywords are now unified as tags
    }

    for field, relationship_type in gluon_id_fields.items():
        gluon_ids_raw = metadata.get(field)
        if gluon_ids_raw is None:
            continue

        # Parse gluon IDs (may be JSON string or list)
        gluon_ids = []
        if isinstance(gluon_ids_raw, str):
            try:
                gluon_ids = json.loads(gluon_ids_raw)
            except (json.JSONDecodeError, TypeError):
                pass
        elif isinstance(gluon_ids_raw, list):
            gluon_ids = gluon_ids_raw

        # Delete existing links for this source + relationship type
        await db.execute("""
            DELETE FROM source_gluon_links
            WHERE source_id = ? AND relationship_type = ?
        """, [source_id, relationship_type])

        # Create new links with position ordering
        for position, gluon_id in enumerate(gluon_ids):
            if not gluon_id:
                continue
            link_id = f"sgl_{source_id[:4]}_{gluon_id[:4]}_{relationship_type[0]}_{position}"
            await db.execute("""
                INSERT OR IGNORE INTO source_gluon_links
                (id, source_id, gluon_id, relationship_type, position)
                VALUES (?, ?, ?, ?, ?)
            """, [link_id, source_id, gluon_id, relationship_type, position])


@router.get("/{source_id}/gluon-stats")
async def get_source_gluon_stats(source_id: str):
    """
    Get counts of highlights and notes attached to this source.
    Used to show warning before delete.
    Also returns source_type and content_path for local file deletion option.
    """
    db = await get_db()

    # Check source exists and get metadata
    cursor = await db.execute(
        "SELECT id, title, source_type, content_path FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    source_title = row[1]
    source_type = row[2] or 'document'
    content_path = row[3]

    # Check if local folder exists (any source type with a content_path)
    has_local_folder = False
    local_folder_path = None
    if content_path:
        content_file = Path(content_path)
        if content_file.exists():
            folder = content_file.parent
            if folder.exists() and folder.is_dir():
                has_local_folder = True
                local_folder_path = str(folder)

    # Count highlights
    cursor = await db.execute(
        "SELECT COUNT(*) FROM gluons WHERE source_id = ? AND type = 'highlight'",
        [source_id]
    )
    highlight_count = (await cursor.fetchone())[0]

    # Count notes (attached to source or to highlights in this source)
    cursor = await db.execute("""
        SELECT COUNT(*) FROM gluons
        WHERE type = 'note' AND (
            source_id = ?
            OR parent_gluon_id IN (SELECT id FROM gluons WHERE source_id = ? AND type = 'highlight')
        )
    """, [source_id, source_id])
    note_count = (await cursor.fetchone())[0]

    return {
        "source_id": source_id,
        "title": source_title,
        "source_type": source_type,
        "highlight_count": highlight_count,
        "note_count": note_count,
        "total_gluons": highlight_count + note_count,
        "has_local_folder": has_local_folder,
        "local_folder_path": local_folder_path
    }


@router.delete("/{source_id}")
async def delete_source(
    source_id: str,
    keep_gluons: bool = Query(False, description="If true, keep highlights/notes as orphans"),
    delete_local_files: bool = Query(False, description="If true, delete the local extraction folder")
):
    """
    Delete a source.

    Args:
        source_id: The source to delete
        keep_gluons: If true, highlights and notes will become orphans (source_id set to NULL).
                     If false (default), all gluons will be deleted with the source.
        delete_local_files: If true, delete the local folder containing extracted text, media, etc.
    """
    db = await get_db()

    # Get source info (need source_type and content_path for local file deletion)
    cursor = await db.execute(
        "SELECT id, source_type, content_path FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    source_type = row[1]
    content_path = row[2]

    if not keep_gluons:
        # Explicitly delete gluons (since we now use SET NULL, cascade won't do it)
        # First delete from FTS
        await db.execute("""
            DELETE FROM gluons_fts WHERE rowid IN
            (SELECT rowid FROM gluons WHERE source_id = ?)
        """, [source_id])

        # Delete links for gluons in this source
        await db.execute("""
            DELETE FROM links WHERE source_id IN
            (SELECT id FROM gluons WHERE source_id = ?)
            OR target_id IN
            (SELECT id FROM gluons WHERE source_id = ?)
        """, [source_id, source_id])

        # Delete the gluons
        await db.execute("DELETE FROM gluons WHERE source_id = ?", [source_id])

    # Delete sections
    await db.execute("DELETE FROM sections WHERE source_id = ?", [source_id])

    # Delete the source
    await db.execute("DELETE FROM sources WHERE id = ?", [source_id])

    # Remove from FTS
    await db.execute("""
        DELETE FROM sources_fts WHERE rowid NOT IN
        (SELECT rowid FROM sources)
    """)

    await db.commit()

    # Delete local files if requested (non-document sources only)
    local_files_deleted = False
    deleted_folder = None
    if delete_local_files and content_path:
        try:
            import shutil
            content_file = Path(content_path)
            if content_file.exists():
                # Delete the parent folder (e.g., data/sources/web/example_com_article/)
                folder_to_delete = content_file.parent
                if folder_to_delete.exists() and folder_to_delete.is_dir():
                    shutil.rmtree(folder_to_delete)
                    local_files_deleted = True
                    deleted_folder = str(folder_to_delete)
                    logger.info(f"Deleted local files for source {source_id}: {deleted_folder}")
        except Exception as e:
            logger.error(f"Failed to delete local files for source {source_id}: {e}")
            # Don't fail the whole operation if file deletion fails

    return {
        "deleted": source_id,
        "gluons_kept": keep_gluons,
        "local_files_deleted": local_files_deleted,
        "deleted_folder": deleted_folder
    }


# ============================================================
# Helper Functions
# ============================================================

def _parse_sections(content: str, source_id: str) -> list:
    """
    Parse [SECTION] markers from content to build section list.
    """
    sections = []

    # Find all section markers
    # Format: [SECTION] ## Heading or [SECTION] # Heading
    pattern = r"\[SECTION\]\s*(#{1,6})\s*(.+?)(?=\n)"

    for match in re.finditer(pattern, content):
        level = len(match.group(1))  # Count # symbols
        title = match.group(2).strip()
        start_offset = match.start()

        sections.append({
            "title": title,
            "level": level,
            "start_offset": start_offset,
            "end_offset": start_offset  # Will be updated
        })

    # Calculate end offsets (each section ends where the next begins)
    for i, section in enumerate(sections):
        if i + 1 < len(sections):
            section["end_offset"] = sections[i + 1]["start_offset"]
        else:
            section["end_offset"] = len(content)

    # If no sections found, create a single "Full Document" section
    if not sections:
        sections.append({
            "title": "Full Document",
            "level": 1,
            "start_offset": 0,
            "end_offset": len(content)
        })

    return sections


def _find_all_occurrences(text: str, substring: str) -> list[int]:
    """Find all starting positions of substring in text."""
    positions = []
    start = 0
    while True:
        idx = text.find(substring, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions


def _find_section_id_at_offset(
    offset: int, sections: list[dict], source_id: str
) -> str | None:
    """Find which section contains the given character offset."""
    for i, section in enumerate(sections):
        if section["start_offset"] <= offset < section["end_offset"]:
            return f"{source_id}-s{i}"
    return None


async def _relocate_highlights(
    db, source_id: str, old_content: str, new_content: str, new_sections: list[dict]
) -> dict:
    """
    Relocate highlight offsets after document edit.
    Uses stored highlight text (content field) to find new positions.
    """
    cursor = await db.execute("""
        SELECT id, content, start_offset, end_offset
        FROM gluons WHERE source_id = ? AND type = 'highlight'
    """, [source_id])
    highlights = await cursor.fetchall()

    if not highlights:
        return {"relocated": 0, "failed": 0, "total": 0}

    relocated = 0
    failed = 0

    for h_id, h_content, old_start, old_end in highlights:
        if not h_content:
            failed += 1
            continue

        # Try exact match in new content
        matches = _find_all_occurrences(new_content, h_content)

        new_start = None
        if len(matches) == 1:
            # Unique match — unambiguous
            new_start = matches[0]
        elif len(matches) > 1:
            # Multiple matches — pick the one closest to the old position
            new_start = min(matches, key=lambda m: abs(m - old_start))
        else:
            # No exact match — try normalized whitespace
            normalized_query = re.sub(r'\s+', ' ', h_content.strip())
            normalized_content = re.sub(r'\s+', ' ', new_content)
            norm_matches = _find_all_occurrences(normalized_content, normalized_query)
            if norm_matches:
                new_start = min(norm_matches, key=lambda m: abs(m - old_start))

        if new_start is not None:
            new_end = new_start + len(h_content)
            new_section_id = _find_section_id_at_offset(
                new_start, new_sections, source_id
            )

            await db.execute("""
                UPDATE gluons
                SET start_offset = ?, end_offset = ?, section_id = ?, updated_at = ?
                WHERE id = ?
            """, [new_start, new_end, new_section_id,
                  datetime.now().isoformat(), h_id])
            relocated += 1
        else:
            failed += 1

    return {"relocated": relocated, "failed": failed, "total": len(highlights)}


async def _reindex_highlights_for_source(
    db, source_id: str, content: str, sections: list[dict]
) -> dict:
    """
    Reindex all highlight offsets by matching stored text against current content.
    Used by batch migration and can be called after any edit.
    """
    cursor = await db.execute("""
        SELECT id, content, start_offset, end_offset
        FROM gluons
        WHERE source_id = ? AND type = 'highlight' AND content IS NOT NULL
    """, [source_id])
    highlights = await cursor.fetchall()

    if not highlights:
        return {"fixed": 0, "already_correct": 0, "failed": 0, "total": 0}

    fixed = 0
    already_correct = 0
    failed = 0

    for h_id, h_content, old_start, old_end in highlights:
        matches = _find_all_occurrences(content, h_content)

        if len(matches) == 1:
            new_start = matches[0]
        elif len(matches) > 1:
            # Pick closest to old position
            new_start = min(matches, key=lambda m: abs(m - old_start))
        else:
            failed += 1
            continue

        new_end = new_start + len(h_content)

        if new_start == old_start and new_end == old_end:
            already_correct += 1
            continue

        new_section_id = _find_section_id_at_offset(
            new_start, sections, source_id
        )
        await db.execute("""
            UPDATE gluons
            SET start_offset = ?, end_offset = ?, section_id = ?, updated_at = ?
            WHERE id = ?
        """, [new_start, new_end, new_section_id,
              datetime.now().isoformat(), h_id])
        fixed += 1

    return {
        "fixed": fixed,
        "already_correct": already_correct,
        "failed": failed,
        "total": len(highlights),
    }


# ============================================================
# Section Editor Endpoints
# ============================================================

@router.get("/{source_id}/raw")
async def get_raw_text(source_id: str):
    """
    Get the raw extracted text file content for editing.

    Returns:
        content: The raw text content
        content_path: Path to the file
        original_path: Path to the original PDF (for reference)
        sections: Current parsed sections
    """
    db = await get_db()

    cursor = await db.execute(
        "SELECT id, title, content_path, metadata FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    src_id, title, content_path, metadata_json = row

    if not content_path:
        raise HTTPException(status_code=404, detail="No content file for this source")

    content_file = Path(content_path)
    if not content_file.exists():
        raise HTTPException(status_code=404, detail=f"Content file not found: {content_path}")

    # Read the raw content
    content = content_file.read_text(encoding="utf-8")

    # Get original_path from metadata
    original_path = None
    if metadata_json:
        try:
            metadata = json.loads(metadata_json)
            original_path = metadata.get("original_path")
        except (json.JSONDecodeError, TypeError):
            pass

    # Get current sections
    cursor = await db.execute(
        "SELECT id, title, level, start_offset, end_offset, order_index FROM sections WHERE source_id = ? ORDER BY order_index",
        [source_id]
    )
    section_rows = await cursor.fetchall()
    sections = [
        {
            "id": r[0],
            "title": r[1],
            "level": r[2],
            "start_offset": r[3],
            "end_offset": r[4],
            "order_index": r[5]
        }
        for r in section_rows
    ]

    return {
        "source_id": source_id,
        "title": title,
        "content": content,
        "content_path": content_path,
        "original_path": original_path,
        "sections": sections,
        "char_count": len(content)
    }



class RawTextUpdate(BaseModel):
    content: str


@router.put("/{source_id}/raw")
async def update_raw_text(source_id: str, update: RawTextUpdate):
    """
    Save edited raw text and re-parse sections.

    This will:
    1. Read old content for highlight relocation
    2. Write the new content to the content file
    3. Re-parse sections from the updated content
    4. Update the sections table
    5. Relocate highlight offsets to match new content
    6. Update FTS index
    """
    db = await get_db()

    # Get source info
    cursor = await db.execute(
        "SELECT id, title, author_display, content_path FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    src_id, title, author_display, content_path = row

    if not content_path:
        raise HTTPException(status_code=400, detail="No content file for this source")

    content_file = Path(content_path)

    # Read old content before overwriting (needed for highlight relocation + backup)
    old_content = ""
    if content_file.exists():
        old_content = content_file.read_text(encoding="utf-8")

    # Save backup before overwriting (enables undo/revert)
    backup_file = content_file.with_suffix(content_file.suffix + ".bak")
    backup_file.write_text(old_content, encoding="utf-8")

    # Write the new content
    content_file.write_text(update.content, encoding="utf-8")

    # Re-parse sections
    new_sections = _parse_sections(update.content, src_id)

    # Delete old sections
    await db.execute("DELETE FROM sections WHERE source_id = ?", [src_id])

    # Insert new sections
    for i, section in enumerate(new_sections):
        section_id = f"{src_id}-s{i}"
        await db.execute("""
            INSERT INTO sections (id, source_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, src_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"], i, None
        ])

    # Relocate highlight offsets to match new content
    highlight_stats = await _relocate_highlights(
        db, src_id, old_content, update.content, new_sections
    )

    # Update FTS
    await db.execute("""
        DELETE FROM sources_fts WHERE rowid = (SELECT rowid FROM sources WHERE id = ?)
    """, [src_id])
    await db.execute("""
        INSERT INTO sources_fts (rowid, title, author_display)
        SELECT rowid, title, author_display FROM sources WHERE id = ?
    """, [src_id])

    # Update source timestamp
    now = datetime.now().isoformat()
    await db.execute("UPDATE sources SET updated_at = ? WHERE id = ?", [now, src_id])

    await db.commit()

    return {
        "source_id": src_id,
        "sections_count": len(new_sections),
        "sections": new_sections,
        "char_count": len(update.content),
        "updated_at": now,
        "highlights_relocated": highlight_stats,
    }


@router.post("/{source_id}/preview-sections")
async def preview_sections(source_id: str, update: RawTextUpdate):
    """
    Preview what sections would be parsed from edited content WITHOUT saving.
    Useful for live preview in the editor.
    """
    # Just parse and return - don't save
    sections = _parse_sections(update.content, source_id)

    return {
        "sections_count": len(sections),
        "sections": sections,
        "char_count": len(update.content)
    }


@router.post("/{source_id}/raw/revert")
async def revert_raw_text(source_id: str):
    """
    Revert the last save by restoring from backup (.bak) file.
    Re-parses sections and relocates highlights back to the old content.
    """
    db = await get_db()

    cursor = await db.execute(
        "SELECT id, title, author_display, content_path FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    src_id, title, author_display, content_path = row

    if not content_path:
        raise HTTPException(status_code=400, detail="No content file for this source")

    content_file = Path(content_path)
    backup_file = content_file.with_suffix(content_file.suffix + ".bak")

    if not backup_file.exists():
        raise HTTPException(status_code=404, detail="No backup found to revert to")

    # Read current and backup content
    current_content = content_file.read_text(encoding="utf-8") if content_file.exists() else ""
    backup_content = backup_file.read_text(encoding="utf-8")

    # Restore backup as the active content
    content_file.write_text(backup_content, encoding="utf-8")

    # Remove backup file (single-level undo)
    backup_file.unlink()

    # Re-parse sections from restored content
    new_sections = _parse_sections(backup_content, src_id)

    await db.execute("DELETE FROM sections WHERE source_id = ?", [src_id])
    for i, section in enumerate(new_sections):
        section_id = f"{src_id}-s{i}"
        await db.execute("""
            INSERT INTO sections (id, source_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, src_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"], i, None
        ])

    # Relocate highlights back to the restored content
    highlight_stats = await _relocate_highlights(
        db, src_id, current_content, backup_content, new_sections
    )

    # Update FTS
    await db.execute("""
        DELETE FROM sources_fts WHERE rowid = (SELECT rowid FROM sources WHERE id = ?)
    """, [src_id])
    await db.execute("""
        INSERT INTO sources_fts (rowid, title, author_display)
        SELECT rowid, title, author_display FROM sources WHERE id = ?
    """, [src_id])

    now = datetime.now().isoformat()
    await db.execute("UPDATE sources SET updated_at = ? WHERE id = ?", [now, src_id])

    await db.commit()

    return {
        "source_id": src_id,
        "sections_count": len(new_sections),
        "sections": new_sections,
        "char_count": len(backup_content),
        "updated_at": now,
        "highlights_relocated": highlight_stats,
    }


# =============================================================================
# AI Metadata Suggestions
# =============================================================================

class MetadataSuggestRequest(BaseModel):
    """Request for AI metadata suggestion."""
    source_ids: Optional[List[str]] = None  # If None, process all sources


# NOTE: batch-suggest-metadata MUST be defined BEFORE /{source_id}/suggest-metadata
# Otherwise FastAPI interprets "batch-suggest-metadata" as a source_id!

@router.post("/batch-suggest-metadata")
async def batch_suggest_metadata(request: MetadataSuggestRequest):
    """
    Use AI to suggest metadata for multiple sources (or all sources if source_ids is None).
    Returns suggestions for each source with confidence scores.

    Smart filtering: skips sources where previous AI suggestions have been applied
    (i.e., the suggested fields are now filled, even if values differ).
    """
    try:
        db = await get_db()
    except Exception as e:
        logger.error(f"batch_suggest_metadata DB error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    # Load suggestion history for smart filtering
    suggestion_history = _load_suggestions_history()

    # Get sources to process (excluding those with metadata_skip = true)
    if request.source_ids:
        placeholders = ",".join(["?" for _ in request.source_ids])
        cursor = await db.execute(f"""
            SELECT id, title, author_display, year, content_path, source_type, metadata
            FROM sources
            WHERE id IN ({placeholders})
            AND (metadata_skip IS NULL OR metadata_skip = 0)
        """, request.source_ids)
    else:
        cursor = await db.execute("""
            SELECT id, title, author_display, year, content_path, source_type, metadata
            FROM sources
            WHERE metadata_skip IS NULL OR metadata_skip = 0
            ORDER BY created_at DESC
        """)

    rows = await cursor.fetchall()
    # Rows are tuples, manually map to dicts
    sources = [
        {
            "id": row[0],
            "title": row[1],
            "author_display": row[2],
            "year": row[3],
            "content_path": row[4],
            "source_type": row[5],
            "metadata": row[6],
        }
        for row in rows
    ]

    if not sources:
        return {"results": [], "processed": 0, "total": 0, "skipped": 0}

    # Process each source
    results = []
    skipped_sources = []

    for source in sources:
        source_id = str(source["id"])
        content_path = source.get("content_path")

        # Parse metadata JSON for additional fields
        meta = source.get("metadata")
        if isinstance(meta, str):
            meta = json.loads(meta) if meta else {}
        elif meta is None:
            meta = {}

        # Build current metadata dict for comparison
        current_metadata = {
            "title": source.get("title"),
            "author": source.get("author_display"),
            "year": source.get("year"),
            "journal": meta.get("journal"),
            "doi": meta.get("doi"),
            "isbn": meta.get("isbn"),
        }

        # Check if we should skip this source (previous suggestions applied)
        all_applied, empty_fields = _check_suggestion_applied(
            source_id, current_metadata, suggestion_history
        )

        if all_applied and source_id in suggestion_history:
            # Previous suggestions were applied - skip
            skipped_sources.append({
                "source_id": source_id,
                "title": source.get("title", "Unknown"),
                "reason": "Previous suggestions applied"
            })
            continue

        if not content_path or not Path(content_path).exists():
            results.append({
                "source_id": source_id,
                "title": source.get("title", "Unknown"),
                "suggestions": [],
                "has_suggestions": False,
                "error": "No content file"
            })
            continue

        try:
            content = Path(content_path).read_text(encoding="utf-8")

            source_type = source.get("source_type", "document")
            suggestions = await suggest_metadata(content, source_id, current_metadata, source_type=source_type)
            result = format_suggestions_for_review(suggestions)
            result["title"] = source.get("title", "Unknown")

            # Add info about previous suggestions if any
            if source_id in suggestion_history:
                result["previously_suggested"] = True
                result["empty_fields"] = empty_fields
            else:
                result["previously_suggested"] = False

            results.append(result)

            # Record new suggestions to tracking file
            if suggestions.suggestions:
                suggestion_values = {s.field: s.value for s in suggestions.suggestions}
                _record_suggestion(source_id, suggestion_values)

        except Exception as e:
            results.append({
                "source_id": source_id,
                "title": source.get("title", "Unknown"),
                "suggestions": [],
                "has_suggestions": False,
                "error": str(e)
            })

    # Count sources with suggestions
    with_suggestions = sum(1 for r in results if r.get("has_suggestions"))

    return {
        "results": results,
        "processed": len(results),
        "total": len(sources),
        "skipped": len(skipped_sources),
        "skipped_sources": skipped_sources,
        "with_suggestions": with_suggestions
    }


# ============================================================
# Tag Management Endpoints
# ============================================================

class AddTagRequest(BaseModel):
    """Request to add a tag to a source."""
    tag: str  # Tag name (will be created if doesn't exist)


@router.get("/{source_id}/tags")
async def get_source_tags(source_id: str):
    """
    Get all tags for a source.

    Returns:
        tags: List of tag objects with id and content
    """
    db = await get_db()

    # Check source exists
    cursor = await db.execute("SELECT id FROM sources WHERE id = ?", [source_id])
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Source not found")

    # Get tags via source_gluon_links
    cursor = await db.execute("""
        SELECT g.id, g.content, sgl.position
        FROM source_gluon_links sgl
        JOIN gluons g ON sgl.gluon_id = g.id
        WHERE sgl.source_id = ? AND sgl.relationship_type = 'tag'
        ORDER BY sgl.position
    """, [source_id])
    rows = await cursor.fetchall()

    tags = [{"id": row[0], "content": row[1], "position": row[2]} for row in rows]

    return {"source_id": source_id, "tags": tags}


@router.post("/{source_id}/tags")
async def add_source_tag(source_id: str, request: AddTagRequest):
    """
    Add a tag to a source. Creates the tag gluon if it doesn't exist.

    Args:
        source_id: The source to tag
        tag: The tag name (case-insensitive lookup, preserves original case for new tags)

    Returns:
        The created/existing tag with link info
    """
    db = await get_db()

    # Check source exists
    cursor = await db.execute("SELECT id FROM sources WHERE id = ?", [source_id])
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Source not found")

    tag_name = request.tag.strip()
    if not tag_name:
        raise HTTPException(status_code=400, detail="Tag name cannot be empty")

    # Find existing tag gluon (case-insensitive)
    cursor = await db.execute("""
        SELECT id, content FROM gluons
        WHERE type = 'tag' AND LOWER(content) = LOWER(?)
    """, [tag_name])
    existing_tag = await cursor.fetchone()

    if existing_tag:
        tag_id = existing_tag[0]
        tag_content = existing_tag[1]
    else:
        # Create new tag gluon
        tag_id = str(uuid.uuid4())
        tag_content = tag_name
        await db.execute("""
            INSERT INTO gluons (id, type, content)
            VALUES (?, 'tag', ?)
        """, [tag_id, tag_content])

    # Check if link already exists
    cursor = await db.execute("""
        SELECT id FROM source_gluon_links
        WHERE source_id = ? AND gluon_id = ? AND relationship_type = 'tag'
    """, [source_id, tag_id])
    existing_link = await cursor.fetchone()

    if existing_link:
        # Already tagged
        return {
            "source_id": source_id,
            "tag": {"id": tag_id, "content": tag_content},
            "already_exists": True
        }

    # Get next position
    cursor = await db.execute("""
        SELECT COALESCE(MAX(position), -1) + 1
        FROM source_gluon_links
        WHERE source_id = ? AND relationship_type = 'tag'
    """, [source_id])
    next_position = (await cursor.fetchone())[0]

    # Create link
    link_id = f"sgl_tag_{source_id[:4]}_{tag_id[:4]}_{next_position}"
    await db.execute("""
        INSERT INTO source_gluon_links (id, source_id, gluon_id, relationship_type, position)
        VALUES (?, ?, ?, 'tag', ?)
    """, [link_id, source_id, tag_id, next_position])

    await db.commit()

    return {
        "source_id": source_id,
        "tag": {"id": tag_id, "content": tag_content},
        "already_exists": False,
        "position": next_position
    }


@router.delete("/{source_id}/tags/{tag_id}")
async def remove_source_tag(source_id: str, tag_id: str):
    """
    Remove a tag from a source.

    Note: This only removes the link, not the tag gluon itself
    (it may be used by other sources or in notes).
    """
    db = await get_db()

    # Check source exists
    cursor = await db.execute("SELECT id FROM sources WHERE id = ?", [source_id])
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Source not found")

    # Delete the link
    cursor = await db.execute("""
        DELETE FROM source_gluon_links
        WHERE source_id = ? AND gluon_id = ? AND relationship_type = 'tag'
    """, [source_id, tag_id])

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Tag not found on this source")

    await db.commit()

    return {"source_id": source_id, "removed_tag_id": tag_id}


@router.get("/tags/all")
async def list_all_tags():
    """
    Get all unique tags in the system.

    Returns:
        tags: List of tag objects with id, content, and usage count
    """
    db = await get_db()

    cursor = await db.execute("""
        SELECT g.id, g.content, COUNT(sgl.id) as usage_count
        FROM gluons g
        LEFT JOIN source_gluon_links sgl ON g.id = sgl.gluon_id AND sgl.relationship_type = 'tag'
        WHERE g.type = 'tag'
        GROUP BY g.id
        ORDER BY usage_count DESC, g.content
    """)
    rows = await cursor.fetchall()

    tags = [
        {"id": row[0], "content": row[1], "usage_count": row[2]}
        for row in rows
    ]

    return {"tags": tags, "count": len(tags)}


@router.get("/sitenames/all")
async def list_all_sitenames():
    """
    Get all unique site names from web sources.

    Returns:
        sitenames: List of site name objects with name and usage count
    """
    db = await get_db()

    cursor = await db.execute("""
        SELECT
            json_extract(metadata, '$.sitename') as sitename,
            COUNT(*) as usage_count
        FROM sources
        WHERE source_type = 'web'
        AND json_extract(metadata, '$.sitename') IS NOT NULL
        AND json_extract(metadata, '$.sitename') != ''
        GROUP BY sitename
        ORDER BY usage_count DESC, sitename
    """)
    rows = await cursor.fetchall()

    sitenames = [
        {"name": row[0], "usage_count": row[1]}
        for row in rows
    ]

    return {"sitenames": sitenames, "count": len(sitenames)}


@router.post("/{source_id}/suggest-metadata")
async def suggest_source_metadata(source_id: str):
    """
    Use AI to suggest metadata for a single source.
    Reads the extracted content and returns suggested fields with confidence scores.
    """
    try:
        db = await get_db()

        # Get source with existing metadata
        cursor = await db.execute("""
            SELECT id, title, author_display, year, content_path, source_type, metadata
            FROM sources WHERE id = ?
        """, (source_id,))
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Source not found")

        # Row is a tuple, manually map to dict
        source = {
            "id": row[0],
            "title": row[1],
            "author_display": row[2],
            "year": row[3],
            "content_path": row[4],
            "source_type": row[5],
            "metadata": row[6],
        }

        # Read content
        content_path = source.get("content_path")
        if not content_path or not Path(content_path).exists():
            raise HTTPException(status_code=400, detail="No content file found for this source")

        content = Path(content_path).read_text(encoding="utf-8")

        # Parse metadata JSON for additional fields
        meta = source.get("metadata")
        if isinstance(meta, str):
            meta = json.loads(meta) if meta else {}
        elif meta is None:
            meta = {}

        # Get AI suggestions with source-type-aware prompts
        existing_metadata = {
            "title": source.get("title"),
            "author": source.get("author_display"),
            "year": source.get("year"),
            "journal": meta.get("journal"),
            "doi": meta.get("doi"),
            "isbn": meta.get("isbn"),
        }

        source_type = source.get("source_type", "document")
        suggestions = await suggest_metadata(content, source_id, existing_metadata, source_type=source_type)

        # Record suggestions to tracking file
        if suggestions.suggestions:
            suggestion_values = {s.field: s.value for s in suggestions.suggestions}
            _record_suggestion(source_id, suggestion_values)

        return format_suggestions_for_review(suggestions)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"suggest_source_metadata error for {source_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"AI suggestion failed: {str(e)}")
