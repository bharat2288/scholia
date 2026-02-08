# Metadata & Autotagging

> How Scholia identifies what you're reading and organizes it without manual data entry.

---

## The Problem

You import a PDF. The filename is `10.1080_00131857.2020.1751728.pdf`. What is this? Who wrote it? When? What's it about?

Metadata entry is the most tedious part of building a research library. Every paper needs a title, authors, year, and ideally some tags. Manual entry takes 2-3 minutes per source. Across 200 papers, that's 7+ hours of data entry. Nobody does this, so libraries stay unorganized.

Scholia attacks this problem from three angles: **DOI/ISBN lookup**, **AI-powered suggestion**, and **batch processing**.

---

## DOI Lookup (Crossref)

If a paper has a DOI, you have a near-perfect metadata source. Crossref maintains a database of over 130 million scholarly records.

### How It Works

```
User enters DOI → Clean identifier → Query Crossref API → Parse response → Return structured metadata
```

**Cleaning**: The endpoint accepts DOIs in any format:
- `10.1080/00131857.2020.1751728`
- `https://doi.org/10.1080/00131857.2020.1751728`
- `doi:10.1080/00131857.2020.1751728`

All normalize to the bare DOI before querying.

**Author handling**: Crossref returns authors as `{given: "Andy", family: "Clark"}`. Combined to "Andy Clark" for display.

**Year extraction**: Crossref stores dates inconsistently. The lookup tries fields in priority order: `published-print` → `published-online` → `issued` → `created`. First valid year wins.

**What you get**: Title, authors (list), year, journal/publisher, DOI (confirmed).

---

## ISBN Lookup (Open Library)

For books, ISBN is the equivalent of DOI. Open Library provides free bibliographic data.

### The Indirection Problem

Open Library stores authors as references, not inline data. A book entry says `"authors": [{key: "/authors/OL123A"}]` — you need a second API call to resolve each author's name. The lookup handles this transparently, making N+1 calls (1 for the book + 1 per author).

**Year extraction**: Open Library's `publish_date` field is wildly inconsistent: "2020", "January 2020", "Jan 15, 2020", "2020-01-15". A regex (`\b(1[0-9]{3}|20[0-9]{2})\b`) extracts the 4-digit year from any format.

---

## AI-Powered Suggestion

When there's no DOI or ISBN — or when you want tags and keywords that bibliographic databases don't provide — the AI takes over.

### Strategic Content Sampling

The AI doesn't read the entire document. It samples strategically based on source type:

**Documents (PDFs, EPUBs)**:
- First 2,000 characters (title page, abstract)
- Text around "abstract" heading if found
- Table of contents if detected
- Introduction section
- Last 1,500 characters (references section — reveals topics and related work)

**Web articles**: First 15,000 characters (beginning + end if longer)

**Twitter threads**: Full content + extracted hashtags (threads are short enough to send whole)

**Videos**: Beginning (3,000 chars) + middle (2,000 chars) + end (2,000 chars) — captures intro, core content, and conclusions

This sampling strategy is deliberate. The first pages have the title and authors. The abstract states the topic. The table of contents reveals structure. The references reveal what field the paper belongs to. And the last pages often have keywords that don't appear anywhere else.

### What It Suggests

The AI returns structured metadata with confidence scores:

```json
{
  "title": {"value": "Supersizing the Mind", "confidence": 0.95},
  "authors": {"value": ["Clark, Andy"], "confidence": 0.92},
  "year": {"value": "2008", "confidence": 0.88},
  "keywords": {
    "value": ["extended mind", "distributed cognition", "embodied cognition", "cognitive science"],
    "confidence": 0.85
  },
  "doi": {"value": "10.1093/acprof:oso/9780195333213.001.0001", "confidence": 0.70}
}
```

**Confidence thresholds**: Only fields with confidence ≥ 0.7 are shown. DOI and ISBN require ≥ 0.9 (false positives are worse than missing values for identifiers).

### Keyword Inference

The most valuable part of AI suggestion isn't extracting what's explicitly stated — it's **inferring topics**. A paper might never use the phrase "distributed cognition" in its abstract, but the AI can infer it from the content. The prompt explicitly instructs: "Suggest inferred topics even if not explicitly stated in the document."

This turns every paper into a tagged, searchable entry without the author having used your preferred taxonomy.

### Skip Existing Values

If a source already has a title and the AI suggests the same title, it's omitted from results. No point showing "suggestion: same thing you already have." This keeps the suggestion UI clean — only genuinely new or different values appear.

---

## Batch Processing

### The Workflow

For a library of 50 untagged papers:

1. Open Metadata view
2. Click "Suggest All" → triggers `suggest_metadata_batch()`
3. For each source: sample content → build prompt → call GPT-4o-mini → parse response
4. Review suggestions per source: accept, modify, or dismiss each field
5. Accepted tags and authors are created via batch gluon endpoints

### Why GPT-4o-mini?

Metadata extraction is a structured output task — not a reasoning task. GPT-4o-mini is:
- Fast (~1s per source)
- Cheap (~$0.001 per source)
- Accurate enough for metadata (doesn't need Opus-level reasoning)

At $0.001 per source, processing 200 papers costs $0.20. That's a reasonable price to avoid 7 hours of manual data entry.

---

## How Tags Become Gluons

When the AI suggests keywords and the user accepts them, the frontend calls `/tags/batch` with the list of tag names. For each tag:

1. Normalize (lowercase, no spaces)
2. Get-or-create tag gluon
3. Create source → tag link

If the AI suggests "distributed cognition" for three different papers, all three get linked to the *same* tag gluon. The knowledge graph emerges from metadata — you get cross-document connections for free.

Similarly, when the AI identifies authors, `/people/batch` creates or retrieves person gluons and links them to the source. Author pages accumulate: "Andy Clark" links to every Clark paper in your library.

---

## Design Decisions

### Why Not Auto-Apply?

The AI suggests; the human decides. This is deliberate. Metadata errors compound — a wrong tag pollutes search results, a wrong author creates false connections. The review step adds 30 seconds per source but prevents systematic errors from propagating through your library.

### Why Sample Instead of Full Text?

Sending a 300-page book to GPT-4o-mini would cost more and produce worse results. The model would get lost in the middle content. Strategic sampling gives it exactly the information-dense parts: title page, abstract, TOC, references. These are where metadata *lives* in academic documents.

### Why Separate DOI/ISBN from AI?

DOI/ISBN lookups are deterministic — they either find the record or they don't. AI suggestion is probabilistic — it might get the year wrong. Keeping them separate means you can trust DOI results completely and treat AI results as suggestions. The UI reflects this: DOI results auto-fill; AI results require confirmation.

### Why Store Confidence Scores?

Confidence scores let the UI prioritize what to show. A 0.95 title suggestion gets prominent placement; a 0.71 DOI suggestion gets a "low confidence" warning. This is more informative than binary "found / not found."
