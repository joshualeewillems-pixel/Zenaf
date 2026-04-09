# File sorting / Workspace Organizer pipeline — architecture inspection

**Purpose:** Document the full flow so we can decide where to constrain council behavior (e.g. parent-folder categories only, brief reasoning, no long narrative or restructuring logic).  
**Scope:** Analyze → Assess (optional) → Recommend → Council (optional) → Simulate. No code changes in this doc.

---

## 1. End-to-end flow

### 1.1 "Analyze & assess uncertainty" and "Recommend folders"

| Step | UI action | Frontend | API | Backend | Model? |
|------|-----------|----------|-----|---------|--------|
| **Analyze** | User picks folder, clicks "Run Analyze" | `runMode('analyze', path)` → `POST /run` with `mode: 'analyze'`, `params: { folder_path }` | `api/main.py` → `_run_analyze(params)` | `zenaf_tools.analyze_file_steward_folder(path)` → `tools/file_steward/app.py` → `analyze_folder_structure(folder_path)` | **No** |
| **Assess (optional)** | "Run Assess uncertainty" | `runMode('assess', path)` → `POST /run` with `mode: 'assess_uncertainty'` | `_run_assess_uncertainty(params)` | Calls `_run_simulate(params)` (no suggested_folders), then filters low-confidence; returns assess summary + simulate_tree | **No** (simulate may use LLM in a second pass if configured; default path is algorithmic) |
| **Recommend** | "Run Suggest Folders" | `runMode('recommend', path)` → `POST /run` with `mode: 'recommend'` | `_run_recommend(params)` | `zenaf_tools.recommend_child_folders(path)` → `app.recommend_child_folders(folder_path)` | **No** |

**Functions responsible:**

- **Analyzing folder contents:** `tools/file_steward/app.py` → `analyze_folder_structure(folder_path)`. Wrapper: `local_ai/zenaf_tools.py` → `analyze_file_steward_folder()` (and `analyze_folder_structure()`).
- **Generating suggested folders:** `tools/file_steward/app.py` → `recommend_child_folders(folder_path)`. Wrapper: `local_ai/zenaf_tools.py` → `recommend_child_folders()`.
- **Invoking council:** User clicks "Ask Council" (or "Run Council" from AI agents panel). Frontend calls `runCouncil()` → `POST /run/stream` with `mode: 'council'`, `params: { question, included_agents?, perspective_definitions? }`, `context: { folder_path?, context_block? }`. API → `_council_stream_gen(params, request.context)` → `local_ai/zenaf_tools.run_council_stream(question, context=context_str, ...)`.
- **Passing council output back to UI:** SSE stream yields `data: {"chunk": "...", "done": false|true}`. Frontend accumulates chunks into `fullText`, then sets `setResult(councilText)`, `setLastCouncilResult(councilText)`, and appends to `agentThread`. Council output is shown in the **AI agents** (right) panel as free-form text via `CouncilText`; it is **not** shown in the left-panel "Workflow result (JSON)" (that is only for analyze/simulate/assess/recommend).

### 1.2 Pipeline diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  USER (Workspace Organizer)                                                       │
└─────────────────────────────────────────────────────────────────────────────────┘
     │
     │ 1. Select folder
     │ 2. Run Analyze
     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  POST /run  mode=analyze  params={ folder_path }                                  │
│  → _run_analyze → analyze_file_steward_folder(path)                               │
│  → tools/file_steward/app.analyze_folder_structure(path)                         │
│  ← JSON: folder_path, item_count, file_count, folder_count, repeated_tokens,      │
│          repeated_years, extension_breakdown, inferred_context_domain,            │
│          suggested_child_folders [, truncated, total_items_seen, items_analyzed ] │
└─────────────────────────────────────────────────────────────────────────────────┘
     │
     │ 3. (Optional) Run Assess uncertainty
     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  POST /run  mode=assess_uncertainty  params={ folder_path }                      │
│  → _run_assess_uncertainty → _run_simulate (no suggested_folders)                │
│  → simulate_folder_plan(path) → filter confidence < 0.4                            │
│  ← JSON: low_confidence_count, items[], simulate_tree                              │
└─────────────────────────────────────────────────────────────────────────────────┘
     │
     │ 4. Run Suggest Folders
     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  POST /run  mode=recommend  params={ folder_path }                               │
│  → _run_recommend → recommend_child_folders(path)                                 │
│  → tools/file_steward/app.recommend_child_folders(path)  [no analyze/assess data] │
│  ← JSON: folder_path, inferred_context_domain, suggested_child_folders[], notes  │
└─────────────────────────────────────────────────────────────────────────────────┘
     │
     │ 5. User edits list (reject/add). approvedFolders = suggested − rejected + custom
     │ 6. (Optional) Ask Council
     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  POST /run/stream  mode=council  params={ question, perspective_definitions? }   │
│                    context={ folder_path?, context_block? }                       │
│  → _council_stream_gen → run_council_stream(question, context=context_str, ...)   │
│  → get_council_provider() → N × provider.generate(prompt) [parallel seats]       │
│  → optional synthesis generate(synthesis_prompt)                                  │
│  ← SSE: data: {"chunk":"...","done":false} ... data: {"chunk":"...","done":true}  │
└─────────────────────────────────────────────────────────────────────────────────┘
     │
     │ 7. Run simulation (uses approvedFolders)
     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  POST /run  mode=simulate  params={ folder_path, suggested_folders: approved }  │
│  → _run_simulate → simulate_folder_plan(path, allowed_folders=approved)          │
│  ← proposed_assignments[], simulate_tree, ...                                     │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Folder analysis inputs

**Source:** `tools/file_steward/app.py` → `analyze_folder_structure(folder_path)`.

**What is read from the filesystem:**

- **Immediate children only** of the given folder (single directory listing via `p.iterdir()`).
- **Skip list:** `should_skip_path(item)` (e.g. hidden, system, or configured skip patterns).
- **Caps:** At most `MAX_ANALYZE_ITEMS` (200) children kept for analysis; rest are counted but not analyzed.

**Data extracted:**

| Data | How | Limit |
|------|-----|--------|
| **File / folder counts** | Count of children that are file vs directory. | — |
| **File names** | Used only via tokenization and pattern detection (see below). No raw name list in output. | — |
| **Tokenized words** | `tokenize_name(item.name)` on each child: stem lowercased, regex `[a-zA-Z0-9]+`, length ≥ 3, not in STOP_WORDS. | — |
| **Repeated tokens** | From `detect_local_patterns(children)` → tokens that appear ≥ 2 times. | `MAX_REPEATED_TOKENS` (20) |
| **Repeated years** | Regex `(20\d{2}|19\d{2})` in names, counted; years with count ≥ 2. | `MAX_REPEATED_YEARS` (20) |
| **Extensions** | From `detect_local_patterns` → `ext_counter` (suffix lowercased per file). | `MAX_EXTENSION_BREAKDOWN` (20) most common |
| **Subfolder structure** | Not enumerated; only counts (folder_count). No recursive tree. | — |
| **Context domain** | `infer_context_domain(p)`: path parts + folder name matched against `ALLOWED_DOMAINS`, else `classify_item(folder_path)` (path-based classification). | One value: e.g. CLINIC, UNKNOWN |
| **Suggested child folders (analysis)** | `suggest_schema_children(inferred_context_domain)` (schema) + `build_dynamic_children(patterns)` (years, tokens, extension-based). | `MAX_SUGGESTED_CHILD_FOLDERS` (30) |

**Structure of the analysis object returned to callers:**

```python
{
    "folder_path": str,
    "item_count": int,
    "file_count": int,
    "folder_count": int,
    "repeated_tokens": list[str],
    "repeated_years": list[str],
    "extension_breakdown": dict[str, int],
    "inferred_context_domain": str,
    "suggested_child_folders": list[str],
}
# If truncated:
#   "truncated": True, "total_items_seen": int, "items_analyzed": int
# On error:
#   "error": str
```

This object is **not** passed to the recommend step. Recommend runs independently and re-scans the same folder.

---

## 3. Recommendation generation

**Code:** `tools/file_steward/app.py` → `recommend_child_folders(folder_path)`.

**Mechanism:** **Purely algorithmic** (no LLM in the recommend step).

- Re-scans folder (same caps: `MAX_ANALYZE_ITEMS`).
- `infer_context_domain(root)` → same as analyze.
- `detect_local_patterns(items)` → same token/ext/year counts.
- `suggest_schema_children(context_domain)` → domain-based schema list from `SUBFOLDER_SCHEMAS`.
- `build_dynamic_children(patterns)` → folders from repeated years, repeated tokens, extension-based buckets (e.g. HTML, CSS, Images).
- `discover_themes(items)` → themes from token and bigram prevalence in names; score ≥ 0.15.
- Combined list: `schema_children + dynamic_children + theme_names`, sorted (extension-type folders last), capped at `MAX_SUGGESTED_CHILD_FOLDERS` (30).
- `build_folder_plan(...)` produces a table with suggested_child, source, confidence, exists (used internally / for richer UIs); the API return to the frontend does **not** include this table (see below).

**No model call** in `recommend_child_folders`. No prompt.

**API return shape** (`api/main.py` → `_run_recommend`):

```python
{
    "folder_path": str,
    "inferred_context_domain": str,
    "suggested_child_folders": list[str],
    "notes": list[str],
}
# or { "error": str }
```

So the "Suggested folders" list in the UI is the **algorithmic** `suggested_child_folders` from File Steward.

---

## 4. Council invocation for folder decisions

**Where:** "Ask Council" button in Step 3 (Recommend) sets question and switches to council; user then clicks "Run Council" in the AI agents panel. Alternatively user can type a question and run council from the agents panel.

**Trigger (folder workflow):**  
`frontend/src/App.tsx` (e.g. ~2117):  
`onClick={() => { setFolderPath(lastFolderPath); setActiveMode('council'); setQuestion(`Given these folder options — ${approvedFolders.join(', ') || 'this folder'} — which should I prioritize and why?`); }}`  
Then user clicks "Run Council" → `runCouncil()`.

**Request:**  
`POST /run/stream`  
Body: `{ mode: 'council', params: { question, perspective_definitions? }, context?: { folder_path?, context_block? } }`.

**Backend:**  
`api/main.py` → `_council_stream_gen(params, request.context)`  
- `context_str` = `context["context_block"]` if present, else `"Folder: " + context["folder_path"]` if present, else None.  
- No `recent_tool_summary` or `key_constraints` are sent from the frontend in this flow; they stay None.

**Packet built in:** `local_ai/zenaf_tools.py` → `build_council_decision_packet(question, context=context_str, recent_tool_summary=None, key_constraints=None, subject_ref=..., object_snapshot=...)`.

**Prompt sent to council (per seat):**

- **System:** Either built-in role prompt (e.g. `COUNCIL_STRATEGIST_PROMPT`) or `_build_perspective_system_prompt(defn)` from `perspective_definitions`.
- **Then (built-in path only):** optional `_format_decision_context_block(role_name, 5)` → "Recent decisions relevant to your role (RoleName)." + list (VE decisions, perspective-filtered).
- **Then:** shared **packet** (see below).
- **Then:** **role_limit** (structured output instruction).

**Packet content (folder workflow, typical case):**

- **Context:** From `context_block` sent by frontend. When "Use current result as context" is checked, `buildContextBlock()` returns:
  - `Folder: <lastFolderPath>`
  - If last mode was **recommend:** `Mode: Recommend. Context: <inferred_context_domain>. Suggested folders: <N>.`
  - (No full analysis, no tree, no list of folder names in context — the folder list is in the **question** when user uses the prefilled "Given these folder options — A, B, C — which ...")
- **Question:** User question, e.g. "Given these folder options — Invoices, Reports, Archive — which should I prioritize and why?"
- **Working memory:** Only if API passed `subject_ref`/`object_snapshot` (not used in current folder UI).
- **Recent tool summary:** None (not sent).
- **Constraints:** None.
- **Operator priorities:** Loaded from `context.phil_context.load_operator_priority()` (truncated to 220 chars).

So in practice:

- **Folder analysis summary:** Only a one-line summary in context ("Mode: Recommend. Context: X. Suggested folders: N."). No item_count, repeated_tokens, extension_breakdown, or tree.
- **Tree preview:** Not included in the packet.
- **Suggested folder list:** Not in the context block. It appears in the **question** if the user uses the prefilled question that includes `approvedFolders.join(', ')`.

**Council output:**  
Streamed back as SSE; frontend concatenates chunks. Full text is stored in `lastCouncilResult` and shown in the right-hand AI agents panel via `CouncilText` (which only does light formatting of lines ending with `:` and "Zenaf synthesis:"). No parsing into structured fields for display; the UI treats the response as **free-form text**.

---

## 5. Current output expectations (council)

**Format:** **Structured by instruction, free-form in practice.**

- **Seat instruction (`role_limit`):**  
  "Return your answer in this exact structured format:  
  Position: <proceed | pause | reject | revise>  
  Primary reason: ...  
  Main risk: ...  
  Required guardrail: ...  
  Next step: ...  
  Response:"

- **Synthesis:** Short synthesis with agreement, disagreement, recommended action (from `COUNCIL_SYNTHESIS_PROMPT`).

**UI interpretation:**  
The UI does **not** parse Position / Primary reason / etc. It displays the raw streamed text in the agent panel (and optionally in the thread). So the system *asks* for structure but does not rely on it for layout or behavior; long narrative is therefore possible and is shown in full (up to 2000 chars in one place, full text in state).

---

## 6. Model selection

**Council workflow:** Uses **`get_council_provider()`** only.

- **Where:** `local_ai/zenaf_tools.py` in `run_council` and `run_council_stream`: `from local_ai.providers import get_council_provider` then `provider = get_council_provider()`.
- **Config:** `local_ai/providers/__init__.py` → `get_council_provider()`:
  - If `ZENAF_COUNCIL_MODEL` env is set → `OllamaProvider(model=council_model)`.
  - Else if `local_ai.config.OLLAMA_COUNCIL_MODEL` is set → `OllamaProvider(model=...)`.
  - Else → `get_default_provider()` (default Ollama model).
- **Analyze / Recommend / Simulate (non-LLM path):** No model. If simulate uses an LLM second pass (e.g. `use_llm_second_pass`), that uses `get_default_provider()` inside File Steward (`tools/file_steward/app.py`), not council provider.
- **Override:** The folder workflow does not override model selection; council always uses whatever `get_council_provider()` returns (env or config).

---

## 7. Performance considerations

- **Analyze:** One call, no model; cost is filesystem + in-process pattern/domain logic.
- **Recommend:** One call, no model; same.
- **Council:**
  - **Model calls:** N seat calls in parallel (N = number of selected seats, cap `COUNCIL_MAX_SEATS` e.g. 3) + 1 synthesis call if `do_synthesis` (default when positions disagree). So typically **3 + 1 = 4** calls for default 3 seats with synthesis.
  - **Prompt size:** Packet = Context (≤800 chars) + Question + optional Working memory (≤400) + optional Recent tool summary (≤500) + optional Constraints + Operator priorities (≤220). Per-seat prompt = system prompt (role or perspective) + optional decisions block (built-in only) + packet + role_limit. No conversation history.
  - **Bottlenecks:** Council latency is dominated by the slowest seat and then synthesis; total time ≈ max(seat times) + synthesis time. No multiple council runs in the folder flow unless the user clicks Run Council again.

---

## 8. Opportunities for constraint

To make council in this workflow only suggest parent-folder categories, give brief reasoning, avoid long narrative, and avoid proposing restructuring logic, the **safest place to constrain** is the **shared instruction** that every seat (and optionally synthesis) sees — i.e. the **role_limit** and/or a **folder-specific constraint** added only when the packet is built for this use case.

**Exact file/function:**

- **Primary:** `local_ai/zenaf_tools.py` → **`role_limit`** (the string appended to every seat prompt: "Return your answer in this exact structured format: Position: ... Primary reason: ..."). Tightening that string (e.g. "Keep to 1–2 sentences per field; do not propose new folder structures or renaming.") would apply to all council runs, not just folder.
- **Scoped option:** Add an optional parameter to `build_council_decision_packet` or to `run_council`/`run_council_stream` (e.g. `constrain_to_folder_advice: bool`) and, when True, append a short **Constraints** or **Instructions** block to the packet (e.g. "Limit advice to choosing among the given folder options; one short reason per seat; do not propose new categories or restructuring."). The frontend would need to pass this when invoking council from the folder workflow (e.g. via `context.constrain_to_folder_advice` or a new param). Constraint would then live in **`build_council_decision_packet`** (add a short folder-advice-only block when requested) or in the **packet assembly** in **`run_council`**/`run_council_stream` when building the prompt for the request.

**Summary:**

- **Safest single place** that affects all council runs: **`local_ai/zenaf_tools.py`**, the **`role_limit`** string (around lines 921–931).
- **Safest scoped place** (folder workflow only): **`local_ai/zenaf_tools.py`** — add a folder-specific constraint block when the request is for folder advice (e.g. when context or a flag indicates "folder options" use case), either in **`build_council_decision_packet`** (new param + optional block) or in **`run_council`**/`run_council_stream` when constructing the prompt.

---

## 9. Deliverables summary

| Deliverable | Location / value |
|-------------|------------------|
| **Pipeline diagram** | §1.2 above (ASCII). |
| **Exact prompts (council)** | See §9.1 below. |

### 9.1 Exact council prompt strings

**Packet block order** (`_COUNCIL_PACKET_ORDER`): context → question → working_memory → recent_tool_summary → constraints → operator_priorities.

**Packet contents (from `build_council_decision_packet`):**

- `Context:\n` + context truncated to `MAX_CONTEXT_CHARS` (800)
- `Question:\n` + question
- Optional: `Working memory:\n` + block (capped `MAX_WORKING_MEMORY_CHARS` 400)
- Optional: `Recent tool summary:\n` + truncated to 500
- Optional: `Constraints:\n` + key_constraints
- Optional: `Operator priorities:\n` + truncated to 220

**role_limit** (appended to every seat prompt in `local_ai/zenaf_tools.py`):

```
Return your answer in this exact structured format:

Position: <proceed | pause | reject | revise>
Primary reason: <one sentence explaining your position from your perspective>
Main risk: <one concrete risk you see>
Required guardrail: <one guardrail that must be in place>
Next step: <one practical next step consistent with your mandate>

Response:
```

**COUNCIL_SYNTHESIS_PROMPT** (used for synthesis step):

```
You are Zenaf synthesizing a council discussion. Below are perspectives from the council on the same question.
Do NOT repeat or summarize each role response. Instead, produce a short, structured synthesis with:
- Points of agreement (1–3 bullets)
- Points of disagreement or tension (1–3 bullets)
- Recommended action (2–4 sentences, including the key trade-off and any critical guardrails)
Keep the synthesis concise and decision-ready.
```

**Synthesis prompt template:**  
`{COUNCIL_SYNTHESIS_PROMPT}\n\nQuestion: {q}\n\nSeat summaries:\n{combined}\n\nDecision recommendation:`  
(or with `{combined}` as raw seat output if no summaries). Fallback when no seat output: packet + "As Zenaf (chief of staff / integrator), give one short decision recommendation (2–4 sentences)..."

**Per-seat prompt:**  
`{system}\n\n` + optional `{decisions_block}\n\n` (built-in roles only) + `{packet}{role_limit}`.
| **Model** | **Council:** `get_council_provider()` → `OllamaProvider(model=ZENAF_COUNCIL_MODEL or config.OLLAMA_COUNCIL_MODEL or default)`. Analyze/Recommend: no model. |
| **Analysis object structure** | §2: folder_path, item_count, file_count, folder_count, repeated_tokens, repeated_years, extension_breakdown, inferred_context_domain, suggested_child_folders [, truncated, total_items_seen, items_analyzed ]. |
| **Where folder suggestions are generated** | `tools/file_steward/app.py` → `recommend_child_folders(folder_path)`; returned list = schema + dynamic + themes, capped at 30. API returns it as `suggested_child_folders`. |
| **Where council is invoked** | Frontend: `runCouncil()` → `POST /run/stream` (mode=council). API: `_council_stream_gen`. Backend: `run_council_stream()` in `local_ai/zenaf_tools.py`. |
| **Safest place to constrain council output** | **`local_ai/zenaf_tools.py`** — either (1) tighten **`role_limit`** for all council, or (2) add a folder-only constraint block when building the packet or prompt (new param/flag from frontend so only folder workflow gets the constraint). |
