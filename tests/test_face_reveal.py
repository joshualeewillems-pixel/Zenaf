"""Face reveal gate tests (Joshua's first live run, 2026-10-23).

The keystone design makes a seat's first meeting the reveal of its
name, face, and demeanor. But the face gate in naming.py predated the
meetings and only listened to training depth — so Joshua completed the
Conductor's first meeting and the Weaver's page still showed ??? with
"10 more depth to go". These tests pin the reconciliation: keystone 1
completion reveals the assigned fellowship face (face_revealed), while
customization (avatar_unlocked) stays on the depth milestone alone.
"""

from __future__ import annotations

import threading

import pytest


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (test_meetings pattern)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _seeded_user(email="face@example.com"):
    from local_ai.vision_execution import keystone_seeding
    from local_ai.vision_execution import service as ve

    user = ve.create_user_account(email, "pw", "Face")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _entry(status: dict, archetype_id: str) -> dict:
    return next(e for e in status["archetypes"] if e["id"] == archetype_id)


def test_face_hidden_before_any_meeting(ve_ctx):
    from local_ai.council import naming

    uid = _seeded_user()
    entry = _entry(naming.rename_status(uid), "conductor")
    assert entry["face_revealed"] is False
    assert entry["avatar_unlocked"] is False  # no training depth either


def test_first_meeting_reveals_face_but_not_customization(ve_ctx):
    from local_ai.conversation.meeting import _seat_keystone_tasks
    from local_ai.council import naming
    from local_ai.vision_execution import models as ve_models
    from local_ai.vision_execution import service as ve

    uid = _seeded_user()
    k1 = _seat_keystone_tasks(uid, "conductor")[0]
    ve.update_task(k1["id"], ve_models.TaskUpdate(status="Done"), uid)

    status = naming.rename_status(uid)
    conductor = _entry(status, "conductor")
    assert conductor["face_revealed"] is True
    # Customization is a different door and stays depth-gated.
    assert conductor["avatar_unlocked"] is False
    # Other seats are untouched by the Conductor's meeting.
    assert _entry(status, "mentor")["face_revealed"] is False


def test_keystone_one_done_never_raises_for_unknown_user(ve_ctx):
    from local_ai.council import naming

    assert naming.keystone_one_done(None, "conductor") is False
    assert naming.keystone_one_done("no-such-user", "conductor") is False
