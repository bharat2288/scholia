"""
Council Service
===============
Multi-model LLM council for document analysis.

Adapted from research_council.py for Scholia integration:
- Uses httpx instead of aiohttp (consistent with Scholia patterns)
- Integrates with async SQLite for persistence
- SSE streaming support for real-time progress
"""

import asyncio
import httpx
from datetime import datetime
from typing import Optional, AsyncIterator

from .config import (
    COUNCIL_CONFIG, PRICING, MAX_RETRIES, RETRY_DELAY,
    get_api_key
)


class CouncilService:
    """
    Multi-model LLM council for document analysis.

    Three models deliberate independently, then Claude (chairman)
    synthesizes their perspectives into a unified output.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.config = COUNCIL_CONFIG

    def _log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(f"[Council] {message}")

    def _normalize_usage(self, provider: str, usage: dict) -> dict:
        """Normalize usage data to common format."""
        if provider == "anthropic":
            return {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0)
            }
        else:  # OpenAI and OpenRouter use same format
            return {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0)
            }

    def _calculate_cost(self, provider: str, usage: dict) -> float:
        """Calculate cost in USD for a single API call."""
        normalized = self._normalize_usage(provider, usage)
        pricing = PRICING.get(provider, {"input": 0, "output": 0})

        input_cost = (normalized["input_tokens"] / 1_000_000) * pricing["input"]
        output_cost = (normalized["output_tokens"] / 1_000_000) * pricing["output"]

        return input_cost + output_cost

    def _aggregate_usage(
        self,
        perspectives: list[dict],
        chairman_result: dict = None
    ) -> dict:
        """Aggregate usage across all API calls and calculate total cost."""
        usage_breakdown = []
        total_input = 0
        total_output = 0
        total_cost = 0.0

        # Process theorist perspectives
        for p in perspectives:
            if p.get("success") and p.get("usage"):
                provider = p["provider"]
                usage = p["usage"]
                normalized = self._normalize_usage(provider, usage)
                cost = self._calculate_cost(provider, usage)

                usage_breakdown.append({
                    "provider": provider,
                    "role": p.get("role", "theorist"),
                    "input_tokens": normalized["input_tokens"],
                    "output_tokens": normalized["output_tokens"],
                    "cost_usd": round(cost, 6)
                })

                total_input += normalized["input_tokens"]
                total_output += normalized["output_tokens"]
                total_cost += cost

        # Process chairman synthesis
        if chairman_result and chairman_result.get("success") and chairman_result.get("usage"):
            usage = chairman_result["usage"]
            normalized = self._normalize_usage("anthropic", usage)
            cost = self._calculate_cost("anthropic", usage)

            usage_breakdown.append({
                "provider": "anthropic",
                "role": "chairman",
                "input_tokens": normalized["input_tokens"],
                "output_tokens": normalized["output_tokens"],
                "cost_usd": round(cost, 6)
            })

            total_input += normalized["input_tokens"]
            total_output += normalized["output_tokens"]
            total_cost += cost

        return {
            "breakdown": usage_breakdown,
            "totals": {
                "input_tokens": total_input,
                "output_tokens": total_output,
                "total_tokens": total_input + total_output,
                "cost_usd": round(total_cost, 6)
            }
        }

    async def _call_anthropic(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        system: str = None,
        max_tokens: int = 4096
    ) -> dict:
        """Call Anthropic Claude API with retry logic."""
        config = self.config["anthropic"]
        api_key = get_api_key("anthropic")

        if not api_key:
            return {
                "provider": "anthropic",
                "model": config["model"],
                "role": config["role"],
                "success": False,
                "error": "API key not configured",
                "content": None
            }

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        payload = {
            "model": config["model"],
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        }
        if system:
            payload["system"] = system

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
                    return {
                        "provider": "anthropic",
                        "model": config["model"],
                        "role": config["role"],
                        "success": True,
                        "content": data["content"][0]["text"],
                        "usage": data.get("usage", {})
                    }
                else:
                    error_text = response.text[:200]
                    self._log(f"Anthropic error {response.status_code}: {error_text}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            except asyncio.TimeoutError:
                self._log(f"Anthropic timeout on attempt {attempt + 1}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            except Exception as e:
                self._log(f"Anthropic exception: {str(e)}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))

        return {
            "provider": "anthropic",
            "model": config["model"],
            "role": config["role"],
            "success": False,
            "error": "Max retries exceeded",
            "content": None
        }

    async def _call_openai(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        system: str = None,
        max_tokens: int = 4096
    ) -> dict:
        """Call OpenAI API with retry logic."""
        config = self.config["openai"]
        api_key = get_api_key("openai")

        if not api_key:
            return {
                "provider": "openai",
                "model": config["model"],
                "role": config["role"],
                "success": False,
                "error": "API key not configured",
                "content": None
            }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": config["model"],
            "max_completion_tokens": max_tokens,
            "messages": messages
        }

        for attempt in range(MAX_RETRIES):
            try:
                self._log(f"OpenAI attempt {attempt + 1}/{MAX_RETRIES}")
                response = await client.post(
                    config["api_url"],
                    headers=headers,
                    json=payload,
                    timeout=120.0
                )

                if response.status_code == 200:
                    data = response.json()
                    return {
                        "provider": "openai",
                        "model": config["model"],
                        "role": config["role"],
                        "success": True,
                        "content": data["choices"][0]["message"]["content"],
                        "usage": data.get("usage", {})
                    }
                else:
                    error_text = response.text[:200]
                    self._log(f"OpenAI error {response.status_code}: {error_text}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            except asyncio.TimeoutError:
                self._log(f"OpenAI timeout on attempt {attempt + 1}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            except Exception as e:
                self._log(f"OpenAI exception: {str(e)}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))

        return {
            "provider": "openai",
            "model": config["model"],
            "role": config["role"],
            "success": False,
            "error": "Max retries exceeded",
            "content": None
        }

    async def _call_openrouter(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        system: str = None,
        max_tokens: int = 4096
    ) -> dict:
        """Call OpenRouter API (Gemini) with retry logic."""
        config = self.config["openrouter"]
        api_key = get_api_key("openrouter")

        if not api_key:
            return {
                "provider": "openrouter",
                "model": config["model"],
                "role": config["role"],
                "success": False,
                "error": "API key not configured",
                "content": None
            }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/scholia",
            "X-Title": "Scholia Council"
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": config["model"],
            "max_tokens": max_tokens,
            "messages": messages
        }

        for attempt in range(MAX_RETRIES):
            try:
                self._log(f"OpenRouter attempt {attempt + 1}/{MAX_RETRIES}")
                response = await client.post(
                    config["api_url"],
                    headers=headers,
                    json=payload,
                    timeout=120.0
                )

                if response.status_code == 200:
                    data = response.json()
                    return {
                        "provider": "openrouter",
                        "model": config["model"],
                        "role": config["role"],
                        "success": True,
                        "content": data["choices"][0]["message"]["content"],
                        "usage": data.get("usage", {})
                    }
                else:
                    error_text = response.text[:200]
                    self._log(f"OpenRouter error {response.status_code}: {error_text}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            except asyncio.TimeoutError:
                self._log(f"OpenRouter timeout on attempt {attempt + 1}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            except Exception as e:
                self._log(f"OpenRouter exception: {str(e)}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))

        return {
            "provider": "openrouter",
            "model": config["model"],
            "role": config["role"],
            "success": False,
            "error": "Max retries exceeded",
            "content": None
        }

    async def _gather_perspectives(
        self,
        prompt: str,
        system: str = None
    ) -> list[dict]:
        """Gather perspectives from all three theorists in parallel."""
        async with httpx.AsyncClient() as client:
            tasks = [
                self._call_anthropic(client, prompt, system),
                self._call_openai(client, prompt, system),
                self._call_openrouter(client, prompt, system)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Handle any exceptions that weren't caught
            processed = []
            providers = ["anthropic", "openai", "openrouter"]
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed.append({
                        "provider": providers[i],
                        "success": False,
                        "error": str(result),
                        "content": None
                    })
                else:
                    processed.append(result)

            return processed

    async def _chairman_synthesize(
        self,
        query: str,
        perspectives: list[dict],
        context: str = None
    ) -> dict:
        """Chairman (Claude) synthesizes all perspectives into unified output."""
        # Filter successful responses
        valid_perspectives = [p for p in perspectives if p.get("success")]
        failed_providers = [p["provider"] for p in perspectives if not p.get("success")]

        if not valid_perspectives:
            return {
                "success": False,
                "error": "All theorists failed to respond",
                "synthesis": None,
                "failed_providers": failed_providers
            }

        # Build synthesis prompt
        perspectives_text = ""
        for p in valid_perspectives:
            perspectives_text += f"\n\n--- {p['provider'].upper()} ({p.get('role', 'theorist')}) ---\n"
            perspectives_text += p["content"]

        synthesis_prompt = f"""As the Chairman of this Council, synthesize the following
perspectives into a unified, coherent response.

ORIGINAL QUERY:
{query}

{f'CONTEXT PROVIDED:{chr(10)}{context}{chr(10)}' if context else ''}

COUNCIL PERSPECTIVES:
{perspectives_text}

---

Provide a synthesis that:
1. Identifies common threads across perspectives
2. Notes unique insights from each council member
3. Resolves any tensions or contradictions
4. Presents a unified conclusion that incorporates the strongest elements

Structure your synthesis with clear sections."""

        system_prompt = """You are the Chairman of a Council - an expert synthesizer
of diverse perspectives. Your role is to find coherence across viewpoints while
preserving the unique value each perspective brings. Be thorough but concise."""

        async with httpx.AsyncClient() as client:
            result = await self._call_anthropic(
                client,
                synthesis_prompt,
                system_prompt,
                max_tokens=8192
            )

        return {
            "success": result["success"],
            "synthesis": result.get("content"),
            "error": result.get("error"),
            "failed_providers": failed_providers if failed_providers else None,
            "usage": result.get("usage")
        }

    async def deliberate(
        self,
        query: str,
        context: str = None
    ) -> dict:
        """
        Main deliberation method: all 3 models respond, chairman synthesizes.

        Args:
            query: The question or topic for deliberation
            context: Optional additional context (e.g., selected text)

        Returns:
            dict with perspectives, synthesis, and metadata
        """
        self._log(f"Starting deliberation on: {query[:100]}...")

        # Build theorist prompt
        theorist_prompt = f"""Provide your perspective on the following query.
Draw upon your knowledge to offer unique insights.

QUERY:
{query}

{f'CONTEXT:{chr(10)}{context}' if context else ''}

Provide a substantive, well-reasoned response."""

        system_prompt = """You are a member of a Council of diverse AI perspectives.
Provide your unique, substantive perspective on the query. Be thorough and
don't shy away from nuanced or contrarian positions if warranted."""

        # Gather perspectives in parallel
        self._log("Gathering perspectives from all theorists...")
        perspectives = await self._gather_perspectives(theorist_prompt, system_prompt)

        successful = sum(1 for p in perspectives if p.get("success"))
        self._log(f"Received {successful}/3 successful responses")

        # Chairman synthesizes
        self._log("Chairman synthesizing perspectives...")
        synthesis_result = await self._chairman_synthesize(query, perspectives, context)

        # Aggregate usage data
        usage = self._aggregate_usage(perspectives, synthesis_result)
        self._log(f"Total tokens: {usage['totals']['total_tokens']}, Cost: ${usage['totals']['cost_usd']:.4f}")

        return {
            "query": query,
            "context": context,
            "perspectives": perspectives,
            "synthesis": synthesis_result.get("synthesis"),
            "success": synthesis_result["success"],
            "failed_providers": synthesis_result.get("failed_providers"),
            "timestamp": datetime.now().isoformat(),
            "usage": usage,
            "config": {k: {"model": v["model"], "role": v["role"]}
                      for k, v in self.config.items()}
        }

    async def query_single(
        self,
        query: str,
        context: str = None,
        model: str = "anthropic",
        system_prompt: str = None,
        max_tokens: int = 4096
    ) -> dict:
        """
        Query a single model (no synthesis).

        Args:
            query: The question or topic
            context: Optional additional context
            model: Provider name ('anthropic', 'openai', 'openrouter')
            system_prompt: Optional custom system prompt
            max_tokens: Maximum response tokens

        Returns:
            dict with content, usage, and metadata
        """
        self._log(f"Querying single model ({model}): {query[:100]}...")

        # Build prompt
        prompt = f"""Answer the following query thoughtfully and thoroughly.

QUERY:
{query}

{f'CONTEXT:{chr(10)}{context}' if context else ''}

Provide a substantive, well-reasoned response."""

        if not system_prompt:
            system_prompt = """You are a helpful AI assistant. Provide thorough,
accurate, and insightful responses to queries."""

        # Call the appropriate model
        async with httpx.AsyncClient() as client:
            if model == "anthropic":
                result = await self._call_anthropic(client, prompt, system_prompt, max_tokens)
            elif model == "openai":
                result = await self._call_openai(client, prompt, system_prompt, max_tokens)
            elif model == "openrouter":
                result = await self._call_openrouter(client, prompt, system_prompt, max_tokens)
            else:
                return {
                    "query": query,
                    "success": False,
                    "error": f"Unknown model: {model}"
                }

        # Calculate usage/cost in the same format as deliberate()
        usage = None
        if result.get("success") and result.get("usage"):
            normalized = self._normalize_usage(model, result["usage"])
            cost = self._calculate_cost(model, result["usage"])
            usage = {
                "breakdown": [{
                    "provider": model,
                    "role": "single",
                    "input_tokens": normalized["input_tokens"],
                    "output_tokens": normalized["output_tokens"],
                    "cost_usd": round(cost, 6)
                }],
                "totals": {
                    "input_tokens": normalized["input_tokens"],
                    "output_tokens": normalized["output_tokens"],
                    "total_tokens": normalized["input_tokens"] + normalized["output_tokens"],
                    "cost_usd": round(cost, 6)
                }
            }
            self._log(f"Tokens: {normalized['input_tokens']} in, {normalized['output_tokens']} out, Cost: ${cost:.4f}")

        return {
            "query": query,
            "context": context,
            "model": model,
            "content": result.get("content"),
            "success": result.get("success", False),
            "error": result.get("error"),
            "timestamp": datetime.now().isoformat(),
            "usage": usage
        }

    async def deliberate_streaming(
        self,
        query: str,
        context: str = None
    ) -> AsyncIterator[dict]:
        """
        Streaming version of deliberate - yields progress events.

        Yields dicts with 'event' and 'data' keys for SSE.
        """
        self._log(f"Starting streaming deliberation on: {query[:100]}...")

        # Build theorist prompt
        theorist_prompt = f"""Provide your perspective on the following query.
Draw upon your knowledge to offer unique insights.

QUERY:
{query}

{f'CONTEXT:{chr(10)}{context}' if context else ''}

Provide a substantive, well-reasoned response."""

        system_prompt = """You are a member of a Council of diverse AI perspectives.
Provide your unique, substantive perspective on the query. Be thorough and
don't shy away from nuanced or contrarian positions if warranted."""

        # Yield start event
        yield {"event": "start", "data": {"query": query, "timestamp": datetime.now().isoformat()}}

        # Call each model and yield progress as they complete
        perspectives = []
        providers = ["anthropic", "openai", "openrouter"]

        async with httpx.AsyncClient() as client:
            # Create tasks for all three
            tasks = {
                "anthropic": asyncio.create_task(self._call_anthropic(client, theorist_prompt, system_prompt)),
                "openai": asyncio.create_task(self._call_openai(client, theorist_prompt, system_prompt)),
                "openrouter": asyncio.create_task(self._call_openrouter(client, theorist_prompt, system_prompt))
            }

            # Signal that all models are starting
            for provider in providers:
                yield {"event": "model_start", "data": {"provider": provider}}

            # Process as they complete
            pending = set(tasks.values())
            task_to_provider = {v: k for k, v in tasks.items()}

            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    provider = task_to_provider[task]
                    try:
                        result = task.result()
                        perspectives.append(result)
                        yield {
                            "event": "model_complete",
                            "data": {
                                "provider": provider,
                                "success": result.get("success", False),
                                "content": result.get("content"),
                                "usage": result.get("usage")
                            }
                        }
                    except Exception as e:
                        perspectives.append({
                            "provider": provider,
                            "success": False,
                            "error": str(e),
                            "content": None
                        })
                        yield {
                            "event": "model_complete",
                            "data": {"provider": provider, "success": False, "error": str(e)}
                        }

        # Chairman synthesis
        yield {"event": "synthesis_start", "data": {}}

        synthesis_result = await self._chairman_synthesize(query, perspectives, context)

        yield {
            "event": "synthesis_complete",
            "data": {
                "synthesis": synthesis_result.get("synthesis"),
                "success": synthesis_result.get("success"),
                "usage": synthesis_result.get("usage")
            }
        }

        # Aggregate usage
        usage = self._aggregate_usage(perspectives, synthesis_result)

        # Final result
        yield {
            "event": "complete",
            "data": {
                "query": query,
                "context": context,
                "perspectives": perspectives,
                "synthesis": synthesis_result.get("synthesis"),
                "success": synthesis_result["success"],
                "failed_providers": synthesis_result.get("failed_providers"),
                "timestamp": datetime.now().isoformat(),
                "usage": usage
            }
        }
