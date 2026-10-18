"""Today aggregate v1 tests.

The follow-through service is faked (canned nudge feed); the VE service is
faked (person links, due dates). No real databases are touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from local_ai.today.service import TodayService, envelope_score


def _iso_days_ago(n: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _iso_days_ahead(n: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=n)).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).isoformat()[:10]


class FakeFT:
    """Canned engine feed."""

    def __init__(self, nudges):
        self._nudges = nudges

    def compute_nudges(self, user_id):
        assert user_id == "u1"
        return [dict(n) for n in self._nudges]


class FakeVE:
    def __init__(self, tasks=(), projects=()):
        self._tasks = {t["id"]: t for t in tasks}
        self._projects = {p["id"]: p for p in projects}

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


def _nudge(nid, kind, seat="Conductor", entity_id="t1", **kw):
    base = {
        "id": nid, "kind": kind, "entity_type": "task", "entity_id": entity_id,
        "entity_title": f"title-{nid}", "severity": "should", "why": f"why-{nid}",
        "suggested_seat": seat, "created_at": "2026-10-18T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _task(tid="t1", **kw):
    base = {
        "id": tid, "user_id": "u1", "title": "T", "status": "Todo",
        "due_date": None, "assignee_id": "",
        "created_at": _iso_days_ago(10), "updated_at": _iso_days_ago(10),
    }
    base.update(kw)
    return base


def _svc(nudges, tasks=(), projects=()):
    return TodayService(ft=FakeFT(nudges), ve=FakeVE(tasks, projects))


# -- tier assignment ----------------------------------------------------------


def test_tier_assignment():
    svc = _svc([
        _nudge("n1", "date_overdue"),
        _nudge("n2", "stalled"),
        _nudge("n3", "growth_stall"),
    ])
    items = svc.briefing("u1")["items"]
    tiers = {i["id"]: i["tier"] for i in items}
    assert tiers == {"n1": "must", "n2": "should", "n3": "could"}


def test_approaching_due_today_is_must_future_is_should():
    svc = _svc(
        [
            _nudge("n1", "date_approaching", entity_id="t1"),
            _nudge("n2", "date_approaching", entity_id="t2"),
        ],
        tasks=[
            _task("t1", due_date=_today_iso()),
            _task("t2", due_date=_iso_days_ahead(2)[:10]),
        ],
    )
    tiers = {i["id"]: i["tier"] for i in svc.briefing("u1")["items"]}
    assert tiers == {"n1": "must", "n2": "should"}


# -- people waiting -----------------------------------------------------------


def test_people_waiting_outranks_due_today():
    svc = _svc(
        [
            _nudge("n1", "date_approaching", entity_id="t1"),
            _nudge("n2", "date_approaching", entity_id="t2"),
        ],
        tasks=[
            _task("t1", due_date=_today_iso()),
            _task("t2", due_date=_today_iso(), assignee_id="p9"),
        ],
    )
    items = svc.briefing("u1")["items"]
    assert [i["id"] for i in items] == ["n2", "n1"]
    assert items[0]["people_waiting"] is True
    assert items[1]["people_waiting"] is False


def test_people_waiting_promotes_stalled_to_must():
    svc = _svc(
        [_nudge("n1", "stalled", entity_id="t1")],
        tasks=[_task("t1", assignee_id="p9")],
    )
    items = svc.briefing("u1")["items"]
    assert items[0]["tier"] == "must"
    assert items[0]["people_waiting"] is True


def test_growth_stall_stays_gentle_even_with_person():
    svc = _svc(
        [_nudge("n1", "growth_stall", entity_id="t1", seat="Gardener")],
        tasks=[_task("t1", assignee_id="p9")],
    )
    items = svc.briefing("u1")["items"]
    assert items[0]["tier"] == "could"


# -- envelope -----------------------------------------------------------------


def test_envelope_score_unit():
    assert envelope_score("life-altering", "irreversible", "urgent") == 9
    assert envelope_score("significant", "costly", "deliberative") == 6
    assert envelope_score("low", "easily", "open-ended") == 3
    # Unknown is neutral: ties the lowest known level, never penalized.
    assert envelope_score("unknown", "unknown", "unknown") == 3


def test_envelope_orders_within_tier():
    svc = _svc(
        [
            _nudge("n1", "stalled", entity_id="t1"),
            _nudge("n2", "date_approaching", entity_id="t2"),
        ],
        tasks=[
            _task("t1"),
            _task("t2", due_date=_iso_days_ahead(2)[:10]),
        ],
    )
    items = svc.briefing("u1")["items"]
    # Both should-tier; approaching (deliberative, score 4) before stalled
    # (unknown time pressure, score 3).
    assert [i["id"] for i in items] == ["n2", "n1"]


# -- deck pagination ----------------------------------------------------------


def test_deck_pagination_three_plus_next():
    nudges = [_nudge(f"n{i}", "stalled", entity_id=f"t{i}") for i in range(5)]
    svc = _svc(nudges, tasks=[_task(f"t{i}") for i in range(5)])
    page1 = svc.briefing("u1")
    assert len(page1["items"]) == 3
    assert page1["has_more"] is True
    assert page1["cursor"]

    page2 = svc.briefing("u1", cursor=page1["cursor"])
    assert len(page2["items"]) == 2
    assert page2["has_more"] is False
    assert page2["cursor"] is None
    # No overlap, no gaps.
    ids1 = {i["id"] for i in page1["items"]}
    ids2 = {i["id"] for i in page2["items"]}
    assert not ids1 & ids2
    assert ids1 | ids2 == {f"n{i}" for i in range(5)}


def test_bad_cursor_restarts_deck():
    svc = _svc([_nudge("n1", "stalled")])
    items = svc.briefing("u1", cursor="not-a-cursor")["items"]
    assert [i["id"] for i in items] == ["n1"]


# -- mode discovery -----------------------------------------------------------


def test_dismissal_downweights_seat_live():
    svc = _svc([
        _nudge("a", "stalled", seat="Conductor", entity_id="t1"),
        _nudge("b", "stalled", seat="Conductor", entity_id="t2"),
        _nudge("c", "stalled", seat="Guardian", entity_id="t3"),
    ])
    items = svc.briefing("u1", dismissed_ids=["a"])["items"]
    # "a" is out ("not now"); "b" shares its seat so it sinks below "c".
    assert [i["id"] for i in items] == ["c", "b"]


def test_engage_proposes_mode():
    svc = _svc([_nudge("a", "stalled", seat="Conductor")])
    out = svc.briefing("u1", engaged_id="a")
    assert out["suggested_mode"] == "Conductor"


def test_no_engage_no_mode():
    svc = _svc([_nudge("a", "stalled", seat="Conductor")])
    assert svc.briefing("u1")["suggested_mode"] is None


def test_mode_param_reranks_around_seat():
    svc = _svc([
        _nudge("a", "stalled", seat="Conductor"),
        _nudge("b", "stalled", seat="Guardian"),
    ])
    items = svc.briefing("u1", mode="Guardian")["items"]
    assert [i["id"] for i in items] == ["b", "a"]
    # Case-insensitive seat match.
    items = svc.briefing("u1", mode="guardian")["items"]
    assert [i["id"] for i in items] == ["b", "a"]


def test_dismiss_only_suppresses_this_briefing():
    svc = _svc([_nudge("a", "stalled"), _nudge("b", "stalled")])
    page1 = svc.briefing("u1", dismissed_ids=["a"])
    assert [i["id"] for i in page1["items"]] == ["b"]
    # Fresh briefing (no dismissed ids) recomputes: "a" is back.
    page2 = svc.briefing("u1")
    assert {i["id"] for i in page2["items"]} == {"a", "b"}


# -- contract -----------------------------------------------------------------


def test_no_counts_in_response():
    svc = _svc([_nudge("a", "stalled")])
    out = svc.briefing("u1")
    assert set(out) == {"items", "has_more", "cursor", "suggested_mode"}
    for key in ("total", "count", "tier_counts", "badges"):
        assert key not in out


def test_next_action_present_and_singular():
    svc = _svc([
        _nudge("a", "date_overdue"),
        _nudge("b", "commitment_open", entity_type="commitment",
               entity_id="c1", seat="Guardian"),
    ])
    items = {i["id"]: i for i in svc.briefing("u1")["items"]}
    assert items["a"]["next_action"] == {"code": "done", "label": "Mark done"}
    assert items["b"]["next_action"] == {"code": "make_task",
                                        "label": "Make it a task"}
    for i in items.values():
        assert set(i["next_action"]) == {"code", "label"}


def test_why_carried_through():
    svc = _svc([_nudge("a", "date_overdue")])
    items = svc.briefing("u1")["items"]
    assert items[0]["why"] == "why-a"
    assert items[0]["suggested_seat"] == "Conductor"
