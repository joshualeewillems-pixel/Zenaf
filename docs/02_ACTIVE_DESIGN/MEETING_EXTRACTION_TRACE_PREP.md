# Meeting extraction — trace / outcome prep (Vision Execution)

**Status:** **Client emit wired** — `frontend/src/ai-actions/meetingExtractionTrace.ts` + `VisionExecutionView.tsx` (`handleExtractMeeting` success branch, one trace per completed run with reviewable staging; outcomes on commit / close / link-out). Aligns with **`AI_ACTION_TRACE_AND_ROUTING_DESIGN.md`** and the emit-only pattern used for Workspace and Content.

---

## Flow (as-built)

Implemented in **`frontend/src/vision-execution/VisionExecutionView.tsx`** (Meeting Capture):

1. Paste / upload → `meetingNotes`
2. **Extract** → `handleExtractMeeting`
   - **Short / single pass:** `POST /extract-meeting` (notes under ~12k chars, or non-chunk mode)
   - **Chunk mode:** sequential `POST /extract-meeting` per chunk; staging updated progressively
   - **Hierarchical long meeting:** `POST /extract-meeting-segments` then `POST /extract-meeting-synthesis`
3. Parse / merge → `stagingArea` + `showReviewExtraction`
4. **Review UI** → toggle approvals, assign parents, etc.
5. **Commit** → `handleCommitReview` → `commitStagedItems(...)`; optional signal push; clear staging on success

Retries: `handleRetryChunk`, `handleRetryFailedChunks` — same extract endpoint, restage from succeeded chunks.

---

## Trace **emission** point (**as implemented**)

Emit **one trace per completed “extraction run”** that produced **reviewable staging** — **not** per progressive chunk UI update.

| Mode | Emit when |
|------|-----------|
| Single `/extract-meeting` | End of `handleExtractMeeting` success `else` branch: after merged `buildStagingArea(extraction)`, same tick as `setShowReviewExtraction(true)`. |
| Chunk mode | Same **end** of `handleExtractMeeting` (after all chunk HTTP calls in the loop); `input_snapshot` includes `chunk_total` / `chunk_succeeded`. No emit inside the per-chunk loop. |
| Segments + synthesis | Same end-of-handler success path. |

**No** trace when extraction fails and staging is cleared, or when the catch path runs.

Re-extract while a pending trace exists: prior trace gets `edited`, then a new trace is emitted for the new run.

---

## `action_kind` (no new kind)

Meeting output is a **batch** of structured suggestions (ideas, initiatives, tasks, signals, …) the user curates before commit. That matches:

- **`suggestion_batch`** — see design doc: “One-to-many suggestions … user may acknowledge, dismiss, or copy”.

`structured_evaluation` is reserved for scored / assessment-style packages (initiative/idea evaluate). Extraction is not that contract.

---

## Stable `action_intent` names (`snake_case`, strings only)

Map one intent per **top-level extract pipeline** (matches API split today):

| Intent | When |
|--------|------|
| `meeting_extract_single` | Single `POST /extract-meeting` (short notes or non-chunk path). |
| `meeting_extract_chunks` | Assisted chunk mode: multiple `/extract-meeting` calls merged into one staging. |
| `meeting_extract_synthesis` | `extract-meeting-segments` + `extract-meeting-synthesis` hierarchical path. |

Optional future refinement (still strings, not enums): `meeting_extract_chunk_retry` if you want analytics on retries only — not required for first wire.

**`surface`:** `meeting_extraction` (dedicated surface in `AtriaSurface`).  
**`subject_type`:** e.g. `meeting_capture` or `workspace_meeting` (pick one product string; no `subject_id` until a persisted meeting entity exists — `null` or empty is OK if trace schema allows).

---

## Natural **outcome** hooks (no new panels)

Reuse **`createAiActionTrace` → ref → `withTraceOutcome` → `pushAiActionTrace`** like VE evaluate / Content.

| User action | Outcome | Hook |
|-------------|---------|------|
| Commits approved items successfully (`handleCommitReview`, errors empty or partial success with `anyCreated` and user clears per current logic) | `applied` | End of success path after `commitStagedItems` when staging is cleared / work accepted (mirror “commit succeeded” semantics). |
| Clears review / abandons staging without commit (if there is a explicit dismiss / clear control) | `dismissed` | On the handler that clears `stagingArea` / `showReviewExtraction` without commit. |
| User toggles approvals / edits staging before commit | `edited` | Optional: debounced or on first toggle after trace creation — only if low noise; can defer to v2. |

Chunk **progressive** UI updates without closing review should **not** each flip outcome; outcomes attach to the **single** trace for that run.

---

## Implementation sketch (later)

1. `lastMeetingExtractTraceRef` next to meeting state.
2. After successful staging build (per table above): use **`emitMeetingExtractionTrace`** (`surface: 'meeting_extraction'`, `action_kind: 'suggestion_batch'`, bounded `input_snapshot`, staging summary `output`), store ref.
3. `handleCommitReview` success (aligned with product definition of “applied”): `applied` + clear ref.
4. Explicit cancel/dismiss: `dismissed` + clear ref.
5. New extract while ref set: `edited` or replace trace policy — match initiative evaluate “re-run” pattern.

---

## Surfaces that stay **legacy** until wired

- Meeting extraction (this doc).
- Transcript sorter, intake AI, settings LLM test, Perspectives agents, Team assists, any VE AI path without ref + outcome, and APIs that never return or correlate `trace_id`.
