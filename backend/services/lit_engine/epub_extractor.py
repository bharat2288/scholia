"""
EPUB Extractor
==============
Extract text and structure from EPUB files.

Uses ebooklib for EPUB parsing and BeautifulSoup for HTML.
"""

from pathlib import Path
from typing import List, Dict
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup


async def extract_epub(
    file_path: Path,
    output_dir: Path
) -> dict:
    """
    Extract text from an EPUB file.

    Args:
        file_path: Path to the EPUB file
        output_dir: Directory to save extracted text

    Returns:
        dict with:
            - success: bool
            - text_path: Path to extracted text file
            - sections: List of chapters/sections with offsets
            - metadata: Title, author, etc.
    """

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Output file path
    text_path = output_dir / f"{file_path.stem}.txt"

    try:
        # Open EPUB
        book = epub.read_epub(str(file_path))

        # Extract metadata
        metadata = {
            "title": _get_metadata(book, "title"),
            "author": _get_metadata(book, "creator"),
            "publisher": _get_metadata(book, "publisher"),
            "language": _get_metadata(book, "language"),
        }

        # Extract chapters
        full_text = []
        sections = []
        current_offset = 0

        for item in book.get_items():
            # Only process document items (chapters)
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                # Parse HTML content
                soup = BeautifulSoup(item.get_content(), "html.parser")

                # Extract chapter title (usually in h1 or h2)
                title = None
                for heading in soup.find_all(["h1", "h2", "h3"]):
                    if heading.get_text().strip():
                        title = heading.get_text().strip()
                        break

                if not title:
                    title = item.get_name()

                # Add section marker
                section_marker = f"\n[SECTION] {title}\n"
                full_text.append(section_marker)

                # Track section position
                section_start = current_offset + len(section_marker)

                # Extract text content
                chapter_text = soup.get_text(separator="\n")
                chapter_text = _clean_text(chapter_text)
                full_text.append(chapter_text)

                # Record section
                sections.append({
                    "title": title,
                    "level": 1,
                    "start_offset": section_start,
                    "end_offset": section_start + len(chapter_text),
                    "item_name": item.get_name()
                })

                current_offset = section_start + len(chapter_text)

        # Combine all text
        combined_text = "\n".join(full_text)

        # Save to file
        text_path.write_text(combined_text, encoding="utf-8")

        return {
            "success": True,
            "text_path": str(text_path),
            "sections": sections,
            "metadata": metadata,
            "chapter_count": len(sections)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "text_path": None,
            "sections": [],
            "metadata": {}
        }


def _get_metadata(book: epub.EpubBook, field: str) -> str:
    """Extract metadata field from EPUB."""
    try:
        values = book.get_metadata("DC", field)
        if values:
            return values[0][0]
    except Exception:
        pass
    return None


def _clean_text(text: str) -> str:
    """Clean extracted text."""
    # Remove excessive whitespace
    lines = text.split("\n")
    cleaned = []
    prev_empty = False

    for line in lines:
        line = line.strip()
        if not line:
            if not prev_empty:
                cleaned.append("")
                prev_empty = True
        else:
            cleaned.append(line)
            prev_empty = False

    return "\n".join(cleaned)
