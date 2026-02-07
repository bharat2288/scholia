"""
Scholia Models
==============
Pydantic models for API request/response validation.
"""

from .document import Document, DocumentCreate, DocumentUpdate
from .gluon import Gluon, GluonCreate, GluonUpdate, GluonType, GluonWithLinks, Link, LinkCreate
# Backward compatibility aliases
from .gluon import Rem, RemCreate, RemUpdate, RemType
from .highlight import Highlight, HighlightCreate, HighlightColor
from .council import (
    Preset, PresetCreate, PresetUpdate,
    Conversation, ConversationCreate, ConversationWithMessages,
    Message, MessageCreate,
    QueryRequest, QueryResponse, QueryMode, ContextType, MessageRole,
    ModelInfo, Usage, UsageItem, UsageTotal, Perspective, SSEEvent
)

__all__ = [
    "Document", "DocumentCreate", "DocumentUpdate",
    "Gluon", "GluonCreate", "GluonUpdate", "GluonType", "GluonWithLinks", "Link", "LinkCreate",
    "Rem", "RemCreate", "RemUpdate", "RemType",  # Deprecated aliases
    "Highlight", "HighlightCreate", "HighlightColor",
    # Council
    "Preset", "PresetCreate", "PresetUpdate",
    "Conversation", "ConversationCreate", "ConversationWithMessages",
    "Message", "MessageCreate",
    "QueryRequest", "QueryResponse", "QueryMode", "ContextType", "MessageRole",
    "ModelInfo", "Usage", "UsageItem", "UsageTotal", "Perspective", "SSEEvent",
]
