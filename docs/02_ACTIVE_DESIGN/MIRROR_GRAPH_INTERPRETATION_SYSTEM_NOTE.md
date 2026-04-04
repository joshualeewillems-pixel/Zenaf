# Mirror graph interpretation — system note (strong architectural intent)

<!--
Status: Active direction (North Star)
Last updated: 2026-03-29
Owner context: Aligns intake, profile, files, meetings, and future surfaces on one inspectable contract.
-->

## 1. Declared intent

**Atria should push as far as is responsible toward a single pattern:** incoming evidence is **interpreted against an existing or implied system graph**, and the system emits **explicit proposed graph operations** (not only labels or free text). Humans mediate before durable writes. Automation may assist ranking and prefill, not silent commitment.

This is **strong intent**: new features should default to this shape; existing flows should **migrate toward** it when touched, unless a brief exception is documented.

## 2. Definitions

- **Graph (mirror context):** The set of stable entities / records the user already cares about—Vision Execution ideas/initiatives/projects/tasks/people/assets, intake mirror rows, core profile structured fields, folder taxonomy, etc. The exact *schema* per domain differs; the **envelope** is shared.
- **Interpretation:** Classification of a piece of evidence **relative to that graph** (e.g. enrichment vs amendment vs new child vs new node vs signal-only).
- **Proposed operation:** A concrete suggested mutation: **action** + optional **payload** + optional **targetId** + **confidence**, suitable for staging/review/commit—not a replacement for extraction or judgment depth, but the **bridge** to execution.

## 3. Canonical envelope (target contract)

Implementations may extend with namespaced fields, but **core fields** should converge on:

| Field | Purpose |
|-------|---------|
| `type` | Interpretation class: `existing_enrichment` \| `existing_amendment` \| `child_of_existing` \| `genuinely_new` \| `signal_only` |
| `targetId` | Existing graph node when applicable |
| `confidence` | Heuristic or model score, inspectable |
| `action` | Operational verb: `update` \| `patch` \| `create_child` \| `create_new` \| `ignore` |
| `payload` | Prefill: `title`, `description`, `notes`, `parentId`, `fieldsToPatch`, etc. |

**Mapping (normative):** `existing_enrichment` → `update`; `existing_amendment` → `patch`; `child_of_existing` → `create_child`; `genuinely_new` → `create_new`; `signal_only` → `ignore`.

**Reference implementation (meetings):** `local_ai/vision_execution/graph_interpretation.py` runs **after** `post_process_extraction`, rule-first, no extra LLM. **Frontend** types and staging: `frontend/src/meeting-intelligence/types.ts`, `stagingHelpers.ts`, `extractionParser.ts`.

## 4. Principles (non-negotiable for this direction)

1. **Separate extraction from interpretation.** Extractors produce candidate rows; interpretation consumes rows + context graph. Do not collapse into one opaque “AI said do X.”
2. **Prefer cheap, inspectable interpretation first** (rules, similarity, existing match ids, `possibleMatches`); add LLM layers only where necessary and keep them **after** or **beside** the rule pass, never as the only articulation of “what to do.”
3. **No auto-apply of high-impact graph writes** from interpretation alone—staging, review, or explicit policy gates.
4. **Same review primitives across surfaces** where possible: show classification, proposed action, payload prefill, confidence, and lineage (source excerpt / judgment id when available).
5. **Mediation-friendly:** interpretation outputs should be loggable and explainable in council/intake/profile UIs (see `docs/MEDIATION_OPERATIONAL_NOTE.md`).

## 5. Subsystems — alignment depth and priority

Rough ordering for **how deep to push** when engineering time appears (deeper = shared envelope + staged ops + UI hooks):

| Subsystem | Alignment | Depth | Notes |
|-----------|-----------|-------|--------|
| **Meeting extraction → VE** | In progress | **Deep** | `interpret_against_graph`; extend only via interpretation module + types, not by bloating extractors. |
| **Core profile reconcile** | High value | **Deep** | Already “propose → review → apply.” Map field-level proposals to `patch`/`update` + `fieldsToPatch` on structured keys; keep LLM as proposer. See `docs/02_ACTIVE_DESIGN/CORE_PROFILE_ARCHITECTURE.md`. |
| **Intake (email/fax) → queue → mirror** | High value | **Medium → deep** | Today: category/lane/judgment. Add interpretation vs VE or case graph where product warrants; reuse envelope on `IntakeItem` or mirror sidecar. See `docs/DATA_FLOW.md`. |
| **File steward / folder sorting** | Medium | **Medium** | Graph = taxonomy + linked entities; ops = move, tag, create_child folder, ignore. |
| **Personal inbox classifier** | Medium | **Medium** | Same envelope as clinic intake where unified UX is desired. |
| **Presort / commit paths** | High | **Deep** | Already entity-match oriented; surface `action`/`payload` alongside `acceptedExistingId` / `parentLink` to reduce duplicate concepts. |
| **Harvest / rolling synthesis** | Lower until scoped | **Shallow** | When artifacts become graph-addressable, attach interpretation to harvested rows before commit. |

## 6. What we are explicitly *not* claiming yet

- A single **Subject/Node** runtime refactor (see `SYSTEM_REFERENCE.md` Part II §2.1)—interpretation is **compatible** with that projection but does not require it.
- Replacing **judgment chains** or council artifacts with interpretation; interpretation should **feed** or **label** proposals those systems already carry.
- **Uniform LLM prompts** across modules—only a uniform **output contract** where it helps the product.

## 7. Implementation sequencing (when building)

1. **Schema first in the domain** that already has staging (meetings ✓; next best: profile reconcile or intake detail).
2. **Rule-based interpreter** mirroring `graph_interpretation` patterns (thresholds, match ids, title similarity).
3. **Wire through API** and **parser** so clients never drop fields.
4. **UI: one row** shows interpretation + suggested op + prefill; commit path consumes payload where safe.
5. **Extract shared helper** (optional): e.g. `local_ai/interpretation/schema.py` or TS shared types package—**only after** a second domain proves duplication pain.

## 8. Related documents

- `docs/01_TRUTH/SYSTEM_REFERENCE.md` — Part II §2.5 (summary pointer)
- `docs/DATA_FLOW.md` — intake → mirror
- `docs/02_ACTIVE_DESIGN/CORE_PROFILE_ARCHITECTURE.md` — reconcile review model
- `docs/MEDIATION_OPERATIONAL_NOTE.md` — inspectable decisions
- `docs/FILE_SORTING_WORKSPACE_ORGANIZER_ARCHITECTURE.md` — file routing

## 9. Change log

- **2026-03-29:** Initial system note; records strong intent and subsystem map after meeting `interpret_against_graph` + `action`/`payload` extension.
