"""
RunPod Router
=============
Endpoints for managing remote GPU processing on RunPod.

Features:
- Connection configuration (save/load/test)
- Upload PDFs to pod and start processing
- Poll job status
- Download completed jobs as zip
- Finalize (rebuild_extracted + crop_figures)
- Multi-pod management via RunPod API
- Network Volume operations
"""

import subprocess
import json
import uuid
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio

from database import get_db
from routers.processor import _check_existing_extractions
from services.runpod_api import RunPodClient, get_runpod_client

# Paths
DATA_DIR = Path(__file__).parent.parent.parent / "data"
DOCUMENTS_DIR = DATA_DIR / "sources" / "documents"
CONFIG_FILE = DATA_DIR / "runpod_connection.json"
UPLOAD_TEMP_DIR = DATA_DIR / "runpod_uploads"

# Default SSH key location
DEFAULT_SSH_KEY = Path.home() / ".ssh" / "id_ed25519"

# Default network volume (can be overridden in config)
# Texas volume (US-TX-3) has better GPU availability than Montreal (CA-MTL-1)
DEFAULT_VOLUME_ID = "rxfyzj7m42"

router = APIRouter(prefix="/runpod", tags=["runpod"])


# ============================================================================
# Pydantic Models
# ============================================================================

class RunPodConfig(BaseModel):
    host: str
    port: int
    pod_id: Optional[str] = None
    ssh_key_path: Optional[str] = None


class ConfigResponse(BaseModel):
    configured: bool
    host: Optional[str] = None
    port: Optional[int] = None
    pod_id: Optional[str] = None
    ssh_key_path: Optional[str] = None
    last_updated: Optional[str] = None


class TestResponse(BaseModel):
    connected: bool
    gpu: Optional[str] = None
    workspace_available: Optional[bool] = None
    error: Optional[str] = None


class ExistingExtractions(BaseModel):
    """Info about existing extractions for duplicate detection."""
    folder_name: Optional[str] = None
    folder_exists: bool = False
    existing_methods: list[str] = []
    document_id: Optional[str] = None
    annotation_count: int = 0
    match_type: Optional[str] = None  # "exact" | "folder" | "fuzzy" | None
    matched_title: Optional[str] = None  # Title of matched document


class UploadResponse(BaseModel):
    job_id: str
    filename: str
    status: str
    existing_extractions: Optional[ExistingExtractions] = None


class JobInfo(BaseModel):
    job_id: str
    filename: str
    status: str
    current_page: int = 0
    total_pages: int = 0
    folder_name: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    downloaded_at: Optional[str] = None
    finalized_at: Optional[str] = None


class JobsResponse(BaseModel):
    jobs: list[JobInfo]
    pod_status: Optional[dict] = None
    last_poll: Optional[str] = None


class DownloadResponse(BaseModel):
    status: str
    job_id: str
    local_path: Optional[str] = None
    page_count: Optional[int] = None
    error: Optional[str] = None


class FinalizeResult(BaseModel):
    job_id: str
    folder_name: str
    chars_extracted: int = 0
    figures_cropped: int = 0
    error: Optional[str] = None


class FinalizeResponse(BaseModel):
    finalized: list[FinalizeResult]
    errors: list[str]


# ============================================================================
# Folder Name Conversion
# ============================================================================

import re

# Import shared finalization module
from services.finalize_document import (
    standardize_folder_name,
    finalize_document,
    MAX_FOLDER_NAME_LENGTH
)


def _zotero_to_scholia_folder(zotero_name: str) -> str:
    """
    Convert Zotero-style folder name to Scholia format.

    Delegates to shared standardize_folder_name() from finalize_document module.
    This function is kept for backwards compatibility with job discovery code.

    Examples:
        "Gillespie (2014) - The Relevance of Algorithms"
        -> "Gillespie_2014_Relevance_Algorithms"
    """
    return standardize_folder_name(zotero_name)


# ============================================================================
# SSH/SCP Helpers
# ============================================================================

def _get_config() -> Optional[dict]:
    """Load RunPod connection config from JSON file."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return None


def _get_ssh_key_path(config: dict) -> Path:
    """Get SSH key path, expanding ~ if present."""
    key_path = config.get("ssh_key_path") or str(DEFAULT_SSH_KEY)
    return Path(key_path).expanduser()


def _ssh_command(config: dict, cmd: str, timeout: int = 30) -> tuple[bool, str]:
    """Run SSH command on RunPod and return (success, output)."""
    ssh_key = _get_ssh_key_path(config)

    # Use shutil.which to find ssh in PATH, with fallback to common locations
    import shutil
    ssh_path = shutil.which("ssh")
    if not ssh_path:
        # Try common locations on Windows
        for candidate in [
            r"C:\Program Files\Git\usr\bin\ssh.exe",
            r"C:\Windows\System32\OpenSSH\ssh.exe",
        ]:
            if Path(candidate).exists():
                ssh_path = candidate
                break
    if not ssh_path:
        return False, "SSH command not found. Is OpenSSH or Git Bash installed?"

    try:
        result = subprocess.run(
            [
                ssh_path, "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
                "-i", str(ssh_key),
                "-p", str(config["port"]),
                f"root@{config['host']}",
                cmd
            ],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "SSH connection timed out"
    except FileNotFoundError:
        return False, f"SSH not found at {ssh_path}"
    except Exception as e:
        return False, str(e)


import asyncio
import paramiko

def _ssh_command_paramiko(config: dict, cmd: str, timeout: int = 30) -> tuple[bool, str]:
    """
    Run SSH command using paramiko library (more reliable on Windows).

    Falls back to subprocess if paramiko fails to connect.
    """
    ssh_key = _get_ssh_key_path(config)

    try:
        # Create SSH client
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Load private key
        pkey = paramiko.Ed25519Key.from_private_key_file(str(ssh_key))

        # Connect
        client.connect(
            hostname=config["host"],
            port=int(config["port"]),
            username="root",
            pkey=pkey,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout
        )

        # Execute command
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        output = stdout.read().decode('utf-8').strip()
        error = stderr.read().decode('utf-8').strip()
        exit_status = stdout.channel.recv_exit_status()

        client.close()

        if exit_status == 0:
            return True, output
        else:
            return False, error or output or f"Command failed with exit status {exit_status}"

    except paramiko.AuthenticationException:
        return False, "SSH authentication failed"
    except paramiko.SSHException as e:
        return False, f"SSH error: {str(e)}"
    except TimeoutError:
        return False, "SSH connection timed out"
    except Exception as e:
        return False, f"SSH error: {str(e)}"


async def _ssh_command_async(config: dict, cmd: str, timeout: int = 30) -> tuple[bool, str]:
    """Run SSH command asynchronously using paramiko (doesn't block event loop)."""
    return await asyncio.to_thread(_ssh_command_paramiko, config, cmd, timeout)


def _scp_upload(config: dict, local_path: Path, remote_path: str, timeout: int = 300) -> tuple[bool, str]:
    """Upload file to RunPod via SCP."""
    ssh_key = _get_ssh_key_path(config)

    try:
        result = subprocess.run(
            [
                "scp", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
                "-i", str(ssh_key),
                "-P", str(config["port"]),
                str(local_path),
                f"root@{config['host']}:{remote_path}"
            ],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode == 0:
            return True, "Upload successful"
        return False, result.stderr.strip() or "SCP upload failed"
    except subprocess.TimeoutExpired:
        return False, "SCP upload timed out"
    except Exception as e:
        return False, str(e)


def _scp_download(config: dict, remote_path: str, local_path: Path, is_dir: bool = False, timeout: int = 600) -> tuple[bool, str]:
    """Download file/directory from RunPod via SCP."""
    ssh_key = _get_ssh_key_path(config)
    local_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        args = [
            "scp", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
            "-i", str(ssh_key),
            "-P", str(config["port"]),
        ]
        if is_dir:
            args.append("-r")

        args.extend([
            f"root@{config['host']}:{remote_path}",
            str(local_path)
        ])

        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return True, "Download successful"
        return False, result.stderr.strip() or "SCP download failed"
    except subprocess.TimeoutExpired:
        return False, "SCP download timed out"
    except Exception as e:
        return False, str(e)


# ============================================================================
# Configuration Endpoints
# ============================================================================

@router.get("/config", response_model=ConfigResponse)
async def get_config():
    """Get current RunPod connection configuration."""
    config = _get_config()
    if not config:
        return ConfigResponse(configured=False)

    return ConfigResponse(
        configured=True,
        host=config.get("host"),
        port=config.get("port"),
        pod_id=config.get("pod_id"),
        ssh_key_path=config.get("ssh_key_path"),
        last_updated=config.get("last_updated")
    )


@router.post("/config", response_model=ConfigResponse)
async def save_config(config: RunPodConfig):
    """Save RunPod connection configuration."""
    # Validate SSH key exists
    ssh_key = Path(config.ssh_key_path or str(DEFAULT_SSH_KEY)).expanduser()
    if not ssh_key.exists():
        raise HTTPException(status_code=400, detail=f"SSH key not found at {ssh_key}")

    # Save config
    config_data = {
        "host": config.host,
        "port": config.port,
        "pod_id": config.pod_id,
        "ssh_key_path": str(ssh_key),
        "last_updated": datetime.now().isoformat()
    }

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config_data, indent=2))

    return ConfigResponse(
        configured=True,
        host=config.host,
        port=config.port,
        pod_id=config.pod_id,
        ssh_key_path=str(ssh_key),
        last_updated=config_data["last_updated"]
    )


@router.post("/test", response_model=TestResponse)
async def test_connection():
    """Test SSH connection to RunPod."""
    config = _get_config()
    if not config:
        return TestResponse(connected=False, error="RunPod not configured")

    # Test basic connection with nvidia-smi (use async to not block event loop)
    success, output = await _ssh_command_async(config, "nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'No GPU'")

    if not success:
        return TestResponse(connected=False, error=output)

    gpu = output.strip() if output and output != "No GPU" else None

    # Check workspace exists
    ws_success, _ = await _ssh_command_async(config, "test -d /workspace && echo ok")

    return TestResponse(
        connected=True,
        gpu=gpu,
        workspace_available=ws_success
    )


# ============================================================================
# Upload & Processing Endpoints
# ============================================================================

@router.post("/upload", response_model=UploadResponse)
async def upload_to_pod(file: UploadFile = File(None), temp_id: str = None):
    """Upload PDF to RunPod's input folder for batch processing.

    Can upload either:
    - A new file (via file parameter)
    - An already-assessed file (via temp_id parameter)

    Uploads to /workspace/input/ for the multi-pod coordinator to pick up.
    Returns existing_extractions info so UI can warn about duplicates.
    """
    config = _get_config()
    if not config:
        raise HTTPException(status_code=400, detail="RunPod not configured")

    # Handle temp_id upload (file already assessed and in temp storage)
    if temp_id:
        # Find the temp file from processor's temp storage
        PROCESSOR_TEMP = DATA_DIR / "processor_temp"
        temp_pdf = PROCESSOR_TEMP / f"{temp_id}.pdf"

        if not temp_pdf.exists():
            raise HTTPException(status_code=404, detail=f"Temp file {temp_id} not found")

        # Get original filename from assessment info if available
        info_file = PROCESSOR_TEMP / f"{temp_id}.json"
        if info_file.exists():
            info = json.loads(info_file.read_text())
            filename = info.get("original_filename", f"{temp_id}.pdf")
        else:
            filename = f"{temp_id}.pdf"

        local_path = temp_pdf
        job_id = uuid.uuid4().hex[:8]

    elif file:
        # Handle direct file upload
        job_id = uuid.uuid4().hex[:8]
        filename = file.filename or "document.pdf"

        # Save locally first (needed for hash-based duplicate detection)
        UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        local_path = UPLOAD_TEMP_DIR / f"{job_id}_{filename}"

        with open(local_path, "wb") as f:
            content = await file.read()
            f.write(content)
    else:
        raise HTTPException(status_code=400, detail="Either file or temp_id required")

    # Check for existing extractions (duplicate detection with hash matching)
    existing = _check_existing_extractions(filename, str(local_path))
    existing_extractions = ExistingExtractions(
        folder_name=existing.get("folder_name"),
        folder_exists=existing.get("folder_exists", False),
        existing_methods=existing.get("existing_methods", []),
        document_id=existing.get("document_id"),
        annotation_count=existing.get("annotation_count", 0),
        match_type=existing.get("match_type"),
        matched_title=existing.get("matched_title")
    )

    # Upload to RunPod network volume input folder
    remote_path = f"/workspace/input/{filename}"

    # Ensure input directory exists
    _ssh_command(config, "mkdir -p /workspace/input")

    success, error = _scp_upload(config, local_path, remote_path)
    if not success:
        # Only delete if we created this file (not temp_id case)
        if not temp_id:
            local_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {error}")

    # NOTE: No DB record created here. Job tracking happens via /livestatus on pod.
    # DB record is only created when downloading completed output.

    return UploadResponse(
        job_id=job_id,
        filename=filename,
        status="uploaded",
        existing_extractions=existing_extractions
    )


# ============================================================================
# Job Status Endpoints
# ============================================================================

async def _discover_pod_jobs(config: dict, db) -> dict:
    """
    Discover jobs on the pod that aren't tracked locally.

    Checks:
    1. /workspace/status.json for coordinator status (written by coordinator.py)
    2. /workspace/input/ for queued PDFs
    3. /workspace/processing/ for lock files (active jobs)
    4. /workspace/output/*/ for completed outputs

    Returns dict with discovered info and any new jobs created.
    """
    discovered = {
        "status": None,
        "current_doc": None,
        "current_page": 0,
        "total_pages": 0,
        "queued_pdfs": [],
        "processing_pdfs": [],
        "completed_outputs": [],
        "new_jobs_created": 0,
        "ssh_errors": []
    }

    # Get existing tracked filenames and folder names to avoid duplicates
    cursor = await db.execute("SELECT filename, folder_name, status FROM runpod_jobs")
    rows = await cursor.fetchall()
    tracked_files = {row[0] for row in rows if row[0]}
    tracked_folders = {row[1] for row in rows if row[1]}
    # Also track Scholia-converted folder names (for matching already-downloaded jobs)
    tracked_scholia_folders = {_zotero_to_scholia_folder(row[1]) for row in rows if row[1]}
    # Track which folders are already finalized/downloaded (don't recreate jobs for these)
    finalized_folders = {row[1] for row in rows if row[1] and row[2] in ('downloaded', 'finalized')}

    # 1. Check status.json for coordinator status
    success, output = _ssh_command(config, "cat /workspace/status.json 2>/dev/null", timeout=45)
    if success and output:
        try:
            status_data = json.loads(output)
            discovered["status"] = "running" if status_data.get("pods") else None
            summary = status_data.get("summary", {})
            discovered["queued_count"] = summary.get("pending", 0)
            discovered["processing_count"] = summary.get("processing", 0)
            discovered["completed_count"] = summary.get("completed", 0)
        except json.JSONDecodeError:
            pass

    # 2. List PDFs in input folder (handle filenames with spaces)
    success, output = _ssh_command(config, "for f in /workspace/input/*.pdf; do [ -f \"$f\" ] && basename \"$f\"; done 2>/dev/null", timeout=45)
    if success and output:
        discovered["queued_pdfs"] = [f.strip() for f in output.strip().split('\n') if f.strip() and f.strip() != '*.pdf']
    elif not success:
        discovered["ssh_errors"].append(f"input: {output}")

    # 3. List lock files (currently processing)
    # Lock files indicate a job is still in progress - used to filter out incomplete outputs
    lock_files = set()
    success, output = _ssh_command(config, "for f in /workspace/processing/*.lock; do [ -f \"$f\" ] && basename \"$f\"; done 2>/dev/null", timeout=45)
    if success and output:
        for f in output.strip().split('\n'):
            f = f.strip()
            if f and f != '*.lock':
                # Store the base name (without .lock) for matching against output folders
                lock_files.add(f.replace('.lock', ''))
                discovered["processing_pdfs"].append(f.replace('.lock', '.pdf'))

    # 4. List completed output folders (handle folder names with spaces)
    # IMPORTANT: Only consider a folder "completed" if there's NO corresponding lock file
    success, output = _ssh_command(config, "for d in /workspace/output/*/; do [ -d \"$d\" ] && basename \"$d\"; done 2>/dev/null", timeout=45)
    if success and output:
        for folder in output.strip().split('\n'):
            folder = folder.strip()
            if folder and folder != '*':
                # Check if this folder has a lock file (still processing)
                if folder in lock_files:
                    # Still processing - don't mark as complete
                    continue
                discovered["completed_outputs"].append(folder)
    elif not success:
        discovered["ssh_errors"].append(f"output: {output}")

    # Create job records for untracked items
    now = datetime.now().isoformat()

    # For currently processing doc - create as 'processing'
    if discovered["current_doc"] and discovered["current_doc"] not in tracked_files:
        job_id = uuid.uuid4().hex[:8]
        await db.execute("""
            INSERT INTO runpod_jobs (job_id, filename, status, current_page, total_pages,
                                     created_at, started_at)
            VALUES (?, ?, 'processing', ?, ?, ?, ?)
        """, (job_id, discovered["current_doc"], discovered["current_page"],
              discovered["total_pages"], now, now))
        tracked_files.add(discovered["current_doc"])
        discovered["new_jobs_created"] += 1

    # For queued PDFs - create as 'uploaded' (waiting to process)
    for pdf in discovered["queued_pdfs"]:
        if pdf not in tracked_files and pdf != discovered["current_doc"]:
            job_id = uuid.uuid4().hex[:8]
            await db.execute("""
                INSERT INTO runpod_jobs (job_id, filename, status, created_at)
                VALUES (?, ?, 'uploaded', ?)
            """, (job_id, pdf, now))
            tracked_files.add(pdf)
            discovered["new_jobs_created"] += 1

    # For completed outputs - create job if not already tracked by folder name
    for folder in discovered["completed_outputs"]:
        # Skip if already tracking this folder (check both Zotero and Scholia formats)
        scholia_folder = _zotero_to_scholia_folder(folder)
        if folder in tracked_folders or scholia_folder in tracked_scholia_folders:
            continue
        # Also skip if this folder was already downloaded/finalized
        if folder in finalized_folders or scholia_folder in finalized_folders:
            continue

        # Try to match to an existing tracked PDF
        matching_pdf = None
        for pdf in tracked_files:
            pdf_stem = Path(pdf).stem
            # Check if folder name contains key parts of pdf name
            normalized_pdf = pdf_stem.replace(' ', '_').replace('-', '_').lower()
            normalized_folder = folder.lower()
            # Match if first 15 chars match or significant overlap
            if normalized_pdf[:15] in normalized_folder or normalized_folder[:15] in normalized_pdf:
                matching_pdf = pdf
                break

        if matching_pdf:
            # Update existing job to complete_on_pod
            await db.execute("""
                UPDATE runpod_jobs
                SET status = 'complete_on_pod', folder_name = ?, completed_at = ?
                WHERE filename = ? AND status IN ('uploaded', 'processing')
            """, (folder, now, matching_pdf))
        else:
            # Create new job for untracked completed output
            # Use folder name as filename since we don't know the original PDF name
            job_id = uuid.uuid4().hex[:8]
            await db.execute("""
                INSERT INTO runpod_jobs (job_id, filename, status, folder_name, created_at, completed_at)
                VALUES (?, ?, 'complete_on_pod', ?, ?, ?)
            """, (job_id, f"{folder}.pdf", folder, now, now))
            tracked_folders.add(folder)
            discovered["new_jobs_created"] += 1

    if discovered["new_jobs_created"] > 0:
        await db.commit()

    return discovered


@router.get("/livestatus")
async def get_livestatus():
    """
    Get live status from the pod in a single SSH call.

    This is the FAST endpoint - reads /workspace/livestatus.json which is
    continuously updated by the livestatus_watcher.py process on the pod.

    Returns real-time progress of all jobs without multiple SSH round-trips.
    """
    config = _get_config()
    if not config:
        raise HTTPException(status_code=400, detail="RunPod not configured")

    # Single SSH call to read the livestatus file (async to not block event loop)
    success, output = await _ssh_command_async(config, "cat /workspace/livestatus.json 2>/dev/null", timeout=15)

    if not success:
        return {
            "status": "error",
            "error": f"Failed to read livestatus: {output}",
            "fallback": "Use /sync for full discovery (slower)"
        }

    if not output.strip():
        return {
            "status": "no_data",
            "error": "livestatus.json not found - run livestatus_watcher.py on the pod",
            "fallback": "Use /sync for full discovery (slower)"
        }

    try:
        livestatus = json.loads(output)
        livestatus["status"] = "ok"
        livestatus["source"] = "livestatus.json"
        return livestatus
    except json.JSONDecodeError as e:
        return {
            "status": "error",
            "error": f"Invalid JSON in livestatus.json: {e}",
            "raw_output": output[:500]
        }


@router.post("/sync")
async def sync_pod_jobs():
    """
    Discover and sync jobs from the pod (SLOW - multiple SSH calls).

    This makes multiple SSH calls to discover jobs. Use /livestatus for
    fast real-time status instead.

    Call this to find jobs that were started outside the UI
    (e.g., batch processing started via SSH).
    """
    config = _get_config()
    if not config:
        raise HTTPException(status_code=400, detail="RunPod not configured")

    db = await get_db()
    discovered = await _discover_pod_jobs(config, db)

    return {
        "status": "synced",
        "pod_status": discovered["status"],
        "current_doc": discovered["current_doc"],
        "current_page": discovered["current_page"],
        "total_pages": discovered["total_pages"],
        "queued_on_pod": len(discovered["queued_pdfs"]),
        "queued_pdfs": discovered["queued_pdfs"][:10],  # First 10 for debug
        "completed_on_pod": len(discovered["completed_outputs"]),
        "completed_outputs": discovered["completed_outputs"][:10],  # First 10 for debug
        "new_jobs_created": discovered["new_jobs_created"],
        "ssh_errors": discovered["ssh_errors"] if discovered["ssh_errors"] else None
    }


@router.get("/jobs", response_model=JobsResponse)
async def list_jobs():
    """List all RunPod jobs with their statuses.

    Returns jobs from local database only (fast).
    Use POST /runpod/sync to discover jobs from the pod.
    """
    db = await get_db()

    # Get jobs from database (including any just discovered)
    cursor = await db.execute("""
        SELECT job_id, filename, status, current_page, total_pages, folder_name,
               error, created_at, started_at, completed_at, downloaded_at, finalized_at
        FROM runpod_jobs
        ORDER BY created_at DESC
    """)
    rows = await cursor.fetchall()

    jobs = []
    for row in rows:
        job = JobInfo(
            job_id=row[0],
            filename=row[1],
            status=row[2],
            current_page=row[3] or 0,
            total_pages=row[4] or 0,
            folder_name=row[5],
            error=row[6],
            created_at=row[7],
            started_at=row[8],
            completed_at=row[9],
            downloaded_at=row[10],
            finalized_at=row[11]
        )
        jobs.append(job)

    return JobsResponse(
        jobs=jobs,
        pod_status=None,
        last_poll=datetime.now().isoformat()
    )


@router.get("/jobs/{job_id}", response_model=JobInfo)
async def get_job(job_id: str):
    """Get status of a specific job."""
    db = await get_db()

    cursor = await db.execute("""
        SELECT job_id, filename, status, current_page, total_pages, folder_name,
               error, created_at, started_at, completed_at, downloaded_at, finalized_at
        FROM runpod_jobs WHERE job_id = ?
    """, (job_id,))
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobInfo(
        job_id=row[0],
        filename=row[1],
        status=row[2],
        current_page=row[3] or 0,
        total_pages=row[4] or 0,
        folder_name=row[5],
        error=row[6],
        created_at=row[7],
        started_at=row[8],
        completed_at=row[9],
        downloaded_at=row[10],
        finalized_at=row[11]
    )


# ============================================================================
# Download Endpoint
# ============================================================================

class DownloadRequest(BaseModel):
    """Request to download a completed job from RunPod."""
    folder_name: str  # Folder name from /livestatus completed list


@router.post("/download", response_model=DownloadResponse)
async def download_job(request: DownloadRequest):
    """
    Download completed job from RunPod, convert to Scholia format, and auto-finalize.

    v4 Flow (files stay in /output/ until downloaded):
    1. Verify folder exists in /output/ with _complete.json marker
    2. Move output folder + PDF to /downloaded/ (intermediate state)
    3. Download output folder via tar.gz + SCP from /downloaded/
    4. Download source PDF from /downloaded/
    5. Extract to staging area
    6. Create DB record with status 'downloaded'
    7. Auto-trigger finalize_document()
    8. If finalize succeeds → update to 'finalized', move to /archived/ on RunPod
    9. If finalize fails → stays 'downloaded', files stay in /downloaded/ for retry
    10. Clean up staging files

    The folder_name comes from /livestatus endpoint's ready_to_download list.
    """
    config = _get_config()
    if not config:
        raise HTTPException(status_code=400, detail="RunPod not configured")

    remote_folder_name = request.folder_name
    job_id = uuid.uuid4().hex[:8]  # Generate new job_id for tracking

    # Escape special characters for shell commands (apostrophes, etc.)
    def shell_escape(s: str) -> str:
        """Escape string for use in shell single quotes."""
        return s.replace("'", "'\\''")

    escaped_folder = shell_escape(remote_folder_name)

    # =========================================================================
    # Step 0: Check /output/ for folder with _complete.json marker
    # =========================================================================
    # v4: Completed jobs have _complete.json in /output/, files stay there until downloaded
    source_dir = None
    complete_data = None

    # Check /output/ for completed job (has _complete.json)
    test_cmd = f"test -f '/workspace/output/{escaped_folder}/_complete.json' && cat '/workspace/output/{escaped_folder}/_complete.json'"
    print(f"[download] Checking for _complete.json: {remote_folder_name}")
    success, result = await _ssh_command_async(config, test_cmd, timeout=30)

    if success and result.strip():
        source_dir = "/workspace/output"
        try:
            complete_data = json.loads(result.strip())
            print(f"[download] Found completed job in /output/: {remote_folder_name}")
            print(f"[download] Completion info: {complete_data.get('total_pages')} pages, completed at {complete_data.get('completed_at')}")
        except json.JSONDecodeError:
            print(f"[download] Warning: Could not parse _complete.json, continuing anyway")
    else:
        # Fall back: check /archive/ (for legacy v3 jobs)
        success, check = await _ssh_command_async(
            config,
            f"test -d '/workspace/archive/{escaped_folder}' && echo 'exists'",
            timeout=30
        )
        if success and 'exists' in check:
            source_dir = "/workspace/archive"
            print(f"[download] Found folder in /archive/ (legacy): {remote_folder_name}")

    if not source_dir:
        return DownloadResponse(status="error", job_id=job_id, error=f"Completed folder not found: {remote_folder_name}")

    # =========================================================================
    # Step 1: Move to /downloaded/ (intermediate state)
    # =========================================================================
    print(f"[download] Moving to /downloaded/ (intermediate)...")
    await _ssh_command_async(config, "mkdir -p /workspace/downloaded")

    # Find source PDF - location depends on source_dir
    pdf_filename = None
    pdf_location = None

    if complete_data and complete_data.get("source_pdf"):
        pdf_filename = complete_data["source_pdf"]
        pdf_location = "/workspace/input"  # v4 flow: PDF stays in /input/
    else:
        # Search for matching PDF
        folder_search = shell_escape(remote_folder_name[:30])

        # For legacy /archive/ jobs, PDF is co-located with output
        if source_dir == "/workspace/archive":
            success, found = await _ssh_command_async(
                config,
                f"ls -1 '{source_dir}/'*.pdf 2>/dev/null | while read f; do basename \"$f\"; done | grep -i '{folder_search}' | head -1",
                timeout=15
            )
            if success and found.strip():
                pdf_filename = found.strip()
                pdf_location = source_dir
                print(f"[download] Found PDF in {source_dir} (legacy): {pdf_filename}")

        # Also check /input/ (v4 flow or fallback)
        if not pdf_filename:
            success, found = await _ssh_command_async(
                config,
                f"ls -1 /workspace/input/*.pdf 2>/dev/null | while read f; do basename \"$f\"; done | grep -i '{folder_search}' | head -1",
                timeout=15
            )
            if success and found.strip():
                pdf_filename = found.strip()
                pdf_location = "/workspace/input"

    # Move PDF to /downloaded/
    if pdf_filename and pdf_location:
        escaped_pdf = shell_escape(pdf_filename)
        await _ssh_command_async(config, f"mv '{pdf_location}/{escaped_pdf}' /workspace/downloaded/ 2>/dev/null")
        print(f"[download] Moved PDF from {pdf_location} to /downloaded/: {pdf_filename}")

    # Move output folder to /downloaded/
    await _ssh_command_async(config, f"mv '{source_dir}/{escaped_folder}' /workspace/downloaded/")
    print(f"[download] Moved output folder to /downloaded/: {remote_folder_name}")

    # Update source_dir to /downloaded/ for the rest of the process
    source_dir = "/workspace/downloaded"

    print(f"[download] Downloading from {source_dir}: {remote_folder_name}")

    # =========================================================================
    # Step 1: Download output folder (tar.gz)
    # =========================================================================
    archive_name = f"{job_id}.tar.gz"
    tar_cmd = f"cd {source_dir} && tar -czf '{archive_name}' '{escaped_folder}'"
    tar_success, tar_error = await _ssh_command_async(config, tar_cmd, timeout=300)

    if not tar_success:
        return DownloadResponse(status="error", job_id=job_id, error=f"Failed to create archive: {tar_error}")

    local_archive = DATA_DIR / "runpod_downloads" / archive_name
    local_archive.parent.mkdir(parents=True, exist_ok=True)

    dl_success, dl_error = _scp_download(config, f"{source_dir}/{archive_name}", local_archive, timeout=600)

    if not dl_success:
        return DownloadResponse(status="error", job_id=job_id, error=f"Download failed: {dl_error}")

    # =========================================================================
    # Step 2: Download source PDF from /downloaded/
    # =========================================================================
    # v4: PDF was already moved to /downloaded/ in Step 1
    local_pdf_temp = None

    if pdf_filename:
        local_pdf_temp = DATA_DIR / "runpod_downloads" / pdf_filename
        escaped_pdf = shell_escape(pdf_filename)
        print(f"[download] Downloading PDF from /downloaded/: {pdf_filename}")
        pdf_success, _ = _scp_download(config, f"/workspace/downloaded/{escaped_pdf}", local_pdf_temp)
        if not pdf_success:
            print(f"[download] Warning: Could not download PDF {pdf_filename}")
            local_pdf_temp = None
    else:
        print(f"[download] Warning: No source PDF found for {remote_folder_name}")
        # Continue anyway - figure cropping will be skipped

    # =========================================================================
    # Step 3: Extract tarball to staging area
    # =========================================================================
    temp_extract = DATA_DIR / "runpod_downloads" / f"extract_{job_id}"
    temp_extract.mkdir(parents=True, exist_ok=True)

    import tarfile
    with tarfile.open(local_archive, 'r:gz') as tf:
        tf.extractall(temp_extract)

    # Find the extracted folder
    extracted_folders = [f for f in temp_extract.iterdir() if f.is_dir()]
    if not extracted_folders:
        return DownloadResponse(status="error", job_id=job_id, error="No folder found in downloaded archive")

    staging_folder = extracted_folders[0]

    # =========================================================================
    # Step 4: Create DB record as 'downloaded'
    # =========================================================================
    db = await get_db()
    await db.execute("""
        INSERT INTO runpod_jobs (job_id, filename, folder_name, status, downloaded_at, created_at)
        VALUES (?, ?, ?, 'downloaded', datetime('now'), datetime('now'))
    """, (job_id, pdf_filename or f"{remote_folder_name}.pdf", remote_folder_name))
    await db.commit()

    # =========================================================================
    # Step 5: Auto-finalize using shared module
    # =========================================================================
    print(f"[download] Auto-finalizing document...")
    finalize_error = None
    scholia_folder_name = None
    doc_folder = None
    page_count = 0

    try:
        result = finalize_document(
            staging_folder=staging_folder,
            documents_dir=DOCUMENTS_DIR,
            source_pdf=local_pdf_temp if local_pdf_temp and local_pdf_temp.exists() else None,
            original_name=remote_folder_name
        )

        if result.get("error"):
            finalize_error = result["error"]
        else:
            scholia_folder_name = result["folder_name"]
            doc_folder = result["doc_folder"]
            page_count = result["page_count"]
            char_count = result["char_count"]
            figure_count = result["figure_count"]
            print(f"[download] Finalized: {scholia_folder_name} ({page_count} pages, {char_count} chars, {figure_count} figures)")
    except Exception as e:
        finalize_error = str(e)
        print(f"[download] Finalization failed: {finalize_error}")

    # =========================================================================
    # Step 6: Update DB based on finalization result
    # =========================================================================
    if finalize_error:
        # Keep as 'downloaded' with error - can retry finalize later
        await db.execute("""
            UPDATE runpod_jobs
            SET error = ?, updated_at = datetime('now')
            WHERE job_id = ?
        """, (finalize_error, job_id))
        await db.commit()

        # Still clean up staging but keep archive for retry
        shutil.rmtree(temp_extract, ignore_errors=True)

        return DownloadResponse(
            status="downloaded",
            job_id=job_id,
            error=f"Downloaded but finalization failed: {finalize_error}. Use /finalize to retry."
        )
    else:
        # Success - update to 'finalized'
        await db.execute("""
            UPDATE runpod_jobs
            SET status = 'finalized', folder_name = ?, local_output_path = ?,
                total_pages = ?, finalized_at = datetime('now'), updated_at = datetime('now')
            WHERE job_id = ?
        """, (scholia_folder_name, str(doc_folder), page_count, job_id))
        await db.commit()

    # =========================================================================
    # Step 7: Cleanup and archive on success
    # =========================================================================
    # Clean up local staging files
    shutil.rmtree(temp_extract, ignore_errors=True)
    local_archive.unlink(missing_ok=True)
    if local_pdf_temp and local_pdf_temp.exists():
        local_pdf_temp.unlink(missing_ok=True)

    # Clean up remote tar.gz
    await _ssh_command_async(config, f"rm -f '{source_dir}/{archive_name}'")

    # v4: Move from /downloaded/ to /archived/ ONLY after successful finalization
    # This is the final resting place on the RunPod volume
    await _ssh_command_async(config, "mkdir -p /workspace/archived")

    # Move PDF to /archived/
    if pdf_filename:
        escaped_pdf = shell_escape(pdf_filename)
        await _ssh_command_async(config, f"mv '/workspace/downloaded/{escaped_pdf}' /workspace/archived/ 2>/dev/null")

    # Move output folder to /archived/
    await _ssh_command_async(config, f"mv '/workspace/downloaded/{escaped_folder}' /workspace/archived/ 2>/dev/null")

    print(f"[download] Finalization successful! Moved {remote_folder_name} to /workspace/archived/")

    return DownloadResponse(
        status="finalized",
        job_id=job_id,
        local_path=str(doc_folder) if doc_folder else None,
        page_count=page_count
    )


# ============================================================================
# Streaming Download Endpoint (SSE for detailed progress)
# ============================================================================

@router.get("/download-stream/{folder_name:path}")
async def download_job_stream(folder_name: str):
    """
    Stream download progress via Server-Sent Events.

    Sends events for each step:
    - step: Current step name
    - progress: Percentage (0-100)
    - detail: Additional info
    - status: 'progress', 'complete', or 'error'
    """
    config = _get_config()
    if not config:
        async def error_gen():
            yield f"data: {json.dumps({'status': 'error', 'error': 'RunPod not configured'})}\n\n"
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    async def progress_generator():
        """Generate SSE events for download progress."""
        remote_folder_name = folder_name
        job_id = uuid.uuid4().hex[:8]

        def send_event(step: str, progress: int, detail: str = "", status: str = "progress"):
            return f"data: {json.dumps({'step': step, 'progress': progress, 'detail': detail, 'status': status, 'job_id': job_id})}\n\n"

        def shell_escape(s: str) -> str:
            return s.replace("'", "'\\''")

        escaped_folder = shell_escape(remote_folder_name)

        try:
            # Step 1: Check for completed job (5%)
            yield send_event("Checking job status", 5, f"Looking for {remote_folder_name}")
            await asyncio.sleep(0.1)

            test_cmd = f"test -f '/workspace/output/{escaped_folder}/_complete.json' && cat '/workspace/output/{escaped_folder}/_complete.json'"
            success, result = await _ssh_command_async(config, test_cmd, timeout=30)

            source_dir = None
            complete_data = None
            pdf_filename = None
            pdf_location = None

            if success and result.strip():
                source_dir = "/workspace/output"
                try:
                    complete_data = json.loads(result.strip())
                except json.JSONDecodeError:
                    pass
            else:
                # Fall back to /archive/
                success, check = await _ssh_command_async(config, f"test -d '/workspace/archive/{escaped_folder}' && echo 'exists'", timeout=30)
                if success and 'exists' in check:
                    source_dir = "/workspace/archive"

            if not source_dir:
                yield send_event("Error", 0, f"Folder not found: {remote_folder_name}", "error")
                return

            # Step 2: Move to /downloaded/ (10%)
            yield send_event("Preparing download", 10, "Moving to intermediate folder")
            await asyncio.sleep(0.1)

            await _ssh_command_async(config, "mkdir -p /workspace/downloaded")

            # Find PDF
            if complete_data and complete_data.get("source_pdf"):
                pdf_filename = complete_data["source_pdf"]
                pdf_location = "/workspace/input"
            else:
                folder_search = shell_escape(remote_folder_name[:30])
                if source_dir == "/workspace/archive":
                    success, found = await _ssh_command_async(config, f"ls -1 '{source_dir}/'*.pdf 2>/dev/null | while read f; do basename \"$f\"; done | grep -i '{folder_search}' | head -1", timeout=15)
                    if success and found.strip():
                        pdf_filename = found.strip()
                        pdf_location = source_dir

                if not pdf_filename:
                    success, found = await _ssh_command_async(config, f"ls -1 /workspace/input/*.pdf 2>/dev/null | while read f; do basename \"$f\"; done | grep -i '{folder_search}' | head -1", timeout=15)
                    if success and found.strip():
                        pdf_filename = found.strip()
                        pdf_location = "/workspace/input"

            # Move files
            if pdf_filename and pdf_location:
                escaped_pdf = shell_escape(pdf_filename)
                await _ssh_command_async(config, f"mv '{pdf_location}/{escaped_pdf}' /workspace/downloaded/ 2>/dev/null")

            await _ssh_command_async(config, f"mv '{source_dir}/{escaped_folder}' /workspace/downloaded/")
            source_dir = "/workspace/downloaded"

            # Step 3: Create archive (20%)
            yield send_event("Creating archive", 20, "Compressing files on pod")
            await asyncio.sleep(0.1)

            archive_name = f"{job_id}.tar.gz"
            tar_cmd = f"cd {source_dir} && tar -czf '{archive_name}' '{escaped_folder}'"
            tar_success, tar_error = await _ssh_command_async(config, tar_cmd, timeout=300)

            if not tar_success:
                yield send_event("Error", 0, f"Failed to create archive: {tar_error}", "error")
                return

            # Step 4: Download archive (40%)
            yield send_event("Downloading", 40, "Transferring from pod to local")

            local_archive = DATA_DIR / "runpod_downloads" / archive_name
            local_archive.parent.mkdir(parents=True, exist_ok=True)

            dl_success, dl_error = _scp_download(config, f"{source_dir}/{archive_name}", local_archive, timeout=600)

            if not dl_success:
                yield send_event("Error", 0, f"Download failed: {dl_error}", "error")
                return

            # Step 5: Download PDF (55%)
            yield send_event("Downloading PDF", 55, f"Getting {pdf_filename or 'source PDF'}")

            local_pdf_temp = None
            if pdf_filename:
                local_pdf_temp = DATA_DIR / "runpod_downloads" / pdf_filename
                escaped_pdf = shell_escape(pdf_filename)
                pdf_success, _ = _scp_download(config, f"/workspace/downloaded/{escaped_pdf}", local_pdf_temp)
                if not pdf_success:
                    local_pdf_temp = None

            # Step 6: Extract (65%)
            yield send_event("Extracting", 65, "Unpacking archive")
            await asyncio.sleep(0.1)

            temp_extract = DATA_DIR / "runpod_downloads" / f"extract_{job_id}"
            temp_extract.mkdir(parents=True, exist_ok=True)

            import tarfile
            with tarfile.open(local_archive, 'r:gz') as tf:
                tf.extractall(temp_extract)

            extracted_folders = [f for f in temp_extract.iterdir() if f.is_dir()]
            if not extracted_folders:
                yield send_event("Error", 0, "No folder found in archive", "error")
                return

            staging_folder = extracted_folders[0]

            # Step 7: Finalize (80%)
            yield send_event("Finalizing", 80, "Processing pages and figures")
            await asyncio.sleep(0.1)

            from services.finalize_document import finalize_document

            result = finalize_document(
                staging_folder=staging_folder,
                documents_dir=DOCUMENTS_DIR,
                source_pdf=local_pdf_temp if local_pdf_temp and local_pdf_temp.exists() else None,
                original_name=remote_folder_name
            )

            if result.get("error"):
                yield send_event("Error", 0, f"Finalization failed: {result['error']}", "error")
                return

            scholia_folder_name = result["folder_name"]
            doc_folder = result["doc_folder"]
            page_count = result["page_count"]

            # Step 8: Cleanup (95%)
            yield send_event("Cleaning up", 95, "Archiving on pod")
            await asyncio.sleep(0.1)

            # Cleanup local
            shutil.rmtree(temp_extract, ignore_errors=True)
            local_archive.unlink(missing_ok=True)
            if local_pdf_temp and local_pdf_temp.exists():
                local_pdf_temp.unlink(missing_ok=True)

            # Cleanup remote
            await _ssh_command_async(config, f"rm -f '{source_dir}/{archive_name}'")

            # Move to /archived/
            await _ssh_command_async(config, "mkdir -p /workspace/archived")
            if pdf_filename:
                escaped_pdf = shell_escape(pdf_filename)
                await _ssh_command_async(config, f"mv '/workspace/downloaded/{escaped_pdf}' /workspace/archived/ 2>/dev/null")
            await _ssh_command_async(config, f"mv '/workspace/downloaded/{escaped_folder}' /workspace/archived/ 2>/dev/null")

            # Step 9: Complete (100%)
            yield send_event("Complete", 100, f"{page_count} pages finalized to {scholia_folder_name}", "complete")

        except Exception as e:
            yield send_event("Error", 0, str(e), "error")

    return StreamingResponse(
        progress_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ============================================================================
# Finalize Endpoint (for re-processing already downloaded jobs)
# ============================================================================

class FinalizeRequest(BaseModel):
    """Request to finalize specific jobs."""
    job_ids: Optional[list[str]] = None  # If None, finalize all 'downloaded' jobs


@router.post("/finalize", response_model=FinalizeResponse)
async def finalize_jobs(request: FinalizeRequest = None):
    """
    Re-run finalization on downloaded jobs.

    Use this to:
    1. Retry failed finalization (jobs stuck in 'downloaded' status with error)
    2. Re-process already finalized jobs (e.g., after fixing finalize_document)

    Uses shared rebuild_extracted() and crop_figures() from services module.
    """
    from services.rebuild_extracted import rebuild_extracted, crop_figures

    db = await get_db()
    job_ids = request.job_ids if request else None

    # Get jobs to finalize (both 'downloaded' and 'finalized' can be re-processed)
    if job_ids:
        placeholders = ",".join("?" * len(job_ids))
        cursor = await db.execute(f"""
            SELECT job_id, folder_name, local_output_path, error
            FROM runpod_jobs
            WHERE job_id IN ({placeholders}) AND status IN ('downloaded', 'finalized')
        """, job_ids)
    else:
        cursor = await db.execute("""
            SELECT job_id, folder_name, local_output_path, error
            FROM runpod_jobs
            WHERE status IN ('downloaded', 'finalized')
        """)

    rows = await cursor.fetchall()

    if not rows:
        return FinalizeResponse(finalized=[], errors=["No downloaded jobs to finalize"])

    finalized = []
    errors = []

    for row in rows:
        job_id, folder_name, local_output_path, prev_error = row
        try:
            # For jobs that failed during initial finalization, local_output_path might not be set
            if not local_output_path:
                errors.append(f"{job_id}: No local_output_path - job may need re-download")
                continue

            doc_folder = Path(local_output_path)
            if not doc_folder.exists():
                errors.append(f"{job_id}: Document folder not found: {doc_folder}")
                continue

            method_folder = doc_folder / f"{folder_name}--dots-ocr"
            pdf_path = doc_folder / f"{folder_name}.pdf"

            if not method_folder.exists():
                errors.append(f"{job_id}: Method folder not found: {method_folder}")
                continue

            # Rebuild extracted.txt using shared module (reads JSON, not MD!)
            content = rebuild_extracted(doc_folder, method='dots-ocr')
            output_path = method_folder / f"{folder_name}--dots-ocr--extracted.txt"
            output_path.write_text(content, encoding='utf-8')
            char_count = len(content)

            # Crop figures if PDF exists
            figures = 0
            if pdf_path.exists():
                figures = crop_figures(doc_folder, method='dots-ocr')

            # Update job status - clear error, set finalized
            await db.execute("""
                UPDATE runpod_jobs
                SET status = 'finalized', error = NULL,
                    finalized_at = datetime('now'), updated_at = datetime('now')
                WHERE job_id = ?
            """, (job_id,))

            finalized.append(FinalizeResult(
                job_id=job_id,
                folder_name=folder_name or "",
                chars_extracted=char_count,
                figures_cropped=figures
            ))

        except Exception as e:
            errors.append(f"{job_id}: {str(e)}")
            finalized.append(FinalizeResult(
                job_id=job_id,
                folder_name=folder_name or "",
                error=str(e)
            ))

    await db.commit()

    return FinalizeResponse(finalized=finalized, errors=errors)


# ============================================================================
# Cleanup Endpoints
# ============================================================================

@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job record (does not delete files)."""
    db = await get_db()

    cursor = await db.execute("DELETE FROM runpod_jobs WHERE job_id = ?", (job_id,))
    await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"status": "deleted", "job_id": job_id}


@router.delete("/jobs")
async def delete_all_jobs(status: Optional[str] = None):
    """
    Delete job records from database.

    - If status is provided, only delete jobs with that status
    - If status is None, delete ALL jobs (use with caution)

    Does not delete any files - only database records.
    """
    db = await get_db()

    if status:
        cursor = await db.execute("DELETE FROM runpod_jobs WHERE status = ?", (status,))
    else:
        cursor = await db.execute("DELETE FROM runpod_jobs")

    deleted_count = cursor.rowcount
    await db.commit()

    return {
        "status": "deleted",
        "count": deleted_count,
        "filter": status or "all"
    }


class ManualJobCreate(BaseModel):
    filename: str
    status: str = "processing"  # processing, uploaded, complete_on_pod
    folder_name: Optional[str] = None
    total_pages: int = 0


@router.post("/jobs/manual")
async def create_manual_job(job: ManualJobCreate):
    """
    Manually create a job record for tracking.

    Use this when SSH is unresponsive but you know what's processing.
    """
    db = await get_db()
    job_id = uuid.uuid4().hex[:8]
    now = datetime.now().isoformat()

    await db.execute("""
        INSERT INTO runpod_jobs (job_id, filename, status, folder_name, total_pages, created_at, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (job_id, job.filename, job.status, job.folder_name, job.total_pages, now, now))
    await db.commit()

    return {
        "status": "created",
        "job_id": job_id,
        "filename": job.filename
    }


@router.get("/jobs/local")
async def list_local_jobs():
    """
    List jobs from local database only - no SSH sync.

    Use this when SSH is unresponsive due to heavy processing.
    """
    db = await get_db()

    cursor = await db.execute("""
        SELECT job_id, filename, status, current_page, total_pages, folder_name,
               error, created_at, started_at, completed_at, downloaded_at, finalized_at
        FROM runpod_jobs
        ORDER BY created_at DESC
    """)
    rows = await cursor.fetchall()

    jobs = []
    for row in rows:
        jobs.append(JobInfo(
            job_id=row[0],
            filename=row[1],
            status=row[2],
            current_page=row[3] or 0,
            total_pages=row[4] or 0,
            folder_name=row[5],
            error=row[6],
            created_at=row[7],
            started_at=row[8],
            completed_at=row[9],
            downloaded_at=row[10],
            finalized_at=row[11]
        ))

    return JobsResponse(
        jobs=jobs,
        pod_status=None,
        last_poll=datetime.now().isoformat()
    )


# ============================================================================
# Multi-Pod Pipeline Models
# ============================================================================

class PodLaunchRequest(BaseModel):
    """Request to launch multiple pods."""
    count: int = 1
    gpu_type: str = "NVIDIA GeForce RTX 4090"
    network_volume_id: Optional[str] = None  # Uses default if not provided
    image: str = "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04"


class PodInfo(BaseModel):
    """Information about a running pod."""
    pod_id: str
    name: str
    status: str
    gpu_type: Optional[str] = None
    ssh_host: Optional[str] = None
    ssh_port: Optional[int] = None
    created_at: Optional[str] = None


class PodLaunchResponse(BaseModel):
    """Response from pod launch."""
    launched: int
    pods: list[PodInfo]
    errors: list[str]


class VolumeInfo(BaseModel):
    """Network volume information."""
    volume_id: str
    name: str
    size_gb: int
    datacenter: str
    used_gb: Optional[float] = None


class VolumeStatusResponse(BaseModel):
    """Status of files on the network volume."""
    volume: Optional[VolumeInfo] = None
    input_files: list[str]
    processing_files: list[str]
    output_folders: list[str]
    error: Optional[str] = None


class ApiConfigRequest(BaseModel):
    """Request to save API configuration."""
    network_volume_id: str
    # API key is read from environment, not passed in request


class ApiConfigResponse(BaseModel):
    """API configuration response."""
    configured: bool
    has_api_key: bool
    network_volume_id: Optional[str] = None
    volume_info: Optional[VolumeInfo] = None
    error: Optional[str] = None


# ============================================================================
# API Configuration Endpoints
# ============================================================================

def _get_api_config() -> Optional[dict]:
    """Load API config (volume ID, etc.) from JSON file."""
    api_config_file = DATA_DIR / "runpod_api_config.json"
    if api_config_file.exists():
        return json.loads(api_config_file.read_text())
    return None


def _save_api_config(config: dict):
    """Save API config to JSON file."""
    api_config_file = DATA_DIR / "runpod_api_config.json"
    api_config_file.parent.mkdir(parents=True, exist_ok=True)
    config["last_updated"] = datetime.now().isoformat()
    api_config_file.write_text(json.dumps(config, indent=2))


@router.get("/api-config", response_model=ApiConfigResponse)
async def get_api_config():
    """Get current API configuration (volume ID, API key status)."""
    import os

    config = _get_api_config()
    has_api_key = bool(os.getenv("RUNPOD_API_KEY"))

    if not config:
        return ApiConfigResponse(
            configured=False,
            has_api_key=has_api_key
        )

    # Try to get volume info if API key is available
    volume_info = None
    if has_api_key and config.get("network_volume_id"):
        try:
            client = get_runpod_client()
            vol = await client.get_volume(config["network_volume_id"])
            if vol:
                volume_info = VolumeInfo(
                    volume_id=vol.get("id", ""),
                    name=vol.get("name", ""),
                    size_gb=vol.get("size", 0),
                    datacenter=vol.get("dataCenterId", "")
                )
        except Exception:
            pass

    return ApiConfigResponse(
        configured=True,
        has_api_key=has_api_key,
        network_volume_id=config.get("network_volume_id"),
        volume_info=volume_info
    )


@router.post("/api-config", response_model=ApiConfigResponse)
async def save_api_config(config: ApiConfigRequest):
    """Save API configuration (volume ID)."""
    import os

    has_api_key = bool(os.getenv("RUNPOD_API_KEY"))
    if not has_api_key:
        return ApiConfigResponse(
            configured=False,
            has_api_key=False,
            error="RUNPOD_API_KEY not found in environment"
        )

    # Validate volume exists
    try:
        client = get_runpod_client()
        vol = await client.get_volume(config.network_volume_id)
        if not vol:
            return ApiConfigResponse(
                configured=False,
                has_api_key=True,
                error=f"Volume {config.network_volume_id} not found"
            )

        volume_info = VolumeInfo(
            volume_id=vol.get("id", ""),
            name=vol.get("name", ""),
            size_gb=vol.get("size", 0),
            datacenter=vol.get("dataCenterId", "")
        )
    except Exception as e:
        return ApiConfigResponse(
            configured=False,
            has_api_key=True,
            error=f"Failed to validate volume: {str(e)}"
        )

    # Save config
    _save_api_config({"network_volume_id": config.network_volume_id})

    return ApiConfigResponse(
        configured=True,
        has_api_key=True,
        network_volume_id=config.network_volume_id,
        volume_info=volume_info
    )


@router.post("/api-test")
async def test_api_connection():
    """Test RunPod API connection."""
    import os

    if not os.getenv("RUNPOD_API_KEY"):
        return {"success": False, "error": "RUNPOD_API_KEY not found in environment"}

    try:
        client = get_runpod_client()
        result = await client.test_connection()
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# Pod Management Endpoints
# ============================================================================

@router.post("/pods/launch", response_model=PodLaunchResponse)
async def launch_pods(request: PodLaunchRequest):
    """
    Launch multiple pods attached to the network volume.

    All pods will mount the same volume and run the coordinator script.
    """
    import os

    if not os.getenv("RUNPOD_API_KEY"):
        raise HTTPException(status_code=400, detail="RUNPOD_API_KEY not found in environment")

    # Get volume ID from request or config
    volume_id = request.network_volume_id
    if not volume_id:
        config = _get_api_config()
        volume_id = config.get("network_volume_id") if config else DEFAULT_VOLUME_ID

    if not volume_id:
        raise HTTPException(status_code=400, detail="No network volume ID configured")

    client = get_runpod_client()
    db = await get_db()

    launched_pods = []
    errors = []

    for i in range(request.count):
        pod_name = f"scholia-worker-{i+1}-{uuid.uuid4().hex[:4]}"
        try:
            result = await client.create_pod(
                name=pod_name,
                gpu_type=request.gpu_type,
                network_volume_id=volume_id,
                image=request.image,
                container_disk_gb=20,
                volume_mount_path="/data",
                env_vars={"SCHOLIA_WORKER": "true"}
            )

            pod_id = result.get("id")
            if pod_id:
                pod_info = PodInfo(
                    pod_id=pod_id,
                    name=pod_name,
                    status=result.get("desiredStatus", "STARTING"),
                    gpu_type=request.gpu_type,
                    created_at=datetime.now().isoformat()
                )
                launched_pods.append(pod_info)

                # Track in database
                await db.execute("""
                    INSERT INTO runpod_pods (pod_id, name, status, gpu_type, network_volume_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (pod_id, pod_name, "STARTING", request.gpu_type, volume_id, datetime.now().isoformat()))
            else:
                errors.append(f"Pod {i+1}: No ID returned - {result}")

        except Exception as e:
            errors.append(f"Pod {i+1}: {str(e)}")

    await db.commit()

    return PodLaunchResponse(
        launched=len(launched_pods),
        pods=launched_pods,
        errors=errors
    )


@router.get("/pods")
async def list_pods():
    """List all pods attached to the configured network volume."""
    import os

    if not os.getenv("RUNPOD_API_KEY"):
        raise HTTPException(status_code=400, detail="RUNPOD_API_KEY not found in environment")

    config = _get_api_config()
    volume_id = config.get("network_volume_id") if config else DEFAULT_VOLUME_ID

    client = get_runpod_client()
    db = await get_db()

    try:
        # Get pods from API filtered by volume
        api_pods = await client.list_pods(network_volume_id=volume_id)

        pods = []
        for p in api_pods:
            # Extract SSH info from runtime if available
            runtime = p.get("runtime", {}) or {}
            ports = runtime.get("ports", []) or []

            ssh_host = None
            ssh_port = None
            for port in ports:
                if port.get("privatePort") == 22:
                    ssh_host = port.get("ip")
                    ssh_port = port.get("publicPort")
                    break

            pod_info = {
                "pod_id": p.get("id"),
                "name": p.get("name"),
                "status": p.get("desiredStatus"),
                "runtime_status": runtime.get("status") if runtime else None,
                "gpu_type": p.get("gpuTypeId"),
                "ssh_host": ssh_host,
                "ssh_port": ssh_port,
                "cost_per_hr": p.get("costPerHr"),
                "created_at": p.get("createdAt")
            }
            pods.append(pod_info)

            # Update local database
            await db.execute("""
                INSERT OR REPLACE INTO runpod_pods (pod_id, name, status, gpu_type, network_volume_id, ssh_host, ssh_port, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (pod_info["pod_id"], pod_info["name"], pod_info["status"],
                  pod_info["gpu_type"], volume_id, ssh_host, ssh_port, pod_info["created_at"]))

        await db.commit()

        return {
            "pods": pods,
            "volume_id": volume_id,
            "total": len(pods)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/pods/{pod_id}")
async def terminate_pod(pod_id: str):
    """Terminate a specific pod."""
    import os

    if not os.getenv("RUNPOD_API_KEY"):
        raise HTTPException(status_code=400, detail="RUNPOD_API_KEY not found in environment")

    client = get_runpod_client()
    db = await get_db()

    try:
        success = await client.terminate_pod(pod_id)
        if success:
            await db.execute("""
                UPDATE runpod_pods SET status = 'TERMINATED', terminated_at = ? WHERE pod_id = ?
            """, (datetime.now().isoformat(), pod_id))
            await db.commit()
            return {"status": "terminated", "pod_id": pod_id}
        else:
            raise HTTPException(status_code=500, detail="Failed to terminate pod")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/pods")
async def terminate_all_pods():
    """Terminate all pods attached to the configured volume."""
    import os

    if not os.getenv("RUNPOD_API_KEY"):
        raise HTTPException(status_code=400, detail="RUNPOD_API_KEY not found in environment")

    config = _get_api_config()
    volume_id = config.get("network_volume_id") if config else DEFAULT_VOLUME_ID

    client = get_runpod_client()
    db = await get_db()

    # Get all pods for this volume
    pods = await client.list_pods(network_volume_id=volume_id)

    terminated = []
    errors = []

    for p in pods:
        pod_id = p.get("id")
        try:
            success = await client.terminate_pod(pod_id)
            if success:
                terminated.append(pod_id)
                await db.execute("""
                    UPDATE runpod_pods SET status = 'TERMINATED', terminated_at = ? WHERE pod_id = ?
                """, (datetime.now().isoformat(), pod_id))
            else:
                errors.append(f"{pod_id}: Failed")
        except Exception as e:
            errors.append(f"{pod_id}: {str(e)}")

    await db.commit()

    return {
        "terminated": terminated,
        "errors": errors,
        "total": len(terminated)
    }


# ============================================================================
# Volume Operations
# ============================================================================

@router.get("/volume/status", response_model=VolumeStatusResponse)
async def get_volume_status():
    """
    Get status of files on the network volume.

    Requires at least one running pod to SSH into.
    """
    config = _get_api_config()
    volume_id = config.get("network_volume_id") if config else DEFAULT_VOLUME_ID

    # Get a running pod to SSH into
    ssh_config = _get_config()  # Existing SSH config
    if not ssh_config:
        return VolumeStatusResponse(
            input_files=[],
            processing_files=[],
            output_folders=[],
            error="No SSH connection configured. Start a pod first."
        )

    # List files in each directory
    input_files = []
    processing_files = []
    output_folders = []

    # List input PDFs (handle filenames with spaces)
    success, output = _ssh_command(ssh_config, "for f in /workspace/input/*.pdf; do [ -f \"$f\" ] && basename \"$f\"; done 2>/dev/null", timeout=45)
    if success and output:
        input_files = [f.strip() for f in output.strip().split('\n') if f.strip() and f.strip() != '*.pdf']

    # List processing locks (handle filenames with spaces)
    success, output = _ssh_command(ssh_config, "for f in /workspace/processing/*.lock; do [ -f \"$f\" ] && basename \"$f\"; done 2>/dev/null", timeout=45)
    if success and output:
        processing_files = [f.strip().replace('.lock', '') for f in output.strip().split('\n') if f.strip() and f.strip() != '*.lock']

    # List output folders (handle folder names with spaces)
    success, output = _ssh_command(ssh_config, "for d in /workspace/output/*/; do [ -d \"$d\" ] && basename \"$d\"; done 2>/dev/null", timeout=45)
    if success and output:
        output_folders = [f.strip() for f in output.strip().split('\n') if f.strip() and f.strip() != '*']

    return VolumeStatusResponse(
        input_files=input_files,
        processing_files=processing_files,
        output_folders=output_folders
    )


@router.get("/volume/browse")
async def browse_volume(path: str = "/workspace"):
    """
    Browse the network volume directory structure.

    Returns folder listing with counts and sizes.
    If path is /workspace, returns top-level folders with summary.
    If path is a subfolder, returns its contents.
    """
    ssh_config = _get_config()
    if not ssh_config:
        return {"error": "No SSH connection configured. Start a pod first."}

    # Sanitize path to prevent directory traversal
    if ".." in path or not path.startswith("/workspace"):
        return {"error": "Invalid path"}

    # Check if this is the root workspace listing
    is_root = path == "/workspace"

    if is_root:
        # Get top-level folders with item counts
        cmd = """
cd /workspace && for d in */; do
    if [ -d "$d" ]; then
        name="${d%/}"
        count=$(find "$d" -maxdepth 1 -type f 2>/dev/null | wc -l)
        dircount=$(find "$d" -maxdepth 1 -type d 2>/dev/null | wc -l)
        dircount=$((dircount - 1))  # subtract the directory itself
        total=$((count + dircount))
        size=$(du -sb "$d" 2>/dev/null | cut -f1)
        echo "$name|$total|$size"
    fi
done
"""
        success, output = await _ssh_command_async(ssh_config, cmd, timeout=60)

        if not success:
            return {"error": f"Failed to list workspace: {output}"}

        folders = []
        for line in output.strip().split('\n'):
            if '|' in line:
                parts = line.split('|')
                if len(parts) >= 3:
                    folders.append({
                        "name": parts[0],
                        "path": f"/workspace/{parts[0]}",
                        "count": int(parts[1]) if parts[1].isdigit() else 0,
                        "total_size": int(parts[2]) if parts[2].isdigit() else 0
                    })

        # Get summary counts for key directories
        summary_cmd = """
echo "input:$(find /workspace/input -maxdepth 1 -name '*.pdf' 2>/dev/null | wc -l)"
echo "processing:$(find /workspace/processing -maxdepth 1 -name '*.lock' 2>/dev/null | wc -l)"
echo "output:$(find /workspace/output -maxdepth 1 -type d 2>/dev/null | wc -l)"
echo "archive:$(find /workspace/archive -maxdepth 1 -type d 2>/dev/null | wc -l)"
echo "downloaded:$(find /workspace/downloaded -maxdepth 1 -type d 2>/dev/null | wc -l)"
"""
        success, summary_output = await _ssh_command_async(ssh_config, summary_cmd, timeout=30)

        summary = {}
        if success and summary_output:
            for line in summary_output.strip().split('\n'):
                if ':' in line:
                    key, val = line.split(':', 1)
                    # Subtract 1 for output/archive/downloaded to account for the directory itself
                    count = int(val) if val.strip().isdigit() else 0
                    if key in ['output', 'archive', 'downloaded']:
                        count = max(0, count - 1)
                    summary[f"{key}_count"] = count

        return {
            "path": path,
            "folders": folders,
            "summary": summary
        }

    else:
        # List contents of a specific folder
        cmd = f"""
cd '{path}' 2>/dev/null && for item in * .[!.]* ..?*; do
    [ -e "$item" ] || continue
    [ "$item" = "." ] || [ "$item" = ".." ] && continue
    if [ -d "$item" ]; then
        count=$(find "$item" -maxdepth 1 2>/dev/null | wc -l)
        count=$((count - 1))
        echo "d|$item|$count|0|"
    else
        size=$(stat -c%s "$item" 2>/dev/null || echo 0)
        mtime=$(stat -c%Y "$item" 2>/dev/null || echo 0)
        echo "f|$item|0|$size|$mtime"
    fi
done 2>/dev/null | head -500
"""
        success, output = await _ssh_command_async(ssh_config, cmd, timeout=60)

        if not success:
            return {"error": f"Failed to list {path}: {output}", "path": path, "items": []}

        items = []
        for line in output.strip().split('\n'):
            if '|' in line:
                parts = line.split('|')
                if len(parts) >= 4:
                    item_type = parts[0]
                    name = parts[1]
                    count = int(parts[2]) if parts[2].isdigit() else 0
                    size = int(parts[3]) if parts[3].isdigit() else 0
                    mtime = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0

                    item = {
                        "name": name,
                        "path": f"{path}/{name}",
                        "type": "directory" if item_type == "d" else "file"
                    }

                    if item_type == "d":
                        item["count"] = count
                    else:
                        item["size"] = size
                        if mtime > 0:
                            item["modified"] = datetime.fromtimestamp(mtime).isoformat()

                    items.append(item)

        # Sort: directories first, then files, alphabetically
        items.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))

        return {
            "path": path,
            "items": items
        }


@router.post("/volume/upload")
async def upload_to_volume(file: UploadFile = File(...)):
    """
    Upload a PDF to the network volume's input folder.

    Requires at least one running pod to SCP into.
    """
    config = _get_config()
    if not config:
        raise HTTPException(status_code=400, detail="No SSH connection configured. Start a pod first.")

    filename = file.filename or "document.pdf"

    # Save locally first
    UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    local_path = UPLOAD_TEMP_DIR / filename

    with open(local_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Ensure input directory exists
    _ssh_command(config, "mkdir -p /workspace/input")

    # Upload to volume
    remote_path = f"/workspace/input/{filename}"
    success, error = _scp_upload(config, local_path, remote_path)

    # Clean up local temp
    local_path.unlink(missing_ok=True)

    if not success:
        raise HTTPException(status_code=500, detail=f"Upload failed: {error}")

    return {
        "status": "uploaded",
        "filename": filename,
        "remote_path": remote_path
    }


@router.post("/volume/setup")
async def setup_volume():
    """
    Initialize the volume with required directory structure.

    Creates: /workspace/input, /workspace/processing, /workspace/output, /workspace/logs, /workspace/scripts
    """
    config = _get_config()
    if not config:
        raise HTTPException(status_code=400, detail="No SSH connection configured. Start a pod first.")

    # Create directories
    cmd = "mkdir -p /workspace/input /workspace/processing /workspace/output /workspace/logs /workspace/scripts"
    success, output = _ssh_command(config, cmd)

    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to create directories: {output}")

    return {
        "status": "initialized",
        "directories": ["input", "processing", "output", "logs", "scripts"]
    }


class CoordinatorRequest(BaseModel):
    """Request with optional pod SSH details."""
    ssh_host: Optional[str] = None
    ssh_port: Optional[int] = None


def _get_pod_ssh_config(ssh_host: str = None, ssh_port: int = None) -> Optional[dict]:
    """
    Get SSH config for a specific pod or fall back to default config.
    Returns config dict with host, port, ssh_key_path.
    """
    # If specific pod details provided, use those
    if ssh_host and ssh_port:
        default_config = _get_config() or {}
        return {
            "host": ssh_host,
            "port": ssh_port,
            "ssh_key_path": default_config.get("ssh_key_path") or str(DEFAULT_SSH_KEY)
        }
    # Otherwise use default config
    return _get_config()


@router.get("/coordinator/status")
async def get_coordinator_status(ssh_host: str = None, ssh_port: int = None):
    """Check if the coordinator is running on a specific pod or the connected pod."""
    config = _get_pod_ssh_config(ssh_host, ssh_port)
    if not config:
        return {"running": False, "error": "No SSH connection configured"}

    # Check if coordinator process is running
    success, output = _ssh_command(config, "pgrep -f 'coordinator.py' > /dev/null && echo 'running' || echo 'stopped'", timeout=10)

    if not success:
        return {"running": False, "error": f"SSH failed: {output}"}

    is_running = "running" in output.strip()

    # Get additional info if running
    result = {"running": is_running, "ssh_host": config["host"], "ssh_port": config["port"]}

    if is_running:
        # Get PID and recent log
        success, pid_out = _ssh_command(config, "pgrep -f 'coordinator.py' | head -1", timeout=5)
        if success and pid_out.strip():
            result["pid"] = pid_out.strip()

        success, log_out = _ssh_command(config, "tail -5 /workspace/logs/coordinator.log 2>/dev/null", timeout=5)
        if success and log_out.strip():
            result["recent_log"] = log_out.strip().split('\n')

    return result


@router.post("/coordinator/start")
async def start_coordinator(request: CoordinatorRequest = None):
    """Start the coordinator on a specific pod or the connected pod."""
    ssh_host = request.ssh_host if request else None
    ssh_port = request.ssh_port if request else None
    config = _get_pod_ssh_config(ssh_host, ssh_port)
    if not config:
        raise HTTPException(status_code=400, detail="No SSH connection configured")

    # Check if already running
    success, check = _ssh_command(config, "pgrep -f 'coordinator.py'", timeout=5)
    if success and check.strip():
        return {"status": "already_running", "pid": check.strip().split('\n')[0]}

    # Start coordinator in background
    cmd = "nohup python /workspace/scripts/coordinator.py > /workspace/logs/coordinator.log 2>&1 &"
    success, output = _ssh_command(config, cmd, timeout=10)

    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to start coordinator: {output}")

    # Wait a moment and verify it started
    import asyncio
    await asyncio.sleep(1)

    success, pid_out = _ssh_command(config, "pgrep -f 'coordinator.py' | head -1", timeout=5)
    if success and pid_out.strip():
        return {"status": "started", "pid": pid_out.strip()}
    else:
        # Check log for errors
        success, log_out = _ssh_command(config, "tail -10 /workspace/logs/coordinator.log 2>/dev/null", timeout=5)
        return {"status": "failed", "error": "Coordinator did not start", "log": log_out if success else None}


@router.post("/coordinator/stop")
async def stop_coordinator(request: CoordinatorRequest = None):
    """Stop the coordinator on a specific pod or the connected pod."""
    ssh_host = request.ssh_host if request else None
    ssh_port = request.ssh_port if request else None
    config = _get_pod_ssh_config(ssh_host, ssh_port)
    if not config:
        raise HTTPException(status_code=400, detail="No SSH connection configured")

    # Kill coordinator process
    success, output = _ssh_command(config, "pkill -f 'coordinator.py' && echo 'stopped' || echo 'not running'", timeout=10)

    if "stopped" in output:
        return {"status": "stopped"}
    else:
        return {"status": "not_running"}


@router.post("/coordinator/start-all")
async def start_coordinator_all():
    """Start the coordinator on all running pods."""
    import os

    if not os.getenv("RUNPOD_API_KEY"):
        raise HTTPException(status_code=400, detail="RUNPOD_API_KEY not found in environment")

    config = _get_api_config()
    volume_id = config.get("network_volume_id") if config else DEFAULT_VOLUME_ID

    client = get_runpod_client()
    pods = await client.list_pods(network_volume_id=volume_id)

    results = []
    for p in pods:
        if p.get("desiredStatus") != "RUNNING":
            continue

        runtime = p.get("runtime", {}) or {}
        ports = runtime.get("ports", []) or []
        ssh_host = None
        ssh_port = None
        for port in ports:
            if port.get("privatePort") == 22:
                ssh_host = port.get("ip")
                ssh_port = port.get("publicPort")
                break

        if not ssh_host or not ssh_port:
            results.append({"pod_id": p.get("id"), "name": p.get("name"), "status": "no_ssh"})
            continue

        pod_config = _get_pod_ssh_config(ssh_host, ssh_port)

        # Check if already running
        success, check = _ssh_command(pod_config, "pgrep -f 'coordinator.py'", timeout=5)
        if success and check.strip():
            results.append({
                "pod_id": p.get("id"),
                "name": p.get("name"),
                "status": "already_running",
                "pid": check.strip().split('\n')[0]
            })
            continue

        # Start coordinator
        cmd = "nohup python /workspace/scripts/coordinator.py > /workspace/logs/coordinator.log 2>&1 &"
        success, output = _ssh_command(pod_config, cmd, timeout=10)

        if not success:
            results.append({"pod_id": p.get("id"), "name": p.get("name"), "status": "failed", "error": output})
            continue

        # Verify started
        import asyncio
        await asyncio.sleep(1)

        success, pid_out = _ssh_command(pod_config, "pgrep -f 'coordinator.py' | head -1", timeout=5)
        if success and pid_out.strip():
            results.append({
                "pod_id": p.get("id"),
                "name": p.get("name"),
                "status": "started",
                "pid": pid_out.strip()
            })
        else:
            results.append({"pod_id": p.get("id"), "name": p.get("name"), "status": "failed"})

    return {"results": results, "total": len(results)}
