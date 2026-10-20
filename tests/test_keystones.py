"""Keystone initiative seeding: "Meet your council" default-to-every-account.

Covers:
- seed data integrity (7 seats, 4 keystones, valid canonical seat_refs)
- signup hook: a new account gets exactly 1 initiative / 7 projects / 28 tasks
- dependency chains 1→2→3→4 per project, tasks carry seat_refs
- idempotency (double-seed creates nothing)
- admin backfill endpoint (one user by email; all users when omitted)
- the seed_key / seat_ref column migration for pre-existing DBs

Integration tests run against a real temp SQLite DB (same fixture pattern as
test_idea_graduation); endpoint tests follow the test_invites fake pattern.
"""
from __future__ import annotations

import sqlite3
import threading
import types

import pytest
from fastapi import HTTPException

from local_ai.council import archetypes
from local_ai.council import keystones as KD
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve

KEYSTONE_TITLES = ["First meeting", "Strengths", "Weaknesses", "The echo"]


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the VE SQLite DB per test."""
    import local_ai.vision_execution.storage as ve_store

    ve_db = tmp_path / "ve.db"
    monkeypatch.setattr(ve_store, "_DB_PATH", ve_db)
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _make_user(email="ally@example.com"):
    return ve.create_user_account(email, "pw-hunter2", "Ally")


# ------------------------------------------------------------- seed data


def test_seed_data_shape():
    assert KD.INITIATIVE_KEY == "meet-your-council"
    assert KD.INITIATIVE_TITLE == "Meet your council"
    assert len(KD.SEATS) == 7
    seat_refs = [s["seat_ref"] for s in KD.SEATS]
    assert len(set(seat_refs)) == 7
    # Every seat_ref is a canonical archetype id.
    assert set(seat_refs) == set(archetypes.stock_archetype_ids())
    for seat in KD.SEATS:
        assert seat["character"]
        assert seat["demeanor"]
        assert seat["echo"]
        keystones = KD.keystones_for(seat)
        assert [k["title"] for k in keystones] == KEYSTONE_TITLES
        for k in keystones:
            # No quote/motto fields anywhere in the unlock content.
            assert set(k.keys()) == {"title", "description", "completion_criteria"}
            assert k["description"]
            assert k["completion_criteria"]


# ------------------------------------------------------------- seeding


def _seeded_counts(user_id):
    return (
        ve.list_initiatives(user_id),
        ve.list_projects(user_id),
        ve.list_tasks(user_id),
    )


def test_seed_creates_full_structure(ve_ctx):
    user = _make_user()
    result = keystone_seeding.seed_meet_your_council(user["id"])
    assert result["created"] is True

    initiatives, projects, tasks = _seeded_counts(user["id"])
    assert len(initiatives) == 1
    initiative = initiatives[0]
    assert initiative["title"] == "Meet your council"
    assert initiative["status"] == "Active"
    assert initiative["seed_key"] == "meet-your-council"

    assert len(projects) == 7
    expected_titles = {KD.project_title(s) for s in KD.SEATS}
    assert {p["title"] for p in projects} == expected_titles
    for p in projects:
        assert p["initiative_id"] == initiative["id"]
        assert p["status"] == "Ready"

    assert len(tasks) == 28


def test_seed_dependency_chain_and_seat_refs(ve_ctx):
    user = _make_user()
    keystone_seeding.seed_meet_your_council(user["id"])

    seat_by_project_title = {
        KD.project_title(s): s["seat_ref"] for s in KD.SEATS
    }
    projects = ve.list_projects(user["id"])
    for project in projects:
        ptasks = ve.list_tasks(user["id"], project_id=project["id"])
        assert len(ptasks) == 4
        # Every task carries the project's seat_ref.
        assert all(
            t["seat_ref"] == seat_by_project_title[project["title"]]
            for t in ptasks
        )
        by_title = {t["title"]: t for t in ptasks}
        assert set(by_title.keys()) == set(KEYSTONE_TITLES)
        # Chain: 1 → 2 → 3 → 4, each depending on exactly the previous.
        assert by_title["First meeting"]["dependency_ids"] == []
        assert by_title["Strengths"]["dependency_ids"] == [
            by_title["First meeting"]["id"]
        ]
        assert by_title["Weaknesses"]["dependency_ids"] == [
            by_title["Strengths"]["id"]
        ]
        assert by_title["The echo"]["dependency_ids"] == [
            by_title["Weaknesses"]["id"]
        ]


def test_seed_is_idempotent(ve_ctx):
    user = _make_user()
    first = keystone_seeding.seed_meet_your_council(user["id"])
    second = keystone_seeding.seed_meet_your_council(user["id"])
    assert first["created"] is True
    assert second["created"] is False
    assert second["initiative"]["id"] == first["initiative"]["id"]

    initiatives, projects, tasks = _seeded_counts(user["id"])
    assert len(initiatives) == 1
    assert len(projects) == 7
    assert len(tasks) == 28


def test_seed_is_per_user(ve_ctx):
    u1 = _make_user("one@example.com")
    u2 = _make_user("two@example.com")
    keystone_seeding.seed_meet_your_council(u1["id"])
    assert len(ve.list_initiatives(u2["id"])) == 0
    keystone_seeding.seed_meet_your_council(u2["id"])
    assert len(ve.list_initiatives(u2["id"])) == 1
    assert len(ve.list_tasks(u1["id"])) == 28
    assert len(ve.list_tasks(u2["id"])) == 28


# ------------------------------------------------------------- migration


def test_migration_adds_columns_to_old_db(tmp_path):
    """A DB created before seed_key/seat_ref existed gets them via migration."""
    import local_ai.vision_execution.storage as ve_store

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE initiatives (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
    conn.commit()
    ve_store._migrate_keystone_columns(conn)
    cols_i = {r[1] for r in conn.execute("PRAGMA table_info(initiatives)")}
    cols_t = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    assert "seed_key" in cols_i
    assert "seat_ref" in cols_t
    # Running twice is safe (idempotent).
    ve_store._migrate_keystone_columns(conn)
    conn.close()


# ------------------------------------------------------- signup hook


class _FakeRequest:
    def __init__(self, host="9.9.9.9"):
        self.headers = {}
        self.client = types.SimpleNamespace(host=host)
        self.cookies = {}


class _FakeResponse:
    def __init__(self):
        self.cookies = {}

    def set_cookie(self, key, value, **kwargs):
        self.cookies[key] = value


@pytest.fixture()
def signup_ctx(monkeypatch):
    """Wire auth_routes like test_invites does, with a recording seeder."""
    from api.routes import auth_routes as ar

    fake = types.SimpleNamespace(
        users={},
        created=[],
        seed_calls=[],
    )

    def create_user_account(email, pw, display_name, *, is_admin=False):
        email_l = (email or "").strip().lower()
        if not email_l or "@" not in email_l:
            raise ValueError("invalid_email")
        if email_l in fake.users:
            raise ValueError("user_exists")
        user = {
            "id": f"u-{len(fake.users) + 1}",
            "email": email_l,
            "display_name": (display_name or "").strip() or email_l.split("@")[0],
            "is_admin": is_admin,
            "avatar_data_url": None,
        }
        fake.users[email_l] = user
        fake.created.append(user)
        return user

    def create_session(user_id):
        return f"tok-{user_id}"

    monkeypatch.setattr(ar.S, "create_user_account", create_user_account)
    monkeypatch.setattr(ar.S, "create_session", create_session)
    monkeypatch.setattr(ar, "_invite_ip_hits", {})
    monkeypatch.setattr(
        ar.keystone_seeding,
        "seed_meet_your_council",
        lambda uid: fake.seed_calls.append(uid)
        or {"initiative": {"id": "i-1"}, "created": True},
    )
    return fake


def test_signup_seeds_keystones(signup_ctx, tmp_path, monkeypatch):
    from api.routes import auth_routes as ar

    store = ar.InviteStore(db_path=tmp_path / "invites.db")
    monkeypatch.setattr(ar, "_invite_store", store)
    import time as _time

    code = ar._new_invite_code(store)
    now = _time.time()
    store.issue(code, "Ally", now, now + 7 * 86400)

    out = ar.signup(
        M.SignupRequest(
            email="ally@example.com",
            password="pw",
            display_name="Ally",
            invite_code=code,
        ),
        _FakeRequest(),
        _FakeResponse(),
    )
    assert out["ok"] is True
    assert signup_ctx.seed_calls == [out["user"]["id"]]
    store.close()


def test_signup_survives_seeding_failure(signup_ctx, tmp_path, monkeypatch):
    from api.routes import auth_routes as ar

    def boom(uid):
        raise RuntimeError("seed exploded")

    monkeypatch.setattr(ar.keystone_seeding, "seed_meet_your_council", boom)
    store = ar.InviteStore(db_path=tmp_path / "invites.db")
    monkeypatch.setattr(ar, "_invite_store", store)
    import time as _time

    code = ar._new_invite_code(store)
    now = _time.time()
    store.issue(code, "Ally", now, now + 7 * 86400)

    out = ar.signup(
        M.SignupRequest(
            email="ally@example.com",
            password="pw",
            display_name="Ally",
            invite_code=code,
        ),
        _FakeRequest(),
        _FakeResponse(),
    )
    assert out["ok"] is True  # signup itself never breaks over seeding
    store.close()


# ------------------------------------------------------------- backfill


def test_backfill_by_email_and_all(monkeypatch):
    from api.routes import auth_routes as ar

    users = {
        "owner@local.zenaf": {"id": "u-owner", "email": "owner@local.zenaf"},
        "ally@example.com": {"id": "u-ally", "email": "ally@example.com"},
    }
    calls = []

    monkeypatch.setattr(
        ar.S,
        "get_user_by_email",
        lambda email: users.get((email or "").strip().lower()),
    )
    monkeypatch.setattr(ar.S, "list_users", lambda: list(users.values()))
    monkeypatch.setattr(
        ar.keystone_seeding,
        "seed_meet_your_council",
        lambda uid: calls.append(uid)
        or {"initiative": {"id": f"i-{uid}"}, "created": True},
    )

    admin = {"id": "admin-1", "is_admin": True}

    # By email: only that user.
    out = ar.admin_seed_keystones(
        M.SeedKeystonesRequest(email="owner@local.zenaf"), admin
    )
    assert out["ok"] is True
    assert [s["email"] for s in out["seeded"]] == ["owner@local.zenaf"]
    assert calls == ["u-owner"]

    # Unknown email → 404.
    with pytest.raises(HTTPException) as ei:
        ar.admin_seed_keystones(M.SeedKeystonesRequest(email="nope@x.io"), admin)
    assert ei.value.status_code == 404

    # No email: all users.
    calls.clear()
    out = ar.admin_seed_keystones(M.SeedKeystonesRequest(), admin)
    assert {s["email"] for s in out["seeded"]} == set(users.keys())
    assert set(calls) == {"u-owner", "u-ally"}
