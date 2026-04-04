# Role Model — Design Note

**Status:** Design  
**Scope:** Clarify “roles” in the perspective/council system without adding a second redundant personality system.  
**Goal:** Make roles intentional and non-redundant by treating them as **mandates** attached to **profiles**, forming **seats** at runtime.

---

## 1. Definitions

| Term | Definition |
|------|-------------|
| **Profile** | A cognitive identity / way of thinking. This is the existing “perspective” (e.g. Strategist, Artist, Phil, Analyst, Brand). One profile = one voice, reasoning style, decision fingerprint, and optional persona. Profiles are listed and edited in the Perspectives/Content personality layer; they are **not** duplicated as “roles.” |
| **Mandate** | The **responsibility** the profile is serving in a given context. Examples: strategic, governance, operator, integrator, creative, risk, execution. A mandate answers “what hat is this profile wearing here?” It is not a second personality; it is a lens or job. |
| **Seat** | A **runtime pairing** of Profile × Mandate. Examples: Strategist / Governance, Artist / Strategic, Phil / Integrator. The seat is what is actually invoked in council, chat, or content generation. One profile can appear in many seats (e.g. Phil / Integrator, Phil / Strategic) without duplicating the profile. |

**Architectural rule:** Do not create separate parallel systems for perspectives, roles, and seats. There is one list of **profiles** (cognitive identities), one list of **mandates** (responsibilities), and **seats** are the runtime combination of the two.

---

## 2. Why this structure

We should **not** maintain separate redundant lists for “perspectives” and “roles” as if both were personalities. That would create two sources of truth for “who is thinking” and encourage duplication (e.g. “Strategic Perspective” and “Strategic Role” with overlapping traits).

- **Profiles are cognitive identities.** They answer “who”: voice, reasoning, decision style, constraints. They are the single place we define a way of thinking. The existing Perspectives (and, where used, personality profiles) are profiles.
- **Mandates are responsibilities.** They answer “what they’re focused on in this context”: strategic direction, governance, execution, risk, integration, creativity. They are lightweight, reusable descriptors that can be mixed with any profile.
- **Seats are the runtime combination.** When we “consult the Strategist in a governance mandate” or “generate in Phil’s voice with an execution mandate,” we form a seat: profile_id + mandate_id. The same profile can serve different mandates in different calls without duplicating the profile.

This keeps one personality layer (profiles) and makes “role” a clear, non-redundant concept (mandate) that composes with profiles at use time.

---

## 3. Minimal mandate schema

A mandate is a small, first-class object. At minimum:

| Field | Purpose |
|-------|---------|
| **id** | Stable identifier (e.g. `strategic`, `governance`, `operator`). |
| **name** | Human-readable label (e.g. “Strategic”, “Governance”, “Operator”). |
| **core_question** | The central question this mandate focuses on (e.g. “What is the right direction?” “What are we optimizing for?”). |
| **optimize_for** | What this mandate optimizes for (e.g. “leverage”, “safety”, “throughput”). |
| **watch_for** | What this mandate is meant to watch for or flag (e.g. “drift”, “blockers”, “compliance gaps”). |
| **failure_mode** | Typical failure mode to avoid (e.g. “analysis paralysis”, “over-optimism”). |
| **output_style** | How output should be shaped (e.g. “recommendation”, “trade-off”, “constraints”). |

Mandates are **not** full personalities. They are reusable “hats” that can be combined with any profile to form a seat. Persistence can be a small list (built-in + optional user-defined) without a heavy roles engine.

---

## 4. Runtime behavior

A **seat** is formed at invocation time as:

- **profile_id** — which cognitive identity (e.g. Strategist, Phil).
- **mandate_id** — which responsibility (e.g. governance, execution).
- **capability/access settings** — optional (e.g. advisory vs active, memory lens, domain scope), consistent with the existing seat model in the personality/profile design.

The runtime (council, chat, content generation) receives a **seat** (profile + mandate + settings). It loads the profile for voice and reasoning, and the mandate for core_question, optimize_for, watch_for, and output_style. The prompt or context assembly combines both: “Answer as [profile name], in the [mandate name] mandate: [mandate core_question]. Optimize for [optimize_for]; watch for [watch_for].”

No separate “role personality” is stored or mixed in. The same profile can be invoked with different mandates in different calls.

---

## 5. UI implications

Recommend a **thin** UI model:

- **Profiles list** — Existing (Perspectives / personality profiles). Create and edit cognitive identities only here.
- **Mandates list** — New, small list: built-in mandates (strategic, governance, operator, integrator, creative, risk, execution) plus optional user-defined. Edit name, core_question, optimize_for, watch_for, failure_mode, output_style.
- **Seat selection/composition** — In AI Agents chat and other relevant module contexts: choose “Profile” and “Mandate” to form the seat for this conversation or action (e.g. “Consult as: [Profile dropdown] / [Mandate dropdown]”).

**Do not** create a whole separate major “roles system” that duplicates perspectives. **Do** allow context-specific invocation, for example:

- Consult a perspective (as a seat: profile + mandate) on an Idea / Initiative / Project / Task in Vision & Execution.
- Generate content in a selected profile/mandate voice in the Content tab.
- Ask council from a VE object context with an optional default seat or per-participant seat.

No workflow engine, no role analytics, no marketplace UI in scope for this note. Keep persistence minimal (e.g. mandates as a small table or config; seats as runtime composition unless we need to “save favorite seats” later).

---

## 6. Integration points

This model should be **callable** from:

| Surface | How seat is used |
|---------|------------------|
| **AI Agents chat** | Primary thinking interface. User selects or composes a seat (profile + mandate) for the conversation. Replies and reasoning use that profile’s voice and the mandate’s focus (core_question, optimize_for, watch_for, output_style). |
| **Vision & Execution** | On an idea, initiative, project, task, or people-capacity view: “Consult [Profile] / [Mandate]” or “Ask council from this [object].” Seat is passed into the call; context includes the selected VE entity. |
| **Content tab** | When generating script or newsletter (or other outputs): user selects profile + mandate for “voice” and focus. Generation uses that seat so output is in the right cognitive identity and mandate style. |

**Keep it light:**

- No workflow engine.
- No role analytics in this phase.
- No marketplace UI yet.
- No major new persistence unless necessary (e.g. a small mandates table and optional “saved seats” later).

**Goal:** Make roles intentional and non-redundant by treating them as mandates attached to profiles, forming seats at runtime — one personality layer (profiles), one responsibility layer (mandates), one runtime object (seat).
