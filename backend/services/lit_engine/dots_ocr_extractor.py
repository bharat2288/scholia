"""
dots.ocr Extractor
==================

Tier 2: For complex layouts, scanned pages, equations, and tables.
Uses the dots.ocr VLM model for structure-aware extraction.

Ported from Lit Processor with Scholia storage integration.

Requires:
- dots.ocr package installed (set DOTS_OCR_PATH env var, or peer at ../lit-processor/dots-ocr)
- Model weights downloaded
- CUDA-capable GPU (RTX 3070 Ti or better)

Model Persistence:
- The DotsOCRParser is loaded once and reused across all jobs
- This avoids the 2-5 minute model load time for each file
- Call unload_model() to free GPU memory when done

Resume Support:
- Jobs save state to job_state.json in the output folder
- On resume, already-processed pages are skipped
- Progress continues from where it left off
"""

import json
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add dots.ocr to path (located in lit-processor project)
# Resolve via env var, or fall back to peer directory relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DOTS_OCR_PATH = Path(os.getenv("DOTS_OCR_PATH", _PROJECT_ROOT.parent / "lit-processor" / "dots-ocr"))
if str(DOTS_OCR_PATH) not in sys.path:
    sys.path.insert(0, str(DOTS_OCR_PATH))

# Check if dots.ocr is available
DOTS_OCR_AVAILABLE = False
WEIGHTS_PATH = DOTS_OCR_PATH / "weights" / "DotsOCR"

try:
    from dots_ocr.parser import DotsOCRParser
    DOTS_OCR_AVAILABLE = True
except ImportError as e:
    print(f"[dots.ocr] Not available: {e}")

# Global parser instance - loaded once, reused for all jobs
_parser_instance = None
_parser_lock = None  # Threading lock for safe access


def _get_parser():
    """Get or create the singleton parser instance."""
    global _parser_instance, _parser_lock
    import threading

    if _parser_lock is None:
        _parser_lock = threading.Lock()

    with _parser_lock:
        if _parser_instance is None:
            print("[dots.ocr] Loading model (this takes 2-5 minutes on first run)...")

            # Change to dots.ocr directory so relative paths work
            original_cwd = os.getcwd()
            os.chdir(str(DOTS_OCR_PATH))

            try:
                _parser_instance = DotsOCRParser(
                    use_hf=True,
                    output_dir=str(DOTS_OCR_PATH / "output"),  # Default, overridden per-job
                    dpi=120,  # Reduced from 150 for ~35% faster processing
                    num_thread=1,  # HF mode uses single thread
                    max_completion_tokens=12000  # Reduced from 24000 - academic papers rarely need more
                )
                print("[dots.ocr] Model loaded and ready")
            finally:
                os.chdir(original_cwd)

        return _parser_instance


def unload_model():
    """Unload the model to free GPU memory."""
    global _parser_instance
    if _parser_instance is not None:
        # Clear the model references
        if hasattr(_parser_instance, 'model'):
            del _parser_instance.model
        if hasattr(_parser_instance, 'processor'):
            del _parser_instance.processor
        _parser_instance = None

        # Force garbage collection and clear CUDA cache
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        print("[dots.ocr] Model unloaded, GPU memory freed")


def is_model_loaded() -> bool:
    """Check if the model is currently loaded."""
    return _parser_instance is not None


def is_available() -> bool:
    """Check if dots.ocr is ready to use."""
    if not DOTS_OCR_AVAILABLE:
        return False
    return WEIGHTS_PATH.exists()


def get_setup_status() -> dict:
    """Get detailed setup status for diagnostics."""
    status = {
        "dots_ocr_installed": DOTS_OCR_AVAILABLE,
        "weights_present": WEIGHTS_PATH.exists(),
        "weights_path": str(WEIGHTS_PATH),
        "cuda_available": False,
        "gpu_name": None,
        "gpu_memory_gb": 0
    }

    try:
        import torch
        status["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            status["gpu_name"] = torch.cuda.get_device_name(0)
            status["gpu_memory_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
    except ImportError:
        pass

    return status


# =============================================================================
# Job State Management - for resume support
# =============================================================================

def get_job_state_path(save_dir: Path) -> Path:
    """Get path to job_state.json for a given output directory."""
    return save_dir / "job_state.json"


def load_job_state(save_dir: Path) -> Optional[Dict[str, Any]]:
    """Load job state from disk if it exists."""
    state_path = get_job_state_path(save_dir)
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[dots.ocr] Warning: Could not load job state: {e}")
    return None


def save_job_state(save_dir: Path, state: Dict[str, Any]):
    """Save job state to disk."""
    state_path = get_job_state_path(save_dir)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        print(f"[dots.ocr] Warning: Could not save job state: {e}")


def delete_job_state(save_dir: Path):
    """Delete job state file after successful completion."""
    state_path = get_job_state_path(save_dir)
    if state_path.exists():
        try:
            state_path.unlink()
            print(f"[dots.ocr] Cleaned up job state: {state_path}")
        except IOError as e:
            print(f"[dots.ocr] Warning: Could not delete job state: {e}")


def detect_completed_pages(save_dir: Path, filename: str, total_pages: int) -> List[int]:
    """
    Detect which pages have already been processed by checking for output files.

    Returns list of completed page indices (0-based).
    """
    completed = []
    for page_idx in range(total_pages):
        # Check for the .md file which is the final output for each page
        md_file = save_dir / f"{filename}_page_{page_idx}.md"
        json_file = save_dir / f"{filename}_page_{page_idx}.json"

        # Consider page complete if both .md and .json exist
        if md_file.exists() and json_file.exists():
            completed.append(page_idx)

    return completed


# =============================================================================
# Extraction Logic
# =============================================================================

def extract_with_dots_ocr(
    pdf_path: str,
    temp_id: str = None,
    progress_store: dict = None,
    output_dir: Path = None,
    save_name: str = None
) -> str:
    """
    Extract content with progress tracking and resume support.

    Automatically detects previously processed pages and skips them.
    Saves job state after each page for crash recovery.

    Args:
        pdf_path: Path to the PDF file
        temp_id: ID for progress tracking (optional)
        progress_store: Dict to update with progress (optional)
        output_dir: Where to save intermediate files (optional, defaults to temp)
        save_name: Base name for output files (optional, defaults to PDF stem).
            When provided, files are written directly to output_dir as
            {save_name}_page_N.{ext} — matching the RunPod convention.

    Returns:
        Extracted content as Scholia-formatted string
    """
    import fitz  # PyMuPDF for page counting
    from dots_ocr.utils.doc_utils import load_images_from_pdf

    if not DOTS_OCR_AVAILABLE:
        raise RuntimeError(
            f"dots.ocr is not installed. Ensure {DOTS_OCR_PATH} exists, or set DOTS_OCR_PATH env var."
        )

    if not is_available():
        raise RuntimeError(
            f"dots.ocr model weights not found at {WEIGHTS_PATH}. "
            "Run the setup wizard to download them."
        )

    # Normalize paths
    pdf_path_obj = Path(pdf_path).resolve()
    filename = pdf_path_obj.stem

    # Determine the base name for output files
    file_prefix = save_name if save_name else filename

    # Use provided output_dir directly when save_name is given (caller manages structure),
    # otherwise create a subdirectory for intermediate files
    if output_dir and save_name:
        save_dir = output_dir
    elif output_dir:
        save_dir = output_dir / "dots_ocr_pages"
    else:
        save_dir = pdf_path_obj.parent / f"{filename}_dots_ocr"
    save_dir.mkdir(parents=True, exist_ok=True)

    # Get total pages
    doc = fitz.open(str(pdf_path_obj))
    total_pages = len(doc)
    doc.close()

    # Check for resume - detect already completed pages
    completed_pages = detect_completed_pages(save_dir, file_prefix, total_pages)
    remaining_pages = [i for i in range(total_pages) if i not in completed_pages]

    if completed_pages:
        print(f"[dots.ocr] Resume detected: {len(completed_pages)}/{total_pages} pages already done")
        print(f"[dots.ocr] Remaining pages: {remaining_pages}")

    # Initialize progress
    if progress_store and temp_id:
        progress_store[temp_id]["total_pages"] = total_pages
        progress_store[temp_id]["current_page"] = len(completed_pages)
        if is_model_loaded():
            progress_store[temp_id]["stage"] = "extracting"
        else:
            progress_store[temp_id]["stage"] = "loading model"

    # Get or create the parser (loads model on first call)
    parser = _get_parser()

    # Update progress now that model is loaded
    if progress_store and temp_id:
        progress_store[temp_id]["stage"] = "extracting"

    # Change to dots.ocr directory so relative paths work
    original_cwd = os.getcwd()
    os.chdir(str(DOTS_OCR_PATH))

    try:
        print(f"[dots.ocr] Processing: {pdf_path_obj}")
        print(f"[dots.ocr] Output dir: {save_dir}")

        # Check for cancellation before starting
        if progress_store and temp_id:
            if progress_store[temp_id].get("status") == "cancelled":
                raise InterruptedError("Processing cancelled by user")

        # Calculate initial progress (account for already-completed pages)
        base_percent = int(10 + (len(completed_pages) / total_pages) * 75)
        if progress_store and temp_id:
            progress_store[temp_id]["percent"] = base_percent

        # Process remaining pages if any
        new_results = []
        if remaining_pages:
            # Load all page images from PDF
            print(f"[dots.ocr] Loading PDF images...")
            all_images = load_images_from_pdf(str(pdf_path_obj), dpi=parser.dpi)

            # Process only remaining pages
            prompt_mode = "prompt_layout_all_en"
            for i, page_idx in enumerate(remaining_pages):
                # Check for cancellation
                if progress_store and temp_id:
                    if progress_store[temp_id].get("status") == "cancelled":
                        raise InterruptedError("Processing cancelled by user")

                print(f"[dots.ocr] Processing page {page_idx + 1}/{total_pages}...")

                # Get the image for this page
                origin_image = all_images[page_idx]

                # Process single page using parser's internal method
                result = parser._parse_single_image(
                    origin_image=origin_image,
                    prompt_mode=prompt_mode,
                    save_dir=str(save_dir),
                    save_name=file_prefix,
                    source="pdf",
                    page_idx=page_idx
                )
                result['file_path'] = str(pdf_path_obj)
                new_results.append(result)

                # Update progress after each page
                pages_done = len(completed_pages) + i + 1
                percent = int(10 + (pages_done / total_pages) * 75)
                if progress_store and temp_id:
                    progress_store[temp_id]["current_page"] = pages_done
                    progress_store[temp_id]["percent"] = percent

                # Save job state after each page (for crash recovery)
                save_job_state(save_dir, {
                    "pdf_path": str(pdf_path_obj),
                    "total_pages": total_pages,
                    "completed_pages": completed_pages + remaining_pages[:i+1],
                    "status": "processing"
                })

        print(f"[dots.ocr] Extraction complete, {total_pages} pages total")

        if progress_store and temp_id:
            progress_store[temp_id]["percent"] = 85
            progress_store[temp_id]["current_page"] = total_pages

        # Mark job as complete in state file (will be deleted later)
        save_job_state(save_dir, {
            "pdf_path": str(pdf_path_obj),
            "total_pages": total_pages,
            "completed_pages": list(range(total_pages)),
            "status": "complete"
        })

        # Convert to Scholia format
        content = dots_ocr_to_scholia(save_dir, file_prefix, total_pages)

        return content

    finally:
        os.chdir(original_cwd)


def dots_ocr_to_scholia(save_dir: Path, filename: str, total_pages: int) -> str:
    """
    Convert dots.ocr per-page output to Scholia's canonical format.

    Scholia format:
    - [PAGE n] for page markers
    - [SECTION] # Heading for section headers
    - [FIGURE] for images/figures
    - [TABLE] for tables
    - LaTeX equations preserved as-is or in $...$ delimiters

    Args:
        save_dir: Directory containing dots.ocr page outputs
        filename: Base filename (without extension)
        total_pages: Total number of pages

    Returns:
        Formatted text string
    """
    output_lines = []

    for page_idx in range(total_pages):
        # Add page marker
        output_lines.append(f"\n[PAGE {page_idx + 1}]\n")

        # Try to read the markdown file (primary output)
        md_path = save_dir / f"{filename}_page_{page_idx}.md"
        json_path = save_dir / f"{filename}_page_{page_idx}.json"

        if md_path.exists():
            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()

            # Process markdown content
            processed = process_dots_ocr_markdown(md_content)
            output_lines.append(processed)

        elif json_path.exists():
            # Fallback: read JSON layout and convert
            with open(json_path, "r", encoding="utf-8") as f:
                layout_data = json.load(f)

            if isinstance(layout_data, list):
                for item in layout_data:
                    category = item.get("category", item.get("type", "Text"))
                    text = item.get("text", item.get("content", ""))

                    if category in ["Title", "Section-header"]:
                        output_lines.append(f"\n[SECTION] # {text}\n")
                    elif category in ["Picture", "Figure"]:
                        output_lines.append("\n[FIGURE]\n")
                    elif category == "Table":
                        output_lines.append(f"\n[TABLE]\n{text}\n")
                    elif category == "Equation":
                        # Preserve LaTeX
                        output_lines.append(f"\n{text}\n")
                    else:
                        output_lines.append(f"{text}\n")

    return "\n".join(output_lines)


def process_dots_ocr_markdown(md_content: str) -> str:
    """
    Process dots.ocr markdown to Scholia format.

    Converts:
    - # Heading -> [SECTION] # Heading
    - ![](image) -> [FIGURE]
    - <table>...</table> -> [TABLE] ...
    - Preserves LaTeX equations
    """
    import re

    lines = md_content.split("\n")
    output_lines = []

    for line in lines:
        # Convert headings to section markers
        if line.startswith("# ") or line.startswith("## ") or line.startswith("### "):
            output_lines.append(f"[SECTION] {line}")

        # Convert images to figure markers
        elif re.match(r'!\[.*?\]\(.*?\)', line):
            output_lines.append("[FIGURE]")

        # Convert tables
        elif line.strip().startswith("<table") or line.strip() == "[TABLE]":
            output_lines.append("[TABLE]")

        # Preserve equations (usually in $...$ or $$...$$)
        else:
            output_lines.append(line)

    return "\n".join(output_lines)


def generate_document_folder_name(pdf_path: str, content: str = None) -> str:
    """
    Generate document folder name from PDF filename.

    Expected format: Author_Year_Title.pdf
    Output: Author_Year_Title_Words (first 6 words of title, underscored)

    This is the same logic as marker_extractor.py for consistency.
    """
    import re
    from pathlib import Path

    filename = Path(pdf_path).stem

    # Clean up filename
    # Remove common suffixes like "(1)", "_final", etc.
    filename = re.sub(r'\s*\(\d+\)\s*$', '', filename)
    filename = re.sub(r'_?(final|draft|v\d+)\s*$', '', filename, flags=re.IGNORECASE)

    # Replace spaces with underscores, collapse multiple underscores
    folder_name = re.sub(r'[\s-]+', '_', filename)
    folder_name = re.sub(r'_+', '_', folder_name)
    folder_name = folder_name.strip('_')

    # Truncate if too long (max 80 chars for folder name)
    if len(folder_name) > 80:
        folder_name = folder_name[:80].rsplit('_', 1)[0]

    return folder_name


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--status":
            print(json.dumps(get_setup_status(), indent=2))
        else:
            result = extract_with_dots_ocr(sys.argv[1])
            print(result[:2000])  # Print first 2000 chars
    else:
        print("Usage: python dots_ocr_extractor.py <pdf_path> | --status")
        print("\nStatus:")
        print(json.dumps(get_setup_status(), indent=2))
