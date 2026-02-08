# Council Mode

> Three models deliberate. One synthesizes. The wisdom of crowds, applied to LLMs.

---

## The Idea

Andrej Karpathy has talked about the value of running the same question through multiple models and comparing outputs. Different models have different training distributions, different failure modes, and different strengths. A question that stumps Claude might be straightforward for GPT-4, and vice versa.

Council mode formalizes this. Instead of asking one model and hoping for the best, you ask three models independently, then have a fourth synthesize their perspectives into a unified response.

---

## How It Works

### The Deliberation

```
User question + context
        ↓
┌───────────────────────────────────────────┐
│  Parallel execution (asyncio.gather)       │
│                                           │
│  Theorist 1: Claude (Anthropic)           │
│  Theorist 2: GPT-4 (OpenAI)              │
│  Theorist 3: Gemini (OpenRouter)          │
└───────────────────────────────────────────┘
        ↓
Chairman: Claude (Anthropic)
  - Reads all three perspectives
  - Identifies agreement and disagreement
  - Synthesizes unified response
        ↓
Final answer + cost breakdown
```

### Parallel Execution

All three theorists run concurrently. This isn't sequential (ask A, then B, then C) — it's `asyncio.gather()` across all three provider API calls. Total latency is the slowest model, not the sum.

### Graceful Degradation

If one model fails (rate limit, timeout, API error), the council continues with the remaining responses. If two fail, the chairman synthesizes from one. Only if all three fail does the council return an error.

This matters because model APIs are unreliable. OpenRouter's Gemini endpoint might be down. OpenAI might be rate-limiting. The council degrades gracefully instead of failing completely.

### The Chairman

The chairman (always Claude) gets a specific prompt:

> You are the chairman of a panel of theorists. You've received independent analyses from three experts. Your task is to:
> 1. Identify points of agreement
> 2. Note genuine disagreements (don't paper over them)
> 3. Synthesize a unified response that's stronger than any individual
> 4. Flag when experts disagree and the disagreement matters

The chairman doesn't just pick the "best" answer — it creates a meta-analysis. If all three models agree, you get high confidence. If they disagree, you see the fault lines.

---

## When It's Useful

### Contentious Topics

If you're reading a paper that makes strong claims, running it through Council mode reveals where the models diverge. Model A might find the argument convincing; Model B might identify a methodological flaw; Model C might contextualize it differently. The chairman synthesis gives you the full landscape.

### Interpretive Questions

"What does this author mean by 'distributed cognition'?" — the answer depends on how the model interprets the term. Three models bring three interpretive frames. The synthesis surfaces ambiguities you might miss with a single model.

### Conceptual Analysis

"What are the theoretical commitments of this argument?" — different models trained on different corpora have different associations. One might connect to philosophy of mind; another to cognitive science; another to sociology. The cross-pollination produces richer analysis.

---

## When It's Overkill

Most questions don't need three models. If you're asking "summarize this paragraph" or "what's the main argument," a single model is fine. Council mode costs 3-4x more than a single query (three theorist calls + one chairman call) and takes longer (waiting for the slowest model).

**Use Council for**:
- Questions where you suspect the answer is model-dependent
- High-stakes analysis (dissertation material, paper reviews)
- Exploring a concept from multiple angles

**Use single model for**:
- Factual extraction (author, year, methodology)
- Summarization
- Quick explanation
- Most day-to-day reading support

---

## Provider Configuration

### Theorist 1: Anthropic (Claude)

Direct API call. Same SDK used for Chat. Typically the strongest on nuanced textual analysis and careful reasoning.

### Theorist 2: OpenAI (GPT-4)

Direct API call via OpenAI SDK. Often brings different emphasis — more structured, sometimes more factual.

### Theorist 3: OpenRouter (Gemini/other)

Via OpenRouter's unified API. This slot is configurable — it can be Gemini, Llama, Mistral, or any model OpenRouter supports. Gemini brings Google's training distribution, which sometimes surfaces different associations.

### Why Three Providers?

Three is the minimum for meaningful disagreement detection. Two models either agree or disagree — you can't tell who's right. Three models give you majority vote *and* minority dissent. If two agree and one disagrees, you have signal about where the uncertainty lies.

---

## Cost Tracking

Council mode is expensive relative to single-model queries. The cost breakdown shows:

```
Theorist 1 (Claude):    $0.032
Theorist 2 (GPT-4):     $0.028
Theorist 3 (Gemini):    $0.015
Chairman (Claude):       $0.041
─────────────────────────────
Total:                   $0.116
```

Compare this to a single Chat query at ~$0.03. Council mode is 4x the cost. The chairman call is the most expensive because it receives all three theorist outputs plus the original question — a large context.

Each provider uses different pricing, and the system normalizes usage across providers to give you accurate cost data.

---

## Streaming

The streaming variant (`deliberate_streaming()`) yields SSE events as each model completes:

```
council_start     → "Starting deliberation with 3 theorists..."
theorist_complete → "Theorist 1 (Claude) responded"
theorist_complete → "Theorist 2 (GPT-4) responded"
theorist_complete → "Theorist 3 (Gemini) responded"
chairman_start    → "Chairman synthesizing..."
complete          → Final synthesis + cost breakdown
```

This lets the UI show progress: you see each theorist finish in real-time, then the chairman begins synthesis. It's more engaging than staring at a spinner for 15 seconds.

---

## Integration with Presets

Council mode works with analytical presets. When you click "Critique" in Council mode, the preset prompt goes to all three theorists. Each produces an independent critique. The chairman synthesizes the three critiques into a unified critical analysis.

This is particularly powerful for Theorize: three models generate different theoretical framings, and the chairman identifies which framings are complementary, which are contradictory, and which are most productive.

---

## Design Decisions

### Why Claude as Chairman?

The chairman role requires meta-cognition: reading three analyses, identifying patterns across them, and producing coherent synthesis. Claude (Anthropic) is consistently the strongest at this kind of comparative, meta-analytical reasoning. GPT-4 tends to be more summarative; Gemini more pattern-matching. The chairman needs to *judge*, not just compile.

### Why Not More Models?

Five models would give more diversity but at diminishing returns. The marginal value of the 4th and 5th opinion is lower than the 2nd and 3rd, while the cost scales linearly. Three is the sweet spot for information gain per dollar.

### Why Parallel and Not Sequential?

Sequential deliberation would let later models respond to earlier ones — a conversation, not independent analysis. But that introduces anchoring bias: the second model would be influenced by the first. Independent parallel analysis preserves genuine diversity of perspective.

### Why Single-Model Fallback?

`query_single()` bypasses the council entirely for fast, cheap queries. Not everything needs three opinions. The UI lets you toggle between Council and single-model mode, so you choose the level of analysis per question.
