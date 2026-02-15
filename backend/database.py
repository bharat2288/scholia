"""
Database Module
===============
SQLite database connection and schema management.

Uses aiosqlite for async operations.
Database file: ../data/library.db
"""

import json
import aiosqlite
from pathlib import Path
from typing import Optional

# Database path - relative to backend folder
DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "library.db"

# Global connection (initialized on startup)
_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    """
    Get the database connection.
    Raises RuntimeError if called before init_db().
    """
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


async def init_db():
    """
    Initialize database connection and run migrations.
    Called on app startup.
    """
    global _db

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Connect to database
    _db = await aiosqlite.connect(DB_PATH)

    # Enable foreign keys (SQLite has them disabled by default)
    await _db.execute("PRAGMA foreign_keys = ON")

    # Enable WAL mode for better concurrent read performance
    await _db.execute("PRAGMA journal_mode = WAL")

    # Run migrations first (handle existing tables with old schema)
    await _run_migrations()

    # Then create schema (for fresh databases, and indexes after migration)
    await _create_schema()

    print(f"Database initialized: {DB_PATH}")


async def close_db():
    """
    Close database connection.
    Called on app shutdown.
    """
    global _db
    if _db:
        await _db.close()
        _db = None
        print("Database connection closed")


async def _run_migrations():
    """
    Run any necessary database migrations.
    This handles schema changes between versions.
    """
    # Migration 1: Rename 'rems' table to 'gluons' and 'parent_rem_id' to 'parent_gluon_id'
    # Check if old 'rems' table exists
    cursor = await _db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rems'"
    )
    if await cursor.fetchone():
        print("Migrating: Renaming 'rems' table to 'gluons'...")

        # SQLite doesn't support ALTER TABLE RENAME COLUMN in older versions,
        # so we create new table, copy data, drop old, rename
        await _db.execute("""
            CREATE TABLE IF NOT EXISTS gluons (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT,
                document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                section_id TEXT REFERENCES sections(id) ON DELETE SET NULL,
                start_offset INTEGER,
                end_offset INTEGER,
                color TEXT,
                parent_gluon_id TEXT REFERENCES gluons(id) ON DELETE CASCADE,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Copy data from rems to gluons
        await _db.execute("""
            INSERT OR IGNORE INTO gluons
            (id, type, content, document_id, section_id, start_offset, end_offset, color, parent_gluon_id, created_at, updated_at)
            SELECT id, type, content, document_id, section_id, start_offset, end_offset, color, parent_rem_id, created_at, updated_at
            FROM rems
        """)

        # Update links table foreign keys (they still reference same IDs, just table name changed)
        # The links table references rems(id) but the IDs are the same in gluons

        # Drop old FTS table and recreate for gluons
        await _db.execute("DROP TABLE IF EXISTS rems_fts")

        # Drop old table
        await _db.execute("DROP TABLE IF EXISTS rems")

        # Drop old indexes (they reference the old table)
        await _db.execute("DROP INDEX IF EXISTS idx_rems_document")
        await _db.execute("DROP INDEX IF EXISTS idx_rems_type")
        await _db.execute("DROP INDEX IF EXISTS idx_rems_parent")

        await _db.commit()
        print("Migration complete: 'rems' -> 'gluons'")

    # Ensure migrations tracking table exists
    cursor = await _db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='_migrations'"
    )
    if not await cursor.fetchone():
        await _db.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await _db.commit()

    # Migration 2: Change gluons.document_id from CASCADE to SET NULL
    # This allows orphan gluons when a document is deleted (user choice)

    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'gluons_document_set_null'"
    )
    if not await cursor.fetchone():
        # Check if gluons table exists before migrating
        cursor = await _db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='gluons'"
        )
        if await cursor.fetchone():
            print("Migrating: Changing gluons.document_id to SET NULL...")

            # Recreate table with SET NULL constraint
            await _db.execute("""
                CREATE TABLE gluons_new (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    content TEXT,
                    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
                    section_id TEXT REFERENCES sections(id) ON DELETE SET NULL,
                    start_offset INTEGER,
                    end_offset INTEGER,
                    color TEXT,
                    parent_gluon_id TEXT REFERENCES gluons_new(id) ON DELETE CASCADE,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)

            # Copy data
            await _db.execute("""
                INSERT INTO gluons_new
                SELECT * FROM gluons
            """)

            # Drop old table and rename
            await _db.execute("DROP TABLE gluons")
            await _db.execute("ALTER TABLE gluons_new RENAME TO gluons")

            # Recreate indexes
            await _db.execute("CREATE INDEX IF NOT EXISTS idx_gluons_document ON gluons(document_id)")
            await _db.execute("CREATE INDEX IF NOT EXISTS idx_gluons_type ON gluons(type)")
            await _db.execute("CREATE INDEX IF NOT EXISTS idx_gluons_parent ON gluons(parent_gluon_id)")

            # Mark migration as done
            await _db.execute(
                "INSERT INTO _migrations (name) VALUES ('gluons_document_set_null')"
            )

            await _db.commit()
            print("Migration complete: gluons.document_id now uses SET NULL")

    # Migration 3: Add bibliographic metadata fields to documents
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'documents_bibcite_fields'"
    )
    if not await cursor.fetchone():
        print("Migrating: Adding bibliographic metadata fields to documents...")

        # SQLite supports ADD COLUMN, so we can add fields directly
        # Check which columns already exist and add missing ones
        cursor = await _db.execute("PRAGMA table_info(documents)")
        existing_columns = {row[1] for row in await cursor.fetchall()}

        new_columns = [
            ("journal", "TEXT"),        # Journal/conference name
            ("volume", "TEXT"),         # Volume number
            ("issue", "TEXT"),          # Issue number
            ("pages", "TEXT"),          # Page range (e.g., "123-145")
            ("doi", "TEXT"),            # Digital Object Identifier
            ("isbn", "TEXT"),           # ISBN for books
            ("issn", "TEXT"),           # ISSN for journals
            ("abstract", "TEXT"),       # Document abstract
            ("keywords", "TEXT"),       # Comma-separated keywords
            ("url", "TEXT"),            # Source URL
            ("editors", "TEXT"),        # Editors (for edited volumes)
            ("edition", "TEXT"),        # Edition (e.g., "2nd")
            ("series", "TEXT"),         # Book series name
        ]

        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                await _db.execute(f"ALTER TABLE documents ADD COLUMN {col_name} {col_type}")

        # Mark migration as done
        await _db.execute(
            "INSERT INTO _migrations (name) VALUES ('documents_bibcite_fields')"
        )

        await _db.commit()
        print("Migration complete: Added bibliographic metadata fields")

    # Migration 4: Add author_gluon_ids for author-as-gluon linking
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'documents_author_gluon_ids'"
    )
    if not await cursor.fetchone():
        print("Migrating: Adding author_gluon_ids field to documents...")

        # Check if column already exists
        cursor = await _db.execute("PRAGMA table_info(documents)")
        existing_columns = {row[1] for row in await cursor.fetchall()}

        if "author_gluon_ids" not in existing_columns:
            await _db.execute("ALTER TABLE documents ADD COLUMN author_gluon_ids TEXT")

        # Mark migration as done
        await _db.execute(
            "INSERT INTO _migrations (name) VALUES ('documents_author_gluon_ids')"
        )

        await _db.commit()
        print("Migration complete: Added author_gluon_ids field")

    # Migration 5: Convert documents table to sources table with JSON metadata
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'documents_to_sources'"
    )
    if not await cursor.fetchone():
        # Check if old documents table exists and sources doesn't
        cursor = await _db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
        )
        has_documents = await cursor.fetchone()

        cursor = await _db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sources'"
        )
        has_sources = await cursor.fetchone()

        if has_documents and not has_sources:
            print("Migrating: Converting documents table to sources table...")
            import json

            # 1. Create new sources table with unified schema
            await _db.execute("""
                CREATE TABLE sources (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'document',
                    author_display TEXT,
                    year INTEGER,
                    url TEXT,
                    content_path TEXT,
                    reading_position TEXT,
                    metadata JSON,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)

            # 2. Migrate documents data to sources
            cursor = await _db.execute("""
                SELECT id, title, author, year, publisher, doc_type, source_type,
                       original_path, extracted_path, reading_position,
                       journal, volume, issue, pages, doi, isbn, issn,
                       abstract, keywords, url, editors, edition, series,
                       pdf_hash, author_gluon_ids, created_at, updated_at
                FROM documents
            """)
            documents = await cursor.fetchall()

            for doc in documents:
                (doc_id, title, author, year, publisher, doc_type, source_type_old,
                 original_path, extracted_path, reading_position,
                 journal, volume, issue, pages, doi, isbn, issn,
                 abstract, keywords, url, editors, edition, series,
                 pdf_hash, author_gluon_ids, created_at, updated_at) = doc

                # Pack BIBCITE and document-specific fields into metadata JSON
                metadata = {
                    "doc_type": doc_type,           # 'book', 'article', 'chapter'
                    "file_type": source_type_old,   # 'pdf', 'epub'
                    "original_path": original_path,
                    "pdf_hash": pdf_hash,
                    "author_gluon_ids": author_gluon_ids,
                    # BIBCITE fields
                    "publisher": publisher,
                    "journal": journal,
                    "volume": volume,
                    "issue": issue,
                    "pages": pages,
                    "doi": doi,
                    "isbn": isbn,
                    "issn": issn,
                    "abstract": abstract,
                    "keywords": keywords,
                    "editors": editors,
                    "edition": edition,
                    "series": series,
                }
                # Remove None values to keep JSON clean
                metadata = {k: v for k, v in metadata.items() if v is not None}

                await _db.execute("""
                    INSERT INTO sources
                    (id, title, source_type, author_display, year, url, content_path,
                     reading_position, metadata, created_at, updated_at)
                    VALUES (?, ?, 'document', ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    doc_id, title, author, year, url, extracted_path,
                    reading_position, json.dumps(metadata), created_at, updated_at
                ])

            print(f"  Migrated {len(documents)} documents to sources table")

            # 3. Create new sections table with source_id
            await _db.execute("""
                CREATE TABLE sections_new (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    title TEXT,
                    level INTEGER,
                    start_offset INTEGER,
                    end_offset INTEGER,
                    order_index INTEGER,
                    parent_id TEXT REFERENCES sections_new(id) ON DELETE SET NULL
                )
            """)

            # Copy sections data
            await _db.execute("""
                INSERT INTO sections_new (id, source_id, title, level, start_offset, end_offset, order_index, parent_id)
                SELECT id, document_id, title, level, start_offset, end_offset, order_index, parent_id
                FROM sections
            """)

            # Drop old sections and rename
            await _db.execute("DROP TABLE sections")
            await _db.execute("ALTER TABLE sections_new RENAME TO sections")

            print("  Migrated sections table (document_id -> source_id)")

            # 4. Create new gluons table with source_id
            await _db.execute("""
                CREATE TABLE gluons_new (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    content TEXT,
                    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
                    section_id TEXT REFERENCES sections(id) ON DELETE SET NULL,
                    start_offset INTEGER,
                    end_offset INTEGER,
                    color TEXT,
                    parent_gluon_id TEXT REFERENCES gluons_new(id) ON DELETE CASCADE,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)

            # Copy gluons data
            await _db.execute("""
                INSERT INTO gluons_new
                (id, type, content, source_id, section_id, start_offset, end_offset,
                 color, parent_gluon_id, created_at, updated_at)
                SELECT id, type, content, document_id, section_id, start_offset, end_offset,
                       color, parent_gluon_id, created_at, updated_at
                FROM gluons
            """)

            # Drop old gluons and rename
            await _db.execute("DROP TABLE gluons")
            await _db.execute("ALTER TABLE gluons_new RENAME TO gluons")

            print("  Migrated gluons table (document_id -> source_id)")

            # 5. Update FTS tables
            await _db.execute("DROP TABLE IF EXISTS documents_fts")
            await _db.execute("DROP TABLE IF EXISTS gluons_fts")

            await _db.execute("""
                CREATE VIRTUAL TABLE sources_fts USING fts5(
                    title,
                    author_display,
                    content='sources',
                    content_rowid='rowid',
                    tokenize='porter unicode61'
                )
            """)

            await _db.execute("""
                CREATE VIRTUAL TABLE gluons_fts USING fts5(
                    content,
                    content='gluons',
                    content_rowid='rowid',
                    tokenize='porter unicode61'
                )
            """)

            # Populate sources_fts
            await _db.execute("""
                INSERT INTO sources_fts (rowid, title, author_display)
                SELECT rowid, title, author_display FROM sources
            """)

            # Populate gluons_fts
            await _db.execute("""
                INSERT INTO gluons_fts (rowid, content)
                SELECT rowid, content FROM gluons WHERE content IS NOT NULL
            """)

            print("  Recreated FTS tables for sources and gluons")

            # 6. Drop old documents table
            await _db.execute("DROP TABLE documents")

            # 7. Recreate indexes
            await _db.execute("CREATE INDEX idx_sources_type ON sources(source_type)")
            await _db.execute("CREATE INDEX idx_sources_year ON sources(year)")
            await _db.execute("CREATE UNIQUE INDEX idx_sources_content_path ON sources(content_path) WHERE content_path IS NOT NULL")
            await _db.execute("CREATE INDEX idx_sections_source ON sections(source_id)")
            await _db.execute("CREATE INDEX idx_gluons_source ON gluons(source_id)")
            await _db.execute("CREATE INDEX idx_gluons_type ON gluons(type)")
            await _db.execute("CREATE INDEX idx_gluons_parent ON gluons(parent_gluon_id)")

            # Mark migration as done
            await _db.execute(
                "INSERT INTO _migrations (name) VALUES ('documents_to_sources')"
            )

            await _db.commit()
            print("Migration complete: documents -> sources")
        elif has_sources:
            # Sources table already exists, just mark migration as done
            await _db.execute(
                "INSERT OR IGNORE INTO _migrations (name) VALUES ('documents_to_sources')"
            )
            await _db.commit()
            print("Migration skipped: sources table already exists")

    # Migration: Backfill author_display with sitename for web sources without authors
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'web_author_sitename_backfill'"
    )
    if not await cursor.fetchone():
        print("Running migration: web_author_sitename_backfill")

        # Update web sources that have no author but have a sitename
        result = await _db.execute("""
            UPDATE sources
            SET author_display = json_extract(metadata, '$.sitename'),
                updated_at = datetime('now')
            WHERE source_type = 'web'
              AND (author_display IS NULL OR author_display = '')
              AND json_extract(metadata, '$.sitename') IS NOT NULL
              AND json_extract(metadata, '$.sitename') != ''
        """)
        updated_count = result.rowcount

        # Rebuild FTS index for affected sources
        # Note: Use DROP/CREATE instead of DELETE to avoid FTS corruption issues
        if updated_count > 0:
            await _db.execute("DROP TABLE IF EXISTS sources_fts")
            await _db.execute("""
                CREATE VIRTUAL TABLE sources_fts USING fts5(
                    title, author_display,
                    content='sources', content_rowid='rowid',
                    tokenize='porter unicode61'
                )
            """)
            await _db.execute("""
                INSERT INTO sources_fts (rowid, title, author_display)
                SELECT rowid, title, author_display FROM sources
            """)

        # Mark migration as done
        await _db.execute(
            "INSERT INTO _migrations (name) VALUES ('web_author_sitename_backfill')"
        )
        await _db.commit()
        print(f"Migration complete: backfilled {updated_count} web sources with sitename")

    # Migration 7: Add captured_via column to gluons for tracking capture source
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'gluons_captured_via'"
    )
    if not await cursor.fetchone():
        print("Migrating: Adding captured_via field to gluons...")

        # Check if column already exists
        cursor = await _db.execute("PRAGMA table_info(gluons)")
        existing_columns = {row[1] for row in await cursor.fetchall()}

        if "captured_via" not in existing_columns:
            await _db.execute("ALTER TABLE gluons ADD COLUMN captured_via TEXT")

        # Mark migration as done
        await _db.execute(
            "INSERT INTO _migrations (name) VALUES ('gluons_captured_via')"
        )
        await _db.commit()
        print("Migration complete: Added captured_via field to gluons")


async def _create_schema():
    """
    Create database tables if they don't exist.
    This is idempotent - safe to run on every startup.
    """

    # Sources table - unified table for all source types (documents, web, threads, media)
    # Type-specific fields stored in metadata JSON column
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'document',  -- 'document', 'web', 'thread', 'media'
            author_display TEXT,        -- Display string for UI
            year INTEGER,
            url TEXT,                   -- Original URL (web/thread/media) or NULL (document)
            content_path TEXT,          -- Path to readable text
            reading_position TEXT,      -- JSON: {section_id, scroll_offset}
            metadata JSON,              -- Type-specific fields (see migration for structure)
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Index for source type filtering
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type)
    """)

    # Index for year filtering/sorting
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_sources_year ON sources(year)
    """)

    # UNIQUE constraint on content_path to prevent duplicates on refresh
    await _db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_content_path
        ON sources(content_path) WHERE content_path IS NOT NULL
    """)

    # Sections table - chapters/headings parsed from content
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS sections (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            title TEXT,
            level INTEGER,              -- Heading level (1, 2, 3)
            start_offset INTEGER,       -- Character position in full text
            end_offset INTEGER,
            order_index INTEGER,        -- For ordering within source
            parent_id TEXT REFERENCES sections(id) ON DELETE SET NULL
        )
    """)

    # Gluons table - universal linkable objects (highlights, notes, tags, journal entries)
    # Named after the particle that binds quarks - knowledge units that bind together
    # source_id uses SET NULL to allow orphan gluons (user choice at delete time)
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS gluons (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,         -- 'highlight', 'note', 'tag', 'journal_entry'
            content TEXT,               -- Text content (header for journal entries)
            source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
            section_id TEXT REFERENCES sections(id) ON DELETE SET NULL,

            -- For highlights: character positions in source
            start_offset INTEGER,
            end_offset INTEGER,
            color TEXT,                 -- 'yellow', 'blue', 'green', 'pink'

            -- For notes attached to highlights
            parent_gluon_id TEXT REFERENCES gluons(id) ON DELETE CASCADE,

            -- Capture source tracking
            captured_via TEXT,          -- 'whatsapp', 'web', null for manual

            -- For journal entries
            body TEXT,                  -- Sub-bullets/details
            completed INTEGER,          -- NULL=not a task, 0=pending, 1=done

            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Links table - references and tags between gluons
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES gluons(id) ON DELETE CASCADE,
            target_id TEXT NOT NULL REFERENCES gluons(id) ON DELETE CASCADE,
            link_type TEXT,             -- 'reference', 'tag'
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Processing jobs table - tracks PDF processing for resume support
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS processing_jobs (
            temp_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            pdf_path TEXT NOT NULL,
            tier TEXT NOT NULL,         -- 'marker', 'dots-ocr'
            status TEXT NOT NULL,       -- 'queued', 'processing', 'complete', 'error', 'cancelled'
            stage TEXT,                 -- 'waiting', 'loading', 'extracting', 'formatting', 'done', 'failed'
            current_page INTEGER DEFAULT 0,
            total_pages INTEGER DEFAULT 0,
            percent INTEGER DEFAULT 0,
            queue_position INTEGER,
            error TEXT,
            output_path TEXT,
            folder_name TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # RunPod jobs table - tracks remote GPU processing on RunPod
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS runpod_jobs (
            job_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            status TEXT NOT NULL,
            current_page INTEGER DEFAULT 0,
            total_pages INTEGER DEFAULT 0,
            folder_name TEXT,
            local_pdf_path TEXT,
            remote_pdf_path TEXT,
            local_output_path TEXT,
            pod_id TEXT,                -- Which pod processed this job
            network_volume_id TEXT,     -- Volume used for processing
            error TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT,
            downloaded_at TEXT,
            finalized_at TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # RunPod pods table - tracks active pods for multi-pod processing
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS runpod_pods (
            pod_id TEXT PRIMARY KEY,
            name TEXT,
            status TEXT,                -- STARTING, RUNNING, EXITED, TERMINATED
            gpu_type TEXT,
            network_volume_id TEXT,
            ssh_host TEXT,
            ssh_port INTEGER,
            cost_per_hr REAL,
            created_at TEXT DEFAULT (datetime('now')),
            terminated_at TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Full-text search for gluons
    await _db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS gluons_fts USING fts5(
            content,
            content='gluons',
            content_rowid='rowid',
            tokenize='porter unicode61'
        )
    """)

    # Full-text search for sources
    await _db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS sources_fts USING fts5(
            title,
            author_display,
            content='sources',
            content_rowid='rowid',
            tokenize='porter unicode61'
        )
    """)

    # Indexes for common queries
    # Note: Some indexes may fail if migration hasn't run yet (old column names)
    # They'll be created by the migration itself
    try:
        await _db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sections_source
            ON sections(source_id)
        """)
    except Exception:
        pass  # Migration will create this

    try:
        await _db.execute("""
            CREATE INDEX IF NOT EXISTS idx_gluons_source
            ON gluons(source_id)
        """)
    except Exception:
        pass  # Migration will create this

    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_gluons_type
        ON gluons(type)
    """)
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_gluons_parent
        ON gluons(parent_gluon_id)
    """)
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_source
        ON links(source_id)
    """)
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_target
        ON links(target_id)
    """)

    # ============================================================
    # Council Tables (LLM analysis)
    # ============================================================

    # Presets - user-editable analysis prompts
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS council_presets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            prompt TEXT NOT NULL,
            model TEXT DEFAULT 'default',
            max_tokens INTEGER DEFAULT 2500,
            is_system INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Conversations - chat history per source
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            source_id TEXT REFERENCES sources(id) ON DELETE CASCADE,
            title TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Messages - individual queries and responses
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS council_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            mode TEXT,
            model TEXT,
            preset_id TEXT,
            context_type TEXT,
            context_offsets TEXT,
            perspectives TEXT,
            usage TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Council indexes
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_council_messages_conv
        ON council_messages(conversation_id)
    """)
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_source
        ON conversations(source_id)
    """)
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_presets_system
        ON council_presets(is_system)
    """)

    # Migration: Add conversation_type column to conversations table
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'conversations_add_type'"
    )
    if not await cursor.fetchone():
        # Check if column exists
        cursor = await _db.execute("PRAGMA table_info(conversations)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "conversation_type" not in columns:
            print("Migrating: Adding conversation_type to conversations...")
            await _db.execute("""
                ALTER TABLE conversations ADD COLUMN conversation_type TEXT DEFAULT 'council'
            """)
            await _db.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_type ON conversations(conversation_type)
            """)

        # Mark migration as done
        await _db.execute(
            "INSERT OR IGNORE INTO _migrations (name) VALUES ('conversations_add_type')"
        )
        await _db.commit()
        print("Migration complete: Added conversation_type column")

    # Migration: Add show_as_quick_action column to council_presets
    # MUST run before seed_system_presets which uses this column
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'presets_add_quick_action'"
    )
    if not await cursor.fetchone():
        # Check if column exists
        cursor = await _db.execute("PRAGMA table_info(council_presets)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "show_as_quick_action" not in columns:
            print("Migrating: Adding show_as_quick_action to council_presets...")
            await _db.execute("""
                ALTER TABLE council_presets ADD COLUMN show_as_quick_action INTEGER DEFAULT 0
            """)

        # Mark migration as done
        await _db.execute(
            "INSERT OR IGNORE INTO _migrations (name) VALUES ('presets_add_quick_action')"
        )
        await _db.commit()
        print("Migration complete: Added show_as_quick_action column")

    # Migration: Add source_types and prompt_full_doc columns to council_presets
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'presets_add_source_types'"
    )
    if not await cursor.fetchone():
        cursor = await _db.execute("PRAGMA table_info(council_presets)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "source_types" not in columns:
            print("Migrating: Adding source_types to council_presets...")
            await _db.execute("""
                ALTER TABLE council_presets ADD COLUMN source_types TEXT DEFAULT NULL
            """)

        if "prompt_full_doc" not in columns:
            print("Migrating: Adding prompt_full_doc to council_presets...")
            await _db.execute("""
                ALTER TABLE council_presets ADD COLUMN prompt_full_doc TEXT DEFAULT NULL
            """)

        await _db.execute(
            "INSERT OR IGNORE INTO _migrations (name) VALUES ('presets_add_source_types')"
        )
        await _db.commit()
        print("Migration complete: Added source_types and prompt_full_doc columns")

    # Migration: Consolidate presets to canonical 7 (remove merged + legacy presets)
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'presets_consolidate_v2'"
    )
    if not await cursor.fetchone():
        print("Migrating: Consolidating presets (removing merged/legacy presets)...")

        # Delete system presets that have been absorbed into others or are legacy
        removed_ids = (
            'key-claims', 'define', 'connect',  # Merged into summarize/explain/analyze
            'summary', 'counterarguments', 'eli5',  # Legacy presets from earlier versions
        )
        for removed_id in removed_ids:
            await _db.execute(
                "DELETE FROM council_presets WHERE id = ? AND is_system = 1",
                [removed_id]
            )

        await _db.execute(
            "INSERT OR IGNORE INTO _migrations (name) VALUES ('presets_consolidate_v2')"
        )
        await _db.commit()
        print("Migration complete: Removed merged/legacy presets")

    # Migration: Rename 'theorize' preset to 'analyze'
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'presets_rename_theorize_analyze'"
    )
    if not await cursor.fetchone():
        print("Migrating: Renaming 'theorize' preset to 'analyze'...")
        await _db.execute(
            "UPDATE council_presets SET id = 'analyze' WHERE id = 'theorize' AND is_system = 1"
        )
        await _db.execute(
            "INSERT OR IGNORE INTO _migrations (name) VALUES ('presets_rename_theorize_analyze')"
        )
        await _db.commit()
        print("Migration complete: Renamed theorize -> analyze")

    # Seed system presets (after migrations add required columns)
    from services.council.presets import seed_system_presets
    await seed_system_presets(_db)

    # Seed/update quick action presets
    from services.council.presets import seed_quick_action_presets
    await seed_quick_action_presets(_db)

    # ============================================================
    # Source-Gluon Links Table (for author, editor, etc. relationships)
    # ============================================================

    # Create source_gluon_links table if it doesn't exist
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS source_gluon_links (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            gluon_id TEXT NOT NULL REFERENCES gluons(id) ON DELETE CASCADE,
            relationship_type TEXT NOT NULL,  -- 'author', 'editor', etc.
            position INTEGER DEFAULT 0,       -- ordering (1st author, 2nd author, etc.)
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Indexes for efficient querying
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_source_gluon_links_source
        ON source_gluon_links(source_id)
    """)
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_source_gluon_links_gluon
        ON source_gluon_links(gluon_id)
    """)
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_source_gluon_links_type
        ON source_gluon_links(relationship_type)
    """)
    # Unique constraint: one relationship per source+gluon+type combo
    await _db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_source_gluon_links_unique
        ON source_gluon_links(source_id, gluon_id, relationship_type)
    """)

    # Migration: Backfill existing author_gluon_ids from metadata
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'backfill_source_gluon_links'"
    )
    if not await cursor.fetchone():
        print("Migrating: Backfilling source_gluon_links from author_gluon_ids...")
        import json as json_mod

        # Find all sources with author_gluon_ids in metadata
        cursor = await _db.execute("""
            SELECT id, metadata FROM sources WHERE metadata IS NOT NULL
        """)
        rows = await cursor.fetchall()

        backfill_count = 0
        for row in rows:
            source_id, metadata_str = row
            if not metadata_str:
                continue
            try:
                metadata = json_mod.loads(metadata_str)
                author_gluon_ids = metadata.get("author_gluon_ids")
                if author_gluon_ids:
                    # Parse if it's a JSON string
                    if isinstance(author_gluon_ids, str):
                        author_gluon_ids = json_mod.loads(author_gluon_ids)
                    # Create link for each author
                    for position, gluon_id in enumerate(author_gluon_ids):
                        link_id = f"sgl_{source_id[:4]}_{gluon_id[:4]}_{position}"
                        await _db.execute("""
                            INSERT OR IGNORE INTO source_gluon_links
                            (id, source_id, gluon_id, relationship_type, position)
                            VALUES (?, ?, ?, 'author', ?)
                        """, [link_id, source_id, gluon_id, position])
                        backfill_count += 1
            except (json_mod.JSONDecodeError, TypeError):
                continue

        # Mark migration as done
        await _db.execute(
            "INSERT INTO _migrations (name) VALUES ('backfill_source_gluon_links')"
        )
        await _db.commit()
        print(f"Migration complete: Backfilled {backfill_count} author links")

    # NOTE: Backfill migration for keywords->tags removed.
    # Tags are now added via AI suggest in the metadata modal.

    # ============================================================
    # Research Sessions Tables (cross-document intelligence)
    # ============================================================

    # Research sessions - chat-centric workspaces for multi-source analysis
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS research_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Session-Source links - which sources belong to which session
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS session_sources (
            session_id TEXT NOT NULL REFERENCES research_sessions(id) ON DELETE CASCADE,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            context_type TEXT DEFAULT 'full',  -- 'full', 'excerpt', 'highlights', 'notes'
            added_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (session_id, source_id)
        )
    """)

    # Session messages - conversation history per session
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS session_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES research_sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,  -- 'user', 'assistant', 'system'
            content TEXT NOT NULL,
            context_snapshot TEXT,  -- JSON: which sources/excerpts were in context
            model_id TEXT,
            usage TEXT,  -- JSON: token counts, cost
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Indexes for research sessions
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_sources_session
        ON session_sources(session_id)
    """)
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_sources_source
        ON session_sources(source_id)
    """)
    await _db.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_messages_session
        ON session_messages(session_id)
    """)

    # Migration: Clean up stale keywords from metadata JSON
    # Keywords were cleaned from source_gluon_links but metadata JSON still had stale data
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'clean_stale_metadata_keywords'"
    )
    if not await cursor.fetchone():
        print("Migrating: Cleaning stale keywords from metadata JSON...")
        import json as json_mod

        cursor = await _db.execute("SELECT id, metadata FROM sources WHERE metadata IS NOT NULL")
        rows = await cursor.fetchall()

        cleaned_count = 0
        for row in rows:
            source_id, metadata_str = row
            if not metadata_str:
                continue
            try:
                metadata = json_mod.loads(metadata_str)

                # Check if source has any tag links
                link_cursor = await _db.execute(
                    "SELECT COUNT(*) FROM source_gluon_links WHERE source_id = ? AND relationship_type = 'tag'",
                    [source_id]
                )
                has_links = (await link_cursor.fetchone())[0] > 0

                # If no links but keywords in metadata, clear them
                if not has_links and ('keywords' in metadata or 'keyword_gluon_ids' in metadata):
                    if 'keywords' in metadata:
                        del metadata['keywords']
                    if 'keyword_gluon_ids' in metadata:
                        del metadata['keyword_gluon_ids']
                    await _db.execute(
                        "UPDATE sources SET metadata = ? WHERE id = ?",
                        [json_mod.dumps(metadata), source_id]
                    )
                    cleaned_count += 1
            except (json_mod.JSONDecodeError, TypeError):
                continue

        # Mark migration as done
        await _db.execute(
            "INSERT INTO _migrations (name) VALUES ('clean_stale_metadata_keywords')"
        )
        await _db.commit()
        print(f"Migration complete: Cleaned stale keywords from {cleaned_count} sources")

    # Migration: Add gluon_id column to conversations table
    # Links a chat conversation to its auto-saved gluon note
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'conversations_add_gluon_id'"
    )
    if not await cursor.fetchone():
        cursor = await _db.execute("PRAGMA table_info(conversations)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "gluon_id" not in columns:
            print("Migrating: Adding gluon_id to conversations...")
            await _db.execute("""
                ALTER TABLE conversations ADD COLUMN gluon_id TEXT
            """)

        await _db.execute(
            "INSERT OR IGNORE INTO _migrations (name) VALUES ('conversations_add_gluon_id')"
        )
        await _db.commit()
        print("Migration complete: Added gluon_id column to conversations")

    # Migration: Add metadata_skip column to sources table
    # Used to exclude sources from batch AI metadata suggestions
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'sources_add_metadata_skip'"
    )
    if not await cursor.fetchone():
        # Check if column exists
        cursor = await _db.execute("PRAGMA table_info(sources)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "metadata_skip" not in columns:
            print("Migrating: Adding metadata_skip to sources...")
            await _db.execute("""
                ALTER TABLE sources ADD COLUMN metadata_skip INTEGER DEFAULT NULL
            """)

        # Mark migration as done
        await _db.execute(
            "INSERT INTO _migrations (name) VALUES ('sources_add_metadata_skip')"
        )
        await _db.commit()
        print("Migration complete: Added metadata_skip column")

    # Migration: Reindex highlight offsets by matching stored text against content files
    # Fixes highlights created with wrong offsets (e.g., in blockquotes where > prefix was stripped)
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'reindex_highlight_offsets'"
    )
    if not await cursor.fetchone():
        print("Migrating: Reindexing highlight offsets...")
        from routers.sources import (
            _parse_sections,
            _reindex_highlights_for_source,
        )

        # Find all sources that have highlights
        cursor = await _db.execute("""
            SELECT DISTINCT g.source_id, s.content_path
            FROM gluons g
            JOIN sources s ON g.source_id = s.id
            WHERE g.type = 'highlight' AND g.content IS NOT NULL
              AND s.content_path IS NOT NULL
        """)
        source_rows = await cursor.fetchall()

        total_fixed = 0
        total_correct = 0
        total_failed = 0
        sources_processed = 0

        for source_id, content_path in source_rows:
            content_file = Path(content_path)
            if not content_file.exists():
                continue

            content = content_file.read_text(encoding="utf-8")
            sections = _parse_sections(content, source_id)
            stats = await _reindex_highlights_for_source(
                _db, source_id, content, sections
            )
            total_fixed += stats["fixed"]
            total_correct += stats["already_correct"]
            total_failed += stats["failed"]
            sources_processed += 1

        # Mark migration as done
        await _db.execute(
            "INSERT INTO _migrations (name) VALUES ('reindex_highlight_offsets')"
        )
        await _db.commit()
        print(
            f"Migration complete: Reindexed highlights across {sources_processed} sources "
            f"({total_fixed} fixed, {total_correct} already correct, {total_failed} failed)"
        )

    # Migration: Backfill cost_usd into existing RLM message usage data
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'rlm_backfill_cost_usd'"
    )
    if not await cursor.fetchone():
        from services.chat.config import CHAT_MODELS

        print("Running migration: rlm_backfill_cost_usd...")
        cursor = await _db.execute("""
            SELECT id, model_id, usage FROM session_messages
            WHERE context_snapshot LIKE '%"type": "rlm"%'
            AND usage IS NOT NULL
        """)
        rows = await cursor.fetchall()
        updated = 0
        for msg_id, model_id, usage_json in rows:
            try:
                usage = json.loads(usage_json)
                if "cost_usd" in usage:
                    continue  # Already has cost

                config = CHAT_MODELS.get(model_id)
                if not config:
                    continue

                pricing = config.get("pricing", {"input": 0, "output": 0})
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)

                # Calculate cost (no cache breakdown available for historical data)
                cost = (input_tokens / 1_000_000) * pricing["input"] + \
                       (output_tokens / 1_000_000) * pricing["output"]
                usage["cost_usd"] = round(cost, 6)

                await _db.execute(
                    "UPDATE session_messages SET usage = ? WHERE id = ?",
                    [json.dumps(usage), msg_id]
                )
                updated += 1
            except (json.JSONDecodeError, KeyError):
                continue

        await _db.execute(
            "INSERT INTO _migrations (name) VALUES ('rlm_backfill_cost_usd')"
        )
        await _db.commit()
        print(f"Migration complete: Backfilled cost for {updated} RLM messages")

    # Migration: Add journal entry fields to gluons (body, completed)
    cursor = await _db.execute(
        "SELECT name FROM _migrations WHERE name = 'gluons_add_journal_fields'"
    )
    if not await cursor.fetchone():
        print("Migrating: Adding journal entry fields to gluons...")

        cursor = await _db.execute("PRAGMA table_info(gluons)")
        existing_columns = {row[1] for row in await cursor.fetchall()}

        if "body" not in existing_columns:
            await _db.execute("ALTER TABLE gluons ADD COLUMN body TEXT")

        if "completed" not in existing_columns:
            await _db.execute("ALTER TABLE gluons ADD COLUMN completed INTEGER")

        # Index for efficient date-ordered journal queries
        await _db.execute("""
            CREATE INDEX IF NOT EXISTS idx_gluons_journal
            ON gluons(type, created_at DESC)
        """)

        await _db.execute(
            "INSERT INTO _migrations (name) VALUES ('gluons_add_journal_fields')"
        )
        await _db.commit()
        print("Migration complete: Added body and completed columns to gluons")

    await _db.commit()
    print("Database schema created/verified")


async def reset_db():
    """
    Drop all tables and recreate schema.
    WARNING: This deletes all data!
    Only use for development/testing.
    """
    global _db

    if _db is None:
        await init_db()

    # Drop tables in reverse order (respecting foreign keys)
    await _db.execute("DROP TABLE IF EXISTS links")
    await _db.execute("DROP TABLE IF EXISTS gluons_fts")
    await _db.execute("DROP TABLE IF EXISTS sources_fts")
    await _db.execute("DROP TABLE IF EXISTS documents_fts")  # Legacy
    await _db.execute("DROP TABLE IF EXISTS gluons")
    await _db.execute("DROP TABLE IF EXISTS rems")  # Legacy table name
    await _db.execute("DROP TABLE IF EXISTS sections")
    await _db.execute("DROP TABLE IF EXISTS sources")
    await _db.execute("DROP TABLE IF EXISTS documents")  # Legacy
    await _db.commit()

    # Recreate schema
    await _create_schema()
    print("Database reset complete")
