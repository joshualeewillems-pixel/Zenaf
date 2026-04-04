# Next 3 Cleanup Steps — Consistency Without Full Rewrite

**Based on:** ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE.md audit conclusions.  
**Goals:** Improve council sharpness, align UI with runtime/seat reality, make truth-source weighting explicit.  
**Constraint:** Smallest practical steps; no giant prompt-system rewrite.

---

## Audit conclusions (as given)

- Council currently overweights Phil Context (mitigated by Operator priorities refinement; ordering still puts preference next to task).
- Structured memory artifacts are stored but not used as reasoning inputs.
- Prompt assembly is fragmented across modules.
- Operator identity is overrepresented in council and absent elsewhere.
- UI ontology is drifting from the intended seat model (mandate labels, missing Risk/Skeptic).

---

## Recommended order and steps

### Step 1 — Council packet order: task first, operator priority after system facts

**Why first:** Improves council sharpness by making the model see task (context + question) and system facts (recent tool summary) before operator preference. No new concepts; one function, one reorder.

**What to do:** In `build_council_decision_packet()`, assemble blocks in this order:

1. **Context** (task)
2. **Question** (task)
3. **Recent tool summary** (system facts)
4. **Operator priorities** (preference)
5. **Constraints**

**Exact file/function:** `local_ai/atria_tools.py` → `build_council_decision_packet()`.

**Current order:** Context → Operator priorities → Recent tool summary → Constraints → Question.

**Change:** Move `Question` to immediately after `Context`. Then append Recent tool summary, then Operator priorities, then Constraints. Add a one-line comment above the block-building: e.g. `# Packet order: task (context + question) first, then system summary, then operator priorities, then constraints.`

**Do not:** Add new blocks, change truncation limits, or touch synthesis. This is reorder + comment only.

---

### Step 2 — UI: Align mandate dropdown and seat taxonomy with canonical model

**Why second:** Aligns UI with runtime/seat reality and reduces confusion between “what the user sees” and “what the backend expects.” Mandate ids stay the same; only display names and one new mandate.

**What to do:**

1. **Mandate display names** in `frontend/src/mandates.ts` (BUILT_IN_MANDATES):
   - strategist → name: `'Strategy'`
   - operator → name: `'Execution'`
   - analyst → name: `'Evidence'`
   - integrator → name: `'Integration'`
   - creative → name: `'Creativity'`
   - governance → name: `'Governance'` (unchanged)
2. **Add Risk mandate:** new entry with `id: 'risk'`, `name: 'Risk'`, and appropriate core_question, optimize_for, watch_for, failure_mode, output_style (e.g. downside focus, stress-testing assumptions).
3. **Optional but recommended:** Add Skeptic to `frontend/src/perspectives/types.ts` (BUILT_IN_PERSPECTIVES) and `skeptic: 'risk'` in `frontend/src/App.tsx` (DEFAULT_MANDATES_BY_PROFILE) so Skeptic pairs with Risk.

**Exact files:**

- `frontend/src/mandates.ts` — update six `name` values; append Risk mandate; optionally reorder array to canonical order (Strategy, Execution, Evidence, Risk, Integration, Creativity, Governance).
- `frontend/src/perspectives/types.ts` — add one Skeptic entry to BUILT_IN_PERSPECTIVES (if doing optional part).
- `frontend/src/App.tsx` — add `skeptic: 'risk'` to DEFAULT_MANDATES_BY_PROFILE (if adding Skeptic).

**Do not:** Change mandate ids; change backend COUNCIL_ROLE_KEYS or role names; add new API or persistence. Frontend-only.

---

### Step 3 — Document truth-source order and council block contract

**Why third:** Makes weighting explicit and gives a single place to point when adding or reordering blocks later. No new runtime behavior; documentation and one optional in-code contract.

**What to do:**

1. **Doc:** In `docs/ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE.md` (or a new short `docs/TRUTH_SOURCE_ORDER.md`), add a subsection **“Intended truth-source order (council)”** that states:
   - Task (context + question) first.
   - System facts (e.g. recent tool summary, and when used: recent VE decisions) second.
   - Operator priorities (preference) third.
   - Constraints last.
   - Philosophical orientation is not in default council or synthesis.

2. **Optional in-code contract:** In `local_ai/atria_tools.py`, add a comment or a read-only tuple at the top of `build_council_decision_packet()` that names the block order, e.g.:
   - `# Council packet block order: context, question, recent_tool_summary, operator_priorities, constraints (see docs/ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE.md).`
   - Or a tuple like `_COUNCIL_PACKET_ORDER = ("context", "question", "recent_tool_summary", "operator_priorities", "constraints")` and build `parts` in that order so future edits can’t silently reorder.

**Exact files:**

- `docs/ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE.md` — add “Intended truth-source order (council)” and “Where operator identity appears (council only).”
- `local_ai/atria_tools.py` → `build_council_decision_packet()` — add comment and, if desired, a tuple used only to drive the order of appends (no new framework).

**Do not:** Add a shared prompt-assembly layer, change other modules’ prompts, or implement memory injection. Documentation + one function’s explicit order only.

---

## What should explicitly wait until later

- **Shared artifact store and memory injection** — Do not add structured memory (NodeSnapshot, JudgmentSnapshot, CouncilRunArtifact) into prompts until the artifact store and retrieval hooks are designed and implemented. Step 3 only documents the intended hierarchy.
- **Unified prompt-assembly framework** — Do not introduce a single cross-module prompt builder or context-block registry. Cleanup is local to council packet and docs.
- **Operator identity in other paths** — Do not add operator priorities or philosophical orientation to cockpit, next-step, content, initiative eval, or Idea Lab in this set of steps. Document “council only” in step 3.
- **Backend seat/mandate renames** — Do not change COUNCIL_ROLE_KEYS, COUNCIL_ROLES, or backend mandate ids. UI display names and one new mandate id (`risk`) are sufficient; backend already accepts any mandate id from the frontend.
- **Synthesis or governance getting philosophical orientation** — Keep philosophical orientation out of default fast council and synthesis. Reintroduce only when there is a specific product reason and a controlled injection point.
- **Large refactors** — No refactor of the perspective/mandate system, no rewrite of atria.py or idea_lab prompt construction, no new config schema for “truth weights.”

---

## Summary table

| Step | Focus            | Primary file(s)                    | Change type              |
|------|------------------|------------------------------------|---------------------------|
| 1    | Council sharpness| atria_tools.py                     | Packet block reorder + comment |
| 2    | UI ↔ seat reality| mandates.ts, (types.ts, App.tsx)  | Mandate names + Risk (+ optional Skeptic) |
| 3    | Truth weighting  | ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE.md, atria_tools.py | Doc + optional order constant/comment |

Implement in order 1 → 2 → 3. Each step is small and independently shippable.
