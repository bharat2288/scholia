# Deep Dives

Design decisions and architectural documentation for Scholia's core systems.

---

### LLM Integration

- **[Chat vs. Research Sessions](chat-vs-research.md)** — Two modes of engagement: stateless Q&A for quick questions, agentic tool-using loop for deep investigation across multiple sources
- **[Analytical Presets](presets.md)** — One-click analytical moves (summarize, theorize, critique, etc.) with source-type-aware filtering and carefully structured prompts
- **[Council Mode](council-mode.md)** — Multi-model deliberation with parallel execution and chairman synthesis

### Infrastructure

- **[The PDF Pipeline](pdf-pipeline.md)** — Multi-tier extraction (quick → Marker → dots-ocr), RunPod GPU offloading, and the Section Editor for human-in-the-loop correction
- **[Metadata & Autotagging](metadata-autotagging.md)** — DOI/ISBN lookup, AI-powered suggestion with strategic content sampling, batch processing

### Knowledge System

- **[Gluons](gluons.md)** — The knowledge graph: highlights, notes, tags, and references as uniform objects with bidirectional linking
