# Zenaf Data Flow

Major data flows through the system. Based on the current codebase.

---

## 1. Mailbox → Ingestion → Normalization → Pipeline → Queue → Mirror

1. **Mailbox (read-only)**  
   - IMAP (or Gmail OAuth XOAUTH2). Config from env or `intake_imap_config.json`.  
   - `email_ingestion._poll_one_mailbox()` fetches messages; no delete/move/mark-read in current code.

2. **Normalization**  
   - `_normalize_body(msg)` in `email_ingestion.py`: HTML stripped to text, encoding handled.  
   - `_external_id(message_id, uid, date_str)` builds a stable id for deduplication.

3. **Pipeline**  
   - For each message: `run_pipeline(body, "email", subject=..., sender=...)` in `pipeline.py`.  
   - Steps: classifier → category/priority; redaction (optional) → sanitized body; lanes.derive_lane() → lane; `create_intake_judgment()` → judgment_id; summary from sanitized text.  
   - Output: `IntakeItem` (includes `sanitized_body` for mirror only; not in `to_dict()` for in-memory queue).

4. **Queue**  
   - `queue_store.add_item(item)`:  
     - Appends to in-memory `_order` and `_items[item.id]`.  
     - Calls `mirror.upsert_item(item.to_dict(), sanitized_body_text=item.sanitized_body)` and `mirror.upsert_judgment_chain_for_entity(item.id)`.

5. **Mirror**  
   - `mirror_item`: Tier A fields from item dict + `sanitized_body_text` (Tier B). `raw_content_ref` (Tier C) is placeholder.  
   - `mirror_judgment`: one row per judgment record for the entity.  
   - Duplicate detection: `get_by_external_id(external_id)` before add; if present, message is skipped.

**Summary:** Mailbox → fetch → normalize body → run_pipeline → add_item → in-memory queue + mirror (write-through). No sync state or mailbox action written after poll today.

---

## 2. Queue Update / Correction Flow

1. **Client** PATCH `/intake/queue/{item_id}` with body e.g. `{ "status", "notes", "assigned_to", "lane_override", "correction_note", "archived" }`.

2. **API** `intake_routes` → `queue_store.update_item(item_id, ...)`.

3. **update_item()** (`queue_store.py`):  
   - Updates in-memory `_items[item_id]` for status, notes, assigned_to, archived, lane_override.  
   - If `lane_override` and `correction_note` are both non-empty:  
     - `create_correction_record(entity_id=item_id, supersedes_judgment_id=prev_judgment_id, proposed_action_override={"lane": lane_override}, correction_note=...)`  
     - Sets `d["judgment_id"]` to the new record’s id.  
   - Calls `mirror.upsert_item(d)` and `mirror.upsert_judgment_chain_for_entity(item_id)`.

4. **Persisted:** Same item row updated in `mirror_item`; all judgment rows for that entity (including the new correction) in `mirror_judgment`.

**Summary:** PATCH → in-memory update → optional correction record → mirror write-through. Queue and judgment runtime state live in memory; mirror is durable copy.

---

## 3. Judgment Creation / Supersession Flow

1. **Initial judgment**  
   - In `run_pipeline()`: after classifier and lane, `create_intake_judgment()` is called with entity_id=item.id, interpretation, proposed_action (lane, category, etc.), confidence, codes.  
   - Returns a `JudgmentRecord`; its `id` is stored on the item as `judgment_id`.  
   - Record is held in `local_ai.judgment` and persisted via `upsert_judgment_chain_for_entity()` when the item is added.

2. **Supersession (correction)**  
   - `create_correction_record(entity_id, supersedes_judgment_id, proposed_action_override, correction_note)` creates a new record that references the previous one.  
   - The previous record’s `superseded_by` is set to the new record’s id.  
   - `get_supersession_chain(judgment_id)` returns the chain (original → … → latest).  
   - When saving to mirror, all records for the entity are written; mirror schema holds `superseded_by` and `correction_note`.

3. **Persistence**  
   - Only path to persistence: intake mirror. `upsert_judgment_record(r.to_dict())` writes one row; `upsert_judgment_chain_for_entity(entity_id)` reads from in-memory judgment store and writes every record for that entity.

**Summary:** Judgments created in pipeline and on correction; stored in memory; persisted only via intake mirror when queue item is added or updated.

---

## 4. Synthetic Dataset Generation / Evaluation / Review Flow

1. **Generation**  
   - `scripts/generate_intake_synthetic_data.py`: template-based cases → `datasets/intake_synthetic_cases.json` (id, subject, body, expected_category, expected_lane, difficulty, notes).  
   - Another script: `scripts/generate_synthetic_intake_dataset.py` → `data/synthetic_intake_dataset.json`.  
   - No DB or mirror involved; output is JSON files.

2. **Evaluation**  
   - `scripts/evaluate_intake_synthetic_data.py`: reads cases (default `datasets/intake_synthetic_cases.json`), for each runs `run_pipeline(body, "email", subject=...)`, compares actual vs expected category/lane, aggregates stats, optionally exports mismatches to `datasets/intake_synthetic_failures.json`.  
   - Uses `local_ai.judgment.get_record` for optional reason/confidence on failures.  
   - Pipeline and judgment are in-memory; no mirror required for the script (fresh process).

3. **Review**  
   - `scripts/review_intake_failures.py`: operates on failure/review JSON (e.g. failures or `intake_synthetic_reviews.json`).  
   - Used to inspect or re-label; does not write back to mirror.

**Summary:** Synthetic data is file-based; evaluation runs the pipeline in-process against those files; results and reviews are JSON. No flow into the live queue or mirror unless a separate path is added.

---

## 5. Tier A / B / C Data Flow

- **Tier A (operational):** In-memory queue item dicts and mirror_item columns: external_id, subject, sender, timestamps, summary, category, lane, confidence, judgment_id, lane_override, status, notes, archived, etc.  
  - **Flow:** Written by pipeline/add_item and update_item; read by GET queue and GET item. No policy check for Tier A.

- **Tier B (sanitized body):** Stored only in mirror as `sanitized_body_text`; not in queue item `to_dict()` so not in in-memory queue.  
  - **Flow:** Written in `mirror.upsert_item(..., sanitized_body_text=...)`. Read when something needs body text via `mirror.get_item_with_content(item_id, access_level=AccessLevel.SANITIZED_TEXT, ...)` which calls `request_access(...)` then returns item dict with body content.  
  - **Current use:** Only `get_item_with_content()` implements this; no API route or frontend is wired to call it in the codebase today.

- **Tier C (raw):** Placeholder only. `raw_content_ref` in mirror schema; no storage of full raw content.  
  - **Flow:** `request_access(RAW_CONTENT_REQUIRED, justification=...)` would be required; no implementation of actual raw retrieval exists.

**Summary:** Tier A flows through queue and API. Tier B is mirror-only and gated by policy in `get_item_with_content`; no caller uses it yet. Tier C is not implemented.

---

## 6. Internal Local vs External-Bound Access

- **Policy** (`local_ai/policy/data_access.py`):  
  - `request_access(level, justification=..., destination=...)`.  
  - `Destination`: `DEST_LOCAL` (internal use) vs `DEST_EXTERNAL` (egress).  
  - Tier C requires justification unless `allow_without_justification`; destination is for future egress gating.

- **Current usage:**  
  - Only `mirror.get_item_with_content()` calls `request_access(access_level, justification=justification)`.  
  - It does not pass `destination`; so all current calls are effectively local.  
  - No other module (council, File Steward, connectors) calls the policy layer.

- **Intent (from docs):** External-bound use (e.g. sending content to an external API) should call with `destination=Destination.EXTERNAL` and appropriate level/justification. Not yet implemented at any call site.

**Summary:** Local vs external is modeled in the API; only intake mirror uses the policy, and only for level/justification, not yet for destination.
