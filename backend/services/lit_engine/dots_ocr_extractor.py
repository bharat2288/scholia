"""
dots.ocr remote client for the bhaforge OCR service.
"""

import json
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_HEALTH_TIMEOUT_SECONDS = 3.0
DEFAULT_REMOTE_RETRY_LIMIT = int(os.getenv("BHAFORGE_OCR_RETRY_LIMIT", "60"))
DEFAULT_REMOTE_RETRY_DELAY_SECONDS = float(os.getenv("BHAFORGE_OCR_RETRY_DELAY_SECONDS", "2.0"))
REMOTE_RESULT_PREFIX = "bhaforge-ocr-result-"
LOCAL_JOB_STATE_FILENAME = "job_state.json"


class RemoteJobNotFoundError(RuntimeError):
    """Raised when bhaforge no longer knows about a previously submitted job."""


class RemoteJobUnavailableError(RuntimeError):
    """Raised when bhaforge cannot be polled reliably for a known job."""


def _resolve_service_url(service_url: Optional[str] = None) -> Optional[str]:
    value = service_url or os.getenv("BHAFORGE_OCR_URL")
    if not value:
        return None
    return value.rstrip("/")


def _count_output_pages(save_dir: Path, filename: str) -> int:
    pages = set()
    for path in save_dir.glob(f"{filename}_page_*.json"):
        match = path.stem.rsplit("_page_", 1)
        if len(match) != 2:
            continue
        try:
            if path.stat().st_size > 0:
                pages.add(int(match[1]))
        except (OSError, ValueError):
            continue
    return len(pages)


def _job_state_path(save_dir: Path) -> Path:
    return save_dir / LOCAL_JOB_STATE_FILENAME


def _load_job_state(save_dir: Path) -> Dict[str, Any]:
    state_path = _job_state_path(save_dir)
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_job_state(save_dir: Path, state: Dict[str, Any]) -> None:
    save_dir.mkdir(parents=True, exist_ok=True)
    state_path = _job_state_path(save_dir)
    temp_path = state_path.with_suffix(".json.tmp")
    payload = dict(state)
    payload["updated_at"] = time.time()
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(state_path)


def _update_job_state(save_dir: Path, **changes: Any) -> Dict[str, Any]:
    state = _load_job_state(save_dir)
    state.update(changes)
    _save_job_state(save_dir, state)
    return state


def _update_progress(progress_store: Optional[dict], temp_id: Optional[str], **changes: Any) -> None:
    if not progress_store or not temp_id or temp_id not in progress_store:
        return
    progress_store[temp_id].update(changes)


def _submit_remote_job(
    client: httpx.Client,
    url: str,
    pdf_path_obj: Path,
    file_prefix: str,
    save_dir: Path,
    *,
    progress_store: Optional[dict] = None,
    temp_id: Optional[str] = None,
    stage_label: str = "submitting remote",
) -> str:
    _update_progress(progress_store, temp_id, stage=stage_label)
    _update_job_state(
        save_dir,
        remote_job_id=None,
        status="processing",
        stage=stage_label,
        last_error=None,
    )
    with open(pdf_path_obj, "rb") as handle:
        response = client.post(
            f"{url}/ocr/process",
            data={"save_name": file_prefix},
            files={"file": (pdf_path_obj.name, handle, "application/pdf")},
        )
    response.raise_for_status()
    payload = response.json()
    job_id = payload.get("job_id")
    if not job_id:
        raise RuntimeError("bhaforge OCR service did not return a job_id.")
    _update_job_state(
        save_dir,
        remote_job_id=job_id,
        status=payload.get("status", "queued"),
        stage="submitted",
        last_error=None,
    )
    return job_id


def _poll_remote_status(
    client: httpx.Client,
    url: str,
    job_id: str,
    *,
    retry_limit: int,
    retry_delay_seconds: float,
    progress_store: Optional[dict] = None,
    temp_id: Optional[str] = None,
    save_dir: Optional[Path] = None,
    stage_label: str = "waiting for remote reconnect",
) -> Dict[str, Any]:
    failures = 0
    while True:
        try:
            response = client.get(f"{url}/ocr/status/{job_id}", timeout=10.0)
            if response.status_code == 404:
                raise RemoteJobNotFoundError(f"bhaforge OCR job {job_id} was not found")
            response.raise_for_status()
            return response.json()
        except RemoteJobNotFoundError as exc:
            _update_progress(progress_store, temp_id, stage=stage_label)
            if save_dir is not None:
                _update_job_state(
                    save_dir,
                    remote_job_id=job_id,
                    status="processing",
                    stage=stage_label,
                    last_error=str(exc),
                )
            raise
        except (httpx.HTTPError, ValueError) as exc:
            failures += 1
            _update_progress(progress_store, temp_id, stage=stage_label)
            if save_dir is not None:
                _update_job_state(
                    save_dir,
                    remote_job_id=job_id,
                    status="processing",
                    stage=stage_label,
                    last_error=str(exc),
                )
            if failures >= retry_limit:
                raise RemoteJobUnavailableError(
                    f"Lost contact with bhaforge OCR job {job_id} after {failures} retries: {exc}"
                ) from exc
            time.sleep(retry_delay_seconds)


def _safe_extract_tar(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            member_path = (destination / member.name).resolve()
            if member_path != destination and destination not in member_path.parents:
                raise RuntimeError(f"Unsafe path in OCR result archive: {member.name}")
        tar.extractall(destination)


def is_available(service_url: Optional[str] = None) -> bool:
    """
    Whether dots-ocr is configured for this Scholia checkout.
    """
    return bool(_resolve_service_url(service_url))


def is_remote_available(service_url: Optional[str] = None) -> bool:
    """
    Whether the configured bhaforge OCR service is reachable.
    """
    url = _resolve_service_url(service_url)
    if not url:
        return False

    try:
        response = httpx.get(
            f"{url}/ocr/health",
            timeout=DEFAULT_HEALTH_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            return False
        payload = response.json()
        return payload.get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def get_setup_status(service_url: Optional[str] = None) -> dict:
    """
    Return remote OCR configuration diagnostics.
    """
    url = _resolve_service_url(service_url)
    status = {
        "service_url": url,
        "configured": bool(url),
        "remote_available": False,
    }

    if not url:
        return status

    try:
        response = httpx.get(
            f"{url}/ocr/health",
            timeout=DEFAULT_HEALTH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        status["remote_available"] = payload.get("status") == "ok"
        status["health"] = payload
    except (httpx.HTTPError, ValueError) as exc:
        status["error"] = str(exc)

    return status


def extract_with_dots_ocr_remote(
    pdf_path: str,
    temp_id: str = None,
    progress_store: dict = None,
    output_dir: Path = None,
    save_name: str = None,
    service_url: str = None,
) -> str:
    """
    Upload a PDF to bhaforge, poll progress, download the result archive,
    and return the extracted content in Scholia format.
    """
    url = _resolve_service_url(service_url)
    if not url:
        raise RuntimeError("BHAFORGE_OCR_URL is not configured.")

    pdf_path_obj = Path(pdf_path).resolve()
    if not pdf_path_obj.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path_obj}")

    save_dir = Path(output_dir or pdf_path_obj.parent)
    save_dir.mkdir(parents=True, exist_ok=True)
    file_prefix = save_name or pdf_path_obj.stem
    state = _update_job_state(
        save_dir,
        temp_id=temp_id,
        filename=pdf_path_obj.name,
        pdf_path=str(pdf_path_obj),
        save_name=file_prefix,
        service_url=url,
        status="processing",
        stage="connecting remote",
    )
    total_pages_hint = int(state.get("total_pages") or 0)
    local_completed_pages = _count_output_pages(save_dir, file_prefix)
    if total_pages_hint and local_completed_pages >= total_pages_hint:
        _update_progress(
            progress_store,
            temp_id,
            stage="formatting",
            current_page=total_pages_hint,
            total_pages=total_pages_hint,
            percent=95,
        )
        _update_job_state(
            save_dir,
            status="complete",
            stage="downloaded",
            current_page=total_pages_hint,
            total_pages=total_pages_hint,
            percent=100,
            last_error=None,
        )
        return dots_ocr_to_scholia(save_dir, file_prefix, total_pages_hint)

    with httpx.Client(timeout=httpx.Timeout(60.0, connect=DEFAULT_HEALTH_TIMEOUT_SECONDS)) as client:
        job_id = state.get("remote_job_id")
        status_payload = None
        restart_attempted = False
        if job_id:
            _update_progress(progress_store, temp_id, stage="reattaching remote")
            _update_job_state(save_dir, stage="reattaching remote")
            try:
                status_payload = _poll_remote_status(
                    client,
                    url,
                    job_id,
                    retry_limit=DEFAULT_REMOTE_RETRY_LIMIT,
                    retry_delay_seconds=DEFAULT_REMOTE_RETRY_DELAY_SECONDS,
                    progress_store=progress_store,
                    temp_id=temp_id,
                    save_dir=save_dir,
                    stage_label="reattaching remote",
                )
            except RemoteJobNotFoundError as exc:
                _update_job_state(
                    save_dir,
                    remote_job_id=None,
                    status="queued",
                    stage="remote job missing",
                    last_error=str(exc),
                )
                job_id = None
                status_payload = None
            except RemoteJobUnavailableError as exc:
                raise RuntimeError(
                    f"Unable to reattach to existing bhaforge OCR job {job_id}. "
                    f"Local state was preserved for resume: {exc}"
                ) from exc

            if status_payload is not None:
                remote_status = status_payload.get("status")
            else:
                remote_status = None
            if remote_status in {"error", "cancelled", "canceled"}:
                _update_job_state(
                    save_dir,
                    remote_job_id=None,
                    status=remote_status,
                    stage=status_payload.get("stage", "failed"),
                    last_error=status_payload.get("error"),
                )
                job_id = None
                status_payload = None

        if not job_id:
            job_id = _submit_remote_job(
                client,
                url,
                pdf_path_obj,
                file_prefix,
                save_dir,
                progress_store=progress_store,
                temp_id=temp_id,
                stage_label="submitting remote",
            )

        total_pages = total_pages_hint
        while True:
            if progress_store and temp_id and progress_store[temp_id].get("status") == "cancelled":
                try:
                    client.post(f"{url}/ocr/cancel/{job_id}", timeout=10.0)
                finally:
                    raise InterruptedError("Processing cancelled by user")

            if status_payload is None:
                try:
                    status_payload = _poll_remote_status(
                        client,
                        url,
                        job_id,
                        retry_limit=DEFAULT_REMOTE_RETRY_LIMIT,
                        retry_delay_seconds=DEFAULT_REMOTE_RETRY_DELAY_SECONDS,
                        progress_store=progress_store,
                        temp_id=temp_id,
                        save_dir=save_dir,
                    )
                except RemoteJobNotFoundError as exc:
                    if restart_attempted:
                        _update_job_state(
                            save_dir,
                            remote_job_id=None,
                            status="error",
                            stage="failed",
                            last_error=str(exc),
                        )
                        raise RuntimeError(
                            f"bhaforge OCR job disappeared twice while processing {pdf_path_obj.name}: {exc}"
                        ) from exc
                    restart_attempted = True
                    job_id = _submit_remote_job(
                        client,
                        url,
                        pdf_path_obj,
                        file_prefix,
                        save_dir,
                        progress_store=progress_store,
                        temp_id=temp_id,
                        stage_label="resubmitting remote",
                    )
                    status_payload = None
                    total_pages = 0
                    continue
                except RemoteJobUnavailableError as exc:
                    raise RuntimeError(
                        f"Lost contact with bhaforge OCR job {job_id}. "
                        f"Resume can reattach later: {exc}"
                    ) from exc

            remote_status = status_payload.get("status", "processing")
            total_pages = status_payload.get("total_pages") or total_pages
            remote_percent = int(status_payload.get("percent", 0) or 0)
            remote_stage = status_payload.get("stage", "extracting")
            remote_page = status_payload.get("current_page", 0)

            _update_progress(
                progress_store,
                temp_id,
                stage=remote_stage,
                current_page=remote_page,
                total_pages=total_pages,
                percent=min(85, 10 + int(remote_percent * 0.75)),
            )
            _update_job_state(
                save_dir,
                remote_job_id=job_id,
                status=remote_status,
                stage=remote_stage,
                current_page=remote_page,
                total_pages=total_pages,
                percent=remote_percent,
                last_error=None,
            )

            if remote_status == "complete":
                break
            if remote_status == "error":
                _update_job_state(
                    save_dir,
                    remote_job_id=None,
                    status="error",
                    stage=remote_stage,
                    current_page=remote_page,
                    total_pages=total_pages,
                    percent=remote_percent,
                    last_error=status_payload.get("error"),
                )
                raise RuntimeError(status_payload.get("error") or "bhaforge OCR job failed")
            if remote_status in {"cancelled", "canceled"}:
                _update_job_state(
                    save_dir,
                    remote_job_id=None,
                    status="cancelled",
                    stage=remote_stage,
                    current_page=remote_page,
                    total_pages=total_pages,
                    percent=remote_percent,
                    last_error=None,
                )
                raise InterruptedError("bhaforge OCR job was cancelled")

            status_payload = None
            time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)

        with tempfile.NamedTemporaryFile(
            suffix=".tar.gz",
            prefix=REMOTE_RESULT_PREFIX,
            delete=False,
        ) as temp_archive:
            archive_path = Path(temp_archive.name)

        try:
            _update_progress(progress_store, temp_id, stage="downloading remote result")
            _update_job_state(
                save_dir,
                remote_job_id=job_id,
                status="complete",
                stage="downloading remote result",
                current_page=total_pages,
                total_pages=total_pages,
                percent=100,
            )
            with client.stream("GET", f"{url}/ocr/result/{job_id}", timeout=None) as stream:
                stream.raise_for_status()
                with open(archive_path, "wb") as archive_file:
                    for chunk in stream.iter_bytes():
                        archive_file.write(chunk)

            _safe_extract_tar(archive_path, save_dir)
        finally:
            archive_path.unlink(missing_ok=True)

    total_pages = total_pages or _count_output_pages(save_dir, file_prefix)
    if total_pages <= 0:
        raise RuntimeError("bhaforge OCR result did not contain any page JSON files")

    _update_job_state(
        save_dir,
        remote_job_id=job_id,
        status="complete",
        stage="downloaded",
        current_page=total_pages,
        total_pages=total_pages,
        percent=100,
        last_error=None,
    )
    return dots_ocr_to_scholia(save_dir, file_prefix, total_pages)


def dots_ocr_to_scholia(save_dir: Path, filename: str, total_pages: int) -> str:
    """
    Convert dots.ocr per-page output to Scholia's canonical format.
    """
    output_lines = []

    for page_idx in range(total_pages):
        output_lines.append(f"\n[PAGE {page_idx + 1}]\n")

        md_path = save_dir / f"{filename}_page_{page_idx}.md"
        json_path = save_dir / f"{filename}_page_{page_idx}.json"

        if md_path.exists():
            with open(md_path, "r", encoding="utf-8") as handle:
                md_content = handle.read()
            output_lines.append(process_dots_ocr_markdown(md_content))
            continue

        if not json_path.exists():
            continue

        with open(json_path, "r", encoding="utf-8") as handle:
            layout_data = json.load(handle)

        if isinstance(layout_data, str):
            layout_data = json.loads(layout_data)

        if not isinstance(layout_data, list):
            continue

        for item in layout_data:
            if not isinstance(item, dict):
                continue
            category = item.get("category", item.get("type", "Text"))
            text = item.get("text", item.get("content", ""))

            if category in ["Title", "Section-header"]:
                output_lines.append(f"\n[SECTION] # {text}\n")
            elif category in ["Picture", "Figure"]:
                output_lines.append("\n[FIGURE]\n")
            elif category == "Table":
                output_lines.append(f"\n[TABLE]\n{text}\n")
            elif category == "Equation":
                output_lines.append(f"\n{text}\n")
            else:
                output_lines.append(f"{text}\n")

    return "\n".join(output_lines)


def process_dots_ocr_markdown(md_content: str) -> str:
    """
    Convert dots.ocr markdown output to Scholia markers.
    """
    import re

    lines = md_content.split("\n")
    output_lines = []

    for line in lines:
        if line.startswith("# ") or line.startswith("## ") or line.startswith("### "):
            output_lines.append(f"[SECTION] {line}")
        elif re.match(r"!\[.*?\]\(.*?\)", line):
            output_lines.append("[FIGURE]")
        elif line.strip().startswith("<table") or line.strip() == "[TABLE]":
            output_lines.append("[TABLE]")
        else:
            output_lines.append(line)

    return "\n".join(output_lines)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        print(json.dumps(get_setup_status(), indent=2))
    elif len(sys.argv) > 1:
        result = extract_with_dots_ocr_remote(sys.argv[1])
        print(result[:2000])
    else:
        print("Usage: python dots_ocr_extractor.py <pdf_path> | --status")
        print(json.dumps(get_setup_status(), indent=2))
