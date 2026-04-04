# Atria System Charter (v0)

<!--
Status: Canonical (extracted truth → enforceable rules)
Last updated: 2026-04-03
-->

This document encodes **direction as law**: testable constraints, not aspirations. Implementation may lag; violations belong in **`ATRIA_CHARTER_VIOLATION_LEDGER.md`**.

---

## 0. What Atria is

Atria is a **decision and execution mediation** system. It **does not replace user judgment**; it **structures, routes, and records** it. It must **never fabricate certainty** or pretend something is durable when it is not.

---

## 1. Truth ownership

### 1.1 Entity truth (Vision & Execution)

- **Source:** `vision_execution` SQLite + `local_ai.vision_execution` service/storage.
- **UI** is a projection only; no parallel authoritative entity store.

**Rule:** If it is not persisted in VE storage (for VE-scoped entities), it is not entity truth.

### 1.2 Council configuration

- **Target:** reproducible **server-owned** definitions (e.g. perspectives API + persistence).
- **Client** may edit and cache but must not be the sole source of truth for signed-in operation.

**Rule:** Council configuration must be reconstructible without relying on a single browser session.

### 1.3 Core identity vs archetypes

- **User core** → `core_profiles` (and related APIs).
- **System archetypes** → built-in perspective templates (e.g. `BUILT_IN_PERSPECTIVES`); templates are not user identity.

**Rule:** Persisted identity is user-owned; archetypes are templates, not the user’s truth.

### 1.4 Intake product contract

- **Product-facing intake** = **Tier A** behavior only unless explicitly re-chartered.
- Deeper tiers in code are **not** public capability until API + UI + docs align.

**Rule:** Do not advertise or imply capabilities that the shipped API and UI do not support.

### 1.5 Authenticated identity resolution

**Rule:** Authenticated requests must resolve to canonical user identity when explicit profile is not provided, unless explicitly declared as profile-agnostic.

---

## 2. Save and commit (deterministic truth)

### 2.1 Confirmed commit

- User **confirmation** of a structured write must **not** re-involve an LLM to “decide” the payload.

**Rule:** No model involvement in **confirmed** writes; execute from explicit payload.

### 2.2 Schema grounding

- Writable field names and shapes come from **schema / contracts**, not from ad hoc UI keys.

**Rule:** Do not persist to non-existent or inferred fields.

### 2.3 Payload integrity

- Saves require an **explicit payload** (e.g. tagged draft value, structured patch). Control text alone is insufficient.

**Rule:** If the payload is ambiguous, **do not save**; surface a nudge or error.

### 2.4 Honest failure

- Missing or invalid payload → visible nudge or failure, not silent substitution.

**Rule:** Fail **visibly**, not silently.

---

## 3. Model behavior (Zenaf discipline)

### 3.1 Grounding

- Replies must be grounded in **PRIMARY / supplied context**; no invented product features or context bleed.

**Rule:** The model must not introduce domain facts not supported by supplied context.

### 3.2 Mode lock

- **Trunk / mode** selects response shape and obligations; do not cross modes in one turn.

**Rule:** Output structure follows the selected mode strictly.

### 3.3 Execution vs reflection

- “Finalize / decide / integrate” postures are **execution**, not open-ended reflection.

**Rule:** Language intent maps to execution posture where the mode demands it.

### 3.4 No helpful hallucination

**Rule:** Helpfulness does not override accuracy or grounding.

---

## 4. Traceability

### 4.1 Trace or exempt

- Every **AI-touching** path either:
  - emits a **client trace** (`AiActionTrace` / meeting/workspace equivalents), **or**
  - emits a **server trace** where the client cannot see the run, **or**
  - is listed in **`frontend/src/ai-actions/aiTraceExemptRegistry.ts`** with a stable id and reason.

**Rule:** No silent AI behavior.

### 4.2 Trace integrity

- A trace must carry enough to explain the act without external lore: at minimum **intent**, **subject**, **surface**, **origin** (client vs server), within bounded snapshots.

**Rule:** Traces must be self-explanatory at the row level.

### 4.3 Server trace authority

- Backend-only LLM routes must emit **server-side** lineage (e.g. `local_ai/ai_action_trace/server_emit.py` patterns).

**Rule:** If the frontend cannot observe the run, the server must still record it.

---

## 5. Product honesty

### 5.1 No phantom features

- Routes, components, or docs in repo **≠** shipped product unless mounted in the cockpit contract.

**Rule:** Code existence alone does not make a feature real for users.

### 5.2 No partial claims

- Tier B/C, experimental panels, and operator tools are **out of product contract** until explicitly chartered.

**Rule:** Marketing and primary UI must match **runtime** capability.

### 5.3 UI language

- Labels and affordances must map to **real fields and behaviors**.

**Rule:** No conceptual placeholders presented as finished capability.

---

## 6. Context and scope

### 6.1 Scoped digression

- Scoped threads must **constrain** reasoning and **omit** full developmental / aspiration / thread merge where the charter path says so.

**Rule:** Scoped mode must not silently leak unrelated context into the authoritative packet.

### 6.2 Continuity

- Active **subject / entity** should persist across turns unless the user changes focus.

**Rule:** Avoid unnecessary re-derivation of subject that breaks continuity.

---

## 7. Failure and degradation

**Allowed:** ask for clarification; refuse; fall back to an **explicit** documented mode.

**Not allowed:** silent substitution, silent omission, silent reinterpretation of user intent.

**Rule:** Degradation must be **explicit** and **recoverable**.

---

## 8. Field naming

- **Canonical names** live in DB models and API schemas; UI uses labels that map to those names.

**Rule:** One canonical name per persisted field.

---

## 9. Refinement principles

1. **No duplicate truth** — remove parallel sources of the same fact.
2. **No silent fallback** — every fallback is visible or logged under a named policy.
3. **Prefer removal** over abstraction for dead systems.
4. **Enforce before expand** — stabilize truth before adding surface area.

---

## 10. Automation eligibility

Automation is appropriate when: rule is **explicit**, violation is **detectable**, outcome is **deterministic** (e.g. trace inventory, schema vs label diff, dead route detection).

Automation is **not** appropriate for: interpretation, product direction, or philosophical tradeoffs.

---

## Related docs

| Doc | Role |
|-----|------|
| `ACTIVE_VS_PLANNED.md` | Operational as-built vs roadmap |
| `AI_ACTION_SUBSTRATE_COVERAGE_MATRIX.md` | Trace coverage inventory |
| `TRUTH_CONVERGENCE.md` | Locked convergence decisions |
| `ATRIA_CHARTER_VIOLATION_LEDGER.md` | Audit status + violations |
| `GLOBAL_PHILOSOPHY_INTEGRATION_MATRIX.md` | Per-philosophy scope, partials, class (A/B/C), enforcement hooks |
