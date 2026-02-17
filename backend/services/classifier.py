"""
Classifier Service
===================
Classifies quick capture notes into categories.

Two classifiers:
1. classify_note() — Legacy Claude-based classifier (simple category only)
2. classify_structured() — Gemini Flash via OpenRouter (structured: header, details, category, person refs)

Categories:
- task: Action items, reminders, todos
- idea: Exploratory thoughts, no commitment
- social: Involves another person socially
- admin: Reference info, credentials, settings
- inbox: Genuinely unclear (fallback)
"""

import os
import json
import httpx
from dataclasses import dataclass, field
from typing import Optional

CONFIDENCE_THRESHOLD = 0.7


# ============================================================
# Shared result types
# ============================================================

class ClassificationResult:
    """Result of classifying a note (legacy classifier)."""
    def __init__(self, category: str, confidence: float, reasoning: str):
        self.category = category
        self.confidence = confidence
        self.reasoning = reasoning

    @property
    def is_confident(self) -> bool:
        return self.confidence >= CONFIDENCE_THRESHOLD

    @property
    def effective_category(self) -> str:
        """Returns 'inbox' if confidence is low, otherwise the classified category."""
        return self.category if self.is_confident else "inbox"

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "effective_category": self.effective_category,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "is_confident": self.is_confident
        }


@dataclass
class StructuredClassification:
    """Result of structured classification (Gemini Flash)."""
    category: str = "inbox"
    header: str = ""
    details: list[str] = field(default_factory=list)
    is_task: bool = False
    person_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""

    @property
    def effective_category(self) -> str:
        return self.category if self.confidence >= CONFIDENCE_THRESHOLD else "inbox"


# ============================================================
# Legacy classifier (Claude via Anthropic SDK)
# ============================================================

CLASSIFICATION_PROMPT = """You classify personal knowledge items for inbox processing.

CATEGORIES:
- task: Has action verb OR is a reminder. "Call X", "Buy Y", "Email Z", noun-phrase reminders.
- idea: Exploratory thought, no commitment. "What if...", "Maybe try...", "Consider..."
- people: Information ABOUT a person. Contact info, birthdays, notes on someone. NOT actions involving them.
- admin: System/reference info. Passwords, credentials, settings, account details, bookkeeping.
- inbox: Genuinely unclear or multi-purpose.

RULES:
1. Action verbs → task (even if about a person: "Call mom" = task)
2. Questions needing research/action → task ("Look into X", "Find out about Y")
3. Aspirational without commitment → idea ("Maybe I should...", "What if...")
4. Pure information about a person → people ("Mom's birthday March 15")
5. Noun phrases without clear context → task (assumed reminder: "Passport for Zoya" = task)
6. Contains credentials/numbers/data patterns → admin ("Password: abc123", "Account #12345")

EXAMPLES:
- "Call mom Tuesday" → task (action verb, even though about a person)
- "Mom's birthday March 15" → people (information about person, no action)
- "What if I tried spaced repetition?" → idea (exploratory, no commitment)
- "Bank login: user123" → admin (credential/reference)
- "Sarah mentioned a good book" → people (note about person)
- "Look into spaced repetition" → task (action: look into)
- "Passport for Zoya" → task (noun phrase = assumed reminder)
- "Zoya passport: AB1234567" → admin (contains credential pattern)
- "Maybe learn piano someday" → idea (aspirational, not committed)
- "Buy groceries" → task (clear action)

Respond JSON only:
{"classification": "task|idea|people|admin|inbox", "confidence": 0.0-1.0, "reasoning": "brief explanation"}

INPUT:
"""


async def classify_note(text: str) -> ClassificationResult:
    """
    Classify a note using Claude (legacy classifier).
    Kept for backward compatibility.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return ClassificationResult(
            category="inbox",
            confidence=0.0,
            reasoning="No API key configured"
        )

    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": CLASSIFICATION_PROMPT + text
                }
            ]
        )

        response_text = message.content[0].text

        # Handle potential markdown code blocks
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        result = json.loads(response_text.strip())

        return ClassificationResult(
            category=result.get("classification", "inbox"),
            confidence=result.get("confidence", 0.5),
            reasoning=result.get("reasoning", "")
        )

    except Exception as e:
        return ClassificationResult(
            category="inbox",
            confidence=0.0,
            reasoning=f"Classification error: {str(e)}"
        )


# ============================================================
# Structured classifier (Gemini Flash via OpenRouter)
# ============================================================

STRUCTURED_PROMPT = """You parse personal quick-capture messages into one or more structured journal entries.

A single message may contain MULTIPLE independent items. Split them into separate entries when they have different topics or actions. Keep related sub-points together as details under one entry.

CATEGORIES:
- task: Action verb or reminder. "Call X", "Buy Y", "Email Z", noun-phrase reminders.
- idea: Exploratory, no commitment. "What if...", "Maybe try...", "Consider..."
- social: Involves another person socially. "Dinner with Sarah", "Mom called about..."
- admin: Credentials, settings, reference data. "Password: abc123", "Account #12345"
- inbox: Genuinely unclear (use only when confidence is truly low)

CLASSIFICATION RULES:
1. Action verbs → task (even if about a person: "Call mom" = task)
2. Involves a person in a social context → social ("Dinner with Sarah", "Ran into Paul")
3. Aspirational without commitment → idea
4. Contains credentials/data patterns → admin
5. Noun phrases without context → task (assumed reminder)

SPLITTING RULES:
- Different actions/topics → SPLIT into separate entries
- Related sub-points for one action → KEEP as one entry with details array
- "Call dentist and buy groceries" → SPLIT (two independent tasks)
- "Call dentist about cleaning, ask about pricing" → ONE entry (one task, two details)
- "Had coffee with Sarah. Also need to fix the leaky faucet" → SPLIT (social + task)
- Single simple message → ONE entry (don't force-split)

OUTPUT FORMAT — always a JSON array, no markdown:
[
  {
    "category": "task",
    "header": "Concise title (imperative for tasks, descriptive for others)",
    "details": ["Sub-point 1", "Sub-point 2"],
    "is_task": true,
    "person_refs": ["Last, First"],
    "confidence": 0.85
  }
]

SPECIAL SYNTAX (preserve as-is, do NOT modify):
- [[text]] → reference syntax. Keep exactly as written in the header/details.
- [[text (unclosed) → keep the [[ marker and text as-is. Do NOT close it or guess.
- ##tag → tag syntax. Keep exactly as written in the header/details.
- These are user markup. Preserve them; do not interpret or remove them.
- Example: "Finish [[moom audit today ##urgent" → header: "Finish [[moom audit today ##urgent"

HEADER RULES:
- Tasks: imperative verb. "Call dentist" not "Need to call dentist"
- Ideas: descriptive. "Spaced repetition for vocabulary"
- Social: include person. "Dinner plans with Sarah"
- Admin: descriptive. "Bank login credentials"
- If input is short (< 10 words) and a single item, header = input verbatim

PERSON_REFS:
- List people mentioned by name in "Last, First" format when possible
- Only real people, not generic roles ("the doctor" → skip, "Dr. Patel" → include)
- Empty array if no specific people mentioned
- Each person ref goes on the entry where they're mentioned

INPUT:
"""


def _parse_one(item: dict, fallback_text: str) -> StructuredClassification:
    """Parse a single classification item from the LLM response."""
    valid_categories = {"task", "idea", "social", "admin", "inbox"}
    category = item.get("category", "inbox")
    if category not in valid_categories:
        category = "inbox"

    return StructuredClassification(
        category=category,
        header=item.get("header", fallback_text[:100]),
        details=item.get("details", []),
        is_task=item.get("is_task", category == "task"),
        person_refs=item.get("person_refs", []),
        confidence=item.get("confidence", 0.5),
        reasoning=item.get("reasoning", ""),
    )


async def classify_structured(text: str) -> list[StructuredClassification]:
    """
    Classify a note using Gemini Flash via OpenRouter.

    Returns a LIST of structured classifications — one per distinct item
    detected in the input. A simple message returns a single-element list.

    Cost: ~$0.10/M input, ~$0.40/M output (very cheap).
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return [StructuredClassification(
            category="inbox",
            header=text[:100],
            confidence=0.0,
            reasoning="No OpenRouter API key configured"
        )]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.0-flash-001",
                    "max_tokens": 1000,
                    "messages": [
                        {
                            "role": "user",
                            "content": STRUCTURED_PROMPT + text
                        }
                    ]
                }
            )
            response.raise_for_status()
            data = response.json()

        response_text = data["choices"][0]["message"]["content"]

        # Strip markdown code blocks if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        result = json.loads(response_text.strip())

        # Handle both array and single-object responses (defensive)
        if isinstance(result, dict):
            result = [result]

        if not isinstance(result, list) or len(result) == 0:
            return [StructuredClassification(
                category="inbox", header=text[:100], confidence=0.0,
                reasoning="Unexpected classifier output format"
            )]

        return [_parse_one(item, text) for item in result]

    except Exception as e:
        print(f"[Classifier ERROR] {type(e).__name__}: {e}")
        return [StructuredClassification(
            category="inbox",
            header=text[:100],
            confidence=0.0,
            reasoning=f"Classification error: {str(e)}"
        )]
