# Council Mode

> Three models deliberate. One synthesizes. The wisdom of crowds, applied to LLMs.

---

## The Idea

Andrej Karpathy's [llm-council](https://github.com/karpathy/llm-council) demonstrated the value of running the same question through multiple models and comparing outputs. Different models have different training distributions, different failure modes, and different strengths. A question that stumps Claude might be straightforward for GPT, and vice versa.

Scholia's Council mode extends this idea — integrating multi-model deliberation directly into the reading workflow. Rather than a standalone tool, the council is embedded in the reader sidebar, where it can receive document context, work with analytical presets, and track costs per query. My standalone [llm-council-redux](https://github.com/bharat2288/llm-council-redux) is available separately if you want the multi-model deliberation pattern without the rest of Scholia.

---

## How It Works

### The Deliberation

```
User question + document context
        ↓
┌───────────────────────────────────────────────┐
│  Parallel execution (asyncio.gather)           │
│                                               │
│  Theorist 1: Claude Opus (Anthropic)          │
│  Theorist 2: GPT (OpenAI)                    │
│  Theorist 3: Gemini Pro (via OpenRouter)      │
└───────────────────────────────────────────────┘
        ↓
Chairman: Claude (Anthropic)
  - Reads all three perspectives
  - Identifies agreement and disagreement
  - Synthesizes unified response
        ↓
Final answer + per-provider cost breakdown
```

### API Keys Required

Council mode requires your own API keys for each provider:

| Provider | Environment Variable | What It Enables |
|----------|---------------------|-----------------|
| Anthropic | `ANTHROPIC_API_KEY` | Theorist 1 + Chairman |
| OpenAI | `OPENAI_COUNCIL_KEY` | Theorist 2 |
| OpenRouter | `OPENROUTER_API_KEY` | Theorist 3 (Gemini or any OpenRouter-supported model) |

Models are configurable via environment variables (`ANTHROPIC_MODEL`, `OPENAI_MODEL`, `OPENROUTER_MODEL`). The defaults are the latest frontier models from each provider.

### Parallel Execution

All three theorists run concurrently. This isn't sequential (ask A, then B, then C) — it's `asyncio.gather()` across all three provider API calls. Total latency is the slowest model, not the sum.

### Graceful Degradation

If one model fails (rate limit, timeout, API error), the council continues with the remaining responses. If two fail, the chairman synthesizes from one. Only if all three fail does the council return an error.

This matters because model APIs are unreliable. OpenRouter's Gemini endpoint might be down. OpenAI might be rate-limiting. The council degrades gracefully instead of failing completely.

### The Chairman

The chairman (always Claude) gets a specific prompt:

> You are the chairman of a panel of theorists. You've received independent analyses from three experts. Your task is to:
> 1. Identify common threads across perspectives
> 2. Note unique insights from each council member
> 3. Resolve any tensions or contradictions
> 4. Present a unified conclusion that incorporates the strongest elements

The chairman doesn't just pick the "best" answer — it creates a meta-analysis. If all three models agree, you get high confidence. If they disagree, you see the fault lines.

---

## When It's Useful

### Contentious Topics

This is where Council mode genuinely earns its cost. If you're reading a paper that makes strong claims, running it through Council reveals where the models diverge. One model might find the argument convincing; another might identify a methodological flaw; the third might contextualize it differently. The chairman synthesis gives you the full landscape.

### Interpretive Questions

"What does this author mean by 'distributed cognition'?" — the answer depends on how the model interprets the term. Three models bring three interpretive frames. The synthesis surfaces ambiguities you might miss with a single model.

### Conceptual Analysis

"What are the theoretical commitments of this argument?" — different models trained on different corpora have different associations. One might connect to philosophy of mind; another to cognitive science; another to sociology. The cross-pollination produces richer analysis.

---

## When It's Overkill

Honestly, most questions don't need three models. If you're asking "summarize this paragraph" or "what's the main argument," a single model is fine. Council mode costs 3-4x more than a single query (three theorist calls + one chairman call) and takes longer (waiting for the slowest model).

**Use Council for**:
- Questions where you suspect the answer is model-dependent
- High-stakes analysis (dissertation material, paper reviews)
- Exploring a concept from multiple angles
- Topics where genuine disagreement is informative

**Use single model for**:
- Factual extraction (author, year, methodology)
- Summarization
- Quick explanation
- Most day-to-day reading support

---

## Cost Tracking

Every council deliberation tracks cost per provider. The UI shows a breakdown after each query:

```
Theorist 1 (Claude Opus):    $0.032  (15,000 input + 800 output tokens)
Theorist 2 (GPT):            $0.028  (12,000 input + 600 output tokens)
Theorist 3 (Gemini Pro):     $0.015  (14,000 input + 700 output tokens)
Chairman (Claude Opus):       $0.041  (all perspectives + query as input)
─────────────────────────────────────
Total:                        $0.116
```

Compare this to a single Chat query at ~$0.03. Council mode is roughly 4x the cost. The chairman call is the most expensive because it receives all three theorist outputs plus the original question — a large context.

Pricing is maintained per-provider in `config.py` (per 1M tokens, input and output separately). The system normalizes token counts across providers (Anthropic uses `input_tokens`/`output_tokens`, OpenAI uses `prompt_tokens`/`completion_tokens`) to produce accurate, comparable cost data.

---

## Streaming

The streaming variant (`deliberate_streaming()`) yields SSE events as each model completes:

```
council_start     → "Starting deliberation with 3 theorists..."
model_start       → "Claude Opus starting..."
model_start       → "GPT starting..."
model_start       → "Gemini Pro starting..."
model_complete    → "Claude Opus responded" (content + usage)
model_complete    → "Gemini Pro responded" (content + usage)
model_complete    → "GPT responded" (content + usage)
synthesis_start   → "Chairman synthesizing..."
synthesis_complete → Synthesis content + usage
complete          → Final result with all perspectives + cost breakdown
```

This lets the UI show progress: you see each theorist finish in real-time, then the chairman begins synthesis. It's more engaging than staring at a spinner for 15 seconds.

---

## Integration with Presets

Council mode works with analytical presets. When you click "Critique" in Council mode, the preset prompt goes to all three theorists. Each produces an independent critique. The chairman synthesizes the three critiques into a unified critical analysis.

This is particularly powerful for the Analyze preset: three models generate different theoretical framings, and the chairman identifies which framings are complementary, which are contradictory, and which are most productive.

---

## Design Decisions

### Why Claude as Chairman?

The chairman role requires meta-cognition: reading three analyses, identifying patterns across them, and producing coherent synthesis. Claude is consistently the strongest at this kind of comparative, meta-analytical reasoning. The chairman needs to *judge*, not just compile.

### Why Not More Models?

Five models would give more diversity but at diminishing returns. The marginal value of the 4th and 5th opinion is lower than the 2nd and 3rd, while the cost scales linearly. Three is the sweet spot for information gain per dollar.

### Why Parallel and Not Sequential?

Sequential deliberation would let later models respond to earlier ones — a conversation, not independent analysis. But that introduces anchoring bias: the second model would be influenced by the first. Independent parallel analysis preserves genuine diversity of perspective.

### Why Single-Model Fallback?

`query_single()` bypasses the council entirely for fast, cheap queries. Not everything needs three opinions. The UI lets you toggle between Council and single-model mode, so you choose the level of analysis per question.

---

## Lineage

- **[karpathy/llm-council](https://github.com/karpathy/llm-council)** — The original concept: multiple LLMs deliberate, review each other's work, chairman synthesizes. Scholia's Council extends this with document-aware context, preset integration, per-query cost tracking, and streaming progress.
- **[bharat2288/llm-council-redux](https://github.com/bharat2288/llm-council-redux)** — My standalone implementation of the multi-model deliberation pattern, available separately from Scholia.
