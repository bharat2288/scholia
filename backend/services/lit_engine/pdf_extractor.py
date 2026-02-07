"""
PDF Extractor
=============
Extract text from PDFs using tiered approach.

Tier 1: PyMuPDF (fast, text-based PDFs)
Tier 2: Tesseract (scanned PDFs)
Tier 3: dots.ocr (batch, high quality)
"""

from pathlib import Path
from typing import Optional
import fitz  # PyMuPDF


async def extract_pdf(
    file_path: Path,
    output_dir: Path,
    use_ocr: bool = False
) -> dict:
    """
    Extract text from a PDF file.

    Args:
        file_path: Path to the PDF file
        output_dir: Directory to save extracted text
        use_ocr: Whether to use OCR (Tesseract) for extraction

    Returns:
        dict with:
            - success: bool
            - text_path: Path to extracted text file
            - sections: List of detected sections
            - page_count: Number of pages
            - extraction_method: Which tier was used
    """

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Output file path
    text_path = output_dir / f"{file_path.stem}.txt"

    try:
        # Open PDF with PyMuPDF
        doc = fitz.open(file_path)
        full_text = []
        sections = []

        for page_num, page in enumerate(doc, start=1):
            # Add page marker
            full_text.append(f"\n[PAGE {page_num}]\n")

            # Extract text from page
            page_text = page.get_text()

            # Check if page has meaningful text
            if len(page_text.strip()) < 50 and use_ocr:
                # TODO: Fall back to Tesseract for this page
                page_text = f"[OCR needed for page {page_num}]"

            full_text.append(page_text)

        # Combine all text
        combined_text = "\n".join(full_text)

        # Save to file
        text_path.write_text(combined_text, encoding="utf-8")

        doc.close()

        return {
            "success": True,
            "text_path": str(text_path),
            "sections": sections,
            "page_count": len(doc),
            "extraction_method": "pymupdf"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "text_path": None,
            "sections": [],
            "page_count": 0,
            "extraction_method": "failed"
        }


def assess_pdf_quality(file_path: Path) -> dict:
    """
    Assess PDF quality to determine best extraction method.

    Returns:
        dict with:
            - has_text: bool - whether PDF has extractable text
            - text_density: float - characters per page
            - recommended_method: str - 'pymupdf', 'tesseract', or 'dotsocr'
    """
    try:
        doc = fitz.open(file_path)
        total_chars = 0
        pages_with_text = 0

        for page in doc:
            text = page.get_text()
            chars = len(text.strip())
            total_chars += chars
            if chars > 100:
                pages_with_text += 1

        page_count = len(doc)
        doc.close()

        text_density = total_chars / page_count if page_count > 0 else 0
        text_coverage = pages_with_text / page_count if page_count > 0 else 0

        # Determine recommended method
        if text_coverage > 0.8 and text_density > 500:
            method = "pymupdf"
        elif text_coverage > 0.3:
            method = "tesseract"
        else:
            method = "dotsocr"

        return {
            "has_text": text_coverage > 0.5,
            "text_density": text_density,
            "text_coverage": text_coverage,
            "page_count": page_count,
            "recommended_method": method
        }

    except Exception as e:
        return {
            "has_text": False,
            "text_density": 0,
            "error": str(e),
            "recommended_method": "dotsocr"
        }
