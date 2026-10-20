"""Seed the "Meet your council" keystone initiative for a user.

Used by POST /auth/signup (after invite-code consume) and by the admin
backfill endpoint. Idempotent: a user who already has the initiative by key
is left untouched.

The seed *content* lives in local_ai/council/keystones.py (data edits there);
this module is the mechanics: initiative → 7 projects → 4 tasks each, chained
1→2→3→4 via task dependency_ids.
"""

from __future__ import annotations

from typing import Any

from local_ai.council import keystones as KD
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as S


def find_keystone_initiative(user_id: str) -> dict[str, Any] | None:
    """Return the user's keystone initiative if seeded, else None."""
    for initiative in S.list_initiatives(user_id):
        if (initiative or {}).get("seed_key") == KD.INITIATIVE_KEY:
            return initiative
    return None


def seed_meet_your_council(user_id: str) -> dict[str, Any]:
    """Seed the keystone initiative for a user. Idempotent.

    Returns {"initiative": <initiative dict>, "created": bool}.
    """
    existing = find_keystone_initiative(user_id)
    if existing is not None:
        return {"initiative": existing, "created": False}

    initiative = S.create_initiative(
        M.InitiativeCreate(
            title=KD.INITIATIVE_TITLE,
            brief=KD.INITIATIVE_BRIEF,
            status=KD.INITIATIVE_STATUS,
            seed_key=KD.INITIATIVE_KEY,
        ),
        user_id,
    )

    projects: list[dict[str, Any]] = []
    for seat in KD.SEATS:
        project = S.create_project(
            M.ProjectCreate(
                initiative_id=initiative["id"],
                title=KD.project_title(seat),
                brief=KD.project_brief(seat),
                status=KD.PROJECT_STATUS,
            ),
            user_id,
        )
        projects.append(project)

        previous_task_id: str | None = None
        for keystone in KD.keystones_for(seat):
            task = S.create_task(
                M.TaskCreate(
                    project_id=project["id"],
                    title=keystone["title"],
                    description=keystone["description"],
                    completion_criteria=keystone["completion_criteria"],
                    seat_ref=seat["seat_ref"],
                    dependency_ids=[previous_task_id] if previous_task_id else [],
                ),
                user_id,
            )
            previous_task_id = task["id"]

    return {"initiative": initiative, "created": True}


# ---------------------------------------------------------------------------
# Living Tree attention markers ("!")
#
# A seat that wants the user's attention carries a "!" marker over its node
# on the Living Tree — narrative guidance, never a push notification; the
# marker waits on the tree. Rules (Joshua's design):
#
# - The Conductor is the entry seat. Until its first keystone ("First
#   meeting") completes, ONLY the conductor carries a marker (reason
#   "intro" — the Weaver wants to talk about something).
# - Once the conductor's first keystone completes, every other seat with an
#   incomplete keystone chain carries a marker (reason "meet").
# - A seat whose keystones 1–3 are complete but whose keystone 4 ("The
#   echo" — the recognition conversation) is not carries reason
#   "recognition". (v1 proxy for readiness; true readiness detection is
#   separate future work.)
# - A seat with all four keystones Done carries no marker.
# - No initiative seeded → no markers, never an error.
# ---------------------------------------------------------------------------

#: The entry seat_ref — the seat flagged "entry" in the seed data (Conductor).
ENTRY_SEAT_REF: str = next(
    (s["seat_ref"] for s in KD.SEATS if s.get("entry") == "true"),
    KD.SEATS[0]["seat_ref"],
)

_DONE = "Done"


def _chain_order(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order one seat's keystone tasks 1→2→3→4 by dependency-chain depth.

    The seed chains each task to exactly the previous one, so a task's
    chain depth (number of ancestors) is its keystone index. Falls back
    gracefully on partial/odd data: unknown deps stop the walk.
    """
    by_id = {t["id"]: t for t in tasks if t.get("id")}

    def depth(task: dict[str, Any]) -> int:
        d = 0
        seen: set[str] = set()
        cur = task
        while True:
            deps = [x for x in (cur.get("dependency_ids") or []) if x in by_id]
            if not deps or deps[0] in seen:
                return d
            seen.add(deps[0])
            d += 1
            cur = by_id[deps[0]]

    return sorted(tasks, key=lambda t: depth(t))


def keystone_attention(user_id: str) -> dict[str, Any]:
    """Per-seat attention-marker state for the Living Tree.

    Returns {"seeded": bool, "markers": {seat_ref: {"attention": bool,
    "reason": "intro" | "meet" | "recognition" | None}}} covering all seven
    canonical seats. Read-only; an unseeded user gets seeded=False with no
    markers lit.
    """
    markers: dict[str, dict[str, Any]] = {
        seat["seat_ref"]: {"attention": False, "reason": None} for seat in KD.SEATS
    }
    initiative = find_keystone_initiative(user_id)
    if initiative is None:
        return {"seeded": False, "markers": markers}

    project_ids = {
        p["id"]
        for p in S.list_projects(user_id)
        if p.get("initiative_id") == initiative["id"]
    }
    tasks_by_seat: dict[str, list[dict[str, Any]]] = {}
    for task in S.list_tasks(user_id):
        if task.get("project_id") not in project_ids:
            continue
        ref = (task.get("seat_ref") or "").strip()
        if ref in markers:
            tasks_by_seat.setdefault(ref, []).append(task)

    chains: dict[str, list[bool]] = {}
    for ref, seat_tasks in tasks_by_seat.items():
        ordered = _chain_order(seat_tasks)
        chains[ref] = [t.get("status") == _DONE for t in ordered]

    def chain_of(ref: str) -> list[bool]:
        return chains.get(ref, [])

    entry_chain = chain_of(ENTRY_SEAT_REF)
    entry_intro_done = bool(entry_chain) and entry_chain[0]

    for seat in KD.SEATS:
        ref = seat["seat_ref"]
        done = chain_of(ref)
        if not done or all(done):
            continue  # nothing seeded for this seat, or chain complete
        if ref == ENTRY_SEAT_REF and not done[0]:
            markers[ref] = {"attention": True, "reason": "intro"}
        elif not entry_intro_done and ref != ENTRY_SEAT_REF:
            continue  # conductor first — the others wait for the intro
        elif len(done) >= 4 and all(done[:3]) and not done[3]:
            markers[ref] = {"attention": True, "reason": "recognition"}
        else:
            markers[ref] = {"attention": True, "reason": "meet"}

    return {"seeded": True, "markers": markers}
