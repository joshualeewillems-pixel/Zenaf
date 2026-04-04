#!/usr/bin/env python3
"""
Active-now Vision Execution reseed (approved Section A only).

- Clears ideas / initiatives / projects / tasks for owner@local.atria only.
- Does NOT delete persons, assets, or core profiles.
- Tier B/C, matching expansion, radar expansion, substrate: excluded by design.

Run from repo root:
  python scripts/seed_vision_execution_active_now.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from local_ai.vision_execution import storage, models as M


def _clear_execution_graph(owner_id: str) -> None:
    for t in list(storage.list_tasks(owner_id)):
        storage.delete_task(t["id"], owner_id)
    for p in list(storage.list_projects(owner_id)):
        storage.delete_project(p["id"], owner_id)
    conn = storage.get_connection()
    inits = list(storage.list_initiatives(owner_id))
    for i in inits:
        conn.execute("DELETE FROM initiative_seats WHERE initiative_id = ?", (i["id"],))
    conn.commit()
    for i in inits:
        storage.delete_initiative(i["id"], owner_id)
    for idea in list(storage.list_ideas(owner_id)):
        storage.delete_idea(idea["id"], owner_id)


def main() -> None:
    failures: list[str] = []
    storage.get_connection()
    owner = storage.get_user_by_email("owner@local.atria")
    if not owner:
        raise SystemExit("owner@local.atria not found — bootstrap user first.")
    owner_id = owner["id"]

    print("Clearing user-scoped ideas/initiatives/projects/tasks…")
    _clear_execution_graph(owner_id)

    ideas_data: list[M.IdeaCreate] = [
        M.IdeaCreate(
            title="Intake mirror reflects poll reality",
            summary="Mirror sync state should update after a successful email poll.",
            description=(
                "Source: docs/01_TRUTH/ACTIVE_VS_PLANNED.md (Intake mirror sync state). "
                "docs/OPEN_QUESTIONS.md §2, §4."
            ),
            status="Contextualized",
            tags=[],
            created_by="",
            desired_outcome="",
        ),
        M.IdeaCreate(
            title="Truth convergence: council workspace + trace exempt registry",
            summary="Server-owned perspective JSON; Idea Lab removed; trace policy documented in aiTraceExemptRegistry.",
            description="Source: docs/01_TRUTH/TRUTH_CONVERGENCE.md; frontend/src/ai-actions/aiTraceExemptRegistry.ts.",
            status="Contextualized",
            tags=[],
            created_by="",
            desired_outcome="",
        ),
        M.IdeaCreate(
            title="Council packet and seats match documented truth order",
            summary="Packet order, mandate labels, and documented truth-source contract.",
            description=(
                "Source: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md (Steps 1–3). "
                "docs/ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE.md. "
                "docs/01_TRUTH/SYSTEM_REFERENCE.md §3.5."
            ),
            status="Contextualized",
            tags=[],
            created_by="",
            desired_outcome="",
        ),
        M.IdeaCreate(
            title="Assets/read are execution-legible in VE",
            summary="Linked vs required-by and reverse usage from existing VE data.",
            description="Source: docs/MATERIAL_ENTITY_NODE_DIRECTION.md §NOW.",
            status="Contextualized",
            tags=[],
            created_by="",
            desired_outcome="",
        ),
    ]

    created_ideas: list[dict] = []
    for spec in ideas_data:
        try:
            created_ideas.append(storage.create_idea(spec, owner_id))
        except Exception as e:
            failures.append(f"idea {spec.title!r}: {e}")

    id_by_key = {f"i{i+1}": created_ideas[i]["id"] for i in range(len(created_ideas))}

    def make_init(
        title: str,
        brief: str,
        *,
        status: str,
        source_key: str,
    ) -> dict | None:
        try:
            return storage.create_initiative(
                M.InitiativeCreate(
                    source_idea_id=id_by_key[source_key],
                    title=title,
                    brief=brief,
                    status=status,
                    owner_id=None,
                    next_step_ai="",
                    notes="Active-now reseed (approved Section A).",
                ),
                owner_id,
            )
        except Exception as e:
            failures.append(f"initiative {title!r}: {e}")
            return None

    n1 = make_init(
        "Intake operational honesty",
        "Poll completes; durable mirror sync state (and optional mailbox audit) reflects reality.",
        status="Active",
        source_key="i1",
    )
    n2 = make_init(
        "Council workspace persistence",
        "GET/PUT /vision-execution/council-workspace/perspectives; FE migration from localStorage.",
        status="Approved",
        source_key="i2",
    )
    n3 = make_init(
        "Council sharpness & truth contract",
        "Packet order, Risk/seat labels, truth-source documentation.",
        status="Active",
        source_key="i3",
    )
    n4 = make_init(
        "Material / asset presentation",
        "Execution-legible assets: linked vs required-by; reverse usage.",
        status="Active",
        source_key="i4",
    )

    if not all([n1, n2, n3, n4]):
        print("FAIL: missing initiative(s); aborting projects/tasks.")
        print("Failures:", failures)
        raise SystemExit(1)

    in1, in2, in3, in4 = n1["id"], n2["id"], n3["id"], n4["id"]

    projects_raw: list[M.ProjectCreate] = [
        M.ProjectCreate(
            initiative_id=in1,
            title="Wire successful poll → set_sync_state",
            brief=(
                "Call set_sync_state after successful poll. "
                "Source: docs/01_TRUTH/ACTIVE_VS_PLANNED.md; docs/OPEN_QUESTIONS.md §2, §4."
            ),
            status="Active",
            owner_id=None,
            priority="High",
            deliverables="Sync state updated after poll.",
            current_focus="intake poll handler",
            notes="Active-now",
        ),
        M.ProjectCreate(
            initiative_id=in1,
            title="Optional: log poll to mailbox_action",
            brief=(
                "If applicable after poll: record_mailbox_action. "
                "Source: docs/01_TRUTH/ACTIVE_VS_PLANNED.md (mailbox_action table)."
            ),
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Audit log entry path or documented deferral.",
            current_focus="intake",
            notes="Active-now optional",
        ),
        M.ProjectCreate(
            initiative_id=in2,
            title="Verify council-workspace API",
            brief="GET after login; PUT after editing perspectives. Source: TRUTH_CONVERGENCE.md.",
            status="Active",
            owner_id=None,
            priority="High",
            deliverables="SQLite user_council_workspace row for test user.",
            current_focus="api/routes/vision_execution.py",
            notes="Active-now",
        ),
        M.ProjectCreate(
            initiative_id=in2,
            title="Cross-session seat consistency",
            brief="Second browser or incognito: same seats after login (server truth).",
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Manual test note.",
            current_focus="App.tsx",
            notes="Active-now",
        ),
        M.ProjectCreate(
            initiative_id=in3,
            title="Reorder build_council_decision_packet",
            brief=(
                "Task-first packet order per NEXT_CLEANUP Step 1. "
                "Source: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md; local_ai/atria_tools.py."
            ),
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="Reordered blocks + comment.",
            current_focus="atria_tools.py",
            notes="Active-now",
        ),
        M.ProjectCreate(
            initiative_id=in3,
            title="Mandates UI: labels + Risk mandate",
            brief="Source: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md Step 2; frontend/src/mandates.ts.",
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="Display names + Risk mandate entry.",
            current_focus="frontend",
            notes="Active-now",
        ),
        M.ProjectCreate(
            initiative_id=in3,
            title="Truth-source subsection + inline order note",
            brief=(
                "docs/ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE.md + optional comment in atria_tools. "
                "Source: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md Step 3."
            ),
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Doc + inline reference.",
            current_focus="docs + atria_tools",
            notes="Active-now",
        ),
        M.ProjectCreate(
            initiative_id=in4,
            title="Asset UI: linked to vs required by",
            brief="Source: docs/MATERIAL_ENTITY_NODE_DIRECTION.md §NOW (1).",
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="Clear sections in VE Assets UI.",
            current_focus="VisionExecutionView / assets",
            notes="Active-now",
        ),
        M.ProjectCreate(
            initiative_id=in4,
            title="Reverse usage from loaded VE data",
            brief=(
                "Scan required_assets / required_asset_ids. "
                "Source: docs/MATERIAL_ENTITY_NODE_DIRECTION.md §NOW (2)."
            ),
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Deterministic summaries in UI.",
            current_focus="frontend",
            notes="Active-now",
        ),
        M.ProjectCreate(
            initiative_id=in1,
            title="End-to-end sanity check (poll → VE → council visibility)",
            brief=(
                "Validate operational chain: intake poll → durable/mirror state → what VE and council context see. "
                "Active-now extension (approved)."
            ),
            status="Active",
            owner_id=None,
            priority="High",
            deliverables="Documented pass/fail for the chain.",
            current_focus="intake + VE + council context",
            notes="Active-now e2e",
        ),
    ]

    proj_ids: list[str] = []
    for pcreate in projects_raw:
        try:
            row = storage.create_project(pcreate, owner_id)
            proj_ids.append(row["id"])
        except Exception as e:
            failures.append(f"project {pcreate.title!r}: {e}")
            proj_ids.append("")

    # (project_index, title, description, status)
    task_specs: list[tuple[int, str, str, str]] = [
        (0, "Locate post-success poll path", "File + function that completes poll. Source: OPEN_QUESTIONS.", "Todo"),
        (0, "Call set_sync_state with cursor/time", "Persist last poll per mirror_sync design. ACTIVE_VS_PLANNED.", "Todo"),
        (0, "Short note on cursor semantics", "Comment or doc for mirror_sync cursor. OPEN_QUESTIONS §4.", "Todo"),
        (2, "GET /vision-execution/council-workspace/perspectives", "Signed in; row_exists or migration.", "Todo"),
        (2, "Confirm debounced PUT after perspective edit", "Network + DB.", "Todo"),
        (4, "Edit build_council_decision_packet order only", "NEXT_CLEANUP Step 1; no new blocks.", "Todo"),
        (5, "Update BUILT_IN_MANDATES + add Risk mandate", "NEXT_CLEANUP Step 2.", "Todo"),
        (6, "Add truth-source subsection + optional order comment", "NEXT_CLEANUP Step 3.", "Todo"),
        (7, "Separate linked vs required-by in asset presentation", "MATERIAL_ENTITY §NOW.", "Todo"),
        (8, "Implement reverse required-asset scan in UI", "Initiatives/projects/tasks fields. MATERIAL_ENTITY §NOW.", "Todo"),
        (9, "Run poll; confirm mirror/queue updates observable", "Trace intake → mirror visibility.", "Todo"),
        (9, "Confirm council/agent context sees or documents VE state post-poll", "build_council_decision_packet / context. SYSTEM_REFERENCE.", "Todo"),
        (9, "Record any break in poll → VE → council chain", "Short note in ticket or notes.", "Todo"),
    ]

    for pi, title, desc, st in task_specs:
        pid = proj_ids[pi]
        if not pid:
            failures.append(f"task skipped (missing project index {pi}): {title!r}")
            continue
        try:
            storage.create_task(
                M.TaskCreate(
                    project_id=pid,
                    title=title,
                    description=desc,
                    status=st,
                    priority="Medium",
                    notes="seed_vision_execution_active_now.py",
                ),
                owner_id,
            )
        except Exception as e:
            failures.append(f"task {title!r}: {e}")

    n_ideas = len(storage.list_ideas(owner_id))
    n_inits = len(storage.list_initiatives(owner_id))
    n_projs = len(storage.list_projects(owner_id))
    n_tasks = len(storage.list_tasks(owner_id))

    print("--- Active-now reseed complete ---")
    print(f"Ideas: {n_ideas}, Initiatives: {n_inits}, Projects: {n_projs}, Tasks: {n_tasks}")
    if failures:
        print("Failures:")
        for f in failures:
            print(" ", f)
    else:
        print("Failures: none")


if __name__ == "__main__":
    main()
