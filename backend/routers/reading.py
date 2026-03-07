"""
Reading Router
==============
API endpoints for source reading.

Endpoints:
- GET /reading/:id           - Get source content for reading
- GET /reading/:id/sections  - Get sections/ToC for source
- GET /reading/:id/section/:section_id - Get content for specific section
- PUT /reading/:id/position  - Update reading position
- GET /reading/:id/figure/:page/:index - Get cropped figure image
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from typing import Optional
from pathlib import Path
from PIL import Image
import fitz  # PyMuPDF
import json
import io

from database import get_db
from models.document import ReadingPosition

# DPI used by dots-ocr when rendering pages (for coordinate conversion)
# Note: This can vary - check intermediate JPG size vs PDF page size
DOTS_OCR_DPI = 120

# Base path for sources
DATA_DIR = Path(__file__).parent.parent.parent / "data"
SOURCES_DIR = DATA_DIR / "sources"
DOCUMENTS_DIR = SOURCES_DIR / "documents"

# Legacy path (for migration period)
LEGACY_DOCUMENTS_DIR = DATA_DIR / "documents"


def _get_documents_dir() -> Path:
    """Get the documents directory, preferring new location but falling back to legacy."""
    if DOCUMENTS_DIR.exists():
        return DOCUMENTS_DIR
    if LEGACY_DOCUMENTS_DIR.exists():
        return LEGACY_DOCUMENTS_DIR
    return DOCUMENTS_DIR


router = APIRouter()


@router.get("/{source_id}")
async def get_source_content(
    source_id: str,
    include_sections: bool = Query(True, description="Include sections list")
):
    """
    Get full source content for reading.
    Returns the extracted text and section markers.
    """
    db = await get_db()

    # Get source
    cursor = await db.execute(
        "SELECT * FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    columns = [desc[0] for desc in cursor.description]
    source = dict(zip(columns, row))

    # Parse metadata JSON
    metadata = {}
    if source.get("metadata"):
        try:
            metadata = json.loads(source["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass

    # Read extracted text
    content_path = source.get("content_path")
    if not content_path or not Path(content_path).exists():
        raise HTTPException(
            status_code=404,
            detail="Content file not found"
        )

    content = Path(content_path).read_text(encoding="utf-8")

    result = {
        "id": source_id,
        "title": source["title"],
        "author": source.get("author_display"),  # Map to 'author' for API compatibility
        "author_display": source.get("author_display"),
        "year": source.get("year"),
        "source_type": source.get("source_type"),
        "content": content,
        "content_length": len(content),
        "url": source.get("url"),
        "metadata_skip": source.get("metadata_skip"),
        # Document-specific fields from metadata
        "original_path": metadata.get("original_path"),
        # BIBCITE metadata from metadata JSON
        "journal": metadata.get("journal"),
        "volume": metadata.get("volume"),
        "issue": metadata.get("issue"),
        "pages": metadata.get("pages"),
        "doi": metadata.get("doi"),
        "isbn": metadata.get("isbn"),
        "issn": metadata.get("issn"),
        "abstract": metadata.get("abstract"),
        "edition": metadata.get("edition"),
        "series": metadata.get("series"),
        # Video/media metadata
        "video_id": metadata.get("video_id"),
        "platform": metadata.get("platform"),
        "channel": metadata.get("channel"),
        "duration_formatted": metadata.get("duration_formatted"),
        # Include raw metadata for modal
        "metadata": metadata,
    }

    # Fetch linked gluon data (authors, editors, keywords) like get_source does
    for rel_type, gluon_ids_field, content_field in [
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
            content_objects = [{"id": row[0], "content": row[1]} for row in rows]
            result[gluon_ids_field] = json.dumps(gluon_ids)
            result[content_field] = content_objects
        else:
            # Fall back to metadata string if no linked gluons
            if content_field == "keywords":
                result[content_field] = metadata.get("keywords")
            elif content_field == "editors":
                result[content_field] = metadata.get("editors")

    # Include source analyses (Summary, Key Claims, etc.)
    cursor = await db.execute(
        """SELECT id, analysis_type, display_name, content, model, cost_usd,
                  tokens_input, tokens_output, created_at
           FROM source_analyses
           WHERE source_id = ?
           ORDER BY created_at""",
        [source_id]
    )
    analysis_rows = await cursor.fetchall()
    analysis_cols = [desc[0] for desc in cursor.description]
    result["analyses"] = [
        dict(zip(analysis_cols, row))
        for row in analysis_rows
    ]

    # Include sections if requested
    if include_sections:
        cursor = await db.execute(
            """SELECT * FROM sections
               WHERE source_id = ?
               ORDER BY order_index""",
            [source_id]
        )
        section_rows = await cursor.fetchall()
        section_cols = [desc[0] for desc in cursor.description]

        result["sections"] = [
            dict(zip(section_cols, row))
            for row in section_rows
        ]

    # Include reading position
    if source.get("reading_position"):
        try:
            result["reading_position"] = json.loads(source["reading_position"])
        except (json.JSONDecodeError, TypeError):
            pass

    return result


@router.get("/{source_id}/sections")
async def get_sections(source_id: str):
    """
    Get sections/table of contents for a source.
    Returns hierarchical section structure.
    """
    db = await get_db()

    # Verify source exists
    cursor = await db.execute(
        "SELECT id FROM sources WHERE id = ?",
        [source_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Source not found")

    # Get sections
    cursor = await db.execute(
        """SELECT * FROM sections
           WHERE source_id = ?
           ORDER BY order_index""",
        [source_id]
    )
    rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]

    sections = [dict(zip(columns, row)) for row in rows]

    return {
        "source_id": source_id,
        "count": len(sections),
        "sections": sections
    }


@router.get("/{source_id}/section/{section_id}")
async def get_section_content(
    source_id: str,
    section_id: str,
    context_chars: int = Query(0, ge=0, description="Include chars before/after")
):
    """
    Get content for a specific section.
    Optionally include surrounding context.
    """
    db = await get_db()

    # Get source and section
    cursor = await db.execute(
        """SELECT s.content_path, sec.*
           FROM sources s
           JOIN sections sec ON sec.source_id = s.id
           WHERE s.id = ? AND sec.id = ?""",
        [source_id, section_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Section not found")

    columns = [desc[0] for desc in cursor.description]
    data = dict(zip(columns, row))

    # Read content
    content_path = data.get("content_path")
    if not content_path or not Path(content_path).exists():
        raise HTTPException(status_code=404, detail="Content file not found")

    full_content = Path(content_path).read_text(encoding="utf-8")

    # Extract section content
    start = data["start_offset"]
    end = data["end_offset"]

    # Apply context if requested
    if context_chars > 0:
        start = max(0, start - context_chars)
        end = min(len(full_content), end + context_chars)

    section_content = full_content[start:end]

    return {
        "section_id": section_id,
        "source_id": source_id,
        "title": data["title"],
        "level": data["level"],
        "content": section_content,
        "start_offset": data["start_offset"],
        "end_offset": data["end_offset"],
        "actual_start": start,
        "actual_end": end,
    }


@router.put("/{source_id}/position")
async def update_reading_position(
    source_id: str,
    position: ReadingPosition
):
    """
    Update reading position for a source.
    Called periodically as user scrolls.
    """
    db = await get_db()

    # Verify source exists
    cursor = await db.execute(
        "SELECT id FROM sources WHERE id = ?",
        [source_id]
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Source not found")

    # Update position
    position_json = json.dumps(position.model_dump())

    await db.execute(
        """UPDATE sources
           SET reading_position = ?, updated_at = datetime('now')
           WHERE id = ?""",
        [position_json, source_id]
    )
    await db.commit()

    return {"updated": True, "position": position}


@router.post("/{source_id}/open-original")
async def open_original(source_id: str):
    """
    Open the original PDF in the system's default PDF viewer.
    For web sources, opens the URL in browser.
    """
    import subprocess
    import sys
    import webbrowser

    db = await get_db()

    cursor = await db.execute(
        "SELECT source_type, url, metadata FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    source_type, url, metadata_json = row

    # Parse metadata
    metadata = {}
    if metadata_json:
        try:
            metadata = json.loads(metadata_json)
        except (json.JSONDecodeError, TypeError):
            pass

    # For web sources, open URL in browser
    if source_type == "web" and url:
        webbrowser.open(url)
        return {"url": url, "opened": True}

    # For documents, open the original file
    original_path = metadata.get("original_path")

    if not original_path:
        raise HTTPException(
            status_code=404,
            detail="Original file path not recorded"
        )

    file_path = Path(original_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Original file not found: {original_path}"
        )

    # Open file with system default application
    try:
        if sys.platform == 'win32':
            import os
            os.startfile(str(file_path))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(file_path)], check=True)
        else:
            subprocess.run(['xdg-open', str(file_path)], check=True)

        return {
            "path": original_path,
            "opened": True
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to open file: {str(e)}"
        )


@router.get("/{source_id}/pdf")
async def serve_pdf(source_id: str):
    """
    Serve the original PDF file for embedding in iframe.
    Used by the Section Editor for side-by-side viewing.
    """
    from fastapi.responses import FileResponse

    db = await get_db()

    cursor = await db.execute(
        "SELECT metadata FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    metadata_json = row[0]

    # Parse metadata
    metadata = {}
    if metadata_json:
        try:
            metadata = json.loads(metadata_json)
        except (json.JSONDecodeError, TypeError):
            pass

    original_path = metadata.get("original_path")

    if not original_path:
        raise HTTPException(
            status_code=404,
            detail="Original file path not recorded"
        )

    file_path = Path(original_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Original file not found: {original_path}"
        )

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=file_path.name,
        headers={
            "Content-Disposition": f"inline; filename=\"{file_path.name}\""
        }
    )


@router.get("/{source_id}/figure/{page}/{figure_index}")
async def get_figure(
    source_id: str,
    page: int,
    figure_index: int,
    method: str = Query("dots-ocr", description="Processing method folder")
):
    """
    Get a cropped figure image from intermediate files.

    Crops the figure from the page image using bbox coordinates from the JSON.
    - page: 0-indexed page number
    - figure_index: 0-indexed index of Picture element on that page
    - method: processing method (dots-ocr, pymupdf, tesseract)
    """
    db = await get_db()
    docs_dir = _get_documents_dir()

    # Get source content_path from database
    cursor = await db.execute(
        "SELECT content_path FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    content_path = row[0]

    # Determine the method folder from content_path
    # New format: .../DocumentName--method/DocumentName--method--extracted.txt
    # Old format: .../output/LIT-xxx.txt (no intermediates available)
    method_folder = None
    doc_folder = None

    if content_path:
        ext_path = Path(content_path)

        # Check if content path is in new structure
        if "--" in ext_path.parent.name:
            method_folder = ext_path.parent
            doc_folder = method_folder.parent
        else:
            # Old structure - search docs_dir for matching folder
            for folder in docs_dir.iterdir():
                if folder.is_dir():
                    mf = folder / f"{folder.name}--{method}"
                    if mf.exists():
                        page_json = mf / f"{folder.name}--page_{page}.json"
                        if page_json.exists():
                            doc_folder = folder
                            method_folder = mf
                            break

    if not method_folder or not doc_folder:
        raise HTTPException(
            status_code=404,
            detail=f"Intermediate files not found for source {source_id}"
        )

    folder_name = doc_folder.name

    # FAST PATH: Check for pre-cropped figure file first
    precropped_path = method_folder / f"{folder_name}--figure_{page}_{figure_index}.jpg"
    if precropped_path.exists():
        return Response(
            content=precropped_path.read_bytes(),
            media_type="image/jpeg",
            headers={
                "Cache-Control": "max-age=86400",  # Cache for 24 hours (static file)
                "X-Figure-Page": str(page),
                "X-Figure-Index": str(figure_index),
                "X-Figure-Source": "precropped"
            }
        )

    # FALLBACK: Crop from PDF on-demand
    # Read the page JSON - try both naming conventions
    page_json_path = method_folder / f"{folder_name}_page_{page}.json"
    if not page_json_path.exists():
        page_json_path = method_folder / f"{folder_name}--page_{page}.json"
    if not page_json_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Page {page} JSON not found"
        )

    with open(page_json_path, 'r', encoding='utf-8') as f:
        elements = json.load(f)

    # Handle double-encoded JSON (string containing JSON)
    if isinstance(elements, str):
        elements = json.loads(elements)

    # Find all Picture elements
    pictures = [e for e in elements if e.get('category') == 'Picture']

    if figure_index >= len(pictures):
        raise HTTPException(
            status_code=404,
            detail=f"Figure {figure_index} not found on page {page}. Found {len(pictures)} figures."
        )

    picture = pictures[figure_index]
    bbox = picture.get('bbox')

    if not bbox or len(bbox) != 4:
        raise HTTPException(
            status_code=400,
            detail="Invalid bbox coordinates"
        )

    # Find the PDF file
    pdf_path = doc_folder / f"{folder_name}.pdf"
    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"PDF not found: {pdf_path.name}"
        )

    # Convert bbox from dots-ocr pixel coords to PDF points
    # dots-ocr uses 144 DPI, PDF uses 72 points per inch
    scale = DOTS_OCR_DPI / 72  # 2.0
    x1, y1, x2, y2 = bbox
    pdf_rect = fitz.Rect(
        x1 / scale,
        y1 / scale,
        x2 / scale,
        y2 / scale
    )

    # Render the figure from PDF at high quality
    doc = fitz.open(pdf_path)
    if page >= len(doc):
        doc.close()
        raise HTTPException(status_code=404, detail=f"Page {page} not found in PDF")

    pdf_page = doc[page]

    # Render at 2x zoom for crisp output
    mat = fitz.Matrix(2, 2)
    pix = pdf_page.get_pixmap(matrix=mat, clip=pdf_rect)
    doc.close()

    # Convert to JPEG bytes
    img_bytes = io.BytesIO(pix.tobytes("jpeg"))

    return Response(
        content=img_bytes.getvalue(),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "max-age=3600",  # Cache for 1 hour
            "X-Figure-Page": str(page),
            "X-Figure-Index": str(figure_index),
            "X-Figure-Bbox": f"{x1},{y1},{x2},{y2}",
            "X-Figure-Source": "on-demand"  # Cropped from PDF on this request
        }
    )


@router.get("/{source_id}/figures")
async def list_figures(
    source_id: str,
    method: str = Query("dots-ocr", description="Processing method folder")
):
    """
    List all figures in a source with their page and bbox info.
    Useful for pre-loading figure metadata.
    """
    db = await get_db()
    docs_dir = _get_documents_dir()

    # Get source content_path
    cursor = await db.execute(
        "SELECT content_path FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    content_path = row[0]

    # Determine the method folder from content_path
    method_folder = None
    doc_folder = None

    if content_path:
        ext_path = Path(content_path)

        # Check if content path is in new structure
        if "--" in ext_path.parent.name:
            method_folder = ext_path.parent
            doc_folder = method_folder.parent
        else:
            # Old structure - search docs_dir for matching folder
            for folder in docs_dir.iterdir():
                if folder.is_dir():
                    mf = folder / f"{folder.name}--{method}"
                    if mf.exists():
                        doc_folder = folder
                        method_folder = mf
                        break

    if not method_folder or not doc_folder:
        # No intermediate files available - return empty figures list
        return {
            "source_id": source_id,
            "method": method,
            "count": 0,
            "figures": [],
            "note": "No intermediate files available for this source"
        }

    folder_name = doc_folder.name

    # Scan all page JSONs for Picture elements
    figures = []
    page_num = 0

    while True:
        # Try both naming conventions: _page_ (RunPod) and --page_ (old)
        page_json = method_folder / f"{folder_name}_page_{page_num}.json"
        if not page_json.exists():
            page_json = method_folder / f"{folder_name}--page_{page_num}.json"
        if not page_json.exists():
            break

        try:
            with open(page_json, 'r', encoding='utf-8') as f:
                elements = json.load(f)

            # Handle double-encoded JSON (string containing JSON)
            if isinstance(elements, str):
                elements = json.loads(elements)
        except json.JSONDecodeError:
            # Skip corrupted pages
            page_num += 1
            continue

        # Find pictures and their captions
        for idx, elem in enumerate(elements):
            if elem.get('category') == 'Picture':
                # Look for caption right after
                caption = None
                for next_elem in elements[idx+1:idx+3]:
                    if next_elem.get('category') == 'Caption':
                        caption = next_elem.get('text', '')
                        break

                fig_idx = len([f for f in figures if f['page'] == page_num])
                figures.append({
                    "page": page_num,
                    "index": fig_idx,
                    "bbox": elem.get('bbox'),
                    "caption": caption,
                    "url": f"/reading/{source_id}/figure/{page_num}/{fig_idx}?method={method}"
                })

        page_num += 1

    return {
        "source_id": source_id,
        "method": method,
        "count": len(figures),
        "figures": figures
    }


@router.get("/{source_id}/web-figure/{filename}")
async def get_web_figure(source_id: str, filename: str):
    """
    Get a figure image from a web or thread source.

    Web sources store downloaded images in a figures/ subfolder.
    Thread sources store media in a media/ subfolder.
    The filename is referenced in the extracted text as [FIGURE filename].
    """
    db = await get_db()

    # Get source info
    cursor = await db.execute(
        "SELECT content_path, source_type FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    content_path, source_type = row

    # Security: validate filename (prevent path traversal)
    if '/' in filename or '\\' in filename or '..' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Get the source folder from content_path
    source_folder = Path(content_path).parent

    # Different source types store media in different subfolders
    if source_type == 'thread':
        figure_path = source_folder / "media" / filename
    elif source_type == 'document':
        # EPUB and other document sources: figures/ inside the method folder
        # content_path points to the extracted.txt inside the method folder
        figure_path = source_folder / "figures" / filename
    else:
        # web and media sources use figures/ subfolder
        figure_path = source_folder / "figures" / filename

    if not figure_path.exists():
        raise HTTPException(status_code=404, detail=f"Figure not found: {filename}")

    # Determine media type
    ext = figure_path.suffix.lower()
    media_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.svg': 'image/svg+xml',
    }
    media_type = media_types.get(ext, 'application/octet-stream')

    return Response(
        content=figure_path.read_bytes(),
        media_type=media_type,
        headers={
            "Cache-Control": "max-age=86400",  # Cache for 24 hours
            "X-Figure-Source": "web-download"
        }
    )


@router.get("/{source_id}/web-figures")
async def list_web_figures(source_id: str):
    """
    List all figures for a web source.

    Returns figure metadata from figures.json in the source folder.
    """
    db = await get_db()

    # Get source info
    cursor = await db.execute(
        "SELECT content_path, source_type FROM sources WHERE id = ?",
        [source_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    content_path, source_type = row

    if source_type != 'web':
        raise HTTPException(
            status_code=400,
            detail="This endpoint is for web sources only"
        )

    # Get the source folder from content_path
    source_folder = Path(content_path).parent
    figures_json = source_folder / "figures.json"

    if not figures_json.exists():
        return {
            "source_id": source_id,
            "count": 0,
            "figures": []
        }

    import json
    figures = json.loads(figures_json.read_text(encoding='utf-8'))

    # Filter to only downloaded figures and add URLs
    downloaded = []
    for fig in figures:
        if fig.get('downloaded'):
            downloaded.append({
                "index": fig.get('index'),
                "filename": fig.get('filename'),
                "alt": fig.get('alt', ''),
                "url": f"/reading/{source_id}/web-figure/{fig.get('filename')}"
            })

    return {
        "source_id": source_id,
        "count": len(downloaded),
        "figures": downloaded
    }
