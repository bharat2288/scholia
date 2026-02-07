"""
Chat Configuration
==================
Model definitions and pricing for single-model chat.
"""

import os
from typing import Optional

# Chat model configuration
# Supports Anthropic and OpenAI models
CHAT_MODELS = {
    "claude-haiku": {
        "provider": "anthropic",
        "model": "claude-3-5-haiku-20241022",
        "display_name": "Claude 3.5 Haiku",
        "description": "Fast and efficient for simple tasks",
        "api_url": "https://api.anthropic.com/v1/messages",
        "pricing": {"input": 1.00, "output": 5.00},  # per 1M tokens
        "default": False
    },
    "claude-sonnet": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "display_name": "Claude 4 Sonnet",
        "description": "Balanced performance and capability",
        "api_url": "https://api.anthropic.com/v1/messages",
        "pricing": {"input": 3.00, "output": 15.00},
        "default": True
    },
    "claude-opus-45": {
        "provider": "anthropic",
        "model": "claude-opus-4-5-20251101",
        "display_name": "Claude Opus 4.5",
        "description": "Previous flagship model",
        "api_url": "https://api.anthropic.com/v1/messages",
        "pricing": {"input": 15.00, "output": 75.00},
        "default": False
    },
    "claude-opus": {
        "provider": "anthropic",
        "model": "claude-opus-4-6-20250205",
        "display_name": "Claude Opus 4.6",
        "description": "Most capable, 1M context, best for complex analysis",
        "api_url": "https://api.anthropic.com/v1/messages",
        "pricing": {"input": 5.00, "output": 25.00},
        "default": False
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "display_name": "GPT-4o Mini",
        "description": "Fast and cost-effective",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "pricing": {"input": 0.15, "output": 0.60},
        "default": False
    },
    "gpt-4o": {
        "provider": "openai",
        "model": "gpt-4o",
        "display_name": "GPT-4o",
        "description": "Powerful multimodal model",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "pricing": {"input": 2.50, "output": 10.00},
        "default": False
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
        # Use the council key or fall back to regular key
        return os.getenv("OPENAI_COUNCIL_KEY") or os.getenv("OPENAI_API_KEY")
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
            "pricing": config["pricing"]
        })
    return models


def get_default_model() -> str:
    """Get the default model ID."""
    for model_id, config in CHAT_MODELS.items():
        if config.get("default"):
            return model_id
    return "claude-sonnet"
