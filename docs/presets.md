# Analytical Presets

> One-click analytical moves that encode years of academic reading practice into reusable prompts.

---

## The Idea

Every experienced academic reader develops recurring ways of engaging with text. You don't just "read" — you summarize, you identify arguments, you look for assumptions, you generate counterarguments, you extract quotable passages. These are **analytical moves**: practiced, repeatable cognitive operations.

Most people perform these moves by copying text into a ChatGPT window and typing some variation of "summarize this" or "what are the key claims." The prompt quality varies wildly. Sometimes you get a good analysis; sometimes you get a shallow one. It depends on how much effort you put into the prompt that day.

Presets make these moves **one-click operations** with carefully crafted prompts that produce consistent, high-quality output.

---

## The Seven System Presets

### Summarize

**Source types**: All | **Has full-doc variant**: Yes

Two modes:
- **Selection summary**: Contextualizes a highlighted passage within the broader work
- **Full-document summary**: Multi-section analysis covering overview, key arguments, methodology, implications, and open questions

The selection variant doesn't just paraphrase — it explains *why this passage matters* in the context of the whole work. The full-doc variant produces a structured analysis with explicit sections, not a paragraph of mush.

### Analyze

**Source types**: Documents | **Frontend modes**: 3

The most complex preset — a rigorous analytical pipeline for connecting text to established intellectual traditions. Three sub-modes (handled by the frontend, not separate presets):

- **Comprehensive**: The base mode. Identifies theoretical resonances (3-5 frameworks the text engages with, explicitly or implicitly), surfaces theoretical tensions, generates questions about what must be true for the claims to hold, and flags genuinely novel contributions. This isn't "generate frameworks" in the abstract — it's grounded analysis that distinguishes between connections the text makes and connections you're drawing.
- **Reverse**: A completely separate prompt that works *backward* from the text's conclusions. It excavates hidden foundations — the assumptions, commitments, and conditions that must hold for the argument to work. Where Comprehensive looks outward (connecting to traditions), Reverse looks inward (unpacking what's taken for granted).
- **Directed**: Wraps the Comprehensive prompt with a user-supplied deployment context. You specify *how* you intend to use these insights ("designing a curriculum for...", "writing a policy brief on..."), and the analysis weights its theoretical connections toward what's actionable for that context.

Analyze is the preset I use most. Academic reading is fundamentally about seeing texts through theoretical frames, and having the model surface resonances I hadn't considered — or excavate assumptions I'd taken for granted — is where the LLM earns its cost.

### Critique

**Source types**: All

Structured critical analysis:
- Identify the core argument and its support structure
- Find logical gaps, unsupported claims, missing evidence
- Note what the author assumes without arguing for
- Suggest strongest counterarguments
- Assess the argument's overall soundness

Not "find flaws" — more like a rigorous peer review. The prompt instructs the model to be fair: acknowledge strengths before identifying weaknesses.

### Concept Map

**Source types**: Documents, Web

Extract the conceptual architecture of a text:
- Key concepts and their definitions
- Relationships between concepts (causal, hierarchical, oppositional)
- Output as structured text that could be converted to a visual map

Useful for dense theoretical texts where the relationship between concepts is as important as the concepts themselves.

### Explain

**Source types**: All

Plain-language explanation of complex content. Not dumbed down — clarified. The prompt instructs the model to:
- Preserve technical precision while improving accessibility
- Use analogies where helpful
- Define jargon in context
- Maintain the original argument's complexity

This is the "I don't understand this paragraph" button. Different from Summarize in that it doesn't compress — it expands and clarifies.

### Quotables

**Source types**: Documents, Web

Extract passages worth quoting:
- Key claims (quotable in a literature review)
- Vivid formulations (memorable phrasing)
- Definitional passages (where terms are established)
- Methodological commitments (how the author justifies their approach)

Each quote comes with context: why it matters, what it establishes, where it fits in the argument.

### Research Questions

**Source types**: All

Generate questions that this text opens up:
- Questions the text explicitly raises but doesn't answer
- Questions implied by the methodology ("What if you used a different sample?")
- Cross-disciplinary connections ("How does this relate to [adjacent field]?")
- Productive disagreements with the text

This is the "what should I investigate next?" preset. It's designed to generate research agenda items, not study questions.

---

## Source-Type Filtering

Not every preset makes sense for every source type. Concept Map works well for academic papers but poorly for Twitter threads. Quotables makes sense for documents and web articles but not for video transcripts (where exact quotes are harder to use).

Each preset has a `source_types` field:
- `null` — show for all source types (Summarize, Analyze, Critique, Explain)
- `["document", "web"]` — show for PDFs and web articles (Concept Map, Quotables)
- `["document", "web", "thread"]` — show for text-based sources (Research Questions)

When you open the Reader sidebar, the preset list adapts to what you're reading. A PDF shows all seven presets. A YouTube transcript shows four (Summarize, Analyze, Critique, Explain).

---

## Prompt Architecture

Each preset prompt is a substantial structured document — typically 25-45 lines — sent in full to the model (not truncated). They share a common architecture:

```
[Role assignment]
You are an analytical reader performing [specific move] on this text.

[Context variables]
Source: {source_title} by {author}
Type: {source_type}

[Task specification]
Your task is to [specific analytical operation].

[Guidelines]
- [Instruction 1: what to focus on]
- [Instruction 2: what to avoid]
- [Instruction 3: how to handle edge cases]

[Output format]
Structure your response as:
### Section 1: [Label]
[What goes here]

### Section 2: [Label]
[What goes here]
```

**Why structured prompts?** Because unstructured "summarize this" produces inconsistent output. Some days the model writes three paragraphs; some days it writes bullet points; some days it misses the methodology entirely. The output format template ensures you get the same analytical structure every time.

**Why template variables?** `{source_title}` and `{author}` aren't just cosmetic. They give the model grounding: "You're reading Clark's work" produces different analysis than "you're reading a document." The model can use author context (if it knows the author's other work) to enrich its analysis.

---

## Full-Document vs. Selection

Summarize has two variants:
- `prompt` — used when text is selected in the reader (analyzes a passage)
- `prompt_full_doc` — used when no text is selected (analyzes the entire document)

The selection variant focuses on contextualizing: "What does this passage do in the argument?" The full-doc variant focuses on comprehensiveness: "Give me the complete analytical breakdown."

Other presets don't need this distinction because they work the same way regardless of scope.

---

## Custom Presets

System presets cover the common analytical moves. But every researcher has their own. A sociologist might want a preset for "identify the ontological commitments." A legal scholar might want "extract the holding and dicta." A historian might want "identify the periodization assumptions."

Custom presets use the same infrastructure as system presets:
- Same prompt template structure
- Same source-type filtering
- Same quick-action display
- Stored in the same `presets` table with `is_system = 0`

The Preset Editor lets you create, edit, and test custom presets.

---

## Seed and Update Pattern

System presets are defined in code (`services/council/presets.py`), not in the database. On every server startup, `seed_system_presets()` runs:

1. For each system preset defined in code:
   - If it doesn't exist in the DB → INSERT
   - If it exists → UPDATE with the latest prompt text

This means prompt improvements ship with code updates. If I improve the Critique prompt, every user gets the improvement on next restart. No migration needed. The user's custom presets are never touched.

---

## Design Decisions

### Why 7 and Not 15?

An earlier version had 15 presets (key-claims, define, connect, summary, counterarguments, eli5, etc.). Most were redundant or barely used. "Key claims" is a subset of Critique. "Define" is a subset of Explain. "Counterarguments" is a subset of Critique. Consolidation to 7 rich presets is better than 15 thin ones.

### Why Frontend-Only Modes for Analyze?

The three Analyze modes (Comprehensive, Reverse, Directed) share 90% of their prompt. Creating three separate presets would mean maintaining three nearly-identical prompts. Instead, one preset exists in the DB, and the frontend prepends the mode instruction. Less duplication, easier maintenance.

### Why Source-Type Filtering and Not Hiding?

Filtered presets aren't invisible — they're contextually appropriate. A user *could* run Concept Map on a video transcript, but it wouldn't produce useful output. Filtering isn't about restricting access; it's about surfacing the right tools for the right context.

### Why Quick Actions?

Presets marked as `show_as_quick_action = True` appear as one-click buttons in the chat sidebar. This matters because the whole point is reducing friction. If you have to open a dropdown, find the preset, and click it, you'll just type "summarize this" instead. One-click buttons make the preset system faster than manual prompting.
