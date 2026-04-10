"""
FastAPI service for bhaforge dots-ocr processing.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ocr_worker import OCRWorker

worker = OCRWorker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    worker.shutdown()


app = FastAPI(
    title="bhaforge-ocr",
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/ocr/process")
async def process_document(
    file: UploadFile = File(...),
    save_name: str = Form(None),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded PDF was empty")

    try:
        job = worker.submit_job(payload, file.filename, save_name=save_name)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "job_id": job.job_id,
        "status": job.status,
    }


@app.get("/ocr/status/{job_id}")
async def get_status(job_id: str):
    status = worker.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status


@app.get("/ocr/result/{job_id}")
async def get_result(job_id: str):
    archive_path = worker.get_result_path(job_id)
    if not archive_path:
        raise HTTPException(status_code=409, detail="Job result is not ready")

    return FileResponse(
        path=archive_path,
        media_type="application/gzip",
        filename=archive_path.name,
    )


@app.post("/ocr/cancel/{job_id}")
async def cancel_job(job_id: str):
    status = worker.cancel_job(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status


@app.get("/ocr/health")
async def health():
    return worker.get_health()
