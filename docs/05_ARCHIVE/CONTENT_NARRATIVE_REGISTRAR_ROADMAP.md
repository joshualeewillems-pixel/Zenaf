# Content: narrative registrar roadmap (system notes)

This document captures **future** product/backend direction for the Content area. It complements what ships today: **content briefs** (`content_briefs`), **script/newsletter** generation via `/run`, and **Vision Execution** links on the brief payload.

## North star (product intent)

- Users journal and/or chat with the council, **save a durable record**, and **attach** it to initiatives/projects/tasks as they choose.
- Records can be **transformed** into richer artifacts (comic, short film sequence, song, …). Outputs contribute to **candidate token-bearing narrative units** whose weight reflects narrative depth, form, and **transferable usefulness** to others (symbolic/metaphoric reuse — on-chain optional later).
- **Personal registrar**: records, artifacts, links, stylization, token candidates, **backlash / resistance** narratives (regressions, repeating “dragons”), not only success arcs.
- **Global registrar**: consent-first fusion of **anonymized structural patterns** (not raw cross-user identity by default), to suggest guidance framed through **other users’ tokens as metaphor** for the receiver’s progression, needs, and aspirations — combined with world myth / hero’s-journey-style **algorithmic narrative state** (always **interpretation**, never final diagnosis).

## What exists today (handshake anchors)

| Piece | Location / notes |
|--------|------------------|
| Brief storage | `content_briefs` in VE SQLite; CRUD `GET/POST/PATCH /vision-execution/content-briefs` |
| VE attachment | Payload: `linked_initiative_id`, `linked_project_id`, `linked_task_ids`, … |
| Text transforms | `/run` modes `content_script`, `content_newsletter` |
| Transcript tooling | Transcript sorter + decisions path (see content audit doc in archive) |
| Traces | Client content trace helpers + server AI action trace hooks |

## Suggested implementation phases (backend-heavy)

1. **Origin** — Journal table + council snapshot persistence + link model to VE (or promote → `brief_id`).
2. **Transform** — `content_artifacts` (or equivalent) + new `/run` modes or async jobs for non-text media.
3. **Personal registrar** — Aggregating APIs over records + artifacts + token candidate rows + resistance events.
4. **Narrative-state snapshots** — Lightweight phase/metaphor hints with `disclaimer_version` and confidence.
5. **Global resonance** — Opt-in, feature extraction without raw text in shared store; similarity read path for guidance.
6. **Valuation / reuse metrics** — Log reuse events to score candidates; blockchain adapter only if product commits.

## Caution (same as UI)

Narrative inference is **candidate** and **probabilistic**. Copy and persistence should never imply objective truth about a person’s life or character.

## Related

- Cursor plan: `content_tab_narrative_rewrite` (UI framing + expanded backend sketch).
- Archive: `docs/05_ARCHIVE/CONTENT_TAB_EXTRACTION_AUDIT.md` (endpoint inventory).
