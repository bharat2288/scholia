"""
Source Index Generator
======================
Generates specs/index.md from the sources table.

Called after source create, delete, and metadata update operations.
Uses synchronous sqlite3 (works in both async and sync contexts).

Consumer: /study skill reads this file during Phase 0 (Contextualize)
to surface relevant Scholia sources when studying a topic.
QMD indexes it via the project-specs collection.
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# Paths relative to backend folder
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "library.db"
SPECS_DIR = PROJECT_ROOT / "specs"
INDEX_PATH = SPECS_DIR / "index.md"


def regenerate_scholia_index() -> int:
    """
    Regenerate specs/index.md from the sources table.

    Opens its own sqlite3 connection (sync) so it can be called from:
    - sources.py (async): await asyncio.to_thread(regenerate_scholia_index)
    - processor.py (sync): regenerate_scholia_index()

    Returns the number of sources indexed. Raises on failure so callers
    can surface the error rather than swallowing it silently.
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT id, title, source_type, author_display, url,
                   content_path, created_at
            FROM sources
            ORDER BY source_type, created_at DESC
        """)
        sources = cursor.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to query sources for index: {e}")
        raise

    # Group by source_type
    groups: dict[str, list] = {}
    for src in sources:
        st = src["source_type"] or "unknown"
        groups.setdefault(st, []).append(src)

    # Build markdown
    now = datetime.now().isoformat(timespec="seconds")
    total = len(sources)

    lines = [
        "---",
        "type: reference",
        "project: scholia",
        f"date: {datetime.now().strftime('%Y-%m-%d')}",
        "created_by: auto",
        "---",
        "# [[scholia-home|Scholia]] — Source Index",
        "*[[dev-hub|Hub]]*",
        "",
        f"> Auto-generated from library.db. {total} sources.",
        f"> Last regenerated: {now}",
        "",
        "---",
        "",
    ]

    # Ordered type display
    type_order = ["document", "web", "thread", "media", "note", "repo"]
    for st in type_order:
        if st not in groups:
            continue
        entries = groups[st]
        lines.append(f"## {st} ({len(entries)})")
        lines.append("")

        for src in entries:
            title = src["title"] or "Untitled"
            lines.append(f"### {title}")

            # Build compact metadata lines
            meta_parts = [f"**id**: {src['id']}"]
            if src["author_display"]:
                meta_parts.append(f"**author**: {src['author_display']}")
            created = (src["created_at"] or "")[:10]  # date only
            if created:
                meta_parts.append(f"**created**: {created}")
            lines.append("- " + " · ".join(meta_parts))

            if src["url"]:
                lines.append(f"- **url**: {src['url']}")
            if src["content_path"]:
                try:
                    rel = Path(src["content_path"]).relative_to(PROJECT_ROOT)
                    lines.append(f"- **content**: {rel}")
                except ValueError:
                    lines.append(f"- **content**: {src['content_path']}")

            lines.append("")

    # Handle any unexpected types not in type_order
    for st, entries in groups.items():
        if st in type_order:
            continue
        lines.append(f"## {st} ({len(entries)})")
        lines.append("")
        for src in entries:
            title = src["title"] or "Untitled"
            lines.append(f"### {title}")
            meta_parts = [f"**id**: {src['id']}"]
            if src["author_display"]:
                meta_parts.append(f"**author**: {src['author_display']}")
            created = (src["created_at"] or "")[:10]
            if created:
                meta_parts.append(f"**created**: {created}")
            lines.append("- " + " · ".join(meta_parts))
            if src["url"]:
                lines.append(f"- **url**: {src['url']}")
            if src["content_path"]:
                try:
                    rel = Path(src["content_path"]).relative_to(PROJECT_ROOT)
                    lines.append(f"- **content**: {rel}")
                except ValueError:
                    lines.append(f"- **content**: {src['content_path']}")
            lines.append("")

    content = "\n".join(lines)

    # Write to specs
    try:
        SPECS_DIR.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(content, encoding="utf-8")
        logger.info(f"Regenerated index.md: {total} sources")
    except Exception as e:
        logger.error(f"Failed to write index.md: {e}")
        raise

    return total
