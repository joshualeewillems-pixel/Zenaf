# Tiered delegation + internal learning loop

**Status:** Partially implemented (v1). **Truth:** `local_ai/delegation/learning_capture.py`, `general_lane.py`, hooks in structured executors; no heavy persistence yet.

## Goals (product)

1. **Broad external lane** — Use stronger cloud models for many AI calls without rewriting every surface behind a bespoke compiled contract.
2. **Bootstrap local quality** — Treat external successes/failures and (later) user outcomes as **training signals** for prompts, heuristics, and future local fine-tuning / distillation.

This doc complements **`COMPILED_DELEGATION_V1.md`** (narrow structured paths). Compiled contracts remain where they matter; they are **not** required everywhere.

---

## Three tiers of delegation strictness

| Tier | Role | Prompt / validation | Typical surfaces (direction) |
|------|------|---------------------|------------------------------|
| **1 — General / fast** | Broad coverage, minimal path rules | Strong internal compiler, bounded context, destination hints, light parse | New or low-risk assistants, summaries, drafts, exploratory tools |
| **2 — Structured** | Explicit JSON (or typed) contract | Schema validation, path-specific distribution | `workspace_next_step`, `initiative_evaluate`, `core_profile_reconcile` (compiled v1) |
| **3 — Strict secure** | Same as structured **plus** privacy engineering | Externalization / placeholder mapping, fail-closed rebind, audit-friendly traces | Same paths as (2) when OpenAI + mapping active; future PHI-adjacent cloud calls |

**Coexistence:** Tier 2/3 code lives in `local_ai/delegation/*` executors + `externalized_inference.py`. Tier 1 is introduced as **`general_lane.py`**: compile → caller-supplied `run_provider` (policy already applied) → optional JSON parse → **non-blocking** learning capture.

---

## Surface → tier (recommended)

| Surface / intent | Tier | Notes |
|------------------|------|--------|
| `workspace_next_step` (structured path) | 2 / 3 | 3 when externalization mapping applies |
| `initiative_evaluate` (structured path) | 2 / 3 | Same |
| `core_profile_reconcile` (structured path) | 2 / 3 | Same |
| Content briefs, meeting prep, generic chat assist | **1** | Wire `run_general_delegation_lane` when routed to cloud |
| High-trust PHI workflows (future) | **3** | Mandatory gating + rebinding before any external model |

**Enable learning first on:** structured next-step, initiative evaluate, reconcile — they already produce validated JSON and stable `action_intent` keys. Add tier-1 surfaces as they are routed through `general_lane`.

---

## LearningRecord (v1 shape)

Implemented as dataclass **`LearningRecord`** in `learning_capture.py` (serialized via `to_json_dict()`).

Stable fields for downstream pipelines:

- `record_id`, `ts_ms`
- `action_intent`, `surface`
- `delegation_tier`: `general` | `structured` | `strict_secure`
- `provider_used`, `model_used` (from `exec_meta`, not UI)
- `validation_passed`, `validation_error`
- `input_snapshot_redacted` (bounded; **empty** in restrictive modes)
- `compiled_prompt_sha256_prefix`, `compiled_prompt_char_len` (reference, not full prompt)
- `model_output_redacted` (bounded JSON/text; **redacted/minimal** in restrictive modes)
- `delegation_path` (e.g. `structured_cloud_v1` when set)
- `externalization_mapping_active`
- `user_outcome`, `outcome_diff_summary` — **reserved** for async client follow-up (`applied` / `edited` / `dismissed` / `copied`); usually `null` at capture time in v1
- `capture_mode`: `full` | `minimal`

**Per-tier learning emphasis:**

- **General:** Broad text/JSON slices; good for prompt templates and coarse error patterns.
- **Structured:** Schema-aligned outputs; best for validator tuning and distribution bugs.
- **Strict secure:** Same as structured for successful parses; under restrictive privacy, **keys-only** or empty payloads — pattern learning without sensitive content.

---

## Where hooks attach (pipeline)

1. **Structured / strict secure** — After each terminal outcome in:
   - `execute_structured_openai_delegation` (`workspace_next_step.py`)
   - `execute_structured_openai_initiative_delegation` (`initiative_evaluate.py`)
   - `execute_structured_openai_core_profile_reconcile_delegation` (`core_profile_reconcile.py`)

   `capture_structured_delegation_outcome(...)` runs **synchronously** but is **O(1)** (short lock + deque append). It **must not** perform I/O or network calls.

2. **General** — At end of `run_general_delegation_lane` (`general_lane.py`) via `capture_general_delegation_outcome(...)`.

**User outcome / diff:** Not wired in v1. Future: API or trace emitter updates `LearningBuffer` by `record_id`, or appends a second artifact — still off the hot path.

---

## Privacy modes and learning

`privacy_mode` values **`restricted`** and **`local_only`** are treated as **restrictive** for learning:

- No raw `input_snapshot` in the buffer.
- Structured outputs: **key names only** with `[redacted]` values (or empty).
- General tier: output stored as `[redacted]`.
- Prompt body is **never** stored; only hash prefix + length.

This avoids breaking privacy guarantees while preserving **intent + surface + validation outcome + schema key shape** for aggregate learning.

---

## Storage

v1: **In-memory** ring buffer (`LearningBuffer`, default max 5_000 entries), thread-safe, plus **optional durable append-only JSONL**.

### Durable persistence (append-only JSONL)

**Enable:** set **`ZENAF_LEARNING_PERSIST_PATH`** to a file path (e.g. `data/learning_records.jsonl`). On API startup, `init_learning_persistence_from_env()` replays the file into the ring buffer (same shape as export). **Missing file** → start empty; **corrupt lines** → skipped with a warning; process keeps running.

**Writes:** each new capture appends one UTF-8 JSON line (`LearningRecord.to_json_dict()`). **`user_outcome` updates** append a **second** line with the same `record_id` and the updated row; replay keeps the **last line per `record_id`** (chronological order in the buffer uses `ts_ms`).

**Rotation (optional):** **`ZENAF_LEARNING_PERSIST_MAX_MB`** — before an append, if the file exists and size ≥ this cap, it is renamed to `basename.YYYYMMDD-HHMMSS.rotated` and a new active file is created. Operators can archive `.rotated` files alongside the active log for longitudinal jobs. **Secure the path** with OS permissions (same sensitivity as export dumps).

**Why JSONL (not SQLite here):** matches export/NDJSON tooling, zero migrations, easy `grep`/stream processing, simple rotation.

**Analysis — reliable today for prompt / validator tuning**

- **`action_intent`**, **`surface`**, **`delegation_tier`**, **`validation_passed`**, **`validation_error`**, **`provider_used`**, **`model_used`**, **`ts_ms`**, **`capture_mode`** — stable for aggregates and error clustering.
- **`compiled_prompt_sha256_prefix`** + **`compiled_prompt_char_len`** — correlate runs without storing prompts.
- **`model_output_redacted`** / **`input_snapshot_redacted`** — useful when **`capture_mode` = `full`**; under **`minimal`**, outputs are redacted by design (still good for tier/mode mix and validation flags).

**Still missing before distillation prep is trustworthy**

- **Volume and label quality:** need enough **`full`** rows (or a deliberate policy to allow bounded text) per surface/model; **`user_outcome`** coverage remains sparse until clients consistently POST outcomes.
- **Train/val split or PII audit pipeline:** still manual; treat files like other operational logs; restricted/local_only rows are intentionally content-poor.

### Offline dedupe + analysis prep (CLI)

Use **`scripts/zenaf_learning_jsonl_prep.py`** (library: `local_ai/delegation/learning_jsonl_prep.py`) to merge **one or more** JSONL files (active + `*.rotated`), **dedupe by `record_id` with last-line-wins** in file stream order, and emit:

- **Cleaned JSONL** (`-o`): one row per `record_id`, sorted by `ts_ms` then `record_id`.
- **Summary JSON** (`--summary-json`): `dedupe` line stats + per-dimension counts (`action_intent`, `surface`, `delegation_tier`, `provider_used`, `model_used`, validation pass/fail, `user_outcome`, `capture_mode`).
- **Stdout** (default): human-readable summary; use `-q` / `--quiet` to suppress.

**File order:** CLI order matters. For rotated + active, list **oldest → newest**, or use **`--sort-files mtime`** (oldest file first) so the active file’s lines win when they repeat an id.

**Privacy:** reads only stored JSON fields; no prompt rehydration or external joins.

**Evidence pass (post-clean):** **`scripts/zenaf_learning_analysis.py`** reads cleaned JSONL and prints:

- validation **failure rate** by `action_intent`
- **user_outcome** distributions by `action_intent` and by `surface`
- **capture_mode** mix by `action_intent`
- **provider/model** counts for **high-failure** intents (≥1 fail, ranked by failure rate) vs **high-success** intents (low failure rate, ≥1 pass)
- **1–2 recommended surfaces** for prompt/validator work (heuristic: volume × failure pain + mixed outcomes)
- coarse **distillation pilot** gate (volume, `full` share, labeled outcomes)

Library: `local_ai/delegation/learning_record_analysis.py` (notebook-friendly: `load_cleaned_jsonl`, `run_full_analysis`, `format_analysis_report`).

Example: `python scripts/zenaf_learning_analysis.py data/learning_clean.jsonl --json-out analysis.json`

**Recommended next analyses after a cleaned file:** see *First prompt-tuning analyses* below.

### Inspect / export (env-gated, authenticated)

**Enable:** set **`ZENAF_LEARNING_EXPORT_ENABLED=1`** (or `true` / `yes` / `on`). If unset, export endpoints return **403**.

**Routes** (all require a logged-in user via `get_current_user`):

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/vision-execution/learning-records/stats` | Aggregate counts: `delegation_tier`, `capture_mode`, `user_outcome`, validation pass/fail (full buffer snapshot). |
| `GET` | `/vision-execution/learning-records/inspect` | Paginated JSON: `offset`, `limit` (1–500), `order` `asc`\|`desc`, plus `records` array. |
| `GET` | `/vision-execution/learning-records/export` | Same pagination; `format=jsonl` (default, `application/x-ndjson`, attachment `zenaf_learning_export.jsonl`) or `format=json` (same shape as inspect). |

**Privacy posture:** Export is a **verbatim dump of stored rows** — no second redaction pass. Restrictive modes already produced **`capture_mode: minimal`**, empty/redacted snapshots, and hash-only prompt references (see *Privacy modes and learning* above).

**Analysis examples** (offline on JSONL): join `validation_passed` × `action_intent`; `user_outcome` rates by `delegation_tier` or `surface`; provider/model mix; time-bucketed volume from `ts_ms`; `capture_mode` share to confirm privacy tier mix.

**Recommended next step after persistence:** run the **JSONL prep script** on active + rotated logs, then prompt/validator analyses on the cleaned file.

### First prompt-tuning analyses (on cleaned JSONL)

1. **Validator failures:** top `validation_error` strings × `action_intent` / `surface` (structured paths first).
2. **Regression by provider/model:** `validation_passed` rate and error mix per `model_used`.
3. **Outcome-linked quality:** where `user_outcome` ≠ `none`, compare `edited`/`dismissed` vs `applied` by surface (proxy for user friction).
4. **Prompt A/B at hash granularity:** bucket by `compiled_prompt_sha256_prefix` + length; no raw prompt text required.

### Minimum bar before distillation prep is trustworthy

- **Volume:** thousands+ of **deduped** rows per target surface/model, not hundreds.
- **`capture_mode`:** enough **`full`** rows that model outputs (redacted) still carry usable structure/text for the task; `minimal`-only corpora are weak supervision for distillation.
- **Labels:** non-trivial **`user_outcome`** or trusted automated validation; without either, stick to **prompt/ICL tuning**, not student training.
- **Stability:** schema and compiler stable enough that historical rows remain comparable (version tags are a future improvement).

---

## Operational proof (implemented)

**First live general-lane surface:** **Core Profile training conversation** (`POST /vision-execution/core-profiles/{id}/conversation`).

- When the client sends **`routing_context`**, the route uses `_run_ve_llm_with_routing` (same seam as reconcile/evaluate). The LLM branch calls **`run_general_delegation_custom_prompt`** with the existing long `CONVERSATION_PROMPT` as the compiled prompt (tier **general**, not a strict JSON contract).
- Response may include **`learning_record_id`** (opaque server id). The cockpit Core Profile panel stores it and POSTs **`/vision-execution/learning-records/user-outcome`** when the user sends another message (**edited**) or closes / navigates away with a pending assistant turn (**dismissed**), mirroring existing AI trace outcomes.
- **Correlation:** Prefer **`learning_record_id`** over trace_id or HTTP request id — it is **created at capture time**, stable for one delegation attempt, unguessable (12 hex chars), and **does not require** the client to parse headers. Optional body field **`outcome_diff_summary`** is accepted but dropped under **`restricted` / `local_only`** privacy when echoing `privacy_mode` from the client.

**Legacy path:** No `routing_context` → no seam → existing `get_default_provider()` flow; **no** `learning_record_id` (unchanged behavior for older clients).

### Structured / strict-secure tier (same correlation primitive)

Compiled delegation paths also append one `LearningRecord` per inference and return **`learning_record_id`** so clients can call `POST /vision-execution/learning-records/user-outcome` the same way as the general lane:

| Path | Response shape |
|------|----------------|
| **`POST /run`** `mode=next_step` (structured OpenAI + `workspace_next_step`) | Top-level `RunResponse.learning_record_id` (alongside `delegation_path`, externalization fields). |
| **`POST /vision-execution/initiatives/{id}/evaluate`** (structured branch) | JSON body field `learning_record_id` on success and structured failures. |
| **`POST /vision-execution/core-profiles/{id}/reconcile`** (structured branch) | JSON body field `learning_record_id` on success and structured failures. |

### General lane: **Idea evaluate** (`POST /vision-execution/ideas/{id}/evaluate`) — **implemented**

- **Behavior:** Same multi-attempt strict/relaxed evaluator as before (`idea_evaluate.py`). When **`routing_context` is present**, **`use_execution_seam`**, and policy resolves **`provider_used == openai`**, the handler appends **one** tier-general `LearningRecord` per HTTP request (after all internal attempts) via `capture_general_delegation_outcome`, and returns **`learning_record_id`** on the JSON body. **No** `learning_record_id` on legacy paths (no routing context, or Ollama primary, or provider failure before evaluation).
- **Not strict compiled:** Still tolerant MVP JSON contract + relaxed mode; no `initiative_evaluate`-style validator.

### User outcomes (client → `POST /learning-records/user-outcome`)

Wired for: **Core Profile conversation** (existing), **Core Profile reconcile**, **Initiative evaluate**, **Idea evaluate**, **Workspace next step** (when `/run` returns `learning_record_id`). Same endpoint and payload shape everywhere.

---

## Non-goals (v1)

- Training a model inside the app.
- Blocking the user response on learning I/O.
- Embedding provider selection logic in the frontend.

---

## References

- `COMPILED_DELEGATION_V1.md` — compiled JSON contracts
- `PRIVACY_EXTERNALIZATION_AND_REBINDING.md` — tier 3 data washing
- `POLICY_PROVIDER_EXECUTION.md` — where `exec_meta` / routing are set (server-side)
