#!/usr/bin/env python3
"""
Coordinator Script - Runs on each RunPod pod
=============================================
Claims PDFs from /data/input/, processes with dots-ocr, outputs to /data/output/

Job Coordination:
- Each pod scans /data/input/ for PDFs
- Claims a job by atomically creating a lock file in /data/processing/
- If lock exists, another pod has it - skip and try next
- On completion, output goes to /data/output/, lock is removed
- Stale locks (>30 min) are reclaimed automatically

Usage:
    python coordinator.py [--once]  # --once exits after processing all available

Environment:
    POD_ID: Automatically set by RunPod
    DATA_DIR: Override data directory (default: /data)
"""

import os
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

# =============================================================================
# Configuration
# =============================================================================

POD_ID = os.environ.get("RUNPOD_POD_ID", f"unknown-{os.getpid()}")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/workspace"))

INPUT_DIR = DATA_DIR / "input"
PROCESSING_DIR = DATA_DIR / "processing"
OUTPUT_DIR = DATA_DIR / "output"
LOGS_DIR = DATA_DIR / "logs"
ARCHIVE_DIR = DATA_DIR / "archive"  # Successfully processed PDFs move here

LOCK_TIMEOUT_MINUTES = 30
POLL_INTERVAL_SECONDS = 10
MAX_RETRIES = 3

# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging():
    """Configure logging to both file and console."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"pod_{POD_ID}.log"

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

log = setup_logging()

# =============================================================================
# Lock Management
# =============================================================================

def claim_job(pdf_path: Path) -> bool:
    """
    Try to claim a PDF for processing using atomic file creation.

    Returns True if we successfully claimed the job.
    Returns False if another pod already claimed it.
    """
    lock_path = PROCESSING_DIR / f"{pdf_path.stem}.lock"

    try:
        # O_CREAT | O_EXCL = create only if doesn't exist (atomic)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)

        # Write lock metadata
        lock_data = json.dumps({
            "pod_id": POD_ID,
            "pdf_name": pdf_path.name,
            "started_at": datetime.now().isoformat(),
            "status": "processing"
        }, indent=2)
        os.write(fd, lock_data.encode())
        os.close(fd)

        log.info(f"Claimed: {pdf_path.name}")
        return True

    except FileExistsError:
        # Lock exists - check if stale
        if is_lock_stale(lock_path):
            log.warning(f"Reclaiming stale lock: {lock_path.name}")
            try:
                os.remove(lock_path)
                return claim_job(pdf_path)  # Retry claim
            except OSError:
                pass  # Another pod beat us to it
        return False
    except OSError as e:
        log.error(f"Failed to claim {pdf_path.name}: {e}")
        return False


def is_lock_stale(lock_path: Path) -> bool:
    """Check if a lock file is older than the timeout threshold."""
    try:
        with open(lock_path) as f:
            data = json.load(f)
        started = datetime.fromisoformat(data["started_at"])
        age = datetime.now() - started
        return age > timedelta(minutes=LOCK_TIMEOUT_MINUTES)
    except (json.JSONDecodeError, KeyError, ValueError):
        # Corrupted or invalid lock file = treat as stale
        return True
    except FileNotFoundError:
        # Lock was removed while we were checking
        return False


def update_lock_progress(pdf_path: Path, current_page: int, total_pages: int):
    """Update lock file with processing progress."""
    lock_path = PROCESSING_DIR / f"{pdf_path.stem}.lock"

    try:
        with open(lock_path, 'r') as f:
            data = json.load(f)

        data["current_page"] = current_page
        data["total_pages"] = total_pages
        data["percent"] = int((current_page / total_pages) * 100) if total_pages > 0 else 0
        data["updated_at"] = datetime.now().isoformat()

        with open(lock_path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.warning(f"Failed to update lock progress: {e}")


def release_lock(pdf_path: Path, success: bool = True, error: Optional[str] = None):
    """Release a lock file after processing completes or fails."""
    lock_path = PROCESSING_DIR / f"{pdf_path.stem}.lock"

    if success:
        # Clean removal on success
        try:
            lock_path.unlink(missing_ok=True)
            log.info(f"Released lock: {pdf_path.name}")
        except OSError as e:
            log.warning(f"Failed to release lock: {e}")
    else:
        # On failure, update lock with error but leave it for inspection
        try:
            with open(lock_path, 'r') as f:
                data = json.load(f)
            data["status"] = "failed"
            data["error"] = error
            data["failed_at"] = datetime.now().isoformat()
            with open(lock_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

# =============================================================================
# PDF Processing
# =============================================================================

def process_pdf(pdf_path: Path) -> bool:
    """
    Process a PDF using dots.ocr.

    dots.ocr outputs:
    - {filename}.json: Structured layout data with bounding boxes and text
    - {filename}.md: Markdown version of extracted text
    - {filename}_nohf.md: Markdown without headers/footers

    Returns True on success, False on failure.
    """
    output_folder = OUTPUT_DIR / pdf_path.stem
    output_folder.mkdir(parents=True, exist_ok=True)

    log.info(f"Processing: {pdf_path.name}")
    log.info(f"Output to: {output_folder}")

    # dots.ocr repo location on shared volume
    dots_ocr_repo = DATA_DIR / "dots_ocr_repo"
    parser_script = dots_ocr_repo / "dots_ocr" / "parser.py"

    if not parser_script.exists():
        log.error(f"dots.ocr parser not found at {parser_script}")
        return False

    try:
        # Run dots.ocr parser
        # Uses HuggingFace backend (--use_hf true) for simplicity
        # num_thread controls parallel page processing
        result = subprocess.run(
            [
                "python3",
                str(parser_script),
                str(pdf_path),
                "--num_thread", "32",  # Parallel page processing
                "--use_hf", "true",    # Use HuggingFace backend (simpler than vLLM)
                "--output", str(output_folder)
            ],
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout per PDF
            cwd=str(dots_ocr_repo)  # Run from repo dir for correct weight paths
        )

        if result.returncode == 0:
            log.info(f"Completed: {pdf_path.name}")
            if result.stdout:
                log.info(f"Output: {result.stdout[-500:]}")  # Last 500 chars

            # Archive the original PDF (don't delete - user may want it)
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            archive_path = ARCHIVE_DIR / pdf_path.name

            # Move from input to archive
            shutil.move(str(pdf_path), str(archive_path))
            log.info(f"Archived: {pdf_path.name}")

            return True
        else:
            log.error(f"dots.ocr failed with code {result.returncode}")
            if result.stderr:
                log.error(f"stderr: {result.stderr[-1000:]}")  # Last 1000 chars
            if result.stdout:
                log.error(f"stdout: {result.stdout[-500:]}")
            return False

    except subprocess.TimeoutExpired:
        log.error(f"Processing timed out after 2 hours: {pdf_path.name}")
        return False
    except FileNotFoundError as e:
        log.error(f"Command not found: {e}")
        return False
    except Exception as e:
        log.error(f"Processing error: {e}")
        return False


def get_pending_pdfs() -> list[Path]:
    """Get list of PDFs in input directory, sorted by size (smallest first)."""
    if not INPUT_DIR.exists():
        return []

    pdfs = list(INPUT_DIR.glob("*.pdf"))
    # Process smaller files first for quicker wins
    pdfs.sort(key=lambda p: p.stat().st_size)
    return pdfs


def get_active_locks() -> list[Path]:
    """Get list of active (non-stale) lock files."""
    if not PROCESSING_DIR.exists():
        return []

    locks = []
    for lock_path in PROCESSING_DIR.glob("*.lock"):
        if not is_lock_stale(lock_path):
            locks.append(lock_path)
    return locks

# =============================================================================
# Status Reporting
# =============================================================================

def write_status():
    """Write current pod status to shared status file."""
    status_file = DATA_DIR / "status.json"

    try:
        # Read existing status or create new
        if status_file.exists():
            with open(status_file) as f:
                status = json.load(f)
        else:
            status = {"pods": {}, "updated_at": None}

        # Update our pod's status
        pending = len(get_pending_pdfs())
        active_locks = get_active_locks()
        completed = len(list(OUTPUT_DIR.glob("*"))) if OUTPUT_DIR.exists() else 0

        status["pods"][POD_ID] = {
            "last_seen": datetime.now().isoformat(),
            "status": "active"
        }
        status["summary"] = {
            "pending": pending,
            "processing": len(active_locks),
            "completed": completed
        }
        status["updated_at"] = datetime.now().isoformat()

        # Write atomically (write to temp, then rename)
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
    """
    Main coordinator loop.

    Continuously scans for PDFs, claims available ones, and processes them.
    Exits when all work is done (no pending PDFs and no active locks).

    Args:
        run_once: If True, exit after one full scan instead of looping
    """
    log.info("=" * 60)
    log.info(f"Coordinator starting on pod: {POD_ID}")
    log.info(f"Data directory: {DATA_DIR}")
    log.info("=" * 60)

    # Ensure directories exist
    for dir_path in [INPUT_DIR, PROCESSING_DIR, OUTPUT_DIR, LOGS_DIR, ARCHIVE_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)

    jobs_processed = 0
    consecutive_idle = 0

    while True:
        pdfs = get_pending_pdfs()
        claimed_any = False

        for pdf in pdfs:
            if claim_job(pdf):
                claimed_any = True
                consecutive_idle = 0

                # Process the PDF
                success = process_pdf(pdf)
                release_lock(pdf, success=success)

                if success:
                    jobs_processed += 1

                # Update shared status
                write_status()

        # Check if all work is done
        active_locks = get_active_locks()
        remaining_pdfs = get_pending_pdfs()

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

            # Exponential backoff when idle (up to 60 seconds)
            wait_time = min(POLL_INTERVAL_SECONDS * (2 ** min(consecutive_idle - 1, 3)), 60)
            log.info(f"Sleeping {wait_time}s...")
            time.sleep(wait_time)
        else:
            consecutive_idle = 0
            time.sleep(1)  # Brief pause between jobs

        # Update status periodically
        write_status()


def main():
    parser = argparse.ArgumentParser(description="RunPod PDF Processing Coordinator")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process available PDFs once and exit (don't loop)"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current status and exit"
    )
    args = parser.parse_args()

    if args.status:
        # Just print status and exit
        pending = len(get_pending_pdfs())
        active = len(get_active_locks())
        completed = len(list(OUTPUT_DIR.glob("*"))) if OUTPUT_DIR.exists() else 0

        print(f"Pod ID: {POD_ID}")
        print(f"Pending: {pending}")
        print(f"Processing: {active}")
        print(f"Completed: {completed}")
        return

    try:
        run_coordinator(run_once=args.once)
    except KeyboardInterrupt:
        log.info("Interrupted by user. Exiting.")
        sys.exit(0)
    except Exception as e:
        log.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
