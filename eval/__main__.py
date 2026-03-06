"""
Eval CLI
========
Entry point: python -m eval <command>

Commands:
  run <yaml_path>           Run an experiment from YAML definition
  run <yaml_path> --dry-run Validate and preview without executing
  run <yaml_path> --resume  Resume, skipping completed runs
  list                      List all experiments
  status <experiment_id>    Show experiment status and run summary
  judge <experiment_id>     Run LLM-as-judge on completed runs
  fidelity <experiment_id>  Run programmatic fidelity checks (Layer 1)
  cost-estimate <yaml_path> Estimate experiment cost without running
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add backend to path so engine imports work
# (eval runs from project root: python -m eval ...)
BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Load API keys — server.py does this at import time, but eval CLI bypasses it
from dotenv import load_dotenv

local_env = BACKEND_DIR / ".env"
shared_env = Path(r"C:\Users\bhara\dev\.env")
if local_env.exists():
    load_dotenv(local_env, override=True)
elif shared_env.exists():
    load_dotenv(shared_env, override=True)


async def cmd_run(args):
    """Run an experiment."""
    # Initialize library.db (needed by the RLM engine for document loading)
    from database import init_db

    # Import after path setup
    from eval.harness import run_experiment

    if not args.dry_run:
        await init_db()

    experiment_id = await run_experiment(
        yaml_path=args.yaml_path,
        dry_run=args.dry_run,
        resume=args.resume,
    )

    if not args.dry_run:
        from eval.db import close_eval_db
        from database import close_db
        await close_eval_db()
        await close_db()


async def cmd_list(args):
    """List all experiments."""
    from eval.db import get_eval_db, close_eval_db

    db = await get_eval_db()
    cursor = await db.execute(
        """SELECT e.id, e.name, e.status, e.total_cost_usd, e.created_at,
                  COUNT(r.id) as run_count,
                  SUM(CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END) as completed_count
           FROM experiments e
           LEFT JOIN runs r ON r.experiment_id = e.id
           GROUP BY e.id
           ORDER BY e.created_at DESC"""
    )
    rows = await cursor.fetchall()

    if not rows:
        print("No experiments found.")
        await close_eval_db()
        return

    print(f"\n{'ID':>4}  {'Status':<10}  {'Runs':>10}  {'Cost':>8}  {'Name'}")
    print(f"{'-'*4}  {'-'*10}  {'-'*10}  {'-'*8}  {'-'*30}")
    for row in rows:
        completed = row["completed_count"] or 0
        total = row["run_count"] or 0
        runs_str = f"{completed}/{total}"
        cost_str = f"${row['total_cost_usd']:.2f}" if row['total_cost_usd'] else "$0.00"
        print(f"{row['id']:>4}  {row['status']:<10}  {runs_str:>10}  {cost_str:>8}  {row['name']}")

    print()
    await close_eval_db()


async def cmd_status(args):
    """Show detailed experiment status."""
    from eval.db import get_eval_db, close_eval_db

    db = await get_eval_db()

    # Experiment info
    cursor = await db.execute(
        "SELECT * FROM experiments WHERE id = ?", (args.experiment_id,)
    )
    exp = await cursor.fetchone()
    if not exp:
        print(f"Experiment {args.experiment_id} not found.")
        await close_eval_db()
        return

    print(f"\n{'='*60}")
    print(f"Experiment [{exp['id']:03d}]: {exp['name']}")
    print(f"{'='*60}")
    print(f"Status:      {exp['status']}")
    print(f"Dimensions:  {exp['dimensions']}")
    print(f"Total cost:  ${exp['total_cost_usd']:.2f} / ${exp['max_cost_usd']:.2f}")
    print(f"Created:     {exp['created_at']}")
    if exp['completed_at']:
        print(f"Completed:   {exp['completed_at']}")

    # Per-config summary
    cursor = await db.execute(
        """SELECT c.name, c.orchestrator_model, c.sub_model, c.synthesis_model,
                  COUNT(r.id) as runs,
                  SUM(CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END) as completed,
                  AVG(r.total_cost_usd) as avg_cost,
                  AVG(r.iterations) as avg_iter,
                  AVG(r.sub_llm_calls) as avg_sub,
                  AVG(r.duration_s) as avg_dur
           FROM configs c
           LEFT JOIN runs r ON r.config_id = c.id
           WHERE c.experiment_id = ?
           GROUP BY c.id
           ORDER BY c.name""",
        (args.experiment_id,),
    )
    configs = await cursor.fetchall()

    if configs:
        print(f"\nConfig Summary:")
        print(f"  {'Config':<20} {'Runs':>5} {'AvgCost':>8} {'AvgIter':>8} {'AvgSub':>7} {'AvgDur':>7}")
        print(f"  {'-'*20} {'-'*5} {'-'*8} {'-'*8} {'-'*7} {'-'*7}")
        for c in configs:
            avg_cost = f"${c['avg_cost']:.2f}" if c['avg_cost'] else "-"
            avg_iter = f"{c['avg_iter']:.1f}" if c['avg_iter'] else "-"
            avg_sub = f"{c['avg_sub']:.1f}" if c['avg_sub'] else "-"
            avg_dur = f"{c['avg_dur']:.1f}s" if c['avg_dur'] else "-"
            completed = c['completed'] or 0
            total = c['runs'] or 0
            print(f"  {c['name']:<20} {completed}/{total:>3} {avg_cost:>8} "
                  f"{avg_iter:>8} {avg_sub:>7} {avg_dur:>7}")

    # Judgment summary (if any)
    cursor = await db.execute(
        """SELECT c.name,
                  AVG(j.completeness) as avg_comp,
                  AVG(j.coherence) as avg_coh,
                  AVG(j.relevance) as avg_rel,
                  AVG(j.scholarly_quality) as avg_qual
           FROM llm_judgments j
           JOIN runs r ON r.id = j.run_id
           JOIN configs c ON c.id = r.config_id
           WHERE r.experiment_id = ?
           GROUP BY c.id
           ORDER BY c.name""",
        (args.experiment_id,),
    )
    judgments = await cursor.fetchall()

    if judgments:
        print(f"\nLLM Judge Scores (avg):")
        print(f"  {'Config':<20} {'Complete':>8} {'Cohere':>7} {'Relev':>6} {'Quality':>8} {'Mean':>6}")
        print(f"  {'-'*20} {'-'*8} {'-'*7} {'-'*6} {'-'*8} {'-'*6}")
        for j in judgments:
            mean = (j['avg_comp'] + j['avg_coh'] + j['avg_rel'] + j['avg_qual']) / 4
            print(f"  {j['name']:<20} {j['avg_comp']:>8.1f} {j['avg_coh']:>7.1f} "
                  f"{j['avg_rel']:>6.1f} {j['avg_qual']:>8.1f} {mean:>6.1f}")

    # Fidelity check summary (if any)
    cursor = await db.execute(
        """SELECT c.name,
                  AVG(fc.quote_match_rate) as avg_quote,
                  AVG(fc.page_accuracy) as avg_page,
                  AVG(fc.attribution_accuracy) as avg_attr,
                  AVG(fc.synthesis_fidelity) as avg_synth,
                  COUNT(fc.id) as check_count
           FROM fidelity_checks fc
           JOIN runs r ON r.id = fc.run_id
           JOIN configs c ON c.id = r.config_id
           WHERE r.experiment_id = ?
           GROUP BY c.id
           ORDER BY c.name""",
        (args.experiment_id,),
    )
    fidelity_rows = await cursor.fetchall()

    if fidelity_rows:
        print(f"\nFidelity Checks (avg):")
        print(f"  {'Config':<20} {'Quotes':>7} {'Pages':>6} {'Attr':>6} {'Synth':>6} {'Comp':>6}  {'N':>3}")
        print(f"  {'-'*20} {'-'*7} {'-'*6} {'-'*6} {'-'*6} {'-'*6}  {'-'*3}")
        for f in fidelity_rows:
            # Compute composite as weighted average (same weights as FidelityReport)
            scores, weights = [], []
            if f['avg_quote'] is not None:
                scores.append(f['avg_quote']); weights.append(2.0)
            if f['avg_page'] is not None:
                scores.append(f['avg_page']); weights.append(1.0)
            if f['avg_attr'] is not None:
                scores.append(f['avg_attr']); weights.append(1.5)
            if f['avg_synth'] is not None:
                scores.append(f['avg_synth']); weights.append(1.5)
            composite = sum(s * w for s, w in zip(scores, weights)) / sum(weights) if weights else 0
            print(
                f"  {f['name']:<20} "
                f"{f['avg_quote']:>6.0%} "
                f"{f['avg_page']:>5.0%} "
                f"{f['avg_attr']:>5.0%} "
                f"{f['avg_synth']:>5.0%} "
                f"{composite:>5.0%}  "
                f"{f['check_count']:>3}"
            )

    print()
    await close_eval_db()


async def cmd_judge(args):
    """Run LLM-as-judge on experiment runs."""
    from database import init_db, close_db
    from eval.harness import judge_experiment
    from eval.db import close_eval_db

    await init_db()
    await judge_experiment(args.experiment_id, args.model)
    await close_eval_db()
    await close_db()


async def cmd_fidelity(args):
    """Run programmatic fidelity checks on experiment runs."""
    from database import init_db, close_db
    from eval.fidelity import check_experiment
    from eval.db import close_eval_db

    await init_db()
    await check_experiment(args.experiment_id)
    await close_eval_db()
    await close_db()


async def cmd_cost_estimate(args):
    """Estimate experiment cost from YAML."""
    from eval.harness import load_experiment_yaml

    config = load_experiment_yaml(args.yaml_path)

    # Use model pricing to estimate
    # Rough estimates based on typical run costs per orchestrator model
    COST_ESTIMATES = {
        "claude-sonnet": 0.80,
        "claude-opus": 2.50,
        "deepseek-v3": 0.15,
        "deepseek-v3.1": 0.12,
        "grok-code": 0.20,
        "qwen3-coder": 0.18,
        "gemini-flash": 0.10,
        "gemini-3-flash": 0.30,
        "gpt-4.1-mini": 0.25,
        "gpt-5": 0.60,
    }

    print(f"\nCost Estimate: {config.name}")
    print(f"{'='*50}")

    total_est = 0.0
    for cfg in config.configs:
        orch = cfg.get("orchestrator_model", "claude-sonnet")
        per_run = COST_ESTIMATES.get(orch, 0.50)
        runs = len(config.queries) * config.repetitions
        est = per_run * runs
        total_est += est
        print(f"  {cfg['name']:<25} {runs} runs x ${per_run:.2f} = ${est:.2f}")

    print(f"\n  {'TOTAL ESTIMATE':<25} ${total_est:.2f}")
    print(f"  {'Budget cap':<25} ${config.max_experiment_cost_usd:.2f}")

    if total_est > config.max_experiment_cost_usd:
        print(f"\n  WARNING: Estimate exceeds budget by ${total_est - config.max_experiment_cost_usd:.2f}")
    else:
        print(f"\n  OK: Within budget (${config.max_experiment_cost_usd - total_est:.2f} headroom)")
    print()


def main():
    parser = argparse.ArgumentParser(
        prog="python -m eval",
        description="Scholia RLM Evaluation System",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run
    run_parser = subparsers.add_parser("run", help="Run an experiment")
    run_parser.add_argument("yaml_path", help="Path to experiment YAML")
    run_parser.add_argument("--dry-run", action="store_true", help="Preview without executing")
    run_parser.add_argument("--resume", action="store_true", help="Skip completed runs")

    # list
    subparsers.add_parser("list", help="List all experiments")

    # status
    status_parser = subparsers.add_parser("status", help="Show experiment status")
    status_parser.add_argument("experiment_id", type=int, help="Experiment ID")

    # judge
    judge_parser = subparsers.add_parser("judge", help="Run LLM-as-judge scoring")
    judge_parser.add_argument("experiment_id", type=int, help="Experiment ID")
    judge_parser.add_argument("--model", default="claude-sonnet", help="Judge model (default: claude-sonnet)")

    # fidelity
    fidelity_parser = subparsers.add_parser("fidelity", help="Run fidelity checks (Layer 1)")
    fidelity_parser.add_argument("experiment_id", type=int, help="Experiment ID")

    # cost-estimate
    cost_parser = subparsers.add_parser("cost-estimate", help="Estimate experiment cost")
    cost_parser.add_argument("yaml_path", help="Path to experiment YAML")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Dispatch to async handler
    handler = {
        "run": cmd_run,
        "list": cmd_list,
        "status": cmd_status,
        "judge": cmd_judge,
        "fidelity": cmd_fidelity,
        "cost-estimate": cmd_cost_estimate,
    }[args.command]

    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
