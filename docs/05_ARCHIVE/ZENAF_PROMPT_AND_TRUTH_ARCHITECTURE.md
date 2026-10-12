# Zenaf: Information Flow and Truth-Source Architecture

**Status:** Reference (updated: council enriched context, PRIMARY/secondary split, object-first seat prompts vs synthesis packet).  
**Purpose:** Describe how information flows through Zenaf, how context sources influence model prompts, and where truth/authority is applied.

---

## 1. Short architecture description

Zenaf routes user requests through several distinct **prompt paths**: council (multi-seat + synthesis), cockpit agent, next-step recommender, content generation, initiative evaluation, and meeting extract. (A legacy **Idea Lab** prompt stack existed; it was removed — use **Vision Execution** ideas instead.) Each path **assembles a prompt** from a fixed **system/role block** plus **context blocks** drawn from different **truth sources** (task context, optional operator priorities brief, VE decisions, conversation history, tool outputs, etc.). There is **no single shared prompt builder**; each module constructs its own prompt. **Structured memory** (NodeSnapshot, SubjectRef, JudgmentSnapshot, CouncilRunArtifact) is used for **attribution and storage** but is **not yet injected as text** into any prompt. **Optional operator priorities** (from `phil_brand_brief.md` when present and not disabled — see `ZENAF_OPERATOR_BRIEF_ENABLED` in `local_ai/context/phil_context.py`) are injected into council runs as preference text, separate from the built-in **Brand** seat persona (mission/narrative lens; generic wording in `BUILT_IN_PERSONA_DEFINITIONS`). Operator priorities are not used in the cockpit, next-step, or most tool-based flows. The **effective authority hierarchy** varies by path: in council, **enriched context** plus **object-first per-seat assembly** (see §1c) and (for built-in roles) recent VE decisions dominate; **synthesis** uses a **different** monolithic packet shape (see §1c). In the cockpit, SYSTEM_PROMPT plus conversation history (including truncated tool outputs) dominate.

---

## 1b. Council: two prompt shapes (overview)

Council is **not** one universal “packet” for all model calls:

1. **Enriched context string** — Built by `build_enriched_council_context()` in `local_ai/council_preflight.py` from `council_preflight` + optional `subject_ref` / `object_snapshot` (API). This is the single substrate before splitting (§1c).
2. **Per-seat user prompt** — Assembled by `_assemble_council_seat_prompt()` + `build_council_secondary_packet()` in `local_ai/zenaf_tools.py`: **PRIMARY** (when present) is promoted ahead of the rest; persona and shared seat rules sit **between** Question and the trailing “secondary” material (§1c).
3. **Synthesis model prompt** — **Normal path:** instruction block + `COUNCIL_SYNTHESIS_PROMPT` + **Question** + verbatim **seat outputs** (no full `Context packet` in the body). **Fallback** (no seat text): same shell but embeds **`Context packet:`** + the string from `build_council_decision_packet()` (full enriched context under `Context:`, then Question, working memory, tool summary, constraints, operator priorities). The monolithic packet is **always built** for artifacts/debug either way. **PRIMARY is still nested inside `Context:` in that packet**, which **differs** from seats’ top-level PRIMARY (§1c).

**Operational contract for `build_council_decision_packet()`** (see `_COUNCIL_PACKET_ORDER` in `zenaf_tools.py`) — applies to **synthesis / artifact packet**, not verbatim to each seat’s composed prompt:

1. **Task** — `Context:` (entire enriched context, truncated), then `Question:`.
2. **Working memory** — From `subject_ref` / `object_snapshot` when present.
3. **System facts** — Recent tool summary.
4. **Hard bounds** — Constraints.
5. **Preference** — Operator priorities (short block from `phil_brand_brief.md` when enabled; omit entirely if `ZENAF_OPERATOR_BRIEF_ENABLED` is `0` / `false` / `no` / `off`).

Philosophical orientation is **not** in the default council packet or synthesis. Operator priorities appear **only in council** when loaded (in the secondary tail for seats, and in this monolithic packet for synthesis); not in cockpit, next-step, content, initiative eval, or meeting extract.

---

## 1c. Council assembly detail (enriched context, seats, synthesis)

**Enriched context order** (`build_enriched_council_context`) — one string passed as council `context` into `run_council` / `run_council_stream` after API resolution (`_resolve_council_context` in `api/main.py`):

1. **PRIMARY CONTEXT (authoritative)** *or* **CONTEXT NOTE (non-authoritative)** — When Vision & Execution (or similar) supplies focus; vague questions without grounding may omit authoritative PRIMARY and use the legitimacy note instead (`should_treat_primary_as_authoritative`).
2. **Runtime context (from app)** — Surface, breadcrumb, topic, workspace mode, topic summary, folder, optional subject line / object snapshot one-liners.
3. **Workflow / thread** — `context_block` / folder line from the request (merged from `council_preflight.raw_context_block`).

Inside **PRIMARY**, field order follows `_format_ve_focus_block` (e.g. Type, Title, Initiative, Status, Brief, Expanded, Owner, then Reference including navigation ids). The display type **`vision_execution_selection`** is used when lineage/type is inferred from selection only (no `entity_type` on focus).

**PRIMARY vs secondary split for seats** (`split_enriched_council_context_for_seats` in `council_preflight.py`):

- **PRIMARY block** — The substring starting at `PRIMARY CONTEXT (authoritative):` through the line before `\n\nRuntime context (from app):` when that marker exists; otherwise the whole enriched string may remain “secondary-only” (no split primary).
- **Secondary** — Everything after that boundary (runtime + workflow), plus any prefix before PRIMARY (e.g. rare leading material) re-attached to the secondary side for seats.

**Actual per-seat block order** (`_assemble_council_seat_prompt` — object-first; perspective and built-in paths both use this shell; built-in adds `decisions_block` inside block **E**):

| Step | Block | Contents (summary) |
|------|--------|----------------------|
| **A** | PRIMARY (optional) | Authoritative VE/object block only, when split found |
| **B** | Question | User question |
| **C** | Persona | Built-in persona dict or perspective definition block (`_build_council_persona_block`) |
| **D** | Shared seat constraints | System instruction layer + grounding rules + role limit / clarify template (`_compose_council_seat_shared_constraints`) |
| **E** | Tail | Optional **recent VE decisions** (built-in seats only, first inside E), then **`secondary_tail`** from `build_council_secondary_packet` |

**`secondary_tail` order** (`build_council_secondary_packet`):

1. **Secondary context (runtime / thread / workflow)** — Truncated remainder from the split (labeled).
2. **Working memory** — Built from `subject_ref` / `object_snapshot` (`_build_working_memory_block`).
3. **Recent tool summary**
4. **Constraints**
5. **Operator priorities**

So **working memory** is **not** immediately after Question on the seat path; it appears **after** persona and shared constraints, and **after** the labeled secondary context slice, but **before** tool summary, constraints, and operator priorities inside the tail.

**Synthesis vs seats:** Seat prompts **lift** PRIMARY to the top (object-first). The **`packet`** from `build_council_decision_packet` keeps PRIMARY **inside** the `Context:` section; that packet is injected into the **synthesis** prompt only on the **no-seat-text fallback** path (`_run_council_synthesis` in `zenaf_tools.py`). **Typical synthesis** relies on **Question + verbatim seat chunks**, so the synthesizer does not re-read the full enriched context unless fallback triggers — but the **artifact / debug packet shape** still differs from the **per-seat** layout.

**Seat order vs UI:** The API runs seats in **`perspective_definitions` / `included_roles` order**; the client builds that list from **left-to-right seat slots**. Streaming emits chunks in **seat index order**; post-processing **does not reorder** seats. **Any historical “order mismatch” between documented packet vs reality is not from seat execution order vs UI — those are aligned.**

---

## 2. Flow diagram (text)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER / FRONTEND / API                               │
└─────────────────────────────────────────────────────────────────────────────┘
     │                    │                    │                    │
     ▼                    ▼                    ▼                    ▼
┌──────────┐      ┌──────────────┐     ┌─────────────┐     ┌─────────────────┐
│ Council  │      │ Cockpit      │     │ Next-step   │     │ Tool-based      │
│ (run_    │      │ (zenaf.py    │     │ (suggest_   │     │ (content,       │
│ council  │      │ main loop)   │     │ next_step)  │     │ initiative_eval,│
│ _stream) │      │              │     │             │     │ meeting_extract,│
└────┬─────┘      └──────┬───────┘     └──────┬──────┘     │                 │
     │                   │                    │            └────────┬────────┘
     │                   │                    │                     │
     ▼                   ▼                    ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PROMPT ASSEMBLY (per path)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Council seat:   object-first user prompt: PRIMARY → Question → persona →     │
│                 shared constraints → [decisions if built-in] + secondary_    │
│                 tail (runtime slice, WM, tools, constraints, op priorities)  │
│ Council synth: COUNCIL_SYNTHESIS_PROMPT + Question + Context packet from     │
│                 build_council_decision_packet(...) + seat summaries/chunks   │
│ Cockpit:        SYSTEM_PROMPT + "\n\n" + conversation_history + "\nZenaf:"   │
│ Next-step:      NEXT_STEP_PROMPT + Context + Question + "Response:"          │
│ Content:        CONTENT_SCRIPT/NEWSLETTER_PROMPT + brief + source + "Output"  │
│ Initiative:     EVALUATE_PROMPT.format(title, brief, core_profile) + "JSON:"  │
│ Meeting:        EXTRACT_PROMPT.format(notes) + "JSON:"                        │
│ (removed)       Idea Lab stack deleted — VE ideas / evaluate paths replace it │
└─────────────────────────────────────────────────────────────────────────────┘
     │                   │                    │                     │
     ▼                   ▼                    ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CONTEXT / TRUTH SOURCES                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Immediate task (question, context_block, folder_path, brief, notes)       │
│ • Operator priorities (phil_brand_brief.md → council packet only; short)    │
│ • Seat mandates & perspective definitions (council seat system prompts)      │
│ • Recent VE decisions (built-in council path only; per-role filtered)         │
│ • Conversation history (cockpit only; includes formatted tool results)      │
│ • Tool outputs (cockpit only, via history; File Steward, web, council)      │
│ • Core profile summary (initiative_evaluate only, optional)                  │
│ • Model prior (implicit in all paths)                                        │
│ • SubjectRef/object_snapshot: in context_ref for artifacts only, NOT in prompt│
│ • NodeSnapshot, JudgmentSnapshot, CouncilRunArtifact: stored, NOT in prompts │
└─────────────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PROVIDER (get_default_provider() or get_council_provider()) → generate()    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Prompt assembly paths (A)

For each model call: **file/function**, **inputs**, **context blocks injected**, **system prompt**.

| Model call | File / function | Inputs | Context blocks injected | System / role prompt |
|------------|-----------------|--------|-------------------------|----------------------|
| **Council seat (built-in)** | `local_ai/zenaf_tools.py` → `run_council` / `run_council_stream` | question, enriched `context` string, recent_tool_summary, key_constraints, included_roles | **Not** the monolithic `build_council_decision_packet` layout. **Per-seat user prompt** (§1c): PRIMARY (if split) → Question → persona → shared constraints → optional `_format_decision_context_block` inside tail → `build_council_secondary_packet` (runtime/thread slice, working memory, tool summary, constraints, operator priorities). | Persona from built-in dict + same shared constraint / role_limit stack as perspective path (instruction layer wraps role rules). |
| **Council seat (perspective)** | Same | question, enriched `context`, recent_tool_summary, key_constraints, perspective_definitions | Same **object-first** seat assembly as built-in (§1c); **no** VE decisions block in tail. Persona from `_build_council_persona_block(defn)` (definition fields + mandate). | Shared seat constraints + role_limit / clarify template (`_compose_council_seat_shared_constraints`); not a separate legacy “system” file per provider in this table. |
| **Council synthesis** | Same | question, seat chunks; `packet` from `build_council_decision_packet` for fallback | **Usual:** instruction guards + `COUNCIL_SYNTHESIS_PROMPT` + Question + `--- Council seat outputs (verbatim) ---` + combined seat text. **Fallback (empty seats):** same + `Context packet:` + monolithic packet (PRIMARY nested under `Context:`). See §1c. | `COUNCIL_SYNTHESIS_PROMPT` + instruction block; no operator priorities block in the usual synthesis body. |
| **Cockpit agent** | `local_ai/zenaf.py` → `main()` → `ask_model(full_prompt)` | User message; conversation_history (list of strings) | Conversation history: alternating "User: …" and tool-result strings (from `_format_history_*` for each tool). Truncation per tool (e.g. 5000 chars generic, 1200 web). Last `MAX_HISTORY_ENTRIES` (20) entries. | `SYSTEM_PROMPT`: Zenaf heart-centered visionary; when to call tools; tool list; when to answer normally; "only report what the tools returned." |
| **suggest_next_step** | `local_ai/zenaf_tools.py` → `suggest_next_step(context, question)` | context (str), question (str) | Context block ("Context:\n" + ctx); optional "Question / goal:\n" + q. | `NEXT_STEP_PROMPT`: executive-function assistant; structured response (Recommendation, Rationale, Alternatives, Caution). |
| **Content generation** | `local_ai/zenaf_tools.py` → `generate_content(brief, source_text, output_type)` | brief (dict), source_text (str), output_type ("script" \| "newsletter") | "--- Content brief ---" (brief fields); "--- Source materials ---" (source_text). | `CONTENT_SCRIPT_PROMPT` or `CONTENT_NEWSLETTER_PROMPT`: content writer; match tone/audience; output only script/newsletter. |
| **Initiative evaluation** | `local_ai/vision_execution/initiative_evaluate.py` → `evaluate_initiative(title, brief, core_profile_summary)` | title, brief, core_profile_summary (optional) | "Initiative: Title: … Brief: …"; optional "Core profile context:\n" + core_profile_summary. | `EVALUATE_PROMPT`: initiative evaluator; output JSON (estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai, recommendation). |
| **Meeting extract** | `local_ai/vision_execution/meeting_extract.py` → `extract_meeting(notes)` | notes (str) | "Meeting notes:\n---\n{notes}\n---". Notes truncated to 12000 chars. | `EXTRACT_PROMPT`: intake assistant; definitions (Idea, Initiative, Task); rules; JSON output format. |

---

## 4. Truth sources used by each path (B)

| Truth source | Council seat | Council synthesis | Cockpit | Next-step | Content | Initiative eval | Meeting extract |
|--------------|-------------|-------------------|---------|-----------|---------|-----------------|-----------------|
| Immediate question/task context | ✓ (seat prompt + enriched context) | ✓ (question + synthesis `Context` packet) | ✓ (user msgs in history) | ✓ (context, question) | ✓ (brief, source) | ✓ (title, brief) | ✓ (notes) |
| Folder / workspace context | ✓ (enriched + secondary tail) | ✓ (inside synthesis `Context:`) | ✓ (via tool results in history) | ✓ (if in context str) | — | — | — |
| Operator priorities / brand brief | ✓ (end of `secondary_tail` for seats) | ✓ (end of synthesis packet) | — | — | — | — | — |
| Seat mandates / perspective definitions | ✓ (persona block in seat prompt) | — | — | — | — | — | — |
| Recent VE decisions | ✓ (built-in only; first segment inside tail block E) | — | — | — | — | — | — |
| Conversation history | — | — | ✓ (last 20 entries) | — | — | — | — |
| Tool outputs | — | — | ✓ (formatted in history) | — | — | — | — |
| Content brief | — | — | — | — | ✓ | — | — |
| Meeting notes | — | — | — | — | — | — | ✓ |
| Core profile summary | — | — | — | — | — | ✓ (optional) | — |
| Model prior knowledge | implicit | implicit | implicit | implicit | implicit | implicit | implicit |

**Not injected in any path:** NodeSnapshot, SubjectRef as a raw serialized blob in isolation, JudgmentSnapshot, CouncilRunArtifact, shared artifact store. SubjectRef/object_snapshot are stored in context_ref and artifacts; they also feed **working memory** and enriched-context one-liners where implemented — they are not the same as “full packet text” in the old table sense.

**Seat / UI ordering:** Council **seat execution order** matches **client seat slot order** and streamed chunk order (§1c). Mismatches with documentation are about **block layout** (PRIMARY split, tail, synthesis packet), not seat index shuffling.

---

## 5. Authority hierarchy — current behavior (C)

**Council (each seat)** — **object-first user prompt** (see §1c), not the monolithic `build_council_decision_packet` layout.

1. **PRIMARY CONTEXT** (when split from enriched context) — authoritative VE / object ground truth when present; otherwise CONTEXT NOTE or absent.  
2. **Question** — User task.  
3. **Persona** — Role/mandate content (`_build_council_persona_block`).  
4. **Shared instruction + role rules** — Pipeline / grounding / `COUNCIL_SEAT_ROLE_LIMIT` or clarify template (`_compose_council_seat_shared_constraints`).  
5. **Tail (block E)** — Built-in: optional **recent VE decisions** first, then **`secondary_tail`**: labeled runtime/thread slice → **working memory** → recent tool summary → constraints → **operator priorities** (last in tail).  

**Effective dominance:** PRIMARY (when authoritative) is read before persona and before preference; operator priorities remain **preference** and appear **last inside the secondary tail**, after working memory and tool summary.

**Council synthesis**  
1. Instruction / guard block + `COUNCIL_SYNTHESIS_PROMPT`.  
2. **Question.**  
3. **Verbatim seat outputs** (normal path).  
4. **Fallback only:** `Context packet:` + output of `build_council_decision_packet` (PRIMARY nested inside `Context:`).  

No operator-priorities line in the usual synthesis body; grounding checks still use enriched `context` string separately. **Shape mismatch:** seats are object-first; monolithic packet (when used) nests PRIMARY under `Context:`.

**Cockpit**  
1. SYSTEM_PROMPT (tool-use rules, "heart-centered visionary").  
2. Conversation history (user + tool results).  
No operator priorities, no council packet, no VE decisions. Tool results dominate what the model "knows" about the current state.

**Next-step**  
1. NEXT_STEP_PROMPT (executive-function assistant).  
2. Context string (from API: context_block or folder).  
3. Optional question.  
No operator priorities, no history, no VE.

**Content / Initiative eval / Meeting**  
Each is dominated by its **immediate inputs** (brief+source, title+brief+core_profile, notes) and its **inline system instruction**. No shared operator profile or memory.

**Summary:** Operator priorities **only** affect council (last in **secondary tail** for seats; last in **monolithic packet** for synthesis), labeled "Operator priorities:". They do not affect cockpit, next-step, content, initiative eval, or meeting extract.

---

## 6. Context injection map (D)

```
Enriched context (preflight + API) — build_enriched_council_context
    -> PRIMARY or CONTEXT NOTE
    -> Runtime context (from app)
    -> Workflow / thread (context_block)

Council seat call (built-in path) — run_council / run_council_stream
    -> split_enriched_council_context_for_seats -> primary_block, secondary_enriched
    -> _assemble_council_seat_prompt:
        -> A: PRIMARY CONTEXT (if any)
        -> B: Question: <q>
        -> C: persona_block (built-in persona dict)
        -> D: shared_constraints (instruction layer + role_limit / clarify)
        -> E: decisions_block (_format_decision_context_block) [optional]
           + build_council_secondary_packet(secondary_enriched, ...):
                Secondary context (runtime / thread / workflow) <trunc>
                Working memory (subject_ref / object_snapshot)
                Recent tool summary
                Constraints
                Operator priorities

Council seat call (perspective path)
    -> same A–D shell as built-in
    -> E: no decisions_block; same build_council_secondary_packet tail

Council synthesis (_run_council_synthesis)
    -> instruction block + COUNCIL_SYNTHESIS_PROMPT
    -> Question: <q>
    -> --- Council seat outputs (verbatim) --- + combined seat chunks   [normal]
    OR -> Context packet: + build_council_decision_packet(...)            [fallback, no seat text]
            -> Context: <full enriched, trunc; PRIMARY inside here>
            -> Question, working memory, tool summary, constraints, operator priorities

Cockpit agent
    -> SYSTEM_PROMPT
    -> conversation_history (last MAX_HISTORY_ENTRIES)
        -> "User: …" / "Tool used: … \n Result: …" (or compact format per tool)
    -> "Zenaf:"

suggest_next_step
    -> NEXT_STEP_PROMPT
    -> Context: <ctx>
    -> Question / goal: <q> (if provided)
    -> "Response:"

Content generation
    -> CONTENT_SCRIPT_PROMPT or CONTENT_NEWSLETTER_PROMPT
    -> --- Content brief --- <brief_str>
    -> --- Source materials --- <source_str>
    -> --- Output (script|newsletter) ---

Initiative evaluation
    -> EVALUATE_PROMPT (with title, brief, fcore placeholder)
    -> Initiative: Title: … Brief: …
    -> Core profile context: … (if core_profile_summary)
    -> JSON:

Meeting extract
    -> EXTRACT_PROMPT
    -> Meeting notes: --- notes ---
    -> JSON:

```

---

## 7. User identity / operator profile (E)

**Where optional operator-specific preference text can appear:**

- **Operator priorities:** Loaded from `local_ai/context/phil_brand_brief.md` via `load_operator_priority()` (sections tried: "Operator priority", "Priority profile", "Council context"), truncated when appended, and injected into council runs as "Operator priorities:" — **last** inside each seat’s **`secondary_tail`**, and **last** in the **synthesis** `build_council_decision_packet` chain when present. Disabled without reading the file when `ZENAF_OPERATOR_BRIEF_ENABLED` is `0`, `false`, `no`, or `off` (see `local_ai/context/phil_context.py`). Not used in cockpit, next-step, content, initiative eval, or meeting extract.
- **Brand perspective (built-in):** Assembled from `BUILT_IN_PERSONA_DEFINITIONS["brand"]` in `local_ai/zenaf_tools.py` (and mirrored in the frontend perspectives catalog). Copy is **generic** (mission, narrative, clarity); it does **not** name a specific operator. Editable per-workspace perspective JSON can further specialize the Brand lens in council.
- **No other global user profile signals** in the codebase for prompt construction. Core profile summary in initiative_evaluate is **initiative/owner context**, not a global operator profile.

**Strength of influence:** Council is the path where optional operator priorities appear. That block is **preference, not task truth**. Built-in Brand is one council **role lens** among others; operator priorities are a separate trailing block shared across seats.

---

## 8. Memory integration (F)

**Structured artifacts that exist but are not injected into prompts:**

| Artifact | Where it exists | Used for reasoning? | Used for storage/attribution? |
|----------|-----------------|---------------------|-------------------------------|
| **SubjectRef** | Passed into run_council/run_council_stream as subject_ref; normalized and stored in context_ref and in CouncilRunArtifact.seat_judgments[].subject | No — not added to packet or prompt text | Yes — attached to SeatJudgment and CouncilRunArtifact |
| **object_snapshot** | Passed as dict into run_council; stored in context_ref["object_snapshot"] | No — not serialized into prompt | Yes — in context_ref for artifact |
| **JudgmentSnapshot** | Base type for SeatJudgment | N/A (output of council) | SeatJudgment instances stored in CouncilRunArtifact |
| **SeatJudgment** | Produced by _parse_seat_chunk_to_judgment; collected in CouncilRunArtifact.seats | Only **indirectly**: synthesis reads seat **output text** (chunks/summaries), not the structured SeatJudgment objects | Yes — in CouncilRunArtifact |
| **CouncilRunArtifact** | Built at end of run_council when return_artifact=True | No — not fed back into any prompt | Yes — returned to caller; can be stored in VE decision ai_proposal_snapshot |
| **NodeSnapshot** | `node_substrate` type only; ~~entity→NodeSnapshot via `node_adapters`~~ **retired (tombstoned)** | No — no prompt builder reads NodeSnapshot | Prefer **SubjectRef** at seams; `node_ref_to_subject_ref` bridges NodeRef→SubjectRef when needed |
| **Shared artifact store** | Planned (docs/SHARED_ARTIFACT_MEMORY_PLAN.md); not implemented | No | N/A |

**Conclusion:** All of these are used for **attribution, storage, and future use**. None are currently rendered as text into any model prompt. The only "memory" that reaches prompts is (1) **recent VE decisions** (council built-in path only) and (2) **conversation history** in the cockpit (tool outputs + user messages).

---

## 9. Risks and imbalances (G)

- **Operator priorities as framing:** Addressed by refinement: for **seats**, operator priorities are last inside **`secondary_tail`** (after secondary context, working memory, tool summary, constraints); for **synthesis packet** (fallback), last in `build_council_decision_packet`. Label remains "Operator priorities:" (see PHIL_CONTEXT_REFINEMENT_PLAN.md). Philosophical orientation remains out of default council.
- **Role prompt length:** Perspective-based seat prompts from _build_perspective_system_prompt can be long (name, role, purpose, values, decisionRule, tone, full mandate). Combined with packet + role_limit, total prompt size can encourage role bleed or verbosity.
- **Memory artifacts underutilized:** SubjectRef, object_snapshot, NodeSnapshot, CouncilRunArtifact, and (when added) shared artifacts are not used as prompt inputs. Council and next-step do not "see" past judgments or decisions except via the narrow recent-VE-decision block (council only). *(Experimental `node_adapters` / `subject_adapters` layers were retired; universal identity/judgment primitive is **SubjectRef** + **JudgmentTrunk** in `judgment_substrate.py`.)*
- **No shared operator profile outside council:** Cockpit, next-step, content, and initiative eval do not receive any operator-preference or mission context. If we want consistent "Phil alignment" across flows, we would need to add a controlled injection point (and likely a short "operator priority" block rather than full philosophy).
- **Duplicate assembly patterns:** Prompt construction is spread across zenaf_tools, zenaf.py, initiative_evaluate, meeting_extract, idea_evaluate, core profile modules, etc. There is no shared abstraction for "add context block" or "truth source order," so consistency and future changes (e.g. adding a shared artifact block) require edits in multiple places.
- **Cockpit history as only tool truth:** The cockpit relies entirely on formatted tool results in conversation history. There is no separate "current state" or "last council result" structure; if history is truncated or reordered, the model can lose track of what tools returned.
- **Synthesis has no operator priorities or decisions:** Synthesis prompt is deliberately minimal (question + seat summaries). It does not receive operator priorities or recent VE decisions, so the synthesizer has no explicit operator-preference or decision-history signal—only what seats said.

---

## 10. Suggested areas for future cleanup (do not implement yet)

1. **Operator-priority refinement** — Done: council uses short "Operator priorities:" block, last in packet; philosophical orientation is separate and not in default council (see PHIL_CONTEXT_REFINEMENT_PLAN.md).
2. **Define a single truth-source hierarchy** (e.g. task > system facts > seat mandate > memory artifacts > orientation) and document it in one place; then align each prompt path to that hierarchy so that (a) operator priority is clearly preference, and (b) future memory injection has a defined slot.
3. **Introduce optional memory injection:** When shared artifact store exists, add an optional "Recent judgments/decisions" (or similar) block to council packet and/or next-step context, with a small cap and clear provenance.
4. **Consider a thin prompt-assembly layer** (e.g. "context blocks" with named sources and a max length per source) so new truth sources can be added in one place and reused across council, next-step, and optionally cockpit.
5. **Use SubjectRef/object_snapshot in the packet when provided:** If the API passes subject_ref or object_snapshot, optionally add a one-line or short "Object under consideration: …" to the packet so seats explicitly see what they are judging.
6. **Cap or structure perspective system prompts** to avoid bloat: e.g. mandate in one line, values as a short list, so total seat prompt size stays bounded and role bleed is reduced.
7. **Review synthesis inputs:** Decide whether synthesis should receive (a) an optional one-line operator-priority or mission hint, and (b) no VE decisions, or a minimal "last N decision titles" for continuity; implement only after the hierarchy is agreed.

This document should be updated when new prompt paths or truth sources are added, or when the authority hierarchy or Phil-context refinement is implemented.
