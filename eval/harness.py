"""
Eval Harness
=============
Core execution engine for running RLM experiments.

run_single() -- executes one config x query combination, collects all events,
               extracts metrics, saves to eval.db.
run_experiment() -- loads a YAML experiment definition, creates DB rows,
                   executes all runs sequentially with resume support.
run_llm_judge() -- scores a run's response using LLM-as-judge rubric.
"""

import asyncio
import json
import sys
import time
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from eval.db import get_eval_db
from eval.models import ExperimentConfig, RunConfig, RunResult, JudgmentScores
from eval.rubrics.v1 import JUDGE_SYSTEM_PROMPT, build_judge_prompt


def _now_iso() -> str:
    """UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# =========================================================================
# YAML Loading
# =========================================================================

def load_experiment_yaml(yaml_path: str | Path) -> ExperimentConfig:
    """Parse a YAML experiment definition into an ExperimentConfig."""
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Experiment file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return ExperimentConfig(
        name=data["name"],
        description=data.get("description", ""),
        dimensions=data.get("dimensions", []),
        queries=data.get("queries", []),
        configs=data.get("configs", []),
        repetitions=data.get("repetitions", 1),
        max_experiment_cost_usd=data.get("max_experiment_cost_usd", 50.0),
    )


# =========================================================================
# Database Setup -- create experiment/config/query rows
# =========================================================================

async def create_experiment_rows(
    config: ExperimentConfig,
    yaml_path: str = "",
) -> dict:
    """
    Create experiment, config, and query rows in eval.db.
    Returns {experiment_id, config_ids: {name: id}, query_ids: [{id, session_id, query_text}]}.
    Skips duplicates (UNIQUE constraints).
    """
    db = await get_eval_db()

    # Create experiment
    cursor = await db.execute(
        """INSERT INTO experiments (name, description, dimensions, yaml_path, max_cost_usd)
           VALUES (?, ?, ?, ?, ?)""",
        (
            config.name,
            config.description,
            json.dumps(config.dimensions),
            yaml_path,
            config.max_experiment_cost_usd,
        ),
    )
    experiment_id = cursor.lastrowid

    # Create configs
    config_ids = {}
    for cfg in config.configs:
        cursor = await db.execute(
            """INSERT INTO configs
               (experiment_id, name, orchestrator_model, sub_model, synthesis_model,
                max_iterations, max_tokens, budget_cap_usd, reasoning_effort,
                prompt_template_id, architecture, exec_timeout_s, restrict_builtins, extra_params)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                experiment_id,
                cfg["name"],
                cfg.get("orchestrator_model", "claude-sonnet"),
                cfg.get("sub_model", "claude-haiku"),
                cfg.get("synthesis_model", "claude-opus"),
                cfg.get("max_iterations", 20),
                cfg.get("max_tokens", 4096),
                cfg.get("budget_cap_usd"),
                cfg.get("reasoning_effort"),
                cfg.get("prompt_template_id"),
                cfg.get("architecture", "three-tier"),
                cfg.get("exec_timeout_s"),
                1 if cfg.get("restrict_builtins") else 0,
                json.dumps(cfg.get("extra_params")) if cfg.get("extra_params") else None,
            ),
        )
        config_ids[cfg["name"]] = cursor.lastrowid

    # Create queries
    query_ids = []
    for q in config.queries:
        cursor = await db.execute(
            """INSERT INTO queries
               (experiment_id, session_id, query_text, category, difficulty, expected_signals)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                experiment_id,
                q["session_id"],
                q["query_text"],
                q.get("category"),
                q.get("difficulty"),
                json.dumps(q.get("expected_signals", [])),
            ),
        )
        query_ids.append({
            "id": cursor.lastrowid,
            "session_id": q["session_id"],
            "query_text": q["query_text"],
        })

    await db.commit()

    return {
        "experiment_id": experiment_id,
        "config_ids": config_ids,
        "query_ids": query_ids,
    }


# =========================================================================
# Single Run Execution
# =========================================================================

async def run_single(run_config: RunConfig) -> RunResult:
    """
    Execute a single RLM query with the given configuration.

    Calls run_rlm_v2_streaming() directly (no HTTP), collects all events,
    extracts metrics, and saves the run to eval.db.
    """
    # Import here to avoid circular imports and allow running outside FastAPI
    # The engine imports from database.py which needs init_db() called first
    from services.rlm_v2_engine import run_rlm_v2_streaming

    db = await get_eval_db()

    # Create run row (status = running)
    cursor = await db.execute(
        """INSERT INTO runs (experiment_id, config_id, query_id, repetition, status, started_at)
           VALUES (?, ?, ?, ?, 'running', ?)""",
        (
            run_config.experiment_id,
            run_config.config_id,
            run_config.query_id,
            run_config.repetition,
            _now_iso(),
        ),
    )
    run_id = cursor.lastrowid
    await db.commit()

    # Collect all events from the streaming generator
    events = []
    start_time = time.monotonic()
    code_blocks_count = 0
    errors_count = 0
    final_content = ""
    raw_findings = ""
    stored_evidence = {}
    usage = {}
    iterations = 0
    sub_llm_calls = 0
    doc_reads = 0
    error_message = None
    status = "completed"

    try:
        async for event in run_rlm_v2_streaming(
            session_id=run_config.session_id,
            query=run_config.query_text,
            orchestrator_model=run_config.orchestrator_model,
            sub_model=run_config.sub_model,
            synthesis_model=run_config.synthesis_model,
            max_iterations=run_config.max_iterations,
            max_tokens=run_config.max_tokens,
            verbose=False,  # suppress engine logging during eval
        ):
            events.append(event)
            event_type = event.get("event", "")
            data = event.get("data", {})

            if event_type == "code_block":
                code_blocks_count += 1

            elif event_type == "exec_result":
                if data.get("error"):
                    errors_count += 1

            elif event_type == "error":
                error_message = data.get("error", "Unknown error")
                status = "failed"

            elif event_type == "complete":
                final_content = data.get("content", "")
                raw_findings = data.get("raw_findings", "")
                stored_evidence = data.get("stored_evidence", {})
                usage = data.get("usage", {})
                iterations = data.get("iterations", 0)
                sub_llm_calls = data.get("sub_llm_calls", 0)
                doc_reads = data.get("doc_reads", 0)

    except Exception as e:
        error_message = f"{type(e).__name__}: {e}"
        status = "failed"

    duration_s = time.monotonic() - start_time

    # Extract per-tier costs from usage dict
    orch = usage.get("orchestrator", {})
    sub = usage.get("sub_llm", {})
    synth = usage.get("synthesis", {})
    total_cost = usage.get("total", {}).get("cost_usd", 0.0)

    result = RunResult(
        run_id=run_id,
        status=status,
        duration_s=round(duration_s, 2),
        iterations=iterations,
        sub_llm_calls=sub_llm_calls,
        doc_reads=doc_reads,
        code_blocks_executed=code_blocks_count,
        errors_encountered=errors_count,
        orchestrator_input_tokens=orch.get("input_tokens", 0),
        orchestrator_output_tokens=orch.get("output_tokens", 0),
        orchestrator_cost_usd=orch.get("cost_usd", 0.0),
        sub_llm_input_tokens=sub.get("input_tokens", 0),
        sub_llm_output_tokens=sub.get("output_tokens", 0),
        sub_llm_cost_usd=sub.get("cost_usd", 0.0),
        synthesis_input_tokens=synth.get("input_tokens", 0),
        synthesis_output_tokens=synth.get("output_tokens", 0),
        synthesis_cost_usd=synth.get("cost_usd", 0.0),
        total_cost_usd=total_cost,
        final_content=final_content,
        raw_findings=raw_findings,
        stored_evidence=stored_evidence,
        event_log=events,
        error_message=error_message,
    )

    # Save results to eval.db
    await db.execute(
        """UPDATE runs SET
            status = ?, completed_at = ?, duration_s = ?,
            iterations = ?, sub_llm_calls = ?, doc_reads = ?,
            code_blocks_executed = ?, errors_encountered = ?,
            orchestrator_input_tokens = ?, orchestrator_output_tokens = ?,
            orchestrator_cost_usd = ?,
            sub_llm_input_tokens = ?, sub_llm_output_tokens = ?,
            sub_llm_cost_usd = ?,
            synthesis_input_tokens = ?, synthesis_output_tokens = ?,
            synthesis_cost_usd = ?,
            total_cost_usd = ?,
            final_content = ?, raw_findings = ?,
            stored_evidence = ?, event_log = ?, error_message = ?
           WHERE id = ?""",
        (
            result.status, _now_iso(), result.duration_s,
            result.iterations, result.sub_llm_calls, result.doc_reads,
            result.code_blocks_executed, result.errors_encountered,
            result.orchestrator_input_tokens, result.orchestrator_output_tokens,
            result.orchestrator_cost_usd,
            result.sub_llm_input_tokens, result.sub_llm_output_tokens,
            result.sub_llm_cost_usd,
            result.synthesis_input_tokens, result.synthesis_output_tokens,
            result.synthesis_cost_usd,
            result.total_cost_usd,
            result.final_content, result.raw_findings,
            json.dumps(result.stored_evidence) if result.stored_evidence else None,
            json.dumps(result.event_log),
            result.error_message,
            run_id,
        ),
    )

    # Update experiment total cost
    await db.execute(
        """UPDATE experiments SET total_cost_usd = total_cost_usd + ?
           WHERE id = ?""",
        (result.total_cost_usd, run_config.experiment_id),
    )
    await db.commit()

    return result


# =========================================================================
# Full Experiment Execution
# =========================================================================

async def run_experiment(
    yaml_path: str | Path,
    dry_run: bool = False,
    resume: bool = False,
) -> int:
    """
    Load a YAML experiment and execute all config x query combinations.

    Args:
        yaml_path: Path to experiment YAML file
        dry_run: If True, validate config and print plan without executing
        resume: If True, skip runs that already completed

    Returns:
        experiment_id
    """
    config = load_experiment_yaml(yaml_path)

    if dry_run:
        _print_dry_run(config)
        return -1

    # Create DB rows
    rows = await create_experiment_rows(config, str(yaml_path))
    experiment_id = rows["experiment_id"]
    config_ids = rows["config_ids"]
    query_ids = rows["query_ids"]

    db = await get_eval_db()
    await db.execute(
        "UPDATE experiments SET status = 'running' WHERE id = ?",
        (experiment_id,),
    )
    await db.commit()

    total_runs = config.total_runs
    completed = 0
    total_spent = 0.0

    print(f"\n[{experiment_id:03d}] {config.name} -- "
          f"{len(config.queries)} queries x {len(config.configs)} configs "
          f"= {total_runs} runs\n")

    # Execute: for each query x config x repetition
    for q_info in query_ids:
        for cfg_data in config.configs:
            cfg_name = cfg_data["name"]
            cfg_id = config_ids[cfg_name]

            for rep in range(1, config.repetitions + 1):
                # Budget check
                if total_spent >= config.max_experiment_cost_usd:
                    print(f"\n  Budget exceeded (${total_spent:.2f} / "
                          f"${config.max_experiment_cost_usd:.2f}). Stopping.")
                    await db.execute(
                        "UPDATE experiments SET status = 'completed', completed_at = ? WHERE id = ?",
                        (_now_iso(), experiment_id),
                    )
                    await db.commit()
                    return experiment_id

                # Resume support: check if run already exists and completed
                if resume:
                    cursor = await db.execute(
                        """SELECT id, status FROM runs
                           WHERE config_id = ? AND query_id = ? AND repetition = ?""",
                        (cfg_id, q_info["id"], rep),
                    )
                    existing = await cursor.fetchone()
                    if existing and existing["status"] == "completed":
                        completed += 1
                        print(f"  ~ {cfg_name} x {q_info['query_text'][:40]}...  "
                              f"(already completed, skipping)")
                        continue

                # Build RunConfig
                run_cfg = RunConfig(
                    config_id=cfg_id,
                    query_id=q_info["id"],
                    experiment_id=experiment_id,
                    repetition=rep,
                    orchestrator_model=cfg_data.get("orchestrator_model", "claude-sonnet"),
                    sub_model=cfg_data.get("sub_model", "claude-haiku"),
                    synthesis_model=cfg_data.get("synthesis_model", "claude-opus"),
                    max_iterations=cfg_data.get("max_iterations", 20),
                    max_tokens=cfg_data.get("max_tokens", 4096),
                    budget_cap_usd=cfg_data.get("budget_cap_usd"),
                    reasoning_effort=cfg_data.get("reasoning_effort"),
                    architecture=cfg_data.get("architecture", "three-tier"),
                    exec_timeout_s=cfg_data.get("exec_timeout_s"),
                    restrict_builtins=cfg_data.get("restrict_builtins", False),
                    session_id=q_info["session_id"],
                    query_text=q_info["query_text"],
                )

                # Print progress
                label = f"{cfg_name} x {q_info['query_text'][:40]}..."
                print(f"  ... {label}", end="", flush=True)

                try:
                    result = await run_single(run_cfg)
                    completed += 1
                    total_spent += result.total_cost_usd

                    status_char = "+" if result.status == "completed" else "X"
                    print(f"\r  {status_char} {label}  "
                          f"${result.total_cost_usd:.2f}  "
                          f"{result.iterations} iter  "
                          f"{result.sub_llm_calls} sub  "
                          f"{result.duration_s:.1f}s")

                except Exception as e:
                    completed += 1
                    print(f"\r  X {label}  ERROR: {e}")

                # Progress line
                print(f"\n  Progress: {completed}/{total_runs} runs | "
                      f"${total_spent:.2f} spent / "
                      f"${config.max_experiment_cost_usd:.2f} budget\n")

    # Mark experiment complete
    await db.execute(
        """UPDATE experiments SET status = 'completed', completed_at = ?,
           total_cost_usd = ? WHERE id = ?""",
        (_now_iso(), total_spent, experiment_id),
    )
    await db.commit()

    print(f"\nExperiment [{experiment_id:03d}] complete. "
          f"{completed} runs, ${total_spent:.2f} total cost.")

    return experiment_id


# =========================================================================
# LLM-as-Judge
# =========================================================================

async def run_llm_judge(
    run_id: int,
    judge_model: str = "claude-sonnet",
) -> JudgmentScores:
    """
    Score a completed run using LLM-as-judge (Layer 2).

    Loads the run's response, builds the judge prompt, calls the judge model,
    parses JSON scores, and saves to llm_judgments table.
    """
    from services.chat import ChatService

    db = await get_eval_db()

    # Load run data
    cursor = await db.execute(
        "SELECT * FROM runs WHERE id = ?", (run_id,)
    )
    run = await cursor.fetchone()
    if not run:
        raise ValueError(f"Run {run_id} not found")
    if run["status"] != "completed":
        raise ValueError(f"Run {run_id} status is '{run['status']}', not 'completed'")

    # Load query details (for expected_signals)
    cursor = await db.execute(
        "SELECT * FROM queries WHERE id = ?", (run["query_id"],)
    )
    query = await cursor.fetchone()

    # Load doc_info from the session's sources
    # We need session_id to get document metadata
    # For now, we pass minimal doc descriptions -- this avoids needing library.db access
    # TODO: Load actual doc_info from library.db for richer judge context
    doc_descriptions = []

    expected_signals = json.loads(query["expected_signals"]) if query["expected_signals"] else None

    # Build judge prompt
    user_prompt = build_judge_prompt(
        query=query["query_text"],
        response_text=run["final_content"] or "",
        doc_descriptions=doc_descriptions,
        expected_signals=expected_signals,
    )

    # Call judge model
    chat = ChatService(verbose=False)
    result = await chat.chat(
        model_id=judge_model,
        messages=[{"role": "user", "content": user_prompt}],
        system=JUDGE_SYSTEM_PROMPT,
        max_tokens=1024,
    )

    if not result.get("success"):
        raise RuntimeError(f"Judge call failed: {result.get('error')}")

    # Parse JSON response
    response_text = result.get("content", "")
    judge_cost = result.get("usage", {}).get("cost_usd", 0.0)

    try:
        # Strip markdown code fences if present
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            # Remove first and last lines (code fences)
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])
        scores_dict = json.loads(cleaned)
    except json.JSONDecodeError:
        raise RuntimeError(f"Judge returned invalid JSON: {response_text[:200]}")

    scores = JudgmentScores(
        run_id=run_id,
        judge_model=judge_model,
        completeness=int(scores_dict.get("completeness", 0)),
        coherence=int(scores_dict.get("coherence", 0)),
        relevance=int(scores_dict.get("relevance", 0)),
        scholarly_quality=int(scores_dict.get("scholarly_quality", 0)),
        strengths=scores_dict.get("strengths", ""),
        weaknesses=scores_dict.get("weaknesses", ""),
        notes=scores_dict.get("notes", ""),
        judge_cost_usd=judge_cost,
    )

    # Save to eval.db
    await db.execute(
        """INSERT OR REPLACE INTO llm_judgments
           (run_id, judge_model, rubric_version,
            completeness, coherence, relevance, scholarly_quality,
            strengths, weaknesses, notes, judge_cost_usd)
           VALUES (?, ?, 'v1', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id, judge_model,
            scores.completeness, scores.coherence,
            scores.relevance, scores.scholarly_quality,
            scores.strengths, scores.weaknesses,
            scores.notes, scores.judge_cost_usd,
        ),
    )
    await db.commit()

    return scores


async def judge_experiment(experiment_id: int, judge_model: str = "claude-sonnet"):
    """Score all completed runs in an experiment."""
    db = await get_eval_db()
    cursor = await db.execute(
        """SELECT r.id FROM runs r
           LEFT JOIN llm_judgments j ON j.run_id = r.id
           WHERE r.experiment_id = ? AND r.status = 'completed'
           AND j.id IS NULL""",
        (experiment_id,),
    )
    rows = await cursor.fetchall()

    print(f"Judging {len(rows)} runs for experiment {experiment_id}...")

    for i, row in enumerate(rows):
        run_id = row["id"]
        try:
            scores = await run_llm_judge(run_id, judge_model)
            print(f"  [{i+1}/{len(rows)}] Run {run_id}: "
                  f"comp={scores.completeness} coh={scores.coherence} "
                  f"rel={scores.relevance} qual={scores.scholarly_quality} "
                  f"(${scores.judge_cost_usd:.4f})")
        except Exception as e:
            print(f"  [{i+1}/{len(rows)}] Run {run_id}: ERROR -- {e}")


# =========================================================================
# Dry Run Display
# =========================================================================

def _print_dry_run(config: ExperimentConfig):
    """Print experiment plan without executing."""
    print(f"\n{'='*60}")
    print(f"DRY RUN: {config.name}")
    print(f"{'='*60}")
    print(f"Description: {config.description}")
    print(f"Dimensions:  {', '.join(config.dimensions)}")
    print(f"Repetitions: {config.repetitions}")
    print(f"Max budget:  ${config.max_experiment_cost_usd:.2f}")
    print(f"\nQueries ({len(config.queries)}):")
    for q in config.queries:
        cat = q.get('category', '?')
        diff = q.get('difficulty', '?')
        print(f"  [{cat}/{diff}] {q['query_text'][:60]}...")
        print(f"    session: {q['session_id']}")

    print(f"\nConfigs ({len(config.configs)}):")
    for cfg in config.configs:
        orch = cfg.get('orchestrator_model', 'claude-sonnet')
        sub = cfg.get('sub_model', 'claude-haiku')
        synth = cfg.get('synthesis_model', 'claude-opus')
        print(f"  {cfg['name']}: orch={orch}, sub={sub}, synth={synth}")
        if cfg.get('budget_cap_usd'):
            print(f"    budget_cap: ${cfg['budget_cap_usd']}")
        if cfg.get('reasoning_effort'):
            print(f"    reasoning_effort: {cfg['reasoning_effort']}")
        if cfg.get('architecture', 'three-tier') != 'three-tier':
            print(f"    architecture: {cfg['architecture']}")

    total = config.total_runs
    est = config.estimate_cost(avg_cost_per_run=0.50)
    print(f"\nTotal runs: {total}")
    print(f"Estimated cost: ${est:.2f} (at $0.50/run avg)")
    print(f"{'='*60}\n")
