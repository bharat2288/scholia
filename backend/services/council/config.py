"""
Council Configuration
=====================
Model configuration, pricing, and API key management.
"""

import os
from typing import Optional

# Council model configuration
# Models can be overridden via environment variables
COUNCIL_CONFIG = {
    "anthropic": {
        "model": os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5-20251101"),
        "display_name": "Claude Opus",
        "role": "primary",
        "chairman": True,
        "api_url": "https://api.anthropic.com/v1/messages"
    },
    "openai": {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.2"),
        "display_name": "GPT-5",
        "role": "secondary",
        "api_url": "https://api.openai.com/v1/chat/completions"
    },
    "openrouter": {
        "model": os.getenv("OPENROUTER_MODEL", "google/gemini-3-pro-preview"),
        "display_name": "Gemini 3 Pro",
        "role": "tertiary",
        "api_url": "https://openrouter.ai/api/v1/chat/completions"
    }
}

# Pricing per 1M tokens (USD)
PRICING = {
    "anthropic": {
        "input": 15.00,   # Claude Opus 4.5
        "output": 75.00
    },
    "openai": {
        "input": 10.00,   # GPT-5.2 estimate
        "output": 30.00
    },
    "openrouter": {
        "input": 2.50,    # Gemini 3 Pro via OpenRouter
        "output": 7.50
    }
}

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def get_api_key(provider: str) -> Optional[str]:
    """Get API key for a provider."""
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY")
    elif provider == "openai":
        return os.getenv("OPENAI_COUNCIL_KEY")
    elif provider == "openrouter":
        return os.getenv("OPENROUTER_API_KEY")
    return None


def get_available_models() -> list[dict]:
    """
    Get list of available models with their status.
    Checks if API keys are configured.
    """
    models = []
    for provider, config in COUNCIL_CONFIG.items():
        api_key = get_api_key(provider)
        models.append({
            "id": provider,
            "name": config["display_name"],
            "model": config["model"],
            "available": api_key is not None and len(api_key) > 0,
            "role": config["role"],
            "chairman": config.get("chairman", False)
        })
    return models


def validate_api_keys() -> dict:
    """
    Validate all API keys and return status.
    Returns dict with provider -> status mapping.
    """
    status = {}
    for provider in COUNCIL_CONFIG.keys():
        api_key = get_api_key(provider)
        if api_key and len(api_key) > 10:
            status[provider] = {
                "status": "configured",
                "key_prefix": api_key[:8] + "..."
            }
        else:
            status[provider] = {
                "status": "missing",
                "key_prefix": None
            }
    return status
