#!/usr/bin/env python3
"""
Replace Vision Execution demo seed with an execution graph derived from in-repo
planning/docs (not generic product fiction).

- Clears ideas / initiatives / projects / tasks for the default local owner.
- Clears all persons, capacity_profiles, assets (demo-era global rows).
- Keeps one core profile for owner@local.atria (oldest by created_at); deletes extras.
- Inserts ideas, initiatives, projects, and tasks with description citations to source docs.

Run from repo root:
  python scripts/seed_vision_execution_from_repo_docs.py

Requires default owner user (bootstrap). See storage._DEFAULT_OWNER_EMAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from local_ai.vision_execution import storage, models as M

LC = "planning:low-confidence"  # user asked: default uncertain items toward "idea"


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


def _clear_demo_globals() -> None:
    """Remove all persons/assets (global tables) after demo seed removal."""
    for a in storage.list_assets():
        storage.delete_asset(a["id"])
    for p in storage.list_persons():
        try:
            storage.delete_person(p["id"])
        except Exception:
            conn = storage.get_connection()
            conn.execute("DELETE FROM capacity_profiles WHERE person_id = ?", (p["id"],))
            conn.execute("DELETE FROM persons WHERE id = ?", (p["id"],))
            conn.commit()


def _dedupe_core_profiles(owner_id: str) -> dict:
    profiles = storage.list_core_profiles(owner_id)
    if not profiles:
        return storage.create_core_profile(
            M.CoreProfileCreate(
                name="Atria build (from repo docs)",
                core_definition="Execution graph seeded from docs/ planning notes; adjust in VE UI.",
                current_goals="Close documented wiring gaps; align council and intake operational truth.",
                raw_notes="Seeded by scripts/seed_vision_execution_from_repo_docs.py",
            ),
            owner_id,
        )
    profiles.sort(key=lambda x: x.get("created_at") or "")
    keep = profiles[0]
    conn = storage.get_connection()
    for p in profiles[1:]:
        conn.execute("DELETE FROM core_profiles WHERE id = ? AND user_id = ?", (p["id"], owner_id))
    conn.commit()
    return keep


def _idea(
    title: str,
    summary: str,
    description: str,
    *,
    status: str = "Captured",
    tags: list[str] | None = None,
    low_confidence: bool = False,
) -> M.IdeaCreate:
    t = list(tags or [])
    if low_confidence:
        t.append(LC)
    return M.IdeaCreate(
        title=title,
        summary=summary,
        description=description,
        status=status,
        tags=t,
        created_by="",
        desired_outcome="",
    )


def main() -> None:
    storage.get_connection()
    owner = storage.get_user_by_email("owner@local.atria")
    if not owner:
        raise SystemExit("owner@local.atria not found — run API once to bootstrap users.")
    owner_id = owner["id"]

    print("Clearing user-scoped execution graph + global demo persons/assets…")
    _clear_execution_graph(owner_id)
    _clear_demo_globals()
    profile = _dedupe_core_profiles(owner_id)
    print("Kept core profile:", profile.get("id"), profile.get("name"))

    # --- Ideas (doc-sourced; uncertain → status Captured + low_confidence tag) ---
    ideas_spec = [
        _idea(
            "Truth convergence: charter + server-owned council perspectives",
            "Idea Lab stack removed; council seat definitions persist in user_council_workspace when signed in.",
            "Source: docs/01_TRUTH/TRUTH_CONVERGENCE.md; GET/PUT /vision-execution/council-workspace/perspectives.",
            status="Contextualized",
        ),
        _idea(
            "Intake poll should update mirror sync state",
            "mirror_sync APIs exist; poll does not call set_sync_state / mailbox_action.",
            "Source: docs/01_TRUTH/ACTIVE_VS_PLANNED.md (Intake mirror sync state). docs/OPEN_QUESTIONS.md §2, §4.",
            status="Contextualized",
        ),
        _idea(
            "Tier B/C queue content via policy layer",
            "get_item_with_content is implemented; no route or UI consumes it yet.",
            "Source: docs/01_TRUTH/ACTIVE_VS_PLANNED.md (Tier B/C). docs/OPEN_QUESTIONS.md §3.",
            status="Clarifying",
        ),
        _idea(
            "Council packet: task (context + question) before operator priorities",
            "Reorder blocks in build_council_decision_packet per cleanup proposal.",
            "Source: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md Step 1. Code: local_ai/atria_tools.build_council_decision_packet.",
            status="Contextualized",
        ),
        _idea(
            "Mandate UI aligned with seat taxonomy (incl. Risk)",
            "Rename mandate labels; add Risk mandate; optional Skeptic pairing.",
            "Source: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md Step 2. Files: frontend mandates.ts, perspectives, App.tsx.",
            status="Contextualized",
        ),
        _idea(
            "Document truth-source order for council",
            "Single documented contract for block order / weighting.",
            "Source: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md Step 3; docs/ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE.md.",
            status="Contextualized",
        ),
        _idea(
            "Adopt shared policy layer outside intake mirror",
            "Architecture calls for policy on Tier B/C paths; only mirror uses it today.",
            "Source: docs/01_TRUTH/ACTIVE_VS_PLANNED.md (Policy adoption). docs/ATRIA_ARCHITECTURE.md (intent).",
            status="Captured",
            low_confidence=True,
        ),
        _idea(
            "Asset / material-node clarity in Vision Execution UI",
            "Linked vs required-by; human-readable titles; reverse usage from VE data.",
            "Source: docs/MATERIAL_ENTITY_NODE_DIRECTION.md §NOW (priorities 1–3).",
            status="Contextualized",
        ),
        _idea(
            "Unify LLM access: adapters vs get_default_provider",
            "OPEN_QUESTIONS: registry vs direct provider as long-term contract.",
            "Source: docs/01_TRUTH/ACTIVE_VS_PLANNED.md; docs/OPEN_QUESTIONS.md §6.",
            status="Captured",
            low_confidence=True,
        ),
        _idea(
            "Configurable paths for intake mirror and Vision Execution DB",
            "Paths are fixed to repo layout today.",
            "Source: docs/OPEN_QUESTIONS.md §8.",
            status="Captured",
            low_confidence=True,
        ),
        _idea(
            "Server-side persistence for council perspectives",
            "Perspectives today live in browser localStorage only.",
            "Source: docs/OPEN_QUESTIONS.md §2.",
            status="Captured",
            low_confidence=True,
        ),
        _idea(
            "Judgment persistence beyond intake domain",
            "Judgment protocol is intake-mirror-only; VE/council unclear.",
            "Source: docs/OPEN_QUESTIONS.md §1.",
            status="Captured",
            low_confidence=True,
        ),
    ]

    created_ideas = [storage.create_idea(spec, owner_id) for spec in ideas_spec]
    ids = {f"i{i+1}": created_ideas[i]["id"] for i in range(len(created_ideas))}

    def ini(
        title: str,
        brief: str,
        *,
        status: str = "Active",
        source_key: str | None = None,
    ) -> str:
        sid = ids[source_key] if source_key else None
        row = storage.create_initiative(
            M.InitiativeCreate(
                source_idea_id=sid,
                title=title,
                brief=brief,
                status=status,
                owner_id=None,
                next_step_ai="",
                notes="Derived from docs/; see linked idea sources.",
            ),
            owner_id,
        )
        return row["id"]

    in1 = ini(
        "Intake sync, Tier B/C deferral, and policy completeness",
        "Wire poll→sync state when product needs it; Tier B/C remain internal until contract expands (TRUTH_CONVERGENCE).",
        status="Approved",
        source_key="i1",
    )
    in2 = ini(
        "Council sharpness and truth-source contract",
        "Packet reorder, mandate/seat UI alignment, document truth-source order.",
        status="Active",
        source_key="i4",
    )
    in3 = ini(
        "Policy and provider boundaries (pilot)",
        "Align cross-module policy adoption and clarify adapter vs provider LLM entry (pilot only).",
        status="Draft",
        source_key="i7",
    )
    in4 = ini(
        "Material / asset execution presentation",
        "Ship MATERIAL_ENTITY_NODE_DIRECTION §NOW priorities without schema rewrites.",
        status="Active",
        source_key="i8",
    )

    projects_raw: list[M.ProjectCreate] = [
        M.ProjectCreate(
            initiative_id=in1,
            title="Council workspace persistence verification",
            brief="Exercise GET/PUT /vision-execution/council-workspace/perspectives; confirm App.tsx migration from localStorage.",
            status="Active",
            owner_id=None,
            priority="High",
            deliverables="Signed-in users see consistent seats across sessions.",
            current_focus="api/routes/vision_execution.py + App.tsx",
            notes="docs/01_TRUTH/TRUTH_CONVERGENCE.md",
        ),
        M.ProjectCreate(
            initiative_id=in1,
            title="Wire email poll → mirror sync state",
            brief="Call set_sync_state after successful poll; consider record_mailbox_action.",
            status="Active",
            owner_id=None,
            priority="High",
            deliverables="Sync state reflects last poll; cursor semantics documented.",
            current_focus="intake poll handler",
            notes="docs/OPEN_QUESTIONS.md §2, §4",
        ),
        M.ProjectCreate(
            initiative_id=in1,
            title="Minimal Tier B/C read API",
            brief="Expose get_item_with_content via authenticated route with policy justification.",
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="One route + access level contract.",
            current_focus="api/routes intake",
            notes="docs/01_TRUTH/ACTIVE_VS_PLANNED.md Tier B/C",
        ),
        M.ProjectCreate(
            initiative_id=in2,
            title="Reorder council decision packet",
            brief="Context → Question → recent tool summary → operator priorities → constraints.",
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="build_council_decision_packet updated + comment.",
            current_focus="local_ai/atria_tools.py",
            notes="NEXT_CLEANUP_STEPS Step 1",
        ),
        M.ProjectCreate(
            initiative_id=in2,
            title="Mandate display + Risk mandate",
            brief="frontend/src/mandates.ts: names; add risk id; optional Skeptic.",
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="UI matches canonical seat labels.",
            notes="NEXT_CLEANUP_STEPS Step 2",
        ),
        M.ProjectCreate(
            initiative_id=in2,
            title="Truth-source documentation pass",
            brief="ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE + optional order tuple in atria_tools.",
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Doc subsection + inline comment.",
            notes="NEXT_CLEANUP_STEPS Step 3",
        ),
        M.ProjectCreate(
            initiative_id=in3,
            title="Policy adoption pilot (council + intake body)",
            brief="When council touches queue body, route through request_access / get_item_with_content.",
            status="Draft",
            owner_id=None,
            priority="Low",
            deliverables="Decision doc or one pilot call site.",
            notes="OPEN_QUESTIONS §5; architecture intent",
        ),
        M.ProjectCreate(
            initiative_id=in3,
            title="LLM call-site inventory (adapter vs provider)",
            brief="List atria_tools/council call sites vs adapter registry.",
            status="Draft",
            owner_id=None,
            priority="Low",
            deliverables="Short inventory in docs or ticket.",
            notes="ACTIVE_VS_PLANNED adapters",
        ),
        M.ProjectCreate(
            initiative_id=in4,
            title="Asset UI: linked vs required-by",
            brief="Summary strip; human-readable titles; states per MATERIAL doc.",
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="Clear sections in Assets/VE UI.",
            notes="MATERIAL_ENTITY_NODE_DIRECTION §NOW item 1",
        ),
        M.ProjectCreate(
            initiative_id=in4,
            title="Reverse usage from loaded VE data",
            brief="Deterministic scan required_assets / required_asset_ids across initiatives/projects/tasks.",
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Derived summaries in UI.",
            notes="MATERIAL_ENTITY_NODE_DIRECTION §NOW item 2",
        ),
    ]

    proj_ids: list[str] = []
    for pcreate in projects_raw:
        row = storage.create_project(pcreate, owner_id)
        proj_ids.append(row["id"])

    # Tasks (project index matches projects_raw order)
    task_specs: list[tuple[int, str, str, str]] = [
        (0, "Call GET /vision-execution/council-workspace/perspectives", "After login; expect row_exists or migration.", "Todo"),
        (0, "Edit a perspective; confirm PUT debounces", "Network tab; SQLite user_council_workspace.", "Todo"),
        (1, "Locate intake poll success path", "File + function that completes poll.", "Todo"),
        (1, "Invoke set_sync_state after successful poll", "Persist last_poll_at / cursor per OPEN_QUESTIONS.", "Todo"),
        (1, "Document cursor semantics for mirror_sync", "Short note in docs or code comment.", "Todo"),
        (2, "Design Tier B route contract", "Access level + justification + errors.", "Todo"),
        (2, "Implement GET (or POST) using get_item_with_content", "Auth-scoped; no raw bypass.", "Todo"),
        (3, "Edit build_council_decision_packet order", "Per NEXT_CLEANUP Step 1 only.", "Todo"),
        (3, "Add one-line packet order comment", "Reference doc.", "Todo"),
        (4, "Update BUILT_IN_MANDATES display names", "strategist→Strategy, etc.", "Todo"),
        (4, "Add Risk mandate entry", "id risk; backend accepts string ids.", "Todo"),
        (5, "Add 'Intended truth-source order' subsection", "ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE.md", "Todo"),
        (5, "Optional: order tuple comment in atria_tools", "Non-behavioral.", "Todo"),
        (6, "Record policy decision for council+intake", "Approved approach or defer.", "Todo"),
        (6, "If approved: one pilot call site", "Smallest integration.", "Todo"),
        (7, "Grep LLM call sites", "providers vs adapters.", "Todo"),
        (7, "Write inventory summary", "docs or ADR snippet.", "Todo"),
        (8, "Asset list/detail: separate linked vs required", "Match MATERIAL §NOW.", "Todo"),
        (8, "Replace raw id display where titles exist", "Use loaded VE entities.", "Todo"),
        (9, "Implement reverse required-asset scan", "Initiatives/projects/tasks JSON fields.", "Todo"),
        (9, "Surface summary strings in UI", "Unused / linked / required-by active work.", "Todo"),
    ]

    for pi, title, desc, st in task_specs:
        pid = proj_ids[pi]
        storage.create_task(
            M.TaskCreate(
                project_id=pid,
                title=title,
                description=desc,
                status=st,
                priority="Medium" if st == "Todo" else "Medium",
                notes="From repo docs seed; adjust in VE.",
            ),
            owner_id,
        )

    print(f"Created {len(created_ideas)} ideas, 4 initiatives, {len(proj_ids)} projects, {len(task_specs)} tasks.")
    print("Ideas tagged", LC, "are planning-low-confidence (architectural/open questions).")
    print("Done.")


if __name__ == "__main__":
    main()
