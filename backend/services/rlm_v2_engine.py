"""
RLM-v2 Engine
=============
Lightweight code-execution RLM engine inspired by Zhang/Khattab and Nightjar.

Key idea: documents live in a Python namespace, NOT in the LLM context window.
The orchestrator LLM writes Python code to explore them. Semantic reasoning
is delegated to independent sub-LLM calls that don't accumulate history.

Three-tier model architecture:
- Orchestrator (Sonnet): writes Python code to explore documents — fast iterations
- Sub-LLM (Haiku): independent semantic reasoning on passages — cheap
- Synthesis (Opus): produces the final polished answer — quality where it counts

Cost savings come from keeping documents outside ALL models' context windows.
The orchestrator only sees code + stdout. Sub-LLM calls are independent.
Opus only sees the collected findings for synthesis, never raw documents.
"""

import asyncio
import io
import re
import traceback
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from typing import Any, Optional

from database import get_db
from services.chat import ChatService
from services.rlm_tools import (
    _get_source_text,
    _find_page_for_offset,
    get_highlights as rlm_get_highlights,
    get_notes as rlm_get_notes,
)

# Maximum stdout captured per execution to prevent context blowout
MAX_STDOUT_LENGTH = 3000

# Maximum code block length we'll execute
# Generous limit because FINAL_ANSWER() embeds the full findings text
MAX_CODE_LENGTH = 30000

# Stop after this many consecutive code errors without progress
MAX_CONSECUTIVE_ERRORS = 3

# System prompt for the orchestrator LLM
ORCHESTRATOR_SYSTEM_PROMPT = """You are a research assistant with access to a Python environment.
Documents are loaded as string variables. Write Python code to explore them.

## Available Variables
- `docs` — dict mapping source_id to full document text
- `doc_info` — dict mapping source_id to metadata: {title, author, year, sections: [{id, title, start, end}]}

## Available Functions
- `search(pattern, doc_id=None)` — Regex search across docs. Returns list of {source_id, match, start, end, context_before, context_after, section}
- `peek(doc_id, start, end)` — Read character range. Returns {text, page_start, section}
- `toc(doc_id)` — Get table of contents. Returns hierarchical section list
- `section_titles(doc_id)` — Get flat list of section title strings
- `read_section(doc_id, section_id)` — Read full section text. Returns {text, title, page_start}
- `highlights(doc_id)` — Get user's highlights. Returns list of {text, color, start_offset, page}
- `notes(doc_id)` — Get user's notes. Returns list of {content, tags}
- `llm_query(prompt, context="")` — Ask a sub-LLM to reason about text. Returns string response
- `llm_query_batch(items)` — Concurrent sub-LLM calls. items = list of {prompt, context}. Returns list of strings
- `store(key, value)` — Save a value for use in later iterations
- `recall(key)` — Retrieve a stored value (returns None if not found)
- `FINAL_ANSWER(text)` — Submit your final answer. Call this when done

## Research Methodology
1. Write code in ```python fenced blocks. Only code inside these blocks is executed.
2. Use `print()` to see results — stdout is your only feedback channel.
3. Use `llm_query()` for semantic reasoning about specific passages.
4. Use `llm_query_batch()` when you need to analyze multiple passages concurrently.
5. Be strategic: search → read relevant passages → analyze → collect evidence → synthesize.

## Citation Requirements (CRITICAL)
Your findings will be used to produce a scholarly response. You MUST collect:
- **Direct quotes**: Use `peek()` or `read_section()` to read passages, then store exact quotes.
- **Page numbers**: Both `peek()` and `read_section()` return `page_start`. Always record it.
- **Section/chapter titles**: Returned by `peek()`, `read_section()`, and `search()`.

Use `store()` to accumulate evidence as you go. Example pattern:
```
result = peek(doc_id, start, end)
store("quote_1", {
    "text": result["text"][:500],  # exact quote
    "page": result["page_start"],
    "section": result["section"],
    "author": doc_info[doc_id]["author"]
})
```

## FINAL_ANSWER Requirements
When you call FINAL_ANSWER(text), include:
- Specific findings organized by theme or by source
- **Direct quotes** (blockquoted with >) with page numbers and author attribution
- Section/chapter references where you found key material
- Notes on where sources agree or disagree
- Format with markdown

The text you pass to FINAL_ANSWER is your complete research dossier. Be thorough —
include all relevant quotes, page numbers, and evidence you collected. A synthesis
model will polish it into the final response, but it can only cite what you provide."""


def _extract_code_blocks(text: str) -> list[str]:
    """Extract Python code from fenced code blocks in LLM output."""
    pattern = r'```python\s*\n(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL)
    return matches


def _extract_final_answer_text(code: str) -> Optional[str]:
    """
    Try to extract the FINAL_ANSWER text directly from code without exec().

    Handles patterns like:
      FINAL_ANSWER(\"\"\"...text...\"\"\")
      FINAL_ANSWER("...text...")
      FINAL_ANSWER('''...text...''')

    Returns the extracted text, or None if pattern doesn't match.
    """
    # Triple-quoted strings (most common for long answers)
    for quote in ['"""', "'''"]:
        pattern = rf'FINAL_ANSWER\(\s*{re.escape(quote)}(.*?){re.escape(quote)}\s*\)'
        match = re.search(pattern, code, re.DOTALL)
        if match:
            return match.group(1).strip()

    # Single/double quoted strings
    for quote in ['"', "'"]:
        pattern = rf'FINAL_ANSWER\(\s*{re.escape(quote)}(.*?){re.escape(quote)}\s*\)'
        match = re.search(pattern, code, re.DOTALL)
        if match:
            return match.group(1).strip()

    return None


class RLMV2Engine:
    """
    Lightweight RLM engine with shared program state.

    Documents live in a Python namespace. The orchestrator LLM writes
    code to explore them. Sub-LLM calls handle semantic reasoning.
    """

    def __init__(
        self,
        session_id: str,
        orchestrator_model: str = "claude-sonnet",
        sub_model: str = "claude-haiku",
        synthesis_model: str = "claude-opus",
        max_iterations: int = 20,
        max_tokens: int = 4096,
        verbose: bool = True,
    ):
        self.session_id = session_id
        self.orchestrator_model = orchestrator_model
        self.sub_model = sub_model
        self.synthesis_model = synthesis_model
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.verbose = verbose
        self.chat = ChatService(verbose=verbose)

        # Shared program state (the namespace)
        self.namespace: dict[str, Any] = {}
        self._stored: dict[str, Any] = {}
        self._final_answer: Optional[str] = None
        self._sub_llm_calls = 0
        self._sub_llm_tokens = {"input": 0, "output": 0, "cost_usd": 0.0}
        self._synthesis_tokens = {"input": 0, "output": 0, "cost_usd": 0.0}

    def _log(self, msg: str):
        if self.verbose:
            print(f"[RLM-v2] {msg}")

    # -----------------------------------------------------------------
    # Document Loading
    # -----------------------------------------------------------------

    async def load_session_documents(self) -> dict:
        """
        Load all session sources as string variables in the namespace.

        Returns doc_info metadata dict for the system prompt.
        """
        db = await get_db()

        cursor = await db.execute("""
            SELECT s.id, s.title, s.author_display, s.year, s.content_path
            FROM session_sources ss
            JOIN sources s ON s.id = ss.source_id
            WHERE ss.session_id = ?
            ORDER BY ss.added_at ASC
        """, [self.session_id])
        rows = await cursor.fetchall()

        docs = {}
        doc_info = {}

        for source_id, title, author, year, content_path in rows:
            text = _get_source_text(content_path) if content_path else None
            if not text:
                continue

            docs[source_id] = text

            # Get sections for this source
            cursor = await db.execute("""
                SELECT id, title, start_offset, end_offset
                FROM sections WHERE source_id = ?
                ORDER BY order_index
            """, [source_id])
            section_rows = await cursor.fetchall()

            doc_info[source_id] = {
                "title": title,
                "author": author,
                "year": year,
                "char_count": len(text),
                "sections": [
                    {"id": s[0], "title": s[1], "start": s[2], "end": s[3]}
                    for s in section_rows
                ],
            }

        self._log(f"Loaded {len(docs)} documents into namespace")
        return {"docs": docs, "doc_info": doc_info}

    # -----------------------------------------------------------------
    # Namespace Function Builders
    # -----------------------------------------------------------------

    def _build_namespace_functions(self) -> dict:
        """
        Build sync functions for the namespace.

        All functions operate on in-memory data (docs, doc_info, _stored)
        so they're naturally synchronous. No async bridging needed for
        document access — only llm_query needs async (handled in _execute_code).
        """
        engine = self

        def search(pattern: str, doc_id: str = None) -> list[dict]:
            """Synchronous regex search on in-memory documents."""
            docs = engine.namespace.get("docs", {})
            doc_info = engine.namespace.get("doc_info", {})
            flags = re.IGNORECASE
            try:
                regex = re.compile(pattern, flags)
            except re.error:
                return [{"error": f"Invalid regex: {pattern}"}]

            results = []
            targets = {doc_id: docs[doc_id]} if doc_id and doc_id in docs else docs

            for sid, text in targets.items():
                for match in regex.finditer(text):
                    start, end = match.start(), match.end()
                    ctx_start = max(0, start - 80)
                    ctx_end = min(len(text), end + 80)

                    # Find section
                    section_title = None
                    info = doc_info.get(sid, {})
                    for sec in info.get("sections", []):
                        if sec["start"] <= start <= sec["end"]:
                            section_title = sec["title"]
                            break

                    results.append({
                        "source_id": sid,
                        "match": match.group(),
                        "start": start,
                        "end": end,
                        "context_before": text[ctx_start:start],
                        "context_after": text[end:ctx_end],
                        "section": section_title,
                    })

                    if len(results) >= 50:
                        break
                if len(results) >= 50:
                    break

            return results

        def peek(doc_id: str, start: int, end: int) -> dict:
            """Read a character range from a document."""
            docs = engine.namespace.get("docs", {})
            doc_info = engine.namespace.get("doc_info", {})

            if doc_id not in docs:
                return {"error": f"Document {doc_id} not found"}

            text = docs[doc_id]
            start = max(0, start)
            end = min(len(text), end)
            excerpt = text[start:end]

            page = _find_page_for_offset(text, start)
            section_title = None
            info = doc_info.get(doc_id, {})
            for sec in info.get("sections", []):
                if sec["start"] <= start <= sec["end"]:
                    section_title = sec["title"]
                    break

            return {
                "text": excerpt,
                "page_start": page,
                "section": section_title,
            }

        def toc(doc_id: str) -> list[dict]:
            """Get table of contents for a document."""
            doc_info = engine.namespace.get("doc_info", {})
            info = doc_info.get(doc_id, {})
            return info.get("sections", [])

        def section_titles_fn(doc_id: str) -> list[str]:
            """Get flat list of section titles."""
            doc_info = engine.namespace.get("doc_info", {})
            info = doc_info.get(doc_id, {})
            return [s["title"] for s in info.get("sections", []) if s.get("title")]

        def read_section(doc_id: str, section_id: str) -> dict:
            """Read a full section by ID."""
            docs = engine.namespace.get("docs", {})
            doc_info = engine.namespace.get("doc_info", {})

            if doc_id not in docs:
                return {"error": f"Document {doc_id} not found"}

            info = doc_info.get(doc_id, {})
            for sec in info.get("sections", []):
                if sec["id"] == section_id:
                    text = docs[doc_id][sec["start"]:sec["end"]]
                    page = _find_page_for_offset(docs[doc_id], sec["start"])
                    return {
                        "text": text,
                        "title": sec["title"],
                        "page_start": page,
                    }

            return {"error": f"Section {section_id} not found"}

        def highlights(doc_id: str) -> list[dict]:
            """Get user's highlights (sync from in-memory cache)."""
            cache_key = f"_highlights_{doc_id}"
            cached = engine._stored.get(cache_key)
            if cached is not None:
                return cached
            # Return empty — will be populated by async preload
            return []

        def notes_fn(doc_id: str) -> list[dict]:
            """Get user's notes (sync from in-memory cache)."""
            cache_key = f"_notes_{doc_id}"
            cached = engine._stored.get(cache_key)
            if cached is not None:
                return cached
            return []

        def store_fn(key: str, value: Any):
            """Persist a value across iterations."""
            engine._stored[key] = value

        def recall_fn(key: str) -> Any:
            """Retrieve a previously stored value."""
            return engine._stored.get(key)

        def final_answer(text: str):
            """Signal completion with the final answer."""
            engine._final_answer = text

        # llm_query and llm_query_batch are injected in _execute_code
        # because they need async bridging via run_coroutine_threadsafe
        return {
            "search": search,
            "peek": peek,
            "toc": toc,
            "section_titles": section_titles_fn,
            "read_section": read_section,
            "highlights": highlights,
            "notes": notes_fn,
            "store": store_fn,
            "recall": recall_fn,
            "FINAL_ANSWER": final_answer,
        }

    # -----------------------------------------------------------------
    # Sub-LLM Calls
    # -----------------------------------------------------------------

    async def _sub_llm_query(self, prompt: str, context: str = "") -> str:
        """Make an independent sub-LLM call for semantic reasoning."""
        self._sub_llm_calls += 1
        self._log(f"Sub-LLM call #{self._sub_llm_calls}: {prompt[:80]}...")

        messages = [{"role": "user", "content": prompt}]
        result = await self.chat.chat(
            model_id=self.sub_model,
            messages=messages,
            context=context if context else None,
            max_tokens=2000,
        )

        if result.get("success"):
            usage = result.get("usage", {})
            self._sub_llm_tokens["input"] += usage.get("input_tokens", 0)
            self._sub_llm_tokens["output"] += usage.get("output_tokens", 0)
            self._sub_llm_tokens["cost_usd"] += usage.get("cost_usd", 0.0)
            return result.get("content", "")
        else:
            return f"[Sub-LLM error: {result.get('error', 'unknown')}]"

    async def _sub_llm_batch(self, items: list[dict]) -> list[str]:
        """Run multiple sub-LLM calls concurrently."""
        tasks = [
            self._sub_llm_query(
                item.get("prompt", ""),
                item.get("context", ""),
            )
            for item in items
        ]
        return await asyncio.gather(*tasks)

    # -----------------------------------------------------------------
    # Code Execution
    # -----------------------------------------------------------------

    async def _execute_code(self, code: str) -> tuple[str, str, Optional[str]]:
        """
        Execute Python code in the shared namespace.

        Returns (stdout, stderr, error_message).

        Sub-LLM calls (llm_query, llm_query_batch) are bridged from sync
        to async using asyncio.run_coroutine_threadsafe(). The exec() runs
        in a thread so it can block on async results without deadlocking
        the event loop.
        """
        if len(code) > MAX_CODE_LENGTH:
            # Before rejecting, check if it's just a FINAL_ANSWER call
            # (these embed long text and are safe to parse directly)
            extracted = _extract_final_answer_text(code)
            if extracted is not None:
                self._final_answer = extracted
                return "FINAL_ANSWER captured (parsed directly)", "", None
            return "", "", f"Code too long ({len(code)} chars, max {MAX_CODE_LENGTH})"

        loop = asyncio.get_event_loop()
        engine = self

        # Build sync wrappers that bridge to async via the running event loop
        def llm_query_sync(prompt: str, context: str = "") -> str:
            """Blocking sync wrapper for sub-LLM calls."""
            future = asyncio.run_coroutine_threadsafe(
                engine._sub_llm_query(prompt, context), loop
            )
            return future.result(timeout=120)

        def llm_query_batch_sync(items: list[dict]) -> list[str]:
            """Blocking sync wrapper for batch sub-LLM calls."""
            future = asyncio.run_coroutine_threadsafe(
                engine._sub_llm_batch(items), loop
            )
            return future.result(timeout=300)

        # Build the exec namespace with all functions
        exec_namespace = {
            **self.namespace,
            "llm_query": llm_query_sync,
            "llm_query_batch": llm_query_batch_sync,
        }

        # Run exec() in a thread so sync sub-LLM calls can block
        # without deadlocking the async event loop
        stdout, stderr, error_msg = await asyncio.to_thread(
            self._exec_in_thread, code, exec_namespace
        )

        # Update namespace with any new variables from exec
        protected_keys = {
            "docs", "doc_info", "search", "peek", "toc",
            "section_titles", "read_section", "highlights", "notes",
            "store", "recall", "FINAL_ANSWER",
            "llm_query", "llm_query_batch",
            "__builtins__",
        }
        for key, value in exec_namespace.items():
            if key not in protected_keys:
                self.namespace[key] = value

        # Truncate stdout to prevent context blowout
        if len(stdout) > MAX_STDOUT_LENGTH:
            stdout = stdout[:MAX_STDOUT_LENGTH] + f"\n...[truncated, {len(stdout) - MAX_STDOUT_LENGTH} chars omitted]"

        return stdout, stderr, error_msg

    def _exec_in_thread(
        self, code: str, exec_namespace: dict
    ) -> tuple[str, str, Optional[str]]:
        """
        Run exec() synchronously in a worker thread.

        Called via asyncio.to_thread() so that blocking llm_query() calls
        (which use run_coroutine_threadsafe) don't deadlock the event loop.
        """
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        error_msg = None

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, exec_namespace)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            tb = traceback.format_exc()
            tb_lines = tb.strip().split("\n")
            if len(tb_lines) > 4:
                tb_lines = tb_lines[-4:]
            stderr_buf.write("\n".join(tb_lines))

        return stdout_buf.getvalue(), stderr_buf.getvalue(), error_msg

    # -----------------------------------------------------------------
    # Preload Annotations
    # -----------------------------------------------------------------

    async def _preload_annotations(self, doc_ids: list[str]):
        """Preload highlights and notes into the stored cache."""
        for doc_id in doc_ids:
            hl_result = await rlm_get_highlights(source_id=doc_id)
            if "result" in hl_result:
                self._stored[f"_highlights_{doc_id}"] = hl_result["result"]

            notes_result = await rlm_get_notes(source_id=doc_id)
            if "result" in notes_result:
                self._stored[f"_notes_{doc_id}"] = notes_result["result"]

    # -----------------------------------------------------------------
    # Synthesis Step (Opus)
    # -----------------------------------------------------------------

    async def _synthesize_final_answer(
        self, query: str, raw_findings: str, doc_info: dict
    ) -> dict:
        """
        Use the synthesis model (Opus) to produce a polished final answer
        from the orchestrator's collected findings.

        The orchestrator (Sonnet) is fast at exploring documents but may
        produce rougher prose. Opus takes the findings and produces a
        well-structured, well-cited research response.

        Returns {content, usage} or {error}.
        """
        # Build a concise source reference for Opus
        source_refs = []
        for doc_id, info in doc_info.items():
            title = info.get("title", "Untitled")
            author = info.get("author", "Unknown")
            year = info.get("year", "")
            year_str = f" ({year})" if year else ""
            source_refs.append(f"- {title} by {author}{year_str}")

        sources_block = "\n".join(source_refs)

        synthesis_prompt = f"""You are a research assistant synthesizing collected evidence into a polished scholarly response.

## Sources Referenced
{sources_block}

## Original Question
{query}

## Research Findings
The following findings, quotes, and evidence were collected by systematically searching and analyzing the source documents:

{raw_findings}

## Synthesis Instructions
Transform these raw findings into a comprehensive, well-structured response:

1. **Preserve all direct quotes** — use blockquote format (> quote) with attribution (Author, p. XX)
2. **Cite every claim** — include page numbers, section/chapter titles from the findings
3. **Organize by theme or by source** as appropriate to the question
4. **Note where sources agree, disagree, or complement each other** — tensions are valuable
5. **Distinguish what sources say vs. your interpretation**
6. Use clear headings and structure for complex topics
7. If findings include a comparison table, refine and include it

The quality of this response depends on grounding every point in the specific evidence provided.
Do not add claims that aren't supported by the findings above. Be thorough but not repetitive.
Format with markdown."""

        self._log(f"Synthesizing with {self.synthesis_model}...")

        result = await self.chat.chat(
            model_id=self.synthesis_model,
            messages=[{"role": "user", "content": synthesis_prompt}],
            max_tokens=self.max_tokens,
        )

        if result.get("success"):
            usage = result.get("usage", {})
            self._synthesis_tokens["input"] = usage.get("input_tokens", 0)
            self._synthesis_tokens["output"] = usage.get("output_tokens", 0)
            self._synthesis_tokens["cost_usd"] = usage.get("cost_usd", 0.0)
            return {"content": result.get("content", ""), "usage": usage}
        else:
            return {"error": result.get("error", "Synthesis failed")}

    # -----------------------------------------------------------------
    # Main Agent Loop (Streaming)
    # -----------------------------------------------------------------

    async def run_streaming(self, query: str, system: str = None):
        """
        Run the RLM-v2 agent loop, yielding SSE events.

        Events:
        - start: {query}
        - thinking: {iteration}
        - code_block: {code, iteration}
        - exec_result: {stdout, stderr, duration_ms}
        - sub_llm_done: {count, duration_ms}
        - complete: {content, iterations, usage, cost}
        - error: {error}
        """
        yield {"event": "start", "data": {"query": query}}

        # 1. Load documents into namespace
        try:
            data = await self.load_session_documents()
            self.namespace["docs"] = data["docs"]
            self.namespace["doc_info"] = data["doc_info"]
        except Exception as e:
            yield {"event": "error", "data": {"error": f"Failed to load documents: {e}"}}
            return

        if not data["docs"]:
            yield {"event": "error", "data": {"error": "No documents in session"}}
            return

        # 2. Inject helper functions
        ns_functions = self._build_namespace_functions()
        self.namespace.update(ns_functions)

        # 3. Preload annotations
        await self._preload_annotations(list(data["docs"].keys()))

        # 4. Build doc overview for the prompt
        doc_overview = self._build_doc_overview(data["doc_info"])

        # 5. Agent loop
        effective_system = system or ORCHESTRATOR_SYSTEM_PROMPT
        conversation = [
            {
                "role": "user",
                "content": f"{doc_overview}\n\nUser query: {query}",
            }
        ]

        total_orchestrator_usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        consecutive_errors = 0

        for iteration in range(1, self.max_iterations + 1):
            yield {"event": "thinking", "data": {"iteration": iteration}}
            self._log(f"Iteration {iteration}")

            try:
                # Call orchestrator — capped at 4096 for code generation
                # (the user's max_tokens setting is reserved for the synthesis step)
                orchestrator_max = min(self.max_tokens, 4096)
                result = await self.chat.chat(
                    model_id=self.orchestrator_model,
                    messages=conversation,
                    system=effective_system,
                    max_tokens=orchestrator_max,
                )
            except Exception as e:
                self._log(f"Orchestrator call exception: {e}")
                yield {"event": "error", "data": {"error": f"Orchestrator exception: {type(e).__name__}: {e}"}}
                return

            if not result.get("success"):
                yield {"event": "error", "data": {"error": result.get("error", "Orchestrator call failed")}}
                return

            # Track orchestrator usage
            usage = result.get("usage", {})
            total_orchestrator_usage["input_tokens"] += usage.get("input_tokens", 0)
            total_orchestrator_usage["output_tokens"] += usage.get("output_tokens", 0)
            total_orchestrator_usage["cost_usd"] += usage.get("cost_usd", 0.0)

            response_text = result.get("content", "")

            # Extract code blocks
            code_blocks = _extract_code_blocks(response_text)

            if not code_blocks:
                # No code blocks — check if there's a FINAL_ANSWER in the text
                # or if the model just wants to respond directly
                if self._final_answer:
                    break

                # Model responded without code — treat as final answer
                self._log("No code blocks found, treating response as final answer")
                self._final_answer = response_text
                break

            # Execute each code block
            all_stdout = []
            iteration_had_error = False

            for code in code_blocks:
                yield {
                    "event": "code_block",
                    "data": {"code": code, "iteration": iteration},
                }

                # Track sub-LLM calls before/after
                pre_calls = self._sub_llm_calls
                start_time = datetime.now()

                stdout, stderr, error = await self._execute_code(code)

                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                post_calls = self._sub_llm_calls

                # Emit sub-LLM events if any were made
                if post_calls > pre_calls:
                    yield {
                        "event": "sub_llm_done",
                        "data": {
                            "count": post_calls - pre_calls,
                            "duration_ms": duration_ms,
                        },
                    }

                yield {
                    "event": "exec_result",
                    "data": {
                        "stdout": stdout,
                        "stderr": stderr,
                        "error": error,
                        "duration_ms": duration_ms,
                    },
                }

                all_stdout.append(stdout)

                if error:
                    all_stdout.append(f"Error: {error}")
                    iteration_had_error = True

                # Check if FINAL_ANSWER was called
                if self._final_answer is not None:
                    break

            # If we have a final answer, stop
            if self._final_answer is not None:
                break

            # Consecutive error safeguard
            if iteration_had_error:
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    self._log(
                        f"Stopping: {MAX_CONSECUTIVE_ERRORS} consecutive "
                        "iterations with errors"
                    )
                    yield {
                        "event": "error",
                        "data": {
                            "error": (
                                f"Stopped after {MAX_CONSECUTIVE_ERRORS} "
                                "consecutive iterations with code errors"
                            )
                        },
                    }
                    return
            else:
                consecutive_errors = 0

            # Add assistant response and execution output to conversation
            exec_output = "\n".join(s for s in all_stdout if s.strip())
            conversation.append({"role": "assistant", "content": response_text})
            conversation.append({
                "role": "user",
                "content": f"Execution output:\n```\n{exec_output}\n```",
            })

        # 6. Synthesis step — Opus produces the polished final answer
        raw_findings = self._final_answer or "No findings collected."

        yield {
            "event": "synthesizing",
            "data": {"model": self.synthesis_model},
        }

        try:
            synthesis_result = await self._synthesize_final_answer(
                query=query,
                raw_findings=raw_findings,
                doc_info=data["doc_info"],
            )
        except Exception as e:
            self._log(f"Synthesis exception: {e}")
            synthesis_result = {"error": f"{type(e).__name__}: {e}"}

        if "error" in synthesis_result:
            # Synthesis failed — fall back to raw findings
            self._log(f"Synthesis failed: {synthesis_result['error']}, using raw findings")
            final_content = raw_findings
        else:
            final_content = synthesis_result["content"]

        # 7. Compile usage across all three tiers
        total_cost = (
            total_orchestrator_usage["cost_usd"]
            + self._sub_llm_tokens["cost_usd"]
            + self._synthesis_tokens["cost_usd"]
        )
        total_input = (
            total_orchestrator_usage["input_tokens"]
            + self._sub_llm_tokens["input"]
            + self._synthesis_tokens["input"]
        )
        total_output = (
            total_orchestrator_usage["output_tokens"]
            + self._sub_llm_tokens["output"]
            + self._synthesis_tokens["output"]
        )

        total_usage = {
            "orchestrator": {
                "model": self.orchestrator_model,
                "input_tokens": total_orchestrator_usage["input_tokens"],
                "output_tokens": total_orchestrator_usage["output_tokens"],
                "cost_usd": round(total_orchestrator_usage["cost_usd"], 6),
            },
            "sub_llm": {
                "model": self.sub_model,
                "calls": self._sub_llm_calls,
                "input_tokens": self._sub_llm_tokens["input"],
                "output_tokens": self._sub_llm_tokens["output"],
                "cost_usd": round(self._sub_llm_tokens["cost_usd"], 6),
            },
            "synthesis": {
                "model": self.synthesis_model,
                "input_tokens": self._synthesis_tokens["input"],
                "output_tokens": self._synthesis_tokens["output"],
                "cost_usd": round(self._synthesis_tokens["cost_usd"], 6),
            },
            "total": {
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cost_usd": round(total_cost, 6),
            },
        }

        yield {
            "event": "complete",
            "data": {
                "content": final_content,
                "iterations": iteration,
                "sub_llm_calls": self._sub_llm_calls,
                "usage": total_usage,
            },
        }

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _build_doc_overview(self, doc_info: dict) -> str:
        """Build a concise document overview for the orchestrator prompt."""
        lines = ["## Documents in Session\n"]
        for doc_id, info in doc_info.items():
            title = info.get("title", "Untitled")
            author = info.get("author", "Unknown")
            year = info.get("year", "")
            chars = info.get("char_count", 0)
            sections = info.get("sections", [])
            year_str = f" ({year})" if year else ""

            lines.append(f"**{title}** by {author}{year_str}")
            lines.append(f"  - ID: `{doc_id}` | {chars:,} chars | {len(sections)} sections")

            # Show first few section titles
            titles = [s["title"] for s in sections[:8] if s.get("title")]
            if titles:
                lines.append(f"  - Sections: {', '.join(titles)}")
                if len(sections) > 8:
                    lines.append(f"    ... and {len(sections) - 8} more")
            lines.append("")

        return "\n".join(lines)


# =============================================================================
# Convenience Function
# =============================================================================

async def run_rlm_v2_streaming(
    session_id: str,
    query: str,
    orchestrator_model: str = "claude-sonnet",
    sub_model: str = "claude-haiku",
    synthesis_model: str = "claude-opus",
    max_iterations: int = 20,
    max_tokens: int = 4096,
    verbose: bool = True,
):
    """
    Run an RLM-v2 query with streaming events.

    Three-tier model architecture:
    - Orchestrator (Sonnet): writes Python code to explore documents — fast
    - Sub-LLM (Haiku): independent semantic reasoning on passages — cheap
    - Synthesis (Opus): produces polished final answer — quality

    Cost savings come from keeping documents outside all models' context
    windows. The orchestrator only sees code + stdout.

    Yields event dicts for SSE streaming.
    """
    engine = RLMV2Engine(
        session_id=session_id,
        orchestrator_model=orchestrator_model,
        sub_model=sub_model,
        synthesis_model=synthesis_model,
        max_iterations=max_iterations,
        max_tokens=max_tokens,
        verbose=verbose,
    )

    async for event in engine.run_streaming(query):
        yield event
