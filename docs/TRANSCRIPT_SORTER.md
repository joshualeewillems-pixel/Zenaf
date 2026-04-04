## TRANSCRIPT_SORTER – Thin transcript-to-deliverables pipeline

This note defines a thin, reviewable pipeline for turning messy transcripts into structured, execution-ready deliverables that can feed Vision Execution without becoming a second durable core.

- **Transcript** = observation
- **Transcript sorting / extraction** = judgment
- **Confirmed tasks / decisions** = bridge into Vision Execution
- **Completed follow-up** = outcome

The sorter lives alongside Intake as another source of observations and judgments. Vision Execution remains the durable center for tasks, projects, decisions, and outcomes.

---

### 1. Inputs

**Primary input**

- **`raw_transcript_text`** (required)
  - Full text of the meeting/call/conversation.
  - May include line breaks, timestamps, or light markup.

**Optional metadata**

- **`speaker_labels`** (optional)
  - Mapping or per-line annotations such as:
    - `{"line_index": 42, "speaker": "Alice"}` or
    - normalized IDs like `speaker_1`, `speaker_2`.
  - Used for:
    - attributing decisions (“Who decided X?”)
    - assigning candidate task owners.

- **`call_context`** (optional)
  - **`title`** (e.g., “Weekly product sync”)
  - **`date` / `start_time`** (ISO timestamp if available)
  - **`source`** (e.g., `zoom`, `meets`, `phone_recording`, `manual_notes`)
  - **`participants`** (optional list of names/emails if known)

**Intended API shape (conceptual)**

```json
{
  "raw_transcript_text": "string",
  "speaker_labels": [
    {"offset": 0, "length": 120, "speaker": "Alice"},
    {"offset": 121, "length": 300, "speaker": "Bob"}
  ],
  "call_context": {
    "title": "Weekly product sync",
    "date": "2026-03-11T15:00:00Z",
    "source": "zoom",
    "participants": ["Alice", "Bob", "Carol"]
  }
}
```

Implementation can start with only `raw_transcript_text` and a minimal `call_context` (title/date).

---

### 2. Processing stages

The transcript sorter should be a **thin, composable pipeline** of judgment steps. Each stage transforms the previous representation, but the raw transcript remains the source of truth.

#### 2.1 Topic segmentation

- **Goal**: Break the transcript into coherent segments representing distinct topics or agenda items.
- **Behavior**:
  - Detect boundaries based on:
    - topic shift cues (“switching gears”, “next item”, “on another note”),
    - strong changes in vocabulary,
    - long pauses or explicit section headings if available.
  - Produce an ordered list of segments with:
    - character/line offsets into the original transcript,
    - approximate time bounds if timestamps are present.
- **Output (per segment)**:
  - `segment_id`
  - `start_offset`, `end_offset`
  - raw `text_slice`

#### 2.2 Topic labeling

- **Goal**: Assign a short, human-meaningful label to each segment.
- **Behavior**:
  - Use LLM or heuristic summarization to generate:
    - a **short title** (1 line),
    - an optional **1–3 sentence summary**.
  - Emphasize concrete nouns (projects, features, customers, dates) over generic labels.
- **Output (per segment)**:
  - `topic_title`
  - `topic_summary`

#### 2.3 Substantive vs non-substantive filtering

- **Goal**: Filter out segments that are primarily small talk, logistics, or repetitions without new commitments.
- **Behavior**:
  - Mark each segment as:
    - `substantive` (contains decisions, plans, risks, requirements, or follow-ups), or
    - `non_substantive` (greetings, meta-talk, “can you hear me?”, repeated explanations without new commitments).
  - **Do not delete** non-substantive segments; simply flag them, so the transcript structure remains intact.
- **Effect**:
  - Downstream extraction stages focus primarily on `substantive` segments.

#### 2.4 Deliverable extraction

- **Goal**: Identify **explicit deliverables** mentioned in the conversation, regardless of whether they are fully formed tasks.
- **Examples**:
  - “We should send a follow-up email to the client.”
  - “Let’s update the onboarding flow by next week.”
  - “Someone needs to write a migration plan.”
- **Behavior**:
  - For each substantive segment, scan for lines/sentences that describe:
    - actions to be taken,
    - artifacts to be created or updated,
    - decisions to be applied.
  - Produce deliverable items with:
    - reference to the originating segment and text span,
    - natural-language description,
    - optional candidate owner and time frame.

#### 2.5 Open question extraction

- **Goal**: Capture unresolved questions, uncertainties, and explicit “we still need to figure out X” items.
- **Examples**:
  - “We still don’t know if we’re supporting multi-tenant.”
  - “Who is going to own the reporting layer?”
  - “What’s our plan for migration downtime?”
- **Behavior**:
  - Extract questions and unresolved items as **open questions** with:
    - text,
    - topic reference,
    - optional suggested owner to answer.

#### 2.6 Candidate task extraction

- **Goal**: Propose **candidate Vision Execution tasks** from deliverables.
- **Behavior**:
  - For each deliverable, attempt to normalize into a task-like shape:
    - **title** (short verb-first summary),
    - **optional description / notes**,
    - **candidate owner** (if speaker/participant mapping is clear),
    - **related topic / initiative** (if inferrable from context).
  - Mark these as **candidates only**; they are not created in Vision Execution yet.
- **Output (per candidate task)**:
  - `candidate_task_id`
  - `source_segment_id`
  - `source_text`
  - `title`
  - `description` (optional)
  - `suggested_owner` (optional)
  - `confidence` (e.g., low/medium/high)

#### 2.7 Candidate decision extraction

- **Goal**: Extract **candidate decisions** that might be worth recording in Vision Execution.
- **Examples**:
  - “We’re going to deprecate the old API by June.”
  - “We agreed to prioritize the onboarding revamp over the analytics work.”
  - “We decided to switch providers.”
- **Behavior**:
  - Detect statements that:
    - reflect agreement or commitment,
    - change a plan, scope, or policy,
    - set constraints or success criteria.
  - Normalize into a decision-like shape:
    - **summary**,
    - **rationale** (if visible),
    - **participants / approvers**,
    - **effective date** (if present).
- **Output (per candidate decision)**:
  - `candidate_decision_id`
  - `source_segment_id`
  - `source_text`
  - `summary`
  - `rationale` (optional)
  - `suggested_decider` / `participants` (optional)
  - `confidence`

---

### 3. Output shape

A minimal structured output for a transcript could look like:

```json
{
  "transcript_id": "optional-stable-id-or-hash",
  "call_context": {
    "title": "Weekly product sync",
    "date": "2026-03-11T15:00:00Z",
    "source": "zoom",
    "participants": ["Alice", "Bob", "Carol"]
  },
  "topics": [
    {
      "segment_id": "seg_1",
      "start_offset": 0,
      "end_offset": 1024,
      "topic_title": "Onboarding flow issues",
      "topic_summary": "Discussion of drop-off in onboarding and proposed A/B tests.",
      "substantive": true
    }
  ],
  "deliverables": [
    {
      "deliverable_id": "deliv_1",
      "segment_id": "seg_1",
      "source_text": "We should run an A/B test on the signup form.",
      "description": "Run an A/B test on the signup form to improve completion rate.",
      "suggested_owner": "Alice"
    }
  ],
  "open_questions": [
    {
      "question_id": "q_1",
      "segment_id": "seg_1",
      "source_text": "We still don't know whether we should ask for phone number upfront.",
      "description": "Decide whether to ask for phone number on the first signup step.",
      "suggested_owner": "Product"
    }
  ],
  "candidate_tasks": [
    {
      "candidate_task_id": "ct_1",
      "segment_id": "seg_1",
      "source_text": "We should run an A/B test on the signup form.",
      "title": "Run A/B test on signup form",
      "description": "Design and run an A/B test for the signup form to reduce drop-off.",
      "suggested_owner": "Alice",
      "confidence": "high"
    }
  ],
  "candidate_decisions": [
    {
      "candidate_decision_id": "cd_1",
      "segment_id": "seg_2",
      "source_text": "Let's deprecate the old dashboard by the end of the quarter.",
      "summary": "Deprecate old dashboard by end of quarter.",
      "rationale": "Maintaining both dashboards splits engineering focus.",
      "participants": ["Alice", "Bob"],
      "confidence": "medium"
    }
  ]
}
```

Notes:

- IDs can be local to the transcript (e.g. `seg_1`, `ct_1`) and do not need global stability.
- Raw transcript text is kept outside this structure but referenced via offsets; this output is a **judgment snapshot**, not the source of truth.

---

### 4. Bridge behavior into Vision Execution

The bridge from transcript judgments into Vision Execution should follow the same principles as the intake-to-core bridge:

- Vision Execution remains the **durable center** for:
  - tasks, projects, initiatives, decisions, people, assets, etc.
- Transcript sorter is a **judgment layer**:
  - It proposes candidate tasks and decisions.
  - It never becomes a second durable execution system.

#### 4.1 Confirming candidate tasks

- **UI / flow concept**:
  - Show a list/table of `candidate_tasks` for a selected transcript.
  - For each candidate:
    - allow editing of `title`, `description`, `owner`, `project_id` (or initiative),
    - show `segment` context and original `source_text`.
  - User explicitly confirms which items to **promote** to Vision Execution.

- **Bridge behavior (per confirmed task)**:
  - Call the existing Vision Execution task creation path (e.g. via existing storage/API).
  - Include a **provenance note**, similar to the intake-to-core bridge:
    - reference to:
      - `transcript_id`
      - `segment_id`
      - optionally a snippet of `source_text`.
    - e.g. in task notes:
      - `[Atria lifecycle] transcript_id=<id> segment_id=<seg_id>`
  - Optionally create a corresponding Vision Execution **Decision** when a task reflects a concrete decision outcome (same pattern as intake bridge).

#### 4.2 Confirming candidate decisions

- **UI / flow concept**:
  - Show `candidate_decisions` with summaries and context.
  - Allow user to:
    - refine `summary`,
    - add `rationale`,
    - link to existing initiatives/projects/tasks.

- **Bridge behavior (per confirmed decision)**:
  - Create a Vision Execution **Decision** entity with:
    - summary, rationale, participants.
    - **provenance** back to the transcript:
      - `[Atria lifecycle] transcript_id=<id> segment_id=<seg_id>`
  - If the decision implies follow-up work, the operator can manually create linked tasks using the normal Vision Execution paths.

#### 4.3 Lifecycle alignment

- **Observation**: transcript (raw text + call_context).
- **Judgment**: structured transcript sorter output (topics, candidates).
- **Decision / Task**: confirmed items bridged into Vision Execution.
- **Outcome**:
  - Derived from the state of VE tasks/decisions (completed vs not),
  - Or explicit outcome assessments later (e.g. “meeting follow-ups completed successfully”).

No new lifecycle table is required initially; provenance is stored in notes/metadata consistent with existing patterns.

---

### 5. Scope constraints

To keep the transcript sorter thin and reviewable:

- **No live call recording**:
  - Assume transcripts are provided by external systems (Zoom, Meet, manual copy-paste).
  - Do not implement recording or transcription infrastructure.

- **No full meeting assistant**:
  - Focus on **sorting and extracting deliverables**, not on live facilitation or scheduling.

- **No auto-created tasks/decisions**:
  - All tasks and decisions require explicit **human confirmation** before entering Vision Execution.

- **No second durable store**:
  - Do not invent a full “meeting DB” with its own lifecycle.
  - Store transcripts as Tier B/C data and judgments as **derived artifacts** that can be regenerated.

- **Thin, explainable prompts**:
  - Prompt shapes and judgment steps should be small and inspectable, not opaque mega-prompts.

---

### 6. First implementation recommendation

The smallest real implementation path should look like:

**Step 1 – Paste/upload transcript**

- Add a simple UI (or API) surface to:
  - paste a transcript into a text area, or
  - upload a `.txt` file.
- Capture minimal `call_context` (title + date/time).

**Step 2 – Run transcript sorter (judgment only)**

- Implement a backend function (e.g. `local_ai.transcripts.sort_transcript(...)`) that:
  - performs:
    - topic segmentation,
    - topic labeling,
    - substantive vs non-substantive classification,
    - deliverable / open question / candidate task / candidate decision extraction,
  - returns a **single structured JSON object** as described in section 3.
- Use existing LLM provider abstractions; no new providers or infra.

**Step 3 – Review extracted deliverables**

- Frontend:
  - show:
    - topics as a left-hand list or timeline,
    - candidate tasks and decisions grouped by topic,
    - open questions as a separate section.
  - allow:
    - quick editing of titles/descriptions,
    - simple checkboxes or buttons: “Promote to task”, “Promote to decision”, “Ignore”.

**Step 4 – Create tasks/decisions manually from confirmed items**

- Use existing Vision Execution APIs/bridges:
  - For each confirmed item:
    - create VE Task or Decision,
    - include transcript provenance notes.
  - No new lifecycle persistence required at this stage.

**Step 5 – Iterate lightly**

- Once this basic loop is working:
  - refine extraction heuristics based on real meetings,
  - add small conveniences (e.g. default owners from speaker labels, default project from call title),
  - keep the sorter a **judgment tool** feeding the same core VE entities rather than growing its own execution layer.

