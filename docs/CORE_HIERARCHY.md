# Core Hierarchy

Design note: **Vision Execution is the primary core of Zenaf.** Intake is subordinate and serves Vision Execution. No subsystem should become a second durable center of work.

**Guiding rule:** Vision Execution is the durable center for organizational meaning and execution state. All other subsystems support it or feed into it; none should evolve into an independent durable silo.

---

## 1. Vision Execution: Primary Core

Vision Execution is the **internal system of truth** for:

- **ideas** — raw possibilities and hypotheses  
- **initiatives** — committed strategic efforts  
- **projects** — concrete work streams  
- **tasks** — actionable units tied to projects  
- **decisions** — durable committed decisions linked to execution entities  
- **people** — who is involved and their capacity  
- **assets** — resources and artifacts  
- **capacity** — availability and allocation  
- **radar / roadmap** — act now, blocked, overcapacity, unanchored, kill candidates  

**Location:** `local_ai/vision_execution/` (storage, service, models, radar, derived, initiative_evaluate, meeting_extract). API: `/vision-execution`. Persistence: `data/vision_execution/vision_execution.db`.

**Implication:** New “organizational meaning” (what we’re doing, why, who, what’s next) belongs in Vision Execution. Intake, council, Idea Lab, and File Steward should create or update Vision Execution entities when their outputs imply commitments or execution state—not maintain parallel durable stores of the same kind.

---

## 2. Intake: Subordinate Staging / Triage

Intake is a **staging and triage subsystem**, not a parallel core. It:

- **Ingests** external messages (email, fax) from mailboxes  
- **Classifies and prioritizes** (category, priority, lane)  
- **Supports operator review** (queue, PATCH, overrides)  
- **Produces preliminary judgments** (interpretation, proposed action, confidence, reason codes)  
- **Creates or updates Vision Execution entities when relevant** (e.g. turn a triaged item into a task, initiative, or decision)  

**Location:** `local_ai/intake/` (pipeline, queue_store, mirror, email_ingestion, classifier, redaction, lanes, etc.). API: `/intake`. Persistence: `intake_mirror.db` for **staging state** (queue items, judgment history for triage, sync state, mailbox action audit)—not for execution truth.

**Implication:** The intake mirror is the source of truth for “what’s in the triage queue and how we judged it,” not for “what the organization is doing.” When intake outcomes should affect execution, the path is: intake → create/update Vision Execution entities (tasks, decisions, etc.). Intake does not own ideas, initiatives, projects, or decisions; it feeds them.

---

## 3. Judgment: Reasoning Infrastructure

Judgment is **reasoning infrastructure**, not the final execution store.

- **Judgment records** = interpretations, proposals, corrections (e.g. “this item is needs_attention because …”; “operator overrode to waiting_fyi because …”). They explain and justify; they can be superseded.  
- **Vision Execution decisions** = durable, committed decisions tied to execution entities. They are the record of what was decided for the organization, not the reasoning trail.  

**Location:** `local_ai/judgment/` (in-memory store; persistence today is via intake mirror for intake-domain judgments). Vision Execution has its own `decisions` table for committed decisions.

**Implication:** Keep judgment as the shared protocol for “why we interpreted/decided this way” and for corrections. When a judgment implies a **commitment** (e.g. “we will do X”), that commitment should be recorded in Vision Execution (e.g. as a decision or task), not only as a judgment record. Judgment supports audit and explainability; Vision Execution holds what we’re actually doing.

---

## 4. Tools and Modules: Feeders into the Core

Council, File Steward, Idea Lab, and similar tools should **feed the Vision Execution core**, not become independent durable centers.

- **Council** — Multi-perspective reasoning and synthesis. Outputs (recommendations, trade-offs, next actions) should be able to create or update ideas, initiatives, tasks, or decisions in Vision Execution when they represent commitments.  
- **File Steward** — Folder analysis, recommendations, simulation. Outcomes (e.g. “adopt this structure”) can translate into tasks or decisions in Vision Execution.  
- **Idea Lab** — Ideas, prioritization, hypotheticals. Ideas that are “accepted” or “committed” should live or be reflected in Vision Execution (ideas, initiatives), not only in a separate Idea Lab store.  

**Implication:** Avoid building a second durable “ideas” or “decisions” store in Idea Lab or council. Prefer: tools produce recommendations or drafts; when the user or system commits, write to Vision Execution. Same for any future connectors (calendar, PM tools): they normalize and feed; Vision Execution remains the durable center for execution state.

---

## 5. Practical Implications for Cleanup and Refactor

| Priority | Direction |
|----------|-----------|
| **Single durable center** | Resist adding new “centers” (e.g. a separate Idea Lab DB that mirrors ideas/initiatives). Prefer Vision Execution as the target for committed state; other DBs are for staging, cache, or external sync only. |
| **Intake → Vision Execution** | Add or clarify flows where intake outcomes create/update Vision Execution entities (e.g. “create task from queue item,” “log decision from override”). Document and implement these as the intended path from triage to execution. |
| **Judgment vs decisions** | Keep judgment as the reasoning/audit layer. When intake or council produces a “decision” that should be organizational record, also write a Vision Execution decision (or task/initiative) linked to the context. Do not treat judgment persistence as the execution store. |
| **Mirror and queue** | Intake mirror remains the source of truth for **staging** (queue, triage judgments, sync, mailbox audit). It is not the source of truth for execution. Naming and docs should reflect “staging mirror” / “triage state,” not “second core.” |
| **Tools and persistence** | When adding persistence for council, Idea Lab, or File Steward, prefer: (1) ephemeral or short-lived cache, or (2) write-through to Vision Execution (ideas, tasks, decisions). Avoid new long-lived “content” or “decision” DBs that duplicate Vision Execution’s role. |
| **Docs and manifest** | Update ZENAF_ARCHITECTURE, CODEBASE_INVENTORY, PLATFORM_PRIMITIVES, and codebase_manifest.json to state that Vision Execution is the primary core and intake is subordinate staging; judgment is reasoning infrastructure; tools feed the core. |

---

## Summary

| Layer | Role | Durable? |
|-------|------|----------|
| **Vision Execution** | Primary core: ideas, initiatives, projects, tasks, decisions, people, assets, capacity, radar | Yes — execution state |
| **Intake** | Staging/triage: ingest, classify, review, preliminary judgments; feed Vision Execution when relevant | Staging only — queue + triage mirror |
| **Judgment** | Reasoning: interpretations, proposals, corrections; supports audit and explainability | Supports intake (and future domains); not the execution store |
| **Council / File Steward / Idea Lab** | Feeders: produce recommendations and drafts; committed outcomes → Vision Execution | No independent durable center |
