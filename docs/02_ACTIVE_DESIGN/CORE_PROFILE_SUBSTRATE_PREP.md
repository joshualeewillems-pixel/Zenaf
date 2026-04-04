# Core profile — trace / substrate prep (next high-value surface)

**Status:** **Implemented (substrate pass):** `routing_context` + `privacy_mode` on reconcile/conversation, bounded traces (`coreProfileTrace.ts`), outcome hooks (apply / dismiss / close / follow-up message → edited). Heuristic conversation replies (no LLM) bypass execution policy by design.  
**Compared to:** TranscriptSorter (Content) still not wired to this pattern; Meeting extraction already traced separately.

---

## Recommendation: **Core profile first**

| Criterion | Core profile | TranscriptSorter | Meeting extraction |
|-----------|--------------|------------------|---------------------|
| Centralized UI | **One panel** `CoreProfileDetailPanel` (`frontend/src/vision-execution/coreProfilePanels.tsx`) | **One component** `TranscriptSorter.tsx` | Done |
| API clarity | **Two** POSTs: `/core-profiles/{id}/conversation`, `/core-profiles/{id}/reconcile` | **One** POST: `/transcripts/sort` + ad-hoc VE writes on promote | Done |
| Subject binding | **Stable** `profileId` | Weak until `transcript_id` in response; often `manual` | `meeting_capture` / id |
| Outcome hooks | **Strong** (reconcile review: Apply / Cancel/Close) | Weaker (many candidates, per-row promote/dismiss) | Done |
| Policy note | `ai_execution_policy.json` already references `core_profile_reconcile` under intent overrides | Listed as `content_transcript_sort` in policy prep | N/A |

TranscriptSorter is **smaller** (one sort call) but **outcome parity** is harder: one trace per sort run vs many independent promote/dismiss actions unless you accept **coarse** outcomes (e.g. first promote → `applied`, abandon sort → `dismissed`) or defer per-candidate outcomes.

**Solidifying Meeting extraction** (chunk retry / staging `edited`) is **explicitly lower priority** for this step.

---

## Exact emit points (proposed)

### 1. Reconcile (higher value first)

- **When:** Immediately after successful `apiPost` to `/core-profiles/${profileId}/reconcile` when `res.proposed` is set (same block as `setProposed(res.proposed)` today in `handleReconcile`).
- **Do not emit** on `res.error` or empty proposal.

### 2. Training conversation

- **When:** After a **successful** assistant turn (HTTP OK and `res.reply` is a non-empty string — not the generic fallback error string).
- **Re-run / supersede:** If a trace ref is already pending for conversation, next successful send → `edited` on prior (mirror initiative evaluate), then push new trace.

---

## Surface / kind / intent / subject (proposed)

| Field | Reconcile | Conversation |
|-------|-----------|----------------|
| **`surface`** | `vision_execution` *(recommended: no new `AtriaSurface` value; routes live under VE API)* — optional later: `core_profile` if you add one enum for analytics clarity | Same |
| **`action_kind`** | `structured_evaluation` — structured multi-field JSON proposal fits the design doc bucket | `suggestion_batch` — single assistant “deliverable” the user may keep or ignore (closest fit without a chat-specific kind) |
| **`action_intent`** | `core_profile_reconcile` | `core_profile_conversation` |
| **`subject_type`** | `core_profile` | `core_profile` |
| **`subject_id`** | `profileId` | `profileId` |
| **`field_key`** | `null` (whole-profile operation) | `null` |
| **`input_snapshot`** (bounded) | `profile_id`, `conversation_turns_n`, `notes_len`, `structured_keys_present_n` — no raw notes/chat body | `profile_id`, `user_turn_index` or `conversation_turns_n`, `notes_len` |
| **`output`** (bounded) | JSON summary: keys changed count, non-empty field count, max slice per field | `reply_len`, optional first-line preview cap |

**Execution policy:** Reuse / align `core_profile_reconcile` in `config/ai_execution_policy.json` when wiring resolver hints (client mirror already names this intent).

---

## Outcome hooks (natural, low UI churn)

### Reconcile trace

| User action | `user_outcome` | Hook |
|-------------|----------------|------|
| **Apply proposed values** (`handleApplyProposed`) | `applied` | After `setForm` merge + `setProposed(null)` |
| **Cancel** or **Close** on proposal panel (`setProposed(null)` without apply) | `dismissed` | On those button handlers |
| User edits proposed textareas before apply | `edited` | Optional v2: first change after trace, or defer |

### Conversation trace

| User action | `user_outcome` | Hook |
|-------------|----------------|------|
| User sends another message while prior trace pending | `edited` | Start of `handleSendMessage` (before new POST), if ref set |
| Close panel / navigate away with pending last assistant trace | `dismissed` | `onClose` wrapper (like Idea/Initiative panels) |
| **Copy** assistant text | `copied` | Only if you add explicit copy control; **none today** |

**Save profile** persists form; it does not have to close the reconcile outcome if proposal already cleared — optional: if you ever emit reconcile and user saves without applying, treat as `dismissed` only if proposal still open.

---

## Implementation pattern (match Workspace / Content / Meeting)

- New **`coreProfileTrace.ts`** (or under `ai-actions/`) with `emitCoreProfileReconcileTrace`, `emitCoreProfileConversationTrace`, `recordCoreProfileTraceOutcome`.
- `useRef<AiActionTrace | null>` for **reconcile** and **conversation** separately (or one ref + disambiguation flag — two refs simpler).
- **No** transport redesign: keep `apiPost` in `coreProfilePanels.tsx`; call emitters only on success.

---

## TranscriptSorter (alternative) — summary

- **Emit point:** End of `runTranscriptSorter` after `setTranscriptResult(data)` on success.
- **Surface:** `content` (hosted in `ContentView`).
- **Kind / intent:** `suggestion_batch` + `content_transcript_sort` (aligns with coverage matrix).
- **Subject:** `content_transcript` / `subject_id` = `data.transcript_id ?? 'inline'` (same idea as meeting unpersisted).
- **Outcomes:** Coarse only unless overbuilding — e.g. `applied` on first successful task/decision promote from that result; `dismissed` on new sort or clear; per-row dismiss **not** recommended in v1.

---

## Legacy surfaces after Core profile is wired

Still **without** trace substrate (representative): TranscriptSorter (until wired), intake AI, settings LLM test, Perspectives agent **LLM** paths (if any), Team assists, VE **focus stub** buttons, **Clarify with AI** stub, Content **distill-source** (if not traced), optional **meeting** chunk-retry / staging-toggle `edited`, Workspace **outcome** UI on existing traces, etc.

---

## Related

- **`CORE_PROFILE_ARCHITECTURE.md`** — conversation / reconcile / apply flow.  
- **`AI_ACTION_TRACE_AND_ROUTING_DESIGN.md`** — kinds and surfaces.  
- **`config/ai_execution_policy.json`** — `core_profile_reconcile` intent override.
