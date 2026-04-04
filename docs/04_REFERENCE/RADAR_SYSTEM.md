# Radar System — Design Note

**Status:** Design  
**Scope:** Generalize Radar into a shared cross-system signal layer that aggregates attention signals from multiple modules while keeping the current Vision Execution radar behavior intact.  
**Goal:** Make Radar the nervous system of Atria in a clean, elegant, minimally imposing way — one system, multiple emitters, multiple views.

---

## 1. Core framing

Radar should be a **shared system service**, not a collection of separate per-module dashboards.

**Flow:**

```
modules → emit radar signals → radar aggregates → radar views
```

- **Modules** (Vision Execution, transcript sorter, Content, inbox cleanup, council, etc.) **emit** standardized radar signals when something deserves attention.
- **Radar** **aggregates** those signals (filter, sort, optionally persist) and exposes them to views.
- **Radar views** consume the aggregated stream. The current Vision Execution radar tab is the **first concrete view** — deterministic buckets (act_now, blocked, overcapacity, unanchored, high_value_stalled, kill_candidates) — and must remain working. Future views (e.g. a cross-system “Signals” view) sit on top of the same signal layer.

**Principles:**

- **One Radar, many emitters.** We do not create many separate radar dashboards per module. We create one Radar system with multiple module emitters.
- **Current VE radar is preserved.** The existing VE radar logic and UI are treated as the first view over the signal layer, not discarded. Migration is incremental: introduce the abstraction, map VE to it, then add other emitters and views.
- **Thin first step.** No heavy event bus, no ML, no overbuilt persistence. Start with a minimal signal schema and a single aggregation path that still serves the current VE view.

---

## 2. RadarSignal schema

A **radar signal** is a minimal, immutable-ish event that describes “something that needs attention.” Modules emit these; Radar aggregates and serves them to views.

**Minimal signal object:**

| Field | Type | Purpose |
|-------|------|---------|
| **id** | string | Unique identifier for this signal (e.g. UUID or `{source_module}:{entity_type}:{entity_id}:{signal_type}`). Enables deduplication and resolution tracking. |
| **source_module** | string | Which module emitted this (e.g. `vision_execution`, `transcript_sorter`, `content`, `inbox_cleanup`, `council`). |
| **signal_type** | string | Module-specific subtype (e.g. `act_now`, `blocked`, `overcapacity`, `unanchored`, `high_value_stalled`, `kill_candidate` for VE; `handoff_gap` for content). Allows filtering and grouping. |
| **attention_class** | string | **Cross-module category** for the kind of attention. Enables grouping and prioritization across sources. See suggested values below. |
| **entity_type** | string | What kind of thing this is (e.g. `initiative`, `project`, `task`, `person`, `brief`, `thread`, `intake_item`). |
| **entity_id** | string | Id of the entity in the source system (e.g. initiative id, project id). |
| **title** | string | Short human-readable label (e.g. initiative title, project name). |
| **summary** | string? | Optional one-line context or reason. |
| **severity** | string? | Optional: e.g. `low`, `medium`, `high`, `critical`. For ordering and filtering. |
| **confidence** | number? | Optional 0–1 or 0–100. For ML-derived or heuristic signals; deterministic emitters can omit or use 1.0. |
| **created_at** | string (ISO datetime) | When the signal was emitted. |
| **resolution_state** | string | **Lifecycle of the signal:** `open`, `acknowledged`, `resolved`, `dismissed`. Enables tracking what’s been looked at vs. still pending. |

**Required for every signal:** `id`, `source_module`, `signal_type`, `attention_class`, `entity_type`, `entity_id`, `title`, `created_at`, `resolution_state`. Others are optional.

**Suggested `attention_class` values (canonical set):**

| attention_class | Meaning | Example |
|-----------------|---------|--------|
| **risk** | Something could go wrong or is deteriorating. | Initiative score dropped; compliance gap. |
| **opportunity** | Something high-value that could be advanced. | High-score initiative still in Draft. |
| **blocker** | Progress is blocked. | Project/task status Blocked; missing dependency. |
| **drift** | Alignment or scope drift. | Project unanchored from initiative; brand drift. |
| **handoff_gap** | Handoff or follow-up missing. | Brief generated but no VE task created; email triaged but not assigned. |
| **capacity** | Resource or capacity issue. | Person over capacity; queue backing up. |
| **noise_pattern** | Pattern worth reviewing (e.g. many similar decisions). | Many dismissals in transcript sorter; repeated intake corrections. |

**Suggested `resolution_state` values:**

| resolution_state | Meaning |
|------------------|--------|
| **open** | Not yet looked at or acted on. |
| **acknowledged** | User (or system) has seen it; no resolution yet. |
| **resolved** | Addressed (e.g. owner assigned, blocker cleared). |
| **dismissed** | Intentionally ignored or not actionable. |

---

## 3. Why attention_class and resolution_state matter

These two fields keep the model simple today while enabling richer behavior later.

- **attention_class**  
  - **Signal grouping:** Views can group by “all blockers” or “all capacity” across modules (VE + inbox + content) without each module knowing about the others.  
  - **Prioritization:** Policies like “show blockers first, then handoff_gap, then opportunity” can be applied at the Radar layer.  
  - **Council triggers:** “When radar has open signals of class X, suggest a council run.”  
  - **Agenda generation:** “Build today’s focus list from open signals grouped by attention_class.”  
  No need to implement these now; the schema supports them without extra complexity.

- **resolution_state**  
  - **Resolution tracking:** Distinguish “new” (open) from “seen” (acknowledged) and “done” (resolved/dismissed).  
  - **Views:** Execution view can show only `open` or `open + acknowledged`; Signals view can show full lifecycle and filters.  
  - **Audit:** Optional later: “Who resolved this and when?” without changing the core schema.  
  Again, the first step stays thin (e.g. VE-derived signals start as `open`; resolution can be “implicit” via VE state or a later explicit API).

---

## 4. Module emitters

Each module that participates in Radar **emits** signals that conform to the RadarSignal schema. Emitters are responsible for their own semantics; Radar only aggregates and serves.

| Module | Role | Example signal types (signal_type) | Example attention_class |
|--------|------|-------------------------------------|-------------------------|
| **vision_execution** | Current VE radar logic. Emits one signal per item in each bucket (act_now, blocked, overcapacity, unanchored, high_value_stalled, kill_candidate). | `act_now`, `blocked`, `overcapacity`, `unanchored`, `high_value_stalled`, `kill_candidate` | act_now → handoff_gap or opportunity; blocked → blocker; overcapacity → capacity; unanchored → drift; high_value_stalled → opportunity; kill_candidate → risk |
| **transcript_sorter** | After user promotes/dismisses candidate tasks or topics. | `promoted_task`, `dismissed_topic`, `unassigned_segment` | handoff_gap (promoted but no VE task); noise_pattern (many dismissals) |
| **content** | Briefs or outputs with no downstream handoff. | `brief_no_ve_task`, `output_not_exported` | handoff_gap |
| **inbox_cleanup** | Intake items needing decision or backing up. | `untriaged`, `corrected_not_synced`, `queue_backlog` | handoff_gap, capacity, risk |
| **perspectives / council** | (Later.) e.g. council run suggested by context, or thread with no follow-up. | `suggested_run`, `thread_no_action` | opportunity, handoff_gap |

**Emission style (first step):**  
- **Synchronous, on read:** When a view or API calls “get radar,” the Radar service asks each registered emitter “give me your signals for this request.” No heavy event bus; emitters can be pure functions over current state (e.g. VE emitter runs the same logic as today’s `get_radar()`, but returns a list of RadarSignals).  
- **Optional persistence later:** A second phase could write signals to a small store and allow resolution_state updates; the first phase can be in-memory aggregation only so the current VE radar behavior is unchanged.

---

## 5. Radar views

Two conceptual views over the **same** signal layer:

| View | Purpose | Consumes |
|------|---------|----------|
| **Execution view** | Current VE-style “what needs attention” in execution terms. Deterministic buckets (act_now, blocked, overcapacity, unanchored, high_value_stalled, kill_candidates). Same UX as today’s Radar tab. | Signals from `source_module = vision_execution` (and only those, for this view), possibly still grouped by existing bucket names. Behavior and layout stay as-is. |
| **Signals view** | Future cross-system attention view. One list or board of all signals (or filtered by attention_class, resolution_state, source_module). Enables “everything that needs attention” in one place. | All signals from all emitters; optional grouping by attention_class or source_module; resolution_state filters. |

**Why one shared layer:**  
- **Single place to add new “attention”:** New modules only need to emit signals; they don’t create a new dashboard.  
- **Consistent semantics:** attention_class and resolution_state work across modules.  
- **No duplication of concepts:** “Blocked” in VE and “blocker” in another module can both use `attention_class: blocker` and appear in a unified view later.  
- **Migration safety:** Execution view stays the first consumer; Signals view is an additional view when we’re ready.

---

## 6. Migration path

Thin, incremental steps:

| Step | Action |
|------|--------|
| **1. Keep current VE radar** | No change to the existing `/vision-execution/radar` API or UI. It continues to return the current bucket structure and the Radar tab keeps working. |
| **2. Introduce RadarSignal abstraction** | Define the RadarSignal schema (e.g. in a shared types module or doc). Implement a small **Radar service** (e.g. `radar/` or under `vision_execution`) that can collect and return a list of RadarSignals. No new UI yet; optional new endpoint e.g. `GET /radar/signals` that returns signals. |
| **3. Map VE radar logic to emitted signals** | Add a **Vision Execution emitter**: given current initiatives/projects/tasks/capacity, run the same logic as today’s `get_radar()`, but for each bucket item produce one RadarSignal (with id, source_module=`vision_execution`, signal_type=bucket name, attention_class mapped, entity_type/entity_id/title, resolution_state=`open`, created_at=now). The existing `get_radar()` can remain and be implemented by “call VE emitter, then shape result into current bucket format” so the current API response is unchanged. |
| **4. Later: other modules emit** | Register emitters for transcript_sorter, content, inbox_cleanup (and later council). When “get all signals” is called, Radar asks each emitter and concatenates. Execution view continues to use only VE emitter; Signals view uses all. |
| **5. Aggregate into shared Radar UI/views** | Radar tab can stay “Execution view” (VE buckets). Add a second view (e.g. “Signals” or “All attention”) that consumes the full signal list. Optional: single “Radar” entry point that switches between Execution and Signals view. |

**First step deliverable:** Steps 1–3 only: RadarSignal schema, one VE emitter that emits signals, and existing VE radar implemented on top of that so behavior is identical. No new views, no new persistence, no event bus.

---

## 7. Scope constraints

- **Keep current VE radar behavior working.** The existing bucket API and Radar tab must remain correct and unchanged in behavior. Migration is additive and backward-compatible.
- **Do not build a heavy event bus.** First phase: synchronous “on read” aggregation from emitters. No message queue, no pub/sub requirement.
- **Do not add ML.** Signal content and severity/confidence are from deterministic rules or explicit module logic. No automatic clustering or scoring in the Radar layer for the first step.
- **Do not overbuild persistence yet.** Signals can be computed on demand from current state. Optional later: store signals and resolution_state in a small table or store for history and resolution tracking.
- **Keep the first step thin and deterministic.** One schema, one emitter (VE), same VE view. Then add emitters and views incrementally.

**Goal:** Make Radar the nervous system of Atria — one shared signal layer, multiple emitters, multiple views — in a clean, elegant, minimally imposing way.
