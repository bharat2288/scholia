# Scholia

> **σχόλια** (scholia) — Ancient Greek for "marginal notes." In classical scholarship, scholia were explanatory notes written in manuscript margins by generations of readers. This is where your marginalia live.

A local-first research knowledge system for reading, annotating, and connecting ideas across PDFs, web articles, Twitter threads, and video transcripts.

![Status](https://img.shields.io/badge/status-alpha-orange)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## Demos

### Library
Browse, search, filter, and sort your sources — PDFs, web articles, tweets, video transcripts — in card or row view.

https://github.com/user-attachments/assets/2a929a97-f6c0-4123-9274-feb1dab1cb50

### Reader + Highlights
Three-pane reading interface with Table of Contents navigation, multi-color highlighting, and annotations.

https://github.com/user-attachments/assets/d237d5c9-4f59-4bb3-ac01-b52b7dc5b397

### Reader + AI Chat
Per-document AI conversations with history, analytical presets, model selection, and Council mode.

https://github.com/user-attachments/assets/66ad38e5-0cf3-4643-946a-1bf4e7354b95

### Knowledge Hub
Cross-document knowledge browsing — notes, highlights, tags, people, journal, and chat history.

https://github.com/user-attachments/assets/c2735cc3-e311-4534-b1a4-11adb04ecf2b

### Research Sessions
Multi-document AI research with agentic tool use, evidence traces, and source cross-referencing.

https://github.com/user-attachments/assets/aff07efd-4ed3-448c-9b8d-4cac4c34c48e

### Section Editor
Three-pane editing with PDF reference, syntax-highlighted markers, and structure analysis.

https://github.com/user-attachments/assets/38a8b6c1-f0de-4f34-b6f3-f4023ff44cf2

---

## Why I Built This

I was a heavy [RemNote](https://www.remnote.com/) user during my PhD, and I owe a real debt to that tool — its model of bidirectional linking, highlights-as-objects, and intercitational note-taking shaped how I think about knowledge management. Scholia is built on that foundation.

But my workflow kept bumping against edges:

- **LLM integration behind a quota wall.** RemNote's AI features require a subscription with limited credits. I'm already paying for API access directly — I'd rather route that into my own reader with no throttling, full model choice, and custom prompting.
- **Research doesn't live in one format.** I read PDFs, but I also consume web articles, Twitter threads, and YouTube lectures. I wanted a single system that normalizes all of these into the same reading and annotation experience.
- **Preset analytical moves.** Over years of academic reading, I developed recurring ways of engaging with texts — summarize, analyze, critique, extract claims. I wanted those baked into the tool as one-click presets, not copy-pasted into a separate chat window.
- **Extensibility.** I built a [RemNote plugin](https://github.com/bharat2288/notes-processor) and found myself doing ongoing technical work to maintain it. At that point, I decided to channel that energy into building exactly what I wanted.

---

## Features

### 📖 Unified Reading Experience
- Import PDFs and EPUBs into a single library
- Three-pane reader: Table of Contents | Content | Sidebar
- Section-based navigation with reading position memory
- Rich text rendering (bold, italic, tables, math, code blocks)

### 🎨 Offset-Based Highlighting
- Multi-color highlights (yellow, blue, green, pink)
- Character-offset storage — no text-matching fragility
- Attach notes to any highlight
- Click highlight in sidebar → jump to position

### 🔗 Everything is Linkable (Gluons)
- Create notes with `[[references]]` and `##tags`
- Bidirectional backlinks show what links to what
- Cross-document knowledge graph emerges naturally
- Full-text search across all content

### 🌐 Multi-Source Capture
- **Web clipper**: Save articles with preserved formatting (trafilatura)
- **Tweet/thread clipper**: Capture Twitter threads and articles via URL (FxTwitter API)
- **Video clipper**: YouTube transcripts with chapter detection and timestamps
- **WhatsApp capture**: Send notes via WhatsApp webhook — auto-classified and tagged by Claude

### 🤖 Built-in LLM Chat
- Chat with Claude/GPT about what you're reading
- "Council" mode: three independent models deliberate, Claude synthesizes
- Save AI responses as notes
- Per-query cost tracking

### 🧪 Analytical Presets
- One-click preset prompts: summarize, analyze, critique, concept-map, explain, quotables, research questions
- Source-type-aware filtering (different presets surface for documents vs. web vs. video)
- Full-document vs. selection variants
- Analyze mode with three sub-modes: Comprehensive, Reverse, Directed
- Create custom presets alongside system defaults

### 🔬 Research Sessions
- Multi-document AI conversations across your library
- Add multiple sources to a session as context
- Agentic RLM (Research Language Model) with tool use — the model can search, retrieve, and cross-reference your sources
- Streaming responses with visible tool call feed

### 📚 Metadata Management
- DOI lookup via Crossref, ISBN lookup via Open Library
- AI-powered metadata suggestion (title, author, year, tags)
- Batch metadata suggestion across your library

### ⚙️ PDF Processing Pipeline
- Multi-tier extraction: Marker → dots-ocr → Tesseract
- Batch processing with job persistence
- Optional GPU acceleration via RunPod (remote pod management)
- Figure extraction with bounding box cropping
- Section Editor for fixing OCR errors

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                            SCHOLIA                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  INGESTION                                                       │
│  ┌────────┐ ┌────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐    │
│  │  PDF   │ │  EPUB  │ │   Web    │ │ Video  │ │ WhatsApp │    │
│  │Marker/ │ │ebooklib│ │trafilat. │ │ yt-dlp │ │ webhook  │    │
│  │dots-ocr│ │        │ │FxTwitter │ │        │ │          │    │
│  └───┬────┘ └───┬────┘ └────┬─────┘ └───┬────┘ └────┬─────┘    │
│      └──────────┴───────────┴────────────┴───────────┘          │
│                            ↓                                     │
│                  ┌─────────────────┐                             │
│                  │  Unified Source │                             │
│                  │     Storage     │                             │
│                  └────────┬────────┘                             │
│                           ↓                                      │
│  STORAGE (SQLite + FTS5)                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ sources │ sections │ gluons │ highlights │ conversations │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           ↓                                      │
│  LLM LAYER                                                      │
│  ┌────────────┬───────────────┬──────────────────────────┐      │
│  │ Chat (1:1) │ Council (n:1) │ RLM Agent (tool-using)   │      │
│  │            │ 3 models +    │ search, retrieve, cross-  │      │
│  │            │ synthesizer   │ reference across sources  │      │
│  └────────────┴───────────────┴──────────────────────────┘      │
│                           ↓                                      │
│  FRONTEND (React + TanStack Query + Zustand)                    │
│  ┌────────┬──────────────────┬───────────┬───────────────┐      │
│  │Library │     Reader       │ Knowledge │   Research    │      │
│  │        │ ToC│Content│Side │ Gluons    │   Sessions    │      │
│  └────────┴──────────────────┴───────────┴───────────────┘      │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Tech Stack:**
- **Backend**: FastAPI + SQLite (aiosqlite) + FTS5
- **Frontend**: React 18 + Vite + Tailwind CSS + TanStack Query + Zustand
- **LLM Integration**: Anthropic SDK, OpenAI SDK (multi-provider)
- **PDF Extraction**: Marker, dots-ocr, PyMuPDF, Tesseract
- **Web/Video**: trafilatura, yt-dlp, FxTwitter API

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- (Optional) Tesseract OCR for fallback extraction

### Installation

```bash
# Clone the repository
git clone https://github.com/bharat2288/scholia.git
cd scholia

# Backend setup
cd backend
python -m venv venv
.\venv\Scripts\activate  # Windows
# source venv/bin/activate  # Mac/Linux
pip install -r requirements.txt

# Frontend setup
cd ../frontend
npm install
```

### Running

```bash
# Terminal 1: Backend (port 8200)
cd backend
.\venv\Scripts\activate
python -m uvicorn server:app --reload --port 8200

# Terminal 2: Frontend (port 5176)
cd frontend
npm run dev
```

Open http://localhost:5176

### Configuration

Create a `.env` file in the `backend/` folder for LLM features:

```env
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here  # optional, for council mode
```

The frontend defaults to `http://localhost:8200` for the API. Override with `VITE_API_BASE` in a `.env` file in the `frontend/` folder if needed.

---

## Project Structure

```
scholia/
├── backend/
│   ├── server.py              # FastAPI application
│   ├── database.py            # SQLite + migrations
│   ├── routers/               # API endpoints
│   │   ├── sources.py         # Unified source CRUD + clipping
│   │   ├── reading.py         # Content delivery + position tracking
│   │   ├── highlights.py      # Offset-based annotation
│   │   ├── gluons.py          # Notes, tags, linking, backlinks
│   │   ├── chat.py            # Single-model LLM chat
│   │   ├── council.py         # Multi-model council + presets
│   │   ├── sessions.py        # Research sessions + RLM agent
│   │   ├── processor.py       # PDF processing pipeline
│   │   ├── runpod.py          # Remote GPU pod management
│   │   ├── metadata_lookup.py # DOI/ISBN lookup
│   │   └── whatsapp.py        # WhatsApp webhook capture
│   └── services/              # Business logic
│       ├── chat/              # Chat service + config
│       ├── council/           # Council service + preset definitions
│       ├── lit_engine/        # PDF extraction (marker, dots-ocr, epub)
│       ├── rlm_agent.py       # Agentic research model with tools
│       ├── web_clipper.py     # Web article extraction
│       ├── tweet_clipper.py   # Twitter/X thread capture
│       ├── video_clipper.py   # YouTube transcript extraction
│       └── metadata_ai.py    # AI-powered metadata suggestion
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Library/       # Source browsing + import
│   │   │   ├── Reader/        # Reading interface + chat sidebar
│   │   │   ├── Editor/        # Section editor for OCR fixes
│   │   │   ├── Knowledge/     # Gluon browsing + search
│   │   │   ├── Gluon/         # Individual gluon view
│   │   │   ├── Research/      # Research sessions UI
│   │   │   ├── Processor/     # PDF processing + RunPod UI
│   │   │   └── common/        # Shared components (modals, inputs)
│   │   ├── stores/            # Zustand state management
│   │   ├── hooks/             # TanStack Query API hooks
│   │   └── config.js          # API base URL configuration
│   └── index.html
│
└── data/                      # SQLite database + extracted content (gitignored)
```

---

## Status

🔬 **Personal research tool** — I built this for my own academic workflow and I'm sharing it in case it's useful to others.

- Issues welcome as feedback, but no guarantees on response time
- PRs unlikely to be reviewed (I maintain this for my own use)
- Fork freely if you want to take it in a different direction

This is alpha software. Things may break. The database schema may change.

---

## Deep Dives

Detailed documentation on design decisions and architecture:

- **[Chat vs. Research Sessions](docs/chat-vs-research.md)** — Stateless Q&A vs. agentic multi-source investigation
- **[The PDF Pipeline](docs/pdf-pipeline.md)** — Multi-tier extraction, RunPod GPU offloading, Section Editor
- **[Gluons: The Knowledge Graph](docs/gluons.md)** — Bidirectional linking, highlights-as-objects, and the `[[reference]]` system
- **[Metadata & Autotagging](docs/metadata-autotagging.md)** — DOI/ISBN lookup, AI-powered suggestion, batch processing
- **[Analytical Presets](docs/presets.md)** — One-click analytical moves with structured prompts
- **[Council Mode](docs/council-mode.md)** — Multi-model deliberation and synthesis

---

## Roadmap

- [x] Core reading + highlighting
- [x] Web/tweet/video clipping
- [x] Gluon system (notes + linking)
- [x] LLM chat integration
- [x] Analytical presets (summarize, analyze, critique, etc.)
- [x] Research Sessions (multi-document AI with tool use)
- [x] Metadata management (DOI/ISBN lookup, AI suggestion)
- [x] WhatsApp capture
- [ ] Browser extension for quick capture

---

## Acknowledgments

- Deeply influenced by [RemNote](https://www.remnote.com/) — its model of bidirectional linking and highlights-as-objects shaped this project's design
- PDF extraction powered by [Marker](https://github.com/VikParuchuri/marker) and [dots-ocr](https://github.com/ai-forever/dots-ocr)

---

## License

MIT
