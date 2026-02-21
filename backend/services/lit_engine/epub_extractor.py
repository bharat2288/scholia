"""
EPUB Extractor
==============
Extract text and structure from EPUB files into Scholia format.

Produces extracted.txt with:
- [TITLE] from Dublin Core metadata
- [SECTION] # Heading markers with proper hierarchy
- Markdown formatting (**bold**, *italic*, > blockquotes, lists)
- [FIGURE filename] for embedded images
- Fenced code blocks for <pre>/<code>

Uses ebooklib for EPUB parsing and BeautifulSoup for HTML conversion.
"""

import re
from pathlib import Path, PurePosixPath
from typing import Optional

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, NavigableString, Tag


def extract_epub(
    file_path: Path,
    output_dir: Path,
    figures_dir: Optional[Path] = None,
) -> dict:
    """
    Extract an EPUB file into Scholia format.

    Args:
        file_path: Path to the .epub file.
        output_dir: Directory for the extracted.txt output.
        figures_dir: Directory for extracted images. If None, uses output_dir/figures.

    Returns:
        dict with success, text_path, sections, metadata, image_count.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if figures_dir is None:
        figures_dir = output_dir / "figures"

    try:
        book = epub.read_epub(str(file_path), options={"ignore_ncx": True})

        # Extract Dublin Core metadata
        metadata = {
            "title": _get_metadata(book, "title"),
            "author": _get_metadata(book, "creator"),
            "publisher": _get_metadata(book, "publisher"),
            "language": _get_metadata(book, "language"),
            "year": _extract_year(book),
        }

        # Extract images from EPUB and build href -> filename map
        image_map = _extract_images(book, figures_dir)

        # Build full text from spine items
        parts: list[str] = []

        # Add title line
        title = metadata["title"] or file_path.stem
        parts.append(f"[TITLE] {title}\n")

        # Walk spine items in reading order
        spine_ids = [item_id for item_id, _ in book.spine]
        spine_items = []
        for item_id in spine_ids:
            item = book.get_item_with_id(item_id)
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                spine_items.append(item)

        for item in spine_items:
            html_content = item.get_content().decode("utf-8", errors="replace")
            soup = BeautifulSoup(html_content, "html.parser")
            body = soup.find("body") or soup

            # Convert HTML to Scholia-formatted text
            chapter_text = _html_to_scholia(body, item.get_name(), image_map)
            chapter_text = chapter_text.strip()

            if chapter_text:
                parts.append(chapter_text)

        # Assemble final text
        full_text = "\n\n".join(parts)

        # Collapse excessive blank lines (3+ → 2)
        full_text = re.sub(r"\n{4,}", "\n\n\n", full_text)

        # Compute section offsets from the assembled text
        sections = _parse_sections(full_text)

        # Write extracted.txt
        text_filename = f"{output_dir.name}--extracted.txt"
        text_path = output_dir / text_filename
        text_path.write_text(full_text, encoding="utf-8")

        return {
            "success": True,
            "text_path": str(text_path),
            "sections": sections,
            "metadata": metadata,
            "chapter_count": len(sections),
            "image_count": len(image_map),
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "text_path": None,
            "sections": [],
            "metadata": {},
            "chapter_count": 0,
            "image_count": 0,
        }


# =============================================================================
# Metadata helpers
# =============================================================================


def _get_metadata(book: epub.EpubBook, field: str) -> Optional[str]:
    """Extract a Dublin Core metadata field."""
    try:
        values = book.get_metadata("DC", field)
        if values:
            return values[0][0]
    except Exception:
        pass
    return None


def _extract_year(book: epub.EpubBook) -> Optional[int]:
    """Try to extract publication year from Dublin Core date field."""
    try:
        dates = book.get_metadata("DC", "date")
        if dates:
            date_str = dates[0][0]
            match = re.search(r"(\d{4})", date_str)
            if match:
                return int(match.group(1))
    except Exception:
        pass
    return None


def get_epub_metadata(file_path: Path) -> dict:
    """
    Quick metadata extraction without full text processing.
    Used by the assess-epub endpoint.
    """
    book = epub.read_epub(str(file_path), options={"ignore_ncx": True})

    metadata = {
        "title": _get_metadata(book, "title"),
        "author": _get_metadata(book, "creator"),
        "publisher": _get_metadata(book, "publisher"),
        "language": _get_metadata(book, "language"),
        "year": _extract_year(book),
    }

    # Count spine items (chapters)
    chapter_count = sum(
        1 for item_id, _ in book.spine
        if book.get_item_with_id(item_id)
        and book.get_item_with_id(item_id).get_type() == ebooklib.ITEM_DOCUMENT
    )

    # Count images
    image_count = sum(
        1 for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_IMAGE
    )

    return {
        "metadata": metadata,
        "chapter_count": chapter_count,
        "image_count": image_count,
    }


# =============================================================================
# Image extraction
# =============================================================================


def _extract_images(book: epub.EpubBook, figures_dir: Path) -> dict[str, str]:
    """
    Extract all images from the EPUB to figures_dir.

    Returns a map of EPUB-internal href -> saved filename.
    For example: "images/photo.jpg" -> "images_photo.jpg"
    """
    image_map: dict[str, str] = {}

    image_items = [
        item for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_IMAGE
    ]

    if not image_items:
        return image_map

    figures_dir.mkdir(parents=True, exist_ok=True)

    for item in image_items:
        href = item.get_name()  # e.g. "images/cover.jpg" or "OEBPS/images/fig1.png"

        # Sanitize href into a flat filename
        sanitized = _sanitize_image_name(href)
        if not sanitized:
            continue

        # Save the image
        out_path = figures_dir / sanitized
        out_path.write_bytes(item.get_content())

        # Map the href (and its variants) to the sanitized filename
        image_map[href] = sanitized

        # Also map without common prefixes (OEBPS/, OPS/, etc.)
        # so <img src="../images/fig.png"> resolving from "chapter/ch1.xhtml"
        # matches "images/fig.png" in the book items
        for prefix in ("OEBPS/", "OPS/", "content/"):
            if href.startswith(prefix):
                image_map[href[len(prefix):]] = sanitized

    return image_map


def _sanitize_image_name(href: str) -> str:
    """Turn an EPUB image href into a safe flat filename."""
    # Get just the path part (no query/fragment)
    path = PurePosixPath(href)

    # Flatten: "images/cover.jpg" -> "images_cover.jpg"
    parts = list(path.parts)
    name = "_".join(parts)

    # Remove unsafe characters
    name = re.sub(r"[^\w.\-]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")

    return name


def _resolve_image_href(img_src: str, chapter_href: str, image_map: dict[str, str]) -> Optional[str]:
    """
    Resolve an <img src="..."> relative to its chapter path,
    then look up in the image_map.

    Returns the sanitized filename or None.
    """
    if not img_src:
        return None

    # Resolve relative path against the chapter's directory
    chapter_dir = PurePosixPath(chapter_href).parent
    resolved = str((chapter_dir / img_src).as_posix())

    # Normalize ".." components
    parts = []
    for part in resolved.split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part and part != ".":
            parts.append(part)
    resolved = "/".join(parts)

    # Try direct match
    if resolved in image_map:
        return image_map[resolved]

    # Try just the filename portion
    basename = PurePosixPath(img_src).name
    for href, sanitized in image_map.items():
        if PurePosixPath(href).name == basename:
            return sanitized

    return None


# =============================================================================
# HTML → Scholia text converter
# =============================================================================

# Heading tags and their Scholia markdown levels
HEADING_TAGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


def _html_to_scholia(
    element: Tag,
    chapter_href: str,
    image_map: dict[str, str],
) -> str:
    """
    Recursively convert an HTML element tree to Scholia-formatted text.

    Handles: headings, bold, italic, blockquotes, lists, images, code blocks.
    """
    parts: list[str] = []

    for child in element.children:
        if isinstance(child, NavigableString):
            text = str(child)
            # Skip pure whitespace between block elements
            if text.strip():
                parts.append(text)
            elif parts and not parts[-1].endswith("\n"):
                parts.append(" ")
            continue

        if not isinstance(child, Tag):
            continue

        tag = child.name.lower()

        # --- Headings → [SECTION] markers ---
        if tag in HEADING_TAGS:
            heading_text = child.get_text(strip=True)
            if heading_text:
                level = HEADING_TAGS[tag]
                parts.append(f"\n\n[SECTION] {level} {heading_text}\n\n")
            continue

        # --- Images → [FIGURE filename] ---
        if tag == "img":
            src = child.get("src", "")
            filename = _resolve_image_href(src, chapter_href, image_map)
            if filename:
                parts.append(f"\n\n[FIGURE {filename}]\n\n")
            continue

        # SVG images (sometimes used inline)
        if tag == "svg":
            continue

        # --- Inline formatting ---
        if tag in ("strong", "b"):
            inner = _inline_text(child, chapter_href, image_map)
            if inner.strip():
                parts.append(f"**{inner.strip()}**")
            continue

        if tag in ("em", "i"):
            inner = _inline_text(child, chapter_href, image_map)
            if inner.strip():
                parts.append(f"*{inner.strip()}*")
            continue

        if tag in ("sup",):
            inner = child.get_text(strip=True)
            if inner:
                parts.append(f"<sup>{inner}</sup>")
            continue

        if tag in ("sub",):
            inner = child.get_text(strip=True)
            if inner:
                parts.append(f"<sub>{inner}</sub>")
            continue

        # --- Code / pre ---
        if tag == "pre":
            code_el = child.find("code")
            code_text = (code_el or child).get_text()
            lang = ""
            if code_el and code_el.get("class"):
                # Try to extract language from class like "language-python"
                for cls in code_el["class"]:
                    if cls.startswith("language-"):
                        lang = cls[9:]
                        break
            parts.append(f"\n\n```{lang}\n{code_text}\n```\n\n")
            continue

        if tag == "code":
            # Inline code (not inside <pre>)
            code_text = child.get_text()
            parts.append(f"`{code_text}`")
            continue

        # --- Blockquotes ---
        if tag == "blockquote":
            inner = _html_to_scholia(child, chapter_href, image_map).strip()
            if inner:
                # Prefix each line with >
                quoted = "\n".join(f"> {line}" for line in inner.split("\n"))
                parts.append(f"\n\n{quoted}\n\n")
            continue

        # --- Lists ---
        if tag in ("ul", "ol"):
            list_text = _convert_list(child, chapter_href, image_map, ordered=(tag == "ol"))
            if list_text:
                parts.append(f"\n\n{list_text}\n\n")
            continue

        # --- Paragraphs and divs ---
        if tag in ("p", "div"):
            inner = _inline_text(child, chapter_href, image_map).strip()
            if inner:
                parts.append(f"\n\n{inner}\n\n")
            # Also check for images inside the paragraph
            for img in child.find_all("img", recursive=True):
                src = img.get("src", "")
                filename = _resolve_image_href(src, chapter_href, image_map)
                if filename:
                    parts.append(f"\n\n[FIGURE {filename}]\n\n")
            continue

        # --- Line breaks ---
        if tag == "br":
            parts.append("\n")
            continue

        # --- Horizontal rules ---
        if tag == "hr":
            parts.append("\n\n---\n\n")
            continue

        # --- Figure element (HTML5) ---
        if tag == "figure":
            for img in child.find_all("img"):
                src = img.get("src", "")
                filename = _resolve_image_href(src, chapter_href, image_map)
                if filename:
                    parts.append(f"\n\n[FIGURE {filename}]\n\n")
            # Extract figcaption
            figcaption = child.find("figcaption")
            if figcaption:
                caption_text = figcaption.get_text(strip=True)
                if caption_text:
                    parts.append(f"\n[CAPTION] {caption_text}\n")
            continue

        # --- Tables → simple HTML passthrough ---
        if tag == "table":
            table_html = str(child)
            parts.append(f"\n\n[TABLE]\n{table_html}\n\n")
            continue

        # --- Fallback: recurse into unknown block-level elements ---
        if tag in ("section", "article", "main", "aside", "header", "footer",
                    "nav", "details", "summary", "span", "a"):
            inner = _html_to_scholia(child, chapter_href, image_map)
            parts.append(inner)
            continue

        # Any other tag: try to get useful text
        inner = _html_to_scholia(child, chapter_href, image_map)
        if inner.strip():
            parts.append(inner)

    return "".join(parts)


def _inline_text(element: Tag, chapter_href: str, image_map: dict[str, str]) -> str:
    """
    Extract inline text from an element, preserving bold/italic/code/sup/sub.
    Does NOT add paragraph breaks — used for content within a single paragraph.
    """
    parts: list[str] = []

    for child in element.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
            continue

        if not isinstance(child, Tag):
            continue

        tag = child.name.lower()

        if tag in ("strong", "b"):
            inner = _inline_text(child, chapter_href, image_map)
            if inner.strip():
                parts.append(f"**{inner.strip()}**")
        elif tag in ("em", "i"):
            inner = _inline_text(child, chapter_href, image_map)
            if inner.strip():
                parts.append(f"*{inner.strip()}*")
        elif tag == "code":
            parts.append(f"`{child.get_text()}`")
        elif tag == "sup":
            parts.append(f"<sup>{child.get_text(strip=True)}</sup>")
        elif tag == "sub":
            parts.append(f"<sub>{child.get_text(strip=True)}</sub>")
        elif tag == "br":
            parts.append("\n")
        elif tag == "img":
            src = child.get("src", "")
            filename = _resolve_image_href(src, chapter_href, image_map)
            if filename:
                parts.append(f" [FIGURE {filename}] ")
        elif tag == "a":
            # Preserve link text, drop the URL
            inner = _inline_text(child, chapter_href, image_map)
            parts.append(inner)
        elif tag == "span":
            inner = _inline_text(child, chapter_href, image_map)
            parts.append(inner)
        else:
            # Fallback: just get text
            parts.append(child.get_text())

    return "".join(parts)


def _convert_list(
    list_el: Tag,
    chapter_href: str,
    image_map: dict[str, str],
    ordered: bool = False,
    depth: int = 0,
) -> str:
    """Convert <ul> or <ol> to markdown list syntax."""
    lines: list[str] = []
    indent = "  " * depth
    counter = 1

    for li in list_el.find_all("li", recursive=False):
        # Check for nested lists
        nested_lists = li.find_all(["ul", "ol"], recursive=False)

        # Get text content (excluding nested lists)
        text_parts = []
        for child in li.children:
            if isinstance(child, Tag) and child.name in ("ul", "ol"):
                continue
            if isinstance(child, NavigableString):
                text_parts.append(str(child))
            elif isinstance(child, Tag):
                text_parts.append(_inline_text(child, chapter_href, image_map))

        text = "".join(text_parts).strip()

        if ordered:
            prefix = f"{indent}{counter}. "
            counter += 1
        else:
            prefix = f"{indent}- "

        if text:
            lines.append(f"{prefix}{text}")

        for nested in nested_lists:
            nested_text = _convert_list(
                nested, chapter_href, image_map,
                ordered=(nested.name == "ol"),
                depth=depth + 1,
            )
            if nested_text:
                lines.append(nested_text)

    return "\n".join(lines)


# =============================================================================
# Section parsing (from assembled text)
# =============================================================================


def _parse_sections(full_text: str) -> list[dict]:
    """
    Parse [SECTION] markers from assembled text and compute offsets.
    Returns section dicts matching Scholia's sections table schema.
    """
    sections = []
    for match in re.finditer(r"\[SECTION\]\s*(#{1,6})\s*(.+)", full_text):
        level = len(match.group(1))
        title = match.group(2).strip()
        sections.append({
            "title": title,
            "level": level,
            "start_offset": match.start(),
            "end_offset": match.end(),
        })
    return sections
