# Content Pipeline — Design Note

**Status:** Design  
**Scope:** Content workspace tab (thin production workspace serving Vision Execution)  
**Goal:** Make Zenaf the **conductor of the media pipeline** — shared context, tool-shaped handoff packages, and production/distribution tracking — **not a replacement for every instrument.**

---

## 0. Orchestration, not replacement

Zenaf does **not** replace specialist tools (ElevenLabs, HeyGen, page builders, email platforms, etc.). Its role is the **orchestration layer** where those tools can talk to each other through:

- **Shared context** — one content brief that stays coherent across source materials, goals, audience, tone, and outputs.
- **Structured handoff packages** — tool-shaped exports (e.g. script for TTS, script+metadata for avatar, copy for a page) that downstream tools consume.
- **Production/distribution handoff tracking** — VE-linked tasks so “record narration”, “produce avatar video”, “build landing page”, “send newsletter” are tracked in one place.

**Content tab purpose (concise):**

1. **Shared content brief** — single anchor for audience, themes, claims, CTA, tone, formats.
2. **Draft generation** — script, newsletter, copy from brief + source materials.
3. **Tool-shaped output packaging** — exports formatted for ElevenLabs, HeyGen, page builder, email platform, etc., not custom UIs for those tools.
4. **Production/distribution handoff tracking** — what’s been handed off, what’s next; tasks live in Vision Execution.
5. **VE-linked task creation** — create tasks (record narration, produce avatar video, build landing page, send newsletter) attached to the linked project/initiative.

**Zenaf should not become:** a full media editor, a voice cloning UI, an avatar builder, a page builder, or a full campaign sender.

**Zenaf should become:** the place where source materials, goals, audience, tone, and outputs stay coherent; where downstream tool handoffs are prepared and tracked; and where production tasks link back into Vision Execution.

**Future integrations** should be modeled as: **input sources** (e.g. notebook distillations, meeting notes), **transformation endpoints** (e.g. generate script, generate newsletter), and **distribution endpoints** (e.g. “hand off to ElevenLabs”, “hand off to email platform”) — with Zenaf holding the brief and the handoff state, not reimplementing the tools.

**Anchor object:** The **Content Brief** is the anchor. All output packages and downstream handoffs derive from that shared brief.

---

## 1. Core framing

- **Content is a production workspace, not a separate durable core.**  
  The Content tab is the orchestration workspace: brief → drafts → tool-shaped packages → handoff tracking and VE tasks. It does not replace or duplicate Vision Execution as the system of record.

- **Vision Execution remains the system of organizational truth.**  
  Initiatives, projects, tasks, people, and capacity live in Vision Execution. Content work is *in service of* that core: briefs and outputs reference VE entities; tasks for production and distribution are created in VE.

- **Content outputs should link to initiatives/projects/tasks.**  
  Every brief and every generated output can (and should) reference at least one initiative, project, or task. This keeps content traceable, prioritizable, and accountable within the same ontology as the rest of the system.

---

## 2. Minimal pipeline stages

A thin, linear pipeline — enough structure to support the use cases without overbuilding:

| Stage | Purpose |
|-------|--------|
| **Source distillation** | Ingest and summarize source material (notebook distillations, meeting notes, research, existing docs). Output: structured “source pack” or summary that feeds the brief. |
| **Content brief creation** | Define the content package: audience, themes, claims, CTA, tone, formats, distribution. Single lightweight object (see §3). |
| **Script/copy generation** | Generate text from brief + sources: longform/shortform scripts, newsletter, email sequence, landing page, etc. |
| **Media asset packaging** | Package for specific channels: ElevenLabs narration script, HeyGen avatar script/package, infographic/visual spec, documentary visual spec. |
| **Distribution planning** | Audience-aware plan: who gets what, when, and via which channel. Output: plan + optional VE tasks for execution. |
| **Export/publish handoff** | Export packages (files, copy-paste, specs) and create VE tasks for downstream production/distribution. No auto-publish in scope. |

Stages are sequential in concept but the UI can allow re-entry (e.g. edit brief then regenerate) without modeling a heavy workflow engine.

---

## 3. Core object: Content Brief

Single primary entity: **Content Brief**. Lightweight, linkable to VE, enough structure to drive generation and export.

| Field | Type | Purpose |
|-------|------|--------|
| `title` | string | Brief title / content package name |
| `linked_initiative_id` | string? | Vision Execution initiative (optional) |
| `linked_project_id` | string? | Vision Execution project (optional) |
| `linked_task_ids` | string[] | Vision Execution tasks (optional) |
| `source_materials` | reference[] | Links to distilled sources, notebook outputs, or inline summaries |
| `audience` | string | Target audience (e.g. “investors”, “newsletter subscribers”, “sales”) |
| `key_themes` | string[] | Main themes or pillars |
| `claims` | string[] | Key messages or claims to include |
| `cta` | string? | Primary call-to-action |
| `tone_voice` | string | e.g. “Phil’s voice”, “professional”, “conversational” — can reference a perspective/agent or free text |
| `target_formats` | string[] | e.g. “longform_script”, “newsletter”, “landing_page”, “elevenlabs”, “heygen” |
| `distribution_targets` | string[] | e.g. “newsletter”, “email_sequence”, “blog”, “social” — high-level only |
| `notes` | string? | Free-form notes |
| `created_at` / `updated_at` | datetime | Metadata |

**Persistence:** Briefs can live in the Vision Execution backend as a small “content_briefs” resource (or equivalent) keyed by project/initiative, or in the same app DB with `linked_project_id` / `linked_initiative_id` as foreign keys. No separate “content database” is required unless scale or multi-tenant needs justify it later.

---

## 4. Derived outputs (tool-shaped handoff packages)

Outputs are **handoff packages** for downstream tools, not in-app replacements for those tools. At minimum, support **generation and/or export specs** for:

| Output type | Description | Typical use |
|-------------|-------------|-------------|
| **Longform script** | Full narration or documentary script | Keynotes, long video, podcast |
| **Shortform script** | Condensed script (e.g. 60–90s) | Ads, social, teasers |
| **Newsletter draft** | Structured email body (subject + sections) | Newsletter |
| **Email sequence draft** | Multi-message sequence outline/draft | Nurture, launch |
| **Landing page copy** | Headline, subhead, sections, CTA blocks | Campaign landing |
| **Webpage copy** | General page copy (Mastermind or other) | Site pages |
| **Infographic / visual spec** | Bullet spec or narrative for designer | Infographic, one-pager |
| **Documentary visual spec** | Shot list / scene narrative | Video/doc production |
| **ElevenLabs-ready narration script** | Script formatted for TTS (Phil’s voice, etc.) | Voiceover |
| **HeyGen-ready avatar script/package** | Script + metadata for avatar video | Avatar video |

Each output is **tied to a Content Brief** (and thus to VE initiative/project/task). Generation can be “on demand” (e.g. “Generate newsletter from this brief”) with results shown in the workspace and exported as needed; no requirement to store every generated draft as a first-class entity in V1.

---

## 5. Workspace layout (Content tab)

Propose a **thin three-pane structure**:

- **Left: Source / Brief**
  - Source materials selector or paste (distillation input).
  - Content Brief form (fields from §3).
  - Optional: “Create from notebook distillation” or “Link to VE project” shortcuts.

- **Center: Generated outputs**
  - List or tabs of output types (script, newsletter, email sequence, landing page, etc.).
  - Per type: “Generate” and a view of the current draft (read-only or simple edit).
  - No version history or heavy asset management in V1.

- **Right: Export / next-actions**
  - Export actions: copy to clipboard, download as file, “Export for ElevenLabs”, “Export for HeyGen”, etc.
  - “Create VE task” to hand off to production or distribution (task title, link back to brief/output).
  - Optional: short distribution checklist (what’s done / to do) derived from `target_formats` and `distribution_targets`.

Navigation: Content tab in the same top-level nav as Workspace Organizer, Perspectives, Vision & Execution. Same header and (if desired) shared “Current topic” or context bar; AI agents panel can remain available for “in Phil’s voice” or audience-aware generation.

---

## 6. Scope constraints

- **Do not build a full CMS.** No generic media library, asset versioning, or site-wide content tree.
- **Do not build a full CRM.** No contact/audience database; distribution “targets” are labels (e.g. “newsletter”, “email_sequence”), not synced lists.
- **Do not auto-publish.** Export and handoff only; publishing stays in external tools (ElevenLabs, HeyGen, email tool, web CMS).
- **Do not create a separate durable content database unless clearly needed.** Prefer storing briefs (and optionally minimal output metadata) in the existing app/VE data model with strong links to initiatives/projects/tasks.
- **Keep outputs linked to Vision Execution context.** Every brief and every “create task” action should be traceable to initiative/project/task so Content never becomes a silo.
- **Do not replace specialist tools.** Zenaf does not become: a full media editor, a voice cloning UI, an avatar builder, a page builder, or a full campaign sender. It prepares handoff packages and tracks tasks; the actual editing, cloning, building, and sending stay in the specialist tools.

---

## 7. First implementation recommendation (V1)

**Thinnest useful V1:**

1. **Create content brief**
   - Form for the Content Brief object (§3), with `linked_project_id` / `linked_initiative_id` (and optionally task) from Vision Execution.
   - Source materials: free-text or paste (no elaborate distillation UI in V1).

2. **Generate text outputs**
   - From brief + source text, support “Generate” for a small set: e.g. **longform script**, **newsletter draft**, **landing page copy**, **ElevenLabs-ready script**, **HeyGen-ready script**.
   - Use existing AI/run infrastructure (e.g. council or a single “content” mode) with a prompt that includes brief fields + source. Results shown in the center pane; no requirement to persist every draft.

3. **Export packages**
   - Buttons/cards: “Copy to clipboard”, “Download .txt”, and where applicable “Export for ElevenLabs” / “Export for HeyGen” (format/spec as needed for handoff). No direct API integration required in V1.

4. **Create VE tasks for downstream work**
   - “Create task in Vision Execution” with title and optional description, linked to the same project/initiative as the brief. Enables distribution and production follow-up without building a CRM or scheduler.

**Out of V1:**  
- Full source distillation UI (notebook ingestion, structured “source pack”).  
- Distribution planning as a first-class step (can be a short checklist in the right pane later).  
- Stored version history of every generated output.  
- Infographic/visual spec generation (can be a later addition).

This keeps the Content tab a **thin production workspace** that serves Vision Execution and avoids turning it into a separate durable silo or a giant media CMS.
