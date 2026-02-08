# Chat vs. Research Sessions

> Two modes of LLM engagement with your sources — one for quick questions, one for deep investigation.

---

## The Two Modes

Scholia offers two fundamentally different ways to interact with an LLM about your reading:

| | **Chat** | **Research Sessions** |
|---|---|---|
| **Metaphor** | Ask a librarian a question | Hire a research assistant |
| **Scope** | Single source | Multiple sources |
| **State** | Persisted (auto-saved as notes) | Stateful (server-side conversation) |
| **Tools** | None — pure text-in, text-out | 30+ tools for search, retrieval, cross-referencing |
| **Iterations** | 1 API call per message | Up to 20 tool-use loops per message |
| **Use case** | "What does this passage mean?" | "How does this author's argument compare across these three papers?" |

---

## Chat: Fast, Focused, Cheap

Chat lives in the Reader sidebar. You're reading a document, you highlight something or have a question, and you ask. The model answers based on the document context you provide.

### How It Works

```
User message + document context → Single API call → Response → Auto-save as gluon note
```

Chat conversations are persisted server-side: each exchange is stored in the `conversations` + `council_messages` tables, and the full conversation is auto-saved as a gluon note (updated on each new message). The frontend sends the conversation history with each request for prompt caching benefits, but the backend maintains the authoritative record. A "View Note" button in the UI links directly to the auto-saved gluon.

### Prompt Caching

The biggest engineering decision in Chat is **prompt caching**. When you're reading a 50-page PDF and asking repeated questions, you're sending the same document text with every message. Without caching, that's ~50k tokens of input on every call.

Anthropic's prompt caching (marked with `cache_control: {"type": "ephemeral"}`) means the first message costs normal price, but subsequent messages within the cache window reuse the cached prefix at **90% discount**. For a typical reading session where you ask 10 questions about the same document, this saves roughly $0.40.

The cache threshold is 1,024 characters — anything shorter isn't worth the caching overhead.

### Source-Type Awareness

The system prompt adapts based on what you're reading. A PDF gets academic framing ("cite page numbers, note methodological choices"). A Twitter thread gets social media framing ("note rhetorical moves, identify the thread's argument structure"). A YouTube transcript gets temporal framing ("reference timestamps").

This matters because the same question — "What's the main argument here?" — requires different interpretive moves depending on source type.

### Multi-Provider Support

Chat works with both Anthropic (Claude) and OpenAI models. The `ChatService` normalizes the interface:
- Anthropic gets document context as a separate system block (better for caching)
- OpenAI gets it merged into the system prompt string (their API doesn't support multi-block system messages the same way)

Both paths return normalized usage data (`input_tokens`, `output_tokens`, `cost`).

---

## Research Sessions: The Agent

Research Sessions are the power tool. You create a session, add multiple sources to it, and ask complex questions. The LLM doesn't just answer — it **investigates**.

### The Agentic Loop

When you send a message to a Research Session, it enters a loop:

```
1. Send user message + tool definitions to Claude
2. Claude decides: answer directly, or call a tool?
3. If tool call → execute tool → feed result back → goto 2
4. If no tool call → return final answer
5. Maximum 20 iterations (safety limit)
```

Each iteration is a full API round-trip. A complex question might take 5-8 iterations as the agent searches your library, reads specific sections, cross-references across documents, and synthesizes.

### What the Agent Can Do

The agent has access to **30+ tools** organized into categories:

**Library Discovery**
- `library_search` — Full-text search across your entire library
- `library_filter` — Filter by type, year, author, tags
- `add_to_session` — Pull new sources into the active workspace

**Document Navigation**
- `toc` — Get table of contents
- `sections` / `section_titles` — Browse document structure
- `peek` — Quick look at a section without full read

**Deep Reading**
- `read_section` — Full text of a specific section
- `read_around` — Context window around a specific offset
- `search` — Find patterns within a document
- `find_all` — Search across all session sources

**Your Annotations**
- `get_highlights` — What you highlighted (and in which color)
- `get_notes` — Your margin notes (gluons attached to this source)
- `get_tags` — How you categorized this source

**Working Memory**
- `store` / `recall` — Persist key-value data across iterations
- `quote_save` / `quotes_get` — Save exact quotes for later citation

**Synthesis (Sub-LLM Delegation)**
- `sub_query` — Delegate a focused question to a cheaper/faster model
- `summarize` — Get a summary of specific content
- `extract_claims` — Pull out explicit claims from a passage
- `extract_examples` — Find concrete examples in text

### The System Prompt

The agent is guided by a research methodology prompt that teaches it to work systematically:

> 1. Explore what's available (library search, session sources)
> 2. Navigate document structure (TOC, sections)
> 3. Search for relevant content (full-text search, find across sources)
> 4. Read deeply (section content, surrounding context)
> 5. Cross-reference (compare across sources)
> 6. Always cite (page numbers, source titles)

This isn't just a tool list — it's a workflow. The agent learns to explore before diving deep, to cite everything, and to cross-reference rather than relying on a single source.

### Streaming & Visibility

Research Sessions stream events via Server-Sent Events (SSE):

```
start           → "Starting research..."
iteration_start → "Iteration 2 of 20"
tool_start      → "Searching library for 'distributed cognition'..."
tool_complete   → "Found 12 results"
tool_start      → "Reading section 3.2 of 'Clark_2008_Supersizing'..."
tool_complete   → "Read 2,340 characters"
complete        → Final answer with citations
```

The UI shows a live **tool call feed** — you can watch the agent think. This isn't just a progress indicator; it's a transparency mechanism. You can see *what* the agent searched for, *which* sections it read, and *how* it arrived at its answer. If the answer seems wrong, the tool feed tells you where to look.

### Tool Result Truncation

A single section might be 15,000 characters. Feeding that untruncated into the conversation would blow up the context window. Tool results are capped at **10,000 characters** — enough to get the substance, short enough to leave room for multiple iterations.

---

## How They Cross-Cut

Chat and Research Sessions aren't isolated — they share infrastructure:

1. **Same LLM service**: Both use `ChatService` for the actual API calls. Research Sessions just add tool definitions and iteration logic on top.
2. **Same presets**: Analytical presets (summarize, analyze, critique) work in both modes. In Chat, they're one-shot. In Research, the agent can use tools to enhance its analysis.
3. **Same source format**: Both consume the same `[SECTION]`/`[PAGE]`/`[FIGURE]` markup from the extraction pipeline.
4. **Cost tracking**: Both calculate and display per-query costs, so you always know what a question costs.

The distinction is about **depth vs. speed**. Chat is for when you know what you're looking at and want a quick interpretation. Research Sessions are for when you need the model to find things you haven't read yet, connect ideas across documents, and produce grounded analysis.

---

## Design Decisions

### Why auto-save Chat as notes?

Every chat exchange is automatically saved as a gluon note attached to the source. This means your analytical conversations aren't ephemeral — they become part of your annotations, searchable and browsable alongside highlights and manual notes. The conversation is also persisted in the `conversations` table for history browsing. The frontend still sends full history with each request (for prompt caching), but the backend is the source of truth.

### Why 20 iterations max?

The iteration limit is a cost guardrail. Each iteration is a full Claude API call. At 20 iterations with tool use, a single research query could cost $1-2. The limit prevents runaway loops where the agent keeps searching without converging on an answer. In practice, most queries resolve in 3-8 iterations.

### Why sub-LLM delegation?

Some tools (`sub_query`, `summarize`, `extract_claims`) call a smaller, cheaper model (Haiku or Sonnet) instead of the main Opus agent. This is important because the agent's context window is expensive — delegating "summarize this 5,000-word section" to Haiku costs 1/10th what doing it in the main loop would cost, and the result is fed back as a short summary.

### Why expose the tool feed?

Most AI chat interfaces hide the reasoning process. Scholia shows it because the target user is a researcher. Researchers need to evaluate the *basis* of a claim, not just the claim itself. If the agent says "Author X disagrees with Author Y on page 47," you can verify that by checking the tool feed: did it actually read page 47?
