# Utility infrastructure laws

<!--
Status: Canonical TRUTH — engineering mandates promoted from convergence audit.
Last updated: 2026-04-04
Source rationale: docs/02_ACTIVE_DESIGN/SYSTEM_UTILITY_CONVERGENCE_AUDIT.md (final answer + convergence map)
-->

**Purpose:** Declare **strict mandates** for cross-surface **utility infrastructure**. This is not a product redesign; it names what **must** converge so Atria behaves as **one system** rather than isolated tabs. Implementation may lag; **new work** shall not contradict these laws without an explicit TRUTH revision.

**Relationship:** Pairs with `TRUTH_CONVERGENCE.md` (locked decision: Utility Infrastructure Convergence), philosophy **#1 Traceability** and **#7 Execution seam** in `GLOBAL_PHILOSOPHY_INTEGRATION_MATRIX.md`, and server contracts `local_ai/council_preflight.py` / `build_enriched_council_context`.

---

## Mandates

### 1. Council context assembly

There shall be **one** client-side **council preflight composer** (or successor module with the same contract) that all surfaces use when assembling context for **`POST /run`** and council **stream** paths. Optional **digression** and **conversation-subject** helpers shall feed that composer, not parallel ad hoc payloads.

The client assembly **shall** remain aligned with server parsing and enrichment: `council_preflight.parse_preflight_from_request` and `build_enriched_council_context` (and successors) are the **canonical** shape expectations. Surfaces **shall not** introduce alternate “what Zenaf saw” bundles for the same run class without updating TRUTH and server contract docs.

### 2. Trace and routing emission

There shall be **one** thin **shared layer** (or clearly named successor pattern) so every AI-touching client path produces a consistent **`AiActionTrace`** and **`RunRoutingContext`**—including stable **`surface`**, **`action_intent`**, and privacy / externalization fields—without each tab re-implementing `createAiActionTrace` + ad hoc routing objects.

**Exemptions** remain governed by `TRUTH_CONVERGENCE` (full trace coverage or named exempt in `aiTraceExemptRegistry.ts`); this law **does not** relax trace law—it **narrows** how new surfaces satisfy it.

### 3. Focus and selection snapshot

There shall be a **single conceptual system focus model**—“where the user is working”—with **per-surface adapters** (Vision Execution fields, workspace path, Content brief, and future surfaces). Council, voice insertion, and preflight **VE selection** blocks **shall** derive from that model (directly or via the preflight composer), not from incompatible parallel focus state.

Surface-specific **widgets** may remain local; the **snapshot** fed into council and shared actions **shall not** fork into incompatible semantics.

### 4. Signal read models (developmental guidance and execution-flow)

**Developmental guidance context** and **execution-flow readings** **shall** be treated as **reusable read-model packages**, assembled through shared builders (e.g. developmental guidance builder, execution-flow fetch helpers)—not as App-only or Map-only private wiring.

New consumers **shall** reuse those packages or extend them in one place; **shall not** duplicate fetch/assemble logic for the same signals under different module names without TRUTH exception.

### 5. Review and staging frame

There shall be **one** shared **extract → stage → human confirm** interaction **pattern** (state machine and UX contract at the law level). Meeting capture is the **reference instance**; thread handoff, content extractions, and future surfaces **shall** plug into the **same frame** with **adapters** for payload shape—not wholly separate “review languages” for the same mental model.

Domain-specific **bucket schemas** (e.g. meeting idea vs initiative types) **may** stay local to their feature; the **frame** (stage, review, confirm, trace handoff) **shall** converge.

### 6. Navigation and open-entity

There shall be **one** **deep-link or open-entity** contract so “open this id in the correct tab and selection” **shall not** be re-invented per surface (Radar callbacks, Map handlers, search results, etc.). Parent wiring **shall** delegate to that contract as it is introduced or extended.

Until a central module exists, **new** navigation entry points **shall** match the emerging shared signature documented next to this file or in `SYSTEM_UTILITY_CONVERGENCE_AUDIT.md` follow-ons—**shall not** add a third incompatible callback pattern without TRUTH update.

---

## Boundary: what legitimately stays local

The following **remain local** by law—**provided** they **call into** the shared infrastructure above for council context, trace/routing, focus snapshot, signal read models where applicable, staging frame, and open-entity:

- **Presentation and layout** (tables, panels, streaming transcript chrome, seat rendering).
- **Graph layout and map physics** (React Flow, edges, map-only overlays).
- **Domain-specific editors and schemas** (VE entity types, initiative/project/task shapes, brief schema, meeting buckets).
- **Folder file tree and organizer copy** (tree UI; context still feeds shared composer/adapters).
- **Demo or seed copy** (e.g. Radar demo role summaries) until productized.
- **Perspective workout pedagogy** (slots, workout content); routing/trace **shape** still obeys mandate **2** and preflight **shape** obeys **1**.

---

## Non-goals (this document)

- **No** mandate to refactor existing code on a fixed schedule; **yes** mandate that **new** surfaces and **touched** integration paths **move toward** compliance.
- **No** replacement for `FRUIT_MINT_POLICY.md`, charter trace rows, or exempt registry—this file **composes** with them.

---

## Related documents

| Document | Role |
|----------|------|
| `docs/02_ACTIVE_DESIGN/SYSTEM_UTILITY_CONVERGENCE_AUDIT.md` | Discovery, asymmetries, owner hints |
| `TRUTH_CONVERGENCE.md` | Locked decision row |
| `GLOBAL_PHILOSOPHY_INTEGRATION_MATRIX.md` | Trace (#1), execution seam (#7), developmental (#12) alignment |
