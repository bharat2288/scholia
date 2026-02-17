"""
Chat Service
============
Single-model LLM chat for document analysis.

Simpler alternative to the Council for quick Q&A with documents.
Stateless API - client sends full conversation history with each request.
"""

import asyncio
import httpx
from datetime import datetime
from typing import Optional

from .config import (
    CHAT_MODELS, MAX_RETRIES, RETRY_DELAY,
    get_api_key
)


def build_system_prompt(
    source_type: str = "document",
    source_title: str = None,
) -> str:
    """
    Build a source-type-aware system prompt for chat.

    Args:
        source_type: One of 'document', 'web', 'thread', 'media'
        source_title: Optional title of the source being analyzed
    """
    type_descriptions = {
        "document": "an academic document",
        "web": "a web article",
        "thread": "a social media thread",
        "media": "a video or podcast transcript",
    }
    type_desc = type_descriptions.get(source_type, "a document")
    title_clause = f' titled "{source_title}"' if source_title else ""

    return f"""You are a scholarly AI assistant analyzing {type_desc}{title_clause}.

Your approach:
- Be thorough and precise. Cite specific passages when making claims.
- Maintain a scholarly register — substantive but accessible.
- Distinguish between what the text says, what it implies, and what you infer.
- Ground explanations in the source material provided.
- If a question goes beyond the text, say so and label speculation as such."""


class ChatService:
    """
    Single-model chat service for document analysis.

    Features:
    - Stateless API (client manages history)
    - Multiple model support (Anthropic, OpenAI)
    - Token usage tracking and cost calculation
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def _log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(f"[Chat] {message}")

    def _normalize_usage(self, provider: str, usage: dict) -> dict:
        """Normalize usage data to common format."""
        if provider == "anthropic":
            return {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0)
            }
        else:  # OpenAI
            return {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0)
            }

    def _calculate_cost(self, model_id: str, usage: dict) -> float:
        """
        Calculate cost in USD for an API call.

        For Anthropic with prompt caching:
        - cache_creation_input_tokens: 1.25x base input price
        - cache_read_input_tokens: 0.1x base input price (90% savings)
        - Regular input_tokens: base price
        """
        config = CHAT_MODELS.get(model_id)
        if not config:
            return 0.0

        pricing = config.get("pricing", {"input": 0, "output": 0})
        provider = config["provider"]

        if provider == "anthropic":
            # Anthropic with cache support
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            cache_creation = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)

            # Regular input tokens (excluding cached)
            regular_input = input_tokens - cache_creation - cache_read

            # Calculate costs with cache pricing
            regular_input_cost = (regular_input / 1_000_000) * pricing["input"]
            cache_creation_cost = (cache_creation / 1_000_000) * pricing["input"] * 1.25  # 25% more
            cache_read_cost = (cache_read / 1_000_000) * pricing["input"] * 0.1  # 90% less
            output_cost = (output_tokens / 1_000_000) * pricing["output"]

            return regular_input_cost + cache_creation_cost + cache_read_cost + output_cost
        else:
            # OpenAI and others - standard pricing
            normalized = self._normalize_usage(provider, usage)
            input_cost = (normalized["input_tokens"] / 1_000_000) * pricing["input"]
            output_cost = (normalized["output_tokens"] / 1_000_000) * pricing["output"]
            return input_cost + output_cost

    async def _call_anthropic(
        self,
        client: httpx.AsyncClient,
        model_id: str,
        messages: list[dict],
        system: str = None,
        context: str = None,
        max_tokens: int = 12288
    ) -> dict:
        """
        Call Anthropic Claude API with retry logic and prompt caching.

        When context is provided, it's placed in a cacheable block to reduce
        costs on subsequent calls with the same context (90% reduction).
        """
        config = CHAT_MODELS.get(model_id)
        if not config or config["provider"] != "anthropic":
            return {
                "success": False,
                "error": f"Invalid Anthropic model: {model_id}",
                "content": None
            }

        api_key = get_api_key("anthropic")
        if not api_key:
            return {
                "success": False,
                "error": "Anthropic API key not configured",
                "content": None
            }

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        # Note: Prompt caching is now GA - no beta header needed
        # cache_control in system blocks is automatically honored

        # Convert messages to Anthropic format
        anthropic_messages = []
        for msg in messages:
            anthropic_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        payload = {
            "model": config["model"],
            "max_tokens": max_tokens,
            "messages": anthropic_messages
        }

        # Build system prompt with caching support
        # System can be a string OR array of content blocks
        # For caching, we use array format with cache_control on the context block
        system_blocks = []

        # Base system instructions (always included, not cached - small and may change)
        base_system = system or build_system_prompt()
        system_blocks.append({
            "type": "text",
            "text": base_system
        })

        # Document context (CACHED - large and repeated across messages)
        if context:
            context_block = {
                "type": "text",
                "text": f"\n\nDOCUMENT CONTEXT:\n{context}\n\nWhen answering, reference specific parts of the document when relevant."
            }
            # Only add cache_control if context is substantial (>1024 tokens ~ 4000 chars)
            # Caching has overhead, not worth it for tiny contexts
            if len(context) > 1000:
                context_block["cache_control"] = {"type": "ephemeral"}
                self._log(f"Context caching enabled ({len(context)} chars)")
            system_blocks.append(context_block)

        payload["system"] = system_blocks

        last_error = "Unknown error"
        for attempt in range(MAX_RETRIES):
            try:
                self._log(f"Anthropic attempt {attempt + 1}/{MAX_RETRIES}")
                response = await client.post(
                    config["api_url"],
                    headers=headers,
                    json=payload,
                    timeout=120.0
                )

                if response.status_code == 200:
                    data = response.json()
                    usage = data.get("usage", {})
                    return {
                        "success": True,
                        "content": data["content"][0]["text"],
                        "usage": usage,
                        "model": config["model"]
                    }
                else:
                    error_text = response.text[:200]
                    last_error = f"HTTP {response.status_code}: {error_text}"
                    self._log(f"Anthropic error {response.status_code}: {error_text}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
            except asyncio.TimeoutError:
                last_error = f"Timeout after 120s on attempt {attempt + 1}"
                self._log(f"Anthropic timeout on attempt {attempt + 1}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                self._log(f"Anthropic exception ({type(e).__name__}): {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))

        return {
            "success": False,
            "error": f"Max retries exceeded — last error: {last_error}",
            "content": None
        }

    async def _call_openai_compatible(
        self,
        client: httpx.AsyncClient,
        model_id: str,
        messages: list[dict],
        system: str = None,
        max_tokens: int = 12288
    ) -> dict:
        """Call OpenAI-compatible API (OpenAI, OpenRouter) with retry logic."""
        config = CHAT_MODELS.get(model_id)
        provider = config["provider"] if config else None
        if not config or provider not in ("openai", "openrouter"):
            return {
                "success": False,
                "error": f"Invalid OpenAI-compatible model: {model_id}",
                "content": None
            }

        api_key = get_api_key(provider)
        if not api_key:
            return {
                "success": False,
                "error": f"{provider} API key not configured",
                "content": None
            }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        # OpenRouter best practice: identify the app
        if provider == "openrouter":
            headers["HTTP-Referer"] = "http://localhost:5176"
            headers["X-Title"] = "Scholia"

        # Build OpenAI messages
        openai_messages = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        for msg in messages:
            openai_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        payload = {
            "model": config["model"],
            "max_completion_tokens": max_tokens,
            "messages": openai_messages
        }

        for attempt in range(MAX_RETRIES):
            try:
                self._log(f"{provider} attempt {attempt + 1}/{MAX_RETRIES}")
                response = await client.post(
                    config["api_url"],
                    headers=headers,
                    json=payload,
                    timeout=120.0
                )

                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "content": data["choices"][0]["message"]["content"],
                        "usage": data.get("usage", {}),
                        "model": config["model"]
                    }
                else:
                    error_text = response.text[:200]
                    self._log(f"{provider} error {response.status_code}: {error_text}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
            except asyncio.TimeoutError:
                self._log(f"{provider} timeout on attempt {attempt + 1}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
            except Exception as e:
                self._log(f"{provider} exception: {str(e)}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))

        return {
            "success": False,
            "error": "Max retries exceeded",
            "content": None
        }

    async def chat(
        self,
        model_id: str,
        messages: list[dict],
        system: str = None,
        context: str = None,
        max_tokens: int = 12288,
        source_type: str = None,
        source_title: str = None,
    ) -> dict:
        """
        Send a chat request to the specified model.

        Args:
            model_id: Model identifier (e.g., 'claude-sonnet', 'gpt-4o')
            messages: List of {role: 'user'|'assistant', content: str}
            system: Optional system prompt (overrides auto-generated one)
            context: Optional document context (cached for Anthropic models)
            max_tokens: Maximum response tokens
            source_type: Source type for context-aware system prompt
            source_title: Source title for context-aware system prompt

        Returns:
            dict with content, usage, and metadata
        """
        config = CHAT_MODELS.get(model_id)
        if not config:
            return {
                "success": False,
                "error": f"Unknown model: {model_id}",
                "content": None
            }

        self._log(f"Chat request to {model_id}: {len(messages)} messages")

        # Build source-type-aware system prompt if none provided
        effective_system = system or build_system_prompt(
            source_type=source_type or "document",
            source_title=source_title,
        )

        # Call the appropriate API
        async with httpx.AsyncClient() as client:
            if config["provider"] == "anthropic":
                # Anthropic: pass context separately for caching support
                result = await self._call_anthropic(
                    client, model_id, messages, effective_system, context, max_tokens
                )
            elif config["provider"] in ("openai", "openrouter"):
                # OpenAI-compatible: merge context into system prompt
                full_system = effective_system
                if context:
                    full_system = f"""{full_system}

DOCUMENT CONTEXT:
{context}

When answering, reference specific parts of the document when relevant."""
                result = await self._call_openai_compatible(
                    client, model_id, messages, full_system, max_tokens
                )
            else:
                return {
                    "success": False,
                    "error": f"Unknown provider: {config['provider']}",
                    "content": None
                }

        # Calculate usage/cost (with cache awareness for Anthropic)
        usage = None
        if result.get("success") and result.get("usage"):
            raw_usage = result["usage"]
            normalized = self._normalize_usage(config["provider"], raw_usage)
            cost = self._calculate_cost(model_id, raw_usage)

            usage = {
                "input_tokens": normalized["input_tokens"],
                "output_tokens": normalized["output_tokens"],
                "total_tokens": normalized["input_tokens"] + normalized["output_tokens"],
                "cost_usd": round(cost, 6)
            }

            # Add cache info for Anthropic (if present)
            if config["provider"] == "anthropic":
                cache_creation = raw_usage.get("cache_creation_input_tokens", 0)
                cache_read = raw_usage.get("cache_read_input_tokens", 0)
                if cache_creation or cache_read:
                    usage["cache_creation_tokens"] = cache_creation
                    usage["cache_read_tokens"] = cache_read
                    cache_status = "HIT" if cache_read > 0 else "MISS (created)"
                    self._log(f"Cache {cache_status}: {cache_read} read, {cache_creation} created")

            self._log(f"Tokens: {normalized['input_tokens']} in, {normalized['output_tokens']} out, Cost: ${cost:.4f}")

        return {
            "success": result.get("success", False),
            "content": result.get("content"),
            "error": result.get("error"),
            "model_id": model_id,
            "model": result.get("model"),
            "timestamp": datetime.now().isoformat(),
            "usage": usage
        }

    async def _call_anthropic_with_tools(
        self,
        client: httpx.AsyncClient,
        model_id: str,
        messages: list[dict],
        system: str,
        tools: list[dict],
        max_tokens: int = 12288
    ) -> dict:
        """
        Call Anthropic Claude API with tool use enabled.

        This method handles tool-augmented conversations where Claude
        can request tool execution and receive results.
        """
        config = CHAT_MODELS.get(model_id)
        if not config or config["provider"] != "anthropic":
            return {
                "success": False,
                "error": f"Invalid Anthropic model: {model_id}",
                "content": None
            }

        api_key = get_api_key("anthropic")
        if not api_key:
            return {
                "success": False,
                "error": "Anthropic API key not configured",
                "content": None
            }

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        # Build payload with tools
        payload = {
            "model": config["model"],
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": tools
        }

        # Add system prompt
        if system:
            payload["system"] = system

        last_error = "Unknown error"
        for attempt in range(MAX_RETRIES):
            try:
                self._log(f"Anthropic (tools) attempt {attempt + 1}/{MAX_RETRIES}")
                response = await client.post(
                    config["api_url"],
                    headers=headers,
                    json=payload,
                    timeout=180.0  # Longer timeout for tool-heavy responses
                )

                if response.status_code == 200:
                    data = response.json()
                    usage = data.get("usage", {})
                    stop_reason = data.get("stop_reason", "")

                    # Parse content blocks - may contain text and tool_use
                    content_blocks = data.get("content", [])
                    text_content = ""
                    tool_uses = []

                    for block in content_blocks:
                        if block.get("type") == "text":
                            text_content += block.get("text", "")
                        elif block.get("type") == "tool_use":
                            tool_uses.append({
                                "id": block.get("id"),
                                "name": block.get("name"),
                                "input": block.get("input", {})
                            })

                    return {
                        "success": True,
                        "content": text_content,
                        "tool_uses": tool_uses,
                        "raw_content": content_blocks,
                        "stop_reason": stop_reason,
                        "usage": usage,
                        "model": config["model"]
                    }
                else:
                    error_text = response.text[:200]
                    last_error = f"HTTP {response.status_code}: {error_text}"
                    self._log(f"Anthropic error {response.status_code}: {error_text}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
            except asyncio.TimeoutError:
                last_error = f"Timeout after 180s on attempt {attempt + 1}"
                self._log(f"Anthropic timeout on attempt {attempt + 1}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                self._log(f"Anthropic exception ({type(e).__name__}): {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))

        return {
            "success": False,
            "error": f"Max retries exceeded — last error: {last_error}",
            "content": None
        }

    async def chat_with_tools(
        self,
        model_id: str,
        messages: list[dict],
        system: str,
        tools: list[dict],
        max_tokens: int = 12288
    ) -> dict:
        """
        Send a chat request with tool definitions.

        This is used by the RLM agent loop for tool-augmented conversations.

        Args:
            model_id: Model identifier (must be Anthropic for now)
            messages: Conversation history (may include tool results)
            system: System prompt
            tools: List of tool definitions in Claude format
            max_tokens: Maximum response tokens

        Returns:
            dict with:
            - success: bool
            - content: str (text content)
            - tool_uses: list of tool calls [{id, name, input}]
            - raw_content: list of content blocks (for message reconstruction)
            - stop_reason: str ('end_turn', 'tool_use', etc.)
            - usage: dict
            - model: str
        """
        config = CHAT_MODELS.get(model_id)
        if not config:
            return {
                "success": False,
                "error": f"Unknown model: {model_id}",
                "content": None
            }

        if config["provider"] != "anthropic":
            return {
                "success": False,
                "error": "Tool use only supported for Anthropic models currently",
                "content": None
            }

        self._log(f"Chat with tools to {model_id}: {len(messages)} messages, {len(tools)} tools")

        async with httpx.AsyncClient() as client:
            result = await self._call_anthropic_with_tools(
                client, model_id, messages, system, tools, max_tokens
            )

        # Add usage calculation
        if result.get("success") and result.get("usage"):
            raw_usage = result["usage"]
            normalized = self._normalize_usage("anthropic", raw_usage)
            cost = self._calculate_cost(model_id, raw_usage)

            result["usage"] = {
                "input_tokens": normalized["input_tokens"],
                "output_tokens": normalized["output_tokens"],
                "total_tokens": normalized["input_tokens"] + normalized["output_tokens"],
                "cost_usd": round(cost, 6)
            }

            self._log(f"Tokens: {normalized['input_tokens']} in, {normalized['output_tokens']} out, Cost: ${cost:.4f}")
            if result.get("tool_uses"):
                self._log(f"Tool calls: {len(result['tool_uses'])}")

        return result
