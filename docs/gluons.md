# Gluons: The Knowledge Graph

> Named after the particles that bind quarks together — gluons are the connective tissue of your research library.

---

## What's a Gluon?

In particle physics, gluons are the force carriers that hold quarks together inside protons and neutrons. In Scholia, a gluon is any piece of knowledge that connects ideas: a **note**, a **tag**, a **reference**, or a **person**.

Everything that isn't a source document is a gluon. Your highlights become gluons. Your margin notes are gluons. Your tags, your author entries, your cross-references — all gluons. This uniform model means the knowledge graph doesn't care about type boundaries. A tag can link to a note that references a person who authored a source. It's gluons all the way down.

---

## The Data Model

### Gluon Types

| Type | What It Represents | Created By |
|------|-------------------|------------|
| `highlight` | A marked passage in a source | Highlighting text in the Reader |
| `note` | A free-form annotation | Writing in the sidebar or Knowledge view |
| `tag` | A categorical label | Typing `##tagname` in a note or via metadata |
| `person` | An author or referenced individual | Metadata entry or `##person`-tagged note |

### Relationships

Gluons connect to each other and to sources through two relationship types:

**Source → Gluon links** (`source_gluon_links` table):
- A highlight belongs to a source (at a specific character offset)
- A note is attached to a source
- A tag categorizes a source
- A person authored a source

**Gluon → Gluon links** (`links` table):
- A note references another gluon via `[[reference name]]`
- A note is tagged via `##tagname`
- Any gluon can link to any other gluon

This dual-relationship system means you can ask both "what gluons does this source have?" and "what other gluons does this gluon connect to?"

---

## The Linking Syntax

### Tags: `##tagname`

Write `##methodology` in a note, and Scholia:
1. Checks if a tag gluon named "methodology" exists
2. Creates it if not (get-or-create pattern)
3. Creates a link from your note to that tag

Tags are stored lowercase, no spaces. `##Machine Learning` becomes `machinelearning`. This normalization prevents "Machine Learning" and "machine learning" from being separate tags.

### References: `[[name]]`

Write `[[Clark's extended mind thesis]]` in a note, and Scholia:
1. Checks if a gluon with that title exists
2. Creates a reference gluon if not
3. Creates a bidirectional link

This is where the RemNote DNA shows. In RemNote, `[[references]]` create bidirectional links between documents. In Scholia, they create links between gluons. The difference is that Scholia's links are first-class objects — you can navigate from any gluon to everything it connects to.

### Backlinks

Every gluon has a backlinks view: "What links to this?" If you've tagged five notes with `##methodology`, opening the methodology tag shows all five notes. If three different notes reference `[[Clark's extended mind thesis]]`, that reference gluon shows all three.

Backlinks are computed at query time, not stored. This means they're always up-to-date — no stale link maintenance.

---

## Debt to RemNote

I built this after years of heavy RemNote use, and the intellectual debt is real.

RemNote's fundamental unit is the **Rem** — outwardly called "rems," internally represented as "quanta" in their backend. Everything in RemNote is a Rem: a note, a flashcard, a document, a folder. This uniformity is what makes RemNote's bidirectional linking work — you're not linking "notes to documents" or "cards to pages," you're linking Rems to Rems. The type system is an overlay on a uniform base unit.

Scholia's gluon system is directly modeled on this insight. Where RemNote has Rems, Scholia has gluons. The naming is different (particle physics vs. cognitive science metaphor), but the architectural principle is identical: make everything the same kind of object, then let the connections emerge.

That said, RemNote's Rem system is far more mature. Their portal system (live embedding), spaced repetition integration, hierarchical document structure, and collaborative features are years ahead of what Scholia currently offers. I've learned a lot from studying their design, and there's considerably more to learn. The gluon system is functional and useful for my workflow, but it's an honest v1 — not a feature-complete alternative.

Three specific lessons shaped the current design:

### 1. Highlights Should Be Objects

In most PDF readers, a highlight is a visual overlay. You can see it, but you can't do anything with it. In RemNote, highlights are first-class objects that can be tagged, linked, and searched. Scholia inherits this: every highlight is a gluon with its own links and metadata.

This means you can:
- Tag a highlight with `##key-claim` and later find all key claims across your library
- Attach a note to a highlight and link that note to other ideas
- Search for highlights by color (yellow = important, blue = methodology, green = evidence, pink = question)

### 2. Tags Are Better Flat

RemNote has hierarchical tags (tag trees). In practice, I spent more time organizing the hierarchy than using it. Scholia keeps tags flat. If you need hierarchy, use naming conventions: `##methods-qualitative`, `##methods-quantitative`. The search is fast enough that you don't need a tree to find things.

### 3. Everything Should Be Searchable

Scholia indexes all gluon content with FTS5 (SQLite's full-text search). Notes, tags, highlights, references — all searchable from a single query box. The Knowledge view is essentially a search-first interface: type a query, see everything that matches across your entire knowledge graph.

---

## Batch Operations

The metadata workflow often creates tags and people in bulk. When the AI suggests "tags: distributed-cognition, extended-mind, embodied-cognition" for a paper, the frontend needs to create three tag gluons and link them to the source — ideally in one request, not three.

The `/tags/batch` and `/people/batch` endpoints handle this. They accept arrays of names, run get-or-create for each, and return all results. This reduces round-trips from N to 1 for bulk metadata operations.

---

## What's Coming: Portals

The gluon system currently supports linking *to* content. The next evolution is **portals** — embedding content *from* one gluon inside another.

Imagine writing a note about distributed cognition. Instead of saying "see Clark's argument on page 47," you embed that passage directly:

```
My analysis of distributed cognition draws on several frameworks:

{{embed: highlight_id_123}}

This connects to Hutchins' earlier work on...

{{embed: note_id_456}}
```

The embedded content stays live — if you update the original highlight's note, the embedded version updates too. This is how RemNote's "portals" work, and it's one of the most powerful features for building arguments from your reading.

Implementation-wise, portals would be:
- A new link type (`embed`) in the gluon-to-gluon relationship table
- Frontend rendering that resolves `{{embed: id}}` to the gluon's content
- Update propagation (the embedded view is always a live reference, not a copy)

This is on the roadmap but not yet implemented.

---

## Design Decisions

### Why "Gluon" and Not "Note"?

Because not everything is a note. A tag isn't a note. A person isn't a note. A highlight isn't a note. But they're all knowledge objects that participate in the same graph. "Gluon" captures what they have in common: they bind ideas together.

The name also signals that this isn't just a note-taking system. It's a knowledge graph where the connections matter as much as the content.

### Why Get-or-Create?

When you type `##methodology` in ten different notes, you want one tag, not ten. The get-or-create pattern ensures that tags and references converge naturally. You never have to "manage" your tags — just use them, and the system handles deduplication.

### Why Dual Relationship Tables?

Source → Gluon relationships have different semantics than Gluon → Gluon relationships. A highlight *belongs to* a source at a specific offset. A note *references* another note conceptually. Forcing these into one table would require nullable columns and type-checking everywhere.

Two tables, two purposes. The source link table carries offset data, position, color. The gluon link table carries link type (reference, tag) and direction.

### Why FTS5?

SQLite's FTS5 is remarkably good for a single-user application. It supports phrase queries, prefix matching, boolean operators, and ranking — all without an external search service. For a local-first tool that might have 10,000 gluons, FTS5 is more than sufficient. No Elasticsearch, no Typesense, no network dependency.
