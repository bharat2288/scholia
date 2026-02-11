"""
Finalize Document
=================
Shared module for converting downloaded OCR output to Scholia format.

Called by:
- runpod.py download_job() after downloading from RunPod
- process_runpod_batch.py for manual/CLI processing
- CLI for finalizing staged downloads

This module handles:
1. Folder name standardization (Zotero -> Scholia format)
2. File restructuring and renaming
3. Building extracted.txt from JSON files (via rebuild_extracted)
4. Cropping figures from PDF (via crop_figures)
"""

import re
import shutil
from pathlib import Path
from typing import Optional

from services.rebuild_extracted import rebuild_extracted, crop_figures

# Windows MAX_PATH is 260 chars
# Deepest path: documents/{name}/{name}--dots-ocr/{name}_page_999_nohf.md
# That's ~3.5x folder name + 30 chars overhead + base path (~50 chars)
# Safe max: 50 chars for folder name
MAX_FOLDER_NAME_LENGTH = 50

# Common filler words to remove from titles
FILLER_WORDS = {'a', 'an', 'the', 'of', 'in', 'on', 'and', 'or', 'to', 'for', 'with', 'by'}


def standardize_folder_name(raw_name: str, max_title_words: int = 4) -> str:
    """
    Convert Zotero-style folder name to Scholia format.

    Examples:
        "Gillespie (2014) - The Relevance of Algorithms"
        -> "Gillespie_2014_Relevance_Algorithms"

        "Rose & Abi-Rached - 2013 - Neuro"
        -> "Rose_AbiRached_2013_Neuro"

        "Deleuze & Guattari (1983) Anti-Oedipus Capitalism and Schizophrenia"
        -> "Deleuze_Guattari_1983_AntiOedipus_Capitalism"

    Handles:
    - "Author (Year) - Title"
    - "Author - Year - Title"
    - "Author (Year) Title" (no dash)
    - Already-standardized names (pass through)
    - Job ID prefixes like "35406520_Author..."

    Enforces MAX_FOLDER_NAME_LENGTH (50 chars) for Windows compatibility.
    """
    # Strip job ID prefix if present (8 hex chars + underscore)
    if re.match(r'^[a-f0-9]{8}_', raw_name):
        raw_name = raw_name[9:]

    # If already in Scholia format (underscores, no parens, no " - "), pass through
    if "_" in raw_name and "(" not in raw_name and " - " not in raw_name and " " not in raw_name:
        return _truncate_folder_name(raw_name, max_title_words)

    author = None
    year = None
    title = None

    # Pattern 1: "Author (Year) - Title"
    match = re.match(r'^(.+?)\s*\((\d{4})\)\s*[-–—]\s*(.+)$', raw_name)
    if match:
        author, year, title = match.groups()
    else:
        # Pattern 2: "Author - Year - Title"
        match = re.match(r'^(.+?)\s*[-–—]\s*(\d{4})\s*[-–—]\s*(.+)$', raw_name)
        if match:
            author, year, title = match.groups()
        else:
            # Pattern 3: "Author (Year) Title" (no dash before title)
            match = re.match(r'^(.+?)\s*\((\d{4})\)\s+(.+)$', raw_name)
            if match:
                author, year, title = match.groups()

    if not all([author, year, title]):
        # Fallback: just clean up the name
        result = re.sub(r'[\s\-–—()]+', '_', raw_name)
        result = re.sub(r'[^\w_]', '', result)
        result = re.sub(r'_+', '_', result)
        return _truncate_folder_name(result.strip('_'), max_title_words)

    # Clean author
    author = author.strip()
    author = re.sub(r'\s*[&,]\s*', '_', author)  # & and , become underscore
    author = re.sub(r'\s+', '_', author)  # spaces become underscore
    author = re.sub(r'-', '', author)  # remove hyphens in names

    # Clean title
    title = title.strip()
    title = re.sub(r'[:"\']', '', title)  # remove punctuation
    title = re.sub(r'[()]', '', title)  # remove parens
    title = re.sub(r'[\s\-–—]+', '_', title)  # spaces/dashes become underscore

    # Remove filler words and limit word count
    words = title.split('_')
    words = [w for w in words if w.lower() not in FILLER_WORDS and w]
    words = words[:max_title_words]
    title = '_'.join(words)

    # Remove any remaining special chars
    title = re.sub(r'[^\w_]', '', title)

    # Combine
    result = f"{author}_{year}_{title}"
    result = re.sub(r'_+', '_', result)  # collapse multiple underscores

    return _truncate_folder_name(result.strip('_'), max_title_words)


def _truncate_folder_name(name: str, max_title_words: int = 4) -> str:
    """
    Truncate folder name to MAX_FOLDER_NAME_LENGTH while preserving author+year.

    Strategy:
    1. If under limit, return as-is
    2. Find year pattern, keep author+year intact
    3. Truncate title portion at word boundary
    """
    if len(name) <= MAX_FOLDER_NAME_LENGTH:
        return name

    # Try to find year pattern
    year_match = re.search(r'_(\d{4})_', name)
    if year_match:
        year_end = year_match.end()
        prefix = name[:year_end].rstrip('_')
        title = name[year_end:].lstrip('_')

        # Calculate space for title
        available = MAX_FOLDER_NAME_LENGTH - len(prefix) - 1  # -1 for underscore

        if available >= 5:
            # Truncate title at word boundary
            words = title.split('_')[:max_title_words]
            truncated_title = '_'.join(words)

            while len(truncated_title) > available and words:
                words = words[:-1]
                truncated_title = '_'.join(words)

            if truncated_title:
                result = f"{prefix}_{truncated_title}"
                print(f"[finalize] Truncated: {name[:40]}... -> {result} ({len(result)} chars)")
                return result

    # Fallback: simple truncation at word boundary
    truncated = name[:MAX_FOLDER_NAME_LENGTH]
    last_underscore = truncated.rfind('_')
    if last_underscore > MAX_FOLDER_NAME_LENGTH // 2:
        result = truncated[:last_underscore]
    else:
        result = truncated.rstrip('_')

    print(f"[finalize] Truncated: {name[:40]}... -> {result} ({len(result)} chars)")
    return result


def finalize_document(
    staging_folder: Path,
    documents_dir: Path,
    source_pdf: Optional[Path] = None,
    original_name: Optional[str] = None
) -> dict:
    """
    Finalize a downloaded OCR output folder into Scholia format.

    Steps:
    1. Determine Scholia folder name (standardize if needed)
    2. Create document folder structure
    3. Copy/rename files to Scholia naming convention
    4. Copy source PDF if provided
    5. Build extracted.txt from JSON files
    6. Crop figures from PDF using bbox data

    Args:
        staging_folder: Downloaded output folder (may have Zotero-style name)
        documents_dir: Target documents/ directory
        source_pdf: Optional PDF file to include (for figure cropping)
        original_name: Original Zotero name if different from folder name

    Returns:
        dict with:
            - folder_name: Final Scholia folder name
            - doc_folder: Path to created document folder
            - char_count: Characters in extracted.txt
            - page_count: Number of pages processed
            - figure_count: Number of figures cropped
            - error: Error message if failed
    """
    result = {
        "folder_name": None,
        "doc_folder": None,
        "char_count": 0,
        "page_count": 0,
        "figure_count": 0,
        "error": None
    }

    try:
        # Determine the original name (for standardization)
        raw_name = original_name or staging_folder.name

        # Standardize to Scholia format
        scholia_name = standardize_folder_name(raw_name)
        result["folder_name"] = scholia_name
        print(f"[finalize] {raw_name} -> {scholia_name}")

        # Create document folder structure
        doc_folder = documents_dir / scholia_name
        method_folder = doc_folder / f"{scholia_name}--dots-ocr"

        doc_folder.mkdir(parents=True, exist_ok=True)
        method_folder.mkdir(parents=True, exist_ok=True)
        result["doc_folder"] = doc_folder

        # Find source files in staging folder
        # They might be in a nested subfolder with the same name
        source_files_dir = staging_folder
        nested = staging_folder / staging_folder.name
        if nested.exists() and nested.is_dir():
            source_files_dir = nested

        # Also check for nested folder with original name (without job ID prefix)
        if original_name:
            nested_orig = staging_folder / original_name
            if nested_orig.exists() and nested_orig.is_dir():
                source_files_dir = nested_orig
            # Check for job-id prefixed nested folder
            for child in staging_folder.iterdir():
                if child.is_dir() and child.name != staging_folder.name:
                    source_files_dir = child
                    break

        # Copy and rename page files
        page_count = 0
        for src_file in source_files_dir.iterdir():
            if not src_file.is_file():
                continue

            new_name = src_file.name

            # Replace original name with Scholia name in filename
            # Handle various naming patterns
            for pattern in [raw_name, staging_folder.name]:
                if pattern in new_name:
                    new_name = new_name.replace(pattern, scholia_name)
                    break

            # Also handle job ID prefixed names
            if re.match(r'^[a-f0-9]{8}_', new_name):
                # Remove job ID prefix and replace rest
                name_without_prefix = new_name[9:]
                for pattern in [raw_name, staging_folder.name]:
                    clean_pattern = pattern[9:] if re.match(r'^[a-f0-9]{8}_', pattern) else pattern
                    if clean_pattern in name_without_prefix:
                        new_name = name_without_prefix.replace(clean_pattern, scholia_name)
                        break

            # Clean up stray spaces (e.g. trailing space in original name
            # leaves "scholia_name _page_0.json" instead of "scholia_name_page_0.json")
            new_name = re.sub(r'\s+_page_', '_page_', new_name)

            dst_file = method_folder / new_name
            shutil.copy2(str(src_file), str(dst_file))

            if "_page_" in new_name and new_name.endswith(".json"):
                page_count += 1

        result["page_count"] = page_count
        print(f"[finalize] Copied {page_count} page files")

        # Copy .jsonl file if present (at staging folder root)
        for jsonl_file in staging_folder.glob("*.jsonl"):
            new_name = jsonl_file.name
            for pattern in [raw_name, staging_folder.name]:
                if pattern in new_name:
                    new_name = new_name.replace(pattern, scholia_name)
                    break
            shutil.copy2(str(jsonl_file), str(method_folder / new_name))

        # Copy source PDF
        pdf_path = doc_folder / f"{scholia_name}.pdf"
        if source_pdf and source_pdf.exists():
            shutil.copy2(str(source_pdf), str(pdf_path))
            print(f"[finalize] Copied PDF")
        elif not pdf_path.exists():
            print(f"[finalize] Warning: No PDF available for figure cropping")

        # Build extracted.txt from JSON files
        print(f"[finalize] Building extracted.txt...")
        content = rebuild_extracted(doc_folder, method='dots-ocr')
        output_path = method_folder / f"{scholia_name}--dots-ocr--extracted.txt"
        output_path.write_text(content, encoding='utf-8')
        result["char_count"] = len(content)
        print(f"[finalize] Wrote {len(content)} chars")

        # Crop figures from PDF
        if pdf_path.exists():
            print(f"[finalize] Cropping figures...")
            fig_count = crop_figures(doc_folder, method='dots-ocr')
            result["figure_count"] = fig_count
            print(f"[finalize] Cropped {fig_count} figures")

    except Exception as e:
        result["error"] = str(e)
        print(f"[finalize] Error: {e}")
        import traceback
        traceback.print_exc()

    return result


def finalize_from_tarball(
    tarball_path: Path,
    pdf_path: Path,
    documents_dir: Path,
    original_name: Optional[str] = None,
    cleanup: bool = True
) -> dict:
    """
    Extract a tarball and finalize the document.

    Convenience wrapper that:
    1. Extracts tarball to temp directory
    2. Calls finalize_document()
    3. Cleans up temp directory

    Args:
        tarball_path: Path to .tar.gz file
        pdf_path: Path to source PDF
        documents_dir: Target documents/ directory
        original_name: Original Zotero name (inferred from tarball if not provided)
        cleanup: Whether to delete tarball and temp files after

    Returns:
        Same as finalize_document()
    """
    import tarfile
    import tempfile

    # Extract tarball
    temp_dir = Path(tempfile.mkdtemp(prefix="scholia_finalize_"))

    try:
        with tarfile.open(tarball_path, 'r:gz') as tf:
            tf.extractall(temp_dir)

        # Find extracted folder
        extracted_folders = [f for f in temp_dir.iterdir() if f.is_dir()]
        if not extracted_folders:
            return {"error": f"No folder found in tarball: {tarball_path}"}

        staging_folder = extracted_folders[0]

        # Infer original name if not provided
        if not original_name:
            original_name = staging_folder.name

        # Finalize
        result = finalize_document(
            staging_folder=staging_folder,
            documents_dir=documents_dir,
            source_pdf=pdf_path,
            original_name=original_name
        )

        # Cleanup
        if cleanup:
            shutil.rmtree(temp_dir, ignore_errors=True)
            # Don't delete tarball/pdf - caller decides

        return result

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"error": str(e)}


# CLI interface
def main():
    """
    CLI for finalizing downloaded documents.

    Usage:
        python finalize_document.py <staging_folder> [--pdf <pdf_path>]
        python finalize_document.py --tarball <tarball_path> --pdf <pdf_path>
    """
    import argparse

    parser = argparse.ArgumentParser(description="Finalize downloaded OCR output")
    parser.add_argument("staging_folder", nargs="?", help="Path to staging folder")
    parser.add_argument("--tarball", help="Path to .tar.gz file (alternative to staging_folder)")
    parser.add_argument("--pdf", help="Path to source PDF")
    parser.add_argument("--name", help="Original Zotero name (if different from folder)")
    parser.add_argument("--docs-dir", default=None, help="Documents directory (default: data/documents)")

    args = parser.parse_args()

    # Determine documents directory
    if args.docs_dir:
        documents_dir = Path(args.docs_dir)
    else:
        documents_dir = Path(__file__).parent.parent.parent / "data" / "documents"

    pdf_path = Path(args.pdf) if args.pdf else None

    if args.tarball:
        tarball_path = Path(args.tarball)
        if not tarball_path.exists():
            print(f"Tarball not found: {tarball_path}")
            return 1

        result = finalize_from_tarball(
            tarball_path=tarball_path,
            pdf_path=pdf_path,
            documents_dir=documents_dir,
            original_name=args.name
        )
    elif args.staging_folder:
        staging_folder = Path(args.staging_folder)
        if not staging_folder.exists():
            print(f"Staging folder not found: {staging_folder}")
            return 1

        result = finalize_document(
            staging_folder=staging_folder,
            documents_dir=documents_dir,
            source_pdf=pdf_path,
            original_name=args.name
        )
    else:
        parser.print_help()
        return 1

    # Print result
    if result.get("error"):
        print(f"\nFailed: {result['error']}")
        return 1
    else:
        print(f"\nSuccess!")
        print(f"  Folder: {result['folder_name']}")
        print(f"  Pages: {result['page_count']}")
        print(f"  Chars: {result['char_count']}")
        print(f"  Figures: {result['figure_count']}")
        return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
