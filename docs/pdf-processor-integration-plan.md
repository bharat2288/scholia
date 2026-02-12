# PDF Processor Integration Plan

## Overview

Port Lit Processor's PDF processing workflow to Scholia, replacing PyMuPDF/Tesseract with **Marker** as Tier 1 and keeping **dots-ocr** as Tier 2. Uses Scholia's existing storage structure and database.

## Current State

### Lit Processor (Source)
- **Location**: `C:\Users\bhara\dev\lit-processor`
- **Backend**: FastAPI on port 8100
- **Frontend**: React + Vite on port 5175
- **Extraction Tiers**: PyMuPDF, Tesseract, dots.ocr
- **Storage**: `C:\Users\bhara\dev\lit-processor\output` (LIT-Author_Year_Title.txt format)

### Scholia (Target)
- **Location**: `C:\Users\bhara\dev\scholia`
- **Backend**: FastAPI on port 8000
- **Frontend**: React + Vite on port 5173
- **Current Extraction**: Basic PyMuPDF in `services/lit_engine/pdf_extractor.py`
- **Storage**: `data/documents/{Author_Year_Title}/{Author_Year_Title}--{method}/`

## New Extraction Tiers

| Tier | Tool | Use Case | Speed | When to Use |
|------|------|----------|-------|-------------|
| **Tier 1** | Marker | Text-heavy PDFs, clean layouts | ~20-40s | 80%+ text coverage, no complex math |
| **Tier 2** | dots-ocr | Scanned PDFs, equations, tables | ~2.5s/page | Scanned, math-heavy, complex layouts |

## Implementation Tasks

### Phase 1: Backend - Processing Pipeline

#### 1.1 Create `backend/routers/processor.py`

New router for PDF processing workflow:

```python
# Endpoints:
POST /processor/assess       # Upload PDF, get tier recommendation
POST /processor/process      # Start processing with selected tier
GET  /processor/status/{id}  # Poll processing status
POST /processor/cancel/{id}  # Cancel processing
GET  /processor/queue        # Get queue status (for dots-ocr GPU queue)
```

#### 1.2 Create `backend/services/lit_engine/assessor.py`

Port from Lit Processor with modifications:
- Replace "pymupdf" recommendation with "marker"
- Remove "tesseract" tier
- Keep assessment logic (text yield, math detection, table detection)

```python
def assess_pdf(pdf_path: str) -> dict:
    """
    Returns:
        recommendation: "marker" | "dots-ocr"
        reason: str
        page_count: int
        time_estimates: {"marker": float, "dots-ocr": float}
        signals: {avg_text_per_page, scanned_ratio, math_signals, has_tables, ...}
    """
```

#### 1.3 Create `backend/services/lit_engine/marker_extractor.py`

New Marker extraction pipeline:

```python
def extract_with_marker(pdf_path: str, progress_callback=None) -> str:
    """
    Extract text using Marker, convert to Scholia format.

    Returns:
        Formatted text with [PAGE n], [SECTION], [FIGURE], etc. markers
    """
    # 1. Run Marker extraction
    from marker.converters.pdf import PdfConverter
    ...
    markdown = converter(pdf_path).markdown

    # 2. Convert Marker markdown to Scholia format
    return marker_to_scholia(markdown)


def marker_to_scholia(markdown: str) -> str:
    """
    Convert Marker output to Scholia format.

    Transformations:
    - <span id="page-X-Y"> -> [PAGE n+1]
    - # Heading -> [SECTION] # Heading
    - ## Subheading -> [SECTION] ## Subheading
    - ![...](image.jpg) -> [FIGURE]
    - | Table | -> [TABLE] + content
    """
```

#### 1.4 Integrate dots-ocr pipeline

Port `backend/services/dots_ocr.py` from Lit Processor:
- Keep GPU queue management
- Update output path to Scholia's document structure
- Keep resume support for long jobs

#### 1.5 Create `backend/services/lit_engine/formatter.py`

Unified output formatter:
- Takes raw extraction from either tier
- Produces consistent Scholia format
- Handles figure pre-cropping

### Phase 2: Backend - Queue & Progress

#### 2.1 Progress Store

In-memory progress tracking:

```python
# backend/services/progress_store.py
progress_store: Dict[str, ProcessingStatus] = {}

class ProcessingStatus:
    status: str  # "assessing" | "queued" | "processing" | "complete" | "error" | "cancelled"
    stage: str   # "loading" | "extracting" | "formatting" | "done"
    current_page: int
    total_pages: int
    percent: int
    error: Optional[str]
    queue_position: Optional[int]
    output_path: Optional[str]
```

#### 2.2 GPU Queue Worker

For dots-ocr (single job at a time):

```python
# backend/services/gpu_queue.py
gpu_queue: queue.Queue[GPUJob] = queue.Queue()

def gpu_worker():
    """Process dots-ocr jobs one at a time."""
    while running:
        job = gpu_queue.get(timeout=1.0)
        process_dots_ocr(job)
```

### Phase 3: Frontend - PDF Processor Page

#### 3.1 Create `frontend/src/components/Processor/`

New page/component structure:

```
frontend/src/components/Processor/
├── Processor.jsx       # Main page component
├── Processor.css
├── DropZone.jsx        # Drag-drop upload area
├── DropZone.css
├── FileCard.jsx        # Individual file status card
├── FileCard.css
└── FileQueue.jsx       # Queue list component
```

#### 3.2 Processor.jsx Features

- Drag-and-drop PDF upload (multiple files)
- Automatic assessment on upload
- Tier selection (Marker recommended, dots-ocr available)
- "Process" and "Process All" buttons
- Progress bars with page counts
- Queue position display for dots-ocr jobs
- Cancel button
- Completion status with link to Library

#### 3.3 State Management

```javascript
const [files, setFiles] = useState([])
// Each file: {
//   id, name, status, assessment, selectedTier,
//   progress, queuePosition, result, error
// }

// Poll backend for status updates every 500ms
```

### Phase 4: Integration

#### 4.1 Add route to App.jsx

```javascript
<Route path="/processor" element={<Processor />} />
```

#### 4.2 Add navigation link

In Library or header:
```jsx
<Link to="/processor">Process PDFs</Link>
```

#### 4.3 Auto-import to Library

After processing completes:
1. Files saved to `data/documents/{Author_Year_Title}/`
2. Database entry created automatically
3. User sees "View in Library" link

### Phase 5: Storage Integration

#### 5.1 Output Path Structure

```
data/documents/
└── {Author_Year_Title}/
    ├── {Author_Year_Title}.pdf           # Original PDF (copied)
    └── {Author_Year_Title}--marker/      # OR --dots-ocr/
        ├── {name}--marker--extracted.txt
        ├── {name}_page_0.json            # (dots-ocr only)
        ├── {name}_page_0.jpg             # (dots-ocr only)
        └── {name}--figure_0_0.jpg        # Pre-cropped figures
```

#### 5.2 Database Auto-Insert

After successful processing:

```python
# Insert document record
await db.execute("""
    INSERT INTO documents (id, title, author, year, ...)
    VALUES (?, ?, ?, ?, ...)
""")

# Parse sections from extracted text
sections = _parse_sections(content, doc_id)
for section in sections:
    await db.execute("INSERT INTO sections ...")
```

## File Changes Summary

### New Files

| File | Purpose |
|------|---------|
| `backend/routers/processor.py` | Processing API endpoints |
| `backend/services/lit_engine/assessor.py` | PDF quality assessment |
| `backend/services/lit_engine/marker_extractor.py` | Marker extraction + conversion |
| `backend/services/lit_engine/formatter.py` | Output normalization |
| `backend/services/progress_store.py` | In-memory progress tracking |
| `backend/services/gpu_queue.py` | dots-ocr job queue |
| `frontend/src/components/Processor/Processor.jsx` | Main processor page |
| `frontend/src/components/Processor/DropZone.jsx` | Drag-drop upload |
| `frontend/src/components/Processor/FileCard.jsx` | File status card |
| `frontend/src/components/Processor/FileQueue.jsx` | Queue display |
| `frontend/src/components/Processor/*.css` | Styling |

### Modified Files

| File | Changes |
|------|---------|
| `backend/main.py` | Add processor router, GPU worker lifecycle |
| `frontend/src/App.jsx` | Add /processor route |
| `frontend/src/components/Library/Library.jsx` | Add "Process PDFs" link |

## Dependencies

### Backend (add to requirements.txt)

```
marker-pdf>=1.0.0
unidecode
```

### Frontend (existing, no changes needed)

React, Vite already in place.

## API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/processor/assess` | Upload PDF, get assessment |
| POST | `/processor/process` | Start processing |
| GET | `/processor/status/{id}` | Get job status |
| POST | `/processor/cancel/{id}` | Cancel job |
| GET | `/processor/queue` | Get queue status |

## Notes

1. **No Tesseract**: Marker handles most PDFs well; dots-ocr handles the rest
2. **Marker as default**: Fast enough (~20-40s) for interactive use
3. **GPU queue**: Only dots-ocr uses GPU; one job at a time prevents VRAM issues
4. **Resume support**: dots-ocr jobs can resume after interruption
5. **Storage is Scholia's**: All output goes to `data/documents/`, not Lit Processor
6. **Database auto-insert**: Processed files automatically appear in Library
