"""
Document Models
===============
Pydantic models for documents (books, articles, chapters).
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class DocType(str, Enum):
    """Type of document."""
    BOOK = "book"
    ARTICLE = "article"
    CHAPTER = "chapter"


class SourceType(str, Enum):
    """Original file format."""
    PDF = "pdf"
    EPUB = "epub"


class DocumentBase(BaseModel):
    """Base fields shared by all document operations."""
    title: str = Field(..., min_length=1, description="Document title")
    author: Optional[str] = Field(None, description="Author name(s)")
    year: Optional[int] = Field(None, ge=1000, le=2100, description="Publication year")
    publisher: Optional[str] = Field(None, description="Publisher name")
    doc_type: Optional[DocType] = Field(None, description="Type: book, article, chapter")

    # Bibliographic metadata (BIBCITE fields)
    journal: Optional[str] = Field(None, description="Journal or conference name")
    volume: Optional[str] = Field(None, description="Volume number")
    issue: Optional[str] = Field(None, description="Issue number")
    pages: Optional[str] = Field(None, description="Page range (e.g., '123-145')")
    doi: Optional[str] = Field(None, description="Digital Object Identifier")
    isbn: Optional[str] = Field(None, description="ISBN for books")
    issn: Optional[str] = Field(None, description="ISSN for journals")
    abstract: Optional[str] = Field(None, description="Document abstract")
    keywords: Optional[str] = Field(None, description="Comma-separated keywords")
    url: Optional[str] = Field(None, description="Source URL")
    editors: Optional[str] = Field(None, description="Editors for edited volumes")
    edition: Optional[str] = Field(None, description="Edition (e.g., '2nd')")
    series: Optional[str] = Field(None, description="Book series name")


class DocumentCreate(DocumentBase):
    """Fields for creating a new document (via import)."""
    source_type: SourceType = Field(..., description="Original format: pdf or epub")
    original_path: str = Field(..., description="Path to original file")


class DocumentUpdate(BaseModel):
    """Fields that can be updated after import."""
    title: Optional[str] = Field(None, min_length=1)
    author: Optional[str] = None
    year: Optional[int] = Field(None, ge=1000, le=2100)
    publisher: Optional[str] = None
    doc_type: Optional[DocType] = None

    # Bibliographic metadata (BIBCITE fields)
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    isbn: Optional[str] = None
    issn: Optional[str] = None
    abstract: Optional[str] = None
    keywords: Optional[str] = None
    url: Optional[str] = None
    editors: Optional[str] = None
    edition: Optional[str] = None
    series: Optional[str] = None


class ReadingPosition(BaseModel):
    """Current reading position in a document."""
    section_id: Optional[str] = Field(None, description="Current section ID")
    scroll_offset: float = Field(0, ge=0, description="Scroll position within section")


class Document(DocumentBase):
    """Full document model returned from API."""
    id: str = Field(..., description="Unique document ID")
    source_type: Optional[SourceType] = None
    original_path: Optional[str] = None
    extracted_path: Optional[str] = Field(None, description="Path to extracted text")
    reading_position: Optional[ReadingPosition] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # Allows creating from ORM/dict


class Section(BaseModel):
    """A section (chapter/heading) within a document."""
    id: str
    document_id: str
    title: Optional[str]
    level: int = Field(..., ge=1, le=6, description="Heading level 1-6")
    start_offset: int = Field(..., ge=0, description="Start character position")
    end_offset: int = Field(..., ge=0, description="End character position")
    order_index: int = Field(..., ge=0, description="Order within document")
    parent_id: Optional[str] = Field(None, description="Parent section ID for nesting")

    class Config:
        from_attributes = True
