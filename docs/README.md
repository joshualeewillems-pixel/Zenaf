# Zenaf documentation

**Note:** This README describes the **target** folder layout and **current** layout. **Truth docs** live under **`docs/01_TRUTH/`**. **High-signal design docs** live under **`docs/02_ACTIVE_DESIGN/`** (see that folder’s `README.md`). **Bounded implementation plans** live under **`docs/03_IMPLEMENTATION_PLANS/`** (see that folder’s `README.md`). **Reference / spec / lookup docs** live under **`docs/04_REFERENCE/`** (see that folder’s `README.md`). **Superseded or frozen docs** live under **`docs/05_ARCHIVE/`**. Other docs remain in the flat `docs/` root until later moves.

How this folder is organized, what to trust, and where to put new docs.

---

## One doc per category (whole system)

Use this when you want a **single** canonical pointer per question:

| Category | Best single document | Notes |
|----------|----------------------|--------|
| **Current state** (what is implemented, partial, stubbed, not built; surfaces and AI flows) | **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`** | Operational “as-built + gaps”; update when shipping or wiring changes. |
| **Future goals & direction** (philosophy, staged projection, planned evolution) | **`docs/01_TRUTH/SYSTEM_REFERENCE.md`** | Read **Part II** (projection), **Part III** (phased plans), **Part IV §4.3–4.5** (planned vs current summary). For **ticket-level backlog** next to that narrative, also scan **`ACTIVE_VS_PLANNED.md`** § *Planned / Not Yet Built*. |
| **Whole system in one file** (intent + philosophy + definitions + consolidated snapshot) | **`docs/01_TRUTH/SYSTEM_REFERENCE.md`** | Single merged reference; pair with **`ACTIVE_VS_PLANNED.md`** when you care about exhaustive flow-by-flow reality. |
| **Repo layout, modules, build / tooling** | **`docs/01_TRUTH/CODEBASE_INVENTORY.md`** | Overview + how to run; not a substitute for **`ACTIVE_VS_PLANNED`** on product gaps. |
| **Enforcement / routing / persistence rules** | **`docs/01_TRUTH/CODEBASE_TRUTH_RULES.md`** | “Must” behaviors for code and LLM paths. |

---

## Read first (current paths)

**For current product and code reality, read `docs/01_TRUTH/ACTIVE_VS_PLANNED.md` early and often.** It is one of the most important **current-state** documents: what is implemented, partial, stubbed, or not built.

Then, in order:

1. **`docs/01_TRUTH/`** — **Migrated truth docs** (read these first for as-built reality):
   - **`docs/01_TRUTH/CODEBASE_TRUTH_RULES.md`**
   - **`docs/01_TRUTH/CODEBASE_INVENTORY.md`**
   - **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`**
   - **`docs/01_TRUTH/SYSTEM_REFERENCE.md`**
   - **`docs/01_TRUTH/BOOT_FLOW.md`**
   - **`docs/01_TRUTH/VISION_MAP_AND_ZEN_PROJECTION.md`** — Vision map + sand + growth triad (where it is, where it’s going, canonical files).  
   Still in **`docs/`** root (not moved yet): **`ZENAF_ARCHITECTURE.md`**, **`ZENAF_PROMPT_AND_TRUTH_ARCHITECTURE.md`**, and the rest of the library.

2. **`docs/02_ACTIVE_DESIGN/`** — **Design intent** (may run ahead of code). See **`docs/02_ACTIVE_DESIGN/README.md`**. Phase 1 seed: `VISION_EXECUTION_DESIGN.md`, `CORE_PROFILE_ARCHITECTURE.md`, `CONTEXT_ACTION_BAR_DESIGN.md` (**focus strip + voice: see `ACTIVE_VS_PLANNED` for as-built**), `EXECUTION_STEPS_DESIGN.md`, `MEDIATION_EXECUTION_DIRECTION.md`. **Product-wide AI action substrate (traces + outcomes; VE-first client module `frontend/src/ai-actions/`):** **`docs/02_ACTIVE_DESIGN/AI_ACTION_TRACE_AND_ROUTING_DESIGN.md`**. Other design docs (e.g. `COCKPIT_DESIGN.md`) remain under `docs/` until a later pass.

3. **`docs/03_IMPLEMENTATION_PLANS/`** — **Plans and cleanup proposals** (next work, not canonical truth). See **`docs/03_IMPLEMENTATION_PLANS/README.md`**.

4. **`docs/04_REFERENCE/`** — **Specs, tab maps, entity shapes** (lookup; not canonical truth). See **`docs/04_REFERENCE/README.md`**.

5. Additional library docs remain in **`docs/`** root until a later pass.

If you only read **four** current-state anchors: **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`**, **`docs/01_TRUTH/CODEBASE_TRUTH_RULES.md`**, **`docs/01_TRUTH/SYSTEM_REFERENCE.md`**, and **`docs/01_TRUTH/BOOT_FLOW.md`**. For the **Vision map** (zen sand + growth triad), add **`docs/01_TRUTH/VISION_MAP_AND_ZEN_PROJECTION.md`**.

**Flows, surfaces, and AI trace coverage (what’s wired vs legacy):** **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`** is the most exhaustive single doc. **`docs/01_TRUTH/SYSTEM_REFERENCE.md`** (especially Part IV + V) is the most exhaustive *combined* reference for intent, projection, entities/APIs, and current state in one file.

---

## Target folder map (full layout after all migration steps)

| Folder | Purpose | Status |
|--------|---------|--------|
| **`00_START_HERE/`** | Optional ultra-short orientation. | Not created yet. |
| **`01_TRUTH/`** | Canonical **as-built** facts, governance rules, system reference, boot flow. | **Partially populated** (five core docs). |
| **`02_ACTIVE_DESIGN/`** | **Target** UX/architecture/product design. | **Seeded** (core VE / profile / mediation design set). |
| **`03_IMPLEMENTATION_PLANS/`** | Phases, proposals, cleanup steps. | **Seeded** (see folder `README.md`). |
| **`04_REFERENCE/`** | Specs, tab maps, checklists, YAML. | **Seeded** (see folder `README.md`). |
| **`05_ARCHIVE/`** | Superseded or frozen docs. | **Seeded** (superseded system notes + audits). |

---

## Canonical vs active (paths as of this migration)

- **Canonical (truth) in `docs/01_TRUTH/`:**  
  **`CODEBASE_TRUTH_RULES.md`**, **`CODEBASE_INVENTORY.md`**, **`ACTIVE_VS_PLANNED.md`**, **`SYSTEM_REFERENCE.md`**, **`BOOT_FLOW.md`** — same descriptions as before; paths are now under **`01_TRUTH/`**.

- **Canonical (truth) still at `docs/` root (not moved yet):**  
  **`ZENAF_ARCHITECTURE.md`**, **`ZENAF_PROMPT_AND_TRUTH_ARCHITECTURE.md`** — architecture and prompt/truth stack; cross-link with `01_TRUTH` docs.

**Conflict order:** runtime code → **`docs/01_TRUTH/CODEBASE_TRUTH_RULES.md`** → **`docs/01_TRUTH/CODEBASE_INVENTORY.md`** / **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`** / **`docs/01_TRUTH/BOOT_FLOW.md`** → **`docs/01_TRUTH/SYSTEM_REFERENCE.md`** → **`docs/02_ACTIVE_DESIGN/`** (intent) → **`docs/03_IMPLEMENTATION_PLANS/`** (bounded next work; not source of truth) → **`docs/04_REFERENCE/`** (specs / lookup; keep aligned when behavior changes; not canonical truth alone).

- **Active design** — Primary set in **`docs/02_ACTIVE_DESIGN/`**; additional design docs still under **`docs/*.md`** until migrated.

- **Active execution / cleanup proposals** — Primary set in **`docs/03_IMPLEMENTATION_PLANS/`**; any stragglers remain under **`docs/*.md`** until migrated.

- **Reference / specs / tab & field maps** — Primary set in **`docs/04_REFERENCE/`**; stragglers remain under **`docs/*.md`** until migrated.

---

## Archive and superseded docs

- When **`05_ARCHIVE/`** exists, move superseded docs there and add a **`Status: Superseded`** header with a pointer to the replacement.
- **Do not delete** without checking inbound links; prefer **archive + pointer**.

---

## Where to put a new doc

| You are writing… | Put it in… |
|------------------|------------|
| “What the code does / must do” | **`docs/01_TRUTH/`** (if it belongs with the canonical five) or `docs/` root until the next migration pass. |
| “How we want the product to work” | **`docs/02_ACTIVE_DESIGN/`** (preferred) or `docs/` root for not-yet-migrated design notes. |
| “Steps we will take next” | **`docs/03_IMPLEMENTATION_PLANS/`** (preferred) or `docs/` root until the next migration pass. |
| “Spec / field list / tab map / checklist” | **`docs/04_REFERENCE/`** (preferred) or `docs/` root until the next migration pass. |
| “Old version / done / replaced” | **`docs/05_ARCHIVE/`** (preferred) or `docs/` root until the next migration pass. |

---

## Lightweight metadata (recommended)

At the top of each doc (after the title), optional block:

```markdown
<!--
Status: Canonical | Active design | Plan | Reference | Superseded | Draft
Owner:
Last updated: YYYY-MM-DD
Replaces:
Superseded by:
-->
```

**Status meanings:** **Canonical** — truth layer. **Active design** — target state. **Plan** — bounded execution. **Reference** — lookup. **Superseded** — historical. **Draft** — not yet adopted.

Only **Status** and **Last updated** are worth requiring for new or materially changed docs; **Replaces** / **Superseded by** when archiving or merging.

---

*Next step for maintainers: migrate more design docs into `02_ACTIVE_DESIGN/` as needed, and move additional superseded root docs into `05_ARCHIVE/` when clear.*
