"""
Chat Service
============
Simple single-model chat for document analysis.
"""

from .service import ChatService
from .config import CHAT_MODELS, get_chat_models, get_api_key

__all__ = ["ChatService", "CHAT_MODELS", "get_chat_models", "get_api_key"]
