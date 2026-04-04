Status: Superseded  
Superseded by: docs/01_TRUTH/CODEBASE_TRUTH_RULES.md

# Judgment Semantics Audit: Mapping and Minimal Contract

**Purpose:** Map where judgment-like semantics exist across the product, define a minimal shared contract, and recommend the smallest changes so meeting extraction, signals, and Vision Execution align consistently—**without** a giant abstraction rewrite or collapsing intake `JudgmentRecord` and council `SeatJudgment` into one class.

---

## 1. List of All Judgment-Like Actions

| # | Action | Location (primary) | Kind |
|---|--------|--------------------|------|
| 1 | **Intake classification** | `local_ai/intake/pipeline.py`, `classifier.py`, `judgment/__init__.py` | Classification + proposed action |
| 2 | **Intake lane correction** | `local_ai/intake/queue_store.py`, `judgment/create_correction_record` | Correction / override |
| 3 | **Council run** | `local_ai/atria_tools.py`, `judgment_substrate.py` | Multi-seat recommendation |
| 4 | **Initiative evaluate** | `local_ai/vision_execution/initiative_evaluate.py`, VE API + frontend | Recommendation → apply/reject |
| 5 | **VE decision (record)** | `local_ai/vision_execution/storage.py`, `models.DecisionCreate` | Persisted decision (multiple types) |
| 6 | **Intake graduate to task** | `local_ai/intake/bridge.py` | Resolution (item → task) + decision record |
| 7 | **Meeting extraction** | `local_ai/vision_execution/meeting_extract.py`, `extraction_canonization.py` | Extraction + merge/canonization |
| 8 | **Meeting extraction “commit”** | Frontend → POST ideas/initiatives/signals | User approval of extraction (no decision record today) |
| 9 | **Signal create** | `local_ai/signals/service.py`, storage | Creation (often from extraction/triage) |
| 10 | **Signal update** (ack/link/resolve/dismiss) | `local_ai/signals/storage.py` (update_signal) | Resolution / dismissal / linking |
| 11 | **Transcript sorter promote** | `frontend/TranscriptSorter.tsx`, POST `/decisions` | User confirms candidate → decision record |
| 12 | **Suggest next step** | `local_ai/atria_tools.py` | Ephemeral recommendation (no persistence) |

---

## 2. Per-Action Mapping (subject, evidence, interpretation, action, persistence, supersession, authority, human review)

### 1. Intake classification

| Attribute | Value |
|-----------|--------|
| **Subject** | Intake item (entity_id = item id). |
| **Evidence** | Raw text (body), subject line; classifier sees subject + body; observation_ref: subject_preview, body_length, matched_signals (no raw content). |
| **Interpretation** | category, priority; interpretation_codes (e.g. interpretation_category_referral). |
| **Action/proposal** | Lane (e.g. needs_attention, likely_junk); policy_codes explain why. |
| **Persistence** | JudgmentRecord in-memory; mirror_judgment table (SQLite) via mirror; item.judgment_id, item.lane_override as mirror. |
| **Supersession/correction** | New record supersedes via superseded_by; create_correction_record creates new record, sets original.superseded_by; canonical = latest non-superseded. |
| **Authority** | System (classifier + lane derivation); human can override via lane_override + correction_note. |
| **Human review** | Queue UI shows interpretation/lane; user can set lane_override + correction_note → creates correction record; GET `/intake/queue/{id}/judgment` returns chain. |

---

### 2. Intake lane correction

| Attribute | Value |
|-----------|--------|
| **Subject** | Same intake item (entity_id). |
| **Evidence** | Same as original judgment (observation_ref copied); correction_note is human reason. |
| **Interpretation** | Copied from superseded record; interpretation_codes include "interpretation_correction". |
| **Action/proposal** | proposed_action_override (lane); policy_codes include "policy_correction_lane_override". |
| **Persistence** | New JudgmentRecord; mirror updated; item.judgment_id and lane_override updated. |
| **Supersession/correction** | This record supersedes the previous; previous.superseded_by = this.id. |
| **Authority** | Human (confidence=1.0). |
| **Human review** | This *is* the human review outcome; no further review step. |

---

### 3. Council run

| Attribute | Value |
|-----------|--------|
| **Subject** | SubjectRef (entity_type, entity_id, title, summary); question + context_ref. |
| **Evidence** | context_ref (e.g. initiative brief, project list); question. |
| **Interpretation** | Per seat: position, primary_reason, main_risk, required_guardrail, next_step (SeatJudgment). |
| **Action/proposal** | CouncilRunArtifact: recommended_action, distinct_positions, synthesis_text. |
| **Persistence** | None in judgment layer or VE by default; artifact returned to caller (API/frontend). Could be stored in VE as ai_proposal_snapshot for a decision. |
| **Supersession/correction** | None; each run is standalone. |
| **Authority** | System (LLM per seat); user consumes synthesis. |
| **Human review** | User reads synthesis and acts (or not); no formal “approve/reject” record. |

---

### 4. Initiative evaluate

| Attribute | Value |
|-----------|--------|
| **Subject** | Initiative (entity_type=initiative, entity_id=initiative_id). |
| **Evidence** | Initiative title, brief; optional core_profile_summary. |
| **Interpretation** | estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai. |
| **Action/proposal** | recommendation (Approve/Incubate/Park/Reject + reason). |
| **Persistence** | No persistence of proposal alone; on “Apply” frontend calls create_decision with decision_type=evaluation_applied, ai_proposal_snapshot=evaluateProposal, final_values_snapshot=applied. |
| **Supersession/correction** | Decisions table is append-only; no supersession field. Later apply creates another row. |
| **Authority** | AI proposes; human applies or rejects (initiative_approved / initiative_rejected). |
| **Human review** | User sees proposal; Apply = accept (and record decision); Reject/Edit = optional decision record with approved/rejected. |

---

### 5. VE decision (record)

| Attribute | Value |
|-----------|--------|
| **Subject** | entity_type + entity_id (initiative, task, transcript, etc.). |
| **Evidence** | Not stored explicitly; implied by entity and decision_type. |
| **Interpretation** | Optional in ai_proposal_snapshot (e.g. full evaluate result). |
| **Action/proposal** | decision_type (e.g. evaluation_applied, initiative_approved, intake_graduate_task, transcript_candidate_decision); final_values_snapshot = what was committed. |
| **Persistence** | decisions table (id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at). Append-only. |
| **Supersession/correction** | None; no superseded_by or correction chain. |
| **Authority** | user_id or system; varies by decision_type. |
| **Human review** | Semantics vary by type: evaluation_applied = human applied AI proposal; intake_graduate_task = human graduated item; transcript_candidate_decision = user promoted candidate. |

---

### 6. Intake graduate to task

| Attribute | Value |
|-----------|--------|
| **Subject** | Intake item (and resulting task). |
| **Evidence** | Intake item; optional source_judgment_id in task notes and final_values_snapshot. |
| **Interpretation** | Not stored in decision; judgment chain available via judgment_id. |
| **Action/proposal** | Create task; decision_type=intake_graduate_task, final_values_snapshot={ intake_item_id, task_id, judgment_id }. |
| **Persistence** | Task in VE; one Decision row (append-only). |
| **Supersession/correction** | No supersession in decisions; intake judgment chain unchanged. |
| **Authority** | Human (graduate action); optional link to judgment_id for provenance. |
| **Human review** | User chose to graduate; judgment_id ties back to intake judgment chain. |

---

### 7. Meeting extraction

| Attribute | Value |
|-----------|--------|
| **Subject** | “Meeting” (ephemeral meeting_id for activity log). |
| **Evidence** | Pasted notes (precleaned); optional context (existing initiatives/projects/tasks) for linking. |
| **Interpretation** | Ideas, initiatives, tasks, signals (and summary, insights, projects, assets, people); confidence/sourceExcerpt per item; post-merge canonization merges/dedupes. |
| **Action/proposal** | Proposed entities (not persisted by extract); user commits via POST ideas/initiatives/signals. |
| **Persistence** | No judgment/decision record; activity MEETING_PROCESSED; extraction result returned only in API response. |
| **Supersession/correction** | N/A; single-shot. Canonization is internal merge, not user correction. |
| **Authority** | System (LLM + canonization); user chooses what to commit. |
| **Human review** | User reviews extracted list and selectively creates entities; no explicit “approved extraction” record. |

---

### 8. Meeting extraction “commit”

| Attribute | Value |
|-----------|--------|
| **Subject** | The extraction run (no first-class id); created entities (initiatives, signals, etc.). |
| **Evidence** | What user selected from extraction UI. |
| **Interpretation** | Implicit (user’s selection). |
| **Action/proposal** | POST /ideas, /initiatives, /signals etc. |
| **Persistence** | Entities in VE/signals DB; activity for created entities; no decision row for “extraction approved”. |
| **Supersession/correction** | N/A. |
| **Authority** | Human. |
| **Human review** | The commit *is* the review; no separate decision record. |

---

### 9. Signal create

| Attribute | Value |
|-----------|--------|
| **Subject** | New signal (id after create). |
| **Evidence** | source, source_excerpt, source_ref; title, detail, kind. |
| **Interpretation** | kind (attention/risk/opportunity/blocker/info); optional confidence. |
| **Action/proposal** | Creation is the action; status=new. |
| **Persistence** | signals table (VE SQLite); activity SIGNAL_CREATED. |
| **Supersession/correction** | None; no judgment chain. Status changes via update_signal. |
| **Authority** | System (e.g. meeting-extraction) or user (manual). |
| **Human review** | New signals appear in Radar; user can acknowledge/link/resolve/dismiss. |

---

### 10. Signal update (acknowledge / link / resolve / dismiss)

| Attribute | Value |
|-----------|--------|
| **Subject** | Existing signal (signal_id). |
| **Evidence** | Current signal state; patch (status, linked_*_id). |
| **Interpretation** | Implicit: “user considers this acknowledged/linked/resolved/dismissed”. |
| **Action/proposal** | status → acknowledged | linked | resolved | dismissed; optional linked_initiative_id etc. |
| **Persistence** | signals table updated; activity SIGNAL_ACKNOWLEDGED / LINKED / RESOLVED / DISMISSED. |
| **Supersession/correction** | In-place update; no supersession chain. Previous state overwritten. |
| **Authority** | Human (or system if automated). |
| **Human review** | The update *is* the review outcome. |

---

### 11. Transcript sorter promote

| Attribute | Value |
|-----------|--------|
| **Subject** | Transcript (entity_id = transcript_id) and candidate (segment_id, summary, source_text). |
| **Evidence** | candidate_decisions from sort_transcript; user selects one. |
| **Interpretation** | In transcript result (candidate_decisions); not stored in decision. |
| **Action/proposal** | final_values_snapshot = { transcript_id, segment_id, source_text, summary }; decision_type=transcript_candidate_decision; ai_proposal_snapshot=null. |
| **Persistence** | One Decision row (append-only). |
| **Supersession/correction** | None. |
| **Authority** | Human. |
| **Human review** | User explicitly “promotes” a candidate → decision recorded. |

---

### 12. Suggest next step

| Attribute | Value |
|-----------|--------|
| **Subject** | Context (e.g. current state); optional question. |
| **Evidence** | context_str, question. |
| **Interpretation** | Inferred from model output. |
| **Action/proposal** | recommendation, rationale (returned in API response). |
| **Persistence** | None; ephemeral. |
| **Supersession/correction** | N/A. |
| **Authority** | System. |
| **Human review** | User reads and may act; no record. |

---

## 3. Minimal Shared Judgment Contract

A **minimal shared contract** that fits all of the above without one global class:

1. **Subject**  
   - Something identifiable: entity_type + entity_id (or equivalent: intake item id, meeting id, signal id, transcript id).  
   - Optional: title/summary for display.

2. **Evidence**  
   - Reference to what was considered (no raw content in contract): observation_ref / context_ref / source_ref / source_excerpt.  
   - Domains can use different shapes (e.g. subject_preview + body_length for intake; context_ref for council).

3. **Interpretation**  
   - Structured or free-form “what we inferred”: category, priority, positions, extracted ideas, etc.  
   - Optional codes (signal_codes, interpretation_codes, policy_codes) for trust/debugging.

4. **Action / proposal**  
   - What is proposed or what was done: lane, recommendation, status change, created entities, decision_type + final_values_snapshot.  
   - Can be “proposal only” (AI) or “outcome” (human applied).

5. **Persistence**  
   - Some judgments are persisted, some not.  
   - Contract: if persisted, there is a **stable id** and a way to refer to “this judgment/decision” (judgment_id, decision_id).  
   - No requirement that all domains use the same table or type.

6. **Supersession / correction**  
   - When a judgment can be overridden or corrected:  
     - **Explicit supersession**: new record points at previous (e.g. superseded_by); canonical = latest non-superseded.  
     - **Append-only**: no supersession; each record is independent (e.g. VE decisions).  
     - **In-place**: entity updated (e.g. signal status); no chain.  
   - Contract: each domain declares which model it uses; consumers can treat “latest” by chain or by entity state.

7. **Authority**  
   - Who decided: system (AI), human, or mixed.  
   - Optional: confidence or “human_override” flag for display/analytics.

8. **Human review semantics**  
   - One of:  
     - **Pre-record**: human reviews then corrects/overrides (intake correction).  
     - **Proposal → accept/reject**: AI proposes, human applies or rejects (initiative evaluate, transcript promote).  
     - **Entity lifecycle**: human acts on entity (signal ack/resolve/dismiss; intake graduate).  
     - **No record**: ephemeral (suggest_next_step; council unless caller stores artifact).

**Explicitly out of scope for the contract:**  
- One shared class for intake JudgmentRecord and council SeatJudgment.  
- Forcing all domains to use the same persistence schema.  
- Changing council or intake internal shapes beyond optional alignment to the contract where it helps.

---

## 4. Smallest Changes for Alignment

### 4.1 Meeting extraction

- **Add optional “extraction judgment” semantics without a new table:**  
  - When the frontend (or API) commits extraction results (user creates initiatives/signals from one extraction), optionally call `create_decision` once per extraction run with something like:
    - `entity_type="meeting"`, `entity_id=<meeting_id from extract>` (or a dedicated extraction_run_id if you add it),
    - `decision_type="meeting_extraction_committed"`,
    - `ai_proposal_snapshot=<minimal copy of extraction result that was on screen>` (ideas/initiatives/tasks/signals as proposed),
    - `final_values_snapshot=<ids of created entities: initiative_ids, signal_ids, etc.>`.
  - This aligns “proposal → user approved” with the same pattern as initiative evaluate and transcript promote, without changing extraction or canonization logic.

- **Naming / docs:**  
  - In `meeting_extract.py` or a short “judgment contract” doc, state that extraction output is a **proposal** (interpretation + proposed action) and that a **commit** is the human outcome; optional decision record above satisfies the contract.

- **Leave as-is:**  
  - Canonization and merge logic; no JudgmentRecord for extraction; no supersession (single-shot is fine).

### 4.2 Signals

- **Authority and human-review semantics:**  
  - Treat “create” as system or user; “update” (ack/link/resolve/dismiss) as human (or system) **resolution/dismissal** in the contract sense.  
  - In code/docs: when logging activity for SIGNAL_ACKNOWLEDGED, SIGNAL_LINKED, SIGNAL_RESOLVED, SIGNAL_DISMISSED, consider adding an optional `detail` that encodes “resolution” vs “dismissal” (e.g. resolved_with_initiative_id) so downstream can align with “action/proposal” semantics without schema change.

- **No supersession:**  
  - Keep in-place updates. The contract allows “in-place” as the correction model for signals; no need for a judgment chain.

- **Optional decision record:**  
  - For parity with other “user confirmed something” flows, you could optionally create a lightweight decision when user resolves or dismisses a signal (entity_type=signal, entity_id=signal_id, decision_type=signal_resolved / signal_dismissed, final_values_snapshot={ linked_initiative_id, ... }).  
  - **Smallest change:** only add this if you need decision history for signals; otherwise document that signal status *is* the outcome and activity log is the audit.

### 4.3 Vision Execution (VE) decisions

- **Consistent decision_type and snapshots:**  
  - Use a small set of decision_type values and document them in one place (e.g. in `vision_execution/models.py` or a short doc):  
    - evaluation_applied, initiative_approved, initiative_rejected, intake_graduate_task, transcript_candidate_decision, (optional) meeting_extraction_committed, (optional) signal_resolved / signal_dismissed.  
  - Convention: `ai_proposal_snapshot` = what was proposed (AI or system); `final_values_snapshot` = what was committed or chosen.  
  - For intake_graduate_task, keep storing judgment_id in final_values_snapshot and in task notes (already aligns with “subject + evidence” via judgment chain).

- **No supersession in decisions table:**  
  - Keep decisions append-only. The contract does not require VE to support supersession; intake keeps its own chain for intake items.

- **Authority:**  
  - Where possible, set `user_id` when the decision is made by a user (e.g. on Apply in initiative evaluate, on graduate, on transcript promote). Leave null for system-only decisions.

### 4.4 Summary table of recommended changes

| Area | Change | Size |
|------|--------|------|
| Meeting extraction | Optional: one `create_decision` on commit with decision_type=meeting_extraction_committed, ai_proposal_snapshot + final_values_snapshot | Small (frontend or API on commit) |
| Meeting extraction | Document extraction as “proposal”; commit as “human outcome” | Doc only |
| Signals | Document signal update as “resolution/dismissal” outcome; optional detail in activity | Doc + optional activity detail |
| Signals | Optional: create_decision on resolve/dismiss for decision history | Optional, small |
| VE | Centralize and document decision_type enum and snapshot semantics | Doc + optional constant list |
| VE | Set user_id when user performs the decision | Small (where missing) |
| Intake / Council | No change to JudgmentRecord vs SeatJudgment; keep separate | None |

---

## 5. What to Leave Unchanged

- **Intake JudgmentRecord** and **council SeatJudgment** remain separate types; no unification into one class.
- **Intake supersession** stays in the judgment layer and mirror; no move of supersession into VE decisions.
- **Council run** stays ephemeral unless a feature explicitly stores the artifact (e.g. in ai_proposal_snapshot); no requirement to persist.
- **Canonization and merge** in meeting extraction stay as-is; they are internal transformation, not the “judgment” record.
- **Suggest next step** stays ephemeral; no persistence required by the contract.
- **Decisions table** remains append-only; no superseded_by column added for now.

This audit gives a single mapping of judgment-like behavior, a minimal shared contract, and targeted, small changes so meeting extraction, signals, and VE align on semantics, authority, and (where applicable) correction/supersession expectations without a large rewrite.
