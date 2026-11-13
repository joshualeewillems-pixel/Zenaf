"""Permissions Slice 1 — consumption-boundary enforcement.

Covers the approved consumption slice (proposal
~/workspace/your_files/zenaf-permissions-slice-1-consumption-boundary-proposal-2026-11-10.md
§5/§7, founder decision record 2026-11-12):

- the shared helper (``local_ai/permissions/consumption.py``):
  flag permissions dispatch to the existing leaf readers, stance
  permissions resolve through the existing stance read (never the
  five-step framework check), everything fails closed, checks are
  read-only, and a resolution FAILURE is distinguishable from an
  explicit denial (failure logs; denial does not);
- B-F1: the fellowship attention read model serves keystone markers
  unchanged with the EXISTING empty observation shape when
  fellowship_derivation is off (O-S1-6), revocation takes effect at
  the next read (O-S1-1), and retained observation rows stay
  status-addressable (the B-F2 acceptance);
- B-R4b: the keystone-attention route omits a seat's invitation
  fields when that seat's R4 stance is not Just do it — while the
  invitations list route and the join context stay open (O-S1-3:
  explicit user invocation overrides initiation restrictions for
  that interaction only);
- B-S2: suggestion minting consumes steward thread summaries only
  when steward_derivation is on — governed by that flag ALONE
  (O-S1-5) — and a cached run's thread citations are not served
  after revocation (O-S1-1);
- B-R6: ``compute_nudges`` creates nothing and returns [] unless
  R6 resolves to Just do it (O-S1-4), with revocation effective at
  the next call.

All stores are tmp/in-memory; no LLM is involved anywhere.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

import local_ai.vision_execution.storage as ve_storage
from local_ai.permissions import store as perm_store
from local_ai.permissions.consumption import consumption_allowed

USER = "user-1"
OTHER = "user-2"


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


def _perm_conn(flags_by_user=None):
    """In-memory permissions DB in the minimal steward-test shape."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in (flags_by_user or {}).items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-11-04T00:00:00+00:00"),
        )
    conn.commit()
    return conn


def _set_stance(conn, user_id, capability, row, stance):
    return perm_store.set_stance(
        user_id, capability, row, stance, surface="test", connection=conn
    )


def _patch_default_conn(monkeypatch, conn):
    """Point the VE storage default connection at ``conn``."""
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)


class _BrokenConn:
    """A connection whose every execute raises (resolution failure)."""

    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    def commit(self):
        pass


# ---------------------------------------------------------------------------
# The shared helper — flags
# ---------------------------------------------------------------------------


def test_helper_fellowship_flag_dispatch():
    conn = _perm_conn({USER: {"fellowship_derivation": True}})
    assert consumption_allowed(USER, "fellowship_derivation", connection=conn) is True
    conn2 = _perm_conn({USER: {"fellowship_derivation": False}})
    assert consumption_allowed(USER, "fellowship_derivation", connection=conn2) is False
    # Missing row / missing key / non-literal-True all fail closed.
    assert consumption_allowed(OTHER, "fellowship_derivation", connection=conn) is False
    conn3 = _perm_conn({USER: {"fellowship_derivation": "yes"}})
    assert consumption_allowed(USER, "fellowship_derivation", connection=conn3) is False


def test_helper_steward_derivation_flag_dispatch():
    conn = _perm_conn({USER: {"steward_derivation": True}})
    assert consumption_allowed(USER, "steward_derivation", connection=conn) is True
    conn2 = _perm_conn({USER: {}})
    assert consumption_allowed(USER, "steward_derivation", connection=conn2) is False


def test_helper_steward_coordination_is_the_flag_alone():
    """The helper's ``steward_coordination`` dispatches to
    ``steward_coordination_allowed`` — the coordination flag alone,
    exactly as that reader defines it (derivation neither implies
    nor is implied by coordination; a cross-branch boundary needing
    both composes the two checks, as ``coordination_allowed`` does).
    No boundary in this slice consumes it; B-S2 must NOT (O-S1-5)."""
    both = _perm_conn(
        {USER: {"steward_derivation": True, "steward_coordination": True}}
    )
    assert consumption_allowed(USER, "steward_coordination", connection=both) is True
    coord_only = _perm_conn({USER: {"steward_coordination": True}})
    assert consumption_allowed(USER, "steward_coordination", connection=coord_only) is True
    deriv_only = _perm_conn({USER: {"steward_derivation": True}})
    assert consumption_allowed(USER, "steward_coordination", connection=deriv_only) is False


# ---------------------------------------------------------------------------
# The shared helper — stances (R4 / R6)
# ---------------------------------------------------------------------------


def test_helper_r4_defaults_to_just_do_it():
    conn = _perm_conn()
    assert consumption_allowed(USER, "R4", scope_row="guardian", connection=conn) is True


def test_helper_r4_per_seat_denial_is_seat_scoped():
    conn = _perm_conn()
    _set_stance(conn, USER, "R4", "guardian", "dont_do_it")
    assert consumption_allowed(USER, "R4", scope_row="guardian", connection=conn) is False
    # Another seat's row is untouched by the guardian denial.
    assert consumption_allowed(USER, "R4", scope_row="mentor", connection=conn) is True


def test_helper_r4_has_no_global_row_wildcards_fail_closed():
    """R4's scheme is the enumerated per-seat rows only — there is no
    "*" row in the registry (set_stance rejects it), and consulting a
    non-row key at consumption time fails closed for that row."""
    conn = _perm_conn()
    with pytest.raises(ValueError):
        _set_stance(conn, USER, "R4", "*", "dont_do_it")
    assert consumption_allowed(USER, "R4", scope_row="*", connection=conn) is False


def test_helper_r4_requires_a_seat_row(caplog):
    conn = _perm_conn()
    assert consumption_allowed(USER, "R4", connection=conn) is False
    # An unknown seat row resolves to the most restrictive stance.
    assert consumption_allowed(USER, "R4", scope_row="nobody", connection=conn) is False


def test_helper_r6_defaults_to_dont_do_it():
    conn = _perm_conn()
    assert consumption_allowed(USER, "R6", connection=conn) is False


def test_helper_r6_standing_row_governs():
    conn = _perm_conn()
    _set_stance(conn, USER, "R6", "all", "just_do_it")
    assert consumption_allowed(USER, "R6", connection=conn) is True
    _set_stance(conn, USER, "R6", "all", "dont_do_it")
    assert consumption_allowed(USER, "R6", connection=conn) is False


def test_helper_unknown_permission_and_empty_user_fail_closed():
    conn = _perm_conn()
    assert consumption_allowed(USER, "R99", connection=conn) is False
    assert consumption_allowed(USER, "not_a_permission", connection=conn) is False
    assert consumption_allowed("", "R6", connection=conn) is False
    assert consumption_allowed(None, "fellowship_derivation", connection=conn) is False


def test_helper_checks_are_read_only():
    """A check never creates a permissions row for an unknown user."""
    conn = _perm_conn()
    assert consumption_allowed("ghost", "fellowship_derivation", connection=conn) is False
    assert consumption_allowed("ghost", "R6", connection=conn) is False
    rows = conn.execute(
        "SELECT COUNT(*) FROM user_permissions_settings WHERE user_id = 'ghost'"
    ).fetchone()[0]
    assert rows == 0


# ---------------------------------------------------------------------------
# Failure vs denial distinguishability
# ---------------------------------------------------------------------------


def test_helper_stance_failure_is_logged_denial_is_not(caplog):
    conn = _perm_conn()
    _set_stance(conn, USER, "R6", "all", "dont_do_it")
    with caplog.at_level(logging.WARNING, logger="zenaf.permissions.consumption"):
        # Explicit denial: False, no failure record.
        assert consumption_allowed(USER, "R6", connection=conn) is False
        # Resolution failure: False, WITH a failure record.
        assert consumption_allowed(USER, "R6", connection=_BrokenConn()) is False
    failure_records = [
        r for r in caplog.records if r.exc_info or "failed" in r.getMessage()
    ]
    assert len(failure_records) == 1
    assert "failing closed" in failure_records[0].getMessage()


def test_helper_flag_failure_is_logged_by_the_leaf_reader(caplog):
    with caplog.at_level(logging.ERROR):
        assert (
            consumption_allowed(USER, "fellowship_derivation", connection=_BrokenConn())
            is False
        )
    assert any(
        "consent check failed" in r.getMessage() and r.exc_info
        for r in caplog.records
    )
    # Explicit denial stays silent.
    caplog.clear()
    conn = _perm_conn({USER: {"fellowship_derivation": False}})
    with caplog.at_level(logging.ERROR):
        assert consumption_allowed(USER, "fellowship_derivation", connection=conn) is False
    assert not any("consent check failed" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# B-F1 — fellowship attention read model
# ---------------------------------------------------------------------------


@pytest.fixture()
def obs_store(tmp_path):
    from local_ai.fellowship.observations import ObservationStore

    return ObservationStore(db_path=tmp_path / "observations.db")


def _dark_keystone():
    from local_ai.council import keystones as KD

    return {
        "seeded": False,
        "markers": {
            s["seat_ref"]: {"attention": False, "reason": None} for s in KD.SEATS
        },
    }


def _add_obs(store, seat="conductor", interpretation="Noted."):
    return store.add(
        user_id=USER,
        seat=seat,
        event_ref="evt-1",
        event_kind="conversation_turn",
        evidence="user words",
        evidence_kind="quote",
        interpretation=interpretation,
    )


def test_bf1_allowed_consumption_unchanged(obs_store, monkeypatch):
    from local_ai.fellowship.attention import attention_for_user

    _patch_default_conn(monkeypatch, _perm_conn({USER: {"fellowship_derivation": True}}))
    obs = _add_obs(obs_store)
    out = attention_for_user(
        USER, observation_store=obs_store, keystone_state=_dark_keystone()
    )
    marker = out["markers"]["conductor"]
    assert marker["attention"] is True
    assert marker["observation_ids"] == [obs.id]
    assert marker["observation_count"] == 1
    assert marker["observation_reason"] is not None


def test_bf1_denied_returns_existing_empty_shape(obs_store, monkeypatch):
    from local_ai.fellowship.attention import attention_for_user

    _patch_default_conn(monkeypatch, _perm_conn({USER: {"fellowship_derivation": False}}))
    _add_obs(obs_store)
    out = attention_for_user(
        USER, observation_store=obs_store, keystone_state=_dark_keystone()
    )
    marker = out["markers"]["conductor"]
    # O-S1-6: the existing shape, emptied — never a dropped marker,
    # never an error.
    assert marker["observation_ids"] == []
    assert marker["observation_count"] == 0
    assert marker["observation_reason"] is None
    assert marker["attention"] is False


def test_bf1_denied_keeps_keystone_markers_unchanged(obs_store, monkeypatch):
    from local_ai.fellowship.attention import attention_for_user

    _patch_default_conn(monkeypatch, _perm_conn({USER: {}}))
    _add_obs(obs_store, seat="conductor")
    keystone = _dark_keystone()
    keystone["seeded"] = True
    keystone["markers"]["conductor"] = {"attention": True, "reason": "intro"}
    out = attention_for_user(
        USER, observation_store=obs_store, keystone_state=keystone
    )
    marker = out["markers"]["conductor"]
    assert marker["attention"] is True
    assert marker["reason"] == "intro"
    assert marker["keystone_reason"] == "intro"
    assert marker["observation_ids"] == []
    assert marker["observation_count"] == 0
    assert marker["observation_reason"] is None


def test_bf1_revocation_takes_effect_at_next_read(obs_store, monkeypatch):
    from local_ai.fellowship.attention import attention_for_user

    conn = _perm_conn({USER: {"fellowship_derivation": True}})
    _patch_default_conn(monkeypatch, conn)
    _add_obs(obs_store)
    out = attention_for_user(
        USER, observation_store=obs_store, keystone_state=_dark_keystone()
    )
    assert out["markers"]["conductor"]["observation_count"] == 1
    # Revoke: same store, same rows — the next read serves none.
    conn.execute(
        "UPDATE user_permissions_settings SET permissions_json = ? WHERE user_id = ?",
        (json.dumps({"fellowship_derivation": False}), USER),
    )
    conn.commit()
    out = attention_for_user(
        USER, observation_store=obs_store, keystone_state=_dark_keystone()
    )
    assert out["markers"]["conductor"]["observation_count"] == 0
    assert out["markers"]["conductor"]["observation_ids"] == []


def test_bf1_denied_rows_retained_and_status_addressable(obs_store, monkeypatch):
    """B-F2 acceptance: retained observations stay gettable/settable
    by id while consumption is denied (no deletion, no lockout)."""
    _patch_default_conn(monkeypatch, _perm_conn({USER: {"fellowship_derivation": False}}))
    obs = _add_obs(obs_store)
    assert obs_store.get(USER, obs.id) is not None
    updated = obs_store.set_status(USER, obs.id, "dismissed")
    assert updated.status == "dismissed"


# ---------------------------------------------------------------------------
# B-R4b — keystone-attention route invitation fields, per-seat R4
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the VE SQLite DB per test (test_keystone_attention pattern)."""
    monkeypatch.setattr(ve_storage, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_storage, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_storage, "_init_done_paths", set())
    monkeypatch.setattr(ve_storage, "_thread_local", threading.local())
    return {}


@pytest.fixture()
def inv_store(tmp_path, monkeypatch):
    """Conversation store on an isolated DB, patched in as the class
    the routes lazily import (test_keystone_attention pattern)."""
    import local_ai.conversation.store as store_mod
    from local_ai.conversation.store import ConversationStore

    store = ConversationStore(db_path=tmp_path / "inv.db")
    monkeypatch.setattr(store_mod, "ConversationStore", lambda *a, **k: store)
    return store


def _make_user(email="ally@example.com"):
    from local_ai.vision_execution import service as ve

    return ve.create_user_account(email, "pw-hunter2", "Ally")


def _create_inv(store, user_id, conv, seat):
    return store.create_or_refresh_invitation(
        user_id,
        conv,
        seat,
        "a reason",
        evidence={"user_message": "hello", "assistant_reply": "hi"},
    )


def test_br4b_default_stance_serves_invitation_fields(ve_ctx, inv_store):
    from api.routes.vision_execution import get_keystone_attention

    user = _make_user()
    _create_inv(inv_store, user["id"], "talk-1", "guardian")
    out = get_keystone_attention({"id": user["id"]})
    assert out["markers"]["guardian"]["invitation_count"] == 1
    assert out["markers"]["guardian"]["invitation_conversation_ids"] == ["talk-1"]
    inv_store.close()


def test_br4b_denied_seat_fields_omitted_others_unchanged(ve_ctx, inv_store):
    from api.routes.vision_execution import get_keystone_attention

    user = _make_user()
    conn = ve_storage.get_connection()
    _set_stance(conn, user["id"], "R4", "guardian", "dont_do_it")
    _create_inv(inv_store, user["id"], "talk-1", "guardian")
    _create_inv(inv_store, user["id"], "talk-2", "mentor")
    out = get_keystone_attention({"id": user["id"]})
    guardian = out["markers"]["guardian"]
    # Omitted — the route's existing unavailable shape — not zeroed.
    assert "invitation_count" not in guardian
    assert "invitation_conversation_ids" not in guardian
    # The marker itself and other seats are untouched.
    assert guardian["attention"] is False
    assert guardian["observation_count"] == 0
    assert out["markers"]["mentor"]["invitation_count"] == 1
    assert out["markers"]["mentor"]["invitation_conversation_ids"] == ["talk-2"]
    inv_store.close()


def test_br4b_revocation_takes_effect_at_next_read(ve_ctx, inv_store):
    from api.routes.vision_execution import get_keystone_attention

    user = _make_user()
    _create_inv(inv_store, user["id"], "talk-1", "guardian")
    out = get_keystone_attention({"id": user["id"]})
    assert out["markers"]["guardian"]["invitation_count"] == 1
    conn = ve_storage.get_connection()
    _set_stance(conn, user["id"], "R4", "guardian", "dont_do_it")
    out = get_keystone_attention({"id": user["id"]})
    assert "invitation_count" not in out["markers"]["guardian"]
    inv_store.close()


def test_os13_invitations_list_route_stays_open(ve_ctx, inv_store, monkeypatch):
    """O-S1-3 narrowness (a): with the seat's R4 at Don't do it, the
    invitations list route (B-R4c) still serves the row — the gate is
    on the proactive fields only, not on user-invoked surfaces."""
    import api.routes.conversation_routes as conv_routes

    user = _make_user()
    conn = ve_storage.get_connection()
    _set_stance(conn, user["id"], "R4", "guardian", "dont_do_it")
    _create_inv(inv_store, user["id"], "skeleton", "guardian")
    monkeypatch.setattr(conv_routes, "_store", lambda: inv_store)
    out = conv_routes.list_invitations("skeleton", {"id": user["id"]})
    assert [i["seat"] for i in out["invitations"]] == ["guardian"]
    inv_store.close()


def test_os13_join_context_still_renders(ve_ctx, inv_store):
    """O-S1-3 narrowness (b): the join path (B-R4a) still renders the
    pending invitation's context with the seat's R4 at Don't do it —
    explicit user invocation overrides the initiation restriction
    for that interaction."""
    from local_ai.conversation.service import build_invitation_context

    user = _make_user()
    conn = ve_storage.get_connection()
    _set_stance(conn, user["id"], "R4", "guardian", "dont_do_it")
    _create_inv(inv_store, user["id"], "skeleton", "guardian")
    pending = inv_store.list_pending_invitations(user["id"], "skeleton")
    assert len(pending) == 1
    context = build_invitation_context(pending[0])
    assert context is not None
    assert "invitation context" in context.lower()
    assert "a reason" in context
    inv_store.close()


# ---------------------------------------------------------------------------
# B-S2 — suggestion minting thread summaries (steward_derivation alone)
# ---------------------------------------------------------------------------


class _FakeSuggestionPayload:
    def __init__(self, threads):
        self.threads = threads


@pytest.fixture()
def sugg_harness(tmp_path, monkeypatch):
    """The suggestions route over a tmp conversation store, with the
    suggestion engine faked to record the ``threads`` it receives and
    to shape a thread-cited mint item exactly when threads are passed
    (mirroring how thread influence appears in real payloads)."""
    import api.routes.conversation_routes as conv_routes
    import api.routes.steward_routes as steward_routes
    from local_ai.conversation import suggestions as sugg
    from local_ai.conversation.service import ConversationService
    from local_ai.conversation.store import ConversationStore
    from local_ai.narrative import read_model

    store = ConversationStore(db_path=tmp_path / "conv.db")
    svc = ConversationService(store, generate_fn=lambda prompt, **kw: "ok")
    store.ensure_conversation(USER)
    store.append_message(USER, "skeleton", "mentor", "user", "I protect my mornings")

    calls: list = []
    summary_calls: list = []

    def _fake_generate(turns, live_context=None, **kw):
        calls.append(kw.get("threads"))
        return _FakeSuggestionPayload(kw.get("threads"))

    def _fake_asdict(payload):
        if isinstance(payload, dict):
            return payload
        items = []
        if getattr(payload, "threads", None):
            items.append(
                {
                    "title": "thread-cited mint",
                    "thread_note": "Steward thread note",
                    "thread_id": "thread-1",
                }
            )
        return {
            "trainable_moments": [],
            "project_proposals": [],
            "mint_suggestions": items,
        }

    def _fake_summaries(snapshot):
        summary_calls.append(snapshot)
        return [{"thread_id": "thread-1", "title": "A live thread"}]

    class _FakeNarrativeStore:
        def snapshot_for_read(self, user_id):
            return {"user_id": user_id}

        def close(self):
            pass

    monkeypatch.setattr(conv_routes, "_service", lambda: svc)
    monkeypatch.setattr(conv_routes, "_store", lambda: store)
    monkeypatch.setattr(sugg, "generate_suggestions", _fake_generate)
    monkeypatch.setattr(sugg, "asdict_suggestion_payload", _fake_asdict)
    monkeypatch.setattr(steward_routes, "get_narrative_store", lambda: _FakeNarrativeStore())
    monkeypatch.setattr(read_model, "active_thread_summaries", _fake_summaries)
    yield conv_routes, store, calls, summary_calls
    store.close()


def _get_suggestions(conv_routes):
    return conv_routes.get_suggestions("skeleton", {"id": USER})


def test_bs2_allowed_minting_receives_thread_summaries(sugg_harness, monkeypatch):
    conv_routes, store, calls, summary_calls = sugg_harness
    _patch_default_conn(monkeypatch, _perm_conn({USER: {"steward_derivation": True}}))
    out = _get_suggestions(conv_routes)
    assert summary_calls, "summaries should be built when derivation is on"
    assert calls and calls[-1], "minting should receive the summaries"
    assert out["mint_suggestions"][0]["thread_note"] == "Steward thread note"


def test_bs2_denied_minting_gets_no_threads(sugg_harness, monkeypatch):
    conv_routes, store, calls, summary_calls = sugg_harness
    _patch_default_conn(monkeypatch, _perm_conn({USER: {"steward_derivation": False}}))
    out = _get_suggestions(conv_routes)
    # The summaries are not even built, and minting takes the
    # existing no-threads degradation path.
    assert summary_calls == []
    assert calls == [None]
    assert out["mint_suggestions"] == []


def test_bs2_governed_by_derivation_alone(sugg_harness, monkeypatch):
    """O-S1-5: coordination OFF must not gate same-conversation
    consumption; derivation ON alone serves the summaries."""
    conv_routes, store, calls, summary_calls = sugg_harness
    conn = _perm_conn({USER: {"steward_derivation": True, "steward_coordination": False}})
    _patch_default_conn(monkeypatch, conn)
    # Sanity: coordination really is off for this user.
    assert consumption_allowed(USER, "steward_coordination", connection=conn) is False
    out = _get_suggestions(conv_routes)
    assert calls and calls[-1], "derivation alone must serve thread summaries"
    assert out["mint_suggestions"][0]["thread_note"] == "Steward thread note"


def test_bs2_cached_run_not_served_after_revocation(sugg_harness, monkeypatch):
    """O-S1-1 at B-S2: a run minted (and cached) while derivation was
    on must not serve its thread citations after revocation."""
    conv_routes, store, calls, summary_calls = sugg_harness
    conn = _perm_conn({USER: {"steward_derivation": True}})
    _patch_default_conn(monkeypatch, conn)
    out1 = _get_suggestions(conv_routes)
    assert out1["cached"] is False
    assert out1["mint_suggestions"][0]["thread_note"] == "Steward thread note"
    out2 = _get_suggestions(conv_routes)
    assert out2["cached"] is True
    assert out2["mint_suggestions"][0]["thread_note"] == "Steward thread note"
    # Revoke: the next request must bypass the cached run and mint
    # thread-free, converging the cache to a thread-free run.
    conn.execute(
        "UPDATE user_permissions_settings SET permissions_json = ? WHERE user_id = ?",
        (json.dumps({"steward_derivation": False}), USER),
    )
    conn.commit()
    out3 = _get_suggestions(conv_routes)
    assert out3["cached"] is False
    assert out3["mint_suggestions"] == []
    assert calls[-1] is None


# ---------------------------------------------------------------------------
# B-R6 — compute_nudges entry gate
# ---------------------------------------------------------------------------


class _FakeVE:
    def __init__(self, tasks=(), projects=()):
        self._tasks = {t["id"]: t for t in tasks}
        self._projects = {p["id"]: p for p in projects}

    def list_tasks(self, user_id):
        return [t for t in self._tasks.values() if t.get("user_id") == user_id]

    def list_projects(self, user_id):
        return [p for p in self._projects.values() if p.get("user_id") == user_id]

    def get_task(self, task_id, user_id=None):
        t = self._tasks.get(task_id)
        if t is None:
            return None
        if user_id is not None and t.get("user_id") != user_id:
            return None
        return t

    def get_project(self, project_id, user_id=None):
        p = self._projects.get(project_id)
        if p is None:
            return None
        if user_id is not None and p.get("user_id") != user_id:
            return None
        return p


def _iso_days_ago(n: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _overdue_task(tid="t1"):
    return {
        "id": tid,
        "user_id": USER,
        "title": "Write the report",
        "status": "Todo",
        "due_date": _iso_days_ago(2)[:10],
        "created_at": _iso_days_ago(10),
        "updated_at": _iso_days_ago(10),
    }


def _ft_service(tmp_path, tasks=()):
    from local_ai.followthrough.service import FollowthroughService
    from local_ai.followthrough.store import FollowthroughStore

    store = FollowthroughStore(db_path=tmp_path / "ft.db")
    return FollowthroughService(store=store, ve=_FakeVE(tasks)), store


def test_br6_default_deny_creates_nothing(tmp_path, monkeypatch):
    svc, store = _ft_service(tmp_path, tasks=[_overdue_task()])
    _patch_default_conn(monkeypatch, _perm_conn())
    assert svc.compute_nudges(USER) == []
    assert store.list_feed_nudges(USER) == []
    assert store.list_active_keys(USER) == set()


def test_br6_just_do_it_computes_as_before(tmp_path, monkeypatch):
    svc, store = _ft_service(tmp_path, tasks=[_overdue_task()])
    conn = _perm_conn()
    _set_stance(conn, USER, "R6", "all", "just_do_it")
    _patch_default_conn(monkeypatch, conn)
    feed = svc.compute_nudges(USER)
    # The overdue task surfaces (a stalled nudge for the same task is
    # also legitimate engine output — the gate changes WHETHER the
    # engine runs, not what it computes).
    assert feed
    assert any(
        n["kind"] == "date_overdue" and n["entity_id"] == "t1" for n in feed
    )
    assert len(store.list_feed_nudges(USER)) == len(feed)


def test_br6_revocation_stops_creation_at_next_call(tmp_path, monkeypatch):
    svc, store = _ft_service(
        tmp_path, tasks=[_overdue_task("t1"), _overdue_task("t2")]
    )
    conn = _perm_conn()
    _set_stance(conn, USER, "R6", "all", "just_do_it")
    _patch_default_conn(monkeypatch, conn)
    feed = svc.compute_nudges(USER)
    assert feed
    assert {n["entity_id"] for n in feed} == {"t1", "t2"}
    rows_before = len(store.list_feed_nudges(USER))
    assert rows_before == len(feed)
    _set_stance(conn, USER, "R6", "all", "dont_do_it")
    assert svc.compute_nudges(USER) == []
    # No new rows were created by the denied call; existing rows are
    # retained data, untouched by the consumption gate.
    assert len(store.list_feed_nudges(USER)) == rows_before
