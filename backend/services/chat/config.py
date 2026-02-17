"""
Chat Configuration
==================
Model definitions and pricing for single-model chat.

Supports Anthropic, OpenAI, and OpenRouter (OpenAI-compatible) providers.
Each model includes tier_hints indicating recommended RLM roles:
  - "orchestrator": fast code-writing tier (strong coders only)
  - "sub": cheap reasoning tier
  - "synthesis": high-quality final answer tier
"""

import os
from typing import Optional

# Chat model configuration
CHAT_MODELS = {
    # =========================================================================
    # ANTHROPIC (direct API)
    # =========================================================================
    "claude-haiku": {
        "provider": "anthropic",
        "model": "claude-3-5-haiku-20241022",
        "display_name": "Claude 3.5 Haiku",
        "description": "Fast and efficient for simple tasks",
        "api_url": "https://api.anthropic.com/v1/messages",
        "pricing": {"input": 1.00, "output": 5.00},
        "default": False,
        "tier_hints": ["sub"],
    },
    "claude-sonnet": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "display_name": "Claude 4 Sonnet",
        "description": "Balanced performance and capability",
        "api_url": "https://api.anthropic.com/v1/messages",
        "pricing": {"input": 3.00, "output": 15.00},
        "default": True,
        "tier_hints": ["orchestrator"],
    },
    "claude-opus-45": {
        "provider": "anthropic",
        "model": "claude-opus-4-5-20251101",
        "display_name": "Claude Opus 4.5",
        "description": "Previous flagship model",
        "api_url": "https://api.anthropic.com/v1/messages",
        "pricing": {"input": 15.00, "output": 75.00},
        "default": False,
        "tier_hints": ["synthesis"],
    },
    "claude-opus": {
        "provider": "anthropic",
        "model": "claude-opus-4-6",
        "display_name": "Claude Opus 4.6",
        "description": "Most capable, 1M context, best for complex analysis",
        "api_url": "https://api.anthropic.com/v1/messages",
        "pricing": {"input": 15.00, "output": 75.00},
        "default": False,
        "tier_hints": ["orchestrator", "synthesis"],
    },
    # =========================================================================
    # OPENAI (direct API)
    # =========================================================================
    "gpt-4o-mini": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "display_name": "GPT-4o Mini",
        "description": "Fast and cost-effective",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "pricing": {"input": 0.15, "output": 0.60},
        "default": False,
        "tier_hints": ["sub"],
    },
    "gpt-4o": {
        "provider": "openai",
        "model": "gpt-4o",
        "display_name": "GPT-4o",
        "description": "Powerful multimodal model",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "pricing": {"input": 2.50, "output": 10.00},
        "default": False,
        "tier_hints": ["synthesis"],
    },
    "gpt-4.1": {
        "provider": "openai",
        "model": "gpt-4.1",
        "display_name": "GPT-4.1",
        "description": "Optimized for coding and instruction following",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "pricing": {"input": 2.00, "output": 8.00},
        "default": False,
        "tier_hints": ["orchestrator"],
    },
    "gpt-4.1-mini": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "display_name": "GPT-4.1 Mini",
        "description": "Smaller GPT-4.1, good balance of cost and coding",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "pricing": {"input": 0.40, "output": 1.60},
        "default": False,
        "tier_hints": ["orchestrator", "sub"],
    },
    "gpt-5": {
        "provider": "openai",
        "model": "gpt-5",
        "display_name": "GPT-5",
        "description": "OpenAI frontier model, 400K context",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "pricing": {"input": 1.25, "output": 10.00},
        "default": False,
        "tier_hints": ["orchestrator", "synthesis"],
    },
    "gpt-5.2": {
        "provider": "openai",
        "model": "gpt-5.2",
        "display_name": "GPT-5.2",
        "description": "Smartest OpenAI model, 400K context",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "pricing": {"input": 1.75, "output": 14.00},
        "default": False,
        "tier_hints": ["orchestrator", "synthesis"],
    },
    "o3": {
        "provider": "openai",
        "model": "o3",
        "display_name": "O3",
        "description": "Reasoning model, 200K context (reasoning tokens billed as output)",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "pricing": {"input": 2.00, "output": 8.00},
        "default": False,
        "tier_hints": ["orchestrator", "synthesis"],
    },
    "o4-mini": {
        "provider": "openai",
        "model": "o4-mini",
        "display_name": "O4 Mini",
        "description": "Fast reasoning model, 200K context",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "pricing": {"input": 1.10, "output": 4.40},
        "default": False,
        "tier_hints": ["orchestrator", "sub"],
    },
    # =========================================================================
    # OPENROUTER (OpenAI-compatible API)
    # =========================================================================
    "gemini-flash": {
        "provider": "openrouter",
        "model": "google/gemini-2.5-flash-preview",
        "display_name": "Gemini 2.5 Flash",
        "description": "Google's fast model, 1M context",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "pricing": {"input": 0.15, "output": 0.60},
        "default": False,
        "tier_hints": ["sub"],
    },
    "gemini-3-flash": {
        "provider": "openrouter",
        "model": "google/gemini-3-flash-preview",
        "display_name": "Gemini 3 Flash",
        "description": "Near-Pro reasoning, 1M context, configurable thinking",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "pricing": {"input": 0.50, "output": 3.00},
        "default": False,
        "tier_hints": ["orchestrator", "sub"],
    },
    "gemini-25-pro": {
        "provider": "openrouter",
        "model": "google/gemini-2.5-pro",
        "display_name": "Gemini 2.5 Pro",
        "description": "#1 LMArena, 1M context, strong reasoning",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "pricing": {"input": 1.25, "output": 10.00},
        "default": False,
        "tier_hints": ["orchestrator", "synthesis"],
    },
    "gemini-3-pro": {
        "provider": "openrouter",
        "model": "google/gemini-3-pro-preview",
        "display_name": "Gemini 3 Pro",
        "description": "Google frontier, 1M context, multimodal reasoning",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "pricing": {"input": 2.00, "output": 12.00},
        "default": False,
        "tier_hints": ["orchestrator", "synthesis"],
    },
    "grok-code": {
        "provider": "openrouter",
        "model": "x-ai/grok-code-fast-1",
        "display_name": "Grok Code Fast 1",
        "description": "xAI coding specialist, 256K context, fast",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "pricing": {"input": 0.20, "output": 1.50},
        "default": False,
        "tier_hints": ["orchestrator"],
    },
    "qwen3-coder": {
        "provider": "openrouter",
        "model": "qwen/qwen3-coder",
        "display_name": "Qwen3 Coder 480B",
        "description": "MoE coding specialist (35B active), 262K context",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "pricing": {"input": 0.22, "output": 1.00},
        "default": False,
        "tier_hints": ["orchestrator", "sub"],
    },
    "deepseek-v3": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat-v3-0324",
        "display_name": "DeepSeek V3",
        "description": "Strong coder, very cheap",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "pricing": {"input": 0.27, "output": 1.10},
        "default": False,
        "tier_hints": ["orchestrator", "sub"],
    },
    "deepseek-v3.1": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat-v3.1",
        "display_name": "DeepSeek V3.1",
        "description": "Hybrid reasoning (671B/37B active), thinking modes",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "pricing": {"input": 0.15, "output": 0.75},
        "default": False,
        "tier_hints": ["orchestrator", "sub"],
    },
    "llama-70b": {
        "provider": "openrouter",
        "model": "meta-llama/llama-3.3-70b-instruct",
        "display_name": "Llama 3.3 70B",
        "description": "Open-source, fast and capable",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "pricing": {"input": 0.40, "output": 0.40},
        "default": False,
        "tier_hints": ["sub"],
    },
}

# Retry configuration
MAX_RETRIES = 5
RETRY_DELAY = 3  # seconds (exponential backoff: 3, 6, 12, 24, 48)


def get_api_key(provider: str) -> Optional[str]:
    """Get API key for a provider."""
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY")
    elif provider == "openai":
        return os.getenv("OPENAI_COUNCIL_KEY") or os.getenv("OPENAI_API_KEY")
    elif provider == "openrouter":
        return os.getenv("OPENROUTER_API_KEY")
    return None


def get_chat_models() -> list[dict]:
    """
    Get list of available chat models with their status.
    Checks if API keys are configured.
    """
    models = []
    for model_id, config in CHAT_MODELS.items():
        api_key = get_api_key(config["provider"])
        models.append({
            "id": model_id,
            "name": config["display_name"],
            "description": config["description"],
            "model": config["model"],
            "provider": config["provider"],
            "available": api_key is not None and len(api_key) > 0,
            "default": config.get("default", False),
            "pricing": config["pricing"],
            "tier_hints": config.get("tier_hints", []),
        })
    return models


def get_default_model() -> str:
    """Get the default model ID."""
    for model_id, config in CHAT_MODELS.items():
        if config.get("default"):
            return model_id
    return "claude-sonnet"
