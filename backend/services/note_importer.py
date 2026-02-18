"""
Note Importer Service
=====================
Converts local markdown files into Scholia's internal format.

Takes a raw .md file and produces:
- [TITLE] line at the top
- [SECTION] markers for each heading
- Body text passed through unchanged (already markdown)

Output is saved as `{folder}--note--extracted.txt` in data/sources/notes/.
"""

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from unidecode import unidecode
import logging

logger = logging.getLogger(__name__)


@dataclass
class NoteImportResult:
    """Result of importing a markdown note."""
    title: str
    content_path: str
    sections: list[dict]
    word_count: int


def _sanitize_folder_name(title: str) -> str:
    """Convert a title to a safe folder name."""
    # Transliterate unicode to ASCII
    clean = unidecode(title)
    # Replace non-alphanumeric with underscores
    clean = re.sub(r'[^a-zA-Z0-9]+', '_', clean)
    # Collapse multiple underscores, strip leading/trailing
    clean = re.sub(r'_+', '_', clean).strip('_')
    # Truncate to reasonable length
    return clean[:80]


def _extract_title(content: str, filename: str) -> str:
    """
    Extract title from markdown content.

    Priority:
    1. First # heading (h1)
    2. First ## heading (h2) if no h1
    3. Filename without extension
    """
    # Look for first heading (any level)
    match = re.search(r'^(#{1,6})\s+(.+?)$', content, re.MULTILINE)
    if match:
        return match.group(2).strip()

    # Fallback to filename
    return Path(filename).stem.replace('-', ' ').replace('_', ' ').title()


def _convert_headings_to_sections(content: str) -> str:
    """
    Convert markdown headings to [SECTION] markers.

    `# Heading` → `[SECTION] # Heading`
    `## Subheading` → `[SECTION] ## Subheading`

    Body text and other markdown formatting pass through unchanged.
    """
    def replace_heading(match):
        hashes = match.group(1)
        text = match.group(2).strip()
        if not text:
            return ''
        # Strip inline formatting from headings (same as web_clipper.convert_hn)
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # bold
        text = re.sub(r'\*([^*]+)\*', r'\1', text)     # italic
        text = re.sub(r'`([^`]+)`', r'\1', text)       # code
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # links
        return f'[SECTION] {hashes} {text}'

    return re.sub(r'^(#{1,6})\s+(.+?)$', replace_heading, content, flags=re.MULTILINE)


def import_note(
    content: str,
    filename: str,
    notes_dir: Path,
    title_override: Optional[str] = None,
) -> NoteImportResult:
    """
    Import a markdown file as a Scholia note source.

    Args:
        content: Raw markdown content
        filename: Original filename (for title fallback)
        notes_dir: Base directory for notes (data/sources/notes/)
        title_override: Optional title to use instead of extracted one

    Returns:
        NoteImportResult with title, content_path, sections, word_count
    """
    # Extract title
    title = title_override or _extract_title(content, filename)

    # Convert headings to [SECTION] markers
    converted = _convert_headings_to_sections(content)

    # Prepend [TITLE] line
    converted = f"[TITLE] {title}\n\n{converted}"

    # Create output folder
    folder_name = _sanitize_folder_name(title)
    folder = notes_dir / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    # Write extracted.txt
    output_file = folder / f"{folder_name}--note--extracted.txt"
    output_file.write_text(converted, encoding="utf-8")

    # Parse sections from converted content
    sections = _parse_note_sections(converted)

    # Count words
    word_count = len(converted.split())

    return NoteImportResult(
        title=title,
        content_path=str(output_file),
        sections=sections,
        word_count=word_count,
    )


def _parse_note_sections(content: str) -> list[dict]:
    """
    Parse [SECTION] markers from converted content.

    Same logic as sources.py:_parse_sections but kept local to avoid
    circular imports.
    """
    sections = []
    pattern = r"\[SECTION\]\s*(#{1,6})\s*(.+?)(?=\n)"

    for match in re.finditer(pattern, content):
        level = len(match.group(1))
        title = match.group(2).strip()
        start_offset = match.start()
        sections.append({
            "title": title,
            "level": level,
            "start_offset": start_offset,
            "end_offset": start_offset,  # Updated below
        })

    # Calculate end offsets
    for i, section in enumerate(sections):
        if i + 1 < len(sections):
            section["end_offset"] = sections[i + 1]["start_offset"]
        else:
            section["end_offset"] = len(content)

    # If no sections, create a single "Full Document" section
    if not sections:
        sections.append({
            "title": "Full Document",
            "level": 1,
            "start_offset": 0,
            "end_offset": len(content),
        })

    return sections


def preview_note(content: str, filename: str) -> dict:
    """
    Quick preview of a markdown file without importing.

    Returns title and word count for the import modal.
    """
    title = _extract_title(content, filename)
    word_count = len(content.split())
    return {
        "title": title,
        "word_count": word_count,
    }
