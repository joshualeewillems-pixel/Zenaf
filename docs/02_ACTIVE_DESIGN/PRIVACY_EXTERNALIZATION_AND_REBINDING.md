# Privacy-preserving externalization (“data washing”) & rebinding

**Status:** Architecture — **complements** existing privacy gating (allow/block, fallback filtering, `execution_blocked`, trace redaction). **Does not replace** any of that.

**Problem:** Sometimes **local models are too weak** and **approved cloud models** are desired, but **raw sensitive identifiers, PHI-adjacent text, or firm-specific details** must not cross the external boundary unchanged.

**Approach:** An optional **pre-execution transformation** layer produces an **external-safe payload** and a **reversible mapping**; after the model returns, **rebind** placeholders back to internal references in a controlled way.

---

## 1. Relationship to the current privacy stack

| Layer | Role | Keep? |
|--------|------|--------|
| **Gating / filtering** | `require_local`, allowlists, `allow_cloud_fallback`, `ExecutionPolicyBlocked` | **Yes** — first gate; if blocked, **no** external call and **no** transformation for cloud. |
| **Retention / traces** | `redact_trace_snapshot`, `suppress_trace_output`, export gates | **Yes** — applies **after** execution; must **never** log the rebinding map keyed to raw secrets at `restricted` without policy. |
| **Externalization** (this doc) | Shape what crosses the wire **when** cloud is **allowed** | **New** — orthogonal axis: “**how** we send,” not “**whether** we send.” |

**Rule:** Externalization runs only if privacy + execution policy **already permit** an external (cloud) call for this step. If the effective primary is **local**, default strategy is **`none`** unless a future policy explicitly requests local-side scrubbing for logging (out of scope for v1).

---

## 2. End-to-end pipeline (conceptual)

```
raw request (+ routing_context, privacy_mode, sensitivity)
    → [existing] substrate merge → ExecutionPolicyResolution
    → [existing] apply_privacy_to_execution_resolution → allowed | ExecutionPolicyBlocked
    → if blocked: return (no provider call)

    → [new] resolve externalization_strategy (privacy_mode, sensitivity, tier(primary), policy hints)
    → if strategy == none OR primary is local: pass-through payload

    → [new] build internal execution envelope (structured fields: prompts, context blocks, subject_ref, etc.)
    → [new] transform → { external_envelope, placeholder_map, transform_metadata }
    → [existing] provider selection + generate(external_envelope …)

    → [new] rebind(model_output, placeholder_map) → internal-shaped output
    → [existing] normalize tool/API result
    → [existing] trace privacy (redact / suppress) on emitted traces
```

**Ordering invariant:** Gating **before** transform; transform **before** `generate`; rebind **after** `generate` **before** returning structured results to callers.

---

## 3. Recommended placement in code (today’s seam)

**Hook point:** Immediately **after** `_begin_run_routing` (or equivalent) has an **allowed** resolution with a **cloud** primary, and **before** any code path invokes `provider.generate` (or HTTP to cloud).

Concrete targets as the platform converges on one seam:

1. **`api/main.py`** — inside `/run` / `/run/stream`, after `exec_meta` shows not blocked and `provider_used` is cloud **or** inside a shared **`execute_with_policy(...)`** helper introduced later.
2. **`local_ai/execution_policy/`** — new module e.g. `externalization.py`: pure functions + types (**no** network I/O).
3. **`local_ai/providers/`** — providers remain **dumb transport**; they receive **already-transformed** strings/structured messages. Avoid embedding washing logic inside `OpenAIProvider`.
4. **Request-scoped context** — extend `run_context` (or a sibling `ContextVar`) to hold **`ExternalizationSession`** (map + strategy + nonce scope) for the lifetime of the request, cleared in the same teardown as routing.

**Where this should *not* apply (initially):**

- **Binary or non-text payloads** (images, PDFs) unless you add a separate media pipeline.
- **Arbitrary code** the model must execute verbatim (e.g. “fix this script”) — abstraction can break validity; gate to **local** or **none** only.
- **Streaming** where consumers read partial tokens **unless** the implementation buffers to completion before rebind (otherwise users see placeholders mid-stream).
- **Multi-agent / council** with **divergent** per-seat prompts unless each seat gets a **consistent** map or shared `ExternalizationSession` (higher complexity — defer or use **shared** washed packet + seat-specific non-sensitive instructions only).
- **Third-party tools** that forward user text unchanged (web search queries, etc.) — either block, transform query builder, or treat as **high risk** and keep **`local_only`** / **`none`** for that sub-step.

---

## 4. Concept: `externalization_strategy` (or `transformation_mode`)

Single enum (names can ship as `externalization_strategy` in JSON; `transformation_mode` is an acceptable alias in TS/Python if aligned).

| Value | Intent |
|--------|--------|
| **`none`** | No washing; payload is sent as today (still subject to gating + trace rules). |
| **`light_redaction`** | Fast, deterministic rules: strip/obfuscate obvious patterns (emails, phone-like, national IDs if configured), cap lengths on narrative fields. **Weak reversibility** — prefer **lossy** fields not used for rebind, or pair with placeholders for IDs only. |
| **`hypothetical_abstraction`** | Rewrite narrative to **hypothetical framing** (“Company A,” “a mid-size health system”) with **structured slots** for anything that must round-trip. Higher LLM risk; usually **local** model generates the abstraction **or** template-based substitution. |
| **`structured_placeholder_mapping`** | Preferred default for **reversible** flows: operate on **typed spans** (entity id, person ref, project id) with stable **opaque tokens** (`[[ZENAF_REF:pk_01]]`), never reusing tokens across requests without a new map. |

**Privacy mode → suggested *default* strategy** (org/user policy may override; **`local_only`** forces **no cloud**, so strategy for cloud is moot):

| `privacy_mode` | Default externalization if cloud allowed | Notes |
|----------------|------------------------------------------|--------|
| `normal` | `none` | User/org can opt into stricter washing without changing mode. |
| `protected` | `light_redaction` or `structured_placeholder_mapping` for structured surfaces | Prefer **placeholders** when rebinding is needed. |
| `restricted` | `structured_placeholder_mapping` (strong preference) | Minimize free-text abstraction drift; narrow allowlists already. |
| `local_only` | N/A | No external call; keep **`none`** for any local post-processing unless separate logging policy. |

**`sensitivity` from `routing_context`** can **upgrade** strategy (e.g. `high` → force mapping even in `normal`) without relaxing gating.

---

## 5. Architecture: transformation + rebinding

### 5.1 Core types (conceptual)

- **`PlaceholderMap`** — immutable for the request: `token → { kind, internal_id, optional_checksum }`. Tokens are **unguessable** and **opaque** to the model (no sequential `1,2,3` for entities).
- **`TransformResult`** — `external_text` (or structured message list), `map`, `warnings` (e.g. “unmapped UUID detected”).
- **`RebindResult`** — `internal_text`, `unresolved_tokens`, `integrity_ok`.

### 5.2 Structured placeholder mapping (preferred)

1. **Extract** internal references from **structured** inputs first (`subject_ref`, initiative id, known JSON fields), not only regex on prose.
2. **Replace** with placeholders in **all** channels that will go external (system prompt, user message, tool descriptions if any).
3. **Attach** short **machine instructions** to the model: “Do not alter tokens matching `[[ZENAF_REF:…]]`; echo them when referring to those entities.” (Reduces but does not eliminate model misbehavior.)
4. **Parse** output for known token grammar; **replace** with internal ids. **Validate** optional checksums / allowlists of ids that were in scope for this request.
5. **Reject or sanitize** if unknown tokens appear (see risks).

### 5.3 Hypothetical abstraction (secondary)

- Use when **narrative** must change semantically, not just token swap.
- **Rebind** is **harder**; prefer **structured sidecar**: model returns **JSON** with abstract labels + you map via **pre-declared** `abstract_label → internal_id` table produced in step 1.
- Treat as **higher risk** for correctness; keep behind **`protected`/`restricted`** and tests.

### 5.4 Light redaction

- Best for **PII patterns** where **no** round-trip is needed (e.g. scrub before summarization-only tasks).
- If the task **requires** restoring exact IDs in the answer, use **placeholder mapping** instead.

---

## 6. Risks & failure modes

| Risk | Mitigation |
|------|------------|
| **Model mutates placeholders** | Constrain format; validate on rebind; retry with stricter system prompt; fall back to **blocked** or **local** if integrity fails. |
| **Partial rebind / silent wrong entity** | Checksums, allowlist “only ids present in input,” flag `integrity_ok: false` to UI; never silent fix across categories (person vs project). |
| **Leakage via logs/traces** | Never attach full `PlaceholderMap` to client traces in `restricted`; server logs opt-in only; map cleared at teardown. |
| **Over-abstraction → useless cloud answer** | Tier strategies by task type; allow policy to set **`none`** for low-sensitivity cloud steps. |
| **Latency / cost** | Local pre-pass (regex + structured walk) is cheap; second local LLM for abstraction is expensive — budget explicitly. |
| **Bypass via tool calls** | If tools send raw strings, washing is defeated; **tool layer** must consume **already-washed** args or be disabled for sensitive flows. |
| **Unicode / homoglyph attacks** | Normalize before replace; reject ambiguous matches. |
| **Stale map across retries** | New map per attempt; no cross-request token reuse. |

---

## 7. Minimal first implementation target

**Shipped (v1):** See **`EXTERNALIZATION_V1_NEXT_STEP.md`**.

- **`maybe_externalize_for_cloud`** + **`structured_placeholder_mapping`** for **`POST /run`** `mode=next_step`, intent **`workspace_next_step`**, **OpenAI** primary, and **`subject_id`** (or `subject_ref.id`) present in prompt text.  
- **Rebind + strict integrity** (exact token match, checksum, no silent misbind on corruption / missing echo).  
- **Restricted / local_only:** API omits token-string lists; counts only.

**Explicitly defer:** `hypothetical_abstraction`, council multi-seat, streaming rebind, file-steward bulk documents, intake PHI pipeline (may need **stronger** rules later).

---

## 8. Summary

- **Gating first**, **wash when cloud is allowed**, **rebind before normalize**, **trace rules last**.  
- Prefer **`structured_placeholder_mapping`** for reversibility; use **`light_redaction`** when round-trip is unnecessary.  
- **`local_only`** remains **no externalization path** because there is **no** external call — not because washing is disabled on principle.  
- **Minimal v1:** plumb the layer with **`none`**, then one **mapping** implementation on one **structured** path with tests.
