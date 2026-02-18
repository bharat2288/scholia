# RLM Implementation Status — Exhaustive Reference

> Complete as-built documentation of Scholia's Recursive Language Model infrastructure.
> Covers architecture, code paths, data flow, tool inventories, frontend components,
> model catalog, cost tracking, quality safeguards, and gaps.
>
> **Last Updated:** 2026-02-18
> **Status:** Implemented through Phase 5 (both tool-use and code-execution engines operational)

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Mode 1: Tool-Use Agent (v1)](#2-mode-1-tool-use-agent-v1)
3. [Mode 2: Code-Execution Engine (v2)](#3-mode-2-code-execution-engine-v2)
4. [Tool & Function Inventories](#4-tool--function-inventories)
5. [Model Catalog & Routing](#5-model-catalog--routing)
6. [Data Model & Persistence](#6-data-model--persistence)
7. [API Endpoints](#7-api-endpoints)
8. [Frontend Architecture](#8-frontend-architecture)
9. [SSE Event Protocols](#9-sse-event-protocols)
10. [Cost Tracking & Token Accounting](#10-cost-tracking--token-accounting)
11. [Quality Safeguards](#11-quality-safeguards)
12. [Async-Sync Bridging (v2)](#12-async-sync-bridging-v2)
13. [Spec vs Implementation Gap Analysis](#13-spec-vs-implementation-gap-analysis)
14. [Key Lessons Learned](#14-key-lessons-learned)
15. [File Inventory](#15-file-inventory)

---

## 1. Architecture Overview

Scholia implements **two parallel RLM engines** that coexist in the same UI, toggled via a `rlmMode` state variable (`'tool-use'` | `'code'`):

```
┌──────────────────────────────────────────────────────────────────────┐
│                         RESEARCH SESSION                              │
│                                                                       │
│  Sources: doc_1, doc_2, ...  (linked from library, text on disk)     │
│  Messages: conversation history (persisted to session_messages)       │
│                                                                       │
│  ┌─────────────────────┐         ┌──────────────────────────────┐    │
│  │  MODE 1: Tool-Use   │         │  MODE 2: Code-Execution      │    │
│  │  (rlm_agent.py)     │         │  (rlm_v2_engine.py)          │    │
│  │                     │         │                               │    │
│  │  Single model calls │         │  Three-tier model split:      │    │
│  │  Claude tool_use    │         │  Orchestrator → Sub-LLM →     │    │
│  │  API natively       │         │  Synthesis                    │    │
│  │                     │         │                               │    │
│  │  28 tools defined   │         │  Python exec() sandbox        │    │
│  │  as JSON schemas    │         │  Docs as namespace variables  │    │
│  └─────────┬───────────┘         └──────────────┬───────────────┘    │
│            │                                     │                    │
│            ▼                                     ▼                    │
│  GET /sessions/{id}/rlm/stream    GET /sessions/{id}/rlm-v2/stream   │
│            │                                     │                    │
│            ▼                                     ▼                    │
│  ToolCallFeed.jsx                 CodeBlockFeed.jsx                   │
│                                   EvidenceTrace.jsx                   │
└──────────────────────────────────────────────────────────────────────┘
```

### The Fundamental Design Insight

**Documents never enter any model's context window in v2.** The cost savings are structural:

| Component | What it sees | Context size |
|-----------|-------------|--------------|
| **Orchestrator (Sonnet)** | System prompt + code + stdout | Small (~10-20K tokens) |
| **Sub-LLM (Haiku)** | Specific passage + analysis prompt | Focused (~15-50K tokens) |
| **Synthesis (Opus)** | Collected findings only | Medium (~20-40K tokens) |
| **No model** | Full document text | N/A — text lives in Python namespace |

In v1 (tool-use mode), documents are also kept out of context — the model accesses them via tool calls that return bounded results (`MAX_TOOL_RESULT_LENGTH = 10,000 chars`).

### Phase Mapping

| Phase from Original Plan | Status | Where Implemented |
|--------------------------|--------|-------------------|
| Phase 1: Research Sessions (CRUD, source linking) | DONE | `routers/sessions.py` |
| Phase 2: Smart Context Assembly | PARTIAL | `_assemble_context()` in `sessions.py` — simple concat, no priority extraction |
| Phase 3: Structured Tools | DONE | `rlm_agent.py` + `rlm_tools.py` — 28 tools, full agent loop |
| Phase 4: Sub-LLM Calls | DONE | `sub_query()` in v1, `llm_query()`/`llm_query_batch()` in v2 |
| Phase 5: Full Python Sandbox | DONE | `rlm_v2_engine.py` — exec()-based code execution |

---

## 2. Mode 1: Tool-Use Agent (v1)

**File:** `backend/services/rlm_agent.py` (1111 lines)
**Architecture:** Single model with Claude's native `tool_use` API
**Default model:** `claude-opus`

### Agent Loop

```
User query
    ↓
Build messages + tool definitions (28 tools as JSON schemas)
    ↓
┌─→ Call Claude with tools enabled (chat_with_tools)
│       ↓
│   Claude responds with:
│   ├── tool_use blocks → execute each tool → append results → loop back ↑
│   └── text only (no tools) → final answer → done
│
│   Track: tool_calls count, iteration count, token usage per iteration
└─── Max iterations: 20
```

### Key Classes and Functions

```python
class RLMAgent:
    """Agent with tool use loop."""
    session_id: str
    model_id: str           # Default "claude-opus"
    max_iterations: int     # Default 20
    max_tokens: int         # Default 4096
    tools: list[dict]       # 28 tool JSON schemas from get_tool_definitions()
    iteration_log: list     # Detailed per-iteration log

    async def run(messages, system) -> dict          # Non-streaming
    async def run_streaming(messages, system)         # Yields SSE events

# Convenience functions:
async def run_rlm_query(session_id, query, model_id, ...) -> dict
async def run_rlm_query_streaming(session_id, query, model_id, ...)  # Yields events
```

### Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_TOOL_RESULT_LENGTH` | 10,000 chars | Truncates tool results to prevent context blowout |

### System Prompt

Located at `RLM_SYSTEM_PROMPT` in `rlm_agent.py`. Key instructions:
- Explore first (library_search, library_filter)
- Add promising sources (add_to_session)
- Navigate structure (toc, section_titles)
- Search for specifics (search, find_mentions)
- Read carefully (peek, read_section)
- Cite precisely (page numbers, source titles)
- Check user annotations (get_highlights, get_notes)
- Be strategic about token efficiency

### Tool Execution

Tools are dispatched through `execute_tool()` in `rlm_tools.py`:

```python
async def execute_tool(tool_name: str, session_id: str, **kwargs) -> dict:
    """Dispatches to the TOOLS registry. Injects session_id where needed."""
```

The `_truncate_tool_result()` method serializes results to JSON and truncates at 10K chars.

---

## 3. Mode 2: Code-Execution Engine (v2)

**File:** `backend/services/rlm_v2_engine.py` (1036 lines)
**Architecture:** Three-tier model split with Python exec() sandbox
**Inspired by:** Zhang et al. (2025), Khattab et al. (2025), Nightjar

### Three-Tier Model Architecture

```
┌─────────────────────┐
│   ORCHESTRATOR       │  Sonnet (default) — writes Python code
│   Fast iterations    │  Only sees: system prompt + code + stdout
│   ~3-5s per iter     │  Capped at 4096 tokens per response
└──────────┬──────────┘
           │ writes code that calls...
           ▼
┌─────────────────────┐
│   SUB-LLM            │  Haiku (default) — semantic reasoning
│   Independent calls  │  Sees: specific passage + analytical prompt
│   No history         │  Max 2000 tokens response
│   Concurrent batch   │  Bridged async→sync for exec()
└──────────┬──────────┘
           │ findings collected, then...
           ▼
┌─────────────────────┐
│   SYNTHESIS          │  Opus (default) — final polished answer
│   One call at end    │  Sees: source refs + original query + raw findings
│   Quality focus      │  Uses user's max_tokens setting
└─────────────────────┘
```

### Engine Class

```python
class RLMV2Engine:
    session_id: str
    orchestrator_model: str     # Default "claude-sonnet"
    sub_model: str              # Default "claude-haiku"
    synthesis_model: str        # Default "claude-opus"
    max_iterations: int         # Default 20
    max_tokens: int             # Default 4096
    namespace: dict             # Shared Python namespace (docs, functions, variables)
    _stored: dict               # Persistent key-value store across iterations
    _final_answer: Optional[str]
    _doc_reads: int             # Counter for search/peek/read_section calls
    _sub_llm_calls: int         # Counter for llm_query calls
    _sub_llm_tokens: dict       # {input, output, cost_usd}
    _synthesis_tokens: dict     # {input, output, cost_usd}
```

### Agent Loop (Streaming)

```python
async def run_streaming(query, system=None):
    """
    1. Load documents into namespace (docs, doc_info)
    2. Inject helper functions (search, peek, toc, etc.)
    3. Preload annotations (highlights, notes) into _stored cache
    4. Build doc overview for orchestrator prompt
    5. Agent loop:
       a. Call orchestrator → get response text
       b. Extract ```python code blocks
       c. If no code blocks:
          - Early iteration + 0 reads → force code-writing
          - Later or has reads → treat as final answer
       d. Execute each code block via _execute_code()
       e. If FINAL_ANSWER() called:
          - Early + 0 reads → reject, continue
          - Otherwise → break
       f. Consecutive error check (3 max)
       g. Append response + execution output to conversation
    6. Synthesis: Opus produces polished answer from raw findings
    7. Compile usage across all three tiers
    8. Yield complete event
    """
```

### Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_STDOUT_LENGTH` | 3,000 chars | Truncates stdout to prevent context blowout |
| `MAX_CODE_LENGTH` | 30,000 chars | Max code block size (generous for FINAL_ANSWER embeds) |
| `MAX_CONSECUTIVE_ERRORS` | 3 | Stops after N consecutive error iterations |

### Orchestrator System Prompt

Located at `ORCHESTRATOR_SYSTEM_PROMPT` in `rlm_v2_engine.py`. Key features:
- Documents the full namespace API (variables + functions)
- Emphasizes **heavy sub-LLM usage** (following Zhang et al.)
- Provides example patterns for batch analysis and deep analysis
- Citation requirements: direct quotes, page numbers, section titles
- FINAL_ANSWER format requirements: themes, blockquoted quotes, source agreement/disagreement
- Instruction to **execute immediately**, not just plan

### Synthesis Prompt

Built dynamically in `_synthesize_final_answer()`:
- Includes source reference list (title, author, year)
- Original query
- Raw findings from orchestrator
- Instructions: preserve quotes, cite every claim, organize by theme, note tensions
- Explicit: "Do not add claims that aren't supported by the findings above"

### FINAL_ANSWER Extraction

Two pathways:
1. **Normal:** `FINAL_ANSWER(text)` function sets `self._final_answer` during exec()
2. **Fallback:** If code exceeds `MAX_CODE_LENGTH`, `_extract_final_answer_text()` uses regex to parse the text directly from triple-quoted or single-quoted strings without executing

---

## 4. Tool & Function Inventories

### v1 Tools (28 total, defined as Claude tool_use JSON schemas)

#### Library Tools (4)

| Tool | Signature | Implementation |
|------|-----------|----------------|
| `library_search` | `(query, limit=20)` | SQL `LIKE` on title/author_display + content snippet |
| `library_filter` | `(source_type?, author?, year_min?, year_max?, limit=50)` | SQL WHERE clauses. **Tag filtering has TODO** |
| `library_stats` | `()` | Counts by type, year range |
| `add_to_session` | `(source_id, context_type='full')` | Insert into session_sources |

#### Session Tools (4)

| Tool | Signature | Implementation |
|------|-----------|----------------|
| `session_sources` | `(session_id)` | List sources with token estimates, annotation counts |
| `session_stats` | `(session_id)` | Source count, total tokens, highlights/notes counts |
| `source_info` | `(source_id)` | Full metadata, char_count, section_count, annotations |
| `remove_from_session` | `(session_id, source_id)` | Delete from session_sources |

#### Navigate Tools (3)

| Tool | Signature | Implementation |
|------|-----------|----------------|
| `toc` | `(source_id)` | Hierarchical section tree with page numbers |
| `sections` | `(source_id)` | Flat section list with offsets |
| `section_titles` | `(source_id)` | Just title strings |

#### Search Tools (3)

| Tool | Signature | Implementation |
|------|-----------|----------------|
| `search` | `(pattern, source_id?, session_id?, case_sensitive=False, limit=50)` | Regex search with context, page, section |
| `find_all` | `(term, source_id?, session_id?, context_chars=100)` | Delegates to search() with escaped term |
| `find_mentions` | `(concept, source_ids?, session_id?)` | Cross-source mention grouping |

#### Read Tools (4)

| Tool | Signature | Implementation |
|------|-----------|----------------|
| `peek` | `(source_id, start, end)` | Character range read with page/section |
| `read_section` | `(source_id, section_id)` | Full section text with metadata |
| `read_around` | `(source_id, offset, context_chars=500)` | Delegates to peek() centered on offset |
| `page_for_offset` | `(source_id, offset)` | Offset → page number + section |

#### Scholia Tools (3)

| Tool | Signature | Implementation |
|------|-----------|----------------|
| `get_highlights` | `(source_id, color?)` | Highlights with page, attached notes |
| `get_notes` | `(source_id)` | Notes with tags, parent highlight |
| `get_tags` | `(session_id)` | Tags used in session sources with counts |

#### State Tools (4)

| Tool | Signature | Implementation |
|------|-----------|----------------|
| `store` | `(session_id, key, value)` | In-memory dict per session |
| `recall` | `(session_id, key)` | Retrieve from in-memory dict |
| `quote_save` | `(session_id, source_id, start_offset, end_offset, context_note?, deployment_note?)` | Save quote with metadata to session state |
| `quotes_get` | `(session_id, source_id?, concept?)` | Filter saved quotes |

#### Synthesis Tools (4)

| Tool | Signature | Implementation |
|------|-----------|----------------|
| `sub_query` | `(prompt, context, model='haiku')` | Independent sub-LLM call via ChatService |
| `summarize` | `(source_id, section_id?, max_length=500)` | Delegates to sub_query with summarization prompt |
| `extract_claims` | `(source_id, section_id?, start_offset?, end_offset?)` | Sub-LLM extracts claims as JSON array |
| `extract_examples` | `(source_id, concept?)` | Sub-LLM finds examples as JSON array |

### v2 Namespace Functions (11 total, injected into exec() namespace)

| Function | Type | Notes |
|----------|------|-------|
| `search(pattern, doc_id=None)` | Sync | Regex on in-memory docs dict |
| `peek(doc_id, start, end)` | Sync | Slice from in-memory text |
| `toc(doc_id)` | Sync | Returns sections from doc_info |
| `section_titles(doc_id)` | Sync | Returns title strings |
| `read_section(doc_id, section_id)` | Sync | Slice by section offsets |
| `highlights(doc_id)` | Sync | Returns preloaded cache from `_stored` |
| `notes(doc_id)` | Sync | Returns preloaded cache from `_stored` |
| `store(key, value)` | Sync | Writes to `_stored` dict |
| `recall(key)` | Sync | Reads from `_stored` dict |
| `FINAL_ANSWER(text)` | Sync | Sets `_final_answer` |
| `llm_query(prompt, context='')` | **Sync wrapper** | Bridges to async via `run_coroutine_threadsafe` |
| `llm_query_batch(items)` | **Sync wrapper** | Concurrent batch via `asyncio.gather` |

### v2 Namespace Variables

| Variable | Type | Content |
|----------|------|---------|
| `docs` | `dict[str, str]` | `{source_id: full_document_text}` |
| `doc_info` | `dict[str, dict]` | `{source_id: {title, author, year, char_count, sections: [{id, title, start, end}]}}` |

### Key Difference: v1 vs v2 Tool Access

| Aspect | v1 (tool-use) | v2 (code-execution) |
|--------|---------------|---------------------|
| Document access | Async DB queries per tool call | In-memory dict (loaded once at start) |
| Search | DB-backed regex with section joins | In-memory regex on loaded text |
| Highlights/notes | Async DB query per call | Preloaded into cache at start |
| Sub-LLM | `sub_query()` tool call via Claude API | `llm_query()` function in exec namespace |
| State | In-memory dict, accessed via tool calls | In-memory dict, accessed via `store()`/`recall()` |
| Code execution | N/A — model uses predefined tools only | Full Python via `exec()` |

---

## 5. Model Catalog & Routing

**File:** `backend/services/chat/config.py`

### Available Models (19 total)

#### Anthropic (Direct API)

| ID | Model | Display Name | Pricing ($/M tokens) | Tier Hints |
|----|-------|-------------|----------------------|------------|
| `claude-haiku` | `claude-3-5-haiku-20241022` | Claude 3.5 Haiku | $1.00 / $5.00 | sub |
| `claude-sonnet` | `claude-sonnet-4-20250514` | Claude 4 Sonnet | $3.00 / $15.00 | orchestrator |
| `claude-opus-45` | `claude-opus-4-5-20251101` | Claude Opus 4.5 | $15.00 / $75.00 | synthesis |
| `claude-opus` | `claude-opus-4-6` | Claude Opus 4.6 | $15.00 / $75.00 | orchestrator, synthesis |

#### OpenAI (Direct API)

| ID | Model | Display Name | Pricing ($/M tokens) | Tier Hints |
|----|-------|-------------|----------------------|------------|
| `gpt-4o-mini` | `gpt-4o-mini` | GPT-4o Mini | $0.15 / $0.60 | sub |
| `gpt-4o` | `gpt-4o` | GPT-4o | $2.50 / $10.00 | synthesis |
| `gpt-4.1` | `gpt-4.1` | GPT-4.1 | $2.00 / $8.00 | orchestrator |
| `gpt-4.1-mini` | `gpt-4.1-mini` | GPT-4.1 Mini | $0.40 / $1.60 | orchestrator, sub |
| `gpt-5` | `gpt-5` | GPT-5 | $1.25 / $10.00 | orchestrator, synthesis |
| `gpt-5.2` | `gpt-5.2` | GPT-5.2 | $1.75 / $14.00 | orchestrator, synthesis |
| `o3` | `o3` | O3 | $2.00 / $8.00 | orchestrator, synthesis |
| `o4-mini` | `o4-mini` | O4 Mini | $1.10 / $4.40 | orchestrator, sub |

#### OpenRouter (OpenAI-Compatible API)

| ID | Model | Display Name | Pricing ($/M tokens) | Tier Hints |
|----|-------|-------------|----------------------|------------|
| `gemini-flash` | `google/gemini-2.5-flash-preview` | Gemini 2.5 Flash | $0.15 / $0.60 | sub |
| `gemini-3-flash` | `google/gemini-3-flash-preview` | Gemini 3 Flash | $0.50 / $3.00 | orchestrator, sub |
| `gemini-25-pro` | `google/gemini-2.5-pro` | Gemini 2.5 Pro | $1.25 / $10.00 | orchestrator, synthesis |
| `gemini-3-pro` | `google/gemini-3-pro-preview` | Gemini 3 Pro | $2.00 / $12.00 | orchestrator, synthesis |
| `grok-code` | `x-ai/grok-code-fast-1` | Grok Code Fast 1 | $0.20 / $1.50 | orchestrator |
| `qwen3-coder` | `qwen/qwen3-coder` | Qwen3 Coder 480B | $0.22 / $1.00 | orchestrator, sub |
| `deepseek-v3` | `deepseek/deepseek-chat-v3-0324` | DeepSeek V3 | $0.27 / $1.10 | orchestrator, sub |
| `deepseek-v3.1` | `deepseek/deepseek-chat-v3.1` | DeepSeek V3.1 | $0.15 / $0.75 | orchestrator, sub |
| `llama-70b` | `meta-llama/llama-3.3-70b-instruct` | Llama 3.3 70B | $0.40 / $0.40 | sub |

### Tier Hints

Each model has `tier_hints` indicating recommended RLM roles:
- `"orchestrator"` — fast code-writing tier (strong coders only)
- `"sub"` — cheap reasoning tier
- `"synthesis"` — high-quality final answer tier

The frontend uses these to filter model dropdowns per tier.

### API Key Routing

```python
def get_api_key(provider: str) -> Optional[str]:
    "anthropic"  → ANTHROPIC_API_KEY
    "openai"     → OPENAI_COUNCIL_KEY or OPENAI_API_KEY
    "openrouter"  → OPENROUTER_API_KEY
```

### Default Selections (Frontend)

Stored in `useResearchStore.js` and persisted to `localStorage` key `scholia-rlm-models`:

```javascript
const DEFAULT_RLM_MODELS = {
  orchestrator: 'claude-sonnet',
  sub: 'claude-haiku',
  synthesis: 'claude-opus',
}
```

### Retry Configuration

`MAX_RETRIES = 5`, `RETRY_DELAY = 3s` (exponential backoff: 3, 6, 12, 24, 48s)

---

## 6. Data Model & Persistence

### Database Tables

```sql
-- Research sessions (workspace containers)
CREATE TABLE research_sessions (
    id TEXT PRIMARY KEY,           -- uuid[:8]
    title TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Session ↔ Source links (many-to-many)
CREATE TABLE session_sources (
    session_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    context_type TEXT DEFAULT 'full',  -- 'full', 'excerpt', 'highlights', 'notes'
    added_at TIMESTAMP,
    PRIMARY KEY (session_id, source_id),
    FOREIGN KEY (session_id) REFERENCES research_sessions(id),
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

-- Conversation messages (both user and assistant)
CREATE TABLE session_messages (
    id TEXT PRIMARY KEY,           -- uuid[:8]
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,             -- 'user' | 'assistant'
    content TEXT NOT NULL,
    context_snapshot TEXT,          -- JSON: metadata about what was in context
    model_id TEXT,
    usage TEXT,                    -- JSON: {input_tokens, output_tokens, cost_usd}
    created_at TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES research_sessions(id)
);
```

### context_snapshot Field

For **regular chat** messages:
```json
{"sources": [{"id": "abc123", "title": "...", "context_type": "full", "chars": 45000}]}
```

For **v1 RLM** messages:
```json
{"type": "rlm", "tool_calls": 15, "iterations": 4}
```

For **v2 RLM** messages:
```json
{
  "type": "rlm-v2",
  "iterations": 6,
  "sub_llm_calls": 12,
  "orchestrator_model": "claude-sonnet",
  "sub_model": "claude-haiku",
  "synthesis_model": "claude-opus",
  "raw_findings": "...(full text of FINAL_ANSWER before synthesis)...",
  "stored_evidence": {"key1": "value1", ...},
  "doc_reads": 23
}
```

### In-Memory State (NOT persisted)

| Store | Scope | Location | Contents |
|-------|-------|----------|----------|
| `_session_state` (v1) | Per session, in-memory | `rlm_tools.py` module-level dict | `store()`/`recall()` values, saved quotes |
| `_stored` (v2) | Per engine instance | `RLMV2Engine._stored` | `store()`/`recall()` values, preloaded highlights/notes |
| `namespace` (v2) | Per engine instance | `RLMV2Engine.namespace` | `docs`, `doc_info`, all functions, plus any variables created by orchestrator code |

**Critical limitation:** All in-memory state is lost when the server restarts or a new engine instance is created.

### Document Text Loading

`_get_source_text(content_path)` in `rlm_tools.py`:
1. If `content_path` is a file → read directly
2. If `content_path` is a directory → look for `*--extracted.txt`, then `content.txt`, then any `*.txt`
3. Returns `None` if nothing found

### Page Number Resolution

`_find_page_for_offset(text, offset)`:
- Scans for `[PAGE n]` markers using regex `\[PAGE (\d+)\]`
- Returns the page number of the last marker before the offset
- Returns `None` if no markers found

---

## 7. API Endpoints

**Router:** `backend/routers/sessions.py`, prefix `/sessions`

### Session CRUD

| Method | Path | Request | Response | Notes |
|--------|------|---------|----------|-------|
| `POST` | `/sessions` | `SessionCreate {title, description?}` | `SessionDetail` | Creates with uuid[:8] ID |
| `GET` | `/sessions` | `?limit=50&offset=0` | `List[SessionSummary]` | Ordered by updated_at DESC |
| `GET` | `/sessions/{id}` | — | `SessionDetail` | Includes sources list |
| `PATCH` | `/sessions/{id}` | `SessionUpdate {title?, description?}` | `SessionDetail` | Updates timestamp |
| `DELETE` | `/sessions/{id}` | — | `{status, id}` | Cascades to sources/messages |

### Session Sources

| Method | Path | Request | Response |
|--------|------|---------|----------|
| `POST` | `/sessions/{id}/sources` | `AddSourceRequest {source_id, context_type='full'}` | `SourceBrief` |
| `DELETE` | `/sessions/{id}/sources/{source_id}` | — | `{status, session_id, source_id}` |

### Chat (Simple Context Assembly)

| Method | Path | Request | Response |
|--------|------|---------|----------|
| `POST` | `/sessions/{id}/chat` | `SessionChatRequest {model_id, messages, max_tokens=12288}` | `SessionChatResponse` |
| `GET` | `/sessions/{id}/messages` | `?limit=100&offset=0` | `List[MessageDetail]` |

Context assembly (`_assemble_context`): concatenates all session source texts with `=== SOURCE: {header} ===` delimiters, truncated to 50K chars per source.

### RLM v1 (Tool-Use)

| Method | Path | Parameters | Response |
|--------|------|------------|----------|
| `POST` | `/sessions/{id}/rlm` | `RLMChatRequest {query, model_id='claude-opus', conversation_history?, max_iterations=20, max_tokens=12288}` | `RLMChatResponse` |
| `GET` | `/sessions/{id}/rlm/stream` | `?query=...&model_id=claude-opus&max_iterations=20&max_tokens=12288` | SSE stream |

### RLM v2 (Code-Execution)

| Method | Path | Parameters | Response |
|--------|------|------------|----------|
| `GET` | `/sessions/{id}/rlm-v2/stream` | `?query=...&orchestrator_model=claude-sonnet&sub_model=claude-haiku&synthesis_model=claude-opus&max_iterations=20&max_tokens=4096` | SSE stream |

### Message Actions

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/sessions/messages/{message_id}/save` | `{status, gluon_id}` — Saves assistant message as a gluon note |

---

## 8. Frontend Architecture

### Component Tree

```
ResearchView (route: /research)
├── SessionList (left panel, resizable)
│   └── Session cards with title, source count, message count
│
├── SourcePanel (middle panel, collapsible)
│   ├── Source cards with metadata
│   ├── Add source from library search
│   └── Remove source
│
└── RLMChat.jsx (main panel)
    ├── Mode toggle: 'tool-use' | 'code'
    ├── Model selectors (per-tier dropdowns filtered by tier_hints)
    ├── Max tokens selector
    ├── Message history (scrollable)
    │   ├── User messages
    │   └── Assistant messages with:
    │       ├── Markdown-rendered content
    │       ├── Usage/cost display
    │       ├── ToolCallFeed (v1 mode) — tool call timeline
    │       ├── CodeBlockFeed (v2 mode) — code + stdout per iteration
    │       └── EvidenceTrace (v2 mode) — collapsible evidence panel
    │
    ├── Active stream visualization:
    │   ├── v1: ToolCallFeed with running/completed status badges
    │   └── v2: CodeBlockFeed with iteration grouping + live stdout
    │
    └── Message input (textarea, Ctrl+Enter to submit)
```

### State Management

**File:** `frontend/src/stores/useResearchStore.js` (Zustand)

```javascript
{
  activeSessionId: null,
  widths: { sessions: 320, sources: 240 },   // Persisted to localStorage
  sourcesCollapsed: false,
  maxTokens: 12288,
  rlmMode: 'code',                           // 'tool-use' | 'code'
  rlmModels: {                                // Persisted to localStorage
    orchestrator: 'claude-sonnet',
    sub: 'claude-haiku',
    synthesis: 'claude-opus',
  },
  // Actions: setActiveSession, setMaxTokens, setRlmMode, setRlmModel, setWidth, toggleSourcesPanel
}
```

### Hooks

| Hook | File | Purpose |
|------|------|---------|
| `useSessions()` | `useRLM.js` | TanStack Query for session list |
| `useSessionDetail(id)` | `useRLM.js` | Session with sources |
| `useSessionMessages(id)` | `useRLM.js` | Conversation history |
| `useSaveSessionMessage()` | `useRLM.js` | Save message to DB |
| `useRLMStream()` | `useRLM.js` | v1 tool-use SSE streaming |
| `useRLMV2Stream()` | `useRLMV2.js` | v2 code-execution SSE streaming |

### useRLMV2Stream Hook State

```javascript
{
  isStreaming: boolean,
  isSynthesizing: boolean,      // True during Opus synthesis step
  synthesisModel: string | null,
  codeBlocks: [{
    code: string,
    iteration: number,
    stdout: string | null,
    stderr: string | null,
    error: string | null,
    duration_ms: number | null,
    subLlmCount: number,
    status: 'running' | 'success' | 'error'
  }],
  result: {
    content: string,
    iterations: number,
    sub_llm_calls: number,
    usage: object,
    raw_findings: string,
    stored_evidence: object,
    doc_reads: number,
    message_id: string,
    codeBlocks: array             // Snapshot from ref at save time
  } | null,
  error: Error | null,
  currentIteration: number,
  // Methods: startStream({...}), stopStream(), reset()
}
```

### Key Components

#### CodeBlockFeed.jsx
- Groups code blocks by iteration
- Each block: expandable code (syntax highlighted), stdout (truncated at 3K), stderr, error, duration, sub-LLM call count
- Camel accent icon, uppercase labels

#### ToolCallFeed.jsx
- Shows running vs completed tool calls
- Expandable input/output details
- Max-height 260px scrollable
- Status badges: running (colored), completed (muted)

#### EvidenceTrace.jsx
- Collapsible panel with header: "Evidence Trace (N reads, M stored, K iterations)"
- Three tabs:
  1. **Evidence** — stored key-value pairs from `store()` calls, expandable cards
  2. **Raw Findings** — pre-synthesis FINAL_ANSWER text, markdown-rendered
  3. **Exec Log** — embedded CodeBlockFeed showing all code blocks
- Max-height 384px scrollable content area

---

## 9. SSE Event Protocols

### v1 Events (Tool-Use)

| Event | Data | When |
|-------|------|------|
| `start` | `{query}` | Query begins |
| `iteration_start` | `{iteration}` | New agent loop iteration |
| `tool_start` | `{id, name, input}` | Tool execution begins (input truncated to 100 chars) |
| `tool_complete` | `{id, name, success, preview}` | Tool finished (preview max 150 chars) |
| `complete` | `{content, tool_calls, iterations, usage}` | Final answer |
| `error` | `{error}` | Failure |
| `saved` | `{message_id}` | Message persisted to database |

### v2 Events (Code-Execution)

| Event | Data | When |
|-------|------|------|
| `start` | `{query}` | Query begins |
| `thinking` | `{iteration}` | New iteration starting |
| `code_block` | `{code, iteration}` | Code about to be executed |
| `exec_result` | `{stdout, stderr, error, duration_ms}` | Code execution finished |
| `sub_llm_done` | `{count, duration_ms}` | Sub-LLM calls completed during this block |
| `synthesizing` | `{model}` | Opus synthesis starting |
| `complete` | `{content, iterations, sub_llm_calls, usage, raw_findings, stored_evidence, doc_reads}` | Final synthesized answer |
| `error` | `{error}` | Failure |
| `saved` | `{message_id}` | Message persisted to database |

### SSE Transport

Both endpoints use `StreamingResponse` with:
```python
media_type="text/event-stream"
headers={
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no"  # Prevents nginx buffering
}
```

Frontend uses `EventSource` (native browser SSE client) with named event listeners.

---

## 10. Cost Tracking & Token Accounting

### v1 Cost Tracking

Single accumulator across all iterations:
```python
total_usage = {
    "input_tokens": int,
    "output_tokens": int,
    "cost_usd": float   # Calculated per-iteration by ChatService with cache-aware pricing
}
```

### v2 Cost Tracking

Three separate accumulators + total:
```python
total_usage = {
    "orchestrator": {
        "model": str,
        "input_tokens": int,
        "output_tokens": int,
        "cost_usd": float
    },
    "sub_llm": {
        "model": str,
        "calls": int,              # Number of sub-LLM calls
        "input_tokens": int,
        "output_tokens": int,
        "cost_usd": float
    },
    "synthesis": {
        "model": str,
        "input_tokens": int,
        "output_tokens": int,
        "cost_usd": float
    },
    "total": {
        "input_tokens": int,
        "output_tokens": int,
        "cost_usd": float
    }
}
```

### Token Estimation

`_estimate_tokens(char_count) = char_count // 4` — rough approximation for English text. Used for session token budget display, not for actual billing.

---

## 11. Quality Safeguards

### v2-Specific Safeguards

| Safeguard | Trigger | Action |
|-----------|---------|--------|
| **Premature answer rejection** | `FINAL_ANSWER()` called in iteration 1-2 with 0 doc reads | Resets `_final_answer`, appends rejection message, loop continues |
| **Force code-writing** | No code blocks + 0 doc reads in iteration 1-2 | Appends nudge message: "You MUST write Python code..." |
| **Consecutive error limit** | 3 iterations in a row with code errors | Stops with error event |
| **Stdout truncation** | stdout > 3,000 chars | Truncates with `...[truncated, N chars omitted]` |
| **Code length limit** | Code block > 30,000 chars | Rejects unless it's a `FINAL_ANSWER()` call (parsed via regex) |
| **Prose fallback** | No code blocks after initial iterations + some doc reads | Treats response text as final answer |
| **Synthesis fallback** | Opus synthesis fails | Uses raw findings as final content |
| **Orchestrator token cap** | — | Capped at `min(max_tokens, 4096)` per orchestrator call; user's `max_tokens` reserved for synthesis |

### v1-Specific Safeguards

| Safeguard | Implementation |
|-----------|----------------|
| **Tool result truncation** | Results > 10,000 chars truncated |
| **Max iterations** | 20 (configurable) |
| **Model validation** | Checks API key availability before starting |

### Both Modes

| Safeguard | Implementation |
|-----------|----------------|
| **Session existence check** | 404 before starting stream |
| **Model availability check** | Validates all models have API keys |
| **Message persistence** | User query saved before stream starts; assistant response saved after completion |
| **Error event on crash** | try/except wraps entire stream generator |

---

## 12. Async-Sync Bridging (v2)

The v2 engine needs to run `exec(code)` which is synchronous, but sub-LLM calls (`llm_query`) are async. The bridging pattern:

```
Main event loop (async FastAPI)
    │
    ▼
asyncio.to_thread(_exec_in_thread)     ← Runs exec() in a worker thread
    │                                      so it doesn't block the event loop
    │
    ▼ (inside the worker thread)
exec(code, exec_namespace)              ← Code calls llm_query_sync()
    │
    ▼
llm_query_sync(prompt, context)
    │
    ▼
asyncio.run_coroutine_threadsafe(       ← Schedules async work back on
    _sub_llm_query(prompt, context),       the main event loop
    loop
)
    │
    ▼
future.result(timeout=120)             ← Blocks the worker thread until
                                         the async call completes
```

**Why this works:** `asyncio.to_thread()` runs `_exec_in_thread` in a separate thread. Inside that thread, `run_coroutine_threadsafe()` schedules the async `_sub_llm_query()` back on the main event loop and returns a `Future`. The thread blocks on `future.result()` without deadlocking because the event loop is free to process the scheduled coroutine.

**Batch calls:** `llm_query_batch_sync()` uses the same pattern but schedules `_sub_llm_batch()` which internally uses `asyncio.gather()` for concurrency. Timeout: 300s for batch.

---

## 13. Spec vs Implementation Gap Analysis

### From `rlm-tools.md` Spec — NOT Implemented

| Spec'd Tool | Category | Status |
|-------------|----------|--------|
| `compare(source_id_1, source_id_2, concept?)` | Cross-Reference | **Not implemented** |
| `find_shared_terms(source_ids?, min_occurrences=2)` | Cross-Reference | **Not implemented** |
| `find_tensions(source_id_1, source_id_2, concept?)` | Cross-Reference | **Not implemented** |
| Tag filtering in `library_filter()` | Library | **TODO in code** |

### From `rlm-tools.md` Spec — Implemented Differently

| Spec'd Behavior | Actual Implementation |
|-----------------|----------------------|
| `library_search` uses FTS5 | Uses SQL `LIKE` on title/author_display only |
| `sub_query` returns `{response, model_used, input_tokens, output_tokens}` | Returns nested under `result` key |

### From `research-sessions-brief.md` — NOT Implemented

| Feature | Layer | Status |
|---------|-------|--------|
| Token budget management (priority: highlights > notes > abstract > full) | Layer 2 | **Not implemented** — simple concat only |
| Section-level selection (include relevant chapters only) | Layer 2 | **Not implemented** |
| Query-time FTS5 retrieval from library | Layer 3 | **Not implemented** (v1 has `library_search` tool but it's LIKE-based) |
| Citation graph traversal | Layer 3 | **Not implemented** |
| Session → formatted document export | UX | **Not implemented** |
| Semantic search (embeddings) | Layer 3 | **Not implemented** |

### From `rlm-concepts.md` Open Questions — Status

| Question | Status |
|----------|--------|
| Nightjar availability | **Not pursued** — built custom instead |
| Sandbox strategy | **Resolved:** exec() in thread, personal tool security posture |
| State serialization between sessions | **Not implemented** — state lost on restart |
| Token budgeting | **Not implemented** — estimation only |
| Semantic search integration | **Not implemented** |
| Tool granularity | **Resolved:** 28 tools in v1, 11 functions in v2 |
| Sub-LLM routing | **Resolved:** tier_hints system in model catalog |
| Caching strategy | **Not implemented** — no caching of tool results or summaries |
| Error handling in loop | **Resolved:** consecutive error limit (3) |
| Transparency level | **Resolved:** full transparency (code blocks, stdout, tool calls visible) |
| Interruptibility | **Partial:** frontend `stopStream()` closes EventSource |
| Cost visibility | **Resolved:** full per-tier cost breakdown in UI |

### In-Memory State Persistence Gap

| State | Persisted? | Lost When? |
|-------|-----------|------------|
| Research sessions | Yes (SQLite) | Never |
| Session sources | Yes (SQLite) | Never |
| Conversation history | Yes (SQLite) | Never |
| v2 raw_findings + stored_evidence | Yes (in context_snapshot JSON) | Never |
| v1 `store()`/`recall()` values | No (module-level dict) | Server restart |
| v1 saved quotes | No (module-level dict) | Server restart |
| v2 Python namespace (docs, variables) | No (per-engine instance) | After each query completes |

---

## 14. Key Lessons Learned

### Opus Is Too Slow for Orchestration

**Finding:** Opus takes ~20-40s per call, making it unusable for iterative code-writing where you need 5-15 iterations.

**Solution:** Use Sonnet as orchestrator (~3-5s/iter), reserve Opus for the single synthesis call at the end. This is the core insight behind the three-tier split.

### Documents-as-Variables Is the Right Abstraction

**Finding:** Keeping documents in a Python namespace instead of LLM context means:
- No model ever sees the full corpus → lower cost per query
- Orchestrator context stays small → fast iterations
- Sub-LLMs get focused passages → better reasoning
- Adding more documents doesn't increase per-iteration cost

### Force-Exploration Safeguards Are Necessary

**Finding:** LLMs (especially capable ones) will try to answer research questions from memory without reading the actual documents. This produces plausible but ungrounded responses.

**Solution:** Two safeguards:
1. Reject `FINAL_ANSWER` if called before any document reads
2. Force code-writing if model responds with prose instead of code in early iterations

### The Three-Tier Split Isn't Just About Cost

It's about **latency** (Sonnet is fast enough for iteration), **quality** (Opus produces better prose), and **focus** (each model sees only what it needs).

### In-Memory State Is Fragile

`store()`/`recall()` values in v1 mode are lost on server restart. The v2 engine's stored evidence IS persisted via `context_snapshot` in the database, but the v1 tools don't do this. This is a known gap.

---

## 15. File Inventory

### Backend

| File | Lines | Purpose |
|------|-------|---------|
| `backend/routers/sessions.py` | ~1047 | All session/RLM endpoints |
| `backend/services/rlm_v2_engine.py` | ~1036 | Code-execution RLM engine (v2) |
| `backend/services/rlm_agent.py` | ~1111 | Tool-use agent loop (v1) |
| `backend/services/rlm_tools.py` | ~1905 | Tool implementations + registry |
| `backend/services/chat/config.py` | ~283 | Model catalog + pricing |
| `backend/services/chat/service.py` | — | ChatService (LLM API calls) |

### Frontend

| File | Purpose |
|------|---------|
| `frontend/src/hooks/useRLMV2.js` | v2 SSE streaming hook |
| `frontend/src/hooks/useRLM.js` | v1 hooks (sessions, messages, streaming) |
| `frontend/src/stores/useResearchStore.js` | Global research state (Zustand) |
| `frontend/src/components/Research/RLMChat.jsx` | Main chat UI (mode switching) |
| `frontend/src/components/Research/CodeBlockFeed.jsx` | v2 code block visualizer |
| `frontend/src/components/Research/ToolCallFeed.jsx` | v1 tool call visualizer |
| `frontend/src/components/Research/EvidenceTrace.jsx` | v2 evidence panel |

### Spec Documents

| File | Purpose | Currency |
|------|---------|----------|
| `specs/rlm-concepts.md` | Conceptual reference (RAG vs RLM vs fine-tuning) | Current (theory) |
| `specs/rlm-implementation-plan.md` | Decision guide + interview framework | Pre-implementation |
| `specs/rlm-tools.md` | Tool specifications (contract) | Partially implemented |
| `specs/research-sessions-brief.md` | Research brief + phased plan | Phases 1, 3-5 done |
| `specs/rlm-implementation-status.md` | **THIS DOCUMENT** — as-built reference | Current |

---

*Created: 2026-02-18*
*This document reflects the actual implementation, not aspirational specs.*
