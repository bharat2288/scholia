"""
Council Presets
===============
System preset definitions for document analysis prompts.

These presets are seeded to the database on first run.
Users can duplicate system presets to customize them.

Variables available in prompts:
- {context} - The selected text, section, or full document
- {source_title} - Title of the source being read
- {author} - Author of the source
- {selection} - Alias for {context} when selection-specific
- {source_type} - Human-readable source type noun (e.g., "this document")

Quick Actions:
Some presets are marked as show_as_quick_action=True which makes them
appear as one-click buttons in the chat interface.

Source Types:
Presets can specify which source types they're relevant for:
- null (default) = shown for all source types
- ["document", "web"] = only shown for those types
Valid types: "document", "web", "thread", "media"
"""

import json


# System presets - seeded to database on first run
# NOTE: show_as_quick_action determines if preset appears in quick action bar
# NOTE: source_types determines which source types see this preset (null = all)
SYSTEM_PRESETS = [
    {
        "id": "summarize",
        "name": "Summarize",
        "description": "Structured summary with key claims and evidence assessment",
        "prompt": """You are analyzing {source_type}. Your goal is to produce a structured summary that captures the argument, not just the topic.

## Your Task

### 1. Overview
Write 2-3 sentences that answer: What is this about? Who produced it? What is the context?

### 2. Key Claims
Identify 5-10 central claims. For each:
- **Claim**: [State it precisely in one sentence]
- **Evidence**: [What supports this? Quote or paraphrase]
- **Strength**: [Strong / Moderate / Weak / Asserted without evidence]

### 3. Structure
Outline the argument flow: how does the text move from premise to conclusion? Note any pivots, digressions, or structural choices.

### 4. Implications
What follows from this text? Why does it matter? What does it leave open?

## Guidelines
- Specificity over generality: name the actual claims, not just the topics
- Distinguish between what the text claims, what evidence it provides, and what it merely asserts
- Note any internal disagreements or tensions
- If the text argues against something, state what it argues against

---

TEXT TO ANALYZE:

{context}""",
        "prompt_full_doc": """You are analyzing {source_type} in its entirety. Your goal is to produce a comprehensive structural summary that treats the work as a whole.

## Your Task

### 1. Thesis & Purpose
What is the central argument? What is this work trying to accomplish? State in 2-3 precise sentences.

### 2. Chapter/Section Inventory
For each major section or chapter:
- **Title**: [Section name or topic]
- **Focus**: [What this section is about in 1-2 sentences]
- **Role**: [How it serves the larger argument — establishes framework, provides evidence, addresses objections, etc.]

### 3. Argument Architecture
How do the sections build on each other? Where are the key pivots? What is the structural logic — does it move chronologically, thematically, from theory to evidence?

### 4. Key Claims
Identify 5-10 of the most important claims across the whole work:
- **Claim**: [State precisely]
- **Where**: [Which section/chapter]
- **Strength**: [Strong / Moderate / Weak / Asserted]

### 5. Assessment
- **Strengths**: What does this work do well?
- **Gaps**: What does it leave unaddressed?
- **Accomplishments vs. Ambitions**: Does it deliver on its stated purpose?

## Guidelines
- Treat each chapter/section as a unit with its own contribution
- Assess how each part serves the whole
- Identify the spine of the argument — the through-line that connects everything
- Note where the text is strongest and where it stretches

---

TEXT TO ANALYZE:

{context}""",
        "model": "default",
        "max_tokens": 8192,
        "sort_order": 1,
        "show_as_quick_action": True,
        "source_types": None,  # All source types
    },
    {
        "id": "analyze",
        "name": "Analyze",
        "description": "Connect to theoretical frameworks across disciplines",
        "prompt": """You are analyzing {source_type}. Your goal is a rigorous theoretical analysis that connects this text to established intellectual traditions.

## Your Task

### 1. Theoretical Resonances
Identify 3-5 theoretical frameworks this text engages with (explicitly or implicitly). For each:
- **Framework**: [Name — e.g., "Bourdieu's field theory", "Actor-Network Theory", "Cognitive Load Theory"]
- **Connection**: [How does this text relate to, extend, or depart from this framework?]
- **Text Awareness**: [Does the author explicitly reference this, or is this your analytical connection?]

Draw from philosophy, social theory, psychology, media studies, STS, education theory, political theory, and other relevant traditions.

### 2. Theoretical Tensions
Where does this text sit in existing debates?
- What theoretical positions does it implicitly take sides on?
- Where do its claims conflict with established frameworks?
- What intellectual traditions would push back, and why?

### 3. Generative Questions
What must be true for the text's claims to hold? For each:
- **Question**: [State it]
- **Stakes**: [What hangs on the answer]
- **Possible Test**: [What empirical work or further analysis would address this]
- **Complicating Case**: [What example or scenario makes this harder]

### 4. Novel Contributions
What, if anything, is genuinely new here?
- New concepts or terms introduced
- Unexpected synthesis of existing ideas
- Challenges to established theoretical positions
- Productive ambiguities worth developing further

## Guidelines
- Name specific theorists and works, not just traditions
- Distinguish between connections the text itself makes and connections you are drawing
- Depth over breadth: better to develop 3 resonances richly than list 10 superficially
- If the text is atheoretical, say so — then analyze what implicit theoretical commitments it carries anyway

---

TEXT TO ANALYZE:

{context}""",
        "model": "default",
        "max_tokens": 12288,
        "sort_order": 2,
        "show_as_quick_action": True,
        "source_types": ["document", "note"],
    },
    {
        "id": "critique",
        "name": "Critique",
        "description": "Steel-manned counterarguments and objections",
        "prompt": """You are analyzing {source_type}. Your goal is to generate the strongest possible counterarguments — not straw men, but objections a serious interlocutor would raise.

## Your Task

Generate 5-8 substantive counterarguments. For each:

- **Original Claim**: [What the text argues — state it fairly]
- **Strongest Objection**: [The best counterargument, steel-manned]
- **Why It Matters**: [What's at stake if the objection holds]
- **Possible Response**: [How the author might respond — does the text already address this?]

## Guidelines
- Steel-man every objection: make it the strongest version of itself
- Draw from academic debates, empirical evidence, and alternative frameworks — not just personal disagreement
- Distinguish between factual objections (the evidence doesn't support this) and framing objections (this isn't the right way to think about the problem)
- Include at least one objection about methodology or approach, not just conclusions
- If the text is strong, say so — but still find the pressure points
- Be charitable to the original text while being rigorous about weaknesses

---

TEXT TO ANALYZE:

{context}""",
        "model": "default",
        "max_tokens": 8192,
        "sort_order": 3,
        "show_as_quick_action": True,
        "source_types": ["document", "web", "note"],
    },
    {
        "id": "concept-map",
        "name": "Concept Map",
        "description": "Map concepts, relationships, and hidden assumptions",
        "prompt": """You are analyzing {source_type}. Your goal is to surface the conceptual architecture — not just what the text says, but how its ideas relate to each other.

## Your Task

### 1. Core Concepts
Identify 5-10 key concepts. For each:
- **Name**: [The concept]
- **Definition as Used**: [How THIS text uses it — may differ from standard usage]
- **Importance**: [Central / Supporting / Background]

### 2. Relationships
Map how concepts connect. For each relationship:
- **A → B**: [Concept A] → [Concept B]
- **Nature**: [causes / enables / contradicts / requires / instantiates / transforms / is-a-type-of]
- **Explanation**: [Why this relationship holds in the text's logic]

### 3. Conceptual Moves
What intellectual work is the text doing with these concepts?
- **Redefinitions**: Any terms given new meaning?
- **Novel Distinctions**: Where does the text split what's usually treated as one thing?
- **Collapsed Distinctions**: Where does it merge what's usually kept separate?
- **Unexpected Analogies**: What surprising comparisons does it draw?

### 4. Unstated Assumptions
What does the text take for granted?
- Shared premises it doesn't argue for
- Assumed frameworks or worldviews
- What a reader must already accept for the argument to land

## Guidelines
- Use the text's own vocabulary where possible
- Mark when a concept is used differently than its standard definition
- Focus on relationships that do intellectual work, not just co-occurrence
- If you find a tension between concepts, flag it — that's often where the interesting analysis lives

---

TEXT TO ANALYZE:

{context}""",
        "model": "default",
        "max_tokens": 8192,
        "sort_order": 4,
        "show_as_quick_action": False,
        "source_types": ["document", "web", "media", "note"],
    },
    {
        "id": "explain",
        "name": "Explain",
        "description": "Clear explanation with key terms, breakdowns, and analogies",
        "prompt": """You are analyzing {source_type}. Your goal is to make this text accessible to an intelligent reader who isn't an expert in this field.

## Your Task

### 1. Plain Language Summary
In 2-3 sentences, what is this text saying? Use everyday language. No jargon.

### 2. Key Terms
For each important or specialized term:
- **Term**: [The word or phrase]
- **Definition**: [What it means in plain English]
- **How Used Here**: [How this specific text uses it]
- **Example**: [A concrete, familiar example]

### 3. Step-by-Step Breakdown
Break the text's argument or explanation into clear steps:
1. [First move — what does the text establish?]
2. [Second move — what builds on that?]
3. [Continue until the conclusion]

### 4. Analogies
For the most complex ideas, provide a familiar comparison:
- [Complex idea] is like [familiar thing] because [shared structure]

## Guidelines
- Use everyday language — if you must use a technical term, define it immediately
- Define ALL technical terms, even if they seem common in the field
- Maintain accuracy: simplify the language, not the ideas
- If something genuinely IS complex and can't be simplified without losing meaning, say so and explain why
- Target audience: someone smart who's reading outside their expertise

---

TEXT TO ANALYZE:

{context}""",
        "model": "default",
        "max_tokens": 8192,
        "sort_order": 5,
        "show_as_quick_action": True,
        "source_types": None,  # All source types
    },
    {
        "id": "quotables",
        "name": "Quotables",
        "description": "Extract memorable, citation-worthy passages",
        "prompt": """You are analyzing {source_type}. Your goal is to identify the passages most worth remembering, citing, or saving.

## Your Task

Extract 5-8 notable passages. For each:

- **Exact Text**: [The passage, quoted precisely — use "..." for omissions]
- **Context**: [Where this appears in the argument and what surrounds it]
- **Why It Works**: Tag one or more: *Surprising* / *Well-phrased* / *Insightful* / *Provocative* / *Foundational* — then explain briefly

## Selection Criteria
Prioritize passages that:
- **Standalone clarity**: Make sense without extensive context
- **Compression**: Pack a complex idea into memorable form
- **Novelty**: Say something you haven't read elsewhere, or say a common thing uncommonly well
- **Memorability**: Would stick in a reader's mind

## Guidelines
- Substance over style: a beautifully written platitude is less valuable than an awkward but original insight
- Include controversial or uncomfortable passages if they're well-argued
- Note if you've lightly edited (e.g., removing a pronoun reference) — mark edits with [brackets]
- If the text doesn't have strong quotable passages, say so honestly rather than forcing selections

---

TEXT TO ANALYZE:

{context}""",
        "model": "default",
        "max_tokens": 6144,
        "sort_order": 6,
        "show_as_quick_action": False,
        "source_types": ["document", "web", "media", "note"],
    },
    {
        "id": "research-questions",
        "name": "Research Questions",
        "description": "Generate empirically answerable questions for further investigation",
        "prompt": """You are analyzing {source_type}. Your goal is to generate research questions that this text opens up — questions worth pursuing, not just worth asking.

## Your Task

Generate 4-6 high-quality research questions. For each:

- **The Question**: [State it precisely and completely]
- **Why It Matters**: [What would answering this contribute?]
- **Possible Approaches**: [How might someone investigate this? Name 1-2 methods]
- **Type**: [Descriptive / Explanatory / Normative]

## Guidelines
- Questions must be empirically answerable — not purely philosophical
- Questions must be non-trivial — can't be answered with a quick search
- Questions must be significant — answering them would actually advance understanding
- Include a mix of types: at least one descriptive, one explanatory, and one normative
- The best questions are specific enough to be actionable but broad enough to be interesting
- Connect questions to gaps, tensions, or unexplored implications in the text

---

TEXT TO ANALYZE:

{context}""",
        "model": "default",
        "max_tokens": 8192,
        "sort_order": 7,
        "show_as_quick_action": False,
        "source_types": ["document", "web", "note"],
    },
]


async def seed_system_presets(db):
    """
    Seed system presets to database if they don't exist.
    Updates existing system presets with latest prompts on each startup.
    Called during database initialization.

    Args:
        db: aiosqlite connection
    """
    from datetime import datetime

    now = datetime.now().isoformat()
    inserted = 0
    updated = 0

    for preset in SYSTEM_PRESETS:
        source_types_json = json.dumps(preset["source_types"]) if preset.get("source_types") else None

        # Check if preset exists
        cursor = await db.execute(
            "SELECT id FROM council_presets WHERE id = ?",
            [preset["id"]]
        )
        existing = await cursor.fetchone()

        if not existing:
            show_quick = 1 if preset.get("show_as_quick_action", False) else 0
            await db.execute("""
                INSERT INTO council_presets
                (id, name, description, prompt, prompt_full_doc, model, max_tokens,
                 is_system, sort_order, show_as_quick_action, source_types, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """, [
                preset["id"],
                preset["name"],
                preset["description"],
                preset["prompt"],
                preset.get("prompt_full_doc"),
                preset["model"],
                preset["max_tokens"],
                preset["sort_order"],
                show_quick,
                source_types_json,
                now,
                now
            ])
            inserted += 1
        else:
            # Update existing system preset with latest prompt content
            show_quick = 1 if preset.get("show_as_quick_action", False) else 0
            await db.execute("""
                UPDATE council_presets
                SET name = ?, description = ?, prompt = ?, prompt_full_doc = ?,
                    max_tokens = ?, sort_order = ?, show_as_quick_action = ?,
                    source_types = ?, updated_at = ?
                WHERE id = ? AND is_system = 1
            """, [
                preset["name"],
                preset["description"],
                preset["prompt"],
                preset.get("prompt_full_doc"),
                preset["max_tokens"],
                preset["sort_order"],
                show_quick,
                source_types_json,
                now,
                preset["id"]
            ])
            updated += 1

    await db.commit()
    if inserted > 0:
        print(f"Seeded {inserted} system presets")
    if updated > 0:
        print(f"Updated {updated} system presets")


async def seed_quick_action_presets(db):
    """
    Update existing presets to set show_as_quick_action flag.
    Also inserts any missing quick action presets.
    Called after migration adds the column.

    Args:
        db: aiosqlite connection
    """
    from datetime import datetime

    now = datetime.now().isoformat()

    # Quick action preset IDs (updated for consolidated set)
    quick_action_ids = {'summarize', 'explain', 'critique', 'analyze'}

    for preset in SYSTEM_PRESETS:
        preset_id = preset["id"]
        show_quick = 1 if preset.get("show_as_quick_action", False) else 0

        # Check if preset exists
        cursor = await db.execute(
            "SELECT id, show_as_quick_action FROM council_presets WHERE id = ?",
            [preset_id]
        )
        existing = await cursor.fetchone()

        if existing:
            # Update the show_as_quick_action flag if it's a quick action
            if preset_id in quick_action_ids:
                await db.execute("""
                    UPDATE council_presets
                    SET show_as_quick_action = ?, updated_at = ?
                    WHERE id = ?
                """, [show_quick, now, preset_id])

    await db.commit()
    print("Quick action presets updated")
