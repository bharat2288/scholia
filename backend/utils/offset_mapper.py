"""
Offset Mapper
=============
Utilities for working with character offsets in documents.

Used for:
- Mapping highlights to text positions
- Finding which section contains an offset
- Converting between page numbers and offsets
"""

from typing import List, Dict, Optional, Tuple


def find_section_at_offset(
    offset: int,
    sections: List[Dict]
) -> Optional[Dict]:
    """
    Find which section contains the given offset.

    Args:
        offset: Character position in document
        sections: List of sections with start_offset and end_offset

    Returns:
        Section dict if found, None otherwise
    """
    for section in sections:
        if section["start_offset"] <= offset < section["end_offset"]:
            return section
    return None


def find_page_at_offset(
    offset: int,
    text: str
) -> int:
    """
    Find which page contains the given offset.
    Looks for [PAGE n] markers in the text.

    Args:
        offset: Character position
        text: Full document text with [PAGE n] markers

    Returns:
        Page number (1-indexed)
    """
    import re

    # Find all page markers
    page_pattern = r"\[PAGE (\d+)\]"
    matches = list(re.finditer(page_pattern, text))

    if not matches:
        return 1  # No markers, assume single page

    # Find the page marker that precedes our offset
    current_page = 1
    for match in matches:
        if match.start() <= offset:
            current_page = int(match.group(1))
        else:
            break

    return current_page


def get_context_around_offset(
    offset: int,
    text: str,
    context_chars: int = 100
) -> Tuple[str, str]:
    """
    Get text before and after an offset for context.

    Args:
        offset: Character position
        text: Full document text
        context_chars: How many characters of context to include

    Returns:
        (text_before, text_after)
    """
    start = max(0, offset - context_chars)
    end = min(len(text), offset + context_chars)

    before = text[start:offset]
    after = text[offset:end]

    # Clean up to word boundaries
    if start > 0:
        # Find first space in "before" and trim
        space_idx = before.find(" ")
        if space_idx > 0:
            before = before[space_idx + 1:]

    if end < len(text):
        # Find last space in "after" and trim
        space_idx = after.rfind(" ")
        if space_idx > 0:
            after = after[:space_idx]

    return before, after


def validate_offset_range(
    start: int,
    end: int,
    text_length: int
) -> Tuple[int, int]:
    """
    Validate and clamp offset range to valid bounds.

    Args:
        start: Start offset
        end: End offset
        text_length: Total length of text

    Returns:
        (start, end) clamped to valid range

    Raises:
        ValueError if start > end
    """
    if start > end:
        raise ValueError(f"Start offset ({start}) cannot be greater than end ({end})")

    start = max(0, start)
    end = min(text_length, end)

    return start, end


def merge_overlapping_ranges(
    ranges: List[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """
    Merge overlapping offset ranges.
    Useful for combining adjacent/overlapping highlights.

    Args:
        ranges: List of (start, end) tuples

    Returns:
        List of merged (start, end) tuples
    """
    if not ranges:
        return []

    # Sort by start position
    sorted_ranges = sorted(ranges, key=lambda x: x[0])

    merged = [sorted_ranges[0]]

    for start, end in sorted_ranges[1:]:
        prev_start, prev_end = merged[-1]

        # Check if overlapping or adjacent
        if start <= prev_end:
            # Merge by extending previous range
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            # No overlap, add new range
            merged.append((start, end))

    return merged
