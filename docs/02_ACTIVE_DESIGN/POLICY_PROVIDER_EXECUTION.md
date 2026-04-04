# Policy-driven provider execution (narrow path)

**Status:** Implemented for **`openai`** primary on **`POST /run`** / **`POST /run/stream`** when `routing_context` is present.

**Future:** Pre-cloud **payload transformation** and **output rebinding** (privacy-preserving externalization) is specified in **`PRIVACY_EXTERNALIZATION_AND_REBINDING.md`** — sits **after** gating, **before** `generate`.

## Execution seam

1. **`api/main.py`** — `_begin_run_routing(request)`  
   - Calls `resolve_execution_policy_for_action` (+ privacy).  
   - **`ollama`:** `push_ollama_model_override(model)` → `RoutingTeardown(ollama_token=...)`.  
   - **`openai`:** if `OPENAI_API_KEY` set, `OpenAIProvider(model=...)` + `push_policy_provider_override(provider)` → `RoutingTeardown(policy_provider_token=...)`; else `execution_blocked` (same response shape as privacy block, `privacy_block_reason` null).  
   - **Other primaries:** **`execution_blocked`** — no silent Ollama (see `seam_routing.py`).

2. **`config/ai_execution_policy.json`** — `overrides_by_action_intent` picks the primary per intent. **Shipped defaults:** **`workspace_council`** uses **Ollama** (local council without `OPENAI_API_KEY`); **`workspace_next_step`**, **`idea_evaluate`**, **`initiative_evaluate`**, meeting extract intents, etc. use **OpenAI** (`gpt-4.1-mini`) when `routing_context` is present. Edit the JSON to move Council to OpenAI if you set **`OPENAI_API_KEY`** on the API server. **`workspace_analyze`** and other folder modes without overrides stay on **Ollama** unless policy is edited. **`privacy_mode: local_only`** still forces local via `privacy_apply`.

3. **`local_ai/providers/__init__.py`** — `get_default_provider()` / `get_council_provider()`  
   - If `get_policy_provider_override()` is set → return that instance.  
   - Else existing Ollama logic (including Ollama model override for council).

4. **`local_ai/execution_policy/run_context.py`**  
   - ContextVar override + `RoutingTeardown` + `end_execution_routing(teardown)` (policy reset first, then Ollama token).

5. **`api/main.py`** — `_end_run_routing(teardown)` in `finally` / stream cleanup → `end_execution_routing`. Logs `provider_used` / `model_used` when `routing_context` is set.

Anything that calls **`get_default_provider()`** or **`get_council_provider()`** during the request sees the OpenAI instance when policy primary is `openai` and the key is configured (e.g. `suggest_next_step`, `run_council`, `DefaultProviderAdapter` / content pipeline on the same request).

## First non-Ollama provider

- **`local_ai/providers/openai.py`** — `OpenAIProvider.generate()` → OpenAI Chat Completions API.

## What stays Ollama-shaped

- **No fallback-chain execution** — only primary is honored for `openai`; fallbacks are not walked.  
- **Unsupported policy primaries** on the shared seam (not `ollama` / `openai`) → **`execution_blocked`** with a clear message — no silent Ollama with misleading `provider_used`.  
- **File Steward** (`tools/file_steward`) — may not use `get_default_provider()` for all paths; verify per tool.  
- **Vision Execution** without `routing_context` on evaluate routes still uses **legacy** user-profile shims (`get_provider_shim_for_legacy_generate`); with `routing_context`, uses `apply_seam_routing` + `get_default_provider()` (see **`PRIVACY_EXECUTION_COVERAGE.md`**).
- **Meeting extraction** — when `routing_context` is sent, `meeting_execution_seam` applies `apply_seam_routing` for the whole call (and for segment batch), so `get_default_provider()` matches policy.

## Tests

`tests/test_run_routing_context.py` — Ollama unchanged for intents without override, OpenAI path + meta, missing key blocked, privacy blocked, council + routing uses OpenAI when policy + key.

## Suggested next `routing_context` surfaces

1. **Transcript / other Content-adjacent tools** — if they gain LLM calls via `/run` or VE, use the same substrate fields.  
2. **Intake** — today **rule-based** only; if LLM classifiers are added, introduce `routing_context` on those routes.
