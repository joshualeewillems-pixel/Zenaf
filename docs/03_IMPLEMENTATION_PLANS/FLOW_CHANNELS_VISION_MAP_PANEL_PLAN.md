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
| `summary` | Single narrative (issue + weakest channel + implication) | “Structure is limiting progress; grounding is thin and output remains low, so this work cannot yet convert effort into results.” |
| `actionLine` | One clear move (verb + intent; channel-modulated) | “Expand this into concrete steps tied to measurable outcomes.” |
| `chatPrefill` | Composer seed aligned with same read | “What concrete milestones would prove this initiative produces real results?” |

Same `dominantIssue`, `primaryAction`, `lowest_channel` drive all three — **zero competing generators** for product-facing text.

**Triad segment click:** Prefill and inspector focus must use this contract (or the same helper) so clicks do not suggest a **wrong dimension** (e.g. soil selected but water-flavored question).

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

- Add `summary` / `actionLine` / `chatPrefill` (names TBD) to the flow or unified assessment pipeline — one function (or paired `buildSummary` + builders) consuming `FlowAssessment` + `lowest_channel` + `channels` + entity kind.
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
