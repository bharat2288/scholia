"""
Highlight Models
================
Specialized models for highlights (a type of Rem).

Highlights are stored using character offsets for reliability.
This avoids the text-matching crashes we had before.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class HighlightColor(str, Enum):
    """Available highlight colors with semantic meanings."""
    YELLOW = "yellow"   # General / important
    BLUE = "blue"       # Definitions / concepts
    GREEN = "green"     # Evidence / data
    PINK = "pink"       # Questions / unclear


# Color display values for frontend
HIGHLIGHT_COLORS = {
    HighlightColor.YELLOW: {
        "name": "Yellow",
        "bg": "rgba(255, 235, 59, 0.3)",
        "border": "rgb(255, 235, 59)",
        "meaning": "General / Important"
    },
    HighlightColor.BLUE: {
        "name": "Blue",
        "bg": "rgba(66, 165, 245, 0.3)",
        "border": "rgb(66, 165, 245)",
        "meaning": "Definitions / Concepts"
    },
    HighlightColor.GREEN: {
        "name": "Green",
        "bg": "rgba(102, 187, 106, 0.3)",
        "border": "rgb(102, 187, 106)",
        "meaning": "Evidence / Data"
    },
    HighlightColor.PINK: {
        "name": "Pink",
        "bg": "rgba(236, 64, 122, 0.3)",
        "border": "rgb(236, 64, 122)",
        "meaning": "Questions / Unclear"
    },
}


class HighlightCreate(BaseModel):
    """Fields for creating a new highlight."""
    source_id: str = Field(..., description="Source containing the highlight")
    section_id: Optional[str] = Field(None, description="Section containing the highlight")
    start_offset: int = Field(..., ge=0, description="Start character position in source")
    end_offset: int = Field(..., ge=0, description="End character position in source")
    color: HighlightColor = Field(HighlightColor.YELLOW, description="Highlight color")
    content: Optional[str] = Field(None, description="The highlighted text (for display)")


class HighlightUpdate(BaseModel):
    """Fields that can be updated on a highlight."""
    color: Optional[HighlightColor] = None


class Highlight(BaseModel):
    """Full highlight model returned from API."""
    id: str
    source_id: str
    section_id: Optional[str]
    start_offset: int
    end_offset: int
    color: HighlightColor
    content: Optional[str]  # The highlighted text
    created_at: datetime
    updated_at: datetime

    # Source info (from join)
    source_title: Optional[str] = None

    # Related data (populated on request)
    notes: list = Field(default_factory=list)  # Attached notes

    class Config:
        from_attributes = True


class HighlightWithContext(Highlight):
    """Highlight with surrounding context for display."""
    context_before: str = Field("", description="Text before highlight")
    context_after: str = Field("", description="Text after highlight")
    section_title: Optional[str] = Field(None, description="Section name for breadcrumb")
