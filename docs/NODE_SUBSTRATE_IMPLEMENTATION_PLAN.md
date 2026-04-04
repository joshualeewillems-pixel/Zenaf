# Node Substrate — Minimal Implementation Plan

<!-- STATUS: Superseded. See docs/01_TRUTH/CODEBASE_TRUTH_RULES.md §5b and local_ai/judgment_substrate.py (SubjectRef, JudgmentTrunk). node_adapters / subject_adapters were attempted and retired (tombstoned). -->

**Status:** Architecture direction / implementation plan *(historical — node adapter path not pursued)*  
**Goal:** Introduce a minimal internal **NodeRef** and **NodeSnapshot** layer for cross-module identity and relationships, to reduce future retrofit cost as Atria moves toward a multi-user office environment (4+ users, divergent workflows).  
**Constraint:** Additive and internal only. Do not replace or rewrite existing business modules (VE, Content, Intake, etc.).

---

## 1. Recommended schema

### 1.1 NodeRef

Lightweight identity for “a thing” in the system, with multi-user and cross-module provenance. Used for references in judgments, links, and scoping.

```text
NodeRef
  node_type: str           # e.g. "task", "project", "initiative", "content_brief", "intake_item", "idea"
  node_id: str            # stable id (today often = source_entity_id; later may be a global node id)
  workspace_id: str       # optional for now; default "" or "default" for single-operator
  owner_user_id: str      # optional for now; default "" for single-operator
  title: Optional[str]    # optional display hint
  summary: Optional[str]  # optional display hint
  source_module: str      # "vision_execution" | "content" | "intake" | ...
  source_entity_id: str   # id in the source module (current entity id)
  extra: Dict[str, Any]   # reserved for future (e.g. visibility, scope flags)
```

- **node_id:** Today can equal `source_entity_id` so existing single-module code keeps working. Later, if you introduce a global node store, `node_id` can be a unified id and `source_entity_id` remain the module-native id.
- **workspace_id / owner_user_id:** Required in the schema but default to `""` or `"default"` so single-operator remains valid without any new persistence.

### 1.2 NodeSnapshot

Richer snapshot for reasoning, linking, and visibility. Used when a service needs “a node and its context” without loading the full entity.

```text
NodeSnapshot
  # Identity (same as NodeRef)
  node_type: str
  node_id: str
  workspace_id: str
  owner_user_id: str
  source_module: str
  source_entity_id: str

  # Context
  title: str
  status: Optional[str]
  summary: Optional[str]
  parent_node_id: Optional[str]    # e.g. task -> project, project -> initiative
  related_node_ids: List[str]     # siblings, links, dependencies

  # Multi-user / scope (optional for now)
  visibility: Optional[str]       # e.g. "private", "workspace", "shared"; None = no policy yet
  scope: Optional[str]            # reserved (e.g. team, org); None = unused

  # Provenance / payload
  payload: Dict[str, Any]         # small, module-specific extras (priority, due_date, etc.)
```

- **parent_node_id / related_node_ids:** Use node ids (same as `node_id` or `source_entity_id` for now) so cross-module links stay consistent.
- **visibility/scope:** Optional; leave `None` until you add real visibility rules.

---

## 2. Where it should live

| Artifact | Location | Rationale |
|----------|----------|-----------|
| **NodeRef, NodeSnapshot, normalize_node_ref** | `local_ai/node_substrate.py` | New module; keeps judgment_substrate focused on judgment types and avoids bloating it. |
| **Adapters entity → NodeSnapshot** | ~~`local_ai/node_adapters.py`~~ **retired (tombstoned)** | Was planned parallel to `subject_adapters.py`. **Superseded:** use **SubjectRef** + **JudgmentTrunk** in `local_ai/judgment_substrate.py` and VE row dicts at boundaries; do not import tombstoned adapter modules. |
| **Bridge NodeRef ↔ SubjectRef** | `local_ai/node_substrate.py` or `local_ai/judgment_substrate.py` | One-way `node_ref_to_subject_ref(NodeRef) -> SubjectRef` so existing council/judgment code can accept NodeRef without changing SubjectRef yet. |

- **Do not** put Node types inside `judgment_substrate.py`; keep that file for judgment/artifact types.
- **Do not** add a new top-level package; keep `local_ai` as the home for shared internal layers.

---

## 3. Smallest implementation path

### Phase 1: Substrate only (no call-site changes)

1. **Add `local_ai/node_substrate.py`**
   - Define `NodeRef` and `NodeSnapshot` (Pydantic) with the fields above.
   - Use `Field(default_factory=...)` for lists/dicts; `workspace_id` and `owner_user_id` default to `""`.
   - Add `normalize_node_ref(data: NodeRef | dict | None) -> Optional[NodeRef]` (same pattern as `normalize_subject_ref`).
   - Add `node_ref_to_subject_ref(node_ref: NodeRef) -> SubjectRef` that returns a SubjectRef built from node_type, node_id/source_entity_id, title, summary, extra (so council and judgment code keep working with SubjectRef).

2. ~~**Add `local_ai/node_adapters.py`**~~ **Retired.** Adapters were implemented then **tombstoned**. Cross-entity identity and judgment use **`judgment_substrate.SubjectRef`** (and related types), not entity→`NodeSnapshot` shims. Git history retains the old adapter code if needed for reference.

3. **Document only**
   - In `docs/ARCHITECTURE_SUBJECT_PRIMITIVE.md` (or a short `docs/NODE_SUBSTRATE.md`), state that NodeRef/NodeSnapshot are the internal multi-user identity layer and that SubjectRef remains the judgment-facing ref, with NodeRef → SubjectRef bridge available.

### Phase 2: Optional use at seams (no breaking changes)

4. **Council / judgment**
   - Keep `run_council(subject_ref=..., object_snapshot=...)` and existing API as-is.
   - Optionally: if a caller has a `NodeRef`, they can pass `subject_ref=node_ref_to_subject_ref(node_ref)` and (if needed) build `object_snapshot` from `NodeSnapshot` (e.g. from an adapter). No change to atria_tools or API required for Phase 1.

5. **New code paths only**
   - Any **new** feature that needs cross-module identity or workspace/owner (e.g. “list all nodes for this user”, “link this task to this brief”) can use NodeRef/NodeSnapshot and the adapters. Existing features continue to use current entities and SubjectRef where they already do.

### Phase 3 (later, out of scope for “smallest now”)

- Add `workspace_id` / `owner_user_id` to VE (or other) storage only when you introduce real multi-tenant persistence; then adapters can read them and fill NodeRef/NodeSnapshot.
- Introduce a shared “node” table or graph only if/when you need global node ids and cross-module queries.

---

## 4. Which modules should get Node adapters first

| Order | Module | Entities | Rationale |
|-------|--------|----------|-----------|
| 1 | **Vision Execution** | task, project, initiative | Core execution hierarchy; parent/related ids are clear (project_id, initiative_id, dependency_ids). *(Legacy “subject/node adapter” idea retired — use SubjectRef + VE dicts.)* |
| 2 | **Content** | content_brief | Links to initiative/project/task map cleanly to parent_node_id and related_node_ids. |
| 3 | **Intake** | intake_item | Single “item” type; status/lane as status; minimal parent/related today. |

**Later (not required for smallest path):** idea, person, asset, decision, transcript artifact — add adapters when a concrete feature needs them in the node layer.

---

## 5. What should explicitly NOT be changed yet

| Area | Do not change |
|------|----------------|
| **VE storage and models** | No new columns, no migration of existing tables. No requirement to store `workspace_id` or `owner_user_id` in VE yet. |
| **Content types and storage** | No change to ContentBrief or content persistence. |
| **Intake storage** | No change to intake item schema or persistence. |
| **API contracts** | RunParams, council API, VE API, intake API keep current shapes. No mandatory `node_ref` or `workspace_id` in request/response. |
| **judgment_substrate.py** | SubjectRef, SubjectSnapshot, JudgmentSnapshot, SeatJudgment, CouncilRunArtifact stay as-is. No replacement by NodeRef in this file. |
| **atria_tools.py** | `run_council` and `run_council_stream` keep `subject_ref` and `object_snapshot`; no need to accept NodeRef directly unless we add a thin adapter at the call site. |
| **Frontend** | No new UI, no workspace or user selectors. Node layer is internal only. |
| **Persistence** | No new “nodes” table, no global node store. *(Tombstoned adapter modules are not a supported path.)* |

---

## 6. Summary

- **Schema:** NodeRef (identity + source_module + source_entity_id + optional workspace_id/owner_user_id) and NodeSnapshot (identity + title, status, parent_node_id, related_node_ids, optional visibility/scope, payload).
- **Location:** `local_ai/node_substrate.py` (types + normalize + node_ref_to_subject_ref). **`node_adapters.py` retired (tombstoned).** Prefer **`judgment_substrate.py`** for identity/judgment primitives.
- **Path:** Phase 1 originally included adapters — **superseded** by SubjectRef + JudgmentTrunk + VE persistence; historical Phase 2/3 notes below remain directional only.
- **Adapters:** Not in use; do not revive `node_adapters` / `subject_adapters`.
- **Do not change:** VE/Content/Intake storage and models, API contracts, judgment_substrate types, atria_tools signatures, frontend.

This keeps the Node substrate additive and internal, and reduces future retrofit cost for multi-user support, shared references, judgment targets, and cross-module linking without destabilizing current product behavior.
