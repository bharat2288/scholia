"""
Council Models
==============
Pydantic models for the LLM Council API.

Handles:
- Presets (analysis prompt templates)
- Conversations (chat history per source)
- Messages (individual queries and responses)
- Query requests/responses
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ============================================================
# Enums
# ============================================================

class QueryMode(str, Enum):
    """Query mode - single model or council deliberation."""
    SINGLE = "single"
    COUNCIL = "council"


class ContextType(str, Enum):
    """What context was sent with the query."""
    SELECTION = "selection"
    SECTION = "section"
    FULL = "full"


class MessageRole(str, Enum):
    """Message role in conversation."""
    USER = "user"
    ASSISTANT = "assistant"


# ============================================================
# Presets
# ============================================================

class PresetBase(BaseModel):
    """Base fields for presets."""
    name: str = Field(..., min_length=1, max_length=100, description="Display name")
    description: Optional[str] = Field(None, max_length=500, description="Brief description")
    prompt: str = Field(..., min_length=10, description="Prompt template with {context}, {source_title}, etc.")
    model: str = Field("default", description="Model preference: 'default' or specific provider")
    max_tokens: int = Field(8192, ge=100, le=32000, description="Maximum response tokens")


class PresetCreate(PresetBase):
    """Fields for creating a new preset."""
    pass


class PresetUpdate(BaseModel):
    """Fields that can be updated."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    prompt: Optional[str] = Field(None, min_length=10)
    model: Optional[str] = None
    max_tokens: Optional[int] = Field(None, ge=100, le=32000)
    show_as_quick_action: Optional[bool] = Field(None, description="Show in quick action bar")
    source_types: Optional[List[str]] = Field(None, description="Applicable source types")
    prompt_full_doc: Optional[str] = Field(None, description="Alternative prompt for full-document context")


class Preset(PresetBase):
    """Full preset model returned from API."""
    id: str
    is_system: bool = Field(False, description="System presets can't be edited, only duplicated")
    sort_order: int = Field(0, description="Display order")
    show_as_quick_action: bool = Field(False, description="Show in quick action bar")
    source_types: Optional[List[str]] = Field(None, description="Applicable source types, null = all")
    prompt_full_doc: Optional[str] = Field(None, description="Alternative prompt for full-document context")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# Usage and Cost
# ============================================================

class UsageItem(BaseModel):
    """Token usage for a single model call."""
    provider: str
    role: str = Field("theorist", description="'theorist' or 'chairman'")
    input_tokens: int
    output_tokens: int
    cost_usd: float


class UsageTotal(BaseModel):
    """Aggregated usage across all calls."""
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float


class Usage(BaseModel):
    """Full usage breakdown."""
    breakdown: List[UsageItem] = []
    totals: UsageTotal


# ============================================================
# Query Request/Response
# ============================================================

class QueryRequest(BaseModel):
    """Request body for council query."""
    context: str = Field(..., min_length=1, description="Text context (selection, section, or full)")
    query: str = Field(..., min_length=1, description="The analysis prompt or question")
    mode: QueryMode = Field(QueryMode.SINGLE, description="Single model or council")
    model: str = Field("anthropic", description="Provider for single mode: anthropic, openai, openrouter")
    context_type: ContextType = Field(ContextType.SELECTION, description="What type of context")
    context_offsets: Optional[Dict[str, int]] = Field(None, description="Character offsets if selection")
    source_id: Optional[str] = Field(None, description="Source being analyzed")
    conversation_id: Optional[str] = Field(None, description="Existing conversation to continue")
    preset_id: Optional[str] = Field(None, description="Preset used for this query")


class Perspective(BaseModel):
    """Single model's response in council mode."""
    provider: str
    model: str
    role: str
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


class QueryResponse(BaseModel):
    """Response from council query."""
    query: str
    context: Optional[str] = None
    mode: QueryMode
    model: Optional[str] = None  # For single mode
    content: Optional[str] = None  # For single mode
    synthesis: Optional[str] = None  # For council mode
    perspectives: Optional[List[Perspective]] = None  # For council mode
    success: bool
    error: Optional[str] = None
    failed_providers: Optional[List[str]] = None
    timestamp: datetime
    usage: Optional[Usage] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None


# ============================================================
# Conversations
# ============================================================

class ConversationCreate(BaseModel):
    """Fields for creating a conversation."""
    source_id: str = Field(..., description="Source this conversation is about")
    title: Optional[str] = Field(None, description="Optional conversation title")


class Conversation(BaseModel):
    """Conversation model."""
    id: str
    source_id: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class ConversationWithMessages(Conversation):
    """Conversation with its messages."""
    messages: List["Message"] = []


# ============================================================
# Messages
# ============================================================

class MessageCreate(BaseModel):
    """Fields for creating a message."""
    conversation_id: str
    role: MessageRole
    content: str
    mode: Optional[QueryMode] = None
    model: Optional[str] = None
    preset_id: Optional[str] = None
    context_type: Optional[ContextType] = None
    context_offsets: Optional[Dict[str, int]] = None
    perspectives: Optional[List[Dict[str, Any]]] = None
    usage: Optional[Dict[str, Any]] = None


class Message(BaseModel):
    """Message model."""
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    mode: Optional[QueryMode] = None
    model: Optional[str] = None
    preset_id: Optional[str] = None
    context_type: Optional[ContextType] = None
    context_offsets: Optional[Dict[str, int]] = None
    perspectives: Optional[List[Dict[str, Any]]] = None
    usage: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# Model Info
# ============================================================

class ModelInfo(BaseModel):
    """Information about an available model."""
    id: str = Field(..., description="Provider ID: anthropic, openai, openrouter")
    name: str = Field(..., description="Display name: Claude Opus, GPT-5, Gemini 3 Pro")
    model: str = Field(..., description="Model identifier")
    available: bool = Field(..., description="Whether API key is configured")
    role: str = Field(..., description="Role in council: primary, secondary, tertiary")
    chairman: bool = Field(False, description="Whether this model is the chairman")


# ============================================================
# SSE Events
# ============================================================

class SSEEvent(BaseModel):
    """Server-sent event for streaming."""
    event: str = Field(..., description="Event type: start, model_start, model_complete, synthesis_start, synthesis_complete, complete")
    data: Dict[str, Any] = Field(default_factory=dict)


# Update forward references
ConversationWithMessages.model_rebuild()
