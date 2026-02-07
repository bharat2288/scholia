"""
Gluon Models
============
Pydantic models for Gluons - the universal linkable objects.

Named after the particle that binds quarks - knowledge units that bind together.

A Gluon can be:
- A highlight (text selection with color)
- A note (text attached to a highlight or standalone)
- A tag (label that can be applied to other gluons)

All Gluons can be linked via [[references]] or ##tags.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class GluonType(str, Enum):
    """Type of Gluon."""
    HIGHLIGHT = "highlight"
    NOTE = "note"
    TAG = "tag"


class GluonBase(BaseModel):
    """Base fields shared by all gluon operations."""
    type: GluonType
    content: Optional[str] = Field(None, description="Text content of the gluon")
    document_id: Optional[str] = Field(None, description="Associated document (if any)")
    section_id: Optional[str] = Field(None, description="Associated section (if any)")


class GluonCreate(GluonBase):
    """Fields for creating a new gluon."""
    # For highlights
    start_offset: Optional[int] = Field(None, ge=0, description="Start character position")
    end_offset: Optional[int] = Field(None, ge=0, description="End character position")
    color: Optional[str] = Field(None, description="Highlight color")

    # For notes attached to other gluons
    parent_gluon_id: Optional[str] = Field(None, description="Parent gluon (for attached notes)")


class GluonUpdate(BaseModel):
    """Fields that can be updated."""
    content: Optional[str] = None
    color: Optional[str] = None  # Only for highlights


class Gluon(GluonBase):
    """Full gluon model returned from API."""
    id: str
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    color: Optional[str] = None
    parent_gluon_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GluonWithLinks(Gluon):
    """Gluon with its links expanded."""
    # Gluons this one references
    outgoing_refs: List["Gluon"] = Field(default_factory=list)
    # Gluons that reference this one
    incoming_refs: List["Gluon"] = Field(default_factory=list)
    # Tags applied to this gluon
    tags: List["Gluon"] = Field(default_factory=list)
    # Child notes (for highlights)
    notes: List["Gluon"] = Field(default_factory=list)


class Link(BaseModel):
    """A link between two gluons."""
    id: str
    source_id: str = Field(..., description="Gluon that contains the link")
    target_id: str = Field(..., description="Gluon being linked to")
    link_type: str = Field(..., description="'reference' or 'tag'")
    created_at: datetime

    class Config:
        from_attributes = True


class LinkCreate(BaseModel):
    """Fields for creating a link."""
    source_id: str
    target_id: str
    link_type: str = Field(..., pattern="^(reference|tag)$")


# Backward compatibility aliases
RemType = GluonType
RemBase = GluonBase
RemCreate = GluonCreate
RemUpdate = GluonUpdate
Rem = Gluon
RemWithLinks = GluonWithLinks
