# Subject / Node Primitive — Architecture Note

**Status:** Intent / future-facing  \n**Scope:** Record the deeper architectural direction for Zenaf’s object model without changing current business modules.  \n**Goal:** Describe the generic **Subject/Node** primitive and how existing entities may eventually become typed expressions of it to support Mandelbrot-scaling decision architecture.

---

## 1. Subject / Node concept

In the long term, Zenaf is evolving toward a **Mandelbrot-scaling cognitive operating system**: the same loop

> observation → judgment → decision → execution → outcome

should operate at many levels of scale (task, project, initiative, venture, organization, etc.).

To support this, the deeper system revolves around a generic primitive:

**Subject (or Node)** — any meaningful thing that can be:

- captured  \n- classified  \n- judged  \n- prioritized  \n- tracked  \n- related to other things  \n- revisited later

Examples of future Subjects:

- idea  \n- initiative  \n- project  \n- task  \n- content brief  \n- offer  \n- service line  \n- person  \n- team  \n- organization  \n- venture candidate

In this framing, a Subject is the object that flows through the **observation → judgment → decision → outcome** lifecycle, regardless of scale or business domain.

---

## 2. Why concrete business modules exist today

Today, Zenaf uses **practical, hard-coded business entities** because it is serving a specific operator and set of workflows:

- Vision Execution: ideas, initiatives, projects, tasks, decisions, people, assets, capacity (see `local_ai/vision_execution/models.py`).  \n- Content: content briefs, generated scripts/newsletters (see `ContentBrief` and related tools).  \n- Intake and transcript sorter: intake items, judgments, candidate tasks/decisions/ideas.  \n- Council: seat judgments and run artifacts (see `judgment_substrate.py` and council tools).

These modules are **valuable and correct** for the current use case and must remain intact. They make it easy to ship real capabilities without prematurely abstracting the entire object model.

Architecturally, though, they can be viewed as **specialized views or adapters** over a deeper Subject/Node primitive that has not yet been fully surfaced.

---

## 3. Mapping current entities to Subject

Existing entities often already contain the fields a generic Subject would need:

- **VE initiatives / projects / tasks** — id, title, brief/description, status, priority, links to people/assets/capacity.  \n- **Content briefs** — id, title, linked initiative/project/task, audience, goals, themes, claims, CTA.  \n- **Intake items / transcript artifacts** — id, source text references, categories, candidate tasks/decisions/ideas.  \n- **People / teams / assets / capacity** — ids and attributes that could be seen as Subjects in a resource dimension.

In the future, these can be treated as:

- **Typed Subject expressions** — e.g. `Subject(entity_type='initiative', entity_id=..., extra={...})`.  \n- **Views over a shared Subject graph** — where “idea”, “initiative”, “project”, “task”, “content_brief”, “person”, etc. are different lenses on the same underlying primitive.

The **judgment substrate** introduced in `local_ai/judgment_substrate.py` (`SubjectRef`, `JudgmentSnapshot`, `SeatJudgment`, `CouncilRunArtifact`) is deliberately generic so it can point at any Subject without knowing its concrete type.

---

## 4. Subjects in the information lifecycle

The existing information lifecycle is:

> **observation → judgment → decision → outcome**

- **Observation** — intake items, transcripts, filesystem scans, existing VE entities, etc.  \n- **Judgment** — intake judgments, transcript sorter outputs, council seat judgments, next-step recommendations.  \n- **Decision** — VE decisions (with `ai_proposal_snapshot` and `final_values_snapshot`), task/initiative/project creation or updates.  \n- **Outcome** — radar, capacity metrics, status changes, and later explicit outcome assessments.

In the long-term architecture:

- A **Subject** (or Node) is the thing being observed, judged, decided about, and monitored for outcomes.  \n- Each lifecycle event carries a `SubjectRef` (or equivalent) so that decisions and outcomes can be attached to the right Subject across time and scale.

This is already visible in the early substrate:

- `SubjectRef` in `judgment_substrate.py`.  \n- VE `Decision` objects with `entity_type` and `entity_id`.  \n- Intake and transcript sorter objects that could be normalized into Subjects.

---

## 5. Mandelbrot scaling: same architecture, different levels

By converging on a Subject/Node primitive:

- **Same decision architecture across levels**:  \n  The council and judgment substrate can reason about a `Subject` whether it is a task, a project, an initiative, an entire service line, or a prospective venture. The code does not need to special-case every level; the mandate and context do the shaping.

- **Reusability of tools**:  \n  Radar, council, next-step, transcript sorter, and content generation can all operate on any Subject type, as long as they understand its fields via adapters.

- **Graph of relationships**:  \n  Subjects can relate to each other (idea → initiative → project → task; person → capacity → initiative; content_brief → initiative, etc.), enabling more powerful reasoning and pattern detection.

The current system does **not** refactor into this model yet; this note simply documents that the **direction of travel** is toward a generic Subject/Node core, with existing business modules acting as typed specializations.

---

## 6. Non-goals for now

- No refactoring of existing data models or APIs.  \n- No new Subject/Node persistence layer yet.  \n- No generic graph engine or large ontology system.

This note is **documentation and architectural breadcrumbs only**. It informs future design choices and small seams (like `SubjectRef` and `object_snapshot` in the judgment substrate) so the system can gradually grow into a Subject/Node-centered architecture without breaking current behavior.

