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
