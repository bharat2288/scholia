"""
AI Metadata Suggestion Service
==============================
Uses OpenAI to extract bibliographic metadata from source content.

Features:
- Source-type-aware extraction (documents, web, threads, media)
- Smart content sampling for long documents
- Extracts title, author, year, keywords, and other metadata
- Returns confidence scores for each field
- High confidence threshold before suggesting values

Content Sampling Strategies:
- Documents (books/papers): Sample beginning, abstract, TOC, introduction, end
- Tweets/Threads: Read entire content (usually short)
- Web articles: Read more content (up to 15k chars)
- Videos: Sample title, description, transcript excerpts
"""

import os
import json
import re
from typing import Optional, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
import httpx
import logging

logger = logging.getLogger(__name__)

# Load environment variables
local_env = Path(__file__).parent.parent / ".env"
dev_env = Path(r"C:\Users\bhara\dev\.env")

if local_env.exists():
    load_dotenv(local_env, override=True)
elif dev_env.exists():
    load_dotenv(dev_env, override=True)

# OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_COUNCIL_KEY")
OPENAI_MODEL = "gpt-4o-mini"  # Cheap and fast
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


@dataclass
class MetadataSuggestion:
    """A single metadata field suggestion with confidence."""
    field: str
    value: str
    confidence: float  # 0.0 to 1.0
    source: str  # 'extracted' or 'inferred'


@dataclass
class MetadataSuggestions:
    """All metadata suggestions for a source."""
    source_id: str
    suggestions: List[MetadataSuggestion]
    doi_found: Optional[str] = None
    isbn_found: Optional[str] = None
    raw_response: Optional[str] = None


# =============================================================================
# Content Sampling Strategies
# =============================================================================

def sample_document_content(content: str) -> str:
    """
    Smart sampling for documents (books, papers, chapters).

    Strategy:
    - First ~2000 chars: title page, copyright, beginning
    - Search for Abstract section (~1500 chars)
    - Search for Table of Contents or chapter headings (~1500 chars)
    - Search for Introduction section (~2000 chars)
    - Last ~1000 chars: often has references/bibliography revealing topics

    This gives us ~8000 chars of strategically selected content.
    """
    samples = []

    # 1. Beginning (title page, copyright, early content)
    samples.append("=== BEGINNING OF DOCUMENT ===")
    samples.append(content[:2000])

    # 2. Look for Abstract
    abstract_match = re.search(
        r'(?:^|\n)\s*(?:ABSTRACT|Abstract)\s*\n(.{100,1500}?)(?=\n\s*(?:[A-Z][A-Z\s]+|Introduction|INTRODUCTION|\d+\.)|\Z)',
        content,
        re.DOTALL
    )
    if abstract_match:
        samples.append("\n=== ABSTRACT ===")
        samples.append(abstract_match.group(1).strip()[:1500])

    # 3. Look for Keywords in the text (often after abstract)
    keywords_match = re.search(
        r'(?:Keywords?|KEY\s*WORDS?|Index Terms?)[:\s]*([^\n]{10,300})',
        content,
        re.IGNORECASE
    )
    if keywords_match:
        samples.append("\n=== KEYWORDS FOUND IN DOCUMENT ===")
        samples.append(keywords_match.group(1).strip())

    # 4. Look for Table of Contents or chapter structure
    toc_match = re.search(
        r'(?:TABLE OF CONTENTS|CONTENTS|Table of Contents)\s*\n(.{100,1500}?)(?=\n\s*(?:Chapter|CHAPTER|\d+\.\s+[A-Z])|\Z)',
        content,
        re.DOTALL
    )
    if toc_match:
        samples.append("\n=== TABLE OF CONTENTS ===")
        samples.append(toc_match.group(1).strip()[:1500])
    else:
        # Try to find chapter headings
        chapters = re.findall(r'^(?:Chapter\s+\d+[:\s]*|CHAPTER\s+\d+[:\s]*|\d+\.\s+)([A-Z][^\n]{5,100})', content, re.MULTILINE)
        if chapters:
            samples.append("\n=== CHAPTER/SECTION HEADINGS ===")
            samples.append("\n".join(chapters[:15]))

    # 5. Look for Introduction
    intro_match = re.search(
        r'(?:^|\n)\s*(?:1\.?\s*)?(?:INTRODUCTION|Introduction)\s*\n(.{100,2000}?)(?=\n\s*(?:\d+\.|[A-Z][A-Z\s]+\n)|\Z)',
        content,
        re.DOTALL
    )
    if intro_match:
        samples.append("\n=== INTRODUCTION ===")
        samples.append(intro_match.group(1).strip()[:2000])

    # 6. End of document (often has references that reveal topics)
    samples.append("\n=== END OF DOCUMENT ===")
    samples.append(content[-1500:])

    return "\n".join(samples)


def sample_thread_content(content: str) -> str:
    """
    For tweets/threads: read entire content (usually short).
    Also extract any hashtags explicitly.
    """
    # Extract hashtags
    hashtags = re.findall(r'#(\w+)', content)

    result = content  # Full content for threads

    if hashtags:
        result += "\n\n=== HASHTAGS FOUND ===\n"
        result += ", ".join(set(hashtags))

    return result


def sample_web_content(content: str) -> str:
    """
    For web articles: read more content (up to 15k chars).
    Web articles are usually focused and not too long.
    """
    max_chars = 15000

    if len(content) <= max_chars:
        return content

    # Take beginning and end
    return content[:12000] + "\n\n[... content truncated ...]\n\n" + content[-3000:]


def sample_video_content(content: str) -> str:
    """
    For video transcripts: sample from different parts.

    Strategy:
    - Beginning (~3000 chars): often has intro explaining the topic
    - Middle section (~2000 chars): main content
    - End (~2000 chars): often has summary/conclusion
    """
    if len(content) <= 8000:
        return content

    samples = []

    # Beginning
    samples.append("=== BEGINNING OF TRANSCRIPT ===")
    samples.append(content[:3000])

    # Middle
    mid_point = len(content) // 2
    samples.append("\n=== MIDDLE OF TRANSCRIPT ===")
    samples.append(content[mid_point-1000:mid_point+1000])

    # End
    samples.append("\n=== END OF TRANSCRIPT ===")
    samples.append(content[-2000:])

    return "\n".join(samples)


def get_sampled_content(content: str, source_type: str) -> str:
    """Get appropriately sampled content based on source type."""
    if source_type in ('thread', 'tweet'):
        return sample_thread_content(content)
    elif source_type == 'web':
        return sample_web_content(content)
    elif source_type == 'media':
        return sample_video_content(content)
    else:  # document
        return sample_document_content(content)


# =============================================================================
# Source-Type-Specific Prompts
# =============================================================================

DOCUMENT_PROMPT = """You are a bibliographic metadata extraction assistant. Analyze the following document excerpts and extract metadata.

IMPORTANT RULES:
1. Only extract values you are confident about (>80% confidence)
2. Authors must be in "Familyname, Firstname M." format (e.g., "Smith, John M.; Doe, Jane A.")
   - Include middle name initial with period if available
   - Multiple authors separated by semicolons
3. Editors should be separate from authors, also in "Familyname, Firstname M." format
5. Year must be a 4-digit number
6. If you find a DOI or ISBN, include it - these can be verified
7. For keywords: extract main topics, themes, and subject areas. Look for:
   - Explicit "Keywords:" sections
   - Topics from table of contents/chapter headings
   - Main themes from abstract/introduction
   - Subject areas the document covers
8. For each field, rate your confidence from 0.0 to 1.0
9. If unsure, omit the field rather than guess

DOCUMENT EXCERPTS:
---
{content}
---

Extract the following fields if present. Respond with ONLY valid JSON, no markdown:
{{
  "title": {{"value": "...", "confidence": 0.95}},
  "author": {{"value": "Smith, John M.; Doe, Jane A.", "confidence": 0.9}},
  "year": {{"value": "2024", "confidence": 0.85}},
  "journal": {{"value": "...", "confidence": 0.8}},
  "volume": {{"value": "...", "confidence": 0.8}},
  "issue": {{"value": "...", "confidence": 0.8}},
  "pages": {{"value": "...", "confidence": 0.8}},
  "publisher": {{"value": "...", "confidence": 0.8}},
  "editors": {{"value": "Johnson, Robert K.", "confidence": 0.8}},
  "edition": {{"value": "...", "confidence": 0.8}},
  "series": {{"value": "...", "confidence": 0.8}},
  "doi": {{"value": "10.xxxx/xxxxx", "confidence": 0.95}},
  "isbn": {{"value": "978-...", "confidence": 0.95}},
  "issn": {{"value": "...", "confidence": 0.9}},
  "abstract": {{"value": "...", "confidence": 0.9}},
  "keywords": {{"value": "topic1, topic2, topic3", "confidence": 0.8}},
  "url": {{"value": "https://...", "confidence": 0.9}}
}}

IMPORTANT: For keywords, infer 3-7 main topics/themes even if not explicitly stated. Consider:
- What subject areas does this document cover?
- What would a reader search for to find this document?
- What are the main concepts discussed?

Only include fields you found or can confidently infer. Omit fields with confidence below 0.7."""


THREAD_PROMPT = """You are a social media content analyst. Analyze the following Twitter/X thread and extract relevant metadata.

IMPORTANT RULES:
1. Author: Use the display name if clear, otherwise the handle
2. Keywords: Extract the main topics, themes, and concepts discussed. Include:
   - Explicit hashtags (without the # symbol)
   - Main topics/themes of the thread
   - Key concepts or ideas discussed
   - Relevant subject areas
3. For each field, rate your confidence from 0.0 to 1.0
4. If unsure, omit the field rather than guess

THREAD CONTENT:
---
{content}
---

Extract the following fields. Respond with ONLY valid JSON, no markdown:
{{
  "title": {{"value": "Brief summary of thread topic (max 100 chars)", "confidence": 0.8}},
  "author": {{"value": "Display Name or @handle", "confidence": 0.9}},
  "keywords": {{"value": "topic1, topic2, topic3, topic4", "confidence": 0.85}}
}}

IMPORTANT: For keywords, identify 3-8 relevant topics/tags. Think about:
- What hashtags would fit this content?
- What topics does this thread discuss?
- What would someone search to find this thread?

Only include fields you can determine. Omit fields with confidence below 0.7."""


WEB_PROMPT = """You are a web content analyst. Analyze the following web article and extract relevant metadata.

IMPORTANT RULES:
1. Title: The article's actual title
2. Author: If byline is present, extract in "Familyname, Firstname M." format (e.g., "Smith, John M.")
3. Year: Publication year if visible
4. Keywords: Extract main topics and themes. Consider:
   - Article subject matter
   - Key concepts discussed
   - Categories this article would belong to
   - What someone would search to find this article
5. For each field, rate your confidence from 0.0 to 1.0

WEB ARTICLE:
---
{content}
---

Extract the following fields. Respond with ONLY valid JSON, no markdown:
{{
  "title": {{"value": "...", "confidence": 0.95}},
  "author": {{"value": "Smith, John M.", "confidence": 0.8}},
  "year": {{"value": "2024", "confidence": 0.8}},
  "sitename": {{"value": "Site Name", "confidence": 0.85}},
  "abstract": {{"value": "Brief summary of article...", "confidence": 0.8}},
  "keywords": {{"value": "topic1, topic2, topic3, topic4", "confidence": 0.85}},
  "url": {{"value": "https://...", "confidence": 0.95}}
}}

IMPORTANT: For keywords, identify 3-7 relevant topics. Think about:
- What is this article about?
- What categories would it fit in?
- What would someone search to find this?

Only include fields you can determine. Omit fields with confidence below 0.7."""


VIDEO_PROMPT = """You are a video content analyst. Analyze the following video transcript and extract relevant metadata.

IMPORTANT RULES:
1. Title: The video's title if mentioned, or create a descriptive title
2. Channel/Author: Creator name if mentioned
3. Keywords: Extract main topics and themes. Consider:
   - Main subjects discussed in the video
   - Key concepts and ideas
   - What someone would search to find this video
   - Relevant categories
4. For each field, rate your confidence from 0.0 to 1.0

VIDEO TRANSCRIPT:
---
{content}
---

Extract the following fields. Respond with ONLY valid JSON, no markdown:
{{
  "title": {{"value": "...", "confidence": 0.85}},
  "channel": {{"value": "Channel Name", "confidence": 0.8}},
  "year": {{"value": "2024", "confidence": 0.7}},
  "description": {{"value": "Brief summary of video content...", "confidence": 0.8}},
  "keywords": {{"value": "topic1, topic2, topic3, topic4, topic5", "confidence": 0.85}}
}}

IMPORTANT: For keywords, identify 4-8 relevant topics. Think about:
- What subjects does this video cover?
- What would someone search to find this video?
- What categories would this video belong to?

Only include fields you can determine. Omit fields with confidence below 0.7."""


def get_prompt_for_source_type(source_type: str) -> str:
    """Get the appropriate extraction prompt for the source type."""
    if source_type in ('thread', 'tweet'):
        return THREAD_PROMPT
    elif source_type == 'web':
        return WEB_PROMPT
    elif source_type == 'media':
        return VIDEO_PROMPT
    else:  # document (default)
        return DOCUMENT_PROMPT


def get_system_message_for_source_type(source_type: str) -> str:
    """Get the appropriate system message for the source type."""
    if source_type in ('thread', 'tweet'):
        return "You are a social media content analyst. Extract topics and metadata from Twitter/X threads. Respond only with valid JSON."
    elif source_type == 'web':
        return "You are a web content analyst. Extract metadata and topics from web articles. Respond only with valid JSON."
    elif source_type == 'media':
        return "You are a video content analyst. Extract topics and metadata from video transcripts. Respond only with valid JSON."
    else:
        return "You are a precise bibliographic metadata extractor. Respond only with valid JSON."


# =============================================================================
# Main API Functions
# =============================================================================

async def suggest_metadata(
    content: str,
    source_id: str,
    existing_metadata: Optional[Dict[str, Any]] = None,
    source_type: str = "document"
) -> MetadataSuggestions:
    """
    Use AI to suggest metadata from source content.

    Args:
        content: The extracted text content
        source_id: The source ID for tracking
        existing_metadata: Current metadata (to avoid re-suggesting same values)
        source_type: Type of source ('document', 'web', 'thread', 'tweet', 'media')

    Returns:
        MetadataSuggestions with field suggestions and confidence scores
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_COUNCIL_KEY not found in environment")

    # Sample content appropriately for source type
    sampled_content = get_sampled_content(content, source_type)

    # Get source-type-specific prompt and system message
    prompt_template = get_prompt_for_source_type(source_type)
    system_message = get_system_message_for_source_type(source_type)

    # Build the prompt
    prompt = prompt_template.format(content=sampled_content)

    # Call OpenAI API
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            OPENAI_API_URL,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,  # Slightly higher for keyword inference
                "max_tokens": 2000
            }
        )
        response.raise_for_status()
        result = response.json()

    # Parse the response
    raw_text = result["choices"][0]["message"]["content"]

    # Clean up potential markdown formatting
    raw_text = raw_text.strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    if raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
    raw_text = raw_text.strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response: {e}\nRaw: {raw_text[:500]}")
        return MetadataSuggestions(
            source_id=source_id,
            suggestions=[],
            raw_response=raw_text
        )

    # Convert to suggestions list
    suggestions = []
    doi_found = None
    isbn_found = None

    existing = existing_metadata or {}

    for field, data in parsed.items():
        if not isinstance(data, dict) or "value" not in data:
            continue

        value = data.get("value", "").strip()
        confidence = float(data.get("confidence", 0.5))

        # Skip empty values or low confidence
        if not value or confidence < 0.7:
            continue

        # Skip if existing value is the same
        existing_value = existing.get(field, "")
        if existing_value and str(existing_value).strip() == value:
            continue

        # Track DOI/ISBN for potential lookup
        if field == "doi" and confidence >= 0.9:
            doi_found = value
        if field == "isbn" and confidence >= 0.9:
            isbn_found = value

        suggestions.append(MetadataSuggestion(
            field=field,
            value=value,
            confidence=confidence,
            source="extracted"
        ))

    return MetadataSuggestions(
        source_id=source_id,
        suggestions=suggestions,
        doi_found=doi_found,
        isbn_found=isbn_found,
        raw_response=raw_text
    )


async def suggest_metadata_batch(
    sources: List[Dict[str, Any]],
    get_content_func
) -> List[MetadataSuggestions]:
    """
    Process multiple sources in batch.

    Args:
        sources: List of source dicts with 'id', 'content_path', and 'source_type'
        get_content_func: Async function to read content given a path

    Returns:
        List of MetadataSuggestions for each source
    """
    results = []

    for source in sources:
        source_id = str(source["id"])
        content_path = source.get("content_path")
        source_type = source.get("source_type", "document")

        if not content_path:
            results.append(MetadataSuggestions(source_id=source_id, suggestions=[]))
            continue

        try:
            content = await get_content_func(content_path)
            if not content:
                results.append(MetadataSuggestions(source_id=source_id, suggestions=[]))
                continue

            # Build existing metadata dict
            existing = {
                "title": source.get("title"),
                "author": source.get("author"),
                "year": source.get("year"),
                "journal": source.get("journal"),
                "doi": source.get("doi"),
                "isbn": source.get("isbn"),
            }

            suggestion = await suggest_metadata(
                content,
                source_id,
                existing,
                source_type=source_type
            )
            results.append(suggestion)

        except Exception as e:
            logger.error(f"Failed to process source {source_id}: {e}")
            results.append(MetadataSuggestions(source_id=source_id, suggestions=[]))

    return results


def format_suggestions_for_review(suggestions: MetadataSuggestions) -> Dict[str, Any]:
    """
    Format suggestions for frontend review UI.
    """
    return {
        "source_id": suggestions.source_id,
        "suggestions": [
            {
                "field": s.field,
                "value": s.value,
                "confidence": s.confidence,
                "confidence_label": (
                    "high" if s.confidence >= 0.9 else
                    "medium" if s.confidence >= 0.8 else
                    "low"
                ),
                "source": s.source
            }
            for s in suggestions.suggestions
        ],
        "doi_found": suggestions.doi_found,
        "isbn_found": suggestions.isbn_found,
        "has_suggestions": len(suggestions.suggestions) > 0
    }
