"""Follow-through engine v1 tests.

The VE service is faked (injected into FollowthroughService); the
FollowthroughStore uses a tmp SQLite file. No real VE database is touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from local_ai.followthrough import growth as G
from local_ai.followthrough.service import FollowthroughService
from local_ai.followthrough.store import FollowthroughStore


def _iso_days_ago(n: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _iso_days_ahead(n: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=n)).isoformat()


class FakeVE:
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


def _task(tid="t1", **kw):
    base = {
        "id": tid, "user_id": "u1", "title": "Write the report",
        "status": "Todo", "due_date": None,
        "created_at": _iso_days_ago(10), "updated_at": _iso_days_ago(10),
    }
    base.update(kw)
    return base


def _svc(tmp_path, tasks=(), projects=()):
    store = FollowthroughStore(db_path=tmp_path / "ft.db")
    return FollowthroughService(store=store, ve=FakeVE(tasks, projects)), store


# -- date watcher ------------------------------------------------------------


def test_date_overdue_is_must(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(due_date=_iso_days_ago(2)[:10],
                                        updated_at=_iso_days_ago(1))])
    nudges = svc.compute_nudges("u1")
    assert len(nudges) == 1
    n = nudges[0]
    assert n["kind"] == "date_overdue"
    assert n["severity"] == "must"
    assert "Overdue" in n["why"] and "Write the report" in n["why"]


def test_date_approaching_is_should(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(due_date=_iso_days_ahead(2)[:10],
                                        updated_at=_iso_days_ago(1))])
    nudges = svc.compute_nudges("u1")
    assert len(nudges) == 1
    assert nudges[0]["kind"] == "date_approaching"
    assert nudges[0]["severity"] == "should"


def test_date_far_future_no_nudge(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(due_date=_iso_days_ahead(30)[:10],
                                        updated_at=_iso_days_ago(1))])
    assert svc.compute_nudges("u1") == []


def test_date_done_task_ignored(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(status="Done",
                                        due_date=_iso_days_ago(5)[:10])])
    assert svc.compute_nudges("u1") == []


def test_date_missing_due_date_ignored(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(due_date=None,
                                        updated_at=_iso_days_ago(1))])
    assert svc.compute_nudges("u1") == []


# -- stalled watcher ----------------------------------------------------------


def test_stalled_task_is_should_with_idle_span(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(updated_at=_iso_days_ago(10))])
    nudges = svc.compute_nudges("u1")
    assert len(nudges) == 1
    n = nudges[0]
    assert n["kind"] == "stalled"
    assert n["severity"] == "should"
    assert "10 days" in n["why"]
    assert n["suggested_seat"] == "Guardian"


def test_stalled_recent_task_no_nudge(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(updated_at=_iso_days_ago(1))])
    assert svc.compute_nudges("u1") == []


def test_stalled_done_task_ignored(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(status="Completed",
                                        updated_at=_iso_days_ago(30))])
    assert svc.compute_nudges("u1") == []


def test_stalled_project(tmp_path):
    svc, _ = _svc(
        tmp_path,
        projects=[{
            "id": "p1", "user_id": "u1", "title": "Garden redesign",
            "status": "Draft", "created_at": _iso_days_ago(20),
            "updated_at": _iso_days_ago(20),
        }],
    )
    nudges = svc.compute_nudges("u1")
    assert len(nudges) == 1
    assert nudges[0]["kind"] == "stalled"
    assert nudges[0]["entity_type"] == "project"


# -- growth states -------------------------------------------------------------


def test_growth_state_skips_generic_stall(tmp_path):
    svc, store = _svc(tmp_path, tasks=[_task(updated_at=_iso_days_ago(10))])
    svc.set_growth_state("u1", "task", "t1", "seed")
    # 10 idle days would stall a linear task, but this one speaks growth —
    # and the seed was just planted, so no growth-stall either.
    assert svc.compute_nudges("u1") == []


def test_growth_stall_is_gentle_could(tmp_path):
    svc, store = _svc(tmp_path, tasks=[_task(updated_at=_iso_days_ago(30))])
    svc.set_growth_state("u1", "task", "t1", "sprout")
    # Backdate the transition to simulate a long-planted sprout.
    store._conn.execute(
        "UPDATE entity_growth SET transitioned_at = ?",
        (_iso_days_ago(20),),
    )
    store._conn.commit()
    nudges = svc.compute_nudges("u1")
    assert len(nudges) == 1
    n = nudges[0]
    assert n["kind"] == "growth_stall"
    assert n["severity"] == "could"
    assert "sprout" in n["why"] and "water it" in n["why"]
    assert n["suggested_seat"] == "Gardener"


def test_growth_forward_transitions_ok(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task()])
    assert svc.set_growth_state("u1", "task", "t1", "seed")["state"] == "seed"
    assert svc.set_growth_state("u1", "task", "t1", "bloom")["state"] == "bloom"
    assert svc.set_growth_state("u1", "task", "t1", "fruit")["state"] == "fruit"


def test_growth_backward_transition_rejected(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task()])
    svc.set_growth_state("u1", "task", "t1", "sapling")
    with pytest.raises(ValueError):
        svc.set_growth_state("u1", "task", "t1", "seed")


def test_growth_clear_with_null(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task()])
    svc.set_growth_state("u1", "task", "t1", "seed")
    out = svc.set_growth_state("u1", "task", "t1", None)
    assert out["state"] is None
    assert svc.get_growth_state("u1", "task", "t1")["state"] is None


def test_growth_invalid_state_rejected(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task()])
    with pytest.raises(ValueError):
        svc.set_growth_state("u1", "task", "t1", "tree")


def test_growth_unknown_entity_rejected(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task()])
    with pytest.raises(KeyError):
        svc.set_growth_state("u1", "task", "nope", "seed")
    with pytest.raises(ValueError):
        svc.set_growth_state("u1", "idea", "t1", "seed")


# -- commitments ----------------------------------------------------------------


def test_commitment_without_task_surfaces(tmp_path):
    svc, _ = _svc(tmp_path)
    svc.create_commitment("u1", "Call the dentist", source_quote="I should call…")
    nudges = svc.compute_nudges("u1")
    assert len(nudges) == 1
    n = nudges[0]
    assert n["kind"] == "commitment_open"
    assert n["severity"] == "should"
    assert "Call the dentist" in n["why"]
    assert "isn’t a task yet" in n["why"]


def test_commitment_linked_to_active_task_no_nudge(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(updated_at=_iso_days_ago(1))])
    c = svc.create_commitment("u1", "Write the report")
    svc.link_commitment("u1", c["id"], "t1")
    assert svc.compute_nudges("u1") == []


def test_commitment_fulfilled_when_task_done(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(status="Done",
                                        updated_at=_iso_days_ago(1))])
    c = svc.create_commitment("u1", "Write the report")
    svc.link_commitment("u1", c["id"], "t1")
    assert svc.compute_nudges("u1") == []
    assert svc.list_commitments("u1")[0]["status"] == "done"


def test_commitment_link_unknown_task_rejected(tmp_path):
    svc, _ = _svc(tmp_path)
    c = svc.create_commitment("u1", "Do a thing")
    with pytest.raises(KeyError):
        svc.link_commitment("u1", c["id"], "nope")


def test_commitment_requires_text(tmp_path):
    svc, _ = _svc(tmp_path)
    with pytest.raises(ValueError):
        svc.create_commitment("u1", "   ")


# -- nudge-once dedup ------------------------------------------------------------


def test_compute_twice_persists_one_nudge(tmp_path):
    svc, store = _svc(tmp_path, tasks=[_task(due_date=_iso_days_ago(2)[:10],
                                           updated_at=_iso_days_ago(1))])
    first = svc.compute_nudges("u1")
    second = svc.compute_nudges("u1")
    assert len(first) == 1 and len(second) == 1
    assert first[0]["id"] == second[0]["id"]
    assert len(store.list_feed_nudges("u1")) == 1


def test_ack_suppresses_resurface(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(due_date=_iso_days_ago(2)[:10],
                                        updated_at=_iso_days_ago(1))])
    nudge = svc.compute_nudges("u1")[0]
    svc.ack_nudge("u1", nudge["id"])
    # Acked: gone from the feed, and stays gone within the cooldown.
    assert svc.compute_nudges("u1") == []


def test_snooze_suppresses_until_expiry(tmp_path):
    svc, store = _svc(tmp_path, tasks=[_task(due_date=_iso_days_ago(2)[:10],
                                            updated_at=_iso_days_ago(1))])
    nudge = svc.compute_nudges("u1")[0]
    svc.snooze_nudge("u1", nudge["id"], _iso_days_ahead(3))
    assert svc.compute_nudges("u1") == []
    # Simulate the snooze expiring: backdate it, nudge returns.
    store._conn.execute(
        "UPDATE followthrough_nudges SET snoozed_until = ? WHERE id = ?",
        (_iso_days_ago(1), nudge["id"]),
    )
    store._conn.commit()
    again = svc.compute_nudges("u1")
    assert len(again) == 1 and again[0]["id"] == nudge["id"]


def test_snooze_past_time_rejected(tmp_path):
    svc, _ = _svc(tmp_path, tasks=[_task(due_date=_iso_days_ago(2)[:10],
                                        updated_at=_iso_days_ago(1))])
    nudge = svc.compute_nudges("u1")[0]
    with pytest.raises(ValueError):
        svc.snooze_nudge("u1", nudge["id"], _iso_days_ago(1))


def test_condition_cleared_auto_resolves(tmp_path):
    ve = FakeVE(tasks=[_task(due_date=_iso_days_ago(2)[:10],
                             updated_at=_iso_days_ago(1))])
    store = FollowthroughStore(db_path=tmp_path / "ft.db")
    svc = FollowthroughService(store=store, ve=ve)
    assert len(svc.compute_nudges("u1")) == 1
    # User pushes the due date out: the nudge's condition no longer holds.
    ve._tasks["t1"]["due_date"] = _iso_days_ahead(30)[:10]
    assert svc.compute_nudges("u1") == []
    assert store.list_feed_nudges("u1") == []


# -- feed ordering ----------------------------------------------------------------


def test_feed_ordered_must_should_could(tmp_path):
    svc, _ = _svc(
        tmp_path,
        tasks=[
            _task("t1", title="Overdue thing",
                  due_date=_iso_days_ago(2)[:10], updated_at=_iso_days_ago(1)),
            _task("t2", title="Stale thing", updated_at=_iso_days_ago(10)),
        ],
    )
    svc.set_growth_state("u1", "task", "t2", "seed")
    store = svc.store
    store._conn.execute(
        "UPDATE entity_growth SET transitioned_at = ?",
        (_iso_days_ago(20),),
    )
    store._conn.commit()
    kinds = [n["kind"] for n in svc.compute_nudges("u1")]
    # t1 overdue (must). t2 has a growth state → generic stall skipped,
    # growth-stall (could) fires instead.
    assert kinds == ["date_overdue", "growth_stall"]
