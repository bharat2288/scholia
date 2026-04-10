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

import importlib.util


def is_available() -> bool:
    """Check if pymupdf4llm is available."""
    return importlib.util.find_spec("pymupdf4llm") is not None


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
    if not is_available():
        raise RuntimeError(
            "Quick extraction requires pymupdf4llm. Rebuild the backend environment from backend/requirements.txt."
        )

    import pymupdf4llm

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
    Uses the shared document naming logic for consistency.
    """
    from services.lit_engine.document_naming import generate_document_folder_name as shared_generate

    return shared_generate(pdf_path, content)
