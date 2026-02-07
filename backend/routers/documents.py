"""
Documents Router
================
API endpoints for document management.

Endpoints:
- GET    /documents          - List all documents
- GET    /documents/:id      - Get single document
- POST   /documents/import   - Import new PDF/EPUB (fresh extraction)
- POST   /documents/import-processed - Import pre-processed files from Lit Processor
- POST   /documents/scan-lit-processor - Scan Lit Processor output folder
- PATCH  /documents/:id      - Update document metadata
- DELETE /documents/:id      - Delete document
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from typing import List, Optional
from pathlib import Path
import uuid
import re
import json
import hashlib
from datetime import datetime

from database import get_db
from models.document import (
    Document, DocumentCreate, DocumentUpdate,
    Section, DocType, SourceType, ReadingPosition
)

router = APIRouter()

# Lit Processor paths (configurable)
LIT_PROCESSOR_OUTPUT = Path(r"C:\Users\bhara\dev\lit-processor\output")
LIT_PROCESSOR_UPLOADS = Path(r"C:\Users\bhara\dev\lit-processor\uploads")

# Scholia data paths
DATA_DIR = Path(__file__).parent.parent.parent / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"


@router.get("", response_model=List[Document])
async def list_documents(
    doc_type: Optional[DocType] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    List all documents in the library.
    Optionally filter by document type.
    """
    db = await get_db()

    query = "SELECT * FROM documents"
    params = []

    if doc_type:
        query += " WHERE doc_type = ?"
        params.append(doc_type.value)

    query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    # Convert rows to dicts
    columns = [desc[0] for desc in cursor.description]
    documents = []
    for row in rows:
        doc_dict = dict(zip(columns, row))
        # Parse reading_position JSON if present
        if doc_dict.get("reading_position"):
            doc_dict["reading_position"] = json.loads(doc_dict["reading_position"])
        documents.append(doc_dict)

    return documents


@router.get("/{document_id}", response_model=Document)
async def get_document(document_id: str):
    """Get a single document by ID."""
    db = await get_db()

    cursor = await db.execute(
        "SELECT * FROM documents WHERE id = ?",
        [document_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    columns = [desc[0] for desc in cursor.description]
    doc_dict = dict(zip(columns, row))

    if doc_dict.get("reading_position"):
        doc_dict["reading_position"] = json.loads(doc_dict["reading_position"])

    return doc_dict


@router.post("/scan-lit-processor")
async def scan_lit_processor():
    """
    Scan Lit Processor output folder and return available files.
    Returns list of files that can be imported, with metadata parsed from filenames.
    """
    if not LIT_PROCESSOR_OUTPUT.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Lit Processor output folder not found: {LIT_PROCESSOR_OUTPUT}"
        )

    # Find all .txt files in output
    txt_files = list(LIT_PROCESSOR_OUTPUT.glob("LIT-*.txt"))

    available = []
    for txt_path in txt_files:
        # Parse metadata from filename
        # Format: LIT-{id}_{Author_Year_Title}.txt or LIT-{Author_Year_Title}.txt
        filename = txt_path.stem  # Remove .txt
        metadata = _parse_lit_filename(filename)

        # Try to find matching PDF (pass full metadata for better matching)
        pdf_path = _find_matching_pdf(metadata.get("id"), metadata.get("raw_name"), metadata)

        available.append({
            "txt_path": str(txt_path),
            "pdf_path": str(pdf_path) if pdf_path else None,
            "filename": txt_path.name,
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
    Import a pre-processed file from Lit Processor.

    Args:
        txt_path: Path to the extracted .txt file
        pdf_path: Optional path to the original PDF
        title, author, year: Optional metadata overrides
    """
    txt_file = Path(txt_path)
    if not txt_file.exists():
        raise HTTPException(status_code=404, detail=f"Text file not found: {txt_path}")

    # Parse metadata from filename if not provided
    metadata = _parse_lit_filename(txt_file.stem)

    title = title or metadata.get("title", txt_file.stem)
    author = author or metadata.get("author")
    year = year or metadata.get("year")

    # Generate document ID
    doc_id = str(uuid.uuid4())[:8]

    # Read the text content to extract sections
    content = txt_file.read_text(encoding="utf-8")
    sections = _parse_sections(content, doc_id)

    # Copy txt file to Scholia's data folder (or just reference it)
    # For now, we'll reference the original location
    extracted_path = str(txt_file)

    # Validate PDF path if provided
    original_path = None
    if pdf_path:
        pdf_file = Path(pdf_path)
        if pdf_file.exists():
            original_path = str(pdf_file)

    # Insert into database
    db = await get_db()
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO documents (id, title, author, year, doc_type, source_type,
                               original_path, extracted_path, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        doc_id, title, author, year, "article", "pdf",
        original_path, extracted_path, now, now
    ])

    # Insert sections
    for i, section in enumerate(sections):
        section_id = f"{doc_id}-s{i}"
        await db.execute("""
            INSERT INTO sections (id, document_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, doc_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"], i, None
        ])

    # Index in FTS
    await db.execute("""
        INSERT INTO documents_fts (rowid, title, author, full_text)
        SELECT rowid, title, author, ? FROM documents WHERE id = ?
    """, [content, doc_id])

    await db.commit()

    return {
        "id": doc_id,
        "title": title,
        "author": author,
        "year": year,
        "sections_count": len(sections),
        "original_path": original_path,
        "extracted_path": extracted_path
    }


@router.post("/scan-documents-folder")
async def scan_documents_folder():
    """
    Scan the new documents folder structure and return available files.
    New structure: documents/{AuthorYear}/AuthorYear--method/AuthorYear--method--extracted.txt
    """
    if not DOCUMENTS_DIR.exists():
        raise HTTPException(status_code=404, detail=f"Documents folder not found: {DOCUMENTS_DIR}")

    available = []
    for doc_folder in DOCUMENTS_DIR.iterdir():
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


@router.post("/import-from-documents-folder")
async def import_from_documents_folder():
    """
    Import all documents from the new documents folder structure.
    Clears existing documents and re-imports fresh.

    WARNING: This clears all existing documents. Use /refresh instead for non-destructive import.
    """
    db = await get_db()

    # Clear existing documents
    await db.execute("DELETE FROM documents_fts")
    await db.execute("DELETE FROM sections")
    await db.execute("DELETE FROM documents")
    await db.commit()

    # Scan for documents
    scan_result = await scan_documents_folder()

    imported = []
    for file_info in scan_result["files"]:
        try:
            result = await import_processed(
                txt_path=file_info["extracted_path"],
                pdf_path=file_info.get("pdf_path"),
                title=file_info.get("title"),
                author=file_info.get("author"),
                year=file_info.get("year")
            )
            imported.append(result)
        except Exception as e:
            imported.append({"error": str(e), "file": file_info["folder_name"]})

    return {
        "imported_count": len([i for i in imported if "id" in i]),
        "imported": imported
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


@router.post("/refresh")
async def refresh_documents():
    """
    Scan documents folder and import new documents without clearing existing ones.

    This is the safe way to add newly processed documents to the library:
    - Imports documents that aren't in the database yet
    - Updates existing documents if a higher-quality extraction is available (dots-ocr > marker)
    - Preserves existing highlights and notes
    - Uses normalized paths to prevent duplicates from path variations

    Returns:
        imported: list of newly imported documents
        updated: list of documents updated to better extraction
        skipped: list of documents already up-to-date
    """
    if not DOCUMENTS_DIR.exists():
        raise HTTPException(status_code=404, detail=f"Documents folder not found: {DOCUMENTS_DIR}")

    db = await get_db()

    # Tier priority: higher = better quality
    TIER_PRIORITY = {
        "tesseract": 1,
        "pymupdf": 2,
        "marker": 3,
        "dots-ocr": 4,
    }

    # Get existing documents indexed by BOTH original_path AND extracted_path (normalized)
    cursor = await db.execute("SELECT id, original_path, extracted_path FROM documents")
    rows = await cursor.fetchall()
    existing_by_original = {}  # normalized original_path -> doc info
    existing_by_extracted = {}  # normalized extracted_path -> doc info
    for doc_id, orig_path, extr_path in rows:
        norm_orig = _normalize_path(orig_path)
        norm_extr = _normalize_path(extr_path)
        doc_info = {"id": doc_id, "extracted_path": extr_path}
        if norm_orig:
            existing_by_original[norm_orig] = doc_info
        if norm_extr:
            existing_by_extracted[norm_extr] = doc_info

    imported = []
    updated = []
    skipped = []
    errors = []

    for doc_folder in DOCUMENTS_DIR.iterdir():
        if not doc_folder.is_dir() or doc_folder.name.startswith("_"):
            continue

        folder_name = doc_folder.name

        # Find all available extraction methods
        # Search for any subfolder matching *--{method} and any extracted.txt inside
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
        norm_extracted_path = _normalize_path(best_method["path"])

        # Parse metadata from folder name
        metadata = _parse_folder_name(folder_name)

        try:
            # Check if document exists by EITHER original_path OR extracted_path
            existing = None
            if norm_pdf_path and norm_pdf_path in existing_by_original:
                existing = existing_by_original[norm_pdf_path]
            elif norm_extracted_path and norm_extracted_path in existing_by_extracted:
                existing = existing_by_extracted[norm_extracted_path]

            if existing:
                # Document exists - check if we should update
                existing_extracted = existing["extracted_path"] or ""

                # Determine existing tier
                existing_tier = None
                existing_priority = 0
                for method in TIER_PRIORITY:
                    if f"--{method}--" in existing_extracted:
                        existing_tier = method
                        existing_priority = TIER_PRIORITY[method]
                        break

                if best_method["priority"] > existing_priority:
                    # Upgrade to better extraction
                    doc_id = existing["id"]
                    now = datetime.now().isoformat()

                    # Read content for sections
                    content = Path(best_method["path"]).read_text(encoding="utf-8")
                    sections = _parse_sections(content, doc_id)

                    # Update document
                    await db.execute("""
                        UPDATE documents
                        SET extracted_path = ?, updated_at = ?
                        WHERE id = ?
                    """, [best_method["path"], now, doc_id])

                    # Re-index sections
                    await db.execute("DELETE FROM sections WHERE document_id = ?", [doc_id])
                    for i, section in enumerate(sections):
                        section_id = f"{doc_id}-s{i}"
                        await db.execute("""
                            INSERT INTO sections (id, document_id, title, level, start_offset,
                                                  end_offset, order_index, parent_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, [
                            section_id, doc_id, section["title"], section["level"],
                            section["start_offset"], section["end_offset"], i, None
                        ])

                    # Update FTS
                    await db.execute("""
                        DELETE FROM documents_fts WHERE rowid = (SELECT rowid FROM documents WHERE id = ?)
                    """, [doc_id])
                    await db.execute("""
                        INSERT INTO documents_fts (rowid, title, author, full_text)
                        SELECT rowid, title, author, ? FROM documents WHERE id = ?
                    """, [content, doc_id])

                    updated.append({
                        "id": doc_id,
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
                # New document - import it
                doc_id = str(uuid.uuid4())[:8]
                now = datetime.now().isoformat()

                # Compute PDF hash for future duplicate detection
                pdf_hash = _compute_pdf_hash(pdf_path) if pdf_path.exists() else None

                # Read content for sections and FTS
                content = Path(best_method["path"]).read_text(encoding="utf-8")
                sections = _parse_sections(content, doc_id)

                await db.execute("""
                    INSERT INTO documents (id, title, author, year, doc_type, source_type,
                                           original_path, extracted_path, pdf_hash, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    doc_id,
                    metadata.get("title", folder_name),
                    metadata.get("author"),
                    metadata.get("year"),
                    "article",
                    "pdf",
                    pdf_path_str,
                    best_method["path"],
                    pdf_hash,
                    now,
                    now
                ])

                # Insert sections
                for i, section in enumerate(sections):
                    section_id = f"{doc_id}-s{i}"
                    await db.execute("""
                        INSERT INTO sections (id, document_id, title, level, start_offset,
                                              end_offset, order_index, parent_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        section_id, doc_id, section["title"], section["level"],
                        section["start_offset"], section["end_offset"], i, None
                    ])

                # Index in FTS
                await db.execute("""
                    INSERT INTO documents_fts (rowid, title, author, full_text)
                    SELECT rowid, title, author, ? FROM documents WHERE id = ?
                """, [content, doc_id])

                imported.append({
                    "id": doc_id,
                    "folder_name": folder_name,
                    "title": metadata.get("title", folder_name),
                    "method": best_method["method"]
                })

        except Exception as e:
            errors.append({
                "folder_name": folder_name,
                "error": str(e)
            })

    await db.commit()

    return {
        "imported_count": len(imported),
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "errors": errors
    }


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


@router.post("/import-all-processed")
async def import_all_processed():
    """
    Import all pre-processed files from Lit Processor that aren't already imported.
    """
    # Get list of already imported extracted_paths
    db = await get_db()
    cursor = await db.execute("SELECT extracted_path FROM documents")
    rows = await cursor.fetchall()
    imported_paths = {row[0] for row in rows if row[0]}

    # Scan for available files
    scan_result = await scan_lit_processor()

    imported = []
    skipped = []

    for file_info in scan_result["files"]:
        txt_path = file_info["txt_path"]

        if txt_path in imported_paths:
            skipped.append(txt_path)
            continue

        try:
            result = await import_processed(
                txt_path=txt_path,
                pdf_path=file_info.get("pdf_path"),
                title=file_info.get("title"),
                author=file_info.get("author"),
                year=file_info.get("year")
            )
            imported.append(result)
        except Exception as e:
            skipped.append({"path": txt_path, "error": str(e)})

    return {
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "imported": imported,
        "skipped": skipped
    }


@router.patch("/{document_id}", response_model=Document)
async def update_document(document_id: str, updates: DocumentUpdate):
    """Update document metadata."""
    db = await get_db()

    # Build update query dynamically
    update_fields = []
    params = []

    for field, value in updates.model_dump(exclude_unset=True).items():
        if value is not None:
            update_fields.append(f"{field} = ?")
            params.append(value.value if hasattr(value, "value") else value)

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    update_fields.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(document_id)

    query = f"UPDATE documents SET {', '.join(update_fields)} WHERE id = ?"
    await db.execute(query, params)
    await db.commit()

    return await get_document(document_id)


@router.get("/{document_id}/gluon-stats")
async def get_document_gluon_stats(document_id: str):
    """
    Get counts of highlights and notes attached to this document.
    Used to show warning before delete.
    """
    db = await get_db()

    # Check document exists
    cursor = await db.execute("SELECT id, title FROM documents WHERE id = ?", [document_id])
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_title = row[1]

    # Count highlights
    cursor = await db.execute(
        "SELECT COUNT(*) FROM gluons WHERE document_id = ? AND type = 'highlight'",
        [document_id]
    )
    highlight_count = (await cursor.fetchone())[0]

    # Count notes (attached to document or to highlights in this document)
    cursor = await db.execute("""
        SELECT COUNT(*) FROM gluons
        WHERE type = 'note' AND (
            document_id = ?
            OR parent_gluon_id IN (SELECT id FROM gluons WHERE document_id = ? AND type = 'highlight')
        )
    """, [document_id, document_id])
    note_count = (await cursor.fetchone())[0]

    return {
        "document_id": document_id,
        "title": doc_title,
        "highlight_count": highlight_count,
        "note_count": note_count,
        "total_gluons": highlight_count + note_count
    }


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    keep_gluons: bool = Query(False, description="If true, keep highlights/notes as orphans")
):
    """
    Delete a document.

    Args:
        document_id: The document to delete
        keep_gluons: If true, highlights and notes will become orphans (document_id set to NULL).
                     If false (default), all gluons will be deleted with the document.
    """
    db = await get_db()

    # Check document exists
    cursor = await db.execute("SELECT id FROM documents WHERE id = ?", [document_id])
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Document not found")

    if not keep_gluons:
        # Explicitly delete gluons (since we now use SET NULL, cascade won't do it)
        # First delete from FTS
        await db.execute("""
            DELETE FROM gluons_fts WHERE rowid IN
            (SELECT rowid FROM gluons WHERE document_id = ?)
        """, [document_id])

        # Delete links for gluons in this document
        await db.execute("""
            DELETE FROM links WHERE source_id IN
            (SELECT id FROM gluons WHERE document_id = ?)
            OR target_id IN
            (SELECT id FROM gluons WHERE document_id = ?)
        """, [document_id, document_id])

        # Delete the gluons
        await db.execute("DELETE FROM gluons WHERE document_id = ?", [document_id])

    # Delete sections
    await db.execute("DELETE FROM sections WHERE document_id = ?", [document_id])

    # Delete the document
    await db.execute("DELETE FROM documents WHERE id = ?", [document_id])

    # Remove from FTS
    await db.execute("""
        DELETE FROM documents_fts WHERE rowid NOT IN
        (SELECT rowid FROM documents)
    """)

    await db.commit()

    return {
        "deleted": document_id,
        "gluons_kept": keep_gluons
    }


# ============================================================
# Helper Functions
# ============================================================

def _parse_lit_filename(filename: str) -> dict:
    """
    Parse metadata from Lit Processor filename.

    Formats:
    - LIT-{8char_id}_{Author_Year_Title}
    - LIT-{Author_Year_Title}

    Returns dict with: id, author, year, title, raw_name
    """
    result = {"raw_name": filename}

    # Remove LIT- prefix
    if filename.startswith("LIT-"):
        filename = filename[4:]

    # Check for 8-char ID prefix (hex)
    id_match = re.match(r"^([0-9a-fA-F]{8})_(.+)$", filename)
    if id_match:
        result["id"] = id_match.group(1)
        filename = id_match.group(2)

    # Parse Author_Year_Title pattern
    # Example: Ba_Et_Al_2016_Using_Fast_Weights_To_Attend_To_The_Recent_Past
    parts = filename.split("_")

    # Try to find year (4 digits)
    year_idx = None
    for i, part in enumerate(parts):
        if re.match(r"^\d{4}$", part):
            year_idx = i
            result["year"] = int(part)
            break

    if year_idx is not None:
        # Author is everything before year
        author_parts = parts[:year_idx]
        # Convert "Et_Al" to "et al."
        author = " ".join(author_parts).replace(" Et Al", " et al.")
        result["author"] = author

        # Title is everything after year
        title_parts = parts[year_idx + 1:]
        result["title"] = " ".join(title_parts)
    else:
        # No year found, use whole thing as title
        result["title"] = " ".join(parts)

    return result


def _find_matching_pdf(file_id: Optional[str], raw_name: Optional[str], metadata: Optional[dict] = None) -> Optional[Path]:
    """
    Try to find the matching PDF in Lit Processor uploads.
    Uses author/year matching for best results.
    """
    if not LIT_PROCESSOR_UPLOADS.exists():
        return None

    # Try matching by ID prefix first
    if file_id:
        matches = list(LIT_PROCESSOR_UPLOADS.glob(f"{file_id}_*.pdf"))
        if matches:
            return matches[0]

    # Match by author and year (more reliable)
    if metadata:
        author = metadata.get("author", "").lower()
        year = metadata.get("year")

        # Normalize author: "Ba et al." -> ["ba"]
        author_parts = [p for p in re.split(r'[\s&,]+', author) if len(p) > 1 and p not in ["et", "al", "and"]]

        for pdf in LIT_PROCESSOR_UPLOADS.glob("*.pdf"):
            pdf_name = pdf.stem.lower()

            # Check if year matches
            if year and str(year) in pdf_name:
                # Check if any author part matches
                if any(part in pdf_name for part in author_parts):
                    return pdf

    # Fallback: match by significant words in title
    if metadata and metadata.get("title"):
        title_words = [w.lower() for w in metadata["title"].split() if len(w) > 4]
        for pdf in LIT_PROCESSOR_UPLOADS.glob("*.pdf"):
            pdf_name = pdf.stem.lower()
            # Need at least 2 significant title words to match
            matches = sum(1 for word in title_words if word in pdf_name)
            if matches >= 2:
                return pdf

    return None


def _parse_sections(content: str, doc_id: str) -> list:
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


# ============================================================
# Section Editor Endpoints
# ============================================================

@router.get("/{document_id}/raw")
async def get_raw_text(document_id: str):
    """
    Get the raw extracted text file content for editing.

    Returns:
        content: The raw text content
        extracted_path: Path to the file
        original_path: Path to the original PDF (for reference)
        sections: Current parsed sections
    """
    db = await get_db()

    cursor = await db.execute(
        "SELECT id, title, extracted_path, original_path FROM documents WHERE id = ?",
        [document_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_id, title, extracted_path, original_path = row

    if not extracted_path:
        raise HTTPException(status_code=404, detail="No extracted text file for this document")

    extracted_file = Path(extracted_path)
    if not extracted_file.exists():
        raise HTTPException(status_code=404, detail=f"Extracted file not found: {extracted_path}")

    # Read the raw content
    content = extracted_file.read_text(encoding="utf-8")

    # Get current sections
    cursor = await db.execute(
        "SELECT id, title, level, start_offset, end_offset, order_index FROM sections WHERE document_id = ? ORDER BY order_index",
        [document_id]
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
        "document_id": document_id,
        "title": title,
        "content": content,
        "extracted_path": extracted_path,
        "original_path": original_path,
        "sections": sections,
        "char_count": len(content)
    }


from pydantic import BaseModel

class RawTextUpdate(BaseModel):
    content: str


@router.put("/{document_id}/raw")
async def update_raw_text(document_id: str, update: RawTextUpdate):
    """
    Save edited raw text and re-parse sections.

    This will:
    1. Write the new content to the extracted.txt file
    2. Re-parse sections from the updated content
    3. Update the sections table
    4. Update FTS index

    Note: Highlights may need adjustment if offsets changed significantly.
    """
    db = await get_db()

    # Get document info
    cursor = await db.execute(
        "SELECT id, title, author, extracted_path FROM documents WHERE id = ?",
        [document_id]
    )
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_id, title, author, extracted_path = row

    if not extracted_path:
        raise HTTPException(status_code=400, detail="No extracted text file for this document")

    extracted_file = Path(extracted_path)

    # Write the new content
    extracted_file.write_text(update.content, encoding="utf-8")

    # Re-parse sections
    new_sections = _parse_sections(update.content, doc_id)

    # Delete old sections
    await db.execute("DELETE FROM sections WHERE document_id = ?", [doc_id])

    # Insert new sections
    for i, section in enumerate(new_sections):
        section_id = f"{doc_id}-s{i}"
        await db.execute("""
            INSERT INTO sections (id, document_id, title, level, start_offset,
                                  end_offset, order_index, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            section_id, doc_id, section["title"], section["level"],
            section["start_offset"], section["end_offset"], i, None
        ])

    # Update FTS
    await db.execute("""
        DELETE FROM documents_fts WHERE rowid = (SELECT rowid FROM documents WHERE id = ?)
    """, [doc_id])
    await db.execute("""
        INSERT INTO documents_fts (rowid, title, author, full_text)
        SELECT rowid, title, author, ? FROM documents WHERE id = ?
    """, [update.content, doc_id])

    # Update document timestamp
    now = datetime.now().isoformat()
    await db.execute("UPDATE documents SET updated_at = ? WHERE id = ?", [now, doc_id])

    await db.commit()

    return {
        "document_id": doc_id,
        "sections_count": len(new_sections),
        "sections": new_sections,
        "char_count": len(update.content),
        "updated_at": now
    }


@router.post("/{document_id}/preview-sections")
async def preview_sections(document_id: str, update: RawTextUpdate):
    """
    Preview what sections would be parsed from edited content WITHOUT saving.
    Useful for live preview in the editor.
    """
    # Just parse and return - don't save
    sections = _parse_sections(update.content, document_id)

    return {
        "sections_count": len(sections),
        "sections": sections,
        "char_count": len(update.content)
    }
