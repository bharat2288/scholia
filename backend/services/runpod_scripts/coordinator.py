#!/usr/bin/env python3
"""
Coordinator Script - Runs on each RunPod pod
=============================================
Claims PDFs from /data/input/, processes with dots-ocr, outputs to /data/output/

Features:
- Smart resume: detects already-processed pages and skips them
- Completion markers: writes _complete.json when all pages are done
- Files stay in /output/ and /input/ until downloaded by the backend
- Progress monitoring: background thread updates lock file every 30s
- Dynamic timeout: scales with remaining page count (4min/page)

Job Coordination:
- Each pod scans /data/input/ for PDFs
- Claims a job by atomically creating a lock file in /data/processing/
- If lock exists AND owned by another pod, skip
- If lock exists AND stale (no progress), reclaim
- On completion:
  1. Write _complete.json in output folder
  2. Release lock file
  3. Files stay in place until download endpoint moves them

Usage:
    python coordinator.py [--once]  # --once exits after processing all available

Environment:
    POD_ID: Automatically set by RunPod
    DATA_DIR: Override data directory (default: /workspace)
"""

import os
import re
import sys
import json
import time
import shutil
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import fitz  # pymupdf — installed on pods

# =============================================================================
# Configuration
# =============================================================================

POD_ID = os.environ.get("RUNPOD_POD_ID", f"pod-{os.getpid()}")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/workspace"))

INPUT_DIR = DATA_DIR / "input"
PROCESSING_DIR = DATA_DIR / "processing"
OUTPUT_DIR = DATA_DIR / "output"
LOGS_DIR = DATA_DIR / "logs"
ARCHIVE_DIR = DATA_DIR / "archive"  # Only populated after successful local finalization
DOWNLOADED_DIR = DATA_DIR / "downloaded"  # Intermediate: during download process

# Timeout settings
STALE_LOCK_MINUTES = 60  # Lock with no progress update for this long = stale
MIN_TIMEOUT_MINUTES = 30  # Minimum timeout for any PDF
TIMEOUT_PER_PAGE_SECONDS = 240  # 4 minutes per page (allows for complex pages)

POLL_INTERVAL_SECONDS = 10

# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging():
    """Configure logging to both file and console."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOGS_DIR / "coordinator.log"

    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

log = setup_logging()

# =============================================================================
# PDF Utilities
# =============================================================================

def get_pdf_page_count(pdf_path: Path) -> int:
    """Get page count from PDF using PyMuPDF."""
    try:
        doc = fitz.open(str(pdf_path))
        count = len(doc)
        doc.close()
        return count
    except Exception as e:
        log.warning(f"Could not get page count for {pdf_path.name}: {e}")
        return 0  # Return 0 so callers know it failed


def get_existing_pages(pdf_stem: str) -> set[int]:
    """Check output folder for already-processed pages."""
    output_folder = OUTPUT_DIR / pdf_stem / pdf_stem
    if not output_folder.exists():
        output_folder = OUTPUT_DIR / pdf_stem
        if not output_folder.exists():
            return set()

    existing = set()
    for json_file in output_folder.glob(f"{pdf_stem}_page_*.json"):
        try:
            page_str = json_file.stem.split("_page_")[-1]
            page_num = int(page_str)
            md_file = json_file.with_suffix(".md")
            if md_file.exists():
                existing.add(page_num)
        except (ValueError, IndexError):
            continue

    return existing


def calculate_timeout(total_pages: int, existing_pages: int) -> int:
    """Calculate appropriate timeout based on remaining pages."""
    remaining = total_pages - existing_pages
    timeout_seconds = remaining * TIMEOUT_PER_PAGE_SECONDS
    min_timeout_seconds = MIN_TIMEOUT_MINUTES * 60
    return max(timeout_seconds, min_timeout_seconds)


def create_subset_pdf(
    source_pdf: Path, missing_pages: list[int], dest_path: Path
) -> None:
    """
    Create a new PDF containing only the specified pages from source_pdf.

    Used for resume: extract only unprocessed pages so dots-ocr doesn't
    redo work. Pages are 0-indexed.
    """
    src_doc = fitz.open(str(source_pdf))
    dst_doc = fitz.open()  # empty document
    for page_num in missing_pages:
        dst_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
    dst_doc.save(str(dest_path))
    dst_doc.close()
    src_doc.close()
    log.info(f"Created subset PDF: {len(missing_pages)} pages -> {dest_path.name}")


def rename_temp_outputs(
    output_folder: Path,
    temp_stem: str,
    original_stem: str,
    missing_pages: list[int],
) -> int:
    """
    Rename dots-ocr outputs from temp page indices back to original numbers.

    dots-ocr names outputs as {stem}_page_{i}.* where i is 0-indexed within
    the PDF it received. If we gave it pages [322, 323, 346], then:
        temp_page_0 -> original_page_322
        temp_page_1 -> original_page_323
        temp_page_2 -> original_page_346

    Scans both the output folder and nested subfolder (dots-ocr creates
    output_folder/temp_stem/ sometimes).
    """
    renamed_count = 0

    # dots-ocr may put files in output_folder/temp_stem/ (nested) or directly
    search_dirs = [output_folder]
    nested = output_folder / temp_stem
    if nested.exists():
        search_dirs.append(nested)

    for search_dir in search_dirs:
        for temp_idx, original_page in enumerate(missing_pages):
            temp_prefix = f"{temp_stem}_page_{temp_idx}"
            original_prefix = f"{original_stem}_page_{original_page}"

            for f in list(search_dir.iterdir()):
                if f.name.startswith(temp_prefix):
                    suffix = f.name[len(temp_prefix):]
                    new_name = f"{original_prefix}{suffix}"
                    # Move to the correct nested folder if it exists
                    original_nested = output_folder / original_stem
                    if original_nested.exists() and original_nested.is_dir():
                        dest = original_nested / new_name
                    else:
                        dest = output_folder / new_name
                    f.rename(dest)
                    renamed_count += 1

    # Clean up empty temp nested folder if created
    if nested.exists() and not any(nested.iterdir()):
        nested.rmdir()

    return renamed_count

# =============================================================================
# Lock Management
# =============================================================================

def claim_job(pdf_path: Path) -> bool:
    """Try to claim a PDF for processing using atomic file creation."""
    lock_path = PROCESSING_DIR / f"{pdf_path.stem}.lock"

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)

        total_pages = get_pdf_page_count(pdf_path)
        existing_pages = get_existing_pages(pdf_path.stem)

        lock_data = json.dumps({
            "pod_id": POD_ID,
            "pdf_name": pdf_path.name,
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "processing",
            "total_pages": total_pages,
            "existing_pages_at_start": len(existing_pages),
            "current_page": len(existing_pages),
        }, indent=2)
        os.write(fd, lock_data.encode())
        os.close(fd)

        log.info(f"Claimed: {pdf_path.name} ({len(existing_pages)}/{total_pages} pages exist)")
        return True

    except FileExistsError:
        lock_info = read_lock(lock_path)

        if lock_info is None:
            return try_reclaim_lock(lock_path, pdf_path)

        if lock_info.get("pod_id") == POD_ID:
            log.info(f"Resuming our own lock: {pdf_path.name}")
            return True

        if is_lock_stale(lock_info):
            return try_reclaim_lock(lock_path, pdf_path)

        return False

    except OSError as e:
        log.error(f"Failed to claim {pdf_path.name}: {e}")
        return False


def read_lock(lock_path: Path) -> Optional[dict]:
    """Read and parse lock file."""
    try:
        with open(lock_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, IOError):
        return None


def is_lock_stale(lock_info: dict) -> bool:
    """Check if a lock is stale based on last update time."""
    try:
        updated_str = lock_info.get("updated_at") or lock_info.get("started_at")
        if not updated_str:
            return True
        updated = datetime.fromisoformat(updated_str)
        age = datetime.now() - updated
        return age > timedelta(minutes=STALE_LOCK_MINUTES)
    except (ValueError, TypeError):
        return True


def try_reclaim_lock(lock_path: Path, pdf_path: Path) -> bool:
    """Try to reclaim a stale or corrupted lock."""
    log.warning(f"Reclaiming stale lock: {lock_path.name}")
    try:
        os.remove(lock_path)
        time.sleep(0.1)
        return claim_job(pdf_path)
    except OSError:
        return False


def update_lock_progress(pdf_path: Path, current_page: int, total_pages: int):
    """Update lock file with processing progress."""
    lock_path = PROCESSING_DIR / f"{pdf_path.stem}.lock"

    try:
        lock_info = read_lock(lock_path)
        if lock_info is None:
            return

        lock_info["current_page"] = current_page
        lock_info["total_pages"] = total_pages
        lock_info["percent"] = int((current_page / total_pages) * 100) if total_pages > 0 else 0
        lock_info["updated_at"] = datetime.now().isoformat()

        with open(lock_path, 'w') as f:
            json.dump(lock_info, f, indent=2)
    except Exception as e:
        log.warning(f"Failed to update lock progress: {e}")


def release_lock(pdf_path: Path, success: bool = True, error: Optional[str] = None):
    """Release a lock file after processing completes or fails."""
    lock_path = PROCESSING_DIR / f"{pdf_path.stem}.lock"

    if success:
        try:
            lock_path.unlink(missing_ok=True)
            log.info(f"Released lock: {pdf_path.name}")
        except OSError as e:
            log.warning(f"Failed to release lock: {e}")
    else:
        try:
            lock_info = read_lock(lock_path) or {}
            lock_info["status"] = "failed"
            lock_info["error"] = error
            lock_info["failed_at"] = datetime.now().isoformat()
            with open(lock_path, 'w') as f:
                json.dump(lock_info, f, indent=2)
        except Exception:
            pass

# =============================================================================
# PDF Processing
# =============================================================================

def is_pdf_complete(pdf_path: Path) -> bool:
    """Check if a PDF has already been fully processed."""
    total_pages = get_pdf_page_count(pdf_path)
    existing_pages = get_existing_pages(pdf_path.stem)

    if len(existing_pages) >= total_pages:
        log.info(f"Already complete: {pdf_path.name} ({len(existing_pages)}/{total_pages} pages)")
        return True

    return False


def is_already_marked_complete(pdf_path: Path) -> bool:
    """Check if a PDF has already been marked complete with _complete.json."""
    output_folder = OUTPUT_DIR / pdf_path.stem
    complete_marker = output_folder / "_complete.json"
    return complete_marker.exists()


def mark_completed(pdf_path: Path):
    """
    Write _complete.json marker file in output folder.

    Files stay in /output/ and /input/ until downloaded.
    The marker file signals to the frontend that this job is ready for download.
    """
    pdf_stem = pdf_path.stem
    output_folder = OUTPUT_DIR / pdf_stem
    complete_marker = output_folder / "_complete.json"

    if not output_folder.exists():
        log.warning(f"Output folder not found for {pdf_stem}, cannot mark complete")
        return

    total_pages = get_pdf_page_count(pdf_path)
    existing_pages = get_existing_pages(pdf_stem)

    complete_data = {
        "status": "completed",
        "total_pages": total_pages,
        "actual_pages": len(existing_pages),
        "completed_at": datetime.now().isoformat(),
        "pod_id": POD_ID,
        "source_pdf": pdf_path.name,
        "source_pdf_location": str(pdf_path)
    }

    try:
        with open(complete_marker, 'w') as f:
            json.dump(complete_data, f, indent=2)
        log.info(f"Marked complete: {pdf_stem} ({len(existing_pages)}/{total_pages} pages)")
        log.info(f"  _complete.json written to {output_folder}")
    except Exception as e:
        log.error(f"Failed to write _complete.json for {pdf_stem}: {e}")


def process_pdf(pdf_path: Path) -> bool:
    """
    Process a PDF using dots.ocr with real resume via subset PDFs.

    dots-ocr has NO built-in page skipping — it processes every page in the
    PDF it receives. To resume, we:
    1. Detect which pages already have output files
    2. If all done -> mark complete, skip
    3. If some done -> extract only missing pages into a temp PDF,
       run dots-ocr on that, then rename outputs back to original page numbers
    4. If none done -> run on the full PDF normally
    """
    # Check if already marked complete
    if is_already_marked_complete(pdf_path):
        log.info(f"Already marked complete: {pdf_path.name}")
        return True

    total_pages = get_pdf_page_count(pdf_path)
    if total_pages == 0:
        log.error(f"Could not read page count: {pdf_path.name}")
        return False

    existing_pages = get_existing_pages(pdf_path.stem)
    all_pages = set(range(total_pages))
    missing_pages = sorted(all_pages - existing_pages)

    # All pages already done
    if not missing_pages:
        log.info(f"All {total_pages} pages done — marking complete: {pdf_path.name}")
        mark_completed(pdf_path)
        return True

    output_folder = OUTPUT_DIR / pdf_path.stem
    output_folder.mkdir(parents=True, exist_ok=True)

    log.info(f"Processing: {pdf_path.name}")
    log.info(f"  Total: {total_pages}, Done: {len(existing_pages)}, Remaining: {len(missing_pages)}")
    log.info(f"  Output: {output_folder}")

    # Determine whether to use a subset PDF for resume
    use_temp_pdf = len(existing_pages) > 0
    actual_pdf = pdf_path
    temp_pdf_path = None

    if use_temp_pdf:
        temp_pdf_path = output_folder / f"_temp_resume.pdf"
        log.info(f"  Resume mode: creating subset PDF with {len(missing_pages)} pages...")
        try:
            create_subset_pdf(pdf_path, missing_pages, temp_pdf_path)
            actual_pdf = temp_pdf_path
        except Exception as e:
            log.error(f"Failed to create subset PDF: {e}")
            return False

    # Calculate timeout based on pages being processed
    timeout_seconds = calculate_timeout(total_pages, len(existing_pages))
    timeout_minutes = timeout_seconds // 60
    log.info(f"  Timeout: {timeout_minutes} minutes for {len(missing_pages)} pages")

    dots_ocr_repo = DATA_DIR / "dots_ocr_repo"
    parser_script = dots_ocr_repo / "dots_ocr" / "parser.py"

    if not parser_script.exists():
        log.error(f"dots.ocr parser not found at {parser_script}")
        return False

    # Background thread to monitor progress and keep lock alive
    import threading
    stop_monitor = threading.Event()

    def monitor_progress():
        while not stop_monitor.is_set():
            current = len(get_existing_pages(pdf_path.stem))
            update_lock_progress(pdf_path, current, total_pages)
            stop_monitor.wait(30)

    monitor_thread = threading.Thread(target=monitor_progress, daemon=True)
    monitor_thread.start()

    try:
        result = subprocess.run(
            [
                "python3",
                str(parser_script),
                str(actual_pdf),
                "--num_thread", "32",
                "--use_hf", "true",
                "--output", str(output_folder),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(dots_ocr_repo),
        )

        stop_monitor.set()
        monitor_thread.join(timeout=1)

        if result.returncode == 0:
            if result.stdout:
                log.info(f"Output: {result.stdout[-500:]}")

            # Rename temp outputs back to original page numbers
            if use_temp_pdf:
                renamed = rename_temp_outputs(
                    output_folder, temp_pdf_path.stem, pdf_path.stem, missing_pages
                )
                log.info(f"Renamed {renamed} temp output files to original page numbers")

            final_pages = len(get_existing_pages(pdf_path.stem))
            log.info(f"Completed: {pdf_path.name} ({final_pages}/{total_pages} pages)")
            mark_completed(pdf_path)
            return True
        else:
            log.error(f"dots.ocr failed with code {result.returncode}")
            if result.stderr:
                log.error(f"stderr: {result.stderr[-1000:]}")
            if result.stdout:
                log.error(f"stdout: {result.stdout[-500:]}")
            return False

    except subprocess.TimeoutExpired:
        stop_monitor.set()
        # On timeout: rename whatever partial outputs were produced so far,
        # so the NEXT retry picks up from further along
        if use_temp_pdf:
            renamed = rename_temp_outputs(
                output_folder, temp_pdf_path.stem, pdf_path.stem, missing_pages
            )
            log.info(f"Timeout recovery: renamed {renamed} partial output files")

        final_pages = len(get_existing_pages(pdf_path.stem))
        log.error(
            f"Timeout after {timeout_minutes}min: {pdf_path.name} "
            f"({final_pages}/{total_pages} pages done)"
        )
        if final_pages > len(existing_pages):
            log.info(f"Made progress ({len(existing_pages)} -> {final_pages}), next retry will resume")
        return False

    except FileNotFoundError as e:
        stop_monitor.set()
        log.error(f"Command not found: {e}")
        return False
    except Exception as e:
        stop_monitor.set()
        log.error(f"Processing error: {e}")
        return False
    finally:
        # Always clean up temp PDF
        if temp_pdf_path and temp_pdf_path.exists():
            temp_pdf_path.unlink()
            log.info("Cleaned up temp resume PDF")


def get_pending_pdfs() -> list[Path]:
    """Get list of PDFs in input directory, sorted by size."""
    if not INPUT_DIR.exists():
        return []

    pdfs = list(INPUT_DIR.glob("*.pdf"))
    pdfs.sort(key=lambda p: p.stat().st_size)
    return pdfs


def get_active_locks() -> list[Path]:
    """Get list of active (non-stale) lock files."""
    if not PROCESSING_DIR.exists():
        return []

    locks = []
    for lock_path in PROCESSING_DIR.glob("*.lock"):
        lock_info = read_lock(lock_path)
        if lock_info and not is_lock_stale(lock_info):
            locks.append(lock_path)
    return locks

# =============================================================================
# Status Reporting
# =============================================================================

def write_status():
    """Write current pod status to shared status file."""
    status_file = DATA_DIR / "status.json"

    try:
        if status_file.exists():
            with open(status_file) as f:
                status = json.load(f)
        else:
            status = {"pods": {}, "updated_at": None}

        pending = len(get_pending_pdfs())
        active_locks = get_active_locks()

        # Count completed jobs (have _complete.json)
        completed_count = 0
        if OUTPUT_DIR.exists():
            for folder in OUTPUT_DIR.iterdir():
                if folder.is_dir() and (folder / "_complete.json").exists():
                    completed_count += 1

        status["pods"][POD_ID] = {
            "last_seen": datetime.now().isoformat(),
            "status": "active"
        }
        status["summary"] = {
            "pending": pending,
            "processing": len(active_locks),
            "completed": completed_count
        }
        status["updated_at"] = datetime.now().isoformat()

        temp_file = status_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(status, f, indent=2)
        temp_file.rename(status_file)

    except Exception as e:
        log.warning(f"Failed to write status: {e}")

# =============================================================================
# Main Loop
# =============================================================================

def run_coordinator(run_once: bool = False):
    """Main coordinator loop."""
    log.info("=" * 60)
    log.info(f"Coordinator starting on pod: {POD_ID}")
    log.info(f"Data directory: {DATA_DIR}")
    log.info(f"Stale lock timeout: {STALE_LOCK_MINUTES} minutes")
    log.info(f"Timeout per page: {TIMEOUT_PER_PAGE_SECONDS} seconds")
    log.info("=" * 60)

    for dir_path in [INPUT_DIR, PROCESSING_DIR, OUTPUT_DIR, LOGS_DIR, ARCHIVE_DIR, DOWNLOADED_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)

    jobs_processed = 0
    consecutive_idle = 0

    while True:
        pdfs = get_pending_pdfs()
        claimed_any = False

        for pdf in pdfs:
            # Skip if already marked complete
            if is_already_marked_complete(pdf):
                log.info(f"Skipping (already complete): {pdf.name}")
                continue

            if is_pdf_complete(pdf):
                mark_completed(pdf)
                continue

            if claim_job(pdf):
                claimed_any = True
                consecutive_idle = 0

                success = process_pdf(pdf)
                release_lock(pdf, success=success)

                if success:
                    jobs_processed += 1

                write_status()

        active_locks = get_active_locks()
        remaining_pdfs = [p for p in get_pending_pdfs() if not is_already_marked_complete(p)]

        if not remaining_pdfs and not active_locks:
            log.info("=" * 60)
            log.info(f"All jobs complete! Processed {jobs_processed} PDFs.")
            log.info("Exiting coordinator.")
            log.info("=" * 60)
            break

        if run_once:
            log.info(f"Single-run mode. Processed {jobs_processed} PDFs.")
            break

        if not claimed_any:
            consecutive_idle += 1

            if remaining_pdfs:
                log.info(f"All {len(remaining_pdfs)} pending PDFs are locked by other pods")
            else:
                log.info(f"Waiting for {len(active_locks)} active jobs to complete...")

            wait_time = min(POLL_INTERVAL_SECONDS * (2 ** min(consecutive_idle - 1, 3)), 60)
            log.info(f"Sleeping {wait_time}s...")
            time.sleep(wait_time)
        else:
            consecutive_idle = 0
            time.sleep(1)

        write_status()


def main():
    parser = argparse.ArgumentParser(description="RunPod PDF Processing Coordinator")
    parser.add_argument("--once", action="store_true", help="Process once and exit")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    args = parser.parse_args()

    if args.status:
        pending = len(get_pending_pdfs())
        active = len(get_active_locks())

        # Count completed
        completed = 0
        if OUTPUT_DIR.exists():
            for folder in OUTPUT_DIR.iterdir():
                if folder.is_dir() and (folder / "_complete.json").exists():
                    completed += 1

        print(f"Pod ID: {POD_ID}")
        print(f"Pending: {pending}")
        print(f"Processing: {active}")
        print(f"Completed (ready to download): {completed}")
        return

    try:
        run_coordinator(run_once=args.once)
    except KeyboardInterrupt:
        log.info("Interrupted by user. Exiting.")
        sys.exit(0)
    except Exception as e:
        log.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
