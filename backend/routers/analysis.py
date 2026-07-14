"""
Analysis Router
===============
Endpoints for source analysis (LLM analysis pipeline) and transcript cue management.

Endpoints:
- GET    /sources/analysis-types        - List available analysis types
- POST   /sources/estimate-analysis-cost - Pre-flight cost estimate
- GET    /sources/:id/analyses          - Get analyses for a source
- GET    /sources/:id/analyze/stream    - Run analyses via SSE
- POST   /sources/:id/regenerate-cues   - Regenerate transcript cues

Mounted under /sources prefix alongside the main sources router.
Static routes (/analysis-types, /estimate-analysis-cost) must be registered
BEFORE the sources router to avoid /{source_id} path capture.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List
from pathlib import Path
import uuid
import json
import logging

from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


class AnalysisCostRequest(BaseModel):
    """Request body for pre-flight cost estimate."""
    transcript_content: str
    analysis_types: List[str] = ["summary", "key_claims"]
    model_id: str = "codex-gpt-5.5"


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
    model: str = Query("codex-gpt-5.5", description="Analysis model ID"),
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
    from services.analysis_engine import (
        run_analysis_with_fallback,
        ANALYSIS_PROMPTS,
        ANALYSIS_FALLBACK_MODEL,
    )

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
                # Run LLM call in thread pool (synchronous API call).
                # Uses the fallback wrapper so a credit/rate-limit failure on
                # the primary model automatically retries on grok-4.20 before
                # surfacing an error to the user.
                loop = asyncio.get_running_loop()
                result, fallback_notice = await loop.run_in_executor(
                    None,
                    lambda at=analysis_type: run_analysis_with_fallback(
                        at,
                        transcript_content,
                        model_id=model,
                        metadata=metadata,
                        fallback_model_id=ANALYSIS_FALLBACK_MODEL,
                    ),
                )

                if fallback_notice:
                    yield send_event({
                        "stage": "analysis",
                        "status": "fallback",
                        "type": analysis_type,
                        "display_name": display_name,
                        "current": i + 1,
                        "total": total,
                        "message": fallback_notice,
                    })

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

    # Delete old cues and insert new (executemany for efficiency)
    await db.execute("DELETE FROM transcript_cues WHERE source_id = ?", [source_id])
    await db.executemany(
        """INSERT INTO transcript_cues
               (source_id, cue_index, start_time, end_time, text, start_offset, end_offset)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (source_id, cue.cue_index, cue.start_time, cue.end_time,
             cue.text, cue.start_offset, cue.end_offset)
            for cue in cues
        ]
    )
    await db.commit()

    return {
        "source_id": source_id,
        "cues_generated": len(cues),
        "segments_total": len(segments),
    }
