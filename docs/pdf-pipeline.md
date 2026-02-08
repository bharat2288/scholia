# The PDF Pipeline

> From scanned page to searchable, navigable text — why this is harder than it sounds, and how Scholia handles it.

---

## The Problem

Academic PDFs are the worst format for machine reading. A born-digital PDF from a recent journal is fine — the text is embedded, you can copy-paste it. But the moment you encounter:

- **Scanned books** — the "text" is pixels
- **Math-heavy papers** — LaTeX equations rendered as images
- **Complex layouts** — two-column papers, tables with subscripts, figures with inline captions
- **Historical documents** — low-resolution scans, degraded type, marginalia

...standard text extraction breaks down. And if you want an LLM to reason about your reading, you need *good* text. Garbage in, garbage out.

Scholia solves this with a **multi-tier extraction pipeline** backed by a **human-in-the-loop editor** for the long tail of errors.

---

## The Three Tiers

### Tier 1: Quick (pymupdf4llm)

**Speed**: ~0.05 seconds/page | **Quality**: Low-Medium

Rips embedded text directly from the PDF. No OCR, no GPU, no model inference. This is what `pymupdf4llm` does — it parses the PDF's internal text objects and reassembles them into markdown.

**Good for**: Born-digital PDFs with simple layouts (most recent journal articles).

**Fails on**: Scanned documents, equations, complex tables, anything where the "text" is actually an image.

**When to use**: Bulk processing when speed matters more than quality, or quick preview before committing to a slower tier.

### Tier 2: Marker (GPU text extraction)

**Speed**: ~1.5 seconds/page | **Quality**: Medium-High

[Marker](https://github.com/VikParuchuri/marker) is a vision-language model that extracts text from PDF pages. It handles two-column layouts, understands reading order, and produces clean markdown with heading hierarchy.

**Good for**: Most academic papers. Born-digital or lightly scanned. Standard layouts.

**Fails on**: Heavy math (equations come out garbled), tables with subscripts, very old/degraded scans.

**Engineering note**: The Marker model is loaded once and reused across jobs. The initial load takes 2-5 minutes (downloading model weights + GPU warmup), but subsequent jobs start instantly. Force float32 mode ensures compatibility with pre-Ampere GPUs (GTX 10xx/20xx don't support bfloat16).

### Tier 3: dots-ocr (VLM-based OCR)

**Speed**: ~2.5 seconds/page | **Quality**: High

[dots-ocr](https://github.com/ai-forever/dots-ocr) treats each page as an image and uses a vision-language model to "read" it. This is closest to how a human reads — it sees the page visually and produces text, including math notation, table structure, and figure captions.

**Good for**: Scanned books, math-heavy papers, complex tables, anything where layout matters.

**Fails on**: Very long documents (cost/time scales linearly), extremely degraded scans (though still better than Tesseract).

**Engineering notes**:
- **Resume support**: Saves `job_state.json` after each page. If the process crashes on page 47 of 300, it picks up from page 48 on restart. Each page produces its own `.md`, `.jpg`, and `.json` files.
- **Reduced settings**: DPI lowered from 150 to 120 (35% faster), max completion tokens from 24k to 12k. Academic papers rarely need the full capacity.
- **Singleton model**: One model instance shared across all jobs (thread-locked). Avoids the 2-5 minute cold start per document.

---

## Tier Selection

Before processing, an **assessor** pre-scans the first 5 pages and recommends a tier:

| Signal | Detected How | Recommended Tier |
|--------|-------------|-----------------|
| Low text yield (<50 chars/page) | pymupdf extraction attempt | dots-ocr |
| High scanned ratio (image-only pages) | Page content analysis | dots-ocr |
| Math patterns (`$...$`, `\frac{}{}`, `\int`) | Regex + Unicode math detection | dots-ocr |
| Equation images (wide, short bounding boxes) | Aspect ratio heuristic | dots-ocr |
| Complex tables with math | Tab-separated columns + math patterns | dots-ocr |
| Standard text-based | Adequate text yield, no special patterns | marker |

The user can override the recommendation. You might choose Marker for a math paper if you only need the prose sections.

---

## The Scholia Format

All three extractors produce the same intermediate format:

```
[PAGE 1]

[SECTION] # Introduction

Body text of the introduction. Regular paragraphs flow naturally.

[SECTION] ## 1.1 Background

More text here. Inline citations like (Smith, 2020) are preserved.

[FIGURE]
[CAPTION] Figure 1: Distribution of responses across conditions

[TABLE]
| Header 1 | Header 2 | Header 3 |
|----------|----------|----------|
| Value    | Value    | Value    |

[PAGE 2]
...
```

**Markers**:
- `[PAGE n]` — Page boundaries (for citation: "see page 12")
- `[SECTION] # Heading` — Section boundaries with heading levels (`#` = H1, `##` = H2, etc.)
- `[FIGURE]` / `[CAPTION]` — Figure placeholders with captions
- `[TABLE]` — Table markers (content follows as markdown table)

This format is what the Reader renders from, what the search index is built on, and what the LLM receives as context. Getting it right matters — a missing `[SECTION]` marker means a heading renders as body text; a wrong heading level breaks the table of contents hierarchy.

---

## RunPod: Remote GPU Processing

### Why Remote GPUs?

dots-ocr is GPU-intensive. A 300-page book takes ~12.5 minutes on an RTX 3070 Ti. That's fine for one book, but if you're processing a reading list of 20 papers, you're looking at 4+ hours of local GPU time — during which you can't use your GPU for anything else.

RunPod provides on-demand cloud GPUs. Spin up an A4000 or A5000, process your queue, shut it down. You pay per minute, and you get access to better GPUs than what's in your desktop.

### How It Works

The workflow is SSH/SCP-based (using paramiko for Windows compatibility):

```
1. Upload PDF to /workspace/input/ on RunPod network volume
2. Multi-pod coordinator on the pod picks up the job
3. Poll /workspace/status.json for progress
4. Download completed output from /workspace/output/{folder}/
5. Finalize locally (rebuild extracted text + crop figures)
```

**Network volumes** persist across pod restarts. Your PDFs and outputs survive even if the pod is destroyed. The Texas datacenter (US-TX-3) is preferred — better GPU availability than Montreal.

**Multi-pod coordination**: A `coordinator.py` script on the pod manages job distribution. Multiple pods can attach to the same network volume and process different PDFs in parallel. Lock files in `/workspace/processing/` prevent two pods from grabbing the same job.

### The Finalization Step

RunPod produces page-level outputs (one `.md` + `.jpg` + `.json` per page). The finalization step:
1. Downloads all page files
2. Rebuilds a single extracted text file from page markdowns
3. Crops figures from page images using bounding box data
4. Imports the result into the Scholia library

This split (remote extraction → local finalization) keeps the expensive GPU work on the cloud while doing lightweight post-processing locally.

---

## Section Editor: The Human-in-the-Loop

No extraction pipeline is perfect. OCR makes mistakes. Heading detection misses some sections. The Section Editor is where you fix these.

### The Interface

Three panes:

| Left (25%) | Center (45%) | Right (30%) |
|------------|-------------|-------------|
| PDF viewer (original) | Raw text editor with syntax highlighting | Issues panel + section preview |

You see the original PDF on the left, the extracted text in the middle, and a live preview of the parsed structure on the right. Edit the text, and the section hierarchy updates in real-time.

### What It Detects

The editor automatically scans for structural issues:

- **Missing heading levels**: `[SECTION]` without a `#` — the marker is there but the heading level is missing
- **Potential headings**: Short lines that look like headings but weren't marked. Scored by heuristics:
  - Isolated by blank lines
  - Numbered patterns (`1.`, `(a)`, `iv.`)
  - Common heading words (Abstract, Introduction, Methods, Results, Discussion, Conclusion)
  - ALL CAPS styling
  - Title Case (60%+ words capitalized)
  - Short length (<80 characters)

Each detected issue is clickable — it jumps you to the exact line in the editor.

### Quick Fixes

- **Ctrl+1 through Ctrl+6**: Set heading level on the current line (converts body text to `[SECTION] # Heading` or changes the heading level)
- **Level picker**: Click "Fix" on an issue → dropdown with levels 1-6
- **Ctrl+S**: Save changes and re-import into the library

### Why This Matters

The Section Editor closes the gap between automated extraction and usable text. A typical workflow:

1. Process a book with dots-ocr → 95% of sections detected correctly
2. Open Section Editor → see 12 flagged issues
3. Fix 8 of them in 2 minutes (quick Ctrl+number keys)
4. Ignore 4 (false positives)
5. Save → book is now perfectly structured for reading and LLM context

Without this step, you'd either accept imperfect extraction (broken TOC, missing sections) or manually edit raw text files. The Section Editor makes the fix workflow fast enough that you actually do it.

---

## Design Philosophy

### Progressive Refinement

The pipeline is built around the idea that **perfection isn't the starting point — it's the destination**.

Quick tier gets you something in seconds. Marker gets you something good in minutes. dots-ocr gets you something excellent in tens of minutes. The Section Editor gets you something perfect in a few more minutes of human effort. You choose how far down the quality ladder to go based on how important the document is.

### Resume Everywhere

Long-running processes crash. Power goes out, GPUs overheat, processes get killed. The pipeline is designed to survive interruption:

- Processing jobs persist in SQLite (survive server restarts)
- dots-ocr saves per-page state (resume from crash point)
- RunPod network volumes survive pod destruction
- Progress is tracked in-memory and synced to DB

### Duplicate Prevention

Re-processing a document you've already processed wastes time. Three detection strategies:

1. **SHA256 hash match** — exact file duplicate (most reliable)
2. **Folder name prediction** — parse filename patterns (Author_Year_Title) and check for existing folder
3. **Fuzzy author+year match** — query DB for matching year + overlapping author words

### Tier Priority

If you process a document with Marker and later reprocess with dots-ocr, the higher-quality extraction wins. But the reverse isn't true — reprocessing a dots-ocr document with Marker won't downgrade it. The UPSERT logic checks `extraction_method` in metadata and only upgrades.
