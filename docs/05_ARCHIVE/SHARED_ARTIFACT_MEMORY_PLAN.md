# Shared Artifact Path — Implementation Plan

**Status:** Planning only (no implementation yet)  
**Intent:** Let the general model and council model inform each other through **inspectable, explicit** shared artifacts (observations, judgments, decisions, outcomes)—**not** through fine-tuning, self-training, or hidden adaptation.

---

## 1. Where general-model outputs exist today (candidates for normalization)

| Source | Location | Current form | Could normalize to |
|--------|----------|--------------|---------------------|
| **Next-step** | `local_ai/zenaf_tools.py` — `suggest_next_step()` | Returns dict: `recommendation`, `rationale`, `alternatives`, `caution`. Not persisted. | **Judgment** artifact (subject from context if any; payload = recommendation + rationale). |
| **Content generation** | `local_ai/zenaf_tools.py` — `generate_content()` | Returns raw string (script/newsletter). Brief and source in caller. | **Observation** or **judgment** (e.g. “content_generated”, brief_id / linked entity in subject_ref; optional short summary in payload). |
| **Folder/workflow summaries** | Frontend `buildContextBlock()` → `context_block` in API | Last analyze/simulate/assess/recommend/council excerpt sent as string to council or next_step. | Not a single “artifact” today; could be **observation** (e.g. “workflow_snapshot”) if we explicitly write a compact summary to the shared store. |
| **Transcript sorter** | `local_ai/transcripts` — `sort_transcript()` | Returns structured topics, deliverables, candidate tasks/decisions. Judgment-only; no storage. | **Judgment** artifact (subject = call/transcript ref if provided; payload = topics + candidates). |
| **Intake judgments** | Intake mirror (`mirror_judgment`) | JudgmentRecord: interpretation, proposed_action, confidence, etc. Already persisted in intake. | **Judgment** artifact: write a **reference** or a small summary into shared store when judgment is created/updated, with subject_ref = intake item; link to judgment_id. |
| **User edits / preferences** | Not centralized | Edits to content, lane overrides, decision confirmations live in VE (final_values_snapshot) or intake (lane_override, correction_note). | **Decision** or **outcome** artifacts: when a VE Decision is created or intake is corrected, optionally write a thin artifact (subject_ref + decision_id or judgment_id) so council/general can “see” recent human decisions. |

**Summary:** The smallest first **writers** for the general path are: (1) **next-step** output as a judgment artifact, (2) optional **intake judgment** summary ref, (3) optional **transcript sort** result. Content generation and workflow summaries can follow once the store and council reader exist.

---

## 2. Where council outputs exist today (candidates for write/read)

| Source | Location | Current form | Could normalize to |
|--------|----------|--------------|---------------------|
| **SeatJudgment** | `local_ai/judgment_substrate.py`; produced in `zenaf_tools.run_council()` | Per-seat: position, primary_reason, main_risk, next_step, seat_id, etc. Returned in `CouncilRunArtifact.seats`. | **Judgment** artifacts: one per seat (subject_ref from run; payload = position, reason, risk, next_step; source = council, source_model = provider name). |
| **CouncilRunArtifact** | Same; returned when `return_artifact=True` | question, subject, seats, synthesis_text, distinct_positions, provider_name, model_name. | **Judgment** (or “council_run”) artifact: one summary record (subject_ref, payload = question + synthesis + positions; source = council). |
| **VE decisions** | `local_ai/vision_execution/storage.py` — `create_decision`, `list_decisions` | Decision: entity_type, entity_id, decision_type, ai_proposal_snapshot (often council artifact), final_values_snapshot. Already persisted. | **Decision** artifacts: when a Decision is created (especially with ai_proposal_snapshot from council), optionally write a **reference** artifact (subject_ref = entity; decision_id; type = decision) so general model can list “recent decisions.” |
| **Council context today** | `zenaf_tools.collect_decision_context`, `_get_recent_decision_context` | Reads VE `list_decisions` and builds text for council packet. | **Retrieval hook:** optionally augment or substitute with `list_artifacts(types=["judgment","decision"], limit=N)` so council sees recent general-model judgments and decisions as well. |

**Summary:** Council **writers:** (1) after `run_council`, write each SeatJudgment + one CouncilRunArtifact summary as judgment artifacts; (2) when VE `create_decision` is called with council in ai_proposal_snapshot, optionally write a decision artifact ref. Council **readers:** (1) keep existing VE `list_decisions`; (2) add optional “recent shared artifacts” in `build_council_decision_packet` (or a dedicated “recent judgments/decisions” block) from the new store.

---

## 3. Smallest additive implementation plan

### 3.1 Shared artifact schema (additive; no rewrite of existing types)

Introduce a single **SharedArtifact** type (e.g. in `local_ai/shared_artifacts.py`) with:

- **artifact_type:** `observation` | `judgment` | `decision` | `outcome`
- **subject_ref:** Optional[SubjectRef] (or NodeRef when node substrate is canonical) — identity of the object this artifact is about
- **source:** `general` | `council` — which path produced it
- **source_provider:** Optional[str] — e.g. "OllamaProvider", "qwen2:7b-instruct"
- **source_entity_id:** Optional[str] — e.g. decision_id, judgment_id, intake_item_id for provenance
- **payload:** Dict[str, Any] — small, inspectable summary (e.g. position, next_step, recommendation, decision_type); no large blobs
- **created_at:** str (ISO)
- **id:** Optional[str] — unique artifact id for retrieval and dedup

Reuse **SubjectRef** from judgment_substrate (or NodeRef from node_substrate) so we do not redefine identity. No change to JudgmentSnapshot, SeatJudgment, or CouncilRunArtifact; they remain as-is. SharedArtifact is a **cross-path envelope** that references them and adds provenance.

### 3.2 Persistence: append-only, inspectable

- **Module:** `local_ai/shared_artifacts.py`
- **Operations:** `write_artifact(artifact: SharedArtifact) -> str` (returns id); `list_artifacts(artifact_types: list[str] | None = None, subject_ref: SubjectRef | None = None, limit: int = 50) -> list[SharedArtifact]`; optionally `get_recent_for_context(limit: int, types: list[str]) -> str` that returns a single formatted string for injection into council or next-step context.
- **Storage:** Append-only (e.g. SQLite table or JSONL file). No updates or deletes in Phase 1. Schema: id, artifact_type, source, source_provider, source_entity_id, subject_ref (JSON), payload (JSON), created_at.
- **Provenance:** Every record has source, source_provider, source_entity_id, created_at so “who produced what and when” is explicit.

### 3.3 Optional retrieval hooks

- **Council:** In `build_council_decision_packet` (or a helper it calls), optionally call `get_recent_for_context(limit=10, types=["judgment","decision"])` and append a “Recent shared judgments/decisions” block (truncated to MAX_*_CHARS) so council sees general-model and prior council outputs. Default: **off** (no change to current behavior) until explicitly enabled (e.g. param or config).
- **General (next-step):** Optional param or config: “include_recent_artifacts”. When set, `suggest_next_step` receives an extra context line from `get_recent_for_context(limit=5, types=["judgment","decision"])` so next-step can consider recent council outcomes and decisions. Default: **off**.

### 3.4 What is explicitly NOT implemented

- **No** model fine-tuning or weight updates.
- **No** self-training loops or automatic behavior rewriting.
- **No** hidden cross-model adaptation (all reads/writes are explicit and inspectable).
- **No** automatic injection into every prompt without an explicit opt-in (config or param).
- **No** schema rewrite of VE Decision, intake mirror, or judgment_substrate; SharedArtifact is additive and references existing ids (decision_id, judgment_id) where needed.

---

## 4. Implementation order and what to defer

### Phase 1 — Store and schema only (implement first)

| What | Where | Notes |
|------|--------|--------|
| **SharedArtifact** Pydantic model | `local_ai/shared_artifacts.py` | artifact_type, subject_ref (SubjectRef from judgment_substrate), source, source_provider, source_entity_id, payload, created_at, id. |
| **write_artifact**, **list_artifacts** | Same module | Append-only store (SQLite or JSONL). Simple, no dependencies on call sites. |
| **get_recent_for_context** (optional) | Same module | Returns a single string for context injection; used only when hooks are enabled. |

No call-site changes in Phase 1. No council or general model writes yet. This validates the schema and storage and keeps the change minimal.

### Phase 2 — Council path (write + optional read)

| What | Where | Notes |
|------|--------|--------|
| After `run_council` when artifact is built | `local_ai/zenaf_tools.py` | If return_artifact and CouncilRunArtifact is built: for each SeatJudgment write one SharedArtifact (type=judgment, source=council, payload=position/reason/risk/next_step); write one summary artifact (type=judgment, payload=question+synthesis+positions). Subject_ref from run. |
| Optional: augment council packet with recent artifacts | `build_council_decision_packet` or helper | Only when a flag/config is set; call get_recent_for_context(limit, types) and append truncated block. Default off. |

### Phase 3 — General path (write + optional read)

| What | Where | Notes |
|------|--------|--------|
| After `suggest_next_step` | `local_ai/zenaf_tools.py` | Optionally write one SharedArtifact (type=judgment, source=general, payload=recommendation+rationale). Subject_ref from context if parseable (e.g. from request) or None. |
| Optional: next-step context from artifacts | `suggest_next_step` or API | When flag set, prepend get_recent_for_context(limit, types) to context. Default off. |

### Defer (do not implement in initial cut)

- Content generation → artifact write (add when content pipeline and brief→entity linking are stable).
- Transcript sort → artifact write (add when transcript flow is a primary input).
- Intake judgment → shared artifact ref (add when we want council to “see” intake judgments explicitly; intake already has mirror).
- Automatic injection into every council/next-step run (keep opt-in only).
- Outcome artifacts (explicit outcome assessment) until VE or a dedicated outcome step exists; then add write when outcome is recorded.
- Any “learning” or “adaptation” logic; the store is read/write memory only.

---

## 5. Exact files/modules to touch (by phase)

| Phase | File / module | Change |
|-------|----------------|--------|
| **1** | **New:** `local_ai/shared_artifacts.py` | SharedArtifact model, write_artifact, list_artifacts, get_recent_for_context; append-only storage. |
| **1** | `local_ai/judgment_substrate.py` | None (reuse SubjectRef via import). |
| **2** | `local_ai/zenaf_tools.py` | After building CouncilRunArtifact, call write_artifact for each seat + one summary. Optional: in build_council_decision_packet (or helper), if enabled, call get_recent_for_context and append. |
| **2** | `local_ai/config.py` (optional) | Add e.g. COUNCIL_USE_SHARED_ARTIFACTS = False so council can optionally pull recent artifacts. |
| **3** | `local_ai/zenaf_tools.py` | In suggest_next_step, optionally write one judgment artifact; optionally prepend get_recent_for_context to context when enabled. |
| **3** | `api/main.py` (optional) | Pass a request or config flag so next-step knows whether to include recent artifacts in context. |

**Do not touch (unless necessary):** VE storage schema, intake mirror schema, judgment_substrate types (SubjectRef, JudgmentSnapshot, SeatJudgment, CouncilRunArtifact), frontend, content generation pipeline, transcript persistence.

---

## 6. What should explicitly NOT be changed yet

- **VE Decision table and schema** — No new required columns. ai_proposal_snapshot and final_values_snapshot stay as-is. Shared artifacts store **references** (e.g. decision_id) and optional small payloads, not full snapshots.
- **Intake mirror and JudgmentRecord** — No schema change. Optional later: when a judgment is created, write a ref into shared_artifacts; not in Phase 1–3.
- **Council run_council signature and return shape** — Still returns str or (str, CouncilRunArtifact). Writing to shared_artifacts is an internal side effect when artifact is present.
- **Default behavior** — Council and next-step behave exactly as today unless a config or param turns on “use shared artifacts” for read and/or write.
- **No new API endpoints** in Phase 1–3 (optional later: GET /artifacts for debugging or UI).
- **No frontend** for “memory” or “recent judgments” until we have a clear UX need.

---

## 7. Summary

- **General-model outputs** that can become shared artifacts: next-step (judgment), optionally content generation and transcript sort later; intake and user decisions as refs when needed.
- **Council outputs** that already exist: SeatJudgment, CouncilRunArtifact; VE decisions with ai_proposal_snapshot. Plan: write seat + summary artifacts when council completes; optionally write decision ref when VE create_decision is called; optionally feed recent artifacts into council packet and next-step context.
- **Smallest path:** Phase 1 = shared artifact schema + append-only store + list/get_recent. Phase 2 = council writes + optional council read. Phase 3 = next-step write + optional next-step read. All opt-in for reads; writes can be always-on for council/next-step to keep memory populated.
- **Inspectable, explicit:** Every artifact has type, source, source_provider, subject_ref, payload, created_at. No opaque learning; no schema rewrite of existing systems.
