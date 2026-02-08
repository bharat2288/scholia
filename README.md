# Scholia

> **σχόλια** (scholia) — Ancient Greek for "marginal notes." In classical scholarship, scholia were explanatory notes written in manuscript margins by generations of readers. This is where your marginalia live.

A local-first research knowledge system for reading, annotating, and connecting ideas across PDFs and documents.

![Status](https://img.shields.io/badge/status-alpha-orange)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## Why I Built This

I was a heavy [RemNote](https://www.remnote.com/) user during my PhD, and I owe a real debt to that tool — its model of bidirectional linking, highlights-as-objects, and intercitational note-taking shaped how I think about knowledge management. Scholia is built on that foundation.

But my workflow kept bumping against edges:

- **LLM integration behind a quota wall.** RemNote's AI features require a subscription with limited credits. I'm already paying for API access directly — I'd rather route that into my own reader with no throttling, full model choice, and custom prompting.
- **Research doesn't live in one format.** I read PDFs, but I also consume web articles, Twitter threads, and YouTube lectures. I wanted a single system that normalizes all of these into the same reading and annotation experience.
- **Preset analytical moves.** Over years of academic reading, I developed recurring ways of engaging with texts — summarize, theorize, critique, extract claims. I wanted those baked into the tool as one-click presets, not copy-pasted into a separate chat window.
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
- **Web clipper**: Save articles with preserved formatting
- **Tweet/thread clipper**: Capture Twitter threads via URL
- **Video clipper**: YouTube transcripts with chapters and timestamps

### 🤖 Built-in LLM Chat
- Chat with Claude/GPT about what you're reading
- "Council" mode: multiple models weigh in on your question
- Save AI responses as notes

### ⚙️ PDF Processing Pipeline
- Multi-tier extraction: Marker → dots-ocr → Tesseract
- Batch processing with job persistence
- Figure extraction with bounding box cropping
- Section Editor for fixing OCR errors

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         SCHOLIA                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  INGESTION                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │   PDF    │  │   EPUB   │  │   Web    │  │  Video   │    │
│  │ Marker/  │  │ ebooklib │  │trafilatura│  │  yt-dlp  │    │
│  │ dots-ocr │  │          │  │          │  │          │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       └─────────────┴─────────────┴─────────────┘           │
│                          ↓                                   │
│                 ┌────────────────┐                          │
│                 │ Unified Source │                          │
│                 │    Storage     │                          │
│                 └───────┬────────┘                          │
│                         ↓                                    │
│  STORAGE (SQLite)                                           │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ sources │ sections │ gluons │ highlights │ *_fts      │ │
│  └────────────────────────────────────────────────────────┘ │
│                         ↓                                    │
│  FRONTEND (React + Tailwind)                                │
│  ┌──────────┬─────────────────────┬────────────────────┐   │
│  │ Library  │      Reader         │     Knowledge      │   │
│  │          │  ToC│Content│Sidebar│  Gluons│Search     │   │
│  └──────────┴─────────────────────┴────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Tech Stack:**
- **Backend**: FastAPI + SQLite (aiosqlite) + FTS5
- **Frontend**: React 18 + Vite + Tailwind CSS
- **PDF Extraction**: Marker, dots-ocr, PyMuPDF, Tesseract
- **Web/Video**: trafilatura, yt-dlp

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
│   ├── server.py           # FastAPI application
│   ├── database.py         # SQLite + migrations
│   ├── routers/            # API endpoints
│   │   ├── sources.py      # Unified source CRUD
│   │   ├── reading.py      # Content delivery
│   │   ├── highlights.py   # Annotation system
│   │   ├── gluons.py       # Notes + linking
│   │   ├── chat.py         # LLM integration
│   │   └── processor.py    # PDF processing
│   └── services/           # Business logic
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Library/    # Source browsing
│   │   │   ├── Reader/     # Reading interface
│   │   │   ├── Knowledge/  # Gluon browsing
│   │   │   └── Processor/  # PDF processing UI
│   │   ├── stores/         # Zustand state
│   │   └── hooks/          # React hooks
│   └── index.html
│
└── data/                   # SQLite database + extracted content (gitignored)
```

---

## Status

🔬 **Personal research tool** — I built this for my own academic workflow and I'm sharing it in case it's useful to others.

- Issues welcome as feedback, but no guarantees on response time
- PRs unlikely to be reviewed (I maintain this for my own use)
- Fork freely if you want to take it in a different direction

This is alpha software. Things may break. The database schema may change.

---

## Roadmap

- [x] Core reading + highlighting
- [x] Web/tweet/video clipping
- [x] Gluon system (notes + linking)
- [x] LLM chat integration
- [ ] Research Sessions (multi-document AI conversations)
- [ ] Browser extension for quick capture

---

## Acknowledgments

- Deeply influenced by [RemNote](https://www.remnote.com/) — its model of bidirectional linking and highlights-as-objects shaped this project's design
- PDF extraction powered by [Marker](https://github.com/VikParuchuri/marker) and [dots-ocr](https://github.com/ai-forever/dots-ocr)

---

## License

MIT
