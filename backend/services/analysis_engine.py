"""
Analysis Engine
===============
Runs one-shot LLM analyses against source content (e.g., video transcripts).
Produces structured markdown (Summary, Key Claims) stored in source_analyses table.

Uses chat/config.py for model registry and API keys — but does NOT use ChatService,
since analysis is a one-shot prompt/response pattern, not multi-turn chat.
"""

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Optional

import anthropic
import openai

from services.chat.config import CHAT_MODELS, get_api_key

logger = logging.getLogger(__name__)


# ============================================================
# Default model + fallback chain
# ============================================================
# Primary: gpt-5.4 (OpenAI direct, via OPENAI_COUNCIL_KEY).
# Fallback: x-ai/grok-4.20 via OpenRouter (OPENROUTER_API_KEY) — used when the
# primary model errors out (e.g. credit exhaustion, rate limit, 5xx).
# Anthropic Claude models are intentionally NOT in the fallback chain — the Max
# subscription does not grant API credit, and direct Anthropic billing was the
# original failure mode this chain is defending against.

DEFAULT_ANALYSIS_MODEL = "gpt-5.4"
ANALYSIS_FALLBACK_MODEL = "grok-4.20"


# ============================================================
# Analysis prompt templates
# ============================================================
# Ported from pod-transcriber, adapted for Scholia's [TIMESTAMP] format.

ANALYSIS_PROMPTS = {
    "summary": {
        "display_name": "Summary",
        "description": "Condensed overview with key points and notable quotes",
        "max_tokens": 2500,
        "template": """You are analyzing a video transcript. Provide a comprehensive but concise summary.

## Your Task

1. **Overview** (2-3 sentences)
   What is this conversation about? Who are the speakers and what's the context?

2. **Key Points** (5-10 bullets)
   The most important insights, claims, arguments, or takeaways. Focus on substance over pleasantries.

3. **Notable Quotes** (3-5)
   Memorable, quotable, or particularly insightful moments. For each quote, reference the approximate timestamp using the format [TIMESTAMP HH:MM:SS] so the reader can jump to that moment.

4. **Structure**
   Brief outline of how the conversation flows — what topics are covered and in what order?

## Guidelines

- Be specific, not generic. "They discussed AI" is useless; "Altman argued that GPT-5 will achieve X because Y" is useful.
- Distinguish between claims, opinions, and facts.
- If speakers disagree, note the disagreement.
- Prioritize novel insights over well-known information.
- When referencing specific moments, include the timestamp in [TIMESTAMP HH:MM:SS] format.

## Video Info

**Title:** {title}
**Channel:** {channel}
**Duration:** {duration}

---

TRANSCRIPT:

{transcript}""",
    },
    "key_claims": {
        "display_name": "Key Claims",
        "description": "Extractable insights, arguments, and quotable statements",
        "max_tokens": 3000,
        "template": """You are analyzing a video transcript to extract its most valuable claims and insights.

## Your Task

Extract **specific, quotable claims** from this conversation. For each claim:

1. **The Claim**: State it clearly and precisely (paraphrase or quote)
2. **Who Said It**: Which speaker made this claim
3. **Type**: Categorize as one of:
   - Prediction (about future)
   - Argument (logical reasoning)
   - Insight (novel framing or understanding)
   - Fact (verifiable information)
   - Opinion (subjective view)
   - Recommendation (advice or suggestion)
4. **Context**: Brief context for why this came up. Include a [TIMESTAMP HH:MM:SS] reference so the reader can jump to the relevant moment in the transcript.

## Guidelines

- Aim for 10-20 claims depending on conversation length and density
- Prioritize novelty and specificity — skip generic statements
- Include claims you might disagree with if they're clearly articulated
- If a claim is surprising or counterintuitive, note that
- Preserve the speaker's framing — don't sanitize controversial takes
- Always include a timestamp reference in the Context field

## Format

For each claim:

### [Brief title]

**Claim:** [The claim itself]
**Speaker:** [Who said it]
**Type:** [Prediction/Argument/Insight/Fact/Opinion/Recommendation]
**Context:** [1-2 sentences of context, including [TIMESTAMP HH:MM:SS] reference]

---

## Video Info

**Title:** {title}
**Channel:** {channel}
**Duration:** {duration}

---

TRANSCRIPT:

{transcript}""",
    },
}


# ============================================================
# Data types
# ============================================================

@dataclass
class AnalysisResult:
    """Result from running a single analysis."""
    analysis_type: str
    display_name: str
    content: str
    model: str
    tokens_input: int
    tokens_output: int
    cost_usd: float


@dataclass
class CostEstimate:
    """Pre-flight cost estimate for a set of analyses."""
    analyses: list[dict]  # [{type, display_name, estimated_cost}]
    total_estimated_cost: float
    model_display_name: str
    word_count: int


# ============================================================
# Core functions
# ============================================================

def list_available_analyses() -> list[dict]:
    """Return available analysis types with display names and descriptions."""
    return [
        {
            "type": analysis_type,
            "display_name": config["display_name"],
            "description": config["description"],
        }
        for analysis_type, config in ANALYSIS_PROMPTS.items()
    ]


def estimate_cost(
    transcript_content: str,
    analysis_types: list[str],
    model_id: str = DEFAULT_ANALYSIS_MODEL,
) -> CostEstimate:
    """
    Pre-flight cost estimate based on transcript word count and model pricing.

    Estimates input tokens as ~1.3 tokens per word (conservative for English text),
    plus prompt overhead (~500 tokens). Output estimated from max_tokens.
    """
    model_config = CHAT_MODELS.get(model_id)
    if not model_config:
        raise ValueError(f"Unknown model: {model_id}")

    pricing = model_config["pricing"]
    word_count = len(transcript_content.split())

    # Estimate input tokens: ~1.3 tokens/word for transcript + ~500 for prompt template
    estimated_input_tokens = int(word_count * 1.3) + 500

    analyses = []
    total_cost = 0.0

    for analysis_type in analysis_types:
        prompt_config = ANALYSIS_PROMPTS.get(analysis_type)
        if not prompt_config:
            continue

        max_output = prompt_config["max_tokens"]
        # Estimate output as ~70% of max_tokens (typical for structured output)
        estimated_output = int(max_output * 0.7)

        input_cost = (estimated_input_tokens / 1_000_000) * pricing["input"]
        output_cost = (estimated_output / 1_000_000) * pricing["output"]
        estimated_cost = round(input_cost + output_cost, 4)

        analyses.append({
            "type": analysis_type,
            "display_name": prompt_config["display_name"],
            "estimated_cost": estimated_cost,
        })
        total_cost += estimated_cost

    return CostEstimate(
        analyses=analyses,
        total_estimated_cost=round(total_cost, 4),
        model_display_name=model_config["display_name"],
        word_count=word_count,
    )


def _build_prompt(
    analysis_type: str,
    transcript_content: str,
    metadata: Optional[dict] = None,
) -> tuple[str, int]:
    """
    Build the filled prompt from template and transcript.

    Returns (filled_prompt, max_tokens).
    """
    prompt_config = ANALYSIS_PROMPTS.get(analysis_type)
    if not prompt_config:
        raise ValueError(f"Unknown analysis type: {analysis_type}")

    metadata = metadata or {}
    title = metadata.get("title", "Unknown")
    channel = metadata.get("channel", "Unknown")
    duration = metadata.get("duration_formatted", "Unknown")

    # Truncate transcript if too long (~180K chars ≈ 45K tokens, leaving room for output)
    max_chars = 180_000
    if len(transcript_content) > max_chars:
        original_len = len(transcript_content)
        transcript_content = transcript_content[:max_chars] + "\n\n[... transcript truncated for length]"
        logger.warning(
            f"Transcript truncated from {original_len} to {max_chars} chars "
            f"for {analysis_type} analysis"
        )

    filled = prompt_config["template"].format(
        transcript=transcript_content,
        title=title,
        channel=channel,
        duration=duration,
    )

    return filled, prompt_config["max_tokens"]


def _call_anthropic(
    prompt: str,
    model: str,
    max_tokens: int,
    api_key: str,
) -> tuple[str, int, int]:
    """
    Make a synchronous Anthropic API call.

    Returns (response_text, input_tokens, output_tokens).
    """
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text
    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens

    return response_text, input_tokens, output_tokens


def _call_openai(
    prompt: str,
    model: str,
    max_tokens: int,
    api_key: str,
) -> tuple[str, int, int]:
    """
    Make a synchronous OpenAI API call.

    GPT-5.x and reasoning models (o1/o3/o4) reject `max_tokens` and require
    `max_completion_tokens` instead. Older chat models still use `max_tokens`.

    Returns (response_text, input_tokens, output_tokens).
    """
    client = openai.OpenAI(api_key=api_key)

    is_new_model = model.startswith(("gpt-5", "o1", "o3", "o4"))
    token_param = "max_completion_tokens" if is_new_model else "max_tokens"

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        **{token_param: max_tokens},
    )

    response_text = response.choices[0].message.content
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0

    return response_text, input_tokens, output_tokens


def _call_openrouter(
    prompt: str,
    model: str,
    max_tokens: int,
    api_key: str,
) -> tuple[str, int, int]:
    """
    Make a synchronous OpenRouter API call (OpenAI-compatible).

    Returns (response_text, input_tokens, output_tokens).
    """
    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = response.choices[0].message.content
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0

    return response_text, input_tokens, output_tokens


def run_analysis_sync(
    analysis_type: str,
    transcript_content: str,
    model_id: str = DEFAULT_ANALYSIS_MODEL,
    metadata: Optional[dict] = None,
) -> AnalysisResult:
    """
    Run a single analysis synchronously (call from thread pool for async).

    Args:
        analysis_type: Key into ANALYSIS_PROMPTS (e.g., "summary", "key_claims")
        transcript_content: The full transcript text with [TIMESTAMP] markers
        model_id: Key into CHAT_MODELS (e.g., "gpt-5.4")
        metadata: Optional dict with title, channel, duration_formatted

    Returns:
        AnalysisResult with content, token counts, and cost
    """
    model_config = CHAT_MODELS.get(model_id)
    if not model_config:
        raise ValueError(f"Unknown model: {model_id}")

    provider = model_config["provider"]
    model_name = model_config["model"]
    pricing = model_config["pricing"]

    api_key = get_api_key(provider)
    if not api_key:
        raise ValueError(f"No API key configured for provider: {provider}")

    # Build the prompt
    filled_prompt, max_tokens = _build_prompt(analysis_type, transcript_content, metadata)

    prompt_config = ANALYSIS_PROMPTS[analysis_type]

    logger.info(
        f"Running {analysis_type} analysis with {model_config['display_name']} "
        f"(~{len(filled_prompt)} chars)"
    )

    # Call the appropriate provider
    if provider == "anthropic":
        response_text, input_tokens, output_tokens = _call_anthropic(
            filled_prompt, model_name, max_tokens, api_key
        )
    elif provider == "openai":
        response_text, input_tokens, output_tokens = _call_openai(
            filled_prompt, model_name, max_tokens, api_key
        )
    elif provider == "openrouter":
        response_text, input_tokens, output_tokens = _call_openrouter(
            filled_prompt, model_name, max_tokens, api_key
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Calculate cost
    cost_usd = round(
        (input_tokens / 1_000_000) * pricing["input"]
        + (output_tokens / 1_000_000) * pricing["output"],
        6,
    )

    logger.info(
        f"Completed {analysis_type}: {input_tokens} in / {output_tokens} out, ${cost_usd}"
    )

    return AnalysisResult(
        analysis_type=analysis_type,
        display_name=prompt_config["display_name"],
        content=response_text,
        model=model_name,
        tokens_input=input_tokens,
        tokens_output=output_tokens,
        cost_usd=cost_usd,
    )


def run_analysis_with_fallback(
    analysis_type: str,
    transcript_content: str,
    model_id: str = DEFAULT_ANALYSIS_MODEL,
    metadata: Optional[dict] = None,
    fallback_model_id: str = ANALYSIS_FALLBACK_MODEL,
) -> tuple[AnalysisResult, Optional[str]]:
    """
    Run an analysis with an automatic fallback to a second provider.

    Tries `model_id` first. If the primary call raises any exception
    (credit exhaustion, rate limit, auth error, timeout), logs the error
    and retries once with `fallback_model_id`. If the primary and fallback
    refer to the same model, no retry is attempted.

    Returns:
        (result, fallback_notice) — `fallback_notice` is None when the
        primary succeeded, otherwise a short string describing which
        fallback model was used and why.
    """
    try:
        result = run_analysis_sync(
            analysis_type, transcript_content, model_id, metadata
        )
        return result, None
    except Exception as primary_error:
        if not fallback_model_id or fallback_model_id == model_id:
            raise
        err_msg = f"{type(primary_error).__name__}: {primary_error}"
        logger.warning(
            f"Primary model {model_id} failed for {analysis_type} ({err_msg}); "
            f"falling back to {fallback_model_id}"
        )
        result = run_analysis_sync(
            analysis_type, transcript_content, fallback_model_id, metadata
        )
        notice = f"Primary model {model_id} unavailable; used fallback {fallback_model_id}"
        return result, notice
