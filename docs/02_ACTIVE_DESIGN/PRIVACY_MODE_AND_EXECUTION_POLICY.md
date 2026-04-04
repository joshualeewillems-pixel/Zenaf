# Privacy mode & execution policy (design)

**Status:** Active design — **policy model** for product and resolver extensions.  
**Goal:** Privacy / sensitivity modes control **what is allowed, retained, and exposed** — **not** an automatic default to local execution. Strong cloud models remain usable while governance tightens.

**Non-goals (initial rollout):** Forcing weak local models for all workflows; new `AiActionKind`; PHI/HIPAA certification (compose with **`docs/POLICY_AWARE_LLM_ROUTING.md`** later).

---

## 1. Problem statement

A first-pass reading of “privacy” often implies **local-only** routing. That is **wrong** for the current product phase: local models are still too slow or unreliable for many real workflows. We want:

- **Privacy controls now** (allowlists, retention, trace hygiene, export gates, confirmations).  
- **Optional cloud** where policy permits — especially **approved** providers/models.  
- **Signal for improving local competence** over time (traces, evals, structured outcomes) without **premature** local-only mandates.

**Rule:** Only **`local_only`** mode sets `require_local = true` and blocks cloud. **`normal`**, **`protected`**, and **`restricted`** may all use cloud subject to allowlists and fallback rules below.

---

## 2. Modes (user-facing semantics)

| Mode | Short intent | Cloud | Local | Default routing bias |
|------|----------------|-------|-------|----------------------|
| **`normal`** | Standard product behavior | Allowed per existing execution policy | Allowed | No privacy-specific constraint |
| **`protected`** | Safer handling; still capable models | **Allowed** — **only** approved providers/models | Allowed | Prefer policy defaults + allowlist |
| **`restricted`** | Strongest governance short of offline | **Allowed** — **only** explicitly approved providers/models; narrow list | Allowed | Same; **no broad fallback chain** |
| **`local_only`** | Future-ready / explicit offline preference | **Disallowed** (no fallback to cloud) | **Required** | Local primary only |

**Initial product default:** `normal`.  
**Do not** auto-upgrade users to `protected` without explicit choice (settings or org policy).

---

## 3. Proposed config extension

Extend the execution policy document (and resolver inputs) with a **`privacy`** block **and** flat fields resolvable into a single **`PrivacyPolicyResolution`** used alongside **`ExecutionPolicyResolution`**.

### 3.1 Top-level fields (conceptual)

```json
{
  "schema_version": 2,
  "privacy_mode": "normal",
  "require_local": false,
  "allow_cloud_fallback": true,
  "approved_providers": ["openai", "anthropic", "ollama"],
  "approved_models": {
    "openai": ["gpt-4.1-mini"],
    "anthropic": ["claude-sonnet-4-20250514"],
    "ollama": ["qwen2:7b-instruct", "llama3.2:3b"]
  },
  "redact_trace_snapshot": false,
  "suppress_trace_output": false,
  "disable_external_exports": false,
  "sensitive_confirmation_required": false
}
```

| Field | Purpose |
|--------|---------|
| **`privacy_mode`** | `normal` \| `protected` \| `restricted` \| `local_only` — selects **preset deltas** merged into explicit fields below. |
| **`require_local`** | If `true`, execution layer must not use non-local providers (see **local detection** below). **`local_only`** forces `true`. |
| **`allow_cloud_fallback`** | If `false`, resolver **drops** cloud entries from `fallback_chain` and does not promote cloud as fallback after local failure. |
| **`approved_providers`** | Allowlist of provider ids; non-listed providers **removed** from primary/fallback when mode is `protected` or `restricted`. |
| **`approved_models`** | Per-provider allowlist of model ids; non-listed models **rejected** or replaced per merge rules. |
| **`redact_trace_snapshot`** | Trace emitters replace/minimize `input_snapshot` (and similar bounded fields) before `pushAiActionTrace`. |
| **`suppress_trace_output`** | Omit or hash **`output`** (and optionally model-identifying fields) in client trace ring / future persistence. |
| **`disable_external_exports** | Block or gate clipboard/export/share actions that send content outside the app (feature-level hooks). |
| **`sensitive_confirmation_required`** | Extra confirmation step before external AI calls or high-risk actions (UX; server may mirror). |

### 3.2 Presets: mode → field defaults

Applied as **defaults**; org or user overrides **win** on specific keys (see merge §4).

| Field | `normal` | `protected` | `restricted` | `local_only` |
|--------|----------|-------------|--------------|--------------|
| `require_local` | `false` | `false` | `false` | **`true`** |
| `allow_cloud_fallback` | inherit policy | `true` but chain **filtered** to approved only | **`false`** (no broad chain) | **`false`** |
| `approved_providers` / `approved_models` | optional; if unset, no extra filter | **required** for cloud; stricter redaction | **required**; minimal list | N/A (cloud off) |
| `redact_trace_snapshot` | `false` | `true` (light: strip long text, keep route labels) | `true` (stronger: shorter caps, hash ids) | `true` (match restricted or stronger) |
| `suppress_trace_output` | `false` | `true` if org opts in; else partial | **`true`** | **`true`** |
| `disable_external_exports` | `false` | optional warn | stronger warn / block optional | block or warn |
| `sensitive_confirmation_required` | `false` | `true` for first cloud call per session or per action class | **`true`** for external actions | N/A (no cloud) |

**`local_only`:** After preset, **`require_local: true`** and **`allow_cloud_fallback: false`** are **mandatory**; allowlists irrelevant for cloud.

### 3.3 Local vs cloud (for `require_local`)

Resolver must use a **single registry** (config) mapping `provider` id → `{ tier: 'local' | 'cloud' | 'unknown' }`.  
- **`require_local`:** primary and every fallback must be `tier === 'local'`.  
- **`protected` / `restricted`:** **do not** set `require_local` unless user explicitly enables it.

---

## 4. Merge behavior with existing execution policy

Treat **privacy** as a **second axis** merged **after** the existing substrate merge (intent → kind → defaults → `priority_profiles[global_priority]`), as documented in **`AI_EXECUTION_POLICY_ROUTING.md`**.

### 4.1 Order of operations (recommended)

1. **Resolve routing (unchanged):**  
   `resolveExecutionPolicyForAction(routingContext, policyJson)` → `primary`, `fallback_chain`, `allow_cloud`, flags.

2. **Resolve privacy (new):**  
   `resolvePrivacyPolicy(orgPolicy, userPolicy, privacy_mode)` → explicit booleans + allowlists + trace/export flags.  
   (Merge org defaults with user overrides: **user stricter wins** for booleans like `suppress_trace_output`; **intersection** for allowlists where “stricter = smaller set”.)

3. **Apply privacy to routing (new):**  
   `applyPrivacyToExecutionResolution(execRes, privacyRes)`:
   - If **`privacyRes.require_local`:** equivalent to today’s `applyPrivacyFilter` — strip non-local from primary/fallback; if primary not local, **fail closed** or swap to configured local default (product decision).
   - Else if **`approved_*` present** (`protected` / `restricted`):  
     - Remove any `ProviderModelRef` not in `approved_providers` + `approved_models`.  
     - If primary removed, promote first **allowed** fallback or fall back to first **allowed** local/cloud per policy.
   - If **`allow_cloud_fallback === false`:** remove all cloud-tier entries from `fallback_chain`; do not add cloud in post-steps.
   - Attach to `flags`: `privacy_mode`, `privacy_applied: true`, `fallback_truncated_reason` if useful for support.

3b. **Optional externalization (“data washing”) before cloud `generate`:**  
   When step 3 **allows** a **cloud** primary, an additional layer may **transform** prompts/context and **rebind** outputs. This is **complementary** to gating (does not replace allow/block). See **`PRIVACY_EXTERNALIZATION_AND_REBINDING.md`**.

4. **Trace layer (client and future server):**  
   After model run, **`emitTraceWithPrivacy(traceDraft, privacyRes)`** applies redaction/suppression (§5).

**Important:** The legacy **`priority_profiles.privacy`** entry that sets `allow_cloud: false` / `require_local: true` is a **quality/speed profile name**, not the new **`privacy_mode`**. To avoid confusion:

- Prefer renaming that profile in config to **`local_first`** or **`offline_preferred`** when you next revise JSON, **or**  
- Document that **`global_priority: privacy`** is **deprecated** for “user privacy mode” and use **`privacy_mode`** only for governance.

---

## 5. Trace emitters: redact / suppress

Trace helpers (`createAiActionTrace`, `pushAiActionTrace`, Content/VE emitters) should accept **optional** `PrivacyPolicyResolution` (or read from a small app-level privacy context).

| Flag | Behavior |
|------|----------|
| **`redact_trace_snapshot`** | **Protected:** cap length aggressively (e.g. 120–200 chars), strip emails/phone-like patterns if cheap rules exist, keep **route labels** (`POST /ideas/{id}/evaluate`) where they add signal without content. **Restricted:** shorter cap or **hash** of snapshot + store length only. |
| **`suppress_trace_output`** | **Protected:** replace `output` with `{ suppressed: true, kind: 'structured_evaluation' }` or cardinality-only summary already partially done. **Restricted:** same or omit `output` entirely from ring buffer. **Analytics:** still record `action_kind`, `action_intent`, `user_outcome`, timestamps for local competence work. |

**Do not** store raw prompts in traces (existing design). Privacy modes **tighten** what already-bounded fields may contain.

**Server mirror:** When traces persist, apply the same rules server-side from the same `privacy_mode` snapshot attached to the request or session.

---

## 6. User-facing labels (avoid “local only” confusion)

| Internal mode | **Avoid** | **Prefer** |
|---------------|-----------|------------|
| `normal` | — | “Standard” / “Default” |
| `protected` | “Private”, “Offline”, “Local only” | **“Protected”**, “Approved providers only”, “Stricter data handling” |
| `restricted` | “Maximum privacy” (implies offline) | **“Restricted”**, “Tight export & trace rules”, “Confirm before external AI” |
| `local_only` | “Private” alone | **“Local only”**, “No cloud models”, “This device / your server only” |

**Tooltips (examples):**

- **Protected:** “Cloud models **you approve** can still run. Stricter trace and export handling.”  
- **Restricted:** “Only **explicitly listed** cloud providers. No broad automatic fallbacks. Stronger confirmations.”  
- **Local only:** “AI runs **only** on local or self-hosted models; cloud is **off**.”

---

## 7. Strategy alignment

- **Stronger models now:** `protected` / `restricted` **allow** cloud within allowlists — routing quality stays high.  
- **Better local over time:** traces still carry **structure** (`action_intent`, outcomes, suppressed flags) for training/eval pipelines without leaking raw content in restricted modes.  
- **Single resolver input:** Thread **`privacy_mode`** (or full `PrivacyPolicyResolution`) into the same call site that builds `ActionRoutingContext` so backend and frontend stay aligned.

---

## 8. Related docs

- **`AI_EXECUTION_POLICY_ROUTING.md`** — substrate merge, `resolveExecutionPolicyForAction`, fallback chain.  
- **`AI_ACTION_TRACE_AND_ROUTING_DESIGN.md`** — trace fields and outcomes.  
- **`POLICY_AWARE_LLM_ROUTING.md`** — PHI / contractual routing; **compose** as an additional gate on top of this privacy layer.

---

## 9. Implementation (as-built, no UI / no persistence)

**TypeScript:** `frontend/src/ai-actions/executionPolicy/privacyApply.ts` — `applyPrivacyToExecutionResolution`, `mergePrivacyPolicyInput`, `providerExecutionTier`.  
`resolveExecutionPolicyForAction` runs **base merge** then **privacy**; returns `{ execution_blocked, reason?, detail? } | { execution_blocked: false, resolution }`.  
`pushAiActionTrace(trace, tracePrivacy?)` applies `tracePrivacy.ts` redaction when flags are set.

**Python:** `local_ai/execution_policy/privacy_apply.py` — same semantics; `resolve_execution_policy_for_action` returns `ExecutionPolicyResolution | ExecutionPolicyBlocked`.  
**API:** `POST /run` with `routing_context` — if blocked, `ok: false`, `execution_blocked: true`, `privacy_block_reason: privacy_constraints`, `error` set; no Ollama override.  
`POST /run/stream` — **403** with JSON `detail` when blocked.

### Example resolution (before → after privacy)

**Before** (base policy only):  
`primary: { provider: ollama, model: qwen }`, `fallback_chain: [{ openai, gpt-4 }], allow_cloud: true`

**After** `require_local: true`:  
`primary: { ollama, qwen }`, `fallback_chain: []`, `allow_cloud: false`, `flags.privacy_require_local: true`  
(cloud fallback dropped; primary kept if local.)

**After** `approved_providers: ['openai']` only (primary was ollama):  
`ExecutionPolicyBlocked`, `reason: privacy_constraints` — **no** silent promotion to unapproved cloud.
