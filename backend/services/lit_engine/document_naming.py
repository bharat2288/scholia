"""
Document naming helpers for extracted PDFs.
"""

from pathlib import Path
import re
from typing import Optional

from unidecode import unidecode


_FILENAME_PATTERNS = [
    r"^(.+?)\s*[-_]\s*(\d{4})\s*[-_]\s*(.+)$",
    r"^(.+?)\s*\((\d{4})\)\s*(.+)$",
    r"^(\d{4})\s*[-_]\s*(.+?)\s*[-_]\s*(.+)$",
    r"^(.+?)_(\d{4})_(.+)$",
]


def _strip_temp_prefix(name: str) -> str:
    if re.match(r"^[a-f0-9]{8}_", name):
        return name[9:]
    return name


def _clean_for_filename(text: str) -> str:
    text = unidecode(text)
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "_", text)
    text = text.strip("_")
    return "_".join(word.capitalize() for word in text.split("_"))


def generate_document_folder_name(pdf_path: str, content: Optional[str] = None) -> str:
    """
    Generate a stable Scholia folder name from a PDF path and optional content.
    """
    pdf_name = _strip_temp_prefix(Path(pdf_path).stem)

    author = "Unknown"
    year = "XXXX"
    title = pdf_name

    for pattern in _FILENAME_PATTERNS:
        match = re.match(pattern, pdf_name)
        if not match:
            continue

        groups = match.groups()
        if len(groups) != 3:
            continue

        if groups[1].isdigit() and len(groups[1]) == 4:
            author, year, title = groups
        elif groups[0].isdigit() and len(groups[0]) == 4:
            year, author, title = groups
        break

    if content:
        title_match = re.search(r"\[SECTION\]\s*#\s*([^#\n]+)", content)
        if title == pdf_name and title_match:
            extracted_title = title_match.group(1).strip()
            if len(extracted_title) > 5:
                title = extracted_title

    author = _clean_for_filename(author)
    title = _clean_for_filename(title)

    if len(title) > 50:
        title = title[:50].rsplit("_", 1)[0]

    return f"{author}_{year}_{title}"


def predict_document_folder_name(filename: str) -> str:
    """
    Predict the document folder name from a filename alone.
    """
    return generate_document_folder_name(filename)
