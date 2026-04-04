# Core Profile: Current Implementation & Intended Architecture

This document describes the **current transitional implementation** of Core Profile and the **intended final direction** for integration with the Perspectives system. The current build is explicitly foundational; several capabilities are documented here but **intentionally not implemented yet**.

**Canonical truth pair:** For **as-built surfaces and roadmap gaps**, see **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`**. For **product ontology** (one core vs many perspectives), see **`docs/01_TRUTH/SYSTEM_REFERENCE.md`** §1.4a and §2.6.

---

## Product ontology (direction)

- **Target:** **One core profile** per person/workspace context — the single structured synthesis / decision engine. **Perspectives** are **modes, lenses, or voices** expressed *from* that core, not additional peer “full profiles.”
- **Today:** SQLite and API still allow **multiple** `core_profiles` per user. **`is_primary`** + **`PATCH /core-profiles/{id}/set-primary`** are **already implemented**; list order is primary-first. Foundation **Brand** path resolves **one** id (`is_primary` else first row); **VE / influences** pickers may still expose **all** rows — convergence plan: **`SINGULAR_CORE_PROFILE_CONVERGENCE_AUDIT.md`**.
- **Influences / linking:** Core-to-core links in the influences UI become less meaningful under singularity; core ↔ perspective and person links remain the main graph.

---

## Prompt anchoring & training-text handling (implemented)

Reconcile, conversation, and **structured delegation** synthesize prompts so **user conversation dominates** model output and long `raw_notes` do not override corrections via position/length alone.

- **Hierarchy (text):** Conversation primary → digest/scaffold in notes → raw source lowest → current structured profile as reference. Explicit rule: **any contradiction between conversation and training inputs → conversation wins** (must override training).
- **FINAL OVERRIDE block:** Same short block appended **immediately before** output instructions (JSON contract / “respond in paragraphs”) in:
  - `local_ai/vision_execution/core_profile_reconcile.py` (`RECONCILE_PROMPT` + `CORE_PROFILE_FINAL_OVERRIDE`)
  - `local_ai/vision_execution/core_profile_conversation.py` (`CONVERSATION_PROMPT`)
  - `local_ai/delegation/core_profile_reconcile.py` (synthesized prompt, before the JSON output contract section)
- **Deterministic note compression:** When conversation turns are non-empty, `raw_notes` passed into prompts are capped (`lightly_compress_notes`, ~8000 characters) via `profile_training_notes_for_prompt` — **no extra LLM call**. Debug log `profile_notes_compressed` when truncation applies.

---

## Current implementation scope (what exists now)

- **3-layer workspace (UI)**
  - **Conversation layer** — Chat-style thread with the profile (user messages + assistant replies). Messages are still stored in browser localStorage keyed by profile id, but each send now calls a minimal `/core-profiles/{id}/conversation` endpoint that returns a single exploratory assistant reply.
  - **Raw notes / source layer** — Freeform text (“profile notebook”) stored in `core_profiles.raw_notes`. Primary dumping ground for thoughts, contradictions, strategy ideas.
  - **Structured profile layer** — The existing schema fields (e.g. `core_definition`, `current_goals`, …). Rendered as the “interpreted” lens; used unchanged by Idea/Initiative evaluation and other consumers.

- **Reconcile flow**
  - User can trigger **Reconcile from conversation & notes**.
  - Backend reads `raw_notes`, conversation turns, and current structured profile; calls the LLM to propose updated structured field values.
  - **No auto-apply.** Proposed changes are shown in a review UI (current vs proposed). User can edit proposed values and then **Apply** to copy into the structured form; **Save profile** persists to the API.

- **Schema**
  - Existing structured fields are **unchanged** (same names, same semantics). One optional field added: `raw_notes` (TEXT, default `''`) for the notebook content.
  - No new tables for conversation yet; conversation is client-side only.
  - **Returning insight (temporary simulation)** — Conversation replies can identify recurring loops by heuristically comparing the last 5–10 user turns. This simulates a future persistent pattern-tracking system without adding long-term memory.
  - **Escalation (temporary simulation)** — When a loop repeats inside the recent window, the conversation assistant escalates its response level (recognition → loop → avoidance → rare confrontation) based on repetition count and lightweight avoidance/engagement signals. This is still non-persistent.

---

## Intended final direction (documented, not implemented)

## Adaptive Reflection & Perspectives (planned)

This section is the **explicit intended direction** for how Core Profile conversation and Perspectives should evolve. It is **not fully implemented yet**; the current system simulates some of these behaviors within a single conversation window.

### 1. Pattern Tracking (Cross-Session)

- Persist lightweight pattern signatures (themes, tensions, loops)
- Detect recurrence across sessions (not just within a single chat)
- Enable “returning insight” when a pattern reappears over time

### 2. Readiness-Aware Escalation

- Responses escalate from gentle → direct → confrontational based on:
  - repetition of pattern
  - user engagement
  - inferred tolerance for challenge
- Default tone is grounded and non-threatening
- System adapts toward sharper clarity when user demonstrates receptivity

### 3. Perspective Modulation Layer

System-defined perspectives (e.g. Strategist, Analyst, Governance, Diogenes) will:

- interpret inputs through distinct lenses
- optionally participate in analysis flows (Ideas, Initiatives, Decisions)

Each perspective supports a gradient:

- 1 = default system perspective
- 5 = strongly user-shaped (inferred from Core Profile + conversation patterns)

### 4. User-Shaped Personalities (Future)

- Derived from Core Profile notes and conversation history
- May be explicitly defined by the user
- Can influence or participate in perspective outputs

### 5. Principle

Chat is for exploration. Reconcile is for formalization. Perspectives are for interpretation.

The system should:

- help the user see patterns
- respect timing
- avoid over-intervention
- surface insight when it is most likely to land

### 1. Connection to the Perspectives system

Core Profile is intended to **connect to the Perspectives system** and to **modulate system-defined perspectives** (e.g. Strategist, Analyst, Governance, and other framework perspectives). The profile (and eventually conversation/notes) should influence how those perspectives behave, not replace them.

### 2. User-shaped vs default system perspective (gradient concept)

A desired future behavior is a **gradient per perspective** from system default to user-shaped:

- **1** = default system perspective (no profile influence).
- **5** = strongly user-shaped perspective inferred from Core Profile (notes, conversation, structured profile).

So for each perspective (e.g. Strategist, Analyst, Governance), the system would support a setting in the range 1–5 controlling how much the Core Profile shapes that perspective’s behavior. This is **not built** in the current pass; it is a target design for the modulation layer.

### 3. Separation / modulation layer (future)

The intended separation is:

1. **User-shaped perspective** — Derived from Core Profile (conversation, raw notes, structured profile) and optionally from explicit user-defined personalities.
2. **Default system perspective** — Built-in definitions for each perspective (Strategist, Analyst, Governance, etc.).

The modulation layer would combine these (e.g. via the 1–5 gradient) so that runtime behavior can range from “pure system” to “strongly profile-informed” without duplicating the core perspective definitions.

### 4. User-defined personalities (future)

User-defined personalities may eventually:

- Be **inferred** from profile content and chat history.
- Be **explicitly named/defined** by the user (e.g. “Risk-averse strategist”, “Growth focus”).
- **Optionally participate in or influence** perspective conversations (e.g. as a voice in council or as a filter on recommendations).

None of this is implemented in the current pass. No persistent personality engine, no multi-perspective orchestration, no weighted blending across perspectives.

---

## Intentionally deferred (not in this pass)

- **Full multi-perspective orchestration** — Coordinating multiple perspectives (Strategist, Analyst, Governance, etc.) in one flow.
- **Weighted runtime blending** — Blending all perspectives with configurable weights or gradient per perspective.
- **Persistent personality engine** — Storing and loading named personalities, inferring them from history, or applying them across the product.
- **Autonomous profile rewriting** — Any process that updates the structured profile without explicit user review and apply.
- **Server-side conversation persistence** — Chat history is client-only (localStorage). There is a minimal `/core-profiles/{id}/conversation` API for generating one assistant reply per turn, but no DB table or long-term storage for conversation yet.
- **Actual wiring to Perspectives** — No code in this pass connects Core Profile to the Perspectives system or to any gradient/modulation logic.

---

## Summary

| Area | Current state | Intended direction |
|------|----------------|--------------------|
| **Ontology** | Multiple `core_profiles` rows + list UI | **One canonical core** per context; perspectives as expressive layer (§ Product ontology) |
| Core Profile UI | 3-layer workspace: chat, raw notes, structured profile; Foundation + Team | Same capabilities; **simpler navigation** when only one core is exposed |
| **LLM prompts** | Hierarchy + FINAL OVERRIDE + deterministic note compression when chat exists | Keep; extend only with explicit product review (no silent extra LLM passes for “summarize notes”) |
| Reconcile | AI proposes structured updates from notes + conversation; user reviews and applies | Keep; may later feed into “user-shaped” side of gradient |
| Structured schema | Unchanged; + optional `raw_notes` | Remain the contract for Idea/Initiative evaluation and others |
| Perspectives | Not wired to modulation engine | Connect; modulate system perspectives by profile (e.g. 1–5 gradient) |
| Personalities | Not implemented | Future: inferred or explicit; optional participation in perspective flows |

The current implementation is explicitly **transitional** and **foundational**: it establishes the chat-first workspace, **prompt-level** enforcement that the live conversation beats static training text, the reconcile flow toward the structured profile, and documents the intended **singular-core / multi-perspective** product model plus Perspectives integration and user-shaped vs default modulation.
