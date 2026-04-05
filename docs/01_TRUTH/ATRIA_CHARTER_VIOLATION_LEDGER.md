# Atria Charter — Violation Ledger

<!--
Status: Living document
Last updated: 2026-04-04
-->

Companion to **`ATRIA_SYSTEM_CHARTER.md`**. This ledger records **audit status** and **known gaps** without redesigning features. For **per-philosophy scope, partial integration, and enforcement hooks**, see **`GLOBAL_PHILOSOPHY_INTEGRATION_MATRIX.md`**.

---

## Audited and coherent

| Topic | Status | Evidence / notes |
|-------|--------|------------------|
| **Coordination plumbing (activity → judgment → read API)** | Coherent for the acknowledged suggestion path | `log_coordination_client_checkpoint` → `append_execution_flow_reading` → `GET /vision-execution/coordination/execution-flow-readings`; pointer `activity_event` + `atria-client-trace`; tests in `tests/test_coordination_signals.py` |
| **Client-checkpoint positive branch** | Coherent for `ai_suggestion_applied` + `user_outcome=applied` | `local_ai/vision_execution/storage.py`: non-neutral `execution_flow_reading` only in that narrow case; council writer unchanged (neutral) |
| **Trace discipline (server meeting debug + core profile LLM routes)** | Substantially hardened for instrumented routes | `api/routes/vision_execution.py` + `local_ai/ai_action_trace/server_emit.py` (`trace_meeting_debug_extract_route`, `trace_core_profile_llm_route`); debug `subject_id` de-collision |

---

## Closed at lab level (interpretation / synthetic only)

**Not** charter “all clear” for product mint or real-user claims — only that the **lab slice** is stable and separated from entity truth.

| Topic | Status | Evidence / notes |
|-------|--------|------------------|
| **Arc detector v0.1 (`friction_to_done`)** | **Lab-stable** | Heuristic + `collect_flow_readings_from_judgment_rows`, table `arc_detection_candidates`, CLI `python -m local_ai.vision_execution.detect_arcs`. **Synthetic lane:** `arc_lab_synthetic@local.atria`, `ARC-LAB:*` titles, `scripts/seed_arc_lab_fixtures.py`, `scripts/eval_arc_detector_lab.py` (regression on expected skips/match). **Spec:** [`docs/02_ACTIVE_DESIGN/ARC_DETECTION_FIXTURE_SPEC.md`](../02_ACTIVE_DESIGN/ARC_DETECTION_FIXTURE_SPEC.md). **Carry-forward:** Arc lab proves the **interpretation layer** (detector, storage, seeded eval, E2E path). Further work here is **productization** (real-lane calibration, mint UX, policy graduation) — not another round of lab-only refinement unless definitions change. |

---

## Next charter audit priority (highest-order gaps)

When leaving the arc lab: prefer **repo-wide trace truth** closure — align `AI_ACTION_SUBSTRATE_COVERAGE_MATRIX.md` with Charter §4 (**full client trace or named exempt**) for remaining **No** rows (Content `/run`, meeting extract, evaluate outcomes, etc.); see **First-pass violation audit §A** below. **In parallel** (not lab polish): **identity / perspective fallback** consistency across VE + Foundation (`ACTIVE_VS_PLANNED.md`, `SINGULAR_CORE_PROFILE_CONVERGENCE_AUDIT.md`), **deterministic commit/save** beyond the integration-commit slice (§B), and **scoped-context leakage** (full `council_preflight` thread vs PRIMARY audit — ledger **Not yet audited**).

---

## Audited but weak / provisional

| Topic | Status | Evidence / notes |
|-------|--------|------------------|
| **Coordination → product influence** | Weakly activated | `buildDevelopmentalGuidanceContext` + `format_developmental_guidance_packet_block`: flow hypotheses can fire; packet cap (`_PACKET_MAX_CHARS = 1200`) + secondary context cap (`MAX_COUNCIL_SECONDARY_CONTEXT_CHARS = 2000`) limit reliable visibility — see `local_ai/developmental_guidance.py`, `local_ai/atria_tools.py` |
| **`execution_flow_reading` council writer** | Intentionally neutral only | `local_ai/atria_tools.py` — no positive/negative from council auto-append by design today |
| **Trace outcomes on some VE flows** | Partial | `AI_ACTION_SUBSTRATE_COVERAGE_MATRIX.md`: initiative/idea evaluate — trace on success; **apply/dismiss not pushed** to trace ring |
| **`infer_draft_value_from_context`** | Provisional / narrow escape hatch | `local_ai/integration_commit.py` — when `[DRAFT_VALUE]` missing; charter §2.3/§2.4 tension if overused |

---

## Not yet audited

| Topic | Status | Notes |
|-------|--------|-------|
| **Repo-wide charter compliance sweep** | Not done | No systematic pass over all `POST /run` modes, all VE LLM routes, intake mirror, file steward edge cases |
| **Council configuration reproducibility** | Partially documented | `ACTIVE_VS_PLANNED.md` — server perspectives + localStorage cache; full reproducibility audit pending |
| **Scoped digression leakage** | Spot-checked only | `council_preflight.build_enriched_council_context` omits developmental guidance when scoped — full thread/PRIMARY split audit pending |
| **Schema vs every VE UI field** | Not exhaustively proven | Charter §8 — spot fixes exist; no automated diff UI label ↔ API field |

---

## First-pass violation audit (2026-04-03)

Mechanical, repo-grounded. **Severity:** **critical** (truth/safety), **misleading** (user trust), **minor** (operator / consistency).

### A. Trace coverage gaps (Charter §4)

| Finding | Severity | Evidence | Smallest fix direction |
|---------|----------|----------|------------------------|
| Content surface `/run` + distill + transcript sort **without** `AiActionTrace` | **misleading** vs §4.1 “full coverage or exempt” | `docs/01_TRUTH/AI_ACTION_SUBSTRATE_COVERAGE_MATRIX.md` rows: Content script/newsletter/regenerate, distill-source, transcript sort, zero-state — **Trace: No** | Add traces **or** add **named exempts** in `aiTraceExemptRegistry.ts` with call-site comments |
| Meeting extract pipelines **no client `AiActionTrace`** | **misleading** | Same matrix: extract / segments / synthesis — **Trace: No**; review screen / commit — **Trace: No** | Same: trace batch per extract **or** exempt + server trace-only policy documented |
| Voice → transcribe → insert **not** `AiActionTrace` | **minor** (declared exempt) | `aiTraceExemptRegistry.ts` `voice_transcribe_only`; matrix row agrees | None required if policy accepted; else narrow “transcribe trace” |
| Core profile conversation/reconcile: **client trace No**; **server** `trace_core_profile_llm_route` exists | **minor** (split authority) | Matrix; `api/routes/vision_execution.py` calls `trace_core_profile_llm_route` | Document “server-only trace” as intentional **or** add client ring rows |
| Initiative/idea evaluate: **apply/dismiss not pushed** to trace | **minor** | Matrix: User outcome **No** for evaluate | Wire `pushAiActionTrace(withTraceOutcome(...))` on apply/dismiss |
| Studio / operator bakeoffs | **minor** | `aiTraceExemptRegistry.ts` `studio_admin_surface` | Keep exempt until aligned with cockpit contract |

### B. Commit / save vs deterministic truth (Charter §2)

| Finding | Severity | Evidence | Smallest fix direction |
|---------|----------|----------|------------------------|
| **`infer_draft_value_from_context`** when tag missing | **misleading** if triggered often | `local_ai/integration_commit.py` + comments in `api/main.py` (committed text from `pending["value"]`) | Tighten gates; log when inference used; prefer nudge per §2.4 |
| Broader “LLM on confirm” | **not verified exhaustive** | Integration commit path bypasses model on confirm when payload present — **full** audit of all PATCH/POST “apply AI” handlers not done this pass | Next audit slice: grep `evaluate` apply handlers + integration apply |

### C. Phantom or overpromising surfaces (Charter §5)

| Finding | Severity | Evidence | Smallest fix direction |
|---------|----------|----------|------------------------|
| **Idea “Clarify with AI”** — stub, no LLM | **misleading** if copy implies AI | `ACTIVE_VS_PLANNED.md` + matrix: “timed local fill” | Rename/disclose stub in UI **or** remove affordance until wired |
| **Tier B/C** code paths exist; **not** product | **minor** (documented) | `ACTIVE_VS_PLANNED.md` “Implemented but Incomplete” / policy | Keep out of primary UX copy; charter already says Tier A only |
| **Soil (dev)** mounted under `import.meta.env.DEV` | **minor** | `ACTIVE_VS_PLANNED.md` soil bullet | Ensure non-dev builds never imply soil is user product |
| **Multiple core profiles** allowed vs “one canonical” direction | **minor** | `ACTIVE_VS_PLANNED.md` Perspectives row | UX/docs alignment only; no schema change required for ledger |

---

## How to use this ledger

1. Fix or accept each row (exempt + reason, or code change).
2. Move topics between **Audited and coherent** / **weak** / **not yet audited** when evidence changes.
3. Prefer **automation** (Charter §10) for rows with deterministic detection (e.g. matrix drift vs `aiTraceExemptRegistry.ts`).

### Mechanical enforcement (v0)

From repo root:

```bash
python scripts/charter_enforcement_check.py
```

**What it checks (narrow, repo-grounded):**

1. **Trace (Charter 4)** — `api/routes/vision_execution.py` route handlers that use `_run_ve_llm_with_routing` or other heuristically detected LLM entry points must contain `trace_core_profile_llm_route`, `trace_meeting_debug_extract_route`, or `emit_server_ai_action_trace` in the **same function body**, **or** a comment `# charter-trace-exempt: <id>` where `<id>` exists in `aiTraceExemptRegistry.ts`. Meeting chunk routes with trace helpers are recognized. **False positives/negatives** are possible if logic moves to shared helpers without updating the script.
2. **Commit (Charter 2)** — flags presence of `infer_draft_value_from_context` in `integration_commit.py` and its use in `atria_tools.py` for manual review.
3. **Product honesty (Charter 5)** — detects Idea Lab **“Clarify with AI”** stub (no `fetch`/`apiPost` in handler) as a label/behavior mismatch candidate.

Optional CI gate: `CHARTER_ENFORCE_STRICT=1` exits non-zero when any **misleading**-severity row is reported (trace gaps + stub button + integration fallback definition).
