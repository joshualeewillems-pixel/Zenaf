# Conversation trunk architecture

<!--
Status: Active design (target)
Last updated: 2026-03-31
-->

## Problem

Zenaf’s conversational surfaces still behave like **parallel mini-systems** rather than one pipeline with variations:

- Map chat (guidance scripts, triad, stage lens)
- Vision & Execution focus chat / council
- Workspace council / Zenaf (Thinking Partner) single-seat path
- Training / Foundation / workout streams
- Guide / opening seed copy

They **share some context** (e.g. `council_preflight`, VE working set, developmental guidance, map triad wiring), but **classification and response shape** are still largely **path-local** (prompt stack, surface defaults). So the model can fall back to a **generic action frame** (“coordinate with…”, three options) even when the user asked for **state / inventory** on a named entity.

This is not fixed by “more adjectives for Zenaf”; it needs **one trunk** that decides question type and **output contract** before surface-specific enrichments apply.

## Target shape

### 1. Common conversation trunk (universal)

Single place (conceptually one module, possibly TS + Python mirrors) responsible for:

| Responsibility | Notes |
|----------------|--------|
| Subject resolution | What idea / project / node / thread is this about? |
| Question / intent classification | State vs action vs reflection vs clarification |
| State read policy | Align with product rules: inventory from Context first when ask is “what exists / missing / incomplete / which fields” |
| Context assembly | Primary entity, working set, graph neighbors, branch payloads |
| Guidance lens selection | When project-like: branch lens, weak dimensions, stage question (see map / VE scaffolding) |
| Response contract selection | What shape must the answer take *before* surface flavor |
| Output normalization | Single contract for lean / inventory / options |

### 2. Use-case branches (thin)

Branches **only add** facts and hints; they do **not** own classification or contract alone.

| Branch | Enrichments (examples) |
|--------|-------------------------|
| **VE** | Missing fields, incomplete entities, execution next steps, focus graph slice |
| **Vision map** | Triad, stage lens, weak dimensions, shippable-slice framing |
| **Workspace** | Current topic, folder/runtime, operator workflow |
| **Training / Foundation** | Aspiration, resonance, core profile shaping |

### Flow (target)

```text
USER ASK
  → CONVERSATION TRUNK
       resolve subject
       classify question type
       assemble common context
       choose response contract
  → BRANCH ENRICHMENTS (VE / map / workspace / training)
  → ZENAF / COUNCIL / STREAM OUTPUT
```

**Anti-pattern (today, in places):**

```text
USER ASK → surface path → surface heuristics → surface answer shape
```

## Conversation trunk contract (draft)

### Inputs

- `user_question` (string)
- `active_surface` (e.g. `vision_execution`, `vision_map`, `workspace`, `perspectives`, …)
- `focused_entity` / `subject_ref` hints (from focus provider, preflight, or resolution)
- `working_set_snapshot` (e.g. VE DB snapshot block)
- `guidance_lens_candidates` (e.g. map triad + `work_guidance_frame`, developmental guidance)
- `runtime_context` (breadcrumb, folder, topic, thread snippet, …)

### Outputs

- `subject_ref` — resolved entity (or explicit ambiguity)
- `question_kind` — e.g. `state_inventory`, `missing_fields`, `next_step`, `option_generation`, `reflective_inquiry`, `clarification`
- `response_mode` / `output_contract` — e.g. `inventory_only`, `inventory_then_recommend`, `three_options_then_lean`, `reflective_synthesis`
- `context_packet` — normalized string or structured blocks for the model
- `branch_enrichments` — labeled slices: `ve`, `map`, `workspace`, `training`
- Optional: `grounding_tier` / legitimacy flags (align with `council_preflight` PRIMARY vs CONTEXT NOTE)

### Example mapping

**Question:** “What do we still need to do to the ‘finalize website’ idea?”

| Trunk output | Value |
|--------------|--------|
| `subject_ref` | Idea “finalize website” (from title match + focus or working set) |
| `question_kind` | `state_inventory` / incomplete work |
| `use_case` | VE / project-like progression |
| `guidance_lens` | When promoted to project: branch lens; until then: seed lens |
| `output_contract` | `inventory_then_recommend` or `inventory_only` per policy (inventory of gaps/dimensions/fields **before** generic next steps unless user asks “what should I do”) |

## Consolidation targets (current code pointers)

**Trunk candidates (logic to centralize):**

- Context resolution and PRIMARY legitimacy: `local_ai/council_preflight.py`
- Council / Thinking Partner instruction stack: `local_ai/zenaf_tools.py` (`COUNCIL_CONVERSATIONAL_PARTNER_SYSTEM`, Thinking Partner injects, Zenaf persona)
- State vs synthesis rule (prompt text — should follow trunk `question_kind`): same file + `frontend/src/perspectives/types.ts` (Zenaf constraints)
- Developmental / lens packet: `local_ai/developmental_guidance.py`, `frontend/src/developmentalGuidance/buildDevelopmentalGuidanceContext.ts`
- VE triad from focus: `frontend/src/developmentalGuidance/buildVeMapTriadSnapshot.ts`

**Branches (enrichment only, after trunk):**

- Map UI scripts: `frontend/src/vision-map/guidanceScripts.ts`, `MapChatShell.tsx`, `guidanceConversationalSeed.ts`
- Workout / training streams: `frontend/src/perspectives/workoutCouncilStream.ts` (and related)
- Workspace folder workflow: `App.tsx` / mediation surfaces

Phased implementation should live under **`docs/03_IMPLEMENTATION_PLANS/`** once trunk milestones are ticketed; this doc stays **intent**.

## Practical first milestone (suggested)

**Phase 1 + 2 (implemented):** `local_ai/conversation_trunk.py` — `classify_question_kind`, `select_output_contract`, `derive_mediation_profile` (`MediationProfile`), `conversational_partner_trunk_instructions` (includes **THIS TURN — MEDIATION CONTROL**); also **`user_providing_precision` → `confirm_and_integrate`** / `acknowledge_integrate` when the user supplies a definition (integration mode, not mediation); **`derive_capture_target`** infers field/entity/confidence from the question, optional `council_preflight` JSON, and PRIMARY **Title** in the packet for precise save/refine fork wording. Zenaf path in `_run_council_conversational_partner_body` computes mediation before prompt assembly; `COUNCIL_CONVERSATIONAL_PARTNER_SYSTEM` defers to mediation when that block is present. Types: `frontend/src/conversation/conversationTrunkTypes.ts`. Tests: `tests/test_conversation_trunk.py`.

Further milestones:

1. Define shared **types** for trunk inputs/outputs (TS + optional Python `TypedDict` / dataclass) in one small module each side.
2. Extend **classification + contract** to multi-seat council / other `/run` modes as needed (no UI rewrite required for Phase 1).
3. Thread `output_contract` into the Thinking Partner / Zenaf system prompt as a **single line** (“This turn’s contract: …”) generated from trunk, not duplicated per surface.
4. Extend to map-initiated council and workout **only after** council path is stable.

## Cursor prompt (for implementation passes)

Paste into a new agent chat when designing or migrating code:

```markdown
## Goal
Design and implement a **Conversation Trunk** for Zenaf so all chat surfaces share one pipeline: subject resolution → question classification → context assembly → response contract → branch enrichments → model call. Surfaces add only thin enrichments.

## Constraints
- Read the repo; cite real files (`local_ai/zenaf_tools.py`, `local_ai/council_preflight.py`, `local_ai/developmental_guidance.py`, `frontend/src/App.tsx`, `frontend/src/vision-map/MapChatShell.tsx`, workout paths).
- Phased PRs; do not rewrite all paths at once.
- Preserve safety/state rules (state/inventory from Context; no invented facts).

## Deliverables
1. **Trunk contract** (types): inputs; outputs `subject_ref`, `question_kind`, `response_mode`/`output_contract`, `context_packet`, `branch_enrichments`.
2. **Single module** (name + responsibilities) for classification + contract **before** surface-specific prompts.
3. **Migration table**: current file/behavior → trunk vs branch.
4. **Minimal first PR**: route **single-seat council** through trunk for classification + contract only.

## Acceptance
For “what do we still need to do to the ‘finalize website’ idea?” with focused entity + working set: trunk classifies state/inventory and sets contract so the answer inventories incomplete dimensions/fields before generic coordination advice unless the user explicitly asks what to do next.
```

## Related docs

- **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`** — As-built surfaces and gaps
- **`docs/01_TRUTH/CODEBASE_TRUTH_RULES.md`** — Routing and persistence expectations
- **`ZENAF_PROMPT_AND_TRUTH_ARCHITECTURE.md`** (repo root / `docs/`) — Prompt and truth stack (may overlap; keep trunk doc as the **conversation unification** anchor)
