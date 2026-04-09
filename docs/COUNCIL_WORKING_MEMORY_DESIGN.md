# Council working-memory pull — minimal design

**Status:** Implemented (see §7 and zenaf_tools.py)  
**Scope:** Fast council only. No full memory framework, no conversation-history injection, no changes to cockpit/next-step/content flows.  
**Goal:** Define the smallest useful working-memory layer for council now that latency is acceptable, without prompt bloat or fluff.

---

## 1. Current memory/fact sources (available for council)

| Source | Where it lives | Currently used in council prompt? | Notes |
|--------|----------------|-----------------------------------|--------|
| **subject_ref** | Passed into `run_council` / `run_council_stream`; normalized in `judgment_substrate.normalize_subject_ref`; stored in `context_ref` and `CouncilRunArtifact.seat_judgments[].subject` | **No** — not in packet text | Identity: entity_type, entity_id, title, summary, extra. API already accepts `params.subject_ref` (dict). |
| **object_snapshot** | Passed as dict to `run_council`; stored in `context_ref["object_snapshot"]` | **No** — not serialized into prompt | Caller-defined small snapshot; can be used for a 1–2 line “current object” line if kept tiny. |
| **Recent VE decisions** | `ve_storage.list_decisions(entity_type, entity_id, limit)`; `_get_recent_decision_context`, `collect_decision_context`, `_format_decision_context_block` in `zenaf_tools.py` | **Yes** — built-in path only | Per-seat block “Recent decisions relevant to your role” (limit=5, perspective-filtered). Not in shared packet. |
| **Related decisions for subject** | Same `list_decisions`; when `entity_type` and `entity_id` are set, can call `list_decisions(entity_type, entity_id, limit=N)` | **No** | Ideal for “recent decisions **about this object**” in working memory. |
| **NodeSnapshot** | `node_substrate.NodeSnapshot` *(type only; `node_adapters` **retired/tombstoned**)* | **No** — no prompt builder reads them | Prefer **SubjectRef** (`judgment_substrate`) at call sites; `node_ref_to_subject_ref` bridges NodeRef→SubjectRef. Do not inject raw NodeSnapshot into packet. |
| **JudgmentSnapshot / CouncilRunArtifact** | `judgment_substrate`; produced by council run; stored in VE `ai_proposal_snapshot` | **No** — not fed back into prompts | Output only. Do not add past council run summaries to default working memory (bloat risk). |
| **Operator priorities** | `phil_context.load_operator_priority()`; used in `build_council_decision_packet` | **Yes** — last block in packet (220 chars) | Keep as-is; preference signal, not “memory.” |

**Conclusion:** The smallest useful pull is (1) **current subject snapshot** (from subject_ref + optional tiny object_snapshot), and (2) **up to N recent decisions about that subject** when subject has entity_type/entity_id. No new persistence or shared-artifact store required.

---

## 2. Recommended default working-memory policy (fast council)

- **Current subject snapshot**  
  One line when `subject_ref` is present:  
  `Object under consideration: <entity_type> [entity_id] <title or summary>`.  
  If `object_snapshot` is a small dict (e.g. status, one-line summary), add at most one more line (e.g. `Status: …`), otherwise omit to avoid bloat.

- **Up to N recent related decisions**  
  When `subject_ref` has `entity_type` and `entity_id`: call `list_decisions(entity_type=..., entity_id=..., limit=N)` (recommend **N = 3**), format each as one short line (e.g. `[date] decision_type — state` or same as current `_decision_row_to_minimal`). If no subject or no entity_id, skip this block.

- **Optional related outcomes**  
  Omit from “smallest” design. Outcome/status is already present in `_decision_row_to_minimal` (state from get_task/get_project/get_initiative). No extra lookup.

- **Short operator-priority block**  
  Already in packet; unchanged.

**Caps:**  
- Working-memory block total: **400 characters** (hard truncate).  
- Related decisions: **3** by default.

---

## 3. Where working memory sits in council truth order

Current packet order (`_COUNCIL_PACKET_ORDER`):  
`context` → `question` → `recent_tool_summary` → `constraints` → `operator_priorities`.

Insert **working_memory** after **question**, before **recent_tool_summary**:

1. **Task** — Context, Question  
2. **Working memory** — Subject snapshot + up to N related decisions (when available)  
3. **System facts** — Recent tool summary (and, for built-in seats only, the existing per-seat “Recent decisions relevant to your role” block)  
4. **Hard bounds** — Constraints  
5. **Preference** — Operator priorities  

So:

- **context** → **question** → **working_memory** → **recent_tool_summary** → **constraints** → **operator_priorities**

Rationale: Model sees the decision problem first, then a minimal “what is this object and what have we already decided about it,” then other system facts and bounds, then preference. Working memory is scoped to the current object and recent decisions about it, not a substitute for the existing per-role “recent decisions” block (which remains perspective-filtered and built-in-only).

---

## 4. Smallest safe implementation path (council only)

- **Files to touch**
  - `local_ai/zenaf_tools.py` only (and optionally `docs/ZENAF_PROMPT_AND_TRUTH_ARCHITECTURE.md` for the new block and order).

- **Functions**

  1. **`_build_working_memory_block(subject_ref, object_snapshot, max_related=3, max_chars=400) -> str | None`** (new, in `zenaf_tools.py`)
     - If no subject_ref (or normalized ref is empty): return `None`.
     - Build one line: `Object under consideration: <entity_type> [entity_id] <title or summary>` (truncate title/summary to ~60 chars).
     - If object_snapshot is a dict with 1–2 keys (e.g. `status`, `summary`), append one short line; else skip.
     - If subject has entity_type and entity_id: call `list_decisions(entity_type, entity_id, limit=max_related)`, map to minimal lines (reuse `_decision_row_to_minimal` or equivalent), format as “Related decisions:” + list.
     - Truncate entire block to `max_chars`; if result is empty or only whitespace, return `None`.

  2. **`build_council_decision_packet(..., subject_ref=..., object_snapshot=..., working_memory_max_chars=400)`**
     - Add optional parameters `subject_ref` and `object_snapshot` (and optionally `working_memory_max_chars`).
     - Call `_build_working_memory_block(subject_ref, object_snapshot, max_related=3, max_chars=working_memory_max_chars)`.
     - If non-empty, insert the block in order after “Question” and before “Recent tool summary.”
     - Update `_COUNCIL_PACKET_ORDER` to include `"working_memory"` and build the packet accordingly (only append working_memory block when present).

  3. **`run_council` / `run_council_stream`**
     - When calling `build_council_decision_packet`, pass `subject_ref=subj`, `object_snapshot=context_ref.get("object_snapshot")` (or the same object_snapshot passed in). No change to other call sites if they don’t pass subject_ref/object_snapshot (block simply stays empty).

- **What not to do**
  - Do not add a new route or a new “memory” API.
  - Do not inject conversation history, past CouncilRunArtifact, or shared-artifact store into council.
  - Do not change cockpit, next-step, content, or other prompt flows.
  - Do not add working memory to synthesis prompt (synthesis stays question + seat summaries only).

---

## 5. What to explicitly NOT include (default fast council memory)

To avoid prompt bloat and muddy reasoning:

- **Full conversation history** — Not in council at all.
- **Past council run artifacts / seat judgments** — Stored for attribution only; do not feed back into the next run by default.
- **Raw NodeSnapshot or long payloads** — Use only to derive a short subject line or 1–2 line object_snapshot at the caller; do not dump into packet.
- **Philosophical orientation / long operator identity** — Operator priorities block stays short (220 chars); no extra “brand” or philosophy block.
- **Unbounded decision list** — Cap related decisions (e.g. 3) and total working-memory chars (e.g. 400).
- **Full ai_proposal_snapshot or final_values_snapshot** — Do not inject decision body JSON; only decision_type, entity, summary, state, created_at (or similar minimal line).
- **Shared artifact store / “recent judgments”** — Out of scope; no new store or retrieval in this design.

---

## 6. Example council packet shape (with working memory)

When `subject_ref = { entity_type: "task", entity_id: "abc-123", title: "Ship login flow" }` and there are 2 related decisions:

```
Context:
Folder: /projects/zenaf

Question:
Should we prioritize the login flow or the dashboard next?

Working memory:
Object under consideration: task abc-123 Ship login flow
Related decisions: [2026-03-10] intake_graduate_task — state=Todo; [2026-03-09] status_change — state=In Progress

Recent tool summary:
File Steward analyzed 12 items; 3 low-confidence. Recommendation: …

Constraints:
Must complete by Q2. No new scope without approval.

Operator priorities:
Focus on user-visible impact; avoid context-switching; …
```

When no subject_ref is provided, the packet is unchanged from today (no “Working memory” block).

---

## 7. Summary

| Item | Recommendation |
|------|----------------|
| **Default working-memory policy** | Current subject snapshot (1–2 lines) + up to 3 related VE decisions; total block ≤ 400 chars. |
| **Truth order** | context → question → **working_memory** → recent_tool_summary → constraints → operator_priorities. |
| **Files to touch first** | `local_ai/zenaf_tools.py`: add `_build_working_memory_block`, extend `build_council_decision_packet`, pass subject_ref/object_snapshot from `run_council`/`run_council_stream`. |
| **Example packet** | See §6. |
| **Out of scope** | Full memory framework, conversation history, shared artifacts, other prompt paths, synthesis input change. |

---

## 8. Implemented format (working-memory block)

**Header:** `Working memory:` (single line).

**Body (all counts toward 400-char cap):**

1. **Subject line:** `Object under consideration: <entity_type> <entity_id> <title_or_summary>`  
   - title_or_summary from subject_ref.title or subject_ref.summary, truncated to 60 chars.

2. **Optional one fact line:** Only if `object_snapshot` is a dict with ≤2 keys; at most one of `Status: <val>` or `Summary: <val>` (first of status/summary present), val truncated to 50 chars.

3. **Related decisions (optional):** Only when subject has entity_type and entity_id.  
   - Section header: `Related decisions:`  
   - One line per decision: `- [<date>] <summary> — <state>`  
   - date = first 10 chars of created_at; summary truncated to 40 chars; state from VE entity lookup.  
   - Up to 3 decisions (same entity_type + entity_id via `list_decisions`).

**Truncation:** Entire block (including header) is truncated to 400 chars; if nothing remains after truncation, no block is added.
