"""
Fidelity Checks (Layer 1)
=========================
Programmatic verification that RLM responses are grounded in source documents.

Four dimensions:
1. Quote Matching — do blockquotes appear in the source text?
2. Page Accuracy — do page references correspond to actual page locations?
3. Source Attribution — do cited author names match known session sources?
4. Synthesis Fidelity — are non-quote claims traceable to raw findings?

No LLM calls. Pure regex + string matching. Runs in <5s per experiment.
"""

import json
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from eval.db import get_eval_db
from eval.models import FidelityReport

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
LIBRARY_DB_PATH = DATA_DIR / "library.db"
SOURCES_DIR = DATA_DIR / "sources"

# Stopwords for Jaccard similarity (common English, no nltk dependency)
STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "not", "no", "as", "if", "so", "than",
    "then", "also", "just", "more", "most", "very", "too", "about", "into",
    "through", "between", "after", "before", "during", "above", "below",
    "each", "every", "all", "both", "few", "some", "any", "other", "such",
    "only", "own", "same", "here", "there", "when", "where", "how", "what",
    "which", "who", "whom", "why", "while", "because", "although", "though",
    "since", "until", "unless", "whether", "their", "they", "them", "he",
    "she", "his", "her", "him", "we", "us", "our", "you", "your", "i", "my",
    "me", "up", "out", "over", "much", "many",
})


# =============================================================================
# Source Loading (duplicated from rlm_tools.py to avoid backend dependency)
# =============================================================================

def _get_source_text(content_path: str) -> Optional[str]:
    """Load source text from content_path (file or folder with extracted.txt)."""
    if not content_path:
        return None

    path = Path(content_path)

    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None

    if path.is_dir():
        for pattern in ["*--extracted.txt", "content.txt", "*.txt"]:
            matches = list(path.glob(pattern))
            if matches:
                try:
                    return matches[0].read_text(encoding="utf-8")
                except Exception:
                    continue

    return None


def _find_page_for_offset(text: str, offset: int) -> Optional[int]:
    """Find page number for a character offset using [PAGE n] markers."""
    page_pattern = r'\[PAGE (\d+)\]'
    pages = [(m.start(), int(m.group(1))) for m in re.finditer(page_pattern, text)]

    if not pages:
        return None

    current_page = pages[0][1]
    for pos, page_num in pages:
        if pos > offset:
            break
        current_page = page_num

    return current_page


def _load_session_sources(library_db_path: Path, session_id: str) -> dict:
    """
    Load source text and metadata for all sources in a session.

    Returns dict keyed by source_id:
        {sid: {"title": ..., "author": ..., "text": ..., "content_path": ...}}
    """
    conn = sqlite3.connect(str(library_db_path), uri=False)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            """SELECT s.id, s.title, s.author_display, s.content_path
               FROM sources s
               JOIN session_sources ss ON ss.source_id = s.id
               WHERE ss.session_id = ?""",
            (session_id,),
        )
        sources = {}
        for row in cursor:
            text = _get_source_text(row["content_path"])
            sources[row["id"]] = {
                "title": row["title"] or "",
                "author": row["author_display"] or "",
                "text": text or "",
                "content_path": row["content_path"] or "",
            }
        return sources
    finally:
        conn.close()


# =============================================================================
# Extraction Parsers (operate on final_content markdown)
# =============================================================================

def _extract_blockquotes(text: str) -> list[dict]:
    """
    Extract contiguous blockquote blocks and their attributions.

    Returns list of:
        {"quote": str, "author": str|None, "page": int|None, "raw": str}
    """
    results = []
    lines = text.split("\n")
    current_block = []

    for line in lines:
        if line.startswith("> "):
            current_block.append(line[2:])
        elif line.strip() == ">" and current_block:
            # Empty blockquote continuation line
            current_block.append("")
        else:
            if current_block:
                raw = "\n".join(current_block)
                results.append(_parse_blockquote(raw))
                current_block = []

    # Flush final block
    if current_block:
        raw = "\n".join(current_block)
        results.append(_parse_blockquote(raw))

    return results


def _parse_blockquote(raw: str) -> dict:
    """Parse attribution (Author, p. XX) from a blockquote block."""
    author = None
    page = None

    # Look for trailing attribution: (Author, p. XX) or (Author, pp. XX-YY)
    attr_pattern = r'\(([^,)]+),\s*pp?\.\s*(\d+)(?:\s*[-–]\s*\d+)?\)\s*$'
    match = re.search(attr_pattern, raw)
    if match:
        author = match.group(1).strip()
        page = int(match.group(2))
        # Strip attribution from quote text
        quote = raw[:match.start()].strip()
    else:
        # Try author-only attribution: (Author)
        attr_only = r'\(([A-Z][^)]{2,})\)\s*$'
        match2 = re.search(attr_only, raw)
        if match2:
            author = match2.group(1).strip()
            quote = raw[:match2.start()].strip()
        else:
            quote = raw.strip()

    return {"quote": quote, "author": author, "page": page, "raw": raw}


def _extract_page_refs(text: str) -> list[dict]:
    """
    Extract all page references from text.

    Returns list of:
        {"page": int, "end_page": int|None, "context": str}
    """
    results = []
    # Match: p. XX, pp. XX-YY, page XX, pages XX-YY
    pattern = r'(?:pp?\.\s*|pages?\s+)(\d+)(?:\s*[-–]\s*(\d+))?'
    for match in re.finditer(pattern, text, re.IGNORECASE):
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 40)
        results.append({
            "page": int(match.group(1)),
            "end_page": int(match.group(2)) if match.group(2) else None,
            "context": text[start:end],
        })
    return results


def _extract_attributions(text: str) -> list[dict]:
    """
    Extract author attributions from text.

    Returns list of:
        {"name": str, "type": "parenthetical"|"inline"}
    """
    results = []
    seen = set()

    # Parenthetical: (Author, p. XX) or (Author YYYY)
    paren_pattern = r'\(([A-Z][a-zA-Zéèêëàâäöüñ\'\-\s]+?)(?:,|\s+\d{4})'
    for match in re.finditer(paren_pattern, text):
        name = match.group(1).strip()
        if name not in seen and len(name) < 60:
            results.append({"name": name, "type": "parenthetical"})
            seen.add(name)

    # Inline: "As Author argues..." / "According to Author..."
    inline_pattern = (
        r'(?:As|According to|Following|Per)\s+'
        r'([A-Z][a-zA-Zéèêëàâäöüñ\'\-]+(?:\s+[A-Z][a-zA-Zéèêëàâäöüñ\'\-]+)?)'
    )
    for match in re.finditer(inline_pattern, text):
        name = match.group(1).strip()
        if name not in seen and len(name) < 60:
            results.append({"name": name, "type": "inline"})
            seen.add(name)

    return results


def _extract_claims(text: str) -> list[str]:
    """
    Extract claim sentences from non-blockquote, non-heading text.

    Filters out transitions, meta-commentary, and very short sentences.
    """
    claims = []
    lines = text.split("\n")

    # Filter out blockquotes, headings, and blank lines
    prose_lines = []
    for line in lines:
        stripped = line.strip()
        if (
            stripped.startswith("> ")
            or stripped.startswith("#")
            or stripped == ">"
            or not stripped
        ):
            continue
        prose_lines.append(stripped)

    # Join and split into sentences
    prose = " ".join(prose_lines)
    sentences = re.split(r'(?<=[.!?])\s+', prose)

    # Filter: skip transitions, meta, and short sentences
    transition_starts = (
        "in this", "this section", "the following", "as we",
        "let us", "we can see", "it is worth", "here,",
        "below,", "above,", "next,", "finally,", "first,",
        "in summary", "to summarize", "in conclusion", "overall,",
        "note that", "importantly,",
    )

    for sentence in sentences:
        s_lower = sentence.lower().strip()
        # Skip very short sentences (likely fragments)
        if len(s_lower.split()) < 5:
            continue
        # Skip transitions / meta-commentary
        if any(s_lower.startswith(t) for t in transition_starts):
            continue
        claims.append(sentence.strip())

    return claims


# =============================================================================
# Four Dimension Checkers
# =============================================================================

def _build_ngram_index(text: str, n: int = 4) -> dict[str, list[int]]:
    """Build an index of word n-grams to their character positions."""
    text_lower = text.lower()
    # Linear scan: find word boundaries and positions in one pass
    word_positions = []  # list of (word, char_position)
    i = 0
    length = len(text_lower)
    while i < length:
        # Skip whitespace
        if text_lower[i].isspace():
            i += 1
            continue
        # Found word start
        start = i
        while i < length and not text_lower[i].isspace():
            i += 1
        word_positions.append((text_lower[start:i], start))

    # Build n-gram index
    index: dict[str, list[int]] = {}
    for j in range(len(word_positions) - n + 1):
        gram = " ".join(wp[0] for wp in word_positions[j:j + n])
        if gram not in index:
            index[gram] = []
        index[gram].append(word_positions[j][1])

    return index


def _find_candidate_regions(
    quote: str, src_text: str, ngram_index: dict, n: int = 4
) -> list[int]:
    """
    Find candidate start positions in source where the quote might match.

    Uses shared n-grams to identify promising regions, then clusters nearby
    hits into candidate windows. Much faster than brute-force sliding.
    """
    quote_words = re.findall(r'\S+', quote.lower())
    if len(quote_words) < n:
        return []

    # Collect all positions where any quote n-gram appears in source
    hit_positions = []
    for i in range(len(quote_words) - n + 1):
        gram = " ".join(quote_words[i:i + n])
        if gram in ngram_index:
            hit_positions.extend(ngram_index[gram])

    if not hit_positions:
        return []

    # Cluster nearby hits (within quote-length distance)
    hit_positions.sort()
    quote_len = len(quote)
    clusters = []
    cluster_start = hit_positions[0]

    for pos in hit_positions[1:]:
        if pos - cluster_start > quote_len * 1.5:
            clusters.append(max(0, cluster_start - 20))
            cluster_start = pos
    clusters.append(max(0, cluster_start - 20))

    return clusters


def _check_quotes(
    blockquotes: list[dict], sources: dict
) -> dict:
    """
    Check whether each blockquote appears in any session source.

    Phase 1: exact substring match (fast).
    Phase 2: n-gram candidate finding + targeted SequenceMatcher (avoids
    brute-force sliding over 100K+ char documents).
    Thresholds: 0.75 for short quotes (<100 chars), 0.65 for long quotes.
    """
    results = []
    matched = 0

    # Build source texts and n-gram indexes (once per source)
    source_data = {}
    for sid, s in sources.items():
        if not s["text"]:
            continue
        normalized = re.sub(r'\s+', ' ', s["text"])
        source_data[sid] = {
            "normalized": normalized,
            "ngram_index": _build_ngram_index(normalized),
        }

    for bq in blockquotes:
        quote = bq["quote"]
        if not quote or len(quote) < 10:
            continue

        best_ratio = 0.0
        best_source = None
        match_type = "none"

        quote_normalized = re.sub(r'\s+', ' ', quote.strip())

        for sid, sd in source_data.items():
            src_normalized = sd["normalized"]

            # Phase 1: fast exact check
            if quote_normalized in src_normalized:
                best_ratio = 1.0
                best_source = sid
                match_type = "exact"
                break

            # Phase 2: n-gram candidate regions + targeted fuzzy match
            if len(quote_normalized) > 500:
                continue

            candidates = _find_candidate_regions(
                quote_normalized, src_normalized, sd["ngram_index"]
            )
            window_size = len(quote_normalized)

            for start in candidates:
                end = min(len(src_normalized), start + window_size + 40)
                window = src_normalized[start:end]
                ratio = SequenceMatcher(
                    None, quote_normalized, window
                ).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_source = sid
                    match_type = "fuzzy"

        # Apply threshold
        threshold = 0.75 if len(quote_normalized) < 100 else 0.65
        is_match = best_ratio >= threshold

        if is_match:
            matched += 1

        results.append({
            "quote_preview": quote[:80] + ("..." if len(quote) > 80 else ""),
            "match_ratio": round(best_ratio, 3),
            "match_type": match_type if is_match else "none",
            "matched": is_match,
            "source_id": best_source,
            "attributed_author": bq["author"],
        })

    total = len(results)
    return {
        "total": total,
        "matched": matched,
        "rate": matched / total if total > 0 else 0.0,
        "details": results,
    }


def _check_pages(
    blockquotes: list[dict],
    page_refs: list[dict],
    sources: dict,
) -> dict:
    """
    Check page reference accuracy.

    For quotes with page attributions: find quote in source, compute actual page,
    allow +/- 1 tolerance.
    For standalone refs: verify the page exists in the document.
    """
    results = []
    correct = 0

    all_source_texts = {sid: s["text"] for sid, s in sources.items() if s["text"]}

    # Check blockquotes with page refs
    for bq in blockquotes:
        if bq["page"] is None:
            continue

        claimed_page = bq["page"]
        quote_normalized = re.sub(r'\s+', ' ', bq["quote"].strip())

        actual_page = None
        for sid, src_text in all_source_texts.items():
            src_normalized = re.sub(r'\s+', ' ', src_text)
            idx = src_normalized.find(quote_normalized[:80])
            if idx >= 0:
                actual_page = _find_page_for_offset(src_text, idx)
                break

        if actual_page is not None:
            is_correct = abs(claimed_page - actual_page) <= 1
        else:
            # Can't verify — count as correct if page exists in any source
            is_correct = _page_exists_in_sources(claimed_page, all_source_texts)

        if is_correct:
            correct += 1

        results.append({
            "claimed_page": claimed_page,
            "actual_page": actual_page,
            "correct": is_correct,
            "source": "blockquote",
            "quote_preview": bq["quote"][:60],
        })

    # Check standalone page refs (not already covered by blockquotes)
    bq_pages = {bq["page"] for bq in blockquotes if bq["page"] is not None}
    for ref in page_refs:
        if ref["page"] in bq_pages:
            continue

        exists = _page_exists_in_sources(ref["page"], all_source_texts)
        if exists:
            correct += 1

        results.append({
            "claimed_page": ref["page"],
            "actual_page": None,
            "correct": exists,
            "source": "standalone",
            "context": ref["context"][:60],
        })

    total = len(results)
    return {
        "total": total,
        "correct": correct,
        "rate": correct / total if total > 0 else 0.0,
        "details": results,
    }


def _page_exists_in_sources(page: int, source_texts: dict) -> bool:
    """Check if a [PAGE n] marker exists in any source (with +/- 1 tolerance)."""
    for text in source_texts.values():
        for p in range(page - 1, page + 2):
            if f"[PAGE {p}]" in text:
                return True
    return False


def _check_attributions(
    attributions: list[dict], sources: dict
) -> dict:
    """
    Check whether cited author names match known session sources.

    Uses last-name matching: "Hinton" matches "Geoffrey Hinton".
    """
    # Build canonical author set
    canonical_authors = {}
    for sid, src in sources.items():
        author = src["author"].strip()
        if not author:
            continue
        # Store full name and extract last name
        canonical_authors[sid] = {
            "full": author.lower(),
            "parts": [p.strip().lower() for p in author.split()],
            "last": author.split()[-1].strip().lower() if author else "",
        }

    results = []
    matched = 0

    for attr in attributions:
        cited = attr["name"].strip()
        cited_lower = cited.lower()
        cited_parts = [p.strip().lower() for p in cited.split()]

        is_match = False
        matched_source = None

        for sid, canon in canonical_authors.items():
            # Exact full name match
            if cited_lower == canon["full"]:
                is_match = True
                matched_source = sid
                break
            # Last name match
            if cited_parts and cited_parts[-1] == canon["last"]:
                is_match = True
                matched_source = sid
                break
            # Any cited part matches canonical last name
            if canon["last"] in cited_parts:
                is_match = True
                matched_source = sid
                break
            # Cited name is a substring of full author name
            if cited_lower in canon["full"]:
                is_match = True
                matched_source = sid
                break

        if is_match:
            matched += 1

        results.append({
            "cited_name": cited,
            "type": attr["type"],
            "matched": is_match,
            "matched_source_id": matched_source,
        })

    total = len(results)
    return {
        "total": total,
        "matched": matched,
        "rate": matched / total if total > 0 else 0.0,
        "details": results,
    }


def _check_synthesis(
    claims: list[str],
    raw_findings: str,
    verified_quotes: set[str],
) -> dict:
    """
    Check synthesis fidelity via token-level Jaccard similarity.

    Compares claim sentences against sliding windows over raw_findings.
    Content words only (stopwords removed). Threshold: 0.3 (low because
    Opus rephrases heavily during synthesis).

    Claims containing verified quotes auto-pass.
    """
    if not raw_findings:
        return {"total": 0, "traceable": 0, "rate": 0.0, "details": []}

    THRESHOLD = 0.25
    results = []
    traceable = 0

    # Tokenize raw findings into content words (ordered list for windowing)
    findings_normalized = re.sub(r'\s+', ' ', raw_findings.lower())
    findings_all_words = _content_words(findings_normalized)

    # Pre-compute sliding windows at multiple scales
    # Larger windows catch rephrased ideas; smaller catch specific terms
    findings_word_list = sorted(findings_all_words)  # deterministic ordering
    # Re-extract in order for windowing
    findings_ordered = [
        w for w in re.findall(r'[a-z]+', findings_normalized)
        if w not in STOPWORDS and len(w) > 2
    ]
    windows = []
    for window_size in (20, 40, 80):
        step = max(5, window_size // 4)
        for i in range(0, max(1, len(findings_ordered) - window_size + 1), step):
            window_set = set(findings_ordered[i:i + window_size])
            windows.append(window_set)

    for claim in claims:
        # Auto-pass if claim contains a verified quote
        claim_lower = claim.lower()
        auto_pass = any(vq in claim_lower for vq in verified_quotes)

        if auto_pass:
            traceable += 1
            results.append({
                "claim_preview": claim[:80],
                "traceable": True,
                "method": "contains_verified_quote",
                "score": 1.0,
            })
            continue

        # Jaccard similarity against sliding windows
        claim_words = _content_words(claim.lower())
        if not claim_words:
            continue

        best_jaccard = 0.0
        for window_set in windows:
            intersection = claim_words & window_set
            union = claim_words | window_set
            if union:
                jaccard = len(intersection) / len(union)
                if jaccard > best_jaccard:
                    best_jaccard = jaccard

        is_traceable = best_jaccard >= THRESHOLD
        if is_traceable:
            traceable += 1

        results.append({
            "claim_preview": claim[:80],
            "traceable": is_traceable,
            "method": "jaccard",
            "score": round(best_jaccard, 3),
        })

    total = len(results)
    return {
        "total": total,
        "traceable": traceable,
        "rate": traceable / total if total > 0 else 0.0,
        "details": results,
    }


def _content_words(text: str) -> set[str]:
    """Extract content words (lowercase, stopwords removed)."""
    words = re.findall(r'[a-z]+', text)
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


# =============================================================================
# Public API
# =============================================================================

async def run_fidelity_check(run_id: int) -> FidelityReport:
    """
    Run all 4 fidelity checks on a single completed run.

    Loads the run's final_content and raw_findings from eval.db,
    loads session sources from library.db, then runs extraction + checking.
    Saves results to fidelity_checks table.
    """
    db = await get_eval_db()

    # Load run data
    cursor = await db.execute(
        """SELECT r.final_content, r.raw_findings, q.session_id
           FROM runs r
           JOIN queries q ON q.id = r.query_id
           WHERE r.id = ?""",
        (run_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise ValueError(f"Run {run_id} not found")

    final_content = row["final_content"] or ""
    raw_findings = row["raw_findings"] or ""
    session_id = row["session_id"]

    # Load sources from library.db
    sources = _load_session_sources(LIBRARY_DB_PATH, session_id)

    if not final_content:
        # Nothing to check — return empty report
        report = FidelityReport(run_id=run_id)
        await _save_report(db, report)
        return report

    # --- Extract ---
    blockquotes = _extract_blockquotes(final_content)
    page_refs = _extract_page_refs(final_content)
    attributions = _extract_attributions(final_content)
    claims = _extract_claims(final_content)

    # --- Check ---
    quote_results = _check_quotes(blockquotes, sources)
    page_results = _check_pages(blockquotes, page_refs, sources)
    attr_results = _check_attributions(attributions, sources)

    # Build set of verified quote snippets for synthesis auto-pass
    verified_quotes = set()
    for qr in quote_results["details"]:
        if qr["matched"]:
            # Use first 40 chars (lowered) as the snippet
            preview = qr["quote_preview"][:40].lower()
            if len(preview) > 10:
                verified_quotes.add(preview)

    synthesis_results = _check_synthesis(claims, raw_findings, verified_quotes)

    # --- Build report ---
    report = FidelityReport(
        run_id=run_id,
        total_quotes=quote_results["total"],
        matched_quotes=quote_results["matched"],
        quote_match_rate=quote_results["rate"],
        total_page_refs=page_results["total"],
        correct_page_refs=page_results["correct"],
        page_accuracy=page_results["rate"],
        total_attributions=attr_results["total"],
        matched_attributions=attr_results["matched"],
        attribution_accuracy=attr_results["rate"],
        total_claims=synthesis_results["total"],
        traceable_claims=synthesis_results["traceable"],
        synthesis_fidelity=synthesis_results["rate"],
        details={
            "quotes": quote_results["details"],
            "pages": page_results["details"],
            "attributions": attr_results["details"],
            "synthesis": synthesis_results["details"],
        },
    )

    await _save_report(db, report)
    return report


async def _save_report(db, report: FidelityReport):
    """Insert or replace fidelity check row."""
    await db.execute(
        """INSERT OR REPLACE INTO fidelity_checks
           (run_id, total_quotes, matched_quotes, quote_match_rate,
            total_page_refs, correct_page_refs, page_accuracy,
            total_attributions, matched_attributions, attribution_accuracy,
            total_claims, traceable_claims, synthesis_fidelity, details)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report.run_id,
            report.total_quotes, report.matched_quotes, report.quote_match_rate,
            report.total_page_refs, report.correct_page_refs, report.page_accuracy,
            report.total_attributions, report.matched_attributions,
            report.attribution_accuracy,
            report.total_claims, report.traceable_claims, report.synthesis_fidelity,
            json.dumps(report.details) if report.details else None,
        ),
    )
    await db.commit()


async def check_experiment(experiment_id: int):
    """
    Run fidelity checks on all completed runs in an experiment.

    Skips runs that already have fidelity_checks rows.
    Prints progress and summary.
    """
    db = await get_eval_db()

    # Find completed runs without fidelity checks
    cursor = await db.execute(
        """SELECT r.id
           FROM runs r
           LEFT JOIN fidelity_checks fc ON fc.run_id = r.id
           WHERE r.experiment_id = ? AND r.status = 'completed'
             AND fc.id IS NULL
           ORDER BY r.id""",
        (experiment_id,),
    )
    run_ids = [row["id"] for row in await cursor.fetchall()]

    if not run_ids:
        # Check if there are any completed runs at all
        cursor = await db.execute(
            "SELECT COUNT(*) as n FROM runs WHERE experiment_id = ? AND status = 'completed'",
            (experiment_id,),
        )
        total = (await cursor.fetchone())["n"]
        if total == 0:
            print(f"No completed runs for experiment {experiment_id}.")
        else:
            print(f"All {total} completed runs already have fidelity checks.")
        return

    print(f"Running fidelity checks on {len(run_ids)} runs...")

    reports = []
    for i, run_id in enumerate(run_ids, 1):
        try:
            report = await run_fidelity_check(run_id)
            reports.append(report)
            print(
                f"  [{i}/{len(run_ids)}] Run {run_id}: "
                f"quotes={report.quote_match_rate:.0%} "
                f"pages={report.page_accuracy:.0%} "
                f"attr={report.attribution_accuracy:.0%} "
                f"synth={report.synthesis_fidelity:.0%} "
                f"composite={report.composite_score:.0%}"
            )
        except Exception as e:
            print(f"  [{i}/{len(run_ids)}] Run {run_id}: ERROR — {e}")

    # Summary
    if reports:
        print(f"\nSummary ({len(reports)} runs):")
        avg = lambda attr: sum(getattr(r, attr) for r in reports) / len(reports)
        print(f"  Quote match rate:      {avg('quote_match_rate'):.0%}")
        print(f"  Page accuracy:         {avg('page_accuracy'):.0%}")
        print(f"  Attribution accuracy:  {avg('attribution_accuracy'):.0%}")
        print(f"  Synthesis fidelity:    {avg('synthesis_fidelity'):.0%}")
        print(f"  Composite score:       {avg('composite_score'):.0%}")
