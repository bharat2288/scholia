"""
Rebuild Extracted Text
======================
Regenerates extracted.txt from per-page JSON files with page markers.
Also pre-crops figures from PDF using bbox coordinates from JSON.

Usage:
    python rebuild_extracted.py <document_folder>

Example:
    python rebuild_extracted.py Vaswani_2017_Attention_Is_All_You_Need
"""

import json
import re
import io
from pathlib import Path

import fitz  # PyMuPDF

# DPI used by dots-ocr when rendering pages (must match dots_ocr.py settings)
DOTS_OCR_DPI = 120

# Map dots-ocr categories to our markers
CATEGORY_MAP = {
    'Title': '[TITLE]',
    'Section-header': '[SECTION]',
    'Picture': '[FIGURE]',
    'Caption': '[CAPTION]',
    'Table': '[TABLE]',
    'Formula': '',  # Formulas are inline in text
    'Text': '',
    'List-item': '',
    'Footnote': '[FOOTNOTE]',
    'Page-header': '',  # Skip headers
    'Page-footer': '',  # Skip footers
}


def rebuild_extracted(doc_folder: Path, method: str = 'dots-ocr') -> str:
    """
    Rebuild extracted text from JSON files with page markers.

    Returns the full extracted text content.
    """
    folder_name = doc_folder.name
    method_folder = doc_folder / f"{folder_name}--{method}"

    if not method_folder.exists():
        raise FileNotFoundError(f"Method folder not found: {method_folder}")

    # Find all page JSON files
    # Try both naming conventions: {name}_page_*.json (RunPod) and {name}--page_*.json (old)
    json_files = list(method_folder.glob(f"{folder_name}_page_*.json"))
    if not json_files:
        json_files = list(method_folder.glob(f"{folder_name}--page_*.json"))
    json_files = sorted(
        json_files,
        key=lambda p: int(re.search(r'page_(\d+)', p.name).group(1))
    )

    if not json_files:
        raise FileNotFoundError(f"No page JSON files found in {method_folder}")

    print(f"Found {len(json_files)} pages")

    output_lines = []

    for json_file in json_files:
        # Extract page number (0-indexed in files, display as 1-indexed)
        page_num = int(re.search(r'page_(\d+)', json_file.name).group(1))
        display_page = page_num + 1

        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                elements = json.load(f)

            # Handle double-encoded JSON (string containing JSON)
            if isinstance(elements, str):
                elements = json.loads(elements)
        except json.JSONDecodeError as e:
            print(f"  Warning: Skipping corrupted page {json_file.name}: {e}")
            continue

        # Add page marker (subtle format)
        if page_num > 0:  # Don't add marker before first page
            output_lines.append('')
            output_lines.append(f'[PAGE {display_page}]')
            output_lines.append('')

        # Process elements (skip if not a list or elements are not dicts)
        if not isinstance(elements, list):
            print(f"  Warning: Unexpected JSON structure in {json_file.name}")
            continue

        for elem in elements:
            # Skip non-dict elements
            if not isinstance(elem, dict):
                continue
            category = elem.get('category', '')
            text = elem.get('text', '').strip()

            # Skip page headers/footers
            if category in ('Page-header', 'Page-footer'):
                continue

            # Get marker prefix
            marker = CATEGORY_MAP.get(category, '')

            # Handle Picture elements specially - they have no text but need [FIGURE] marker
            if category == 'Picture':
                output_lines.append('[FIGURE]')
                output_lines.append('')
                continue

            # Skip other elements with no text
            if not text:
                continue

            if marker:
                output_lines.append(f'{marker} {text}')
            else:
                output_lines.append(text)

            output_lines.append('')  # Blank line between elements

    return '\n'.join(output_lines)


def crop_figures(doc_folder: Path, method: str = 'dots-ocr') -> int:
    """
    Pre-crop figures from PDF using bbox coordinates from page JSONs.

    Saves figures as: {doc_name}--figure_{page}_{index}.jpg

    Returns the number of figures cropped.
    """
    folder_name = doc_folder.name
    method_folder = doc_folder / f"{folder_name}--{method}"
    pdf_path = doc_folder / f"{folder_name}.pdf"

    if not method_folder.exists():
        print(f"  Method folder not found: {method_folder}")
        return 0

    if not pdf_path.exists():
        # Try finding PDF in dots-ocr folder (RunPod puts it there)
        pdf_in_method = method_folder / f"{folder_name}.pdf"
        if pdf_in_method.exists():
            pdf_path = pdf_in_method
        else:
            print(f"  PDF not found: {pdf_path}")
            return 0

    # Find all page JSON files
    # Try both naming conventions: {name}_page_*.json (RunPod) and {name}--page_*.json (old)
    json_files = list(method_folder.glob(f"{folder_name}_page_*.json"))
    if not json_files:
        json_files = list(method_folder.glob(f"{folder_name}--page_*.json"))
    json_files = sorted(
        json_files,
        key=lambda p: int(re.search(r'page_(\d+)', p.name).group(1))
    )

    if not json_files:
        print(f"  No page JSON files found")
        return 0

    # Open PDF once
    doc = fitz.open(pdf_path)

    # Coordinate conversion: dots-ocr bbox pixels → PDF points
    # dots-ocr renders at DOTS_OCR_DPI, PDF uses 72 points per inch
    scale = DOTS_OCR_DPI / 72

    figures_cropped = 0

    for json_file in json_files:
        page_num = int(re.search(r'page_(\d+)', json_file.name).group(1))

        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                elements = json.load(f)

            # Skip if not a list of element dicts
            if not isinstance(elements, list):
                continue

            # Find all Picture elements on this page (skip if element is not a dict)
            pictures = [e for e in elements if isinstance(e, dict) and e.get('category') == 'Picture']
        except (json.JSONDecodeError, TypeError) as e:
            print(f"  Skipping {json_file.name}: {e}")
            continue

        for fig_idx, picture in enumerate(pictures):
            bbox = picture.get('bbox')
            if not bbox or len(bbox) != 4:
                continue

            # Check if figure already exists
            figure_path = method_folder / f"{folder_name}--figure_{page_num}_{fig_idx}.jpg"
            if figure_path.exists():
                print(f"  Skipping existing: figure_{page_num}_{fig_idx}.jpg")
                figures_cropped += 1
                continue

            # Convert bbox from dots-ocr pixel coords to PDF points
            x1, y1, x2, y2 = bbox
            pdf_rect = fitz.Rect(
                x1 / scale,
                y1 / scale,
                x2 / scale,
                y2 / scale
            )

            # Validate page exists
            if page_num >= len(doc):
                print(f"  Warning: Page {page_num} not in PDF (has {len(doc)} pages)")
                continue

            # Crop figure from PDF at 2x zoom for crisp output
            try:
                pdf_page = doc[page_num]
                mat = fitz.Matrix(2, 2)
                pix = pdf_page.get_pixmap(matrix=mat, clip=pdf_rect)

                # Check for valid pixmap dimensions
                if pix.width < 10 or pix.height < 10:
                    print(f"  Skipping too small: figure_{page_num}_{fig_idx} ({pix.width}x{pix.height})")
                    continue

                # Save as JPEG
                img_bytes = pix.tobytes("jpeg")
                with open(figure_path, 'wb') as f:
                    f.write(img_bytes)

                figures_cropped += 1
                print(f"  Cropped: figure_{page_num}_{fig_idx}.jpg ({len(img_bytes)} bytes)")

            except Exception as e:
                print(f"  Error cropping figure_{page_num}_{fig_idx}: {e}")

    doc.close()
    return figures_cropped


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python rebuild_extracted.py <document_folder_name>")
        print("Example: python rebuild_extracted.py Vaswani_2017_Attention_Is_All_You_Need")
        sys.exit(1)

    folder_name = sys.argv[1]

    # Base documents path
    docs_path = Path(__file__).parent.parent.parent / "data" / "documents"
    doc_folder = docs_path / folder_name

    if not doc_folder.exists():
        print(f"Document folder not found: {doc_folder}")
        sys.exit(1)

    # Determine method
    method = 'dots-ocr'
    for m in ['dots-ocr', 'pymupdf', 'tesseract']:
        if (doc_folder / f"{folder_name}--{m}").exists():
            method = m
            break

    print(f"Rebuilding {folder_name} using {method}...")

    try:
        content = rebuild_extracted(doc_folder, method)

        # Write output
        output_path = doc_folder / f"{folder_name}--{method}" / f"{folder_name}--{method}--extracted.txt"

        # Backup original
        if output_path.exists():
            backup_path = output_path.with_suffix('.txt.bak')
            output_path.rename(backup_path)
            print(f"Backed up original to {backup_path.name}")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"Wrote {len(content)} chars to {output_path.name}")

        # Pre-crop figures from PDF
        print(f"\nCropping figures from PDF...")
        num_figures = crop_figures(doc_folder, method)
        print(f"Cropped {num_figures} figures")

        print("\nDone!")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
