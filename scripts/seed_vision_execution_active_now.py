#!/usr/bin/env python3
"""
Active-now Vision Execution reseed (approved Section A only).

- Clears ideas / initiatives / projects / tasks for owner@local.zenaf only.
- Does NOT delete persons, assets, or core profiles.
- Tier B/C, matching expansion, radar expansion, substrate: excluded by design.

Run from repo root:
  python scripts/seed_vision_execution_active_now.py
"""
from __future__ import annotations

import argparse
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
    ap = argparse.ArgumentParser(description="Active-now Vision Execution reseed for one user.")
    ap.add_argument(
        "--user-email",
        default="owner@local.zenaf",
        help="Account to seed (default: owner@local.zenaf). Examples: phil@local.zenaf, phil@local.atria",
    )
    args = ap.parse_args()
    email = (args.user_email or "").strip()
    if not email:
        raise SystemExit("--user-email cannot be empty")

    failures: list[str] = []
    storage.get_connection()
    owner = storage.get_user_by_email(email)
    if not owner:
        raise SystemExit(f"{email!r} not found — bootstrap user first.")
    owner_id = owner["id"]
    print(f"Active-now reseed for {email} (id={owner_id})…")

    print("Clearing user-scoped ideas/initiatives/projects/tasks…")
    _clear_execution_graph(owner_id)

    ideas_data: list[M.IdeaCreate] = [
        M.IdeaCreate(
            title="Email poll results should show up in mirror sync status",
            summary="When polling finishes successfully, stored sync metadata should match what just happened.",
            description=(
                "Status: partially built — APIs exist, but the poll success path still needs to write durable state. "
                "See docs/01_TRUTH/ACTIVE_VS_PLANNED.md and docs/OPEN_QUESTIONS.md for background."
            ),
            status="Contextualized",
            tags=[],
            created_by="",
            desired_outcome="Dashboards and diagnostics never claim the inbox is fresh when it is not.",
        ),
        M.IdeaCreate(
            title="Council seats and traces should follow one clear rulebook",
            summary="Advisor seats belong to the signed-in account on the server; sensitive AI actions declare trace rules explicitly.",
            description=(
                "Status: largely aligned — council workspace persistence shipped directionally; trace exemptions live in a registry. "
                "See docs/01_TRUTH/TRUTH_CONVERGENCE.md."
            ),
            status="Contextualized",
            tags=[],
            created_by="",
            desired_outcome="No more guessing whether seats are local-only or which AI steps skip logging.",
        ),
        M.IdeaCreate(
            title="Council briefs, seat names, and docs should tell the same story",
            summary="Reorder the automatic council packet, fix on-screen advisor labels (including risk), and document reading order.",
            description=(
                "Status: planned cleanup steps — docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md, "
                "docs/ZENAF_PROMPT_AND_TRUTH_ARCHITECTURE.md, docs/01_TRUTH/SYSTEM_REFERENCE.md."
            ),
            status="Contextualized",
            tags=[],
            created_by="",
            desired_outcome="Council output reads like advice on your question, with roles and sources everyone recognizes.",
        ),
        M.IdeaCreate(
            title="Assets should explain how work depends on them",
            summary="Show linked context versus hard requirements, prefer titles over raw IDs, and surface reverse lookups.",
            description=(
                "Status: direction documented; UI still evolving. See docs/MATERIAL_ENTITY_NODE_DIRECTION.md."
            ),
            status="Contextualized",
            tags=[],
            created_by="",
            desired_outcome="Open an asset and immediately see whether it blocks delivery and who relies on it.",
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
                    notes="Active-now seed: focused on intake honesty, council workspace, council brief quality, and asset clarity.",
                ),
                owner_id,
            )
        except Exception as e:
            failures.append(f"initiative {title!r}: {e}")
            return None

    n1 = make_init(
        "Honest email intake status",
        "Finish wiring so a successful poll updates mirror sync metadata (and optionally mailbox audit) that downstream views trust.",
        status="Active",
        source_key="i1",
    )
    n2 = make_init(
        "Council workspace on the server",
        "Prove advisor seats load and save through the Vision & Execution API for signed-in users instead of disappearing with the browser cache.",
        status="Approved",
        source_key="i2",
    )
    n3 = make_init(
        "Sharper council briefs and documented truth order",
        "Reorder the automatic packet, align mandate labels (including risk), and capture the intended reading order in docs.",
        status="Active",
        source_key="i3",
    )
    n4 = make_init(
        "Assets that read like execution facts",
        "Separate casual links from true requirements, show friendly names, and derive “required by” summaries from existing graph data.",
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
            title="Persist sync metadata after a successful inbox poll",
            brief=(
                "Hook the poll-success path so mirror sync timestamps and cursor data update immediately — "
                "the same fields Vision & Execution and diagnostics read."
            ),
            status="Active",
            owner_id=None,
            priority="High",
            deliverables="Observable state change in storage right after a successful poll run.",
            current_focus="Email intake polling flow",
            notes="Background: docs/01_TRUTH/ACTIVE_VS_PLANNED.md, docs/OPEN_QUESTIONS.md",
        ),
        M.ProjectCreate(
            initiative_id=in1,
            title="Optional audit trail entry when polling completes",
            brief=(
                "If we want a mailbox audit log, record a concise entry after polls; otherwise document why we deferred it."
            ),
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Either a working log write or an explicit deferral note with rationale.",
            current_focus="Intake persistence layer",
            notes="Background: docs/01_TRUTH/ACTIVE_VS_PLANNED.md",
        ),
        M.ProjectCreate(
            initiative_id=in2,
            title="Exercise the council workspace API end to end",
            brief=(
                "After login, fetch advisor seats from the server, edit them, and confirm saves land in the Vision & Execution database."
            ),
            status="Active",
            owner_id=None,
            priority="High",
            deliverables="Repeatable steps proving GET/PUT behave for a real user row.",
            current_focus="Vision & Execution API routes",
            notes="Background: docs/01_TRUTH/TRUTH_CONVERGENCE.md",
        ),
        M.ProjectCreate(
            initiative_id=in2,
            title="Confirm seats match across browsers and sessions",
            brief=(
                "Log in from a second profile or device and verify the same advisor lineup — evidence the server is canonical."
            ),
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Short written test result (pass/fail) with screenshots or notes.",
            current_focus="Main application shell",
            notes="Active-now QA",
        ),
        M.ProjectCreate(
            initiative_id=in3,
            title="Reorder the automatic council decision brief",
            brief=(
                "Lead with your context and question before tool summaries and priorities, per the cleanup proposal."
            ),
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="Updated packet assembly plus a pointer to the governing doc.",
            current_focus="Local AI council packet builder",
            notes="Background: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md",
        ),
        M.ProjectCreate(
            initiative_id=in3,
            title="Refresh mandate labels and add risk as a first-class seat",
            brief=(
                "Rename on-screen advisor roles to match the documented taxonomy and ensure risk appears everywhere mandates are listed."
            ),
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="UI/config alignment reviewers can check in one pass.",
            current_focus="Frontend mandates and perspectives",
            notes="Background: NEXT_CLEANUP proposal step 2",
        ),
        M.ProjectCreate(
            initiative_id=in3,
            title="Document council truth order and echo it in code comments",
            brief=(
                "Add a concise subsection to the prompt/truth architecture doc and optionally mirror the order in a comment beside packet assembly."
            ),
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Published doc change plus optional non-functional code note.",
            current_focus="Docs and council tooling",
            notes="Background: NEXT_CLEANUP proposal step 3",
        ),
        M.ProjectCreate(
            initiative_id=in4,
            title="Separate “linked” assets from “required to proceed”",
            brief=(
                "Adjust asset detail UI so casual references do not look like hard blockers, following the material-entity direction doc."
            ),
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="Layouts reviewers can understand without reading schema definitions.",
            current_focus="Vision & Execution asset panels",
            notes="Background: docs/MATERIAL_ENTITY_NODE_DIRECTION.md",
        ),
        M.ProjectCreate(
            initiative_id=in4,
            title="Derive reverse usage summaries from loaded execution data",
            brief=(
                "Scan initiatives, projects, and tasks for required asset fields and show plain-language summaries such as “blocks these two projects.”"
            ),
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Deterministic UI text with no manual duplicate entry.",
            current_focus="Client-side graph already in memory",
            notes="Background: docs/MATERIAL_ENTITY_NODE_DIRECTION.md",
        ),
        M.ProjectCreate(
            initiative_id=in1,
            title="End-to-end check: poll → Vision & Execution → council context",
            brief=(
                "Run a poll, confirm mirror state and execution data look right, then inspect what the council packet would include — "
                "record any break in the chain."
            ),
            status="Active",
            owner_id=None,
            priority="High",
            deliverables="Written pass/fail narrative with pointers to any bugs filed.",
            current_focus="Intake, Vision & Execution, and council context together",
            notes="Active-now integration smoke test",
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
        (0, "Trace the poll success path in code", "Identify the function that runs immediately after a poll succeeds.", "Todo"),
        (0, "Write sync metadata when the poll succeeds", "Persist timestamps/cursor data the mirror already knows how to read.", "Todo"),
        (0, "Document what the inbox cursor means", "Add a short comment or doc so future edits do not corrupt ordering.", "Todo"),
        (2, "Fetch council workspace right after login", "Expect a real payload or a defined empty state — not a silent failure.", "Todo"),
        (2, "Edit a seat and confirm debounced save", "Watch network traffic and the database row to ensure one stable write.", "Todo"),
        (4, "Apply only the approved packet reorder", "Implement cleanup step one without inventing new sections.", "Todo"),
        (5, "Update mandate names and add risk", "Match architecture vocabulary everywhere mandates appear.", "Todo"),
        (6, "Ship the truth-order doc plus optional code note", "Docs first; code comment mirrors but does not change behavior alone.", "Todo"),
        (7, "Rework asset layout for linked vs required", "Follow the material-entity NOW checklist for clarity.", "Todo"),
        (8, "Build reverse lookups from graph data", "Derive summaries from initiatives, projects, and tasks already loaded.", "Todo"),
        (9, "Poll email and watch mirror-facing state", "Confirm queues and sync indicators move as expected.", "Todo"),
        (9, "Inspect council context after the poll", "Ensure execution summaries feeding the council match the new mirror truth.", "Todo"),
        (9, "Log any broken link in the chain", "Capture repro notes so the team can file targeted fixes.", "Todo"),
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
                    notes="Active-now seed task — edit status as you complete work.",
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
