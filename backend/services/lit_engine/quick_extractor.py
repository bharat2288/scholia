"""
Quick PDF Extractor (pymupdf4llm)
=================================
Fast text extraction for born-digital PDFs using pymupdf4llm.

This is the fastest extraction option (~1-2 seconds total) but:
- No OCR - useless for scanned PDFs
- Equations render as garbage
- Complex layouts may break

Best for: Quick previews, simple text-only PDFs, bulk processing where quality isn't critical.
"""

import pymupdf4llm
from pathlib import Path


def is_available() -> bool:
    """Check if pymupdf4llm is available."""
    try:
        import pymupdf4llm
        return True
    except ImportError:
        return False


def extract_with_quick(
    pdf_path: str,
    temp_id: str = None,
    progress_store: dict = None
) -> str:
    """
    Extract text from PDF using pymupdf4llm.

    Args:
        pdf_path: Path to the PDF file
        temp_id: Job ID for progress tracking (optional)
        progress_store: Dict to update with progress (optional)

    Returns:
        Extracted text as markdown string
    """
    # Update progress if tracking
    if progress_store and temp_id:
        progress_store[temp_id] = {
            **progress_store.get(temp_id, {}),
            "status": "processing",
            "stage": "extracting",
            "percent": 10
        }

    # Extract markdown - this is fast, usually < 2 seconds
    md_text = pymupdf4llm.to_markdown(pdf_path)

    # Update progress
    if progress_store and temp_id:
        progress_store[temp_id] = {
            **progress_store.get(temp_id, {}),
            "percent": 90,
            "stage": "formatting"
        }

    return md_text


def generate_document_folder_name(pdf_path: str, content: str = None) -> str:
    """
    Generate a standardized folder name for the document.
    Uses the same logic as marker_extractor for consistency.
    """
    # Import the shared function from marker_extractor
    from services.lit_engine.marker_extractor import generate_document_folder_name as marker_generate
    return marker_generate(pdf_path, content)
