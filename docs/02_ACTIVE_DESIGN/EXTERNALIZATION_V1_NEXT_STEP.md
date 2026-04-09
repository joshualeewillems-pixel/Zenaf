# Externalization v1 — `workspace_next_step` + OpenAI + `subject_id`

**Status:** Implemented (minimal scope). No streaming, one path, no fuzzy match, no second LLM.

## Hook location

1. **`maybe_externalize_for_cloud`** — `local_ai/execution_policy/externalization.py`  
   Called from **`api/main.py`** → **`_run_next_step`** after the **delegation-synthesized** or **legacy line-based** internal prompt is ready and **`routing_context`** is present, **before** `generate_next_step_raw` (which calls `get_default_provider().generate`).

2. **OpenAI + `workspace_next_step` + routing** — uses **structured cloud delegation v1** (`local_ai/delegation/workspace_next_step.py`): JSON-only contract, then **rebind** on raw text, then **parse/validate** JSON. Placeholders must appear inside JSON string values (e.g. `recommendation`). See **`COMPILED_DELEGATION_V1.md`**.

3. **Non-cloud / no routing / wrong intent** — function returns **identity** prompt and **empty** `PlaceholderMap` (`strategy: none`). Legacy `next_step` without `routing_context` still uses the **line-oriented** prompt + parser inside `_run_next_step`.

## Activation conditions

| Condition | Required |
|-----------|----------|
| `POST /run` `mode` | `next_step` |
| `routing_context.action_intent` | `workspace_next_step` |
| Resolved execution (`exec_meta`) | `provider_used == openai` |
| Payload | `context.subject_id` **or** `params.subject_ref.id` (string), and that id **substring** must appear in the built prompt (usually in `context_block`) |

## Token shape

`[[ZENAF_REF:subject_id:<base64url(utf-8 id)>:<8-hex sha256 fragment>]]`

Checksum: first 8 hex chars of `sha256("zenaf.v1|{kind}|{internal_id}")`.

## Example before / after (prompt excerpt)

**Internal (never sent to cloud if mapping applies):**

```text
Context:
Active initiative initiative-uuid-7f2a needs a decision.
...
```

**External (sent to OpenAI):**

```text
Context:
Active initiative [[ZENAF_REF:subject_id:aW5pdGlhdGl2ZS11dWlkLTdmMmE:…]] needs a decision.
...
```

**Model output (must echo token for v1 integrity)** — structured path: single JSON object, e.g.:

```json
{"recommendation":"Follow up on [[ZENAF_REF:subject_id:…]]","rationale":"ok","alternatives":[],"caution":null}
```

**After rebind (client-visible `result` dict):** same fields as before (`recommendation`, `rationale`, `alternatives`, `caution`) with internal ids restored in strings.

## Corrupted / invalid output handling

| Case | Behavior |
|------|-----------|
| **Mutated checksum** or **unknown token** | `invalid_tokens_in_output` populated; `integrity_ok` false; API returns **`ok: false`** with error *Externalized response failed integrity validation…* — **no** silent substitution. |
| **Sent token missing from model output** | `unresolved_tokens` non-empty; treated as **failure** (same error response) so we never accept a response that dropped the placeholder. |
| **`restricted` / `local_only` privacy_mode** | Response includes **`externalization_unresolved_count` / `externalization_invalid_count`** and **`externalization_integrity_ok`** only — **no** full token strings on the wire. |

## API fields (`RunResponse`)

- `externalization_integrity_ok`
- `externalization_unresolved_tokens` / `externalization_invalid_tokens` (omitted in restricted-like redaction; counts only)

**Never** returned: full `PlaceholderMap` or raw map JSON.

## Tests

`tests/test_externalization_next_step.py` — roundtrip, mutated token, foreign token, missing echo, redaction, HTTP e2e with mocked `OpenAIProvider.generate`.
