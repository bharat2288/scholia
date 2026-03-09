---
type: project-home
project: scholia
date: 2026-03-07
cssclasses:
  - project-home
---
# Scholia
*[[dev-hub|Hub]] · [[README|GitHub]]*
<span class="hub-status">Impact Graph declaration complete — 65 nodes, 98 edges, 12 traced events with read-side propagation</span>

Marginal notes and annotations system. OCR-processed documents, source ingestion, research sessions, WhatsApp integration.

![[v_library.png]]

## Specs

```dataview
TABLE rows.file.link as Specs
FROM "scholia/specs"
WHERE type AND type != "spec-prompts"
GROUP BY type
SORT type ASC
```

> [!warning]- Open Errors (`$= dv.pages('"knowledge/exports/errors"').where(p => p.project == "scholia" && !p.resolved).length`)
> ```dataview
> TABLE module, date
> FROM "knowledge/exports/errors"
> WHERE project = "scholia" AND resolved = false
> SORT date DESC
> LIMIT 5
> ```

> [!info]- Decisions (`$= dv.pages('"knowledge/exports/decisions"').where(p => p.project == "scholia").length`)
> ```dataview
> TABLE date
> FROM "knowledge/exports/decisions"
> WHERE project = "scholia"
> SORT date DESC
> LIMIT 5
> ```
>
> > [!info]- All Decisions
> > ```dataview
> > TABLE date
> > FROM "knowledge/exports/decisions"
> > WHERE project = "scholia"
> > SORT date DESC
> > ```

> [!tip]- Learnings (`$= dv.pages('"knowledge/exports/learnings"').where(p => p.project == "scholia").length`)
> ```dataview
> TABLE tags
> FROM "knowledge/exports/learnings"
> WHERE project = "scholia"
> SORT date DESC
> LIMIT 5
> ```
>
> > [!tip]- All Learnings
> > ```dataview
> > TABLE tags
> > FROM "knowledge/exports/learnings"
> > WHERE project = "scholia"
> > SORT date DESC
> > ```

> [!abstract]- Project Plans (`$= dv.pages('"knowledge/plans"').where(p => p.project == "scholia").length`)
> ```dataview
> TABLE title, default(date, file.ctime) as Date
> FROM "knowledge/plans"
> WHERE project = "scholia"
> SORT default(date, file.ctime) DESC
> ```

> [!note]- Sessions (`$= dv.pages('"knowledge/sessions/scholia"').length`)
> ```dataview
> TABLE topic
> FROM "knowledge/sessions/scholia"
> SORT file.mtime DESC
> LIMIT 5
> ```
>
> > [!note]- All Sessions
> > ```dataview
> > TABLE topic
> > FROM "knowledge/sessions/scholia"
> > SORT file.mtime DESC
> > ```
