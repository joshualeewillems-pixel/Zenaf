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


def _assert_single_entry_seat() -> str:
    """The entry-seat invariant: exactly one seat carries entry=true.

    Returns that seat's ref. Raises ValueError naming the count and the
    flagged seats otherwise — never silently falls back to a default
    seat, so a missing or duplicated flag fails loudly at import and
    at seeding instead of restoring Conductor-first behavior.
    """
    flagged = [s["seat_ref"] for s in KD.SEATS if s.get("entry") == "true"]
    if len(flagged) != 1:
        if not flagged:
            raise ValueError(
                "no entry seat configured: exactly one seat must carry "
                'entry="true"'
            )
        raise ValueError(
            f"multiple entry seats configured: {flagged} — exactly one "
            'seat must carry entry="true"'
        )
    return flagged[0]


def seed_meet_your_council(user_id: str) -> dict[str, Any]:
    """Seed the keystone initiative for a user. Idempotent.

    Returns {"initiative": <initiative dict>, "created": bool}.
    """
    # Seed-time assertion (§5): the data being seeded carries exactly
    # one entry seat — a bad seed file fails here, not at first use.
    _assert_single_entry_seat()
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
# - The Guardian is the entry seat. Until its first keystone ("First
#   meeting") completes, ONLY the guardian carries a marker (reason
#   "intro" — the Guardian wants to talk about something).
# - Once the guardian's first keystone completes, the guided journey
#   offers the next seat ONE AT A TIME in JOURNEY_ORDER: only the
#   first seat after the entry whose first keystone is undone carries
#   a marker (reason "meet"). Later seats stay dark until their
#   predecessor's first keystone is Done.
# - STICKY ACCESS, NOT STICKY MARKERS (disposition correction 1):
#   once a seat's begin door has become available it stays available
#   even if the entry seat's task later returns to Todo (Guardian
#   restart or Reopen toggle) — the door sticks via the seat_unlocks
#   table, recorded when the entry keystone-1 task flips to Done
#   (both Done paths — genuine meeting close and bare task toggle —
#   funnel through the VE task update). Markers are a pure function
#   of current keystone states + JOURNEY_ORDER: a recorded seat does
#   NOT keep a lit marker merely because it was recorded. If the
#   entry keystone returns to Todo, "intro" re-lights on the Guardian
#   and "meet" goes dark, while every previously unlocked door stays
#   beginnable. A seat that never lit stays locked behind
#   Guardian-first ordering.
#   Guardian's own marker/door/face logic is unchanged by stickiness.
# - A seat whose keystones 1–3 are complete but whose keystone 4 ("The
#   echo" — the recognition conversation) is not carries reason
#   "recognition". (v1 proxy for readiness; true readiness detection is
#   separate future work.) Recognition is a per-seat milestone,
#   independent of journey position and of the entry intro: it lights
#   even while an earlier seat still carries "meet", or while the
#   entry intro is undone.
# - A seat with all four keystones Done carries no marker.
# - No initiative seeded → no markers, never an error.
# ---------------------------------------------------------------------------

#: The entry seat_ref — the seat flagged "entry" in the seed data (Guardian).
#: Exactly one seat must carry the flag: the derivation raises ValueError
#: at import time otherwise (no SEATS[0] fallback — a missing flag must
#: never silently restore Conductor-first behavior).
ENTRY_SEAT_REF: str = _assert_single_entry_seat()

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


def seat_unlocked(user_id: str, seat_ref: str) -> bool:
    """Whether the seat's begin door has become available and stuck.

    Reads the seat_unlocks table written by maybe_record_entry_unlock.
    Never raises: any read failure degrades to False (fail closed —
    the pre-sticky behavior), so a storage problem can neither invent
    a door nor break the tree or the begin guard.
    """
    try:
        return (seat_ref or "").strip() in S.get_seat_unlocks(user_id)
    except Exception:
        return False


def maybe_record_entry_unlock(user_id: str, task: dict[str, Any]) -> bool:
    """Record sticky unlocks when the entry seat's keystone-1 task flips Done.

    Called from the VE task-update path (both Done paths — genuine
    meeting close via _do_reveal and the bare Execution-view toggle —
    funnel through it, so neither can unlock without recording). The
    check is exact, not heuristic: the task must be Done, belong to
    the entry seat, belong to the user's keystone initiative, and be
    first in its seat's dependency chain. On success, all six
    non-entry seats are recorded (idempotent): every seat with an
    incomplete chain lights at entry completion, and a complete-chain
    seat needs no row — its door is already the revisit door via its
    own face reveal, and the marker loop below skips complete chains
    regardless. Returns True when rows were written. Storage errors
    propagate (the storage-layer caller guards the call so a recording
    failure never breaks the task update itself).
    """
    if (task or {}).get("status") != _DONE:
        return False
    if (task or {}).get("seat_ref") != ENTRY_SEAT_REF:
        return False
    initiative = find_keystone_initiative(user_id)
    if initiative is None:
        return False
    project_ids = {
        p["id"]
        for p in S.list_projects(user_id)
        if p.get("initiative_id") == initiative["id"]
    }
    if task.get("project_id") not in project_ids:
        return False
    mine = [
        t
        for t in S.list_tasks(user_id)
        if t.get("project_id") in project_ids
        and (t.get("seat_ref") or "") == ENTRY_SEAT_REF
    ]
    ordered = _chain_order(mine)
    if not ordered or ordered[0].get("id") != task.get("id"):
        return False
    others = [s["seat_ref"] for s in KD.SEATS if s["seat_ref"] != ENTRY_SEAT_REF]
    S.record_seat_unlocks(user_id, others)
    return True


def keystone_attention(user_id: str) -> dict[str, Any]:
    """Per-seat attention-marker state for the Living Tree.

    Returns {"seeded": bool, "markers": {seat_ref: {"attention": bool,
    "reason": "intro" | "meet" | "recognition" | None}}} covering all seven
    canonical seats. Read-only in output (same shape as before).

    Marker rules (Guardian-first, one-at-a-time journey offering):
    "intro" only on the entry seat while its first keystone is undone;
    "meet" only on the first seat in JOURNEY_ORDER after the entry
    whose first keystone is undone (one at a time, once the entry
    keystone is Done); "recognition" when keystones 1-3 are Done and
    the 4th is pending — a per-seat milestone, independent of journey
    position and of the entry intro. Markers are a pure function of
    current keystone states + JOURNEY_ORDER: seat_unlocks governs gate
    begin-ability only and never lights a marker. A mid-chain seat
    (intro Done, chain incomplete) carries no marker until the
    recognition stage. An unseeded user gets seeded=False with no
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
    # One-at-a-time journey offering (O-I-6): once the entry keystone
    # is Done, exactly one seat carries "meet" — the first seat after
    # the entry in JOURNEY_ORDER whose first keystone is undone.
    # Sticky access lives in seat_unlocks (the gate reads it); the
    # marker loop never consults unlocks, so a reopened entry
    # keystone darkens "meet" and re-lights "intro" while the doors
    # stay open.
    next_meet: str | None = None
    if entry_intro_done:
        for ref in KD.JOURNEY_ORDER:
            if ref == ENTRY_SEAT_REF:
                continue
            done = chain_of(ref)
            if done and not done[0]:
                next_meet = ref
                break

    for seat in KD.SEATS:
        ref = seat["seat_ref"]
        done = chain_of(ref)
        if not done or all(done):
            continue  # nothing seeded for this seat, or chain complete
        if ref == ENTRY_SEAT_REF and not done[0]:
            markers[ref] = {"attention": True, "reason": "intro"}
        elif len(done) >= 4 and all(done[:3]) and not done[3]:
            # Recognition is a per-seat milestone, independent of
            # journey position and of the entry intro: it is checked
            # before any entry gate, so it lights even while the
            # entry intro is undone or an earlier seat carries "meet".
            markers[ref] = {"attention": True, "reason": "recognition"}
        elif ref == next_meet:
            # "meet" lights only while the seat's first keystone is
            # undone. Once the intro is Done the seat goes dark until
            # the recognition stage — a mid-chain seat carries no
            # marker (a completed first meeting must not keep "!"
            # over the seat until the whole chain is Done).
            markers[ref] = {"attention": True, "reason": "meet"}

    return {"seeded": True, "markers": markers}
