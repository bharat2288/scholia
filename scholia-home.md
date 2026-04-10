---
type: project-home
project: scholia
date: 2026-03-07
cssclasses:
  - project-home
---
# Scholia
*[[dev-hub|Hub]] · [[README|GitHub]]*
<span class="hub-status">Bhaforge OCR is deployed and validated end-to-end with restart-safe resume. Next: capture OCR metrics/history and clean up the default 8200 backend path.</span>

Marginal notes and annotations system. OCR-processed documents, source ingestion, research sessions, WhatsApp integration.

![[v_library.png]]

## Specs

```base
filters:
  and:
    - file.folder.contains("specs/scholia")
    - type != "spec-prompts"
properties:
  "0":
    name: file.link
    label: Spec
  "1":
    name: type
    label: Type
  "2":
    name: date
    label: Date
  "3":
    name: created_by
    label: Created By
  "4":
    name: file.mtime
    label: Modified
views:
  - type: table
    name: All Specs
    order:
      - type
      - file.name
      - file.mtime
      - file.backlinks
    sort:
      - property: file.mtime
        direction: DESC
      - property: type
        direction: ASC
```

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

