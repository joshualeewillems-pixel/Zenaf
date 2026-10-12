# Soil layer — filesystem interpretive substrate (spec)

<!--
Status: Soil v1 complete — locked, parked (no expansion without new charter)
Last updated: 2026-04-03
-->

**Soil v1 complete (parked).** Shipped: **spec** (this doc), **kernel** (`local_ai/soil/`), **CLI** (`python -m local_ai.soil.cli`), **transport API** (`POST /vision-execution/soil/append`, `…/promote`), **dev append surface** (`TaskSoilDevAppend`, Vite dev only), **manual verification checklist** (§12.3). **Intentionally not in v1:** read hooks, auto-capture, council integration, vectors/indexing. Further soil work is **deferred**; prefer core convergence lines (traces, guidance, core profile ontology, mirror interpretation, etc.) until soil is explicitly re-opened.

---

This document defines **soil**: a **local-first**, **human-inspectable**, **typed**, **append-friendly** layer on disk for interpretive material that is **allowed to be wrong, incomplete, or tentative**. It sits **beside** SQLite / Vision Execution truth (`vision_execution.db`), judgment history, and activity traces — it **does not replace** them.

**Non-goals for the first implementation slice:** indexing, vector search, automatic summaries, council preflight integration, personality / perspective routing, background capture from every LLM run, or any automatic promotion to canonical truth.

---

## 1. Purpose and positioning

### 1.1 What soil is

- **Interpretive substrate** at the granularity of execution subjects (initiatives, projects, tasks, perspectives, optional global root).
- Each **node** is a **fractal interpretive cell**: stable identity, uniform `soil/` taxonomy, optional non-authoritative `canonical/` mirror for human notes or exports.
- **Intelligence accrues where work happens**; upward movement is **gated** (see §6–§7), not automatic.

### 1.2 What soil is not

- Not a second database of record for VE entities.
- Not a silent authority for routing, council seats, or core profile fields.
- Not a dump of every trace or every model output.

### 1.3 Alignment with existing primitives

- **Identity:** Logical keys align with `SubjectRef` in [`local_ai/judgment_substrate.py`](../../local_ai/judgment_substrate.py) (`entity_type`, `entity_id`, optional `title`). `node_id` in `node.json` is a stable string, typically `{entity_type}:{entity_id}` when `entity_id` is present.
- **Evidence pointers:** Soil items may cite `source_refs` using the same **pointer discipline** as coordination signals (trace ids, activity event ids, council run ids, etc.) — **citation is optional** and **does not** imply automatic ingestion from those systems.
- **Canonical truth:** Remains in VE storage, judgment trunk, and related APIs. **Canonicalized** status (§5) means accepted into that layer, not “a file moved to a magic folder.”

---

## 2. Root path resolution

Resolution order (first match wins):

1. Environment variable **`ZENAF_SOIL_ROOT`**: absolute path to the soil version root (the directory that contains `nodes/`).
2. **Default:** `{user_home}/.zenaf/soil/v1`  
   On Windows, `user_home` is the user profile directory (e.g. `%USERPROFILE%`).

**Documented optional convention:** power users may symlink or set `ZENAF_SOIL_ROOT` to a folder under OneDrive/Desktop for sync — at their own risk (merge conflicts are manual).

The implementation **must not** silently fall back to a path inside the git repo unless the user sets `ZENAF_SOIL_ROOT` to that path.

---

## 3. Directory layout

### 3.1 Node path convention (authoritative identity)

Physical layout uses **two path segments** under `nodes/`:

```text
{root}/nodes/{entity_type}/{safe_entity_id}/
```

- **`entity_type`:** lowercase string matching VE / `SubjectRef` usage (e.g. `initiative`, `project`, `task`, `idea`, `perspective_agent`, `core_profile`). The spec does not enumerate an exhaustive closed set; the kernel **validates** `entity_type` against an allowlist (see §10) for writes.
- **`safe_entity_id`:** filesystem-safe form of `entity_id`. The kernel derives this by normalizing the logical `entity_id` (see §11). **Folder names are convenience; `node.json` is authoritative** for identity and relations.

Nested VE hierarchy (initiative → project → task) may be reflected **logically** in `node.json` (`parent_id`) without requiring physical nesting of folders in v1. Optional future layout: `nodes/initiative/{id}/projects/{project_id}/` — not required for the minimal kernel.

### 3.2 Per-node tree

```text
{node_dir}/
  node.json
  canonical/                 # optional; non-authoritative; created empty by kernel
  soil/
    inbox/
    recurring_patterns/
    tensions/
    hypotheses/
    excerpts/
    mediations/
    entity_shadows/
    route_observations/
    candidate_truth/
    promoted/                  # promotion audit records only (§8)
```

**`canonical/`:** Optional human or tooling use (notes, exports). **Not** treated as source of truth by Zenaf unless a future product explicitly says otherwise. The minimal kernel creates an empty `canonical/` directory when ensuring a node.

**`soil/promoted/`:** Contains **promotion event records** (JSON), not general soil markdown items.

### 3.3 Global node (optional)

Optional catch-all for captures not tied to a VE entity:

```text
{root}/nodes/_root/soil/...
```

Use sparingly; same taxonomy under `soil/`. `node.json` for `_root` uses a dedicated convention (e.g. `node_id: "_root"`, `node_type: "_root"`).

---

## 4. `node.json` schema

Single JSON object per node. Required fields for a valid manifest:

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | integer | Start at `1`; bump when breaking manifest shape. |
| `node_id` | string | Stable id, e.g. `initiative:{uuid}`. |
| `node_type` | string | Same as `entity_type` for VE-backed nodes. |
| `title` | string | Human label (may mirror VE title). |

Recommended fields:

| Field | Type | Description |
|-------|------|-------------|
| `parent_id` | string \| null | Parent `node_id`, or `null` / `"root"`. |
| `inherits_from` | string[] | Explicit inheritance chain for readers (provenance). |
| `promotion_targets` | string[] | Where this node’s material may be promoted (design-time hint). |
| `related_nodes` | string[] | e.g. linked `perspective_agent` ids. |
| `ve_entity_id` | string \| null | Duplicate of logical id for tooling if `node_id` uses prefix form. |
| `updated_at` | string (ISO-8601) | Last manifest touch. |

**Rule:** Renames of VE titles **update** `title` in `node.json`; **`node_id` never changes** for the lifetime of that entity.

---

## 5. Soil item format (Markdown + YAML frontmatter)

One file per item, UTF-8, under the appropriate `soil/{category}/` directory (see §5.1).

### 5.1 Category folders and `soil_type`

**Category** is the **directory name** under `soil/` (one of the fixed set in §3.2, except `promoted`).

**`soil_type`** in frontmatter is a **semantic label** (often singular). Implementations map `soil_type` → `category` with a **fixed table** (kernel). Example: `soil_type: tension` → file under `soil/tensions/`.

Initial mapping (v1 kernel):

- `inbox` → `inbox`
- `recurring_pattern` → `recurring_patterns`
- `tension` → `tensions`
- `hypothesis` → `hypotheses`
- `excerpt` → `excerpts`
- `mediation` → `mediations`
- `entity_shadow` → `entity_shadows`
- `route_observation` → `route_observations`
- `candidate_truth` → `candidate_truth`

Unknown `soil_type` → **reject** at append time (fail closed) or require explicit `category` override in API (kernel may support explicit `category` for imports).

### 5.2 Frontmatter fields (required unless noted)

```yaml
soil_id: soil_2026_04_03_0001      # unique string; kernel may generate
node_id: initiative:abc123         # must match owning node
soil_type: tension                 # semantic type; drives category mapping
status: seed                       # §5.3
created_at: 2026-04-03T12:00:00Z  # ISO-8601 UTC recommended
capture_source: user_action        # §6; required for v1 kernel writes
```

Optional:

```yaml
updated_at: ...
source_refs:                       # evidence pointers, not bulk paste
  - trace:tr_123
  - activity:act_456
tags: [routing, ambiguity]
promotion_score: 0                 # opaque hint; no auto-promotion from this alone
related_soil_ids: []
```

**Body:** Markdown prose — human-owned observation, question, or excerpt.

### 5.3 Maturation ladder (`status`)

Enum (linear intent; not all items need reach the end):

1. **`seed`** — raw capture, may be noisy.
2. **`sprout`** — lightly reviewed or structured.
3. **`cluster`** — grouped / recurring pattern noted (still not truth).
4. **`candidate`** — ready to consider for promotion (still **not** canonical).
5. **`canonicalized`** — accepted into VE / judgment / profile **outside** soil; soil file may be updated to reflect that **after** the canonical write succeeds; **must** point to canonical ref (e.g. in body or optional `canonical_ref` frontmatter in a future revision).

**Hard rule:** No automatic transition to **`canonicalized`** from recurrence, embeddings, or model confidence alone. See §7.

---

## 6. Write boundaries (what may create soil items)

This section is **normative** for product and tooling. The minimal kernel **records** `capture_source` on every append and **refuses** unknown sources.

### 6.1 Allowed

| Source | Meaning |
|--------|---------|
| **`user_action`** | User explicitly chose “capture to soil,” paste/save in a soil UI, or equivalent deliberate act. |
| **`named_system_capture`** | A **specific**, **named**, **bounded** pipeline (documented in code + changelog) that writes soil — e.g. a single “Export trace to soil” button or one admin script id. Each named capture has a stable identifier recorded in frontmatter (`capture_name`) when used. |
| **`manual_import`** | Operator-run import script or manual file drop that sets `capture_source: manual_import` (and optional `import_batch_id`). |

### 6.2 Not allowed (without a new spec revision)

- Writing soil **for every** `AiActionTrace` or server trace line automatically.
- Writing soil **for every** LLM run, council message, or VE read automatically.
- **Background** or **scheduled** bulk dumping of logs into soil without a named, capped pipeline reviewed in this doc.
- Silent expansion of `named_system_capture` without updating §6.1 and release notes.
- **Arbitrary** or **dynamic** `capture_name` strings for `named_system_capture` — see §6.3.

### 6.3 Closed allowlist for `named_system_capture`

`capture_source: named_system_capture` **must** set `capture_name` to one of the following **only** (enforced in code: [`local_ai/soil/named_capture_allowlist.py`](../../local_ai/soil/named_capture_allowlist.py)):

| `capture_name` | Intended surface |
|----------------|------------------|
| `ve_ui_soil_capture` | Explicit Vision & Execution UI action (“save to soil” or equivalent) — **not** wired in v1. |
| `dev_soil_export` | Explicit developer / operator export tool (e.g. opt-in trace → soil). |
| `promotion_helper` | Approved helper that writes soil in support of promotion workflows. |

**Not allowed** as named captures without a spec + code change: council turns, generic “trace exporter,” meeting extraction pipelines, or any default-on hook.

Adding a new name requires: update this table, extend `NAMED_SYSTEM_CAPTURE_ALLOWLIST`, and document the cap (what fires it, how often, human gate).

### 6.4 Rationale

Soil stays **inspectable** and **trustworthy enough to open in an editor**. Unbounded automatic writes turn it into an unsearchable heap and train users (and models) to treat it as garbage.

---

## 7. Promotion gate: `candidate` → canonical (hard rules)

**“Canonical”** means state stored in **Vision Execution DB**, **judgment history**, **core profile** fields, or other **explicitly designated** system-of-record stores — **not** `soil/` alone.

### 7.1 What does *not* trigger promotion

- **`promotion_score`** crossing a threshold.
- Single model assertion or single trace.
- Duplication of the same source (e.g. same trace copied twice).
- Background jobs that “notice” repetition without human or routine review.

### 7.2 What *must* be true before canonical acceptance

All of the following are required unless a **future, explicitly documented** exception is added for a narrow automation (which this spec does not define):

1. **Overlap / repetition (interpretive):** The same **substantive** claim or tension appears in more than one **independent** soil item or is reinforced across **time** or **context** in a way a human reviewer (or defined promotion routine) recognizes — **not** mere string duplicate.
2. **Cross-source support (when claiming external reality):** If the promoted content asserts facts about the world, codebase, or commitments, **where applicable** it should cite **more than one class** of evidence in `source_refs` (e.g. trace + activity, or activity + judgment pointer) — **human may waive** for purely introspective notes.
3. **Human acceptance:** A named user or operator **confirms** promotion through UI, CLI, or signed import — recorded in the promotion record as `accepted_by`.
4. **Defined promotion routine (optional alternative to ad-hoc acceptance):** A **documented** script or API flow that **requires** explicit parameters (`reason`, `supporting_soil_ids`, target canonical handle) and is **idempotent-auditable** — still **not** “auto on schedule.”

### 7.3 Promotion mechanics (reference, not copy)

- The **canonical store** holds the authoritative field or row.
- The **soil item** (or parent summary) **retains** `soil_id` and backlinks via the **promotion record** (§8).
- Parent-level summaries **must** reference child `soil_id`s — **no dumb copy** that severs lineage.

### 7.4 Inheritance visibility

- Readers (human or code) **must** be able to see **which node** a signal came from.
- **No silent flattening** of parent + child soil into one opaque blob for consumption by trusted pipelines **until** a separate doc defines an explicit, lossless serialization — **out of scope** for v1 kernel.

### 7.5 Per-type promotion rules

**Folder taxonomy is uniform; promotion *logic* may differ by `soil_type`.** Example policy (product, not all enforced in kernel):

- `tension` — may bubble to parent node **only** via explicit promotion record after §7.2.
- `excerpt` — slower promotion; often stays local.
- `route_observation` — may stay **perspective_agent**-local in many workflows.

The minimal kernel **does not** implement these differences; it only writes records. Logic belongs in future services.

---

## 8. Promotion record format (`soil/promoted/`)

One JSON file per promotion event (filename implementation-defined; e.g. `promo_{utc_datetime}_{shortid}.json`).

Required fields:

| Field | Type | Description |
|-------|------|-------------|
| `promotion_id` | string | Unique id for this event. |
| `created_at` | string | ISO-8601. |
| `from_soil_id` | string | Source item `soil_id`. |
| `from_path` | string | Path relative to `{root}` for traceability. |
| `from_node_id` | string | Source `node_id`. |
| `to_canonical_ref` | object | Descriptor of canonical write target (see below). |
| `reason` | string | Human or routine justification. |
| `accepted_by` | string | Who accepted (user id, email, or `script:{name}`). |
| `supporting_soil_ids` | string[] | Additional soil ids supporting the promotion. |

Recommended:

| Field | Type | Description |
|-------|------|-------------|
| `to_node_id` | string \| null | If promotion also created a parent-level summary item. |
| `canonical_write_result` | object | Optional stub ids returned from VE/judgment APIs when wired. |

**`to_canonical_ref` (v1 shapes):**

- `{ "kind": "ve_entity", "entity_type": "<type>", "entity_id": "<id>", "field": "<optional_field_key>" }`
- `{ "kind": "judgment", "judgment_id": "<id>" }`
- `{ "kind": "core_profile", "profile_id": "<id>", "field": "<key>" }`
- `{ "kind": "unspecified", "note": "<free text>" }` — **only** for manual audit before APIs exist

---

## 9. Read / inheritance rules (for future consumers)

Until dedicated read APIs exist:

1. **Local first:** Load soil from the **subject’s** `soil/` tree before aggregating ancestors.
2. **Explicit inheritance only:** Parent signals appear only via **dedicated** summary files or APIs that list **provenance** (`node_id` + `soil_id` per bullet).
3. **Caps:** Any automated reader **must** enforce **byte and item count** limits; soil must never swamp prompts.

**v1 kernel** implements **no** aggregation reader. Council, personalities, and guidance **must not** depend on soil until a later phase explicitly removes this restriction.

---

## 10. Day-one node types (kernel allowlist)

The minimal kernel **permits** ensures/appends for:

- `task`
- `project`
- `initiative`
- `idea`
- `perspective_agent`
- `core_profile`
- `_root` (global bucket; `entity_id` may be empty or `"global"` per implementation)

Extending the allowlist **requires** a spec bump or additive section in this doc.

---

## 11. Filesystem safety

- `entity_type`: reject `..`, path separators, and empty string.
- `entity_id`: may contain characters unsafe for paths; **always** normalize to `safe_entity_id` for the directory name (e.g. replace `/\:*?"<>|` and newlines; cap length; use a deterministic hash suffix if needed after stripping — kernel implements one deterministic scheme and documents it in code comments).

---

## 12. Minimal kernel scope (implemented)

The first code slice **only**:

1. Resolves `ZENAF_SOIL_ROOT` / default root.
2. Ensures `{node_dir}`, `node.json`, `canonical/`, `soil/{categories}/`, `soil/promoted/`.
3. Appends a soil Markdown file with valid frontmatter and `capture_source`.
4. Writes a promotion JSON record under `soil/promoted/`.
5. **CLI:** `python -m local_ai.soil.cli append …` and `promote …` (same kernel; no HTTP).
6. **Enforces** `named_system_capture` `capture_name` against the closed allowlist (§6.3).

**Explicitly not in v1:** Read hooks into council/guidance, indexing, auto-ingest from traces, personality integration, automatic status transitions, canonical writes from promote.

### 12.1 CLI examples (`python -m local_ai.soil.cli`)

`--root` is optional on each subcommand (defaults to `ZENAF_SOIL_ROOT` / `~/.zenaf/soil/v1`). For `named_system_capture`, `--capture-name` must be one of §6.3.

```bash
python -m local_ai.soil.cli append \
  --entity-type task \
  --entity-id 123 \
  --soil-type tension \
  --capture-source user_action \
  --title "Scope approval ambiguity" \
  --body-file note.md

python -m local_ai.soil.cli promote \
  --entity-type task \
  --entity-id 123 \
  --from-soil-id soil_2026_04_03_0001 \
  --to-node-id project:abc \
  --reason "Repeated across 3 related tasks"
```

If `--from-path-rel` is omitted, `promote` searches `nodes/**/soil/**/*.md` (excluding `promoted/`) for a unique `soil_id`. The soil item’s `node_id` must match the target node (`--entity-type` / `--entity-id`).

**CLI stdout:** `append` prints line 1 = `soil_id`, line 2 = **`relative_path`** (forward slashes, relative to soil root). `promote` prints one line: relative path to the audit JSON. Matches API `relative_path` field (cross-platform stable).

### 12.2 HTTP API (authenticated, transport-only)

Base path: **`/vision-execution/soil/`** (session cookie auth, same as other VE routes).

| Method | Path | Role |
|--------|------|------|
| `POST` | `/vision-execution/soil/append` | Same as `append_soil_item`; **no** `manual_import`. |
| `POST` | `/vision-execution/soil/promote` | Same as `write_promotion_record` only — **audit JSON**, no canonical VE write. |

**`append` — allowed `capture_source`:** `user_action`, `named_system_capture` (with allowlisted `capture_name`, enforced by kernel). **`manual_import`** is rejected on this surface (CLI/scripts only).

**Authenticated `named_system_capture`:** These routes use session auth (`get_current_user`). Anonymous clients cannot call them; combined with the allowlist, system-style captures cannot present as trusted without identity.

**Implicit `ensure_node` (API only):** Before append/promote, the server checks that `entity_type` / `entity_id` refers to an **existing** Vision Execution row for the signed-in user (`task`, `project`, `initiative`, `idea`, `core_profile`, or `perspective_agent` in persisted council workspace JSON). **`_root`** is allowed **only** when the client sends **`explicit_root_bucket: true`** (opt-in). The CLI is not subject to this VE check.

**`promote`:** Target node must already have `node.json` (typically after at least one append). Default `to_canonical_ref` if omitted: `{ "kind": "unspecified", "note": "API promotion audit only (no canonical write)" }`. `accepted_by` is set to `api:{user_id}`.

**Dev UI (cockpit):** In **`import.meta.env.DEV`**, the task detail panel includes **Soil (dev)** — optional `soil_type`, free-text body, **`capture_source: user_action` only**, response shows **`soil_id`**, **`resolved_node`** (`task:{id}`), and **`relative_path`**. No promotion control in this slice. Body hard-capped in UI at **262,144** chars; title passed to API at **512** chars max (`node.json` uses the same cap on first create).

### 12.3 Manual verification checklist (hand-driven)

**Core path**

1. Append a **tension**, then a **hypothesis**, for one real **task you own** (dev panel or API or CLI).
2. Inspect disk under the soil root: **`nodes/task/{id}/`**, **`node.json`** present, **`node_id`** = `task:{id}`, each file under the correct **`soil/{category}/`** for `soil_type`, frontmatter complete, **body** matches what you entered (UTF-8).
3. **Promote** one item via CLI (or API): confirm **`soil/promoted/*.json`** has **`from_soil_id`** matching the source file, **`to_node_id`** / **`reason`** as intended, **`to_canonical_ref`** is audit-only (no silent VE write).

**Edge checks**

- Append for a **task id that exists but belongs to another user** (or any id not returned by VE for your session): expect **404** `soil_api_ve_subject_not_found` on the API; CLI has no VE guard.
- Append with body at **262,144** characters: should **200**; **262,145** → **422** on API.

**Trust bar:** If this feels clean and inspectable by hand, the substrate is ready for future read-side work — **without** adding read hooks, auto-capture, or council consumption until you explicitly choose to.

---

## 13. Revision history

| Date | Change |
|------|--------|
| 2026-04-03 | Initial locked spec + write boundaries + promotion gate + minimal kernel scope. |
| 2026-04-03 | CLI (`python -m local_ai.soil.cli`), closed `named_system_capture` allowlist in code + §6.3. |
| 2026-04-03 | Authenticated API `POST /vision-execution/soil/append` and `…/promote`; VE existence guard + explicit `_root` flag (§12.2). |
| 2026-04-03 | Dev-only task panel control for soil append (`TaskSoilDevAppend`, Vite dev). |
| 2026-04-03 | Cleanup: stable soil `.md` basenames, `relative_path_posix`, manifest title cap 512, CLI stdout relative paths, §12.3 verification checklist. |
| 2026-04-03 | **Soil v1 complete (parked):** header marker; defer expansion until explicit charter. |
