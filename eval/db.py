"""
Eval Database
=============
SQLite schema and connection for eval.db.

Follows the same aiosqlite singleton pattern as backend/database.py,
but writes to a separate database (data/eval.db) to isolate
evaluation data from production library.db.
"""

import aiosqlite
from pathlib import Path
from typing import Optional

# eval.db lives alongside library.db in data/
DATA_DIR = Path(__file__).parent.parent / "data"
EVAL_DB_PATH = DATA_DIR / "eval.db"

# Global connection (initialized explicitly, not via app lifespan)
_eval_db: Optional[aiosqlite.Connection] = None


async def get_eval_db() -> aiosqlite.Connection:
    """
    Get the eval database connection.
    Initializes on first call (unlike library.db which requires explicit init).
    """
    global _eval_db
    if _eval_db is None:
        _eval_db = await init_eval_db()
    return _eval_db


async def init_eval_db() -> aiosqlite.Connection:
    """Create connection, enable WAL, create schema."""
    global _eval_db

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _eval_db = await aiosqlite.connect(EVAL_DB_PATH)
    _eval_db.row_factory = aiosqlite.Row
    await _eval_db.execute("PRAGMA foreign_keys = ON")
    await _eval_db.execute("PRAGMA journal_mode = WAL")

    await _create_schema()
    return _eval_db


async def close_eval_db():
    """Close connection cleanly."""
    global _eval_db
    if _eval_db:
        await _eval_db.close()
        _eval_db = None


async def _create_schema():
    """Create all eval tables if they don't exist."""
    db = _eval_db

    # Experiments — a named evaluation run
    await db.execute("""
        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            dimensions TEXT,           -- JSON array of dimension names
            yaml_path TEXT,            -- path to source YAML file
            status TEXT DEFAULT 'pending',  -- pending | running | completed | failed
            max_cost_usd REAL DEFAULT 50.0,
            total_cost_usd REAL DEFAULT 0.0,
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        )
    """)

    # Configs — one row per configuration variant to test
    await db.execute("""
        CREATE TABLE IF NOT EXISTS configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL REFERENCES experiments(id),
            name TEXT NOT NULL,
            orchestrator_model TEXT NOT NULL DEFAULT 'claude-sonnet',
            sub_model TEXT NOT NULL DEFAULT 'claude-haiku',
            synthesis_model TEXT NOT NULL DEFAULT 'claude-opus',
            max_iterations INTEGER DEFAULT 20,
            max_tokens INTEGER DEFAULT 4096,
            budget_cap_usd REAL,        -- NULL = no cap
            reasoning_effort TEXT,      -- low | medium | high | NULL
            prompt_template_id INTEGER REFERENCES prompt_templates(id),
            architecture TEXT DEFAULT 'three-tier',  -- three-tier | two-tier
            exec_timeout_s INTEGER,     -- NULL = default
            restrict_builtins INTEGER DEFAULT 0,
            extra_params TEXT,          -- JSON for future extensibility
            UNIQUE(experiment_id, name)
        )
    """)

    # Prompt templates — custom system prompt variations
    await db.execute("""
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            system_prompt TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Queries — test corpus
    await db.execute("""
        CREATE TABLE IF NOT EXISTS queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL REFERENCES experiments(id),
            session_id TEXT NOT NULL,
            query_text TEXT NOT NULL,
            category TEXT,              -- factual | analytical | comparative | synthesis
            difficulty TEXT,            -- easy | moderate | hard
            expected_signals TEXT,      -- JSON array of expected content signals
            UNIQUE(experiment_id, session_id, query_text)
        )
    """)

    # Runs — one row per execution (config × query)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL REFERENCES experiments(id),
            config_id INTEGER NOT NULL REFERENCES configs(id),
            query_id INTEGER NOT NULL REFERENCES queries(id),
            repetition INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',  -- pending | running | completed | failed | aborted
            -- Timing
            started_at TEXT,
            completed_at TEXT,
            duration_s REAL,
            -- Metrics
            iterations INTEGER,
            sub_llm_calls INTEGER,
            doc_reads INTEGER,
            code_blocks_executed INTEGER,
            errors_encountered INTEGER,
            -- Per-tier token counts and costs
            orchestrator_input_tokens INTEGER DEFAULT 0,
            orchestrator_output_tokens INTEGER DEFAULT 0,
            orchestrator_cost_usd REAL DEFAULT 0.0,
            sub_llm_input_tokens INTEGER DEFAULT 0,
            sub_llm_output_tokens INTEGER DEFAULT 0,
            sub_llm_cost_usd REAL DEFAULT 0.0,
            synthesis_input_tokens INTEGER DEFAULT 0,
            synthesis_output_tokens INTEGER DEFAULT 0,
            synthesis_cost_usd REAL DEFAULT 0.0,
            total_cost_usd REAL DEFAULT 0.0,
            -- Content
            final_content TEXT,
            raw_findings TEXT,
            stored_evidence TEXT,       -- JSON
            event_log TEXT,             -- JSON array of all events
            error_message TEXT,
            UNIQUE(config_id, query_id, repetition)
        )
    """)

    # LLM judgments — automated quality scores (Layer 2)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS llm_judgments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            judge_model TEXT NOT NULL,
            rubric_version TEXT DEFAULT 'v1',
            -- 4 quality dimensions (1-5 scale)
            completeness INTEGER,
            coherence INTEGER,
            relevance INTEGER,
            scholarly_quality INTEGER,
            -- Qualitative
            strengths TEXT,
            weaknesses TEXT,
            notes TEXT,
            -- Meta
            judge_cost_usd REAL DEFAULT 0.0,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(run_id, judge_model, rubric_version)
        )
    """)

    # Fidelity checks — programmatic verification (Layer 1)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS fidelity_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            -- Quote matching
            total_quotes INTEGER DEFAULT 0,
            matched_quotes INTEGER DEFAULT 0,
            quote_match_rate REAL,
            -- Page accuracy
            total_page_refs INTEGER DEFAULT 0,
            correct_page_refs INTEGER DEFAULT 0,
            page_accuracy REAL,
            -- Source attribution
            total_attributions INTEGER DEFAULT 0,
            matched_attributions INTEGER DEFAULT 0,
            attribution_accuracy REAL,
            -- Synthesis fidelity
            total_claims INTEGER DEFAULT 0,
            traceable_claims INTEGER DEFAULT 0,
            synthesis_fidelity REAL,
            -- Detail
            details TEXT,               -- JSON with per-check breakdown
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(run_id)
        )
    """)

    # Human evaluations — manual review scores (Layer 3)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS human_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            reviewer TEXT DEFAULT 'bharat',
            -- Scores (1-5)
            interpretive_accuracy INTEGER,
            nuance_preservation INTEGER,
            overall_quality INTEGER,
            -- Qualitative
            notes TEXT,
            preference_rank INTEGER,    -- within experiment (1 = best)
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(run_id, reviewer)
        )
    """)

    # Indexes for common queries
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_experiment
        ON runs(experiment_id)
    """)
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_config
        ON runs(config_id)
    """)
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_status
        ON runs(status)
    """)
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_configs_experiment
        ON configs(experiment_id)
    """)

    await db.commit()
