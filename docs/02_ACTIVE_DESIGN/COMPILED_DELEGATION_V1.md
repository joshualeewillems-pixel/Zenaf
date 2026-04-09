# Compiled / structured cloud delegation — v1 (narrow)

**Status:** Implemented for:

1. **`workspace_next_step`** — `POST /run` `mode=next_step` + **`routing_context`** + OpenAI + `action_intent == workspace_next_step`.
2. **`initiative_evaluate`** — `POST /vision-execution/initiatives/{id}/evaluate` with **`routing_context`** + OpenAI + `action_intent == initiative_evaluate`.

**Not in scope (yet):** `idea_evaluate`, general `externalization_strategy` across VE, policy fallback-chain execution, new `AiActionKind`, council / file steward delegation.

**See also:** **`TIERED_DELEGATION_AND_LEARNING.md`** — general (fast) lane vs structured/strict tiers and the in-memory learning buffer hooked after these executors.

## Responsibility split

| Layer | Owns |
|--------|------|
| **Internal (Zenaf)** | Task intent, bounded context selection, privacy/routing gating, output schema definition, prompt synthesis layout, validation, rebinding placeholders, mapping to API `result`, trace fields |
| **Remote model** | Bounded inference: emit **one JSON object** matching the contract — **not** workflow or storage |

## Pipeline (`workspace_next_step`)

1. **Contract** — `build_workspace_next_step_contract` (`local_ai/delegation/workspace_next_step.py`): caps context/question length; records `output_schema_id`, destination hint, optional `subject_id_hint`.
2. **Prompt synthesis** — `synthesize_structured_cloud_prompt`: modular sections (instruction framing, task, bounded context blocks, JSON schema text). **Not** inside `OpenAIProvider`.
3. **Externalization** — Existing `maybe_externalize_for_cloud` (after contract prompt is built, before `generate_next_step_raw`). Same activation rules as v1 externalization doc.
4. **Transport** — `generate_next_step_raw` → `get_default_provider().generate(prompt)` only.
5. **Rebind** — `rebind_after_cloud_response` on **raw** text (before JSON parse).
6. **Parse** — `extract_json_object` + `json.loads` (`local_ai/delegation/json_extract.py`).
7. **Validate** — `validate_workspace_next_step_json`: **exact** four keys, strict types, length caps; **no** coercion (e.g. `alternatives` must be a JSON array).
8. **Distribute** — `distribute_to_next_step_api_shape` → same `result` shape as legacy: `recommendation`, `rationale`, `alternatives`, `caution`.

## Request/response contract (JSON from model)

Required top-level keys **only**:

- `recommendation` — non-empty string (max 600 chars after trim)
- `rationale` — string (max 2500)
- `alternatives` — array of strings (max 12 items, each max 400); empty allowed
- `caution` — string or `null` (max 800); empty string normalized to `null`

Unknown keys → validation failure → `ok: false`, explicit error (no line-parser fallback).

## Trace

- **`workspace_next_step`:** `RunResponse.delegation_path == "structured_cloud_v1"` when the structured path ran. If routing + OpenAI would apply but **both** context and question are empty, `RunResponse.delegation_skip_reason == "empty_next_step_context_and_question"` and a server log line explains the skip.
- **`initiative_evaluate`:** evaluate response JSON includes `delegation_path: "structured_cloud_v1"` on success **and** on structured validation/provider failures (still `error` set).
- **`core_profile_reconcile`:** same `delegation_path` convention on the reconcile response object.

## Legacy behavior preserved

- **No `routing_context`** — unchanged: `build_next_step_prompt` + line-oriented `parse_next_step_model_output`.
- **`routing_context` but not (OpenAI + `workspace_next_step`)** — unchanged: legacy prompt + externalization + line parse (e.g. Ollama with routing metadata).

## Files

| Area | Path |
|------|------|
| Types / label | `local_ai/delegation/types.py` |
| JSON extraction | `local_ai/delegation/json_extract.py` |
| **Shared:** strict rebind + integrity gate + OK redaction | `local_ai/delegation/externalized_inference.py` (`strict_rebind_cloud_output`, `redact_when_mapping_ok`, `INTEGRITY_FAILURE_MESSAGE`) |
| Identifier / mode-specific externalize | `local_ai/execution_policy/externalization.py` (`maybe_externalize_for_cloud`, `maybe_externalize_structured_initiative_evaluate_for_cloud`, `maybe_externalize_structured_core_profile_reconcile_for_cloud` v1 noop hook, `apply_ordered_identifier_mappings`) |
| Workspace: contract, synthesis, validate, execute | `local_ai/delegation/workspace_next_step.py` |
| Initiative: contract, synthesis, validate, execute | `local_ai/delegation/initiative_evaluate.py` |
| Core profile reconcile: contract, synthesis, validate, execute | `local_ai/delegation/core_profile_reconcile.py` |
| Wire-in (workspace) | `api/main.py` `_run_next_step` |
| Wire-in (initiative + reconcile) | `api/routes/vision_execution.py` (`_run_ve_llm_with_routing` + `local_ai/vision_execution/initiative_evaluate.py` / `core_profile_reconcile.py`) |
| Tests | `tests/test_delegation_externalized_inference.py`, `tests/test_delegation_workspace_next_step.py`, `tests/test_workspace_next_step_cockpit_integration.py`, `tests/test_delegation_initiative_evaluate.py`, `tests/test_delegation_core_profile_reconcile.py`, `tests/test_externalization_initiative_evaluate.py`, `test_run_routing_context.py`, `test_externalization_next_step.py` |

## Initiative evaluate — compiled branch

**Branch condition (all required):** `use_execution_seam` (request had `routing_context`), `routing_payload` present, `exec_meta["provider_used"] == "openai"`, `routing_payload["action_intent"] == "initiative_evaluate"`.

**Otherwise:** legacy `EVALUATE_PROMPT`, alias-based parsing, **one retry** with `EVALUATE_RETRY_SUFFIX` (unchanged).

**Contract keys (exact):** `estimated_cost_ai`, `estimated_timeframe_ai`, `philosophical_alignment_ai`, `recommendation`, `next_steps`, `evaluation_priority`, `strategic_value`, `energy_impact`.

**Validation:** exact key set; four strings non-empty (length caps); `next_steps` length 3–5, each string non-empty; scores **`type is int`** (rejects `bool`, `float`, string numerals), range 0–5; malformed fragment regex; **no** field aliases on this path.

**Distribution:** same dict shape as legacy success (plus `delegation_path` on structured success).

**Externalization (narrow v1):** After synthesis, `maybe_externalize_structured_initiative_evaluate_for_cloud` (`local_ai/execution_policy/externalization.py`) may replace **verbatim** occurrences of:

- **`initiative_id`** — path param from `POST /initiatives/{id}/evaluate` (only if that string appears in the synthesized prompt, e.g. in `brief` or core profile text).
- **`user_id_for_externalize`** — same value as `user_id` passed to `evaluate_initiative` (account id), only if it appears verbatim in the prompt (e.g. embedded in core profile summary).

Replacements use `[[ZENAF_REF:kind:…]]` tokens (longest id first). **Rebind** runs on raw model output before JSON extract; **fail closed** if tokens are missing, corrupted, or invented (same integrity rules as workspace next step). `redact_externalization_for_privacy` applies when mapping was active. Legacy initiative path is unchanged.

**Transport:** `provider.generate(external_prompt)` (shim from `ve_eval_provider_shim`).

**Routed VE metadata:** `_run_ve_llm_with_routing` sets `model_used` / `provider_used` from policy resolution on **any** dict result when `routing_context` was present (`setdefault`), including structured errors — truthful selected seam, not “model never called” for provider errors after routing.

---

## Stopping point (v1)

The system can **prepare an exact task** and **safely consume** JSON for **workspace next step** and **initiative evaluate** (OpenAI + routed seams), with **narrow** initiative id washing as above. Broader washing and `idea_evaluate` are **manual / future** work.

---

## Operational verification (cockpit)

**UI path:** `frontend/src/App.tsx` → `runNextStep` always attaches `routing_context` from `workspaceRunRoutingContext(WORKSPACE_ACTION_INTENTS.next_step, false)`, i.e. `surface: workspace_organizer`, `action_kind: structured_evaluation`, `action_intent: workspace_next_step`, plus `privacy_mode` from Settings.

**Structured branch activation** requires **both**:

1. That shape of `routing_context`, and  
2. Execution policy resolution yielding **`provider_used == openai`** for that intent (e.g. `workspace_next_step` override in `config/ai_execution_policy.json`).

If the policy primary is **Ollama**, the same request stays on the **legacy line-based** parser; `delegation_path` is omitted. This is intentional (local path unchanged).

**Integration tests** (cockpit-shaped JSON body): `tests/test_workspace_next_step_cockpit_integration.py` — OpenAI → `delegation_path`, malformed JSON → `ok: false` + trace, Ollama → no `structured_cloud_v1`.

## Weak points / gaps (v1)

| Gap | Notes |
|-----|--------|
| **Empty context + empty question** | `build_next_step_prompt` returns `None` → `suggest_next_step` runs **before** the structured branch; **`delegation_skip_reason`** + log when routing + OpenAI + `workspace_next_step`. |
| **Policy vs UI** | Cockpit always sends routing; **cloud structured path** only when policy says OpenAI. Operators should confirm policy for `workspace_next_step` matches intent (integration tests assume override). |
| **Frontend trace** | `RunResponse` in `App.tsx` includes optional `delegation_path` for typing; UI does not surface it yet (no redesign required). |
| **Retry** | N/A on **structured** initiative path (single `generate`); **legacy** initiative path still uses second prompt attempt. |
| **Initiative leakage beyond two ids** | Title, brief prose, PII in free text, and ids not equal to path `initiative_id` / account `user_id` are **not** externalized on this path. |

---

## Shared externalization/rebind pattern (refactor)

Compiled paths reuse **`local_ai/delegation/externalized_inference.py`**:

- **`mapping_active_for_externalize(ex)`** — whether tokens were sent.
- **`strict_rebind_cloud_output(raw, ex, privacy_mode=...)`** → **`StrictRebindOk`** or **`StrictRebindIntegrityFailure`** (fail-closed before JSON parse).
- **`redact_when_mapping_ok(...)`** — attach OK externalization diagnostics when mapping was on.
- **`INTEGRITY_FAILURE_MESSAGE`** — single string for integrity failures.

**Still path-specific:** `maybe_externalize_for_cloud` vs `maybe_externalize_structured_initiative_evaluate_for_cloud`, prompt synthesis, JSON validators, distribution, and transport (`generate_next_step_raw` vs `provider.generate`).

---

## Core profile reconcile — compiled branch

**Branch condition (all required):** `use_execution_seam`, `routing_context` present, `exec_meta["provider_used"] == "openai"`, `routing_context["action_intent"] == "core_profile_reconcile"` (same as `INTENT_RECONCILE` in `core_profile_execution.py`).

**Otherwise:** legacy `RECONCILE_PROMPT`, permissive coercion (`str()` on non-strings), merge empty → current snapshot.

**Contract:** exactly the 11 `STRUCTURED_KEYS` strings; **no** `null`; **no** numeric/object values; per-field max length (delegation module). **Distribution:** same as legacy — whitespace-only model value → keep `current_structured` field for apply compatibility.

**Externalization:** `maybe_externalize_structured_core_profile_reconcile_for_cloud` is **identity** in v1 (hook for future `profile_id` / `user_id` in prompt). **Rebind** still runs via shared `strict_rebind_cloud_output` (no-op when mapping off).

---

## Next structured delegation target (recommendation)

| Candidate | Verdict |
|-----------|---------|
| **`idea_evaluate`** | Still **normalization-dependent** (`roi_potential` default, `_normalize_recommendation` / `Incubate`). Needs an explicit **strict** product path before mirroring compiled delegation. |
| **Other VE JSON surfaces** | e.g. content generation, meeting extraction — evaluate case-by-case for fixed schema + no silent repair. |

**Shipped third path:** **`core_profile_reconcile`** (this doc section above).
