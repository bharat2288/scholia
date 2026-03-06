"""
Eval Dashboard API
==================
Read-only endpoints for the eval dashboard frontend.
Queries adapted from eval/__main__.py cmd_status.
"""

import sys
from pathlib import Path

# eval package lives at project root (../eval/ from backend/)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import APIRouter, HTTPException

router = APIRouter()


async def _get_db():
    """Get eval database connection (lazy init)."""
    from eval.db import get_eval_db
    return await get_eval_db()


@router.get("/experiments")
async def list_experiments():
    """List all experiments with summary stats."""
    db = await _get_db()

    cursor = await db.execute("""
        SELECT e.id, e.name, e.status, e.description, e.dimensions,
               e.total_cost_usd, e.max_cost_usd,
               e.created_at, e.completed_at,
               COUNT(r.id) as run_count,
               SUM(CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END) as completed_count,
               SUM(CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END) as failed_count
        FROM experiments e
        LEFT JOIN runs r ON r.experiment_id = e.id
        GROUP BY e.id
        ORDER BY e.created_at DESC
    """)
    rows = await cursor.fetchall()

    return [
        {
            "id": r["id"],
            "name": r["name"],
            "status": r["status"],
            "description": r["description"],
            "dimensions": r["dimensions"],
            "total_cost_usd": r["total_cost_usd"] or 0,
            "max_cost_usd": r["max_cost_usd"] or 0,
            "run_count": r["run_count"] or 0,
            "completed_count": r["completed_count"] or 0,
            "failed_count": r["failed_count"] or 0,
            "created_at": r["created_at"],
            "completed_at": r["completed_at"],
        }
        for r in rows
    ]


@router.get("/experiments/{experiment_id}")
async def get_experiment_detail(experiment_id: int):
    """Full experiment detail: info + configs + judgments + fidelity."""
    db = await _get_db()

    # Experiment info
    cursor = await db.execute(
        "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
    )
    exp = await cursor.fetchone()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")

    info = {
        "id": exp["id"],
        "name": exp["name"],
        "status": exp["status"],
        "description": exp["description"],
        "dimensions": exp["dimensions"],
        "total_cost_usd": exp["total_cost_usd"] or 0,
        "max_cost_usd": exp["max_cost_usd"] or 0,
        "created_at": exp["created_at"],
        "completed_at": exp["completed_at"],
    }

    # Per-config summary
    cursor = await db.execute(
        """SELECT c.name, c.orchestrator_model, c.sub_model, c.synthesis_model,
                  COUNT(r.id) as run_count,
                  SUM(CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END) as completed,
                  AVG(r.total_cost_usd) as avg_cost,
                  AVG(r.iterations) as avg_iterations,
                  AVG(r.sub_llm_calls) as avg_sub_llm,
                  AVG(r.duration_s) as avg_duration
           FROM configs c
           LEFT JOIN runs r ON r.config_id = c.id
           WHERE c.experiment_id = ?
           GROUP BY c.id
           ORDER BY c.name""",
        (experiment_id,),
    )
    configs = [
        {
            "name": c["name"],
            "orchestrator_model": c["orchestrator_model"],
            "sub_model": c["sub_model"],
            "synthesis_model": c["synthesis_model"],
            "run_count": c["run_count"] or 0,
            "completed": c["completed"] or 0,
            "avg_cost": round(c["avg_cost"], 4) if c["avg_cost"] else None,
            "avg_iterations": round(c["avg_iterations"], 1) if c["avg_iterations"] else None,
            "avg_sub_llm": round(c["avg_sub_llm"], 1) if c["avg_sub_llm"] else None,
            "avg_duration": round(c["avg_duration"], 1) if c["avg_duration"] else None,
        }
        for c in await cursor.fetchall()
    ]

    # LLM judgment averages per config
    cursor = await db.execute(
        """SELECT c.name as config_name,
                  AVG(j.completeness) as avg_completeness,
                  AVG(j.coherence) as avg_coherence,
                  AVG(j.relevance) as avg_relevance,
                  AVG(j.scholarly_quality) as avg_scholarly_quality,
                  COUNT(j.id) as judgment_count
           FROM llm_judgments j
           JOIN runs r ON r.id = j.run_id
           JOIN configs c ON c.id = r.config_id
           WHERE r.experiment_id = ?
           GROUP BY c.id
           ORDER BY c.name""",
        (experiment_id,),
    )
    judgments = []
    for j in await cursor.fetchall():
        scores = [j["avg_completeness"], j["avg_coherence"],
                  j["avg_relevance"], j["avg_scholarly_quality"]]
        valid = [s for s in scores if s is not None]
        mean = sum(valid) / len(valid) if valid else None
        judgments.append({
            "config_name": j["config_name"],
            "avg_completeness": round(j["avg_completeness"], 2) if j["avg_completeness"] else None,
            "avg_coherence": round(j["avg_coherence"], 2) if j["avg_coherence"] else None,
            "avg_relevance": round(j["avg_relevance"], 2) if j["avg_relevance"] else None,
            "avg_scholarly_quality": round(j["avg_scholarly_quality"], 2) if j["avg_scholarly_quality"] else None,
            "mean": round(mean, 2) if mean else None,
            "judgment_count": j["judgment_count"],
        })

    # Fidelity check averages per config
    cursor = await db.execute(
        """SELECT c.name as config_name,
                  AVG(fc.quote_match_rate) as avg_quote,
                  AVG(fc.page_accuracy) as avg_page,
                  AVG(fc.attribution_accuracy) as avg_attribution,
                  AVG(fc.synthesis_fidelity) as avg_synthesis,
                  COUNT(fc.id) as check_count
           FROM fidelity_checks fc
           JOIN runs r ON r.id = fc.run_id
           JOIN configs c ON c.id = r.config_id
           WHERE r.experiment_id = ?
           GROUP BY c.id
           ORDER BY c.name""",
        (experiment_id,),
    )
    fidelity = []
    for f in await cursor.fetchall():
        # Composite: weighted average matching eval/__main__.py
        scores, weights = [], []
        if f["avg_quote"] is not None:
            scores.append(f["avg_quote"]); weights.append(2.0)
        if f["avg_page"] is not None:
            scores.append(f["avg_page"]); weights.append(1.0)
        if f["avg_attribution"] is not None:
            scores.append(f["avg_attribution"]); weights.append(1.5)
        if f["avg_synthesis"] is not None:
            scores.append(f["avg_synthesis"]); weights.append(1.5)
        composite = (
            sum(s * w for s, w in zip(scores, weights)) / sum(weights)
            if weights else None
        )
        fidelity.append({
            "config_name": f["config_name"],
            "avg_quote": round(f["avg_quote"], 4) if f["avg_quote"] is not None else None,
            "avg_page": round(f["avg_page"], 4) if f["avg_page"] is not None else None,
            "avg_attribution": round(f["avg_attribution"], 4) if f["avg_attribution"] is not None else None,
            "avg_synthesis": round(f["avg_synthesis"], 4) if f["avg_synthesis"] is not None else None,
            "composite": round(composite, 4) if composite is not None else None,
            "check_count": f["check_count"],
        })

    return {
        **info,
        "configs": configs,
        "judgments": judgments,
        "fidelity": fidelity,
    }
