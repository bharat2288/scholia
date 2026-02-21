"""
PDF Processor Router
====================
API endpoints for PDF processing workflow.

Ported from Lit Processor with Scholia storage integration.
Jobs are persisted to SQLite so they survive server restarts.

Endpoints:
- POST /processor/assess       - Upload PDF, get tier recommendation
- POST /processor/process      - Start processing with selected tier
- GET  /processor/status/{id}  - Poll processing status
- POST /processor/cancel/{id}  - Cancel processing
- GET  /processor/queue        - Get all job statuses
- GET  /processor/resumable    - Get jobs that can be resumed
- POST /processor/resume/{id}  - Resume an interrupted job
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pathlib import Path
import shutil
import uuid
import threading
import queue
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass
import re
from datetime import datetime
import asyncio

from services.lit_engine.assessor import assess_pdf
from database import get_db

router = APIRouter()

# Paths - use Scholia's data directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"

# Support both new (sources/documents) and legacy (documents) locations
SOURCES_DIR = DATA_DIR / "sources"
DOCUMENTS_DIR = SOURCES_DIR / "documents"
LEGACY_DOCUMENTS_DIR = DATA_DIR / "documents"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _get_documents_dir() -> Path:
    """Get the documents directory, preferring new location but falling back to legacy."""
    if DOCUMENTS_DIR.exists():
        return DOCUMENTS_DIR
    if LEGACY_DOCUMENTS_DIR.exists():
        return LEGACY_DOCUMENTS_DIR
    # Default to new location (will be created)
    return DOCUMENTS_DIR

# In-memory progress store (synced with DB)
# Key: temp_id, Value: {current_page, total_pages, status, stage, error, queue_position}
progress_store: Dict[str, Dict[str, Any]] = {}

# Unified processing queue - all jobs (marker + dots-ocr) run sequentially
# Both use GPU, so we process one at a time to avoid memory conflicts
@dataclass
class ProcessingJob:
    temp_id: str
    tier: str
    pdf_path: Path

processing_queue: queue.Queue[ProcessingJob] = queue.Queue()
processing_worker_thread: Optional[threading.Thread] = None
processing_worker_running = False


# =============================================================================
# Database Helpers
# =============================================================================

def _sync_save_job(temp_id: str, data: dict):
    """Synchronously save job to database (for use in worker thread)."""
    import sqlite3
    db_path = DATA_DIR / "library.db"

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO processing_jobs
            (temp_id, filename, pdf_path, tier, status, stage, current_page, total_pages,
             percent, queue_position, error, output_path, folder_name, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            temp_id,
            data.get("filename", ""),
            data.get("pdf_path", ""),
            data.get("tier", ""),
            data.get("status", ""),
            data.get("stage", ""),
            data.get("current_page", 0),
            data.get("total_pages", 0),
            data.get("percent", 0),
            data.get("queue_position"),
            data.get("error"),
            data.get("output_path"),
            data.get("folder_name"),
        ))
        conn.commit()
    finally:
        conn.close()


def _sync_load_all_jobs() -> Dict[str, Dict[str, Any]]:
    """Synchronously load all active jobs from database."""
    import sqlite3
    db_path = DATA_DIR / "library.db"

    if not db_path.exists():
        return {}

    jobs = {}
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM processing_jobs
            WHERE status IN ('queued', 'processing')
        """)
        for row in cursor.fetchall():
            jobs[row['temp_id']] = dict(row)
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        pass
    finally:
        conn.close()

    return jobs


def _sync_delete_job(temp_id: str):
    """Synchronously delete a completed job from database."""
    import sqlite3
    db_path = DATA_DIR / "library.db"

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM processing_jobs WHERE temp_id = ?", (temp_id,))
        conn.commit()
    finally:
        conn.close()


def _compute_pdf_hash(pdf_path: Path) -> str:
    """Compute SHA256 hash of a PDF file for duplicate detection."""
    import hashlib
    if not pdf_path.exists():
        return None
    sha256 = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        # Read in chunks to handle large files
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _sync_import_source(folder_name: str, tier: str):
    """
    Synchronously import a processed document to the library database.
    Called after processing completes to make the document appear in Library.

    Uses UPSERT logic: if source with same original_path exists, update it.
    This allows reprocessing to update the database entry rather than create duplicates.

    Tier priority: dots-ocr > marker (dots-ocr is higher quality)
    - If existing source uses dots-ocr and we just processed marker, DON'T downgrade
    - If existing source uses marker and we just processed dots-ocr, DO upgrade
    """
    import sqlite3

    # Tier priority: higher number = higher priority
    TIER_PRIORITY = {
        "marker": 1,
        "dots-ocr": 2,
    }

    db_path = DATA_DIR / "library.db"
    documents_dir = _get_documents_dir()
    doc_folder = documents_dir / folder_name
    method_folder = doc_folder / f"{folder_name}--{tier}"

    # Find the extracted text file
    txt_path = method_folder / f"{folder_name}--{tier}--extracted.txt"
    if not txt_path.exists():
        print(f"Warning: Could not find extracted text at {txt_path}")
        return None

    # Find PDF
    pdf_path = doc_folder / f"{folder_name}.pdf"

    # Parse metadata from folder name (Author_Year_Title format)
    parts = folder_name.split("_")
    author = None
    year = None
    title = folder_name

    # Find year (4 digits)
    year_idx = None
    for i, part in enumerate(parts):
        if re.match(r"^\d{4}$", part):
            year_idx = i
            year = int(part)
            break

    if year_idx is not None:
        # Author is everything before year
        author = " ".join(parts[:year_idx])
        # Title is everything after year
        title = " ".join(parts[year_idx + 1:])

    # Read content for sections parsing and FTS
    content = txt_path.read_text(encoding="utf-8")
    now = datetime.now().isoformat()

    # Compute PDF hash for duplicate detection
    pdf_hash = _compute_pdf_hash(pdf_path) if pdf_path.exists() else None

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()

        # Build metadata JSON for document-specific fields
        pdf_path_str = str(pdf_path) if pdf_path.exists() else None
        metadata = {
            "original_path": pdf_path_str,
            "extraction_method": tier,
            "pdf_hash": pdf_hash,
        }

        # Check if source already exists by original_path in metadata
        # This is stable across extraction methods (marker vs dots-ocr)
        cursor.execute("""
            SELECT id, content_path, metadata FROM sources
            WHERE json_extract(metadata, '$.original_path') = ?
        """, (pdf_path_str,))
        existing = cursor.fetchone()

        if existing:
            source_id = existing[0]
            existing_content_path = existing[1] or ""
            existing_metadata = json.loads(existing[2]) if existing[2] else {}

            # Determine existing tier from extraction_method in metadata
            existing_tier = existing_metadata.get("extraction_method")

            # Check if we should update content_path based on tier priority
            new_priority = TIER_PRIORITY.get(tier, 0)
            existing_priority = TIER_PRIORITY.get(existing_tier, 0)

            if new_priority >= existing_priority:
                # Upgrade or same tier (reprocess) - update content_path
                # Merge metadata (keep existing fields, update extraction-related ones)
                merged_metadata = {**existing_metadata, **metadata}

                cursor.execute("""
                    UPDATE sources
                    SET title = ?, author_display = ?, year = ?, content_path = ?,
                        metadata = ?, updated_at = ?
                    WHERE id = ?
                """, [
                    title, author, year, str(txt_path),
                    json.dumps(merged_metadata), now, source_id
                ])

                # Delete old sections and FTS entry for re-indexing
                cursor.execute("DELETE FROM sections WHERE source_id = ?", (source_id,))
                cursor.execute("DELETE FROM sources_fts WHERE rowid = (SELECT rowid FROM sources WHERE id = ?)", (source_id,))

                print(f"Updated source to {tier}: {folder_name} (id: {source_id})")
            else:
                # Lower priority tier - don't downgrade content_path, but still update metadata
                cursor.execute("""
                    UPDATE sources
                    SET title = ?, author_display = ?, year = ?, updated_at = ?
                    WHERE id = ?
                """, [
                    title, author, year, now, source_id
                ])
                print(f"Kept existing {existing_tier} extraction, updated metadata only: {folder_name} (id: {source_id})")
                # Don't re-index sections/FTS since we're keeping the existing extraction
                conn.commit()
                return source_id
        else:
            # INSERT new source
            source_id = str(uuid.uuid4())[:8]
            cursor.execute("""
                INSERT INTO sources (id, title, source_type, author_display, year,
                                     content_path, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                source_id, title, "document", author, year,
                str(txt_path), json.dumps(metadata), now, now
            ])
            print(f"Auto-imported source: {folder_name} (id: {source_id})")

        # Parse and insert sections (simple version - just find [SECTION] markers)
        sections = []
        for match in re.finditer(r'\[SECTION\]\s*(#{1,6})\s*(.+)', content):
            level = len(match.group(1))
            section_title = match.group(2).strip()
            sections.append({
                "title": section_title,
                "level": level,
                "start_offset": match.start(),
                "end_offset": match.end()
            })

        for i, section in enumerate(sections):
            section_id = f"{source_id}-s{i}"
            cursor.execute("""
                INSERT INTO sections (id, source_id, title, level, start_offset,
                                      end_offset, order_index, parent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                section_id, source_id, section["title"], section["level"],
                section["start_offset"], section["end_offset"], i, None
            ])

        # Index in FTS
        cursor.execute("""
            INSERT INTO sources_fts (rowid, title, author_display)
            SELECT rowid, title, author_display FROM sources WHERE id = ?
        """, [source_id])

        conn.commit()
        return source_id

    except Exception as e:
        print(f"Error auto-importing source: {e}")
        return None
    finally:
        conn.close()


# =============================================================================
# Job State Management (for dots-ocr resume)
# =============================================================================

def get_job_state_path(save_dir: Path) -> Path:
    """Get path to job_state.json for a given output directory."""
    return save_dir / "job_state.json"


def load_job_state(save_dir: Path) -> Optional[Dict[str, Any]]:
    """Load job state from disk if it exists."""
    state_path = get_job_state_path(save_dir)
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load job state: {e}")
    return None


def save_job_state(save_dir: Path, state: Dict[str, Any]):
    """Save job state to disk."""
    state_path = get_job_state_path(save_dir)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        print(f"Warning: Could not save job state: {e}")


def delete_job_state(save_dir: Path):
    """Delete job state file after successful completion."""
    state_path = get_job_state_path(save_dir)
    if state_path.exists():
        try:
            state_path.unlink()
            print(f"Cleaned up job state: {state_path}")
        except IOError as e:
            print(f"Warning: Could not delete job state: {e}")


# =============================================================================
# Processing Worker (unified queue for marker + dots-ocr)
# =============================================================================

def get_queue_position(temp_id: str) -> int:
    """Get position in processing queue (0 = currently processing, 1+ = waiting)."""
    if temp_id in progress_store and progress_store[temp_id].get("status") == "processing":
        return 0

    position = 1
    for job in list(processing_queue.queue):
        if job.temp_id == temp_id:
            return position
        position += 1
    return -1


def update_queue_positions():
    """Update queue_position for all queued jobs (skips cancelled)."""
    position = 1
    for job in list(processing_queue.queue):
        if job.temp_id in progress_store:
            # Skip cancelled jobs - they're still in queue but will be skipped by worker
            if progress_store[job.temp_id].get("status") == "cancelled":
                continue
            progress_store[job.temp_id]["queue_position"] = position
            # Sync to DB
            _sync_save_job(job.temp_id, progress_store[job.temp_id])
            position += 1


def processing_worker():
    """Worker thread that processes all PDF jobs one at a time (both marker and dots-ocr use GPU)."""
    global processing_worker_running

    while processing_worker_running:
        try:
            job = processing_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        try:
            update_queue_positions()

            if job.temp_id in progress_store and progress_store[job.temp_id].get("status") == "cancelled":
                print(f"Skipping cancelled job: {job.temp_id}")
            else:
                process_pdf_sync(job.temp_id, job.tier, job.pdf_path)
        except Exception as e:
            print(f"GPU worker error processing {job.temp_id}: {e}")
            if job.temp_id in progress_store:
                progress_store[job.temp_id] = {
                    **progress_store[job.temp_id],
                    "status": "error",
                    "stage": "failed",
                    "percent": 0,
                    "error": str(e),
                    "queue_position": None
                }
                _sync_save_job(job.temp_id, progress_store[job.temp_id])
        finally:
            processing_queue.task_done()


def start_processing_worker():
    """Start the processing worker thread and restore any interrupted jobs."""
    global processing_worker_thread, processing_worker_running, progress_store

    if processing_worker_thread is None or not processing_worker_thread.is_alive():
        # Restore jobs from database
        saved_jobs = _sync_load_all_jobs()
        for temp_id, job_data in saved_jobs.items():
            progress_store[temp_id] = {
                "status": job_data.get("status", "queued"),
                "stage": job_data.get("stage", "waiting"),
                "current_page": job_data.get("current_page", 0),
                "total_pages": job_data.get("total_pages", 0),
                "percent": job_data.get("percent", 0),
                "error": job_data.get("error"),
                "queue_position": job_data.get("queue_position"),
                "filename": job_data.get("filename"),
                "pdf_path": job_data.get("pdf_path"),
                "tier": job_data.get("tier"),
            }

            # Re-queue jobs that were processing or queued
            if job_data.get("status") in ["queued", "processing"]:
                pdf_path = Path(job_data.get("pdf_path", ""))
                if pdf_path.exists():
                    processing_queue.put(ProcessingJob(
                        temp_id=temp_id,
                        tier=job_data.get("tier", "marker"),
                        pdf_path=pdf_path
                    ))
                    print(f"Restored job from DB: {temp_id}")

        processing_worker_running = True
        processing_worker_thread = threading.Thread(target=processing_worker, daemon=True)
        processing_worker_thread.start()
        print("Processing worker started")


def stop_processing_worker():
    """Stop the processing worker thread."""
    global processing_worker_running
    processing_worker_running = False
    if processing_worker_thread:
        processing_worker_thread.join(timeout=5.0)
    print("Processing worker stopped")


# =============================================================================
# Processing Logic
# =============================================================================

def process_pdf_sync(temp_id: str, tier: str, pdf_path: Path):
    """Process PDF synchronously with progress tracking."""
    try:
        # Get existing job data
        job_data = progress_store.get(temp_id, {})

        progress_store[temp_id] = {
            **job_data,
            "status": "processing",
            "stage": "loading",
            "current_page": 0,
            "total_pages": 0,
            "percent": 0,
            "error": None,
            "queue_position": 0
        }
        _sync_save_job(temp_id, progress_store[temp_id])

        # Route to appropriate pipeline
        if tier == "quick":
            from services.lit_engine.quick_extractor import extract_with_quick
            progress_store[temp_id]["stage"] = "extracting"
            _sync_save_job(temp_id, progress_store[temp_id])
            content = extract_with_quick(str(pdf_path), temp_id, progress_store)

        elif tier == "marker":
            from services.lit_engine.marker_extractor import (
                extract_with_marker,
                generate_document_folder_name
            )
            progress_store[temp_id]["stage"] = "extracting"
            _sync_save_job(temp_id, progress_store[temp_id])
            content = extract_with_marker(str(pdf_path), temp_id, progress_store)

        elif tier == "dots-ocr":
            from services.lit_engine.dots_ocr_extractor import (
                extract_with_dots_ocr,
                generate_document_folder_name as dots_generate_folder_name,
                is_available as dots_available
            )

            if not dots_available():
                raise RuntimeError(
                    "dots-ocr is not available. Check that dots.ocr is installed and model weights are present."
                )

            progress_store[temp_id]["stage"] = "loading model"
            _sync_save_job(temp_id, progress_store[temp_id])

            # Generate folder name early so we can write intermediate files
            # directly to the final method folder (keeps page .md/.jpg/.json files)
            folder_name = _predict_folder_name_from_filename(pdf_path.name)
            documents_dir = _get_documents_dir()
            doc_folder = documents_dir / folder_name
            method_folder = doc_folder / f"{folder_name}--{tier}"
            doc_folder.mkdir(parents=True, exist_ok=True)
            method_folder.mkdir(parents=True, exist_ok=True)

            # Copy PDF to document folder upfront
            pdf_dest = doc_folder / f"{folder_name}.pdf"
            if not pdf_dest.exists():
                shutil.copy2(pdf_path, pdf_dest)

            content = extract_with_dots_ocr(
                str(pdf_path),
                temp_id,
                progress_store,
                output_dir=method_folder,
                save_name=folder_name
            )

        else:
            raise ValueError(f"Unknown tier: {tier}")

        # Update progress: formatting
        progress_store[temp_id]["stage"] = "formatting"
        progress_store[temp_id]["percent"] = 95
        _sync_save_job(temp_id, progress_store[temp_id])

        # For dots-ocr, folder_name/doc_folder/method_folder were created upfront
        # so intermediate files land in the final location. Other tiers create them here.
        if tier != "dots-ocr":
            from services.lit_engine.marker_extractor import generate_document_folder_name
            folder_name = generate_document_folder_name(str(pdf_path), content)

            documents_dir = _get_documents_dir()
            doc_folder = documents_dir / folder_name
            method_folder = doc_folder / f"{folder_name}--{tier}"
            doc_folder.mkdir(parents=True, exist_ok=True)
            method_folder.mkdir(parents=True, exist_ok=True)

            # Copy PDF to document folder
            pdf_dest = doc_folder / f"{folder_name}.pdf"
            if not pdf_dest.exists():
                shutil.copy2(pdf_path, pdf_dest)
        else:
            # dots-ocr: rebuild extracted text from JSON files (more precise than
            # the markdown-based dots_ocr_to_scholia used during extraction).
            # Uses structured category data for accurate [SECTION]/[FIGURE]/etc markers.
            from services.rebuild_extracted import rebuild_extracted
            content = rebuild_extracted(doc_folder, method='dots-ocr')

        # Write extracted text
        output_path = method_folder / f"{folder_name}--{tier}--extracted.txt"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Pre-crop figures from PDF for faster serving (dots-ocr only —
        # page JSONs contain bbox coordinates for Picture elements)
        if tier == "dots-ocr":
            from services.rebuild_extracted import crop_figures
            try:
                fig_count = crop_figures(doc_folder, method='dots-ocr')
                print(f"[processor] Pre-cropped {fig_count} figures")
            except Exception as e:
                print(f"[processor] Warning: figure cropping failed: {e}")

        # Update progress: complete
        progress_store[temp_id] = {
            **progress_store[temp_id],
            "status": "complete",
            "stage": "done",
            "current_page": progress_store[temp_id].get("total_pages", 0),
            "total_pages": progress_store[temp_id].get("total_pages", 0),
            "percent": 100,
            "error": None,
            "output_path": str(output_path),
            "output_filename": output_path.name,
            "folder_name": folder_name,
            "queue_position": None
        }

        # Delete from DB (job complete, no need to persist)
        _sync_delete_job(temp_id)

        # Auto-import to library database so it appears in Library view
        _sync_import_source(folder_name, tier)

        # Clean up job_state.json if it exists (for dots-ocr)
        delete_job_state(method_folder)

        # Clean up uploaded file
        if pdf_path.exists() and str(UPLOAD_DIR) in str(pdf_path):
            pdf_path.unlink()
            print(f"Cleaned up upload: {pdf_path}")

        # Note: dots-ocr intermediate files (page .md/.jpg/.json) are kept
        # in the method folder — no temp directory cleanup needed

    except Exception as e:
        import traceback
        traceback.print_exc()
        progress_store[temp_id] = {
            **progress_store.get(temp_id, {}),
            "status": "error",
            "stage": "failed",
            "percent": 0,
            "error": str(e),
            "queue_position": None
        }
        _sync_save_job(temp_id, progress_store[temp_id])


# =============================================================================
# Existing Extraction Detection
# =============================================================================

def _predict_folder_name_from_filename(filename: str) -> str:
    """
    Predict the document folder name from just the PDF filename.
    This is used during assessment to check for existing extractions.

    Uses the same logic as generate_document_folder_name but without content.
    """
    from unidecode import unidecode

    pdf_name = Path(filename).stem

    # Strip temp_id prefix if present (format: "xxxxxxxx_originalname")
    if re.match(r'^[a-f0-9]{8}_', pdf_name):
        pdf_name = pdf_name[9:]

    # Try to parse from common filename patterns
    patterns = [
        r'^(.+?)\s*[-_]\s*(\d{4})\s*[-_]\s*(.+)$',  # Author - 2023 - Title
        r'^(.+?)\s*\((\d{4})\)\s*(.+)$',             # Author (2023) Title
        r'^(\d{4})\s*[-_]\s*(.+?)\s*[-_]\s*(.+)$',  # 2023 - Author - Title
        r'^(.+?)_(\d{4})_(.+)$',                     # Author_2023_Title
    ]

    author = "Unknown"
    year = "XXXX"
    title = pdf_name

    for pattern in patterns:
        match = re.match(pattern, pdf_name)
        if match:
            groups = match.groups()
            if len(groups) == 3:
                if groups[1].isdigit() and len(groups[1]) == 4:
                    author = groups[0]
                    year = groups[1]
                    title = groups[2]
                elif groups[0].isdigit() and len(groups[0]) == 4:
                    year = groups[0]
                    author = groups[1]
                    title = groups[2]
                break

    # Clean up for filename
    def clean_for_filename(text):
        text = unidecode(text)
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '_', text)
        text = text.strip('_')
        text = '_'.join(word.capitalize() for word in text.split('_'))
        return text

    author = clean_for_filename(author)
    title = clean_for_filename(title)

    # Truncate title if too long
    if len(title) > 50:
        title = title[:50].rsplit('_', 1)[0]

    return f"{author}_{year}_{title}"


def _parse_author_year_from_filename(filename: str) -> tuple:
    """
    Parse author and year from a PDF filename for fuzzy matching.
    Returns (author_words, year) where author_words is a set of lowercase words.
    """
    from unidecode import unidecode

    pdf_name = Path(filename).stem

    # Strip temp_id prefix if present
    if re.match(r'^[a-f0-9]{8}_', pdf_name):
        pdf_name = pdf_name[9:]

    # Normalize
    pdf_name = unidecode(pdf_name)

    # Try to extract year (4-digit number between 1900-2099)
    year_match = re.search(r'\b(19|20)\d{2}\b', pdf_name)
    year = int(year_match.group()) if year_match else None

    # Extract author part (everything before the year, or first part before separator)
    author_text = ""
    if year_match:
        author_text = pdf_name[:year_match.start()]
    else:
        # Try to get first part before common separators
        parts = re.split(r'[-_]', pdf_name)
        if parts:
            author_text = parts[0]

    # Clean and extract author words
    author_text = re.sub(r'[^\w\s]', ' ', author_text.lower())
    author_words = set(w for w in author_text.split() if len(w) > 2 and w not in {'and', 'the', 'for', 'et', 'al'})

    return author_words, year


def _check_existing_extractions(filename: str, pdf_path: str = None) -> dict:
    """
    Check if extractions already exist for this PDF using multiple strategies:
    1. Exact hash match (if pdf_path provided)
    2. Folder name prediction match
    3. Fuzzy author + year database match

    Returns:
        {
            "folder_name": str or None - predicted folder name,
            "folder_exists": bool - if predicted folder exists,
            "existing_methods": ["marker", "dots-ocr"] - list of existing extractions,
            "source_id": str or None - ID of existing source in database,
            "annotation_count": int - number of highlights/notes on this source,
            "match_type": "exact" | "folder" | "fuzzy" | None - how the match was found,
            "matched_title": str or None - title of matched source (for fuzzy matches)
        }
    """
    import sqlite3

    result = {
        "folder_name": None,
        "folder_exists": False,
        "existing_methods": [],
        "source_id": None,
        "annotation_count": 0,
        "match_type": None,
        "matched_title": None
    }

    db_path = DATA_DIR / "library.db"
    if not db_path.exists():
        return result

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    documents_dir = _get_documents_dir()

    try:
        # Strategy 1: Exact hash match (most reliable)
        if pdf_path:
            pdf_hash = _compute_pdf_hash(Path(pdf_path))
            if pdf_hash:
                cursor.execute("""
                    SELECT id, title, author_display, year, metadata, content_path
                    FROM sources WHERE json_extract(metadata, '$.pdf_hash') = ?
                """, (pdf_hash,))
                row = cursor.fetchone()

                if row:
                    result["source_id"] = row["id"]
                    result["matched_title"] = row["title"]
                    result["match_type"] = "exact"

                    # Get folder info from original_path in metadata
                    metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                    original_path = metadata.get("original_path")
                    if original_path:
                        orig_path = Path(original_path)
                        if orig_path.parent.exists():
                            result["folder_name"] = orig_path.parent.name
                            result["folder_exists"] = True

                            # Check existing methods
                            folder = orig_path.parent
                            for method in ["marker", "dots-ocr"]:
                                method_file = folder / f"{folder.name}--{method}" / f"{folder.name}--{method}--extracted.txt"
                                if method_file.exists():
                                    result["existing_methods"].append(method)

                    # Count annotations
                    cursor.execute("""
                        SELECT COUNT(*) FROM gluons
                        WHERE source_id = ? AND type IN ('highlight', 'note')
                    """, (row["id"],))
                    count_row = cursor.fetchone()
                    result["annotation_count"] = count_row[0] if count_row else 0

                    conn.close()
                    return result

        # Strategy 2: Folder name prediction match (current method)
        folder_name = _predict_folder_name_from_filename(filename)
        result["folder_name"] = folder_name
        doc_folder = documents_dir / folder_name

        if doc_folder.exists():
            result["folder_exists"] = True
            result["match_type"] = "folder"

            # Check for marker extraction
            marker_file = doc_folder / f"{folder_name}--marker" / f"{folder_name}--marker--extracted.txt"
            if marker_file.exists():
                result["existing_methods"].append("marker")

            # Check for dots-ocr extraction
            dots_file = doc_folder / f"{folder_name}--dots-ocr" / f"{folder_name}--dots-ocr--extracted.txt"
            if dots_file.exists():
                result["existing_methods"].append("dots-ocr")

            # Find source in database
            pdf_in_folder = doc_folder / f"{folder_name}.pdf"
            if pdf_in_folder.exists():
                cursor.execute("""
                    SELECT id, title FROM sources
                    WHERE json_extract(metadata, '$.original_path') = ?
                """, (str(pdf_in_folder),))
                row = cursor.fetchone()
                if row:
                    result["source_id"] = row["id"]
                    result["matched_title"] = row["title"]

                    # Count annotations
                    cursor.execute("""
                        SELECT COUNT(*) FROM gluons
                        WHERE source_id = ? AND type IN ('highlight', 'note')
                    """, (row["id"],))
                    count_row = cursor.fetchone()
                    result["annotation_count"] = count_row[0] if count_row else 0

            conn.close()
            return result

        # Strategy 3: Fuzzy author + year match
        author_words, year = _parse_author_year_from_filename(filename)

        if year and author_words:
            # Query sources with matching year
            cursor.execute("""
                SELECT id, title, author_display, metadata, content_path
                FROM sources WHERE year = ?
            """, (year,))
            candidates = cursor.fetchall()

            for source in candidates:
                if not source["author_display"]:
                    continue

                # Check if any author words match
                source_author = source["author_display"].lower()
                source_author_words = set(re.sub(r'[^\w\s]', ' ', source_author).split())

                # Match if at least one significant author word matches
                if author_words & source_author_words:
                    result["source_id"] = source["id"]
                    result["matched_title"] = source["title"]
                    result["match_type"] = "fuzzy"

                    # Get folder info from metadata
                    metadata = json.loads(source["metadata"]) if source["metadata"] else {}
                    original_path = metadata.get("original_path")
                    if original_path:
                        orig_path = Path(original_path)
                        if orig_path.parent.exists():
                            result["folder_name"] = orig_path.parent.name
                            result["folder_exists"] = True

                            # Check existing methods
                            folder = orig_path.parent
                            for method in ["marker", "dots-ocr"]:
                                method_file = folder / f"{folder.name}--{method}" / f"{folder.name}--{method}--extracted.txt"
                                if method_file.exists():
                                    result["existing_methods"].append(method)

                    # Count annotations
                    cursor.execute("""
                        SELECT COUNT(*) FROM gluons
                        WHERE source_id = ? AND type IN ('highlight', 'note')
                    """, (source["id"],))
                    count_row = cursor.fetchone()
                    result["annotation_count"] = count_row[0] if count_row else 0

                    break  # Take first match

    except Exception as e:
        print(f"Warning: Error checking existing extractions: {e}")
    finally:
        conn.close()

    return result


# =============================================================================
# API Endpoints
# =============================================================================

def _sync_assess_pdf(temp_path: Path, filename: str) -> dict:
    """
    Synchronous helper for PDF assessment.
    Runs file I/O, assessment, and duplicate checking in a thread pool.
    """
    result = assess_pdf(str(temp_path))
    result["existing_extractions"] = _check_existing_extractions(filename, str(temp_path))
    return result


@router.post("/assess")
async def assess(file: UploadFile = File(...)):
    """
    Upload and assess a PDF to recommend extraction tier.

    Returns:
        recommendation: "marker" | "dots-ocr"
        page_count: int
        time_estimates: dict with estimates per tier
        signals: dict with detection signals
        existing_extractions: dict with info about existing extractions
    """
    # Save uploaded file temporarily
    temp_id = str(uuid.uuid4())[:8]
    temp_path = UPLOAD_DIR / f"{temp_id}_{file.filename}"

    try:
        # Read file content (this is already async-friendly via SpooledTemporaryFile)
        contents = await file.read()

        # Write to disk in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: temp_path.write_bytes(contents)
        )

        # Run assessment in thread pool (includes file I/O and DB queries)
        result = await loop.run_in_executor(
            None,
            _sync_assess_pdf,
            temp_path,
            file.filename
        )

        result["temp_id"] = temp_id
        result["filename"] = file.filename

        return result

    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process")
async def process(temp_id: str, tier: str, background_tasks: BackgroundTasks):
    """
    Process a previously uploaded PDF with the specified tier.

    Args:
        temp_id: The temp_id returned from /assess
        tier: "marker" | "dots-ocr"

    Returns:
        status: "started" | "queued"
        queue_position: int (only for dots-ocr)
    """
    # Ensure processing worker is running
    start_processing_worker()

    # Find the uploaded file
    matches = list(UPLOAD_DIR.glob(f"{temp_id}_*"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"No file found for temp_id: {temp_id}")

    pdf_path = matches[0]
    filename = pdf_path.name[9:]  # Remove temp_id prefix

    if tier not in ["quick", "marker", "dots-ocr"]:
        raise HTTPException(status_code=400, detail=f"Unknown tier: {tier}")

    # Create initial job state
    job_data = {
        "status": "queued",
        "stage": "waiting",
        "current_page": 0,
        "total_pages": 0,
        "percent": 0,
        "error": None,
        "queue_position": 1,
        "filename": filename,
        "pdf_path": str(pdf_path),
        "tier": tier,
    }

    # All jobs go through unified queue (both marker and dots-ocr use GPU)
    queue_position = processing_queue.qsize() + 1

    # Check if something is currently processing
    currently_processing = any(
        p.get("status") == "processing" and p.get("queue_position") == 0
        for p in progress_store.values()
    )
    if not currently_processing:
        queue_position = 1

    job_data["queue_position"] = queue_position
    progress_store[temp_id] = job_data
    _sync_save_job(temp_id, job_data)

    processing_queue.put(ProcessingJob(temp_id=temp_id, tier=tier, pdf_path=pdf_path))

    return {"status": "queued", "temp_id": temp_id, "queue_position": queue_position}


@router.get("/status/{temp_id}")
async def get_status(temp_id: str):
    """
    Get processing status for a PDF.

    Returns:
        status: "processing" | "complete" | "error" | "cancelled" | "queued"
        stage: "loading" | "extracting" | "formatting" | "done" | "failed" | "waiting"
        current_page: int
        total_pages: int
        percent: int (0-100)
        error: str or None
        output_filename: str (only when complete)
        folder_name: str (only when complete)
        queue_position: int or None
    """
    if temp_id not in progress_store:
        raise HTTPException(status_code=404, detail=f"No status found for temp_id: {temp_id}")

    return progress_store[temp_id]


@router.get("/queue")
async def get_all_status():
    """
    Get status of all tracked jobs.

    Returns dict mapping temp_id to status info.
    """
    return progress_store


@router.post("/cancel/{temp_id}")
async def cancel_processing(temp_id: str):
    """
    Cancel an in-progress or queued PDF processing job.
    Also recalculates queue positions for remaining jobs.
    """
    if temp_id not in progress_store:
        raise HTTPException(status_code=404, detail=f"No status found for temp_id: {temp_id}")

    current_status = progress_store[temp_id]["status"]

    if current_status in ["processing", "queued"]:
        progress_store[temp_id]["status"] = "cancelled"
        progress_store[temp_id]["stage"] = "cancelled"
        progress_store[temp_id]["queue_position"] = None
        _sync_save_job(temp_id, progress_store[temp_id])

        # Recalculate queue positions for remaining jobs
        # The worker will skip cancelled jobs, but we need to update positions now
        update_queue_positions()

        return {"status": "cancelled", "temp_id": temp_id}
    else:
        return {"status": current_status, "message": "Not processing or queued"}


@router.get("/resumable")
async def list_resumable_jobs():
    """
    List jobs that can be resumed (have partial progress in uploads folder).

    Returns list of resumable jobs with their progress.
    """
    resumable = []

    # Find all PDF files in uploads that have partial processing
    for pdf_path in UPLOAD_DIR.glob("*.pdf"):
        filename = pdf_path.name
        temp_id = filename.split("_")[0] if "_" in filename else filename[:8]

        # Check if there's a job_state.json in any potential output location
        # For dots-ocr, state would be saved per-job

        # For now, just list PDFs that aren't currently being processed
        if temp_id not in progress_store or progress_store[temp_id].get("status") in ["error", "cancelled"]:
            import fitz
            try:
                doc = fitz.open(str(pdf_path))
                page_count = len(doc)
                doc.close()

                resumable.append({
                    "temp_id": temp_id,
                    "filename": filename,
                    "total_pages": page_count,
                    "completed_pages": 0,
                    "remaining_pages": page_count,
                    "percent_complete": 0
                })
            except Exception:
                pass

    return {"resumable": resumable}


@router.post("/resume/{temp_id}")
async def resume_job(temp_id: str, tier: str = "marker", background_tasks: BackgroundTasks = None):
    """
    Resume a previously interrupted job.
    """
    # Find the PDF file
    matches = list(UPLOAD_DIR.glob(f"{temp_id}_*.pdf"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"No PDF found for temp_id: {temp_id}")

    pdf_path = matches[0]
    filename = pdf_path.name[9:]  # Remove temp_id prefix

    # Create job state
    job_data = {
        "status": "queued",
        "stage": "waiting (resume)",
        "current_page": 0,
        "total_pages": 0,
        "percent": 0,
        "error": None,
        "queue_position": 1,
        "filename": filename,
        "pdf_path": str(pdf_path),
        "tier": tier,
    }

    progress_store[temp_id] = job_data
    _sync_save_job(temp_id, job_data)

    # Ensure processing worker is running
    start_processing_worker()

    # Add to queue
    processing_queue.put(ProcessingJob(temp_id=temp_id, tier=tier, pdf_path=pdf_path))

    return {
        "status": "queued",
        "temp_id": temp_id,
        "queue_position": processing_queue.qsize()
    }


# =============================================================================
# EPUB Endpoints
# =============================================================================

@router.post("/assess-epub")
async def assess_epub(file: UploadFile = File(...)):
    """
    Upload and assess an EPUB file. Returns metadata and chapter/image counts.
    No tier selection needed — EPUB extraction is fast and deterministic.
    """
    temp_id = str(uuid.uuid4())[:8]
    temp_path = UPLOAD_DIR / f"{temp_id}_{file.filename}"

    try:
        contents = await file.read()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: temp_path.write_bytes(contents))

        # Quick metadata extraction (no full text processing)
        from services.lit_engine.epub_extractor import get_epub_metadata
        info = await loop.run_in_executor(None, get_epub_metadata, temp_path)

        # Check for existing extractions by title+author
        existing = _check_existing_extractions(file.filename, str(temp_path))

        return {
            "temp_id": temp_id,
            "filename": file.filename,
            "file_type": "epub",
            **info,
            "existing_extractions": existing,
        }

    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))


def _sync_process_epub(temp_id: str, epub_path: Path, overrides: dict) -> dict:
    """
    Synchronously process an EPUB: extract text + images, import to library.
    Runs in a thread pool since it does file I/O but no GPU work.
    """
    from services.lit_engine.epub_extractor import extract_epub, get_epub_metadata
    from services.finalize_document import standardize_folder_name

    # Get metadata for folder naming
    info = get_epub_metadata(epub_path)
    meta = info["metadata"]

    # Apply overrides
    title = overrides.get("title") or meta.get("title") or epub_path.stem
    author = overrides.get("author") or meta.get("author") or "Unknown"
    year = overrides.get("year") or meta.get("year")

    # Build folder name in Scholia format: Author_Year_Title
    year_str = str(year) if year else "XXXX"
    raw_name = f"{author} ({year_str}) - {title}"
    folder_name = standardize_folder_name(raw_name)

    documents_dir = _get_documents_dir()
    doc_folder = documents_dir / folder_name
    method_folder = doc_folder / f"{folder_name}--epub"
    doc_folder.mkdir(parents=True, exist_ok=True)
    method_folder.mkdir(parents=True, exist_ok=True)

    # Figures go into the method folder's figures/ subfolder
    figures_dir = method_folder / "figures"

    # Run extraction
    result = extract_epub(epub_path, method_folder, figures_dir)

    if not result["success"]:
        return {"success": False, "error": result.get("error", "Extraction failed")}

    # Copy original .epub to doc folder
    epub_dest = doc_folder / f"{folder_name}.epub"
    if not epub_dest.exists():
        shutil.copy2(epub_path, epub_dest)

    # Import to library database
    source_id = _sync_import_epub_source(folder_name, result, str(epub_dest))

    # Clean up upload
    if epub_path.exists() and str(UPLOAD_DIR) in str(epub_path):
        epub_path.unlink()

    return {
        "success": True,
        "source_id": source_id,
        "folder_name": folder_name,
        "chapter_count": result["chapter_count"],
        "image_count": result["image_count"],
    }


def _sync_import_epub_source(folder_name: str, extraction_result: dict, epub_path_str: str) -> str:
    """Import an extracted EPUB into the library database."""
    import sqlite3
    import hashlib

    db_path = DATA_DIR / "library.db"
    txt_path = extraction_result["text_path"]
    content = Path(txt_path).read_text(encoding="utf-8")
    now = datetime.now().isoformat()
    sections = extraction_result["sections"]
    meta = extraction_result["metadata"]

    # Compute hash of the epub file for duplicate detection
    epub_hash = None
    if Path(epub_path_str).exists():
        sha256 = hashlib.sha256()
        with open(epub_path_str, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        epub_hash = sha256.hexdigest()

    # Parse author/year/title from folder name
    parts = folder_name.split("_")
    author = None
    year = None
    title = folder_name

    year_idx = None
    for i, part in enumerate(parts):
        if re.match(r"^\d{4}$", part):
            year_idx = i
            year = int(part)
            break

    if year_idx is not None:
        author = " ".join(parts[:year_idx])
        title = " ".join(parts[year_idx + 1:])

    # Use metadata title/author if available (more accurate)
    if meta.get("title"):
        title = meta["title"]
    if meta.get("author"):
        author = meta["author"]
    if meta.get("year"):
        year = meta["year"]

    metadata_json = json.dumps({
        "original_path": epub_path_str,
        "extraction_method": "epub",
        "pdf_hash": epub_hash,  # reuse field name for consistency
        "publisher": meta.get("publisher"),
        "language": meta.get("language"),
    })

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()

        # Check for existing source by original_path
        cursor.execute("""
            SELECT id FROM sources
            WHERE json_extract(metadata, '$.original_path') = ?
        """, (epub_path_str,))
        existing = cursor.fetchone()

        if existing:
            source_id = existing[0]
            cursor.execute("""
                UPDATE sources
                SET title = ?, author_display = ?, year = ?, content_path = ?,
                    metadata = ?, updated_at = ?
                WHERE id = ?
            """, [title, author, year, txt_path, metadata_json, now, source_id])

            # Re-index sections
            cursor.execute("DELETE FROM sections WHERE source_id = ?", (source_id,))
            cursor.execute(
                "DELETE FROM sources_fts WHERE rowid = (SELECT rowid FROM sources WHERE id = ?)",
                (source_id,),
            )
            print(f"Updated EPUB source: {folder_name} (id: {source_id})")
        else:
            source_id = str(uuid.uuid4())[:8]
            cursor.execute("""
                INSERT INTO sources (id, title, source_type, author_display, year,
                                     content_path, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [source_id, title, "document", author, year,
                  txt_path, metadata_json, now, now])
            print(f"Imported EPUB source: {folder_name} (id: {source_id})")

        # Insert sections
        for i, section in enumerate(sections):
            section_id = f"{source_id}-s{i}"
            cursor.execute("""
                INSERT INTO sections (id, source_id, title, level, start_offset,
                                      end_offset, order_index, parent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [section_id, source_id, section["title"], section["level"],
                  section["start_offset"], section["end_offset"], i, None])

        # FTS index
        cursor.execute("""
            INSERT INTO sources_fts (rowid, title, author_display)
            SELECT rowid, title, author_display FROM sources WHERE id = ?
        """, [source_id])

        conn.commit()
        return source_id

    except Exception as e:
        print(f"Error importing EPUB source: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        conn.close()


@router.post("/process-epub")
async def process_epub(
    temp_id: str,
    title: Optional[str] = None,
    author: Optional[str] = None,
    year: Optional[int] = None,
):
    """
    Process a previously uploaded EPUB file.
    EPUB extraction is fast (no GPU), so runs synchronously in thread pool.

    Args:
        temp_id: The temp_id returned from /assess-epub
        title: Optional title override
        author: Optional author override
        year: Optional year override
    """
    # Find the uploaded file
    matches = list(UPLOAD_DIR.glob(f"{temp_id}_*"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"No file found for temp_id: {temp_id}")

    epub_path = matches[0]
    overrides = {}
    if title:
        overrides["title"] = title
    if author:
        overrides["author"] = author
    if year:
        overrides["year"] = year

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        _sync_process_epub,
        temp_id,
        epub_path,
        overrides,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Processing failed"))

    return {
        "status": "complete",
        "temp_id": temp_id,
        **result,
    }
