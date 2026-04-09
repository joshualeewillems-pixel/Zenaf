# Flow channels + Vision Map panel — product alignment plan

Living document: merges the technical integration plan with **GPT product review** (one cognitive pass, progressive disclosure, mode + channel modulation).

---

## First principle (lock)

The user should **feel one thing**, then **drill into why**, then **act**.

| Layer | Role | Cognitive load |
|-------|------|----------------|
| **1. Felt read** | Fast, pre-cognitive | Stone chrome, triad bars |
| **2. Explanation** | Structured, single spine | One narrative + optional compact facets |
| **3. Action** | Guided | Best next step, chat, council (opt-in deep) |

Everything new maps to **one** of these. Avoid **five overlapping panels** saying similar things.

**Target experience:** *one coherent read*; everything else **confirms or deepens** it — not competing explanations.

### Radical bar (final 20%)

The goal is **not** “coordinate flow, guidance, and invites” as separate systems that agree. Those are **different expressions of one interpretation**:

`Flow + Channels → SingleInterpretation → { summary, action, chatPrefill, … }`

- **No fallback:** Avoid “flow for summary, guidance when flow doesn’t cover it” — that keeps **two sources of truth**. Flow (+ channel assessment from the same orchestrator) should **determine** what used to live in `guidanceScripts` (questions, suggested moves), not defer to it.
- **No redundant voices:** Prefer **one sentence** that already carries dominant issue, weakest channel, and implication — not `trunkSummary` + `bestNextLabel` + `next_best_question` as parallel prose.
- **One primary action line:** One clear move (e.g. “Expand into concrete steps tied to measurable outcomes”) — not competing CTAs from guidance vs invites vs labels.
- **Invites / chips:** Same ranked intent as `primaryAction` + modulation — **ranking and tint**, not a separate decision layer for “mode.”

Council remains **opt-in**; posture shapes **copy and prefill**, not auto `run_council`.

---

## What already exists (keep structurally)

- **Layer 1:** Stone visuals (condition, cracks, etc.), triad (water / soil / fruit).
- **Layer 2:** Flow sentence (`assessFlow` → `trunkSummary`), maintenance readout, channel inspector sections.
- **Layer 3:** Best next step, Discuss in chat, council / deeper check.

**Orchestrator (do not fork):** `assessNodeFlowAndChannels` → `channels`, `flow` (`FlowAssessment`), `lowest_channel`, `clean_stone_ready`, derived triad/severity/water_level/pulse. Map finalize: `liveProjection`; panel: `MapChatShell`; invite rank: `deriveFocusInvites` + `useFlowAssessmentFromCore`.

**Resolution (not coordination):** Retire parallel narrative from `guidanceScripts`. Long-term: **derive** stage- and kind-aware copy from the same inputs as `assessFlow` + `lowest_channel` + `channels` (or emit everything from an extended `FlowAssessment` / unified DTO). Until then, treat any remaining guidance helpers as **implementation detail behind** the single contract, not a second product voice.

---

## Target contract: one interpretation, three expressions

Extend the **output** of the flow layer (whether on `FlowAssessment`, `UnifiedNodeAssessment`, or a thin `MapPanelReadout` type) so one deterministic pass produces at least:

| Field | Role | Example shape |
|-------|------|----------------|
| `stance` | `proceed` vs `clarify_first` — **clarify_first is strict and rare** (see below) | Only when one answer would **materially change** the recommended action |
| `summary` | Single narrative (issue + weakest channel + implication) | “Structure is limiting progress; grounding is thin and output remains low…” |
| `actionLine` | Proceed: primary move. Clarify: **kind of move** (short), not a second question — avoid duplicating `clarificationQuestion` in the panel | Proceed: “Expand into steps tied to outcomes.” Clarify: “We need one clarification before choosing the next move.” |
| `chatPrefill` | Composer seed; must stay **consistent** with visible question | Proceed: action-oriented prompt. Clarify: **same as** `clarificationQuestion` (or near-identical). |
| `clarificationQuestion` | The **single** discriminating question (shown once in UI when clarify) | Required when `clarify_first`. |
| `ambiguityType` | **Transport enum** — not display copy; **bias to exact parity** with `local_ai/conversation_trunk.AmbiguityType` now, not later | See type block below. |
| `blockingClarification` | Optional explicit flag (`stance === 'clarify_first'` ⇒ true) for UI/analytics without re-deriving | Same as “needs answer to proceed” conceptually. |

Same `dominantIssue`, `primaryAction`, `lowest_channel` drive these fields — **zero competing generators** for product-facing text (see **Node interpretation** section below).

**Triad segment click:** Prefill and inspector focus must use this contract (or the same helper) so clicks do not suggest a **wrong dimension** (e.g. soil selected but water-flavored question).

---

## Node interpretation: clarification as first-class (not a fallback)

**Problem:** Clarification behavior is split across `conversation_trunk` (mediation), `council_preflight`, and gap elicitation, but **not** driven by `assessNodeFlowAndChannels` / unified assessment. That invites a **second narrative path** (“model guessed you need clarity”) vs “the map read says we must clarify.”

**Rule:** Lack of clarity is a **primary outcome** of the same interpretation pipeline as `summary` / `actionLine` / `chatPrefill` — not a downstream fallback when copy is missing.

### Type shape (TS — names can ship as `NodeInterpretation` on the unified DTO)

```ts
export type InterpretationStance = 'proceed' | 'clarify_first'

/**
 * Transport enum for `council_preflight` / trunk — NOT user-facing label text.
 * Values must stay in lockstep with `local_ai/conversation_trunk.AmbiguityType`;
 * add or rename only when the server enum changes, then update both sides in one PR.
 */
export type NodeInterpretationAmbiguityType =
  | 'missing_definition'
  | 'unclear_priority'
  | 'competing_priorities'
  | 'unresolved_dependency'
  | 'ownership_gap'
  | 'unknown'

export type NodeInterpretation = {
  stance: InterpretationStance
  /** True iff one discriminating answer is required before a responsible next move (redundant with stance but explicit for UI + analytics). */
  blockingClarification?: boolean
  /** Single narrative spine (dominant issue + weakest channel + implication). */
  summary: string
  /** Proceed: primary recommended move. Clarify: short “kind of stall” line only — do not repeat the question text here. */
  actionLine: string
  /** Composer seed; must not contradict summary or (when clarify) clarificationQuestion. */
  chatPrefill: string
  /** Exactly one discriminating question; required when stance === 'clarify_first'. */
  clarificationQuestion?: string
  /** Drives trunk `ambiguity_type` when overriding mediation. */
  ambiguityType?: NodeInterpretationAmbiguityType
}
```

Set **`blockingClarification: true`** when `stance === 'clarify_first'` (omit or `false` otherwise) unless you later split “soft suggest question” from “hard block” in a later revision.

Attach as **`interpretation: NodeInterpretation`** on `UnifiedNodeAssessment` (or merge fields onto the same type if you prefer a flat DTO).

### Where logic lives

| Piece | Location |
|-------|----------|
| Stance + clarification question + ambiguity mapping | **`frontend/src/flow/deriveNodeInterpretation.ts`** (new): pure function `(unified: UnifiedNodeAssessment, ctx: { kind, ref, … }) → NodeInterpretation`. Called from **`assessNodeFlowAndChannels`** at the end (single export path) so all consumers get one object. |
| Low-level flow prose today | Keep **`assessFlow` / `buildSummary`** as inputs only; **do not** add a second user-facing question generator outside `deriveNodeInterpretation`. |
| UI | **`MapChatShell`**: **`clarify_first`** — **avoid duplicate question text**: show **`summary`** (why) + **`clarificationQuestion`** once (the actual question); composer from **`chatPrefill`** (same or near-identical to that question). Use **`actionLine`** only as a **short non-repeating** line (e.g. “One clarification needed before the next move”) or fold into layout so you do **not** get: summary + actionLine + question + prefilled question all reading as four versions of the same ask. |
| Invites | **`deriveFocusInvites`**: when `clarify_first`, rank **one** clarify-oriented invite **first**. **Do not** invent a new invite/mode family: prefer existing **`distill`** (or nearest `InviteAction`) with **clarify-oriented copy/framing** unless product later adds a dedicated label. |
| Dev snapshot → API | Extend **`MapTriadDevelopmentalSnapshot`** (or parallel field in council payload) with `node_interpretation: NodeInterpretation` JSON so the server does not re-infer stance. |
| Trunk override | **`local_ai/atria_tools.py`**: after `derive_mediation_profile(...)`, if preflight has `node_interpretation.stance === "clarify_first"` and non-empty **`clarification_question`**, force **`mediation_move = "ask_discriminating_question"`** and set **`ambiguity_type`** from the payload (transport enum parity). **Do not** rely on `classify_question_kind` alone for that mediation decision when this branch applies. **Guard:** only override when the user has **not** clearly pivoted in the composer (e.g. empty draft, session opener, or message still matches prefill) so the system does not feel stubborn. |
| Preflight merge | **`council_preflight.py`**: parse/validate `node_interpretation`; echo into Context block so trunk instructions stay consistent. |

### Stance derivation — **conservative** (product law)

**Encode at top of `deriveNodeInterpretation.ts` (file header comment):**

> Use **`clarify_first`** only when **one discriminating answer would materially change the recommended action**.  
> Otherwise keep **`proceed`** and let **`actionLine`** drive repair.

**`clarify_first` means:** “The system cannot **responsibly** choose the next move without one answer” — **not** “this node is weak” or “soil/fruit is low.” Ordinary underdevelopment → **`proceed`** with an action-oriented recommendation.

**Set `clarify_first` when** (examples — tighten in code; all should satisfy the product law):

- **Missing definition / scope ambiguity** that blocks choosing between materially different next moves (e.g. no boundary, cannot tell whether to expand vs narrow vs escalate).
- **Conflicting signals** such that picking `primaryAction` would be **unsafe** without resolution (explicit rules, not generic `clean_stone_ready === false`).
- **Ownership or dependency ambiguity** that **blocks** the next move (not merely low water score).

**Do not** set `clarify_first` for:

- Low soil or low fruit **alone** (weak but interpretable → still recommend).

**`clarificationQuestion`:** Exactly one string from a **small template table** keyed by `(dominantIssue, lowest_channel)` so the question is **discriminating** and aligned.

When **`clarify_first`**: **`chatPrefill`** = **`clarificationQuestion`** (or near-identical); **`actionLine`** = short **non-duplicative** stall descriptor (see MapChatShell row). Set **`blockingClarification: true`**.

### Minimal integration diff (ordered)

1. **`unifiedNodeAssessmentTypes.ts`** — add `NodeInterpretation`, `interpretation?: NodeInterpretation` on `UnifiedNodeAssessment` (or required once shipped).
2. **`deriveNodeInterpretation.ts`** — implement stance + question + ambiguity mapping + summary/actionLine/chatPrefill assembly (may call refactored `buildSummary` internals or duplicate minimal copy keys until `flowAssessment.ts` exports a single builder).
3. **`assessNodeFlowAndChannels.ts`** — append `interpretation: deriveNodeInterpretation(...)` to return value.
4. **`MapChatShell.tsx`** + triad click handler — consume `interpretation`; prefill and labels from `chatPrefill` / `clarificationQuestion`.
5. **`deriveFocusInvites.ts`** (+ types) — accept optional `interpretation`; prioritize clarify invite when `clarify_first`.
6. **`developmentalGuidance/types.ts`** — extend `MapTriadDevelopmentalSnapshot` with `node_interpretation?`.
7. **`VisionMapView.tsx` / App council payload** — pass snapshot field into `council_preflight`.
8. **`council_preflight.py`** — validate and format `node_interpretation` into PRIMARY / Context.
9. **`atria_tools.py`** — mediation override branch when `node_interpretation.stance == "clarify_first"`.
10. **Tests:** `deriveNodeInterpretation.test.ts`; council/trunk test for mediation override + composer pivot guard; golden cases for **proceed** vs **strict clarify_first**.
11. **Invariant test (product-level):** for a given node read, **`summary`**, **`actionLine`**, and **`chatPrefill`** must **not contradict** each other (lightweight table/snapshot test is enough). Same generator family, one interpretation, multiple expressions.

---

## Core optimization: one narrative spine

**Problem:** Today four voices can describe the same reality:

- Triad row hints (“thin grounding”)
- Flow paragraph
- Maintenance line (weakest channel · dominant issue · clean stone)
- Generic channel section headers

**Direction:**

1. **ONE canonical read** = the contract’s `summary` (folds dominant issue, weakest channel, implication into **one** sentence where possible). Deprecate separate `trunkSummary` vs `bestNextLabel` vs guidance question as **independent** UI fields.
2. **Everything else = facets** of that read:
   - Triad bars = **visual confirmation** (implicit “weakest channel” where possible).
   - **Do not** repeat weakest/dominant/clean as a dense prose line **next to** `summary` — use **tags** only if needed for scan.

### Maintenance readout — replace, don’t stack

**Remove** (or default-hide) the verbose row:

`Weakest channel: X · Dominant issue: Y · Clean stone: Z`

**Replace with** a **compact tag strip** (1–3 tags), e.g.:

`[ Structure limiting ] [ Not clean stone ] [ Low output ]`

- Derived from `flow.dominantIssue`, `clean_stone_ready`, and channel bands / `lowest_channel` — **tags, not a second essay**.
- Drop dev-only inline `code` / assessor name from default UI (keep tests / debug build if needed).

---

## Eye flow (panel order)

**Avoid** triad → paragraph → maintenance → soil → action (too many context resets).

**Preferred vertical order:**

1. **TOP — perception:** Triad (and map stone already on canvas).
2. **MID — meaning (single block):** **`summary`** (+ optional **tag strip**; no second paragraph).
3. **LOWER — action:** **`actionLine`** as the single primary CTA copy + **Discuss in chat** (secondary); council deep explicit. No separate “Best next step” heading if it duplicates `actionLine`.
4. **DEEP — inspection:** Water / Soil / Fruit **sections** (collapsible or below the fold), **after** action affordances **or** clearly separated as “Inspect” so the default path is shorter.

*(Exact collapse rules and spacing belong in a short UI spec when implementing.)*

---

## Channel sections — diagnostic lenses, not documentation

**Avoid:** Static headers like “Soil — Definition, context, and grounding” as the only framing.

**Prefer:** Contextual, state-aware one-liner + content, e.g.:

- **Soil (grounding is thin)** — *This initiative lacks enough defined structure to support execution and synthesis.*

Each channel section:

- **Inherits** current band / reasons from `channels[channel]` (and triad).
- Explains **in context of the selected node**, not generic glossary copy.

---

## Conversation mode activation

### Dominant issue → base mode (posture)

Map `flow.dominantIssue` to the existing invite / flow actions (same vocabulary as `assessFlow`):

| Dominant issue | Base mode (`primaryAction` family) | Intent |
|----------------|-----------------------------------|--------|
| clarify | distill | Tighten language before steps |
| structure | expand_to_steps | Break into executable units |
| tension | surface_tensions | Widen / name tensions, don’t force resolution |
| decide | summarize_for_council | Commit / summarize for decision |

### Channel **modulates** the same mode (high leverage)

**Do not** multiply unrelated “modes.” **One** base mode; **weakest channel** (`lowest_channel` or clearest underperforming channel) **tilts** prompts and optional prefill:

**Example — base mode `expand_to_steps`:**

| Weakest channel | Modulation |
|-----------------|------------|
| soil | Define scope / boundaries before listing steps |
| water | Ownership, energy, checkpoints |
| fruit | Outcome anchoring — measurable milestones |
| condition | Reduce risk / simplify / stabilize |

This matches product copy you already use (e.g. fruit-weak → “What measurable milestone will prove…?”).

### UI / council wiring (no new panels)

- **Primary action:** **`actionLine`** from the contract — always channel-modulated; same source as any “best next” affordance.
- **Discuss in chat:** Prefill with **`chatPrefill`**; inject same mode/channel into system context (user does not pick mode).
- **Chips (VE / focus):** Express the **same** ranked `primaryAction` / invite ordering — optional **tint by channel**; chips do **not** define a separate conversational mode.

---

## What to remove / keep / add (summary)

| Remove | Keep | Add (light) |
|--------|------|-------------|
| Parallel prose: trunk + maintenance essay + guidance `next_best_question` as separate product voices | Triad visuals; single `summary` | Contract fields: `summary`, `actionLine`, `chatPrefill` |
| `guidanceScripts` as independent question engine (long-term) | `assessNodeFlowAndChannels` inputs | Tag strip (optional scan only) |
| Verbose maintenance row as default | Same orchestrator for map + panel | Flow-derived generator (or extended `buildSummary`) |

---

## Implementation phases (when executing)

**Phase 0 — Output contract (ontology)**

- Add `NodeInterpretation` (`stance`, `blockingClarification?`, `summary`, `actionLine`, `chatPrefill`, optional `clarificationQuestion`, `ambiguityType` as **transport enum** synced with trunk) via **`deriveNodeInterpretation`**; invoke at end of **`assessNodeFlowAndChannels`**.
- Stance **`clarify_first`** is **conservative** (product law in `deriveNodeInterpretation` header); when set, single question + **`chatPrefill`** alignment + trunk override via **`council_preflight`** + **`atria_tools`** (with composer pivot guard).
- Add **non-contradiction** tests for interpretation fields (see Node interpretation section).
- Wire **triad click prefill** to this contract (or shared helper keyed by active section + same inputs) to fix **wrong-dimension** prefills.

**Phase 1 — Retire parallel guidance**

- Replace `guidanceScripts` usage in `MapChatShell` with contract-driven copy; either **delete** independent thresholds in guidance or reimplement `buildGuidanceScriptForNode` as a **thin wrapper** over the contract for harvest / commit flows only (structure proposal), not a second “what to ask.”

**Phase 2 — Panel UI**

- One block: **`summary`** then **`actionLine`** + Discuss in chat; tag strip optional; reorder TOP/MID/LOWER/DEEP per eye-flow section.
- Remove default maintenance paragraph and dev `code` line.

**Phase 3 — Invites / chips**

- Ensure `deriveFocusInvites` (and map-adjacent CTAs) read the **same** ranked action + channel signal; optional chip tint by channel.

**Phase 4 — Inspector lenses**

- `MapTriadInspectorContent`: contextual headers from `channels` / contract, not generic docs.

**Phase 5 — Hardening**

- Pass `councilRuns` into panel assessor if pulse parity requires it.
- Short **panel UI spec** (collapse, spacing) if needed.

---

## Architectural guardrails

- **No second scoring path** — extend `assessFlow` / `buildChannels` if axes are wrong, don’t fork UI-only logic.
- **No second narrative path** — product copy for map panel + chat prefill comes from the **contract**, not parallel script tables (stage tables may remain only for **structure harvest** mechanics if kept separate).
- **Less UI, more alignment** — prefer collapsing and wiring over new cards.
- **Council stays opt-in** for heavy runs; posture shapes **copy**, not necessarily auto `run_council`.
