# AI execution policy & model routing (substrate-aligned)

**Status:** Active design — **first-pass architecture**; not fully implemented.  
**Goal:** One **shared execution policy layer** that resolves **which provider/model (and fallbacks)** to use from **substrate metadata** (`surface`, `action_kind`, `action_intent`) plus **user preferences** — **not** ad-hoc logic per feature.

**Non-goals (this doc / first implementation pass):**  
Redesigning the whole provider stack; blocking existing flows; adding new `AiActionKind` values; persisting policy in DB; PHI/HIPAA enforcement (see **`docs/POLICY_AWARE_LLM_ROUTING.md`** for that direction, to **compose on top** later).

**Privacy vs routing:** User/org **privacy mode** (`normal` | `protected` | `restricted` | `local_only`) is a **separate axis** from “which model is primary.” **`protected`** and **`restricted`** **allow cloud** when providers/models are approved; they tighten retention, traces, fallbacks, and exports — they **do not** imply local-only by default. See **`PRIVACY_MODE_AND_EXECUTION_POLICY.md`**.  
*Note:* The config **`priority_profiles.privacy`** (`require_local`, `allow_cloud: false`) is a **routing preference profile**, not the same as **`privacy_mode`**; avoid conflating the name “privacy” in JSON with user-facing “Protected” mode.

---

## 1. Conceptual pipeline

```
user preferences (global)
        +
action context (surface, action_kind, action_intent, optional: streaming, sensitivity hint)
        ↓
resolveExecutionPolicyForAction(...)   ← single resolver entrypoint
        ↓
ExecutionPolicyResolution {
  provider_id, model_id,
  fallback_chain: { provider_id, model_id }[],
  flags: { allow_cloud, streaming_ok, ... }
}
        ↓
provider execution (existing generate / HTTP adapters — unchanged contract at first)
```

- **User preferences** = defaults and global priority (quality / speed / cost / privacy).  
- **Override map** = keyed by `action_kind` and optionally `action_intent` (string match, not a new taxonomy).  
- **Resolver** = pure function (same inputs → same outputs) suitable for unit tests; **no** network I/O inside the resolver.  
- **Provider execution** = today’s code paths (`OllamaProvider`, future adapters); resolver only **selects** parameters; execution stays behind existing seams.

---

## 2. Proposed config shape

Single **versioned** JSON document (or YAML) loadable at startup and overridable by env for dev. Example **v1** sketch:

```json
{
  "schema_version": 1,
  "global_priority": "balanced",
  "defaults": {
    "local": { "provider": "ollama", "model": "qwen2:7b-instruct" },
    "cloud": { "provider": "openai", "model": "gpt-4.1-mini" },
    "allow_cloud_fallback": true,
    "max_fallback_steps": 3
  },
  "priority_profiles": {
    "quality":   { "prefer_cloud": true,  "temperature_bias": "lower" },
    "speed":     { "prefer_cloud": false, "max_tokens_bias": "shorter" },
    "cost":      { "prefer_cloud": false, "prefer_smaller_model": true },
    "privacy":   { "allow_cloud": false, "require_local": true }
  },
  "overrides_by_action_kind": {
    "field_text_rewrite": {
      "inherit_priority": "speed",
      "primary": { "provider": "ollama", "model": "qwen2:7b-instruct" },
      "fallback_chain": [
        { "provider": "ollama", "model": "llama3.2:3b" }
      ]
    },
    "structured_evaluation": {
      "inherit_priority": "quality",
      "primary": { "provider": "ollama", "model": "qwen2:7b-instruct" },
      "fallback_chain": [
        { "provider": "openai", "model": "gpt-4.1-mini" }
      ]
    },
    "suggestion_batch": {
      "inherit_priority": "balanced",
      "primary": { "provider": "ollama", "model": "qwen2:7b-instruct" },
      "fallback_chain": []
    }
  },
  "overrides_by_action_intent": {
    "workspace_council": {
      "primary": { "provider": "ollama", "model": "qwen3:8b" },
      "fallback_chain": [
        { "provider": "openai", "model": "gpt-4.1-mini" },
        { "provider": "anthropic", "model": "claude-sonnet-4-20250514" }
      ],
      "allow_cloud_fallback": true
    },
    "content_distill_source": {
      "inherit_priority": "cost",
      "primary": { "provider": "ollama", "model": "llama3.2:3b" }
    },
    "core_profile_reconcile": {
      "inherit_priority": "privacy",
      "allow_cloud_fallback": false,
      "primary": { "provider": "ollama", "model": "qwen2:7b-instruct" }
    }
  }
}
```

**Resolution order (later tie-break rules, implement explicitly in code):**

1. If `overrides_by_action_intent[action_intent]` exists → merge with defaults (intent wins on conflicts).  
2. Else if `overrides_by_action_kind[action_kind]` exists → merge.  
3. Else → `defaults` + `global_priority` / `priority_profiles[global_priority]`.  
4. Apply `allow_cloud_fallback` and `privacy` / `require_local` to **filter or truncate** `fallback_chain`.  
5. Optional future: `surface` dimension (e.g. `intake` stricter than `content`) as another merge layer **without** new substrate types.

**Types (conceptual):**

- `GlobalPriority = 'quality' | 'speed' | 'cost' | 'privacy' | 'balanced'`  
- `ProviderModelRef = { provider: string; model: string }`  
- `ExecutionPolicyResolution = { primary: ProviderModelRef; fallback_chain: ProviderModelRef[]; allow_cloud: boolean; flags: Record<string, boolean | string> }`  
- `ActionRoutingContext = { surface: ZenafSurface; action_kind: AiActionKind; action_intent: string | null; streaming?: boolean; sensitivity?: 'low' | 'medium' | 'high' }`

---

## 3. Recommended file placement

| Layer | Location | Role |
|--------|-----------|------|
| **Policy config (data)** | `config/ai_execution_policy.json` (repo root) or `frontend/public/` copy for client-only preview — **authoritative copy should live once**; prefer **backend** as source of truth when server executes LLM. | Versioned defaults + overrides. |
| **Resolver (TS)** | `frontend/src/ai-actions/executionPolicy/` — `types.ts`, `resolveExecutionPolicyForAction.ts`, `defaultPolicy.ts` (embedded fallback if file missing). | Client-side resolution for: future headers/body hints, devtools, aligning trace `model_used` with intent. |
| **Resolver (Python)** | `local_ai/execution_policy/` — `types.py`, `load.py`, `resolve.py`; JSON at `config/ai_execution_policy.json`. | **Must** be where `/run` and VE routes actually call `generate()` when Phase 2 wires execution. |
| **Wire point (backend)** | Thin: `local_ai/providers/router.py` or extend `get_default_provider()` → `get_provider_for_context(ctx: ActionRoutingContext)` delegating to resolver **only when** context is passed; default path = today’s behavior. | No per-feature `if council:`. |
| **Wire point (frontend)** | Optional Phase 1: attach resolution result to `AiActionTrace.model_used` / `prompt_version` metadata; optional `X-Zenaf-Routing-Hint` header on fetch — **server may ignore** until implemented. | Zero breaking change. |

Avoid scattering `OllamaProvider(model=...)` in new feature code; **one** resolver + existing provider factory.

---

## 4. Minimal implementation plan (phases)

### Phase 0 — **Implemented (as-built)**

- **`local_ai/execution_policy/`** — `types`, `load` (reads `config/ai_execution_policy.json` or embedded fallback), `resolve_execution_policy_for_action` (null context = legacy default/council model from `local_ai.config` + env).  
- **`frontend/src/ai-actions/executionPolicy/`** — TS mirror: `defaultPolicy.ts`, `resolveExecutionPolicyForAction.ts` (embedded policy; client hints `CLIENT_HINT_*` aligned with `local_ai/config.py`; no env).  
- **`tests/test_execution_policy.py`** — merge precedence, null context, intent vs kind, privacy filter when configured, shipped JSON parity.  
- **`local_ai.providers.describe_default_execution_policy` / `describe_council_execution_policy`** — introspection only (runtime selection uses `run_context` overrides; see **POLICY_PROVIDER_EXECUTION.md**).  
- **Narrow UI seam:** Workspace traces set `model_used` from TS resolver hint (display/analytics only; server unchanged).

### Phase 1 — Wire backend execution (**partial**)

- **`POST /run`** with `routing_context`: resolver runs; **ollama** → model override; **openai** → `push_policy_provider_override` when `OPENAI_API_KEY` set; **absent context** = unchanged legacy path. See **`POLICY_PROVIDER_EXECUTION.md`**.  
- Optional: sync client policy from API or single source of truth to avoid TS/Python config drift.

### Phase 2 — Single backend seam

- Introduce `get_provider_for_routing(resolution: ExecutionPolicyResolution)` that returns first **registered** provider that matches `provider` id (today: only `ollama` fully wired).  
- In **`zenaf_tools`** (or one shared helper used by `/run` and VE services), thread optional `ActionRoutingContext` from API body `routing_context` (optional field) **defaulting to null** → legacy path = `get_default_provider()` / `get_council_provider()` exactly as today.  
- Map high-level modes to substrate metadata in **one table** (e.g. `council` → `structured_evaluation` + `workspace_council`) — **one file**, not per-handler if statements.

### Phase 3 — Frontend opt-in

- When emitting traces / calling API, optionally send `routing_context: { surface, action_kind, action_intent }` (and later `streaming: true`).  
- Server uses resolver when field present; otherwise unchanged.  
- Settings UI: edit global priority + defaults + allow_cloud (persist localStorage first, then API).

### Phase 4 — Fallback chain execution

- Wrapper around `generate()` that tries primary then fallbacks on **transient** errors (timeout, 429), **never** on policy violation.  
- Respect `allow_cloud_fallback` and `privacy` / `require_local`.

---

## 5. Integration with current API / provider setup

**Today (truth):**

- **`local_ai/providers/get_default_provider()`** → `OllamaProvider()` with model from env/config.  
- **`get_council_provider()`** → env `ZENAF_COUNCIL_MODEL` or `config.OLLAMA_COUNCIL_MODEL` or default.  
- **`POST /run`** and VE routes invoke tools/services that call `.generate(prompt, **kwargs)` directly — **no** substrate metadata on the wire.

**Alignment:**

- Substrate metadata already exists on the **client** (`AiActionTrace.surface`, `action_kind`, `action_intent`). The **same triple** should be the **canonical input** to `resolveExecutionPolicyForAction` (plus user prefs and optional flags).  
- **Do not** duplicate routing rules in `VisionExecutionView`, `App.tsx`, or `ContentView`; eventually pass context from the **shared** caller that already knows `action_intent` (e.g. workspace trace emitters, VE trace creators).  
- **PHI / policy-aware routing** (`POLICY_AWARE_LLM_ROUTING.md`) should **gate** or **filter** the resolver output (e.g. drop cloud entries in PHI-safe mode), not replace the substrate-based resolver.

**Trace field `model_used`:**  
Today often `null` on the client. After Phase 2–3, fill from **actual** provider/model used on the server response (optional `model_used` in JSON response) so analytics match policy.

---

## 6. Guardrails recap

| Do | Don’t |
|----|--------|
| One resolver; config-driven overrides by `action_kind` / `action_intent` | Per-feature `if (mode === 'council') model = …` |
| Optional API field + backward-compatible defaults | Require every client to send routing context on day one |
| Compose with PHI/policy layer later | Conflate cost/speed prefs with HIPAA policy in one blob |
| Keep `AiActionKind` as the coarse bucket | Add new kinds just for routing |

---

## 7. Related docs

- **`AI_ACTION_TRACE_AND_ROUTING_DESIGN.md`** — trace model and `action_intent` semantics.  
- **`POLICY_AWARE_LLM_ROUTING.md`** — sensitivity / PHI / external provider policy (orthogonal axis).  
- **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`** — as-built provider usage.
