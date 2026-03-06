---
type: project-home
project: scholia
date: 2026-03-07
---
# Scholia

Marginal notes and annotations system. OCR-processed documents, source ingestion, research sessions, WhatsApp integration.

## Specs

- [[design|Design]]
- [[status|Status]]
- [[pipeline|Pipeline]]
- [[pipeline-whatsapp|WhatsApp Pipeline]]
- [[codemap|Codemap]]

## Documents

```dataview
TABLE type, file.mtime as Modified
FROM "scholia/specs"
WHERE type AND type != "spec-prompts"
SORT file.mtime DESC
```

## Open Errors

```dataview
TABLE module, date
FROM "knowledge/exports/errors"
WHERE project = "scholia" AND resolved = false
SORT date DESC
LIMIT 5
```

## Recent Decisions

```dataview
TABLE date
FROM "knowledge/exports/decisions"
WHERE project = "scholia"
SORT date DESC
LIMIT 5
```

## Recent Learnings

```dataview
TABLE tags
FROM "knowledge/exports/learnings"
WHERE project = "scholia"
SORT date DESC
LIMIT 5
```

## Recent Sessions

```dataview
TABLE topic
FROM "knowledge/sessions/scholia"
SORT file.mtime DESC
LIMIT 5
```

## GitHub

- [[README]]
