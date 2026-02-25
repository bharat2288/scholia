"""
Lit Engine
==========
PDF and EPUB text extraction service.

Three-tier PDF extraction:
1. PyMuPDF enhanced - fast, good for text-based PDFs
2. Tesseract OCR - fallback for scanned/image PDFs
3. dots.ocr - batch processing for high-quality OCR

EPUB extraction:
- ebooklib for chapter extraction
- BeautifulSoup for HTML parsing
"""

from .epub_extractor import extract_epub

__all__ = ["extract_epub"]
