"""
LLM-as-Judge Rubric v1
=======================
4 qualitative dimensions, 1-5 scale.

IMPORTANT: This rubric explicitly does NOT assess citation accuracy or
source fidelity — that's handled by programmatic checks in fidelity.py.
The judge evaluates response quality as a reader would experience it.
"""

JUDGE_SYSTEM_PROMPT = """You are an expert evaluator of scholarly research responses. You will score a response on 4 quality dimensions using a 1-5 scale.

IMPORTANT: Do NOT evaluate citation accuracy, quote correctness, or source fidelity. Those are verified separately by automated tools. Focus purely on the quality of the response as written text.

Score each dimension from 1 (poor) to 5 (excellent):

1. COMPLETENESS (1-5)
   Does the response address all aspects of the question?
   1 = Major aspects missing, superficial treatment
   2 = Some aspects addressed but significant gaps
   3 = Most aspects covered, minor omissions
   4 = Comprehensive coverage with good depth
   5 = Thorough, nuanced treatment of every aspect

2. COHERENCE (1-5)
   Is the response logically structured and well-organized?
   1 = Disorganized, hard to follow, contradictions
   2 = Some structure but unclear transitions or logic gaps
   3 = Reasonable organization, mostly clear
   4 = Well-structured with clear progression of ideas
   5 = Excellent flow, each section builds on previous, seamless

3. RELEVANCE (1-5)
   Does every part of the response serve the question?
   1 = Mostly off-topic or padding
   2 = Some relevant content mixed with tangents
   3 = Generally relevant, minor digressions
   4 = Focused and on-topic throughout
   5 = Every paragraph directly advances the answer

4. OVERALL SCHOLARLY QUALITY (1-5)
   Would a researcher find this response useful and trustworthy?
   1 = Unreliable, wouldn't trust it
   2 = Some useful points but amateurish
   3 = Adequate for getting started on a topic
   4 = Solid work a researcher could build on
   5 = Impressive — insightful analysis a peer would respect

After scoring, provide:
- STRENGTHS: 2-3 specific things the response does well
- WEAKNESSES: 2-3 specific areas for improvement
- NOTES: Any additional observations

Respond ONLY with valid JSON in this exact format:
{
    "completeness": <int 1-5>,
    "coherence": <int 1-5>,
    "relevance": <int 1-5>,
    "scholarly_quality": <int 1-5>,
    "strengths": "<brief strengths>",
    "weaknesses": "<brief weaknesses>",
    "notes": "<any additional observations>"
}"""


def build_judge_prompt(
    query: str,
    response_text: str,
    doc_descriptions: list[dict],
    expected_signals: list[str] | None = None,
) -> str:
    """
    Build the user message for the LLM judge.

    Args:
        query: The original research question
        response_text: The RLM's response to evaluate
        doc_descriptions: [{title, author, year}] — NOT full text
        expected_signals: Optional list of expected content signals
    """
    # Format document context (titles only, not full text)
    doc_lines = []
    for doc in doc_descriptions:
        title = doc.get("title", "Unknown")
        author = doc.get("author", "Unknown")
        year = doc.get("year", "")
        doc_lines.append(f"  - {author} ({year}). {title}")
    docs_section = "\n".join(doc_lines) if doc_lines else "  (no documents listed)"

    # Format expected signals if provided
    signals_section = ""
    if expected_signals:
        signal_lines = [f"  - {s}" for s in expected_signals]
        signals_section = f"""

EXPECTED SIGNALS (what a good answer should contain):
{chr(10).join(signal_lines)}
Note: These are hints, not strict requirements. A response can be excellent
without hitting every signal, or hit every signal while still being mediocre."""

    return f"""QUERY:
{query}

DOCUMENTS AVAILABLE TO THE SYSTEM:
{docs_section}

RESPONSE TO EVALUATE:
---
{response_text}
---
{signals_section}

Score this response on the 4 dimensions described in your instructions.
Respond with JSON only."""
