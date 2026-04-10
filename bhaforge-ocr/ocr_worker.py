"""
Background worker for the bhaforge dots-ocr service.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import importlib
import importlib.util
from pathlib import Path
import json
import os
import queue
import shutil
import sys
import tarfile
import threading
import time
import uuid
from typing import Any, Dict, Optional

import fitz

DOTS_OCR_PATH = Path(os.getenv("DOTS_OCR_PATH", Path.home() / "dots-ocr"))
WEIGHTS_DIR = DOTS_OCR_PATH / "weights"
DATA_ROOT = Path(os.getenv("BHAFORGE_OCR_DATA_ROOT", Path(__file__).resolve().parent / ".data"))
JOB_TTL_SECONDS = int(os.getenv("BHAFORGE_OCR_JOB_TTL_SECONDS", "3600"))
JOB_STATE_FILENAME = "job.json"
ATTN_IMPLEMENTATION_ENV = "BHAFORGE_OCR_ATTN_IMPLEMENTATION"
MODEL_PATH_ENV = "BHAFORGE_OCR_MODEL_PATH"

if str(DOTS_OCR_PATH) not in sys.path:
    sys.path.insert(0, str(DOTS_OCR_PATH))


def _flash_attn_available() -> bool:
    if importlib.util.find_spec("flash_attn") is None:
        return False

    try:
        module = importlib.import_module("flash_attn")
    except Exception:
        return False

    return not getattr(module, "IS_COMPAT_SHIM", False)


def _resolve_attn_implementation() -> str:
    configured = os.getenv(ATTN_IMPLEMENTATION_ENV, "").strip()
    if configured:
        return configured
    return "flash_attention_2" if _flash_attn_available() else "sdpa"


def _candidate_model_paths() -> list[Path]:
    return [
        WEIGHTS_DIR / "DotsOCR",
        WEIGHTS_DIR / "DotsMOCR",
    ]


def _resolve_model_path() -> Path:
    configured = os.getenv(MODEL_PATH_ENV, "").strip()
    if configured:
        return Path(configured)
    for candidate in _candidate_model_paths():
        if candidate.exists():
            return candidate
    return _candidate_model_paths()[0]


def _weights_present() -> bool:
    return _resolve_model_path().exists()


DOTS_OCR_IMPORT_ERROR = None
try:
    from dots_ocr.parser import DotsOCRParser
    from dots_ocr.utils.doc_utils import load_images_from_pdf
except Exception as exc:  # pragma: no cover - import availability is environment-specific
    DotsOCRParser = None
    load_images_from_pdf = None
    DOTS_OCR_IMPORT_ERROR = exc
else:
    class BhaforgeDotsOCRParser(DotsOCRParser):
        def _load_hf_model(self):
            import torch
            from transformers import AutoConfig, AutoModelForCausalLM, AutoProcessor
            from qwen_vl_utils import process_vision_info

            model_path = str(_resolve_model_path())
            attn_implementation = _resolve_attn_implementation()
            config = AutoConfig.from_pretrained(
                model_path,
                trust_remote_code=True,
            )

            if hasattr(config, "vision_config"):
                vision_config = config.vision_config
                if isinstance(vision_config, dict):
                    vision_config["attn_implementation"] = attn_implementation
                else:
                    setattr(vision_config, "attn_implementation", attn_implementation)

            self.model = AutoModelForCausalLM.from_pretrained(
                model_path,
                config=config,
                attn_implementation=attn_implementation,
                torch_dtype=torch.bfloat16,
                trust_remote_code=True,
            )
            if torch.cuda.is_available():
                self.model = self.model.to("cuda")
            self.model.eval()
            self.processor = AutoProcessor.from_pretrained(
                model_path,
                trust_remote_code=True,
                use_fast=True,
            )
            self.process_vision_info = process_vision_info

    DotsOCRParser = BhaforgeDotsOCRParser


@dataclass
class OCRJob:
    job_id: str
    filename: str
    save_name: str
    job_dir: str
    pdf_path: str
    output_dir: str
    archive_path: str
    status: str = "queued"
    stage: str = "waiting"
    current_page: int = 0
    total_pages: int = 0
    percent: int = 0
    error: Optional[str] = None
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_public_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("cancel_requested", None)
        return payload


class OCRWorker:
    def __init__(self) -> None:
        self.jobs: Dict[str, OCRJob] = {}
        self.jobs_lock = threading.Lock()
        self.queue: queue.Queue[str] = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.worker_running = False
        self.parser = None
        self.parser_lock = threading.Lock()
        self.active_job_id: Optional[str] = None
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        self._recover_jobs()
        self.cleanup_old_jobs()
        self.start()

    def start(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self.worker_running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def shutdown(self) -> None:
        self.worker_running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5.0)

    def submit_job(self, file_bytes: bytes, filename: str, save_name: Optional[str] = None) -> OCRJob:
        self._assert_ready()
        self.cleanup_old_jobs()

        job_id = str(uuid.uuid4())[:8]
        safe_save_name = save_name or Path(filename).stem
        job_dir = DATA_ROOT / job_id
        output_dir = job_dir / "output"
        job_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = job_dir / filename
        pdf_path.write_bytes(file_bytes)

        job = OCRJob(
            job_id=job_id,
            filename=filename,
            save_name=safe_save_name,
            job_dir=str(job_dir),
            pdf_path=str(pdf_path),
            output_dir=str(output_dir),
            archive_path=str(job_dir / f"{safe_save_name}.tar.gz"),
        )

        with self.jobs_lock:
            self.jobs[job_id] = job
        self._write_job_state(job)

        self.queue.put(job_id)
        return job

    def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            return job.to_public_dict() if job else None

    def cancel_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            if not job:
                return None

            status = job.status

        if status == "queued":
            job = self._update_job(
                job_id,
                status="cancelled",
                stage="cancelled",
                cancel_requested=True,
            )
        elif status == "processing":
            job = self._update_job(
                job_id,
                status="cancelled",
                stage="cancelling",
                cancel_requested=True,
            )
        else:
            with self.jobs_lock:
                job = self.jobs.get(job_id)
                if not job:
                    return None

        return job.to_public_dict()

    def get_result_path(self, job_id: str) -> Optional[Path]:
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            if not job or job.status != "complete":
                return None
            archive_path = Path(job.archive_path)
            return archive_path if archive_path.exists() else None

    def get_health(self) -> Dict[str, Any]:
        status = {
            "status": "ok" if self._is_ready() else "degraded",
            "dots_ocr_path": str(DOTS_OCR_PATH),
            "weights_path": str(_resolve_model_path()),
            "weights_candidates": [str(path) for path in _candidate_model_paths()],
            "weights_present": _weights_present(),
            "import_error": str(DOTS_OCR_IMPORT_ERROR) if DOTS_OCR_IMPORT_ERROR else None,
            "attn_implementation": _resolve_attn_implementation(),
            "flash_attn_available": _flash_attn_available(),
            "model_loaded": self.parser is not None,
            "queue_size": self.queue.qsize(),
            "active_job_id": self.active_job_id,
        }

        try:
            import torch

            status["cuda_available"] = torch.cuda.is_available()
            if torch.cuda.is_available():
                status["gpu_name"] = torch.cuda.get_device_name(0)
                status["gpu_memory_gb"] = round(
                    torch.cuda.get_device_properties(0).total_memory / 1e9,
                    1,
                )
        except ImportError:
            status["cuda_available"] = False

        return status

    def cleanup_old_jobs(self) -> None:
        now = time.time()
        stale_jobs = []

        with self.jobs_lock:
            for job_id, job in self.jobs.items():
                if job.status not in {"complete", "error", "cancelled"}:
                    continue
                if now - job.updated_at > JOB_TTL_SECONDS:
                    stale_jobs.append((job_id, Path(job.job_dir)))

            for job_id, _ in stale_jobs:
                self.jobs.pop(job_id, None)

        for _, job_dir in stale_jobs:
            shutil.rmtree(job_dir, ignore_errors=True)

    def _job_state_path(self, job_dir: Path) -> Path:
        return job_dir / JOB_STATE_FILENAME

    def _write_job_state(self, job: OCRJob) -> None:
        job_dir = Path(job.job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        state_path = self._job_state_path(job_dir)
        temp_path = state_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(asdict(job), indent=2), encoding="utf-8")
        temp_path.replace(state_path)

    def _load_job_state(self, state_path: Path) -> Optional[OCRJob]:
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            return OCRJob(**payload)
        except Exception:
            return None

    def _recover_jobs(self) -> None:
        recovered: list[OCRJob] = []
        for state_path in DATA_ROOT.glob(f"*/{JOB_STATE_FILENAME}"):
            if not state_path.is_file():
                continue
            job = self._load_job_state(state_path)
            if not job:
                continue
            recovered.append(job)

        if not recovered:
            return

        with self.jobs_lock:
            for job in recovered:
                self.jobs[job.job_id] = job

        for job in recovered:
            output_dir = Path(job.output_dir)
            archive_path = Path(job.archive_path)
            pdf_path = Path(job.pdf_path)
            if not pdf_path.exists():
                self._update_job(
                    job.job_id,
                    status="error",
                    stage="failed",
                    error=f"Recovered job PDF missing: {pdf_path}",
                )
                continue

            if job.cancel_requested or job.status == "cancelled":
                self._update_job(
                    job.job_id,
                    status="cancelled",
                    stage="cancelled",
                    cancel_requested=True,
                    error=None,
                )
                continue

            if job.status in {"queued", "processing"}:
                self._update_job(
                    job.job_id,
                    status="queued",
                    stage="waiting (recovered)",
                    error=None,
                    cancel_requested=False,
                )
                self.queue.put(job.job_id)
                continue

            if job.status == "complete" and output_dir.exists() and not archive_path.exists():
                self._update_job(
                    job.job_id,
                    status="queued",
                    stage="packaging (recovered)",
                    error=None,
                    cancel_requested=False,
                )
                self.queue.put(job.job_id)

    def _completed_pages(self, output_dir: Path, save_name: str) -> set[int]:
        pages = set()
        for path in output_dir.glob(f"{save_name}_page_*.json"):
            if not path.is_file():
                continue
            try:
                page_idx = int(path.stem.rsplit("_page_", 1)[1])
            except (IndexError, ValueError):
                continue
            try:
                if path.stat().st_size > 0:
                    pages.add(page_idx)
            except OSError:
                continue
        return pages

    def _assert_ready(self) -> None:
        if not self._is_ready():
            raise RuntimeError(
                "dots-ocr is not ready on bhaforge. Check DOTS_OCR_PATH, editable install, and model weights."
            )

    def _is_ready(self) -> bool:
        return DotsOCRParser is not None and load_images_from_pdf is not None and _weights_present()

    def _update_job(self, job_id: str, **changes: Any) -> OCRJob:
        with self.jobs_lock:
            job = self.jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = time.time()
            snapshot = OCRJob(**asdict(job))
        self._write_job_state(snapshot)
        return snapshot

    def _get_parser(self):
        self._assert_ready()
        with self.parser_lock:
            if self.parser is not None:
                return self.parser

            original_cwd = os.getcwd()
            os.chdir(str(DOTS_OCR_PATH))
            try:
                self.parser = DotsOCRParser(
                    use_hf=True,
                    output_dir=str(DOTS_OCR_PATH / "output"),
                    dpi=120,
                    num_thread=1,
                    max_completion_tokens=12000,
                )
            finally:
                os.chdir(original_cwd)

            return self.parser

    def _worker_loop(self) -> None:
        while self.worker_running:
            try:
                job_id = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._process_job(job_id)
            finally:
                self.active_job_id = None
                self.queue.task_done()
                self.cleanup_old_jobs()

    def _process_job(self, job_id: str) -> None:
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            if not job or job.status == "cancelled":
                return

        self.active_job_id = job_id

        try:
            pdf_path = Path(job.pdf_path)
            output_dir = Path(job.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)
            doc.close()
            completed_pages = {page for page in self._completed_pages(output_dir, job.save_name) if page < total_pages}
            completed_count = len(completed_pages)
            base_percent = 5
            if total_pages > 0:
                base_percent = max(5, min(90, 10 + int((completed_count / total_pages) * 80)))

            self._update_job(
                job_id,
                status="processing",
                stage="resuming" if completed_count else "loading model",
                current_page=completed_count,
                total_pages=total_pages,
                percent=base_percent,
                error=None,
            )

            if total_pages > 0 and completed_count >= total_pages:
                self._update_job(
                    job_id,
                    stage="packaging",
                    current_page=total_pages,
                    percent=95,
                )
                self._package_result(job_id)
                self._update_job(
                    job_id,
                    status="complete",
                    stage="done",
                    current_page=total_pages,
                    percent=100,
                    error=None,
                )
                return

            parser = self._get_parser()
            self._update_job(
                job_id,
                stage="resuming" if completed_count else "extracting",
                current_page=completed_count,
                percent=base_percent,
            )

            original_cwd = os.getcwd()
            os.chdir(str(DOTS_OCR_PATH))
            try:
                all_images = load_images_from_pdf(str(pdf_path), dpi=parser.dpi)
                for page_idx, origin_image in enumerate(all_images):
                    if page_idx in completed_pages:
                        continue

                    with self.jobs_lock:
                        current_job = self.jobs[job_id]
                        if current_job.cancel_requested:
                            raise InterruptedError("Processing cancelled")

                    parser._parse_single_image(
                        origin_image=origin_image,
                        prompt_mode="prompt_layout_all_en",
                        save_dir=str(output_dir),
                        save_name=job.save_name,
                        source="pdf",
                        page_idx=page_idx,
                    )

                    completed_pages.add(page_idx)
                    completed_count = len(completed_pages)
                    percent = 10 + int((completed_count / total_pages) * 80)
                    self._update_job(
                        job_id,
                        current_page=completed_count,
                        percent=min(percent, 90),
                    )
            finally:
                os.chdir(original_cwd)

            self._update_job(job_id, stage="packaging", percent=95)
            self._package_result(job_id)
            self._update_job(job_id, status="complete", stage="done", percent=100)

        except InterruptedError:
            self._update_job(job_id, status="cancelled", stage="cancelled", error=None)
        except Exception as exc:
            self._update_job(job_id, status="error", stage="failed", error=str(exc))

    def _package_result(self, job_id: str) -> None:
        with self.jobs_lock:
            job = self.jobs[job_id]
            output_dir = Path(job.output_dir)
            archive_path = Path(job.archive_path)

        if archive_path.exists():
            archive_path.unlink()

        with tarfile.open(archive_path, "w:gz") as tar:
            for path in sorted(output_dir.iterdir()):
                if not path.is_file():
                    continue
                tar.add(path, arcname=path.name)
