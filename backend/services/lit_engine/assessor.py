"""
PDF Prescan Assessment
======================
Analyzes PDFs to recommend the appropriate extraction tier:
- marker: Text-based PDFs, good layouts (fast, ~20-40s)
- dots-ocr: Scanned PDFs, complex layouts, equations, tables (slow, ~2.5s/page)

Ported from Lit Processor with tier updates.
"""

import fitz  # PyMuPDF
import re
from pathlib import Path


def assess_pdf(pdf_path: str) -> dict:
    """
    Quick prescan of a PDF to determine the best extraction tier.

    Samples first 5 pages and analyzes:
    - Text extraction yield (scanned vs text-based)
    - Math/equation indicators
    - Layout complexity
    - Page count (100+ defaults to marker for speed)

    Args:
        pdf_path: Path to the PDF file

    Returns:
        dict with:
            recommendation: "marker" | "dots-ocr"
            page_count: int
            time_estimates: dict with seconds per tier
            signals: dict with detection details
    """
    doc = fitz.open(pdf_path)
    page_count = doc.page_count

    # Sample first 5 pages (or all if fewer)
    sample_pages = min(5, page_count)

    text_chars = 0
    image_pages = 0
    math_signals = 0
    has_tables = False

    for i in range(sample_pages):
        page = doc[i]
        text = page.get_text()
        text_chars += len(text.strip())

        # Check if page is mostly image-based (scanned)
        if len(text.strip()) < 50:
            image_pages += 1

        # Check for math indicators
        if _has_math_patterns(text):
            math_signals += 1

        # Check for equation images (blocks that look like inline equations)
        if _has_equation_images(page):
            math_signals += 1

        # Check for table patterns
        if _has_table_patterns(text):
            has_tables = True

    doc.close()

    # Calculate signals
    avg_text_per_page = text_chars / sample_pages if sample_pages > 0 else 0
    scanned_ratio = image_pages / sample_pages if sample_pages > 0 else 0
    is_mostly_scanned = scanned_ratio > 0.5
    is_math_heavy = math_signals >= 2

    # Decision logic - simplified to marker vs dots-ocr
    if is_mostly_scanned:
        # Scanned document - needs OCR
        recommendation = "dots-ocr"
        reason = "Scanned document requires OCR"
    elif is_math_heavy:
        # Text-based but equation-heavy - dots-ocr handles math better
        recommendation = "dots-ocr"
        reason = "Contains significant equations/formulas"
    elif has_tables and is_math_heavy:
        # Complex tables with math
        recommendation = "dots-ocr"
        reason = "Complex tables with equations"
    else:
        # Standard text-based document - Marker handles well
        recommendation = "marker"
        reason = "Text-based document, good for Marker extraction"

    # Time estimates (rough, in seconds)
    # Quick: ~0.05s per page (pure text extraction, no model)
    # Marker: ~1-2s per page for most documents
    # dots-ocr: ~2.5s per page (GPU-bound)
    time_estimates = {
        "quick": max(2, round(page_count * 0.05, 1)),  # Minimum 2s for UI display
        "marker": round(page_count * 1.5, 1),
        "dots-ocr": round(page_count * 2.5, 1)
    }

    return {
        "recommendation": recommendation,
        "reason": reason,
        "page_count": page_count,
        "time_estimates": time_estimates,
        "signals": {
            "avg_text_per_page": round(avg_text_per_page),
            "scanned_ratio": round(scanned_ratio, 2),
            "math_signals": math_signals,
            "has_tables": has_tables,
            "is_mostly_scanned": is_mostly_scanned,
            "is_math_heavy": is_math_heavy
        }
    }


def _has_math_patterns(text: str) -> bool:
    """Check for common math/equation patterns in text."""
    patterns = [
        r'\$.*?\$',           # LaTeX inline math
        r'\\frac\{',          # LaTeX fractions
        r'\\sum',             # LaTeX sum
        r'\\int',             # LaTeX integral
        r'\\partial',         # Partial derivatives
        r'\b[a-z]\s*=\s*[a-z0-9]',  # Simple equations like "x = 2y"
        r'∑|∫|∂|∞|√|±|×|÷',  # Math symbols
        r'\([0-9]+\.[0-9]+\)', # Equation numbers like (3.14)
    ]

    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _has_equation_images(page) -> bool:
    """
    Check for image blocks that might be equations.

    Looks for small, wide images that are likely inline equations
    rather than figures.
    """
    image_list = page.get_images()

    for img in image_list:
        # Get image dimensions from the page
        # This is a heuristic: small height, moderate width = likely equation
        xref = img[0]
        try:
            base_image = page.parent.extract_image(xref)
            width = base_image.get("width", 0)
            height = base_image.get("height", 0)

            # Equation-like proportions: wide and short
            if height > 0 and width / height > 3 and height < 100:
                return True
        except (ValueError, TypeError, KeyError):
            continue

    return False


def _has_table_patterns(text: str) -> bool:
    """Check for table-like patterns in text."""
    # Look for repeated tab/space patterns that suggest tabular data
    lines = text.split('\n')

    # Count lines with multiple tab-separated or space-aligned columns
    tabular_lines = 0
    for line in lines:
        # Multiple consecutive spaces or tabs suggest columns
        if re.search(r'\t.*\t', line) or re.search(r'\s{3,}.*\s{3,}', line):
            tabular_lines += 1

    # If more than 5 lines look tabular, probably has tables
    return tabular_lines > 5


if __name__ == "__main__":
    # Quick test
    import sys
    if len(sys.argv) > 1:
        result = assess_pdf(sys.argv[1])
        print(f"Recommendation: {result['recommendation']}")
        print(f"Reason: {result['reason']}")
        print(f"Pages: {result['page_count']}")
        print(f"Time estimates: {result['time_estimates']}")
        print(f"Signals: {result['signals']}")
