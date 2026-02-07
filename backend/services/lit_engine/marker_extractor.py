"""
Marker PDF Extractor
====================
Extract text from PDFs using Marker, then convert to Scholia format.

Marker outputs standard markdown with:
- # ## ### headings
- <span id="page-X-Y"> page markers
- ![](image.jpg) figure references
- | table | markdown tables

We convert these to Scholia's semantic markers:
- [PAGE n]
- [SECTION] # Heading
- [FIGURE]
- [TABLE]
- [CAPTION]
"""

import re
import torch
from pathlib import Path
from typing import Optional, Callable


def extract_with_marker(
    pdf_path: str,
    temp_id: str = None,
    progress_store: dict = None
) -> str:
    """
    Extract text from PDF using Marker, convert to Scholia format.

    Args:
        pdf_path: Path to PDF file
        temp_id: Job ID for progress tracking
        progress_store: Dict to update with progress

    Returns:
        Formatted text with Scholia markers
    """
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.config.parser import ConfigParser

    # Get page count for progress tracking
    import fitz
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    # Update progress
    if progress_store and temp_id:
        progress_store[temp_id] = {
            "status": "processing",
            "stage": "loading model",
            "current_page": 0,
            "total_pages": total_pages,
            "percent": 5,
            "error": None,
            "queue_position": 0
        }

    # Configure Marker
    config_parser = ConfigParser({
        "output_format": "markdown",
    })

    # Load models (cached after first load)
    # Force float32 for GPUs without bfloat16 support (pre-Ampere: GTX 10xx, 20xx, etc.)
    models = create_model_dict(dtype=torch.float32)

    # Update progress - marker extraction runs as single operation
    # Note: Marker doesn't expose per-page callbacks, so we show "extracting" with
    # indeterminate progress. The terminal shows Marker's internal tqdm progress.
    if progress_store and temp_id:
        progress_store[temp_id]["stage"] = "extracting"
        # Set to -1 to signal "indeterminate" to frontend (extraction in progress but no granular %)
        progress_store[temp_id]["percent"] = -1

    # Create converter and run
    converter = PdfConverter(
        config=config_parser.generate_config_dict(),
        artifact_dict=models,
    )

    result = converter(pdf_path)
    markdown = result.markdown

    # Update progress
    if progress_store and temp_id:
        progress_store[temp_id]["stage"] = "formatting"
        progress_store[temp_id]["percent"] = 95

    # Convert to Scholia format
    scholia_text = marker_to_scholia(markdown)

    return scholia_text


def marker_to_scholia(markdown: str) -> str:
    """
    Convert Marker markdown output to Scholia format.

    Transformations:
    - <span id="page-X-Y"> -> [PAGE n+1]
    - # Heading -> [SECTION] # Heading
    - ## Subheading -> [SECTION] ## Subheading
    - ![...](image.jpg) -> [FIGURE]
    - | Table | rows -> [TABLE] + content
    """
    text = markdown

    # 1. Convert page spans to [PAGE n]
    # Marker uses 0-indexed pages: <span id="page-0-0">
    def replace_page_span(match):
        page_num = int(match.group(1))
        return f'\n[PAGE {page_num + 1}]\n'

    # Handle both self-closing and regular spans
    text = re.sub(r'<span id="page-(\d+)-\d+"></span>', replace_page_span, text)
    text = re.sub(r'<span id="page-(\d+)-\d+">', replace_page_span, text)
    text = text.replace('</span>', '')

    # 2. Add [SECTION] before markdown headers
    # Match lines starting with # (1-6 hashes)
    text = re.sub(r'^(#{1,6}\s+)', r'[SECTION] \1', text, flags=re.MULTILINE)

    # 3. Convert figure references to [FIGURE]
    # Marker outputs: ![caption](path/to/image.jpg)
    # We want: [FIGURE]\n[CAPTION] caption
    def replace_figure(match):
        caption = match.group(1).strip()
        if caption:
            return f'[FIGURE]\n[CAPTION] {caption}'
        return '[FIGURE]'

    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', replace_figure, text)

    # 4. Mark tables with [TABLE]
    # Markdown tables start with | and have a separator row with |---|
    lines = text.split('\n')
    result_lines = []
    in_table = False

    for i, line in enumerate(lines):
        # Detect table start (line with | that's followed by separator)
        if '|' in line and not in_table:
            # Check if next line is a separator
            if i + 1 < len(lines) and re.match(r'\|[-:\s|]+\|', lines[i + 1]):
                result_lines.append('[TABLE]')
                in_table = True

        # Detect table end (line without |)
        if in_table and '|' not in line and line.strip():
            in_table = False

        result_lines.append(line)

    text = '\n'.join(result_lines)

    # 5. Clean up extra whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text


def generate_document_folder_name(pdf_path: str, content: str) -> str:
    """
    Generate Scholia document folder name in Author_Year_Title format.

    Attempts to extract metadata from:
    1. The PDF filename itself
    2. The extracted content (title patterns)
    """
    from unidecode import unidecode

    pdf_name = Path(pdf_path).stem

    # Strip temp_id prefix if present (format: "xxxxxxxx_originalname")
    if re.match(r'^[a-f0-9]{8}_', pdf_name):
        pdf_name = pdf_name[9:]

    # Try to parse from common filename patterns
    patterns = [
        r'^(.+?)\s*[-_]\s*(\d{4})\s*[-_]\s*(.+)$',  # Author - 2023 - Title
        r'^(.+?)\s*\((\d{4})\)\s*(.+)$',             # Author (2023) Title
        r'^(\d{4})\s*[-_]\s*(.+?)\s*[-_]\s*(.+)$',  # 2023 - Author - Title
        r'^(.+?)_(\d{4})_(.+)$',                     # Author_2023_Title
    ]

    author = "Unknown"
    year = "XXXX"
    title = pdf_name

    for pattern in patterns:
        match = re.match(pattern, pdf_name)
        if match:
            groups = match.groups()
            if len(groups) == 3:
                if groups[1].isdigit() and len(groups[1]) == 4:
                    author = groups[0]
                    year = groups[1]
                    title = groups[2]
                elif groups[0].isdigit() and len(groups[0]) == 4:
                    year = groups[0]
                    author = groups[1]
                    title = groups[2]
                break

    # Try to get title from content if we have a [SECTION] # marker (likely title)
    # Only override from content if filename didn't provide a usable title
    # (i.e., title still equals the raw pdf_name because no pattern matched)
    title_match = re.search(r'\[SECTION\]\s*#\s*([^#\n]+)', content)
    if title == pdf_name and title_match:
        extracted_title = title_match.group(1).strip()
        if len(extracted_title) > 5:
            title = extracted_title

    # Clean up for filename
    def clean_for_filename(text):
        text = unidecode(text)
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '_', text)
        text = text.strip('_')
        text = '_'.join(word.capitalize() for word in text.split('_'))
        return text

    author = clean_for_filename(author)
    title = clean_for_filename(title)

    # Truncate title if too long
    if len(title) > 50:
        title = title[:50].rsplit('_', 1)[0]

    return f"{author}_{year}_{title}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        print(f"Extracting {pdf_path}...")
        content = extract_with_marker(pdf_path)
        print(content[:2000])
        print(f"\n... ({len(content)} total chars)")
