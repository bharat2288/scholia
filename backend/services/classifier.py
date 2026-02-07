"""
Classifier Service
===================
Classifies quick capture notes into categories using Claude.

Categories:
- task: Action items, reminders, todos
- idea: Exploratory thoughts, no commitment
- people: Information about a person
- admin: Reference info, credentials, settings
- inbox: Unclear or low-confidence items

Ported from notes-processor project.
"""

import os
import json
from anthropic import Anthropic

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

CONFIDENCE_THRESHOLD = 0.7


class ClassificationResult:
    """Result of classifying a note."""
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


async def classify_note(text: str) -> ClassificationResult:
    """
    Classify a note using Claude.

    Args:
        text: The note content to classify

    Returns:
        ClassificationResult with category, confidence, and reasoning
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Fallback to inbox if no API key
        return ClassificationResult(
            category="inbox",
            confidence=0.0,
            reasoning="No API key configured"
        )

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
        # On error, route to inbox for manual review
        return ClassificationResult(
            category="inbox",
            confidence=0.0,
            reasoning=f"Classification error: {str(e)}"
        )
