# Open Questions

Architectural ambiguities and unresolved decisions visible in the codebase. Where possible, specific file/function references are given.

---

## 1. Intake-Specific vs Platform-Wide

- **Judgment layer:** Implemented only for intake domain (`DOMAIN_INTAKE`). `local_ai/judgment/README.md` and naming suggest a shared “judgment” protocol, but persistence is intake-mirror-only. **Open:** Should other domains (e.g. Vision Execution, council decisions) ever persist judgments through this layer or a separate store?
- **Policy layer:** Documented in `docs/ZENAF_ARCHITECTURE.md` as shared (“intake, council/perspectives, File Steward, future connectors”). Only `local_ai/intake/mirror.get_item_with_content()` uses it. **Open:** Is the intent that every future consumer of Tier B/C or external egress must call `request_access`, and how will that be enforced or adopted?
- **Queue and mirror:** Queue and mirror are intake concepts (email/fax items). **Open:** Is “queue” ever intended to be a generic platform primitive (e.g. other domains with their own queues), or always intake-specific?

---

## 2. Persistent vs Ephemeral

- **Sync state:** `mirror_sync` and `set_sync_state` / `get_sync_state` exist in `local_ai/intake/mirror.py` but are never called after poll. **Open:** Should poll call `set_sync_state` (and optionally `record_mailbox_action`) so that sync state is the source of truth for “last poll” and cursor?
- **Perspectives:** When signed in, **server-owned** in `user_council_workspace` (`GET`/`PUT /vision-execution/council-workspace/perspectives`); `localStorage` is cache + anonymous fallback. **Open:** Cross-tab live sync without refresh is still eventual-consistency (debounced PUT).
- **Vision Execution DB init:** No explicit init at API startup; first request to vision-execution triggers `get_connection()` → `init_db()`. **Open:** Is “lazy init on first use” the long-term contract, or should startup ensure the DB exists and is migrated?

---

## 3. UI and API Wiring

- **Tier B/C in UI:** No API route or frontend flow calls `mirror.get_item_with_content()`. Queue list and item detail use only Tier A from `get_queue` / `get_item`. **Product contract:** Tier A only until explicitly shipped — see **`docs/01_TRUTH/TRUTH_CONVERGENCE.md`**. **Open:** If Tier B/C ship, which routes and policy UX justify access?
- **Ordering queue view:** Implemented in frontend and backed by GET /intake/queue and PATCH. **Open:** Any known gaps (e.g. filters, pagination, or archived handling) that are planned but not yet implemented?

---

## 4. Mailbox Mutation Assumptions

- **Read-only today:** `email_ingestion` only reads from IMAP; no mark-read, move, or delete. **Open:** When mailbox mutations are added, will they be driven from the mirror and `mailbox_action` table (as described in ZENAF_ARCHITECTURE.md) for audit and idempotency?
- **Sync state and cursors:** `mirror_sync` has `last_poll_at` and `cursor`; no code sets them. **Open:** What cursor semantics are expected (e.g. IMAP UID, or provider-specific), and should poll always update sync state after a successful run?

---

## 5. Shared Policy and Modules

- **Council:** Uses `local_ai.providers.get_default_provider()` and does not call `local_ai.policy.data_access`. If council ever receives or displays intake content (e.g. “summarize this queue item body”), **open:** should it call `get_item_with_content` and `request_access` before using that content?
- **File Steward:** Operates on file paths and folder structure; no intake data. **Open:** Is File Steward ever intended to need policy (e.g. when reading files that might contain sensitive content), or is it out of scope for the current policy layer?
---

## 6. Adapters and Providers

- **LLM:** Council and other tools use `local_ai.providers.get_default_provider()` directly. Adapters register `llm.ollama` but nothing calls `get_adapter("llm", ...)`. **Open:** Is the intended design that all LLM access eventually goes through the adapter registry, or are providers the permanent entry point?
- **Mailbox:** No mailbox adapter implementation; intake uses `email_ingestion` and `gmail_oauth` directly. **Open:** Is the plan to introduce a concrete MailboxAdapter (e.g. IMAP/Gmail) and switch intake to `get_adapter("mailbox", ...)` for fetch, or keep ingestion outside adapters?

---

## 7. Synthetic Data and Scripts

- **Two generate scripts:** `scripts/generate_intake_synthetic_data.py` (→ `datasets/intake_synthetic_cases.json`) and `scripts/generate_synthetic_intake_dataset.py` (→ `data/synthetic_intake_dataset.json`). **Open:** Which is canonical for regression/evaluation, or are both maintained for different purposes?
- **Evaluation and mirror:** `evaluate_intake_synthetic_data.py` runs the pipeline in a fresh process; it does not load or write the mirror. **Open:** Is it intentional that evaluation never touches the live mirror (recommended), or will there be a “evaluate against mirror data” mode?

---

## 8. Configuration and Paths

- **Mirror path:** Intake mirror path is hardcoded in `local_ai/intake/mirror.py` (repo root + `intake_mirror.db`). **Open:** Should this be configurable via env or config file for different deployments?
- **Vision Execution DB path:** Under `data/vision_execution/vision_execution.db` relative to repo/cwd. **Open:** Same question for configurability.

---

## 9. Deprecated and Cleanup

- **access_policy shim:** `local_ai/intake/access_policy.py` re-exports from `local_ai.policy.data_access` and is marked deprecated. **Open:** Are any remaining imports still using `local_ai.intake.access_policy`? If not, can the shim be removed and imports updated to `local_ai.policy.data_access` only?

---

## 10. Unclear from Code

- **Tier C raw_content_ref:** Column exists; no writer or reader. Unclear whether raw storage is deferred indefinitely or planned for a specific use case.
- **destination=EXTERNAL:** Parameter exists in `request_access`; no caller uses it. Unclear when the first egress-gating use is expected.
