"""
Eval Models
============
Dataclasses for experiment configuration, run results, and fidelity reports.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExperimentConfig:
    """Parsed from YAML experiment definition."""
    name: str
    description: str
    dimensions: list[str]
    queries: list[dict]          # [{session_id, query_text, category, difficulty, expected_signals}]
    configs: list[dict]          # [{name, orchestrator_model, sub_model, ...}]
    repetitions: int = 1
    max_experiment_cost_usd: float = 50.0

    @property
    def total_runs(self) -> int:
        return len(self.queries) * len(self.configs) * self.repetitions

    def estimate_cost(self, avg_cost_per_run: float = 1.0) -> float:
        """Rough cost estimate based on average cost per run."""
        return self.total_runs * avg_cost_per_run


@dataclass
class RunConfig:
    """Configuration for a single RLM execution."""
    config_id: int
    query_id: int
    experiment_id: int
    repetition: int = 1
    # Model selection
    orchestrator_model: str = "claude-sonnet"
    sub_model: str = "claude-haiku"
    synthesis_model: str = "claude-opus"
    # Engine params
    max_iterations: int = 20
    max_tokens: int = 4096
    budget_cap_usd: Optional[float] = None
    reasoning_effort: Optional[str] = None
    # Prompt
    system_prompt: Optional[str] = None
    # Architecture
    architecture: str = "three-tier"
    exec_timeout_s: Optional[int] = None
    restrict_builtins: bool = False
    # Query details (loaded from DB)
    session_id: str = ""
    query_text: str = ""


@dataclass
class RunResult:
    """Extracted metrics from a completed RLM run."""
    run_id: int
    status: str                     # completed | failed | aborted
    duration_s: float = 0.0
    # Iteration metrics
    iterations: int = 0
    sub_llm_calls: int = 0
    doc_reads: int = 0
    code_blocks_executed: int = 0
    errors_encountered: int = 0
    # Per-tier costs
    orchestrator_input_tokens: int = 0
    orchestrator_output_tokens: int = 0
    orchestrator_cost_usd: float = 0.0
    sub_llm_input_tokens: int = 0
    sub_llm_output_tokens: int = 0
    sub_llm_cost_usd: float = 0.0
    synthesis_input_tokens: int = 0
    synthesis_output_tokens: int = 0
    synthesis_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    # Content
    final_content: str = ""
    raw_findings: str = ""
    stored_evidence: Optional[dict] = None
    event_log: list[dict] = field(default_factory=list)
    error_message: Optional[str] = None


@dataclass
class FidelityReport:
    """Results of programmatic fidelity checks (Layer 1)."""
    run_id: int
    # Quote matching
    total_quotes: int = 0
    matched_quotes: int = 0
    quote_match_rate: float = 0.0
    # Page accuracy
    total_page_refs: int = 0
    correct_page_refs: int = 0
    page_accuracy: float = 0.0
    # Source attribution
    total_attributions: int = 0
    matched_attributions: int = 0
    attribution_accuracy: float = 0.0
    # Synthesis fidelity
    total_claims: int = 0
    traceable_claims: int = 0
    synthesis_fidelity: float = 0.0
    # Per-check details
    details: Optional[dict] = None

    @property
    def composite_score(self) -> float:
        """Weighted average of all fidelity dimensions (0-1)."""
        scores = []
        weights = []
        if self.total_quotes > 0:
            scores.append(self.quote_match_rate)
            weights.append(2.0)  # quotes matter most
        if self.total_page_refs > 0:
            scores.append(self.page_accuracy)
            weights.append(1.0)
        if self.total_attributions > 0:
            scores.append(self.attribution_accuracy)
            weights.append(1.5)
        if self.total_claims > 0:
            scores.append(self.synthesis_fidelity)
            weights.append(1.5)
        if not scores:
            return 0.0
        return sum(s * w for s, w in zip(scores, weights)) / sum(weights)


@dataclass
class JudgmentScores:
    """LLM-as-judge quality scores (Layer 2)."""
    run_id: int
    judge_model: str
    completeness: int = 0       # 1-5
    coherence: int = 0          # 1-5
    relevance: int = 0          # 1-5
    scholarly_quality: int = 0  # 1-5
    strengths: str = ""
    weaknesses: str = ""
    notes: str = ""
    judge_cost_usd: float = 0.0

    @property
    def mean_score(self) -> float:
        """Average across all 4 dimensions."""
        return (
            self.completeness + self.coherence
            + self.relevance + self.scholarly_quality
        ) / 4.0
