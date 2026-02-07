"""
RLM Agent Service
=================
Implements the agent loop for tool-augmented research conversations.

The agent loop:
1. Sends user query + tool definitions to Claude
2. Parses tool calls from response
3. Executes tools via rlm_tools.execute_tool()
4. Returns results to Claude
5. Repeats until Claude provides a final answer

This enables Claude to dynamically explore documents, search, read sections,
and synthesize information in response to research questions.
"""

import json
from typing import Optional, Any
from datetime import datetime

from services.chat import ChatService
from services.rlm_tools import TOOLS, execute_tool


# =============================================================================
# Constants
# =============================================================================

# Maximum length for tool result content in context (chars)
# Prevents context blowout from large document reads
MAX_TOOL_RESULT_LENGTH = 10000


# =============================================================================
# Tool Definitions (Claude Format)
# =============================================================================

def get_tool_definitions() -> list[dict]:
    """
    Generate Claude-compatible tool definitions from the TOOLS registry.

    Each tool definition includes:
    - name: Tool identifier
    - description: What the tool does
    - input_schema: JSON Schema for parameters
    """
    return [
        # ---------------------------------------------------------------------
        # Library Tools
        # ---------------------------------------------------------------------
        {
            "name": "library_search",
            "description": "Search the entire Scholia library using full-text search. Use this to find sources by keywords in titles, authors, or content. Returns matching sources with snippets.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (keywords)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "library_filter",
            "description": "Filter the library by metadata criteria (type, author, year range). Use this to browse by category rather than keyword search.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_type": {
                        "type": "string",
                        "description": "'document', 'web', 'thread', or 'video'",
                        "enum": ["document", "web", "thread", "video"]
                    },
                    "author": {
                        "type": "string",
                        "description": "Partial match on author name"
                    },
                    "year_min": {
                        "type": "integer",
                        "description": "Published after this year"
                    },
                    "year_max": {
                        "type": "integer",
                        "description": "Published before this year"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 50)",
                        "default": 50
                    }
                },
                "required": []
            }
        },
        {
            "name": "library_stats",
            "description": "Get overview statistics of the library (total sources, counts by type, date range). Use to understand the scope of available sources.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "add_to_session",
            "description": "Load a library source into the active research session. Call this to add a source you want to analyze in detail.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID to add"
                    },
                    "context_type": {
                        "type": "string",
                        "description": "'full', 'excerpt', 'highlights', or 'notes'",
                        "default": "full",
                        "enum": ["full", "excerpt", "highlights", "notes"]
                    }
                },
                "required": ["source_id"]
            }
        },
        # ---------------------------------------------------------------------
        # Session Tools
        # ---------------------------------------------------------------------
        {
            "name": "session_sources",
            "description": "List all sources currently in the active session with their details (title, author, token estimates, annotation counts).",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "session_stats",
            "description": "Get statistics for the current session (source count, total tokens, annotation counts).",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "source_info",
            "description": "Get detailed information about a specific source (metadata, token count, sections, annotations).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    }
                },
                "required": ["source_id"]
            }
        },
        {
            "name": "remove_from_session",
            "description": "Remove a source from the active session.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID to remove"
                    }
                },
                "required": ["source_id"]
            }
        },
        # ---------------------------------------------------------------------
        # Navigate Tools
        # ---------------------------------------------------------------------
        {
            "name": "toc",
            "description": "Get the table of contents / document structure for a source. Shows sections with page numbers and hierarchy.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    }
                },
                "required": ["source_id"]
            }
        },
        {
            "name": "sections",
            "description": "Get a flat list of all sections with their character offsets. Use for programmatic navigation.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    }
                },
                "required": ["source_id"]
            }
        },
        {
            "name": "section_titles",
            "description": "Get just the section titles for a quick overview of document structure.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    }
                },
                "required": ["source_id"]
            }
        },
        # ---------------------------------------------------------------------
        # Search Tools
        # ---------------------------------------------------------------------
        {
            "name": "search",
            "description": "Regex search within source(s). Use for finding specific patterns or phrases. Returns matches with context.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for"
                    },
                    "source_id": {
                        "type": "string",
                        "description": "Specific source to search, or omit for all session sources"
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Case sensitive matching (default false)",
                        "default": False
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 50)",
                        "default": 50
                    }
                },
                "required": ["pattern"]
            }
        },
        {
            "name": "find_all",
            "description": "Find all occurrences of an exact term or phrase with context. Simpler than search() for non-regex queries.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "Exact term or phrase to find"
                    },
                    "source_id": {
                        "type": "string",
                        "description": "Specific source, or omit for all session sources"
                    },
                    "context_chars": {
                        "type": "integer",
                        "description": "Context characters on each side (default 100)",
                        "default": 100
                    }
                },
                "required": ["term"]
            }
        },
        {
            "name": "find_mentions",
            "description": "Find where a concept is mentioned across multiple sources. Returns counts and first mentions grouped by source.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "concept": {
                        "type": "string",
                        "description": "Term or phrase to find"
                    },
                    "source_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific sources, or omit for all session sources"
                    }
                },
                "required": ["concept"]
            }
        },
        # ---------------------------------------------------------------------
        # Read Tools
        # ---------------------------------------------------------------------
        {
            "name": "peek",
            "description": "Read a specific character range from a source. Use when you know the exact offsets (e.g., from search results).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    },
                    "start": {
                        "type": "integer",
                        "description": "Start offset (characters)"
                    },
                    "end": {
                        "type": "integer",
                        "description": "End offset (characters)"
                    }
                },
                "required": ["source_id", "start", "end"]
            }
        },
        {
            "name": "read_section",
            "description": "Read an entire section by ID. Use after getting section IDs from toc() or sections().",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    },
                    "section_id": {
                        "type": "string",
                        "description": "Section ID"
                    }
                },
                "required": ["source_id", "section_id"]
            }
        },
        {
            "name": "read_around",
            "description": "Read text surrounding a specific offset. Use to expand context around a search match.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Center point (character offset)"
                    },
                    "context_chars": {
                        "type": "integer",
                        "description": "Characters before and after (default 500)",
                        "default": 500
                    }
                },
                "required": ["source_id", "offset"]
            }
        },
        {
            "name": "page_for_offset",
            "description": "Convert a character offset to page number and section. Useful for citations.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Character offset"
                    }
                },
                "required": ["source_id", "offset"]
            }
        },
        # ---------------------------------------------------------------------
        # Scholia Tools (Annotations)
        # ---------------------------------------------------------------------
        {
            "name": "get_highlights",
            "description": "Get user's highlights for a source. These are passages the user marked as important.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    },
                    "color": {
                        "type": "string",
                        "description": "Filter by highlight color",
                        "enum": ["yellow", "blue", "green", "pink"]
                    }
                },
                "required": ["source_id"]
            }
        },
        {
            "name": "get_notes",
            "description": "Get user's notes for a source. These are the user's own thoughts and annotations.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    }
                },
                "required": ["source_id"]
            }
        },
        {
            "name": "get_tags",
            "description": "Get all tags used in session sources with usage counts.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        # ---------------------------------------------------------------------
        # State Tools
        # ---------------------------------------------------------------------
        {
            "name": "store",
            "description": "Save a value for later retrieval. Use to remember intermediate results across turns.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Identifier for the stored value"
                    },
                    "value": {
                        "description": "JSON-serializable value to store"
                    }
                },
                "required": ["key", "value"]
            }
        },
        {
            "name": "recall",
            "description": "Retrieve a previously stored value.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Identifier used when storing"
                    }
                },
                "required": ["key"]
            }
        },
        {
            "name": "quote_save",
            "description": "Save a quote from a source for later synthesis or citation. Captures exact text with metadata.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    },
                    "start_offset": {
                        "type": "integer",
                        "description": "Quote start (character offset)"
                    },
                    "end_offset": {
                        "type": "integer",
                        "description": "Quote end (character offset)"
                    },
                    "context_note": {
                        "type": "string",
                        "description": "Why this quote matters"
                    },
                    "deployment_note": {
                        "type": "string",
                        "description": "How to use this quote"
                    }
                },
                "required": ["source_id", "start_offset", "end_offset"]
            }
        },
        {
            "name": "quotes_get",
            "description": "Retrieve saved quotes, optionally filtered by source or concept.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Filter by source"
                    },
                    "concept": {
                        "type": "string",
                        "description": "Filter by deployment_note content"
                    }
                },
                "required": []
            }
        },
        # ---------------------------------------------------------------------
        # Synthesis Tools
        # ---------------------------------------------------------------------
        {
            "name": "sub_query",
            "description": "Delegate a question to a sub-LLM with specific context. Use for semantic tasks on large text chunks (classification, extraction, summarization).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Question or instruction for the sub-LLM"
                    },
                    "context": {
                        "type": "string",
                        "description": "Text to analyze"
                    },
                    "model": {
                        "type": "string",
                        "description": "'haiku' (fast/cheap), 'sonnet' (balanced), 'opus' (best)",
                        "default": "haiku",
                        "enum": ["haiku", "sonnet", "opus"]
                    }
                },
                "required": ["prompt", "context"]
            }
        },
        {
            "name": "summarize",
            "description": "Create a summary of a source or section. Returns a paragraph plus key points.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    },
                    "section_id": {
                        "type": "string",
                        "description": "Specific section, or omit for full source"
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Target summary length in words (default 500)",
                        "default": 500
                    }
                },
                "required": ["source_id"]
            }
        },
        {
            "name": "extract_claims",
            "description": "Extract assertions and claims from a passage. Returns structured claims with types (empirical/theoretical/methodological) and supporting quotes.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    },
                    "section_id": {
                        "type": "string",
                        "description": "Specific section"
                    },
                    "start_offset": {
                        "type": "integer",
                        "description": "Start of passage (if not using section_id)"
                    },
                    "end_offset": {
                        "type": "integer",
                        "description": "End of passage (if not using section_id)"
                    }
                },
                "required": ["source_id"]
            }
        },
        {
            "name": "extract_examples",
            "description": "Find concrete examples and case studies in a source. Optionally filter by concept.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID"
                    },
                    "concept": {
                        "type": "string",
                        "description": "Find examples of specific concept"
                    }
                },
                "required": ["source_id"]
            }
        }
    ]


# =============================================================================
# System Prompt for RLM Agent
# =============================================================================

RLM_SYSTEM_PROMPT = """You are a research assistant with tools to explore a library of academic sources.

## Your Capabilities
You can search the library, add sources to your session, navigate document structures,
read specific sections, find patterns across texts, access user annotations, and synthesize information.

## Research Approach
When answering questions:
1. **Explore first** - Use library_search or library_filter to find relevant sources
2. **Add promising sources** - Use add_to_session to load sources you want to analyze
3. **Navigate structure** - Use toc() or section_titles() to understand document organization
4. **Search for specifics** - Use search() or find_mentions() to locate relevant passages
5. **Read carefully** - Use peek() or read_section() to examine relevant text
6. **Cite precisely** - Include page numbers and source titles in your response

## Grounding Requirements
- Every claim must be traceable to a specific source and passage
- Use direct quotes when making important points
- Distinguish between what sources say vs. your interpretation
- Note when sources disagree

## Response Format
After gathering information, provide:
1. A clear answer to the question
2. Supporting evidence with citations (Author, Year, p.XX)
3. Any caveats or limitations
4. Relevant quotes where helpful

## User's Annotations
The user has highlighted passages and written notes in their sources. These represent
their existing engagement with the material. Check get_highlights() and get_notes()
for sources you analyze - the user's annotations may be directly relevant.

## Token Efficiency
Be strategic about which tools to use. Don't read entire documents when a search
would suffice. Use section_titles() before read_section() to find relevant parts."""


# =============================================================================
# Agent Loop
# =============================================================================

class RLMAgent:
    """
    Recursive Language Model agent with tool use.

    Runs an agent loop that:
    1. Sends conversation + tools to Claude
    2. Executes any tool calls
    3. Returns tool results
    4. Repeats until Claude provides a final answer
    """

    def __init__(
        self,
        session_id: str,
        model_id: str = "claude-sonnet",
        max_iterations: int = 20,
        max_tokens: int = 4096,
        verbose: bool = True
    ):
        self.session_id = session_id
        self.model_id = model_id
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.verbose = verbose
        self.chat = ChatService(verbose=verbose)
        self.tools = get_tool_definitions()
        self.iteration_log: list[dict] = []
        self._tool_id_counter = 0

    def _next_tool_id(self) -> str:
        """Generate a unique tool call ID for streaming events."""
        self._tool_id_counter += 1
        return f"tool_{self._tool_id_counter}"

    async def run(
        self,
        messages: list[dict],
        system: str = None
    ) -> dict:
        """
        Run the agent loop until completion.

        Args:
            messages: Conversation history (user/assistant messages)
            system: Optional system prompt override

        Returns:
            {
                "success": bool,
                "content": str,  # Final response text
                "tool_calls": int,  # Total tool calls made
                "iterations": int,  # Loop iterations
                "iteration_log": [...],  # Detailed log for debugging
                "usage": dict,  # Total token usage
                "error": str  # If failed
            }
        """
        if system is None:
            system = RLM_SYSTEM_PROMPT

        current_messages = messages.copy()
        total_tool_calls = 0
        total_usage = {"input_tokens": 0, "output_tokens": 0}

        for iteration in range(self.max_iterations):
            if self.verbose:
                print(f"\n[RLM Agent] Iteration {iteration + 1}")

            # Call Claude with tools
            result = await self._call_with_tools(current_messages, system)

            if not result.get("success"):
                return {
                    "success": False,
                    "content": None,
                    "tool_calls": total_tool_calls,
                    "iterations": iteration + 1,
                    "iteration_log": self.iteration_log,
                    "usage": total_usage,
                    "error": result.get("error", "Unknown error")
                }

            # Track usage
            if result.get("usage"):
                total_usage["input_tokens"] += result["usage"].get("input_tokens", 0)
                total_usage["output_tokens"] += result["usage"].get("output_tokens", 0)

            # Check for tool use
            tool_uses = result.get("tool_uses", [])
            text_content = result.get("content", "")
            stop_reason = result.get("stop_reason", "")

            # Log iteration
            self.iteration_log.append({
                "iteration": iteration + 1,
                "tool_calls": len(tool_uses),
                "text_length": len(text_content) if text_content else 0,
                "stop_reason": stop_reason
            })

            if not tool_uses:
                # No tool calls - Claude is done
                if self.verbose:
                    print(f"[RLM Agent] Complete after {iteration + 1} iterations")

                return {
                    "success": True,
                    "content": text_content,
                    "tool_calls": total_tool_calls,
                    "iterations": iteration + 1,
                    "iteration_log": self.iteration_log,
                    "usage": total_usage
                }

            # Execute tool calls
            total_tool_calls += len(tool_uses)

            # Add assistant message with tool use
            assistant_message = {"role": "assistant", "content": result["raw_content"]}
            current_messages.append(assistant_message)

            # Execute each tool and collect results
            tool_results = []
            for tool_use in tool_uses:
                tool_result = await self._execute_tool(tool_use)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use["id"],
                    "content": self._truncate_tool_result(tool_result)
                })

                if self.verbose:
                    print(f"  Tool: {tool_use['name']} -> {'error' if 'error' in tool_result else 'ok'}")

            # Add tool results as user message
            user_message = {"role": "user", "content": tool_results}
            current_messages.append(user_message)

        # Hit max iterations
        return {
            "success": False,
            "content": None,
            "tool_calls": total_tool_calls,
            "iterations": self.max_iterations,
            "iteration_log": self.iteration_log,
            "usage": total_usage,
            "error": f"Max iterations ({self.max_iterations}) reached"
        }

    async def run_streaming(
        self,
        messages: list[dict],
        system: str = None
    ):
        """
        Run the agent loop with streaming events.

        Yields events as dict with 'event' and 'data' keys:
        - start: {query} - Query begins
        - iteration_start: {iteration} - New loop iteration
        - tool_start: {id, name, input} - Tool execution begins
        - tool_complete: {id, name, success, preview} - Tool finished
        - complete: {content, tool_calls, iterations, usage} - Final answer
        - error: {error} - Failure

        Args:
            messages: Conversation history (user/assistant messages)
            system: Optional system prompt override

        Yields:
            Event dicts for SSE streaming
        """
        if system is None:
            system = RLM_SYSTEM_PROMPT

        # Extract query from last user message for start event
        query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    query = content
                break

        yield {"event": "start", "data": {"query": query}}

        current_messages = messages.copy()
        total_tool_calls = 0
        total_usage = {"input_tokens": 0, "output_tokens": 0}

        for iteration in range(self.max_iterations):
            yield {"event": "iteration_start", "data": {"iteration": iteration + 1}}

            if self.verbose:
                print(f"\n[RLM Agent] Iteration {iteration + 1}")

            # Call Claude with tools
            result = await self._call_with_tools(current_messages, system)

            if not result.get("success"):
                yield {
                    "event": "error",
                    "data": {"error": result.get("error", "Unknown error")}
                }
                return

            # Track usage
            if result.get("usage"):
                total_usage["input_tokens"] += result["usage"].get("input_tokens", 0)
                total_usage["output_tokens"] += result["usage"].get("output_tokens", 0)

            # Check for tool use
            tool_uses = result.get("tool_uses", [])
            text_content = result.get("content", "")
            stop_reason = result.get("stop_reason", "")

            # Log iteration
            self.iteration_log.append({
                "iteration": iteration + 1,
                "tool_calls": len(tool_uses),
                "text_length": len(text_content) if text_content else 0,
                "stop_reason": stop_reason
            })

            if not tool_uses:
                # No tool calls - Claude is done
                if self.verbose:
                    print(f"[RLM Agent] Complete after {iteration + 1} iterations")

                yield {
                    "event": "complete",
                    "data": {
                        "content": text_content,
                        "tool_calls": total_tool_calls,
                        "iterations": iteration + 1,
                        "usage": total_usage
                    }
                }
                return

            # Execute tool calls
            total_tool_calls += len(tool_uses)

            # Add assistant message with tool use
            assistant_message = {"role": "assistant", "content": result["raw_content"]}
            current_messages.append(assistant_message)

            # Execute each tool and collect results
            tool_results = []
            for tool_use in tool_uses:
                tool_id = self._next_tool_id()
                tool_name = tool_use["name"]
                tool_input = tool_use.get("input", {})

                # Emit tool_start event
                yield {
                    "event": "tool_start",
                    "data": {
                        "id": tool_id,
                        "name": tool_name,
                        "input": self._truncate_input(tool_input)
                    }
                }

                # Execute tool
                tool_result = await self._execute_tool(tool_use)
                success = "error" not in tool_result

                # Emit tool_complete event
                yield {
                    "event": "tool_complete",
                    "data": {
                        "id": tool_id,
                        "name": tool_name,
                        "success": success,
                        "preview": self._get_result_preview(tool_result)
                    }
                }

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use["id"],
                    "content": self._truncate_tool_result(tool_result)
                })

                if self.verbose:
                    print(f"  Tool: {tool_name} -> {'error' if not success else 'ok'}")

            # Add tool results as user message
            user_message = {"role": "user", "content": tool_results}
            current_messages.append(user_message)

        # Hit max iterations
        yield {
            "event": "error",
            "data": {"error": f"Max iterations ({self.max_iterations}) reached"}
        }

    def _truncate_input(self, input_dict: dict, max_len: int = 100) -> dict:
        """Truncate long values in tool input for display."""
        truncated = {}
        for key, value in input_dict.items():
            if isinstance(value, str) and len(value) > max_len:
                truncated[key] = value[:max_len] + "..."
            else:
                truncated[key] = value
        return truncated

    def _get_result_preview(self, result: dict, max_len: int = 150) -> str:
        """Generate a brief preview of tool result for display."""
        if "error" in result:
            return f"Error: {str(result['error'])[:max_len]}"
        if "count" in result:
            return f"Found {result['count']} results"
        if "results" in result and isinstance(result["results"], list):
            return f"Returned {len(result['results'])} items"
        if "content" in result:
            content = str(result["content"])
            return content[:max_len] + ("..." if len(content) > max_len else "")
        if "text" in result:
            text = str(result["text"])
            return text[:max_len] + ("..." if len(text) > max_len else "")
        # Generic preview
        preview = json.dumps(result, default=str)
        return preview[:max_len] + ("..." if len(preview) > max_len else "")

    def _truncate_tool_result(self, result: dict) -> str:
        """
        Truncate tool result for context.

        Prevents context blowout from large document reads while
        preserving enough content for Claude to work with.
        """
        result_json = json.dumps(result, default=str)
        if len(result_json) > MAX_TOOL_RESULT_LENGTH:
            # Truncate and add indicator
            truncated = result_json[:MAX_TOOL_RESULT_LENGTH]
            return truncated + f"...[truncated, {len(result_json) - MAX_TOOL_RESULT_LENGTH} chars omitted]"
        return result_json

    async def _call_with_tools(
        self,
        messages: list[dict],
        system: str
    ) -> dict:
        """
        Make a single Claude API call with tools enabled.

        Returns parsed response with tool_uses extracted.
        """
        result = await self.chat.chat_with_tools(
            model_id=self.model_id,
            messages=messages,
            system=system,
            tools=self.tools,
            max_tokens=self.max_tokens
        )

        return result

    async def _execute_tool(self, tool_use: dict) -> dict:
        """Execute a single tool call."""
        tool_name = tool_use["name"]
        tool_input = tool_use.get("input", {})

        if self.verbose:
            print(f"  Executing: {tool_name}({json.dumps(tool_input, default=str)[:100]}...)")

        return await execute_tool(
            tool_name=tool_name,
            session_id=self.session_id,
            **tool_input
        )


# =============================================================================
# Convenience Function
# =============================================================================

async def run_rlm_query(
    session_id: str,
    query: str,
    model_id: str = "claude-sonnet",
    conversation_history: list[dict] = None,
    max_iterations: int = 20,
    max_tokens: int = 4096,
    verbose: bool = True
) -> dict:
    """
    Run an RLM query with full agent loop.

    Args:
        session_id: Research session ID
        query: User's question
        model_id: Claude model to use
        conversation_history: Previous messages (optional)
        max_iterations: Max tool use loops
        max_tokens: Max tokens in LLM response
        verbose: Print progress

    Returns:
        Agent result dict with content, tool_calls, iterations, etc.
    """
    agent = RLMAgent(
        session_id=session_id,
        model_id=model_id,
        max_iterations=max_iterations,
        max_tokens=max_tokens,
        verbose=verbose
    )

    messages = conversation_history.copy() if conversation_history else []
    messages.append({"role": "user", "content": query})

    return await agent.run(messages)


async def run_rlm_query_streaming(
    session_id: str,
    query: str,
    model_id: str = "claude-sonnet",
    conversation_history: list[dict] = None,
    max_iterations: int = 20,
    max_tokens: int = 4096,
    verbose: bool = True
):
    """
    Run an RLM query with streaming events.

    Args:
        session_id: Research session ID
        query: User's question
        model_id: Claude model to use
        conversation_history: Previous messages (optional)
        max_iterations: Max tool use loops
        max_tokens: Max tokens in LLM response
        verbose: Print progress

    Yields:
        Event dicts for SSE streaming
    """
    agent = RLMAgent(
        session_id=session_id,
        model_id=model_id,
        max_iterations=max_iterations,
        max_tokens=max_tokens,
        verbose=verbose
    )

    messages = conversation_history.copy() if conversation_history else []
    messages.append({"role": "user", "content": query})

    async for event in agent.run_streaming(messages):
        yield event
