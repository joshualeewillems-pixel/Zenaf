"""W3 — provenance presentation in the nudge feed (weave): deterministic tests.

Coverage follows the reconciled implementation brief §15 (T-R1–T-R25).
No model calls; no live staging writes; dates relative to the live UTC
date (never a pinned TODAY — midnight drift). Rows are created through
the real storage layer (or the real W1 approve path for provenance),
in-memory VE connection via monkeypatched S.get_connection, isolated
tmp ConversationStore + tmp FollowthroughStore. The VE service module
is the engine's `ve` (as in production); its followthrough-store
factory is monkeypatched to the tmp store so delete orchestration is
exercised without touching the real followthrough.db.

Conventions (same as test_weave_w2_backflow.py): the small
seed/approve helpers are copied here rather than imported across test
modules.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

import api.routes.followthrough_routes as ft_routes
import api.routes.today_routes as today_routes
from local_ai.conversation.store import ConversationStore
from local_ai.followthrough.service import FollowthroughService, w3_provenance_enabled
from local_ai.followthrough.store import FollowthroughStore
from local_ai.today.service import TodayService
from local_ai.vision_execution import execution_context as EC
from local_ai.vision_execution import models as M
from local_ai.vision_execution import provenance as PV
from local_ai.vision_execution import service as VE
from local_ai.vision_execution import storage as S

ALICE = "test-user-w3"
TALK = "talk-w3"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_conn(tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    S.init_db(conn)
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    # Permissions Slice 1: compute_nudges now consults the R6 stance
    # at entry (B-R6; the default is Don't do it). These tests
    # predate the gate and assert feed behavior with nudges
    # permitted — opt the fixture user in through the real stance
    # store. The gate itself is covered in
    # tests/test_permissions_slice1_consumption.py.
    from local_ai.permissions.store import set_stance

    set_stance(ALICE, "R6", "all", "just_do_it", surface="test", connection=conn)
    yield conn
    conn.close()


@pytest.fixture()
def conv_store(tmp_path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


@pytest.fixture()
def ft_store(tmp_path):
    return FollowthroughStore(db_path=tmp_path / "ft.db")


@pytest.fixture()
def svc(ft_store, monkeypatch):
    """The engine against the real VE service module (production wiring),
    with the VE delete orchestration's followthrough factory pointed at
    the tmp store."""
    monkeypatch.setattr(VE, "_followthrough_store", lambda: ft_store)
    return FollowthroughService(store=ft_store, ve=VE)


@pytest.fixture()
def today(svc):
    return TodayService(ft=svc, ve=VE)


@pytest.fixture(autouse=True)
def w3_on(monkeypatch):
    # Explicitly ON for every test in this file; the kill-switch-off
    # tests override it after the fixture runs.
    monkeypatch.setenv("ZENAF_W3_PROVENANCE", "1")


def _today():
    return datetime.now(timezone.utc).date()


def _now():
    return datetime.now(timezone.utc)


def _iso_days_ago(n: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _iso_days_ahead(n: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=n)).isoformat()


def _set_dates(conn, task_id, *, created=None, updated=None, due=None):
    """Pin a task's timestamps/due date by direct SQL — the storage
    layer always writes "now", so tests control time this way."""
    if created is not None:
        conn.execute("UPDATE tasks SET created_at=? WHERE id=?", (created, task_id))
    if updated is not None:
        conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (updated, task_id))
    if due is not None:
        conn.execute("UPDATE tasks SET due_date=? WHERE id=?", (due, task_id))
    conn.commit()


def _set_project_updated(conn, project_id, updated):
    conn.execute(
        "UPDATE projects SET updated_at=? WHERE id=?", (updated, project_id)
    )
    conn.commit()


def _make_task(conn, user, title, *, origin_convo=None, origin_seat="champion",
               origin_msg="m1", **kw):
    """Create a task through the real storage layer. Origin fields
    only when an origin conversation is given (a manual task has
    none). Returns the freshly read task row."""
    data = M.TaskCreate(title=title, **kw)
    tid = S._insert_task(
        conn,
        data,
        user,
        origin_seat=origin_seat if origin_convo else None,
        origin_conversation_id=origin_convo,
        origin_message_id=origin_msg if origin_convo else None,
    )
    conn.commit()
    return S.get_task(tid, user)


def _make_project(conn, user, title, *, status="Draft", **kw):
    data = M.ProjectCreate(title=title, status=status, **kw)
    row = S.create_project(data, user)
    conn.commit()
    return S.get_project(row["id"], user)


def _seed_proposal(conv_store, user, convo, seat, title, *,
                   evidence_quote="Prose here.",
                   timeframe_commitment=None, block_index=0):
    """Seed one pending proposal through the real W1 provenance path.
    The proposing turn's prose IS the evidence quote, so any quote
    (up to the 500-char record limit) verifies verbatim."""
    conv_store.ensure_conversation(user, convo)
    body = (
        f"{evidence_quote}\n```task-proposal\n"
        + json.dumps(
            {
                "proposals": [
                    {
                        "title": title,
                        "timeframe_commitment": timeframe_commitment,
                        "due_date": None,
                        "notes": "W3 seed",
                    }
                ]
            }
        )
        + "\n```"
    )
    msg = conv_store.append_message(user, convo, seat, "voice", body)
    return S.record_task_proposal(
        user,
        {
            "title": title,
            "timeframe_commitment": timeframe_commitment,
            "due_date": None,
            "notes": "W3 seed",
            "conversation_id": convo,
            "source_message_id": msg["id"],
            "block_index": block_index,
            "proposal_index": 0,
            "evidence_quote": evidence_quote,
        },
        conversation_store=conv_store,
    )


def _approve_proposal(ve_conn, conv_store, user=ALICE, convo=TALK,
                      seat="champion", title="Approved task", **seed_kw):
    """Seed + approve one W1 proposal through the real approve path.
    Returns (proposal, task). The task carries origin fields, the
    proposal row carries created_task_id + decided_at."""
    proposal = _seed_proposal(conv_store, user, convo, seat, title, **seed_kw)
    result = S.approve_task_proposal(user, proposal["id"])
    return proposal, result["task"]


def _seed_live_nudge(ft_store, user, kind, entity_type, entity_id, *,
                     severity="should", why_text="seeded why",
                     entity_title="seeded title", suggested_seat="Guardian"):
    """Seed a live nudge row directly (a pre-fix row), bypassing the
    candidate builders — the render/auto-resolve under test sees a
    row the current builders would not create."""
    return ft_store.create_nudge(
        user,
        kind=kind,
        entity_type=entity_type,
        entity_id=entity_id,
        severity=severity,
        why_text=why_text,
        entity_title=entity_title,
        suggested_seat=suggested_seat,
    )


def _feed_ids(feed):
    return [n["id"] for n in feed]

# ---------------------------------------------------------------------------
# T-R1–T-R13
# ---------------------------------------------------------------------------


def test_r01_identical_ordering_with_without_provenance(
    ve_conn, conv_store, svc, today, monkeypatch
):
    """Decision 2: origin does not change ranking."""
    _proposal, task_a = _approve_proposal(
        ve_conn, conv_store, title="Overdue provenance task"
    )
    _set_dates(ve_conn, task_a["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    task_b = _make_task(ve_conn, ALICE, "Stale legacy task")
    _set_dates(ve_conn, task_b["id"], updated=_iso_days_ago(10))
    svc.create_commitment(ALICE, "Call the dentist")
    # Switch ON: origin attached.
    on = today.briefing(ALICE)["items"]
    assert [i["kind"] for i in on] == [
        "date_overdue", "stalled", "commitment_open",
    ]
    assert "origin" in on[0]
    # Switch OFF: origin stripped — the deck order is byte-identical.
    monkeypatch.setenv("ZENAF_W3_PROVENANCE", "0")
    off = today.briefing(ALICE)["items"]
    assert [i["id"] for i in on] == [i["id"] for i in off]
    assert "origin" not in off[0]


def test_r02_stale_kind_validation(ve_conn, svc, ft_store):
    """Decision 1: stale kinds do not surface; the validation and the
    auto-resolve agree (§6.4)."""
    task = _make_task(ve_conn, ALICE, "Was overdue")
    _set_dates(ve_conn, task["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1 and feed[0]["kind"] == "date_overdue"
    # Move the due date to next month: the kind no longer applies.
    _set_dates(ve_conn, task["id"], due=_iso_days_ahead(30)[:10])
    # Render WITHOUT a preceding compute: the card is excluded.
    rendered = svc._render_rows(
        ALICE, ft_store.list_feed_nudges(ALICE), _now()
    )
    assert rendered == []
    # Then run compute: the row is resolved.
    assert svc.compute_nudges(ALICE) == []
    assert ft_store.get_nudge(feed[0]["id"], ALICE)["resolved_at"] is not None


def test_r03_unknown_status_exclusion_and_diagnostic(ve_conn, svc, caplog):
    """Decision 4 (task-only): unknown statuses generate no nudge and
    are counted — task and project counts separately (§5.3)."""
    for i, st in enumerate(["In Review", "Waiting", "completed", "archived", ""]):
        t = _make_task(ve_conn, ALICE, f"Unknown {i}", status=st)
        _set_dates(ve_conn, t["id"], updated=_iso_days_ago(10))
    todo = _make_task(ve_conn, ALICE, "Todo task", status="Todo")
    _set_dates(ve_conn, todo["id"], updated=_iso_days_ago(10))
    with caplog.at_level(logging.INFO, logger="local_ai.followthrough.service"):
        feed = svc.compute_nudges(ALICE)
    assert [n["entity_id"] for n in feed] == [todo["id"]]
    assert feed[0]["kind"] == "stalled"
    lines = [
        r.getMessage()
        for r in caplog.records
        if "nudge_status_unknown" in r.getMessage()
    ]
    assert lines == ["nudge_status_unknown task_count=5 project_count=0"]


def test_r04_terminal_statuses(ve_conn, svc, ft_store):
    """Decision 4 (task-only): Done/Dropped (case variants) generate
    no new nudges and their live rows resolve."""
    for i, st in enumerate(["Done", "Dropped", "done", "dropped"]):
        t = _make_task(ve_conn, ALICE, f"Terminal {i}", status=st)
        _set_dates(ve_conn, t["id"], due=_iso_days_ago(2)[:10],
                   updated=_iso_days_ago(10))
        _seed_live_nudge(ft_store, ALICE, "stalled", "task", t["id"])
        _seed_live_nudge(ft_store, ALICE, "date_overdue", "task", t["id"])
    assert svc.compute_nudges(ALICE) == []
    assert ft_store.list_feed_nudges(ALICE) == []


def test_r05_tentative_date_non_generation(ve_conn, svc):
    """Decision 5: tentative dates never generate deadline nudges."""
    overdue = _make_task(
        ve_conn, ALICE, "Tentative overdue", timeframe_commitment="tentative"
    )
    _set_dates(ve_conn, overdue["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    approaching = _make_task(
        ve_conn, ALICE, "Tentative approaching",
        timeframe_commitment="tentative",
    )
    _set_dates(ve_conn, approaching["id"], due=_iso_days_ahead(2)[:10],
               updated=_iso_days_ago(1))
    assert svc.compute_nudges(ALICE) == []


def test_r06_one_time_correction(ve_conn, svc, ft_store):
    """Decision 5, §9: an existing tentative-date nudge resolves on
    the next successful compute; a snoozed one resolves on the compute
    after snooze expiry."""
    task = _make_task(ve_conn, ALICE, "Becomes tentative")
    _set_dates(ve_conn, task["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1 and feed[0]["kind"] == "date_overdue"
    nudge_id = feed[0]["id"]
    ve_conn.execute(
        "UPDATE tasks SET timeframe_commitment='tentative' WHERE id=?",
        (task["id"],),
    )
    ve_conn.commit()
    assert svc.compute_nudges(ALICE) == []
    assert ft_store.get_nudge(nudge_id, ALICE)["resolved_at"] is not None

    # Snoozed variant.
    task2 = _make_task(ve_conn, ALICE, "Becomes tentative snoozed")
    _set_dates(ve_conn, task2["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    feed2 = svc.compute_nudges(ALICE)
    assert len(feed2) == 1
    nudge2 = feed2[0]
    svc.snooze_nudge(ALICE, nudge2["id"], _iso_days_ahead(3))
    ve_conn.execute(
        "UPDATE tasks SET timeframe_commitment='tentative' WHERE id=?",
        (task2["id"],),
    )
    ve_conn.commit()
    # First compute: the snoozed row survives (not resolved), feed empty.
    assert svc.compute_nudges(ALICE) == []
    assert ft_store.get_nudge(nudge2["id"], ALICE)["resolved_at"] is None
    # Expire the snooze: the next compute resolves it.
    ft_store._conn.execute(
        "UPDATE followthrough_nudges SET snoozed_until=? WHERE id=?",
        (_iso_days_ago(1), nudge2["id"]),
    )
    ft_store._conn.commit()
    assert svc.compute_nudges(ALICE) == []
    assert ft_store.get_nudge(nudge2["id"], ALICE)["resolved_at"] is not None


def test_r07_deletion_read_time_exclusion(ve_conn, svc, ft_store):
    """Decision 3: cards for deleted entities never surface; the
    getter returns None, not a raise."""
    # (a) Service delete: the deletion-time resolution resolves the row.
    task = _make_task(ve_conn, ALICE, "Deleted task")
    _set_dates(ve_conn, task["id"], updated=_iso_days_ago(10))
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1
    nudge_id = feed[0]["id"]
    assert VE.delete_task(task["id"], ALICE) is True
    assert VE.get_task(task["id"], ALICE) is None
    assert svc._render_rows(
        ALICE, ft_store.list_feed_nudges(ALICE), _now()
    ) == []
    assert ft_store.get_nudge(nudge_id, ALICE)["resolved_at"] is not None
    # (b) Storage delete (bypassing the service orchestration, so the
    # row stays live): the READ-TIME exclusion is the guarantee.
    task2 = _make_task(ve_conn, ALICE, "Deleted task 2")
    _set_dates(ve_conn, task2["id"], updated=_iso_days_ago(10))
    feed2 = svc.compute_nudges(ALICE)
    assert len(feed2) == 1
    nudge2_id = feed2[0]["id"]
    assert S.delete_task(task2["id"], ALICE) is True
    assert VE.get_task(task2["id"], ALICE) is None
    assert ft_store.get_nudge(nudge2_id, ALICE)["resolved_at"] is None
    assert svc._render_rows(
        ALICE, ft_store.list_feed_nudges(ALICE), _now()
    ) == []


def test_r08_storage_exception_visible_failure(
    ve_conn, svc, today, monkeypatch
):
    """Decision 3 + 6, §2.3: a storage exception fails visibly as a
    500 — never a silent exclusion and never a silent False."""
    task = _make_task(ve_conn, ALICE, "Boom task")
    _set_dates(ve_conn, task["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    assert len(svc.compute_nudges(ALICE)) == 1

    def _boom(task_id, user_id=None):
        raise RuntimeError("storage boom")

    monkeypatch.setattr(VE, "get_task", _boom)
    with pytest.raises(RuntimeError, match="storage boom"):
        svc.compute_nudges(ALICE)
    # The enrich path propagates rather than returning False.
    with pytest.raises(RuntimeError, match="storage boom"):
        today._people_waiting(
            ALICE, {"entity_type": "task", "entity_id": task["id"]}
        )
    with pytest.raises(RuntimeError, match="storage boom"):
        today._due_today(
            ALICE, {"entity_type": "task", "entity_id": task["id"]}
        )
    with pytest.raises(RuntimeError, match="storage boom"):
        today.briefing(ALICE)
    # The routes translate the failure to an explicit 500.
    monkeypatch.setattr(ft_routes, "_svc", lambda: svc)
    with pytest.raises(HTTPException) as exc:
        ft_routes.get_nudges(user={"id": ALICE})
    assert exc.value.status_code == 500
    assert exc.value.detail == "follow-through error"
    monkeypatch.setattr(today_routes, "_svc", lambda: today)
    with pytest.raises(HTTPException) as exc2:
        today_routes.get_today(
            cursor=None, dismissed_ids=[], engaged_id=None, mode=None,
            user={"id": ALICE},
        )
    assert exc2.value.status_code == 500
    assert exc2.value.detail == "today briefing error"


def test_r09_500_vs_empty_deck(svc, today, monkeypatch):
    """Decision 6, §10 (equivalent contract test): the API returns a
    500 for a failure and a 200 with an empty deck for an empty feed —
    the two are never conflated. The frontend branching this contract
    feeds (error line vs "Nothing pressing.") was verified in the
    reconciliation at today_routes.py:63 and
    TodayView.tsx:95-97/:155/:259/:305-307."""
    # (a) Failure: the route raises 500.
    def _boom(user_id):
        raise RuntimeError("storage boom")

    monkeypatch.setattr(svc, "compute_nudges", _boom)
    monkeypatch.setattr(today_routes, "_svc", lambda: today)
    with pytest.raises(HTTPException) as exc:
        today_routes.get_today(
            cursor=None, dismissed_ids=[], engaged_id=None, mode=None,
            user={"id": ALICE},
        )
    assert exc.value.status_code == 500
    # (b) Empty deck: no error, empty items.
    monkeypatch.setattr(svc, "compute_nudges", lambda user_id: [])
    out = today_routes.get_today(
        cursor=None, dismissed_ids=[], engaged_id=None, mode=None,
        user={"id": ALICE},
    )
    assert out["items"] == [] and out["has_more"] is False
    assert out["suggested_mode"] is None


def test_r10_quote_truncation_both_surfaces(ve_conn, conv_store, svc, today):
    """Decision 8: a 250-char quote renders as 199 chars + "…" on BOTH
    surfaces (identical strings); 200- and 199-char quotes render
    untruncated; the stored evidence_quote keeps the full 250 chars."""
    quotes = {"q250": "A" * 250, "q200": "B" * 200, "q199": "C" * 199}
    tasks = {}
    for key, quote in quotes.items():
        _proposal, task = _approve_proposal(
            ve_conn, conv_store, title=f"Truncation {key}",
            evidence_quote=quote,
        )
        _set_dates(ve_conn, task["id"], due=_iso_days_ago(2)[:10],
                   updated=_iso_days_ago(1))
        tasks[key] = task
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 3
    by_id = {n["entity_id"]: n for n in feed}
    rendered = {key: by_id[tasks[key]["id"]]["origin"]["quote"] for key in quotes}
    assert rendered["q250"] == "A" * 199 + "…"
    assert len(rendered["q250"]) == 200
    assert rendered["q200"] == "B" * 200
    assert rendered["q199"] == "C" * 199
    # Identical strings on the Today surface.
    items = today.briefing(ALICE)["items"]
    assert len(items) == 3
    by_item = {i["entity_id"]: i for i in items}
    for key in quotes:
        assert by_item[tasks[key]["id"]]["origin"]["quote"] == rendered[key]
    # The stored evidence_quote is the full 250 chars.
    rows = S.get_proposals_by_created_task(ALICE, tasks["q250"]["id"])
    assert len(rows) == 1
    assert rows[0]["evidence_quote"] == "A" * 250


def test_r11_quote_label(ve_conn, conv_store, svc, today):
    """Decision 8: the label precedes the quote on both surfaces, and
    no quote renders without the label (the label is a required field
    of the origin object, paired with the quote)."""
    _proposal, task = _approve_proposal(
        ve_conn, conv_store, title="Labeled task",
        evidence_quote="A short verbatim quote.",
    )
    _set_dates(ve_conn, task["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1
    origin = feed[0]["origin"]
    assert origin is not None
    assert origin["quote_label"] == "Quote from the original proposal:"
    assert origin["quote"] == "A short verbatim quote."
    items = today.briefing(ALICE)["items"]
    assert items[0]["origin"]["quote_label"] == "Quote from the original proposal:"
    assert items[0]["origin"]["quote"] == "A short verbatim quote."


def test_r12_kill_switch_on(ve_conn, conv_store, svc, monkeypatch):
    """Decision 9: with the switch ON, a provenance task's nudge
    carries origin and a null public seat; a legacy task carries no
    origin."""
    monkeypatch.setenv("ZENAF_W3_PROVENANCE", "1")
    _proposal, task = _approve_proposal(
        ve_conn, conv_store, title="Provenance task"
    )
    _set_dates(ve_conn, task["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    legacy = _make_task(ve_conn, ALICE, "Legacy task")
    _set_dates(ve_conn, legacy["id"], updated=_iso_days_ago(10))
    feed = svc.compute_nudges(ALICE)
    by_id = {n["entity_id"]: n for n in feed}
    prov = by_id[task["id"]]
    assert prov["origin"] is not None
    assert prov["suggested_seat"] is None
    leg = by_id[legacy["id"]]
    assert "origin" not in leg
    assert leg["suggested_seat"] == "Guardian"


def test_r13_kill_switch_off(ve_conn, conv_store, svc, monkeypatch):
    """Decision 9 (corrected): with the switch OFF, no nudge carries
    origin; the provenance task's public seat is STILL null (not the
    kind hint); a legacy task's public seat is the kind hint."""
    monkeypatch.setenv("ZENAF_W3_PROVENANCE", "0")
    _proposal, task = _approve_proposal(
        ve_conn, conv_store, title="Provenance task"
    )
    _set_dates(ve_conn, task["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    legacy = _make_task(ve_conn, ALICE, "Legacy task")
    _set_dates(ve_conn, legacy["id"], updated=_iso_days_ago(10))
    feed = svc.compute_nudges(ALICE)
    by_id = {n["entity_id"]: n for n in feed}
    assert "origin" not in by_id[task["id"]]
    assert by_id[task["id"]]["suggested_seat"] is None
    assert "origin" not in by_id[legacy["id"]]
    assert by_id[legacy["id"]]["suggested_seat"] == "Guardian"
    # Correctness fixes stay active with the switch OFF (T-R3, T-R5):
    unknown = _make_task(ve_conn, ALICE, "Unknown task", status="In Review")
    _set_dates(ve_conn, unknown["id"], updated=_iso_days_ago(10))
    tent = _make_task(
        ve_conn, ALICE, "Tentative task", timeframe_commitment="tentative"
    )
    _set_dates(ve_conn, tent["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    feed2 = svc.compute_nudges(ALICE)
    ids = {n["entity_id"] for n in feed2}
    assert unknown["id"] not in ids
    assert tent["id"] not in ids


def test_r13b_correctness_fixes_active_with_switch_off(
    ve_conn, svc, ft_store, monkeypatch
):
    """T-R13 companion: T-R6, T-R7, T-R8 with the switch OFF — the
    correctness fixes are not provenance presentation."""
    monkeypatch.setenv("ZENAF_W3_PROVENANCE", "0")
    # (T-R6) A pre-existing tentative-date nudge resolves on compute.
    task = _make_task(ve_conn, ALICE, "Becomes tentative")
    _set_dates(ve_conn, task["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1
    nudge_id = feed[0]["id"]
    ve_conn.execute(
        "UPDATE tasks SET timeframe_commitment='tentative' WHERE id=?",
        (task["id"],),
    )
    ve_conn.commit()
    assert svc.compute_nudges(ALICE) == []
    assert ft_store.get_nudge(nudge_id, ALICE)["resolved_at"] is not None
    # (T-R7) A deleted task's card is excluded at render.
    task2 = _make_task(ve_conn, ALICE, "Deleted task")
    _set_dates(ve_conn, task2["id"], updated=_iso_days_ago(10))
    assert len(svc.compute_nudges(ALICE)) == 1
    assert S.delete_task(task2["id"], ALICE) is True
    assert svc._render_rows(
        ALICE, ft_store.list_feed_nudges(ALICE), _now()
    ) == []
    # (T-R8) A storage exception still fails visibly.
    task3 = _make_task(ve_conn, ALICE, "Boom task")
    _set_dates(ve_conn, task3["id"], updated=_iso_days_ago(10))
    assert len(svc.compute_nudges(ALICE)) == 1

    def _boom(task_id, user_id=None):
        raise RuntimeError("storage boom")

    monkeypatch.setattr(VE, "get_task", _boom)
    with pytest.raises(RuntimeError, match="storage boom"):
        svc.compute_nudges(ALICE)

# ---------------------------------------------------------------------------
# T-R14–T-R25
# ---------------------------------------------------------------------------


def test_r14_kill_switch_default(monkeypatch):
    """Decision 9, §12: local dev ON, staging ON, production OFF; an
    explicit env value wins over the default in all three."""
    monkeypatch.delenv("ZENAF_W3_PROVENANCE", raising=False)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    assert w3_provenance_enabled() is True  # local dev
    monkeypatch.setenv("FLY_APP_NAME", "zenaf-staging")
    assert w3_provenance_enabled() is True  # staging
    monkeypatch.setenv("FLY_APP_NAME", "zenaf")
    assert w3_provenance_enabled() is False  # production
    # Explicit env wins in all three.
    monkeypatch.setenv("ZENAF_W3_PROVENANCE", "1")
    assert w3_provenance_enabled() is True
    monkeypatch.setenv("ZENAF_W3_PROVENANCE", "0")
    assert w3_provenance_enabled() is False
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    assert w3_provenance_enabled() is False
    monkeypatch.setenv("ZENAF_W3_PROVENANCE", "1")
    assert w3_provenance_enabled() is True


def test_r15_shared_resolver_single_source(ve_conn, conv_store):
    """Decision 7: the five explanation wordings exist in exactly one
    module (provenance.py); W2 re-exports them; W3's feed render
    imports resolve_origin from the same module; the two surfaces'
    provenance clauses are identical strings for the same input."""
    fragments = [
        "Created from a proposal you approved on",
        "originating from your",
        "Originating from your conversation with",
        "Task created on",
    ]
    repo = Path(__file__).resolve().parent.parent
    hits = {frag: [] for frag in fragments}
    sources = sorted((repo / "local_ai").rglob("*.py")) + sorted(
        (repo / "api").rglob("*.py")
    )
    for path in sources:
        text = path.read_text()
        for frag in fragments:
            if frag in text:
                hits[frag].append(str(path.relative_to(repo)))
    for frag, files in hits.items():
        assert files == ["local_ai/vision_execution/provenance.py"], (frag, files)
    ec_src = (repo / "local_ai/vision_execution/execution_context.py").read_text()
    assert "from local_ai.vision_execution.provenance import" in ec_src
    ft_src = (repo / "local_ai/followthrough/service.py").read_text()
    assert "from local_ai.vision_execution.provenance import resolve_origin" in ft_src
    # The two surfaces' clauses are identical strings for one fixture.
    # (execution_context re-exports the resolver under its W2 name.)
    _proposal, task = _approve_proposal(ve_conn, conv_store, title="Shared task")
    clause_w2 = EC._provenance_clause(ALICE, task)
    origin_w3 = PV.resolve_origin(ALICE, task)
    assert origin_w3 is not None
    assert origin_w3["explanation"] == clause_w2
    assert clause_w2.startswith("Created from a proposal you approved on")


def test_r16_provenance_degrade(ve_conn, conv_store, svc, today, monkeypatch):
    """Decision 7 + verdict corrections 5 + 6b: the exact wording for
    each hierarchy level; a lookup failure never suppresses the nudge;
    one approved + one declined is level 1 (not a degrade); "You
    decided this" appears nowhere in SYSTEM-AUTHORED rendered text —
    and a verified quote containing the phrase renders VERBATIM."""
    today_iso = _today().isoformat()
    # Level 1: exactly one qualifying approved proposal.
    quote = "You decided this on Tuesday, and I wrote it down."
    proposal, task = _approve_proposal(
        ve_conn, conv_store, title="Decided task", evidence_quote=quote,
    )
    _set_dates(ve_conn, task["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    origin = PV.resolve_origin(ALICE, task)
    assert origin is not None
    assert origin["explanation"] == (
        f"Created from a proposal you approved on {today_iso} "
        f"in your conversation with Champion."
    )
    assert origin["quote"] == quote  # verbatim, unmodified
    assert origin["proposal_id"] == proposal["id"]
    assert origin["seat"] == "Champion"
    assert origin["quote_label"] == "Quote from the original proposal:"
    assert set(origin) == {
        "seat", "conversation_id", "quote", "quote_label",
        "proposal_id", "explanation",
    }
    assert "You decided this" not in origin["explanation"]
    # Both surfaces render the quote verbatim.
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1
    assert feed[0]["origin"]["quote"] == quote
    items = today.briefing(ALICE)["items"]
    assert items[0]["origin"]["quote"] == quote
    # Level 2: origin + seat + date, no qualifying proposal.
    t2 = {
        "id": "t2", "origin_conversation_id": "talk-9",
        "origin_seat": "champion", "created_at": _iso_days_ago(3),
    }
    o2 = PV.resolve_origin(ALICE, t2)
    assert o2["explanation"] == (
        f"Task created on {_iso_days_ago(3)[:10]}, originating from your "
        f"conversation with Champion."
    )
    assert o2["quote"] is None and o2["proposal_id"] is None
    # Level 3: origin + seat, no usable date.
    t3 = {
        "id": "t3", "origin_conversation_id": "talk-9",
        "origin_seat": "champion", "created_at": None,
    }
    o3 = PV.resolve_origin(ALICE, t3)
    assert o3["explanation"] == "Originating from your conversation with Champion."
    assert o3["quote"] is None
    # Level 4: date only (no origin conversation -> no origin object,
    # but the W2 clause still renders).
    t4 = {
        "id": "t4", "origin_conversation_id": "", "origin_seat": None,
        "created_at": _iso_days_ago(3),
    }
    assert PV.provenance_clause(ALICE, t4) == (
        f"Task created on {_iso_days_ago(3)[:10]}."
    )
    assert PV.resolve_origin(ALICE, t4) is None
    # Level 5: neither -> no clause; the nudge still renders.
    t5 = {
        "id": "t5", "origin_conversation_id": "", "origin_seat": None,
        "created_at": None,
    }
    assert PV.provenance_clause(ALICE, t5) == ""
    assert PV.resolve_origin(ALICE, t5) is None
    for o in (origin, o2, o3):
        assert "You decided this" not in o["explanation"]
    # Lookup failure degrades to level 2 and never suppresses the nudge.
    real_lookup = S.get_proposals_by_created_task

    def _boom(user_id, created_task_id):
        raise RuntimeError("storage boom")

    monkeypatch.setattr(S, "get_proposals_by_created_task", _boom)
    degraded = PV.resolve_origin(ALICE, task)
    assert degraded is not None
    assert degraded["explanation"] == (
        f"Task created on {task['created_at'][:10]}, originating from your "
        f"conversation with Champion."
    )
    assert degraded["quote"] is None
    feed2 = svc.compute_nudges(ALICE)
    assert len(feed2) == 1
    assert feed2[0]["origin"]["explanation"] == degraded["explanation"]
    monkeypatch.setattr(S, "get_proposals_by_created_task", real_lookup)
    # Multiple QUALIFYING approved proposals degrade to level 2.
    _p2, _task2 = _approve_proposal(
        ve_conn, conv_store, title="Second task", evidence_quote="Second prose.",
    )
    ve_conn.execute(
        "UPDATE task_proposals SET created_task_id=? WHERE id=?",
        (task["id"], _p2["id"]),
    )
    ve_conn.commit()
    multi = PV.resolve_origin(ALICE, task)
    assert multi is not None
    assert multi["explanation"] == (
        f"Task created on {task['created_at'][:10]}, originating from your "
        f"conversation with Champion."
    )
    assert multi["quote"] is None and multi["proposal_id"] is None
    # One approved + one declined is exactly ONE qualifying row: level 1.
    ve_conn.execute(
        "UPDATE task_proposals SET state='declined' WHERE id=?", (_p2["id"],)
    )
    ve_conn.commit()
    single = PV.resolve_origin(ALICE, task)
    assert single is not None
    assert single["explanation"].startswith(
        "Created from a proposal you approved on"
    )
    assert single["quote"] == quote


def test_r17_stalled_wording(ve_conn, svc):
    """Decision 1, D3 fix: the W2 honest wording, threshold named."""
    idle10 = _make_task(ve_conn, ALICE, "Idle ten days")
    _set_dates(ve_conn, idle10["id"], updated=_iso_days_ago(10))
    idle5 = _make_task(ve_conn, ALICE, "Idle five days")
    _set_dates(ve_conn, idle5["id"], updated=_iso_days_ago(5))
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1
    assert feed[0]["entity_id"] == idle10["id"]
    assert feed[0]["why"] == (
        "No recorded update in 10 days "
        "(idle beyond the 7-day follow-through threshold) "
        "— “Idle ten days”."
    )


def test_r18_internal_hint_preserved_public_null(
    ve_conn, conv_store, svc, today
):
    """Decision 2, §7: the public seat is null, but Today still ranks
    the card as a Conductor card (lens + dismissal)."""
    _proposal, task_a = _approve_proposal(
        ve_conn, conv_store, title="Provenance approaching",
    )
    _set_dates(ve_conn, task_a["id"], due=_iso_days_ahead(2)[:10],
               updated=_iso_days_ago(1))
    task_b = _make_task(ve_conn, ALICE, "Legacy approaching")
    _set_dates(ve_conn, task_b["id"], due=_iso_days_ahead(2)[:10],
               updated=_iso_days_ago(1))
    task_c = _make_task(ve_conn, ALICE, "Legacy stale")
    _set_dates(ve_conn, task_c["id"], updated=_iso_days_ago(10))
    feed = svc.compute_nudges(ALICE)
    by_id = {n["entity_id"]: n for n in feed}
    assert by_id[task_a["id"]]["suggested_seat"] is None  # public null
    assert by_id[task_a["id"]]["origin"] is not None
    # Dismiss the other Conductor card (B): A (Conductor by kind) sinks
    # below C (Guardian by kind).
    items = today.briefing(
        ALICE, dismissed_ids=[by_id[task_b["id"]]["id"]]
    )["items"]
    assert [i["entity_id"] for i in items] == [task_c["id"], task_a["id"]]
    # Lens matching: in Conductor mode, A leads over C.
    lens = today.briefing(ALICE, mode="conductor")["items"]
    lens_ids = [i["entity_id"] for i in lens]
    assert lens_ids.index(task_a["id"]) < lens_ids.index(task_c["id"])


def test_r19_no_quote_on_nudge_row(ve_conn, conv_store, svc, ft_store):
    """Decision 8: followthrough_nudges gains no quote/origin column;
    the origin is resolved at feed time from the proposal row; the
    full quote survives in task_proposals.evidence_quote."""
    cols = {
        r[1]
        for r in ft_store._conn.execute(
            "PRAGMA table_info(followthrough_nudges)"
        ).fetchall()
    }
    assert "quote" not in cols and "origin" not in cols
    quote = "Q" * 250
    _proposal, task = _approve_proposal(
        ve_conn, conv_store, title="Long quote task", evidence_quote=quote,
    )
    _set_dates(ve_conn, task["id"], due=_iso_days_ago(2)[:10],
               updated=_iso_days_ago(1))
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1
    assert feed[0]["origin"]["quote"] == "Q" * 199 + "…"
    rows = S.get_proposals_by_created_task(ALICE, task["id"])
    assert len(rows) == 1
    assert rows[0]["evidence_quote"] == quote


def test_r20_no_get_writes_by_recompute(ve_conn, svc, ft_store):
    """Decision 1: the recompute writes nothing — the stored why_text
    is byte-identical after two renders, and the row is untouched.
    (The engine's normal create/resolve writes on compute are out of
    scope; the routes document that a GET may create/resolve nudges
    as a side effect of computing — §2.1, U-D1 RULED.)"""
    task = _make_task(ve_conn, ALICE, "Stale why task")
    _set_dates(ve_conn, task["id"], updated=_iso_days_ago(10))
    stale = "No movement in 999 days on “Stale why task” — last touched 2020-01-01."
    row = _seed_live_nudge(
        ft_store, ALICE, "stalled", "task", task["id"], why_text=stale,
    )
    before = ft_store.get_nudge(row["id"], ALICE)
    first = svc._render_rows(
        ALICE, ft_store.list_feed_nudges(ALICE), _now()
    )
    assert len(first) == 1
    # The render recomputed the wording (10 days, not 999) — but the
    # stored row is untouched.
    assert "10 days" in first[0]["why"] and "999" not in first[0]["why"]
    second = svc._render_rows(
        ALICE, ft_store.list_feed_nudges(ALICE), _now()
    )
    assert len(second) == 1
    after = ft_store.get_nudge(row["id"], ALICE)
    assert after["why_text"] == stale
    assert after["why_text"] == before["why_text"]
    assert after["resolved_at"] is None and after["acked_at"] is None
    assert after["created_at"] == before["created_at"]


def test_r21_project_status_vocabulary(ve_conn, svc, ft_store, caplog):
    """U-D10 (RULED): the project open set generates; the terminal set
    generates none and its live rows resolve; unknown project statuses
    generate none and are counted in project_count (separately from
    task_count). A Draft project (the default) is NOT silently suppressed."""
    open_statuses = ["Draft", "Active", "Ready", "Evaluating", "Blocked"]
    terminal_statuses = ["Complete", "Killed"]
    unknown_statuses = ["Approved", "Parked"]
    projects = {}
    for st in open_statuses + terminal_statuses + unknown_statuses:
        p = _make_project(ve_conn, ALICE, f"Project {st}", status=st)
        _set_project_updated(ve_conn, p["id"], _iso_days_ago(10))
        projects[st] = p
    # Pre-existing live rows on the terminal + unknown projects.
    seeded = {}
    for st in terminal_statuses + unknown_statuses:
        seeded[st] = _seed_live_nudge(
            ft_store, ALICE, "stalled", "project", projects[st]["id"]
        )
    with caplog.at_level(logging.INFO, logger="local_ai.followthrough.service"):
        feed = svc.compute_nudges(ALICE)
    assert {n["entity_id"] for n in feed} == {
        projects[s]["id"] for s in open_statuses
    }
    assert all(n["kind"] == "stalled" for n in feed)
    lines = [
        r.getMessage()
        for r in caplog.records
        if "nudge_status_unknown" in r.getMessage()
    ]
    assert lines == ["nudge_status_unknown task_count=0 project_count=2"]
    # The terminal/unknown rows were resolved by the auto-resolve loop.
    for st in terminal_statuses + unknown_statuses:
        assert (
            ft_store.get_nudge(seeded[st]["id"], ALICE)["resolved_at"]
            is not None
        ), st


def test_r22_kill_switch_public_seat_identity(
    ve_conn, conv_store, svc, today, monkeypatch
):
    """Correction 4: the public seat is null in BOTH switch states and
    identical between them; the ONLY difference between the two renders
    is the presence/absence of the origin object; the internal kind
    hint still drives lens matching and dismissal in both states."""
    _proposal, task_a = _approve_proposal(
        ve_conn, conv_store, title="Provenance approaching",
    )
    _set_dates(ve_conn, task_a["id"], due=_iso_days_ahead(2)[:10],
               updated=_iso_days_ago(1))
    task_b = _make_task(ve_conn, ALICE, "Legacy approaching")
    _set_dates(ve_conn, task_b["id"], due=_iso_days_ahead(2)[:10],
               updated=_iso_days_ago(1))
    task_c = _make_task(ve_conn, ALICE, "Legacy stale")
    _set_dates(ve_conn, task_c["id"], updated=_iso_days_ago(10))
    feed_on = svc.compute_nudges(ALICE)
    by_on = {n["entity_id"]: n for n in feed_on}
    assert by_on[task_a["id"]]["suggested_seat"] is None
    assert by_on[task_a["id"]]["origin"] is not None
    # Dismissal (Conductor) down-weights A in the ON state.
    dismissed_on = today.briefing(
        ALICE, dismissed_ids=[by_on[task_b["id"]]["id"]]
    )["items"]
    assert [i["entity_id"] for i in dismissed_on] == [
        task_c["id"], task_a["id"],
    ]
    # Switch OFF: the same render, minus the origin object only.
    monkeypatch.setenv("ZENAF_W3_PROVENANCE", "0")
    feed_off = svc.compute_nudges(ALICE)
    by_off = {n["entity_id"]: n for n in feed_off}
    assert by_off[task_a["id"]]["suggested_seat"] is None
    assert "origin" not in by_off[task_a["id"]]
    assert {
        k: v for k, v in by_on[task_a["id"]].items() if k != "origin"
    } == by_off[task_a["id"]]
    # Dismissal still down-weights A in the OFF state.
    dismissed_off = today.briefing(
        ALICE, dismissed_ids=[by_off[task_b["id"]]["id"]]
    )["items"]
    assert [i["entity_id"] for i in dismissed_off] == [
        task_c["id"], task_a["id"],
    ]


def test_r23_commitment_validation(ve_conn, svc, ft_store, monkeypatch):
    """Correction 3: a commitment_open card renders only while the
    commitment exists AND is open AND is unlinked; a storage exception
    fails visibly as a 500."""
    # (a) Delete the commitment row directly; render without a compute.
    c = svc.create_commitment(ALICE, "Call the dentist")
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1 and feed[0]["kind"] == "commitment_open"
    ft_store._conn.execute("DELETE FROM commitments WHERE id=?", (c["id"],))
    ft_store._conn.commit()
    assert svc._render_rows(ALICE, ft_store.list_feed_nudges(ALICE), _now()) == []
    # (b) Status done, then dismissed: the card is absent in both cases.
    c2 = svc.create_commitment(ALICE, "Water the plants")
    feed2 = svc.compute_nudges(ALICE)
    assert len(feed2) == 1
    for status in ("done", "dismissed"):
        ft_store.set_commitment_status(c2["id"], ALICE, status)
        assert (
            svc._render_rows(ALICE, ft_store.list_feed_nudges(ALICE), _now())
            == []
        )
        ft_store._conn.execute(
            "UPDATE commitments SET status='open' WHERE id=?", (c2["id"],)
        )
        ft_store._conn.commit()
    # (c) Link the commitment to a task: the card is absent.
    task = _make_task(ve_conn, ALICE, "Linked task")
    svc.link_commitment(ALICE, c2["id"], task["id"])
    assert svc._render_rows(ALICE, ft_store.list_feed_nudges(ALICE), _now()) == []
    # (d) A storage exception in get_commitment propagates (500), never
    # a silently dropped card.
    c3 = svc.create_commitment(ALICE, "Third commitment")
    feed3 = svc.compute_nudges(ALICE)
    assert len(feed3) == 1 and feed3[0]["kind"] == "commitment_open"

    def _boom(commitment_id, user_id):
        raise RuntimeError("storage boom")

    monkeypatch.setattr(ft_store, "get_commitment", _boom)
    with pytest.raises(RuntimeError, match="storage boom"):
        svc._render_rows(ALICE, ft_store.list_feed_nudges(ALICE), _now())


def test_r24_provenance_immutability(ve_conn, conv_store):
    """Correction 1: edit/decline/re-approve attempts on an approved
    row leave evidence_quote, decided_at, state, and created_task_id
    byte-identical; the :5791 UPDATE carries its AND state='approved'
    guard."""
    proposal, task = _approve_proposal(
        ve_conn, conv_store, title="Immutable task",
        evidence_quote="Frozen words here.",
    )
    pid = proposal["id"]
    before = S.get_proposals_by_created_task(ALICE, task["id"])[0]
    assert before["state"] == "approved"
    assert before["created_task_id"] == task["id"]
    snapshot = {
        k: before[k]
        for k in ("evidence_quote", "decided_at", "state", "created_task_id")
    }
    # (1) Edit attempt: 409, no change.
    with pytest.raises(S.ProposalConflict):
        S.update_task_proposal(ALICE, pid, {"title": "Changed title"})
    # (2) Decline attempt: 409, no change.
    with pytest.raises(S.ProposalConflict):
        S.decline_task_proposal(ALICE, pid)
    # (3) Re-approve: the winner's task is returned, no second task.
    result = S.approve_task_proposal(ALICE, pid)
    assert result["task"]["id"] == task["id"]
    assert len(S.get_proposals_by_created_task(ALICE, task["id"])) == 1
    after = S.get_proposals_by_created_task(ALICE, task["id"])[0]
    assert {k: after[k] for k in snapshot} == snapshot
    # The :5791 guard, as written in the source.
    src = Path(S.__file__).read_text()
    assert (
        "UPDATE task_proposals SET created_task_id = ? "
        "WHERE id = ? AND state = 'approved'" in src
    )


def test_r25a_parent_delete_child_survives(ve_conn, svc, ft_store):
    """Correction 3 (a): deleting a parent resolves the parent's nudge
    and leaves the child's nudge rendering (the child survives as a root)."""
    parent = _make_task(ve_conn, ALICE, "Parent task")
    _set_dates(ve_conn, parent["id"], updated=_iso_days_ago(10))
    child = _make_task(
        ve_conn, ALICE, "Child task", parent_task_id=parent["id"]
    )
    _set_dates(ve_conn, child["id"], updated=_iso_days_ago(10))
    feed = svc.compute_nudges(ALICE)
    assert {n["entity_id"] for n in feed} == {parent["id"], child["id"]}
    assert VE.delete_task(parent["id"], ALICE) is True
    assert VE.get_task(child["id"], ALICE)["parent_task_id"] is None
    feed2 = svc.compute_nudges(ALICE)
    assert [n["entity_id"] for n in feed2] == [child["id"]]
    assert feed2[0]["kind"] == "stalled"


def test_r25b_project_delete_cascade(ve_conn, svc, ft_store):
    """Correction 3 (b): deleting a project resolves the project and
    both task nudges (cascade)."""
    project = _make_project(ve_conn, ALICE, "Doomed project", status="Draft")
    _set_project_updated(ve_conn, project["id"], _iso_days_ago(10))
    t1 = _make_task(ve_conn, ALICE, "Task one", project_id=project["id"])
    _set_dates(ve_conn, t1["id"], updated=_iso_days_ago(10))
    t2 = _make_task(ve_conn, ALICE, "Task two", project_id=project["id"])
    _set_dates(ve_conn, t2["id"], updated=_iso_days_ago(10))
    feed = svc.compute_nudges(ALICE)
    assert {n["entity_id"] for n in feed} == {project["id"], t1["id"], t2["id"]}
    assert VE.delete_project(project["id"], ALICE) is True
    assert svc.compute_nudges(ALICE) == []
    assert ft_store.list_feed_nudges(ALICE) == []


def test_r25c_initiative_delete_unanchors(ve_conn, svc, ft_store):
    """Correction 3 (c): deleting an initiative leaves the project and
    task nudges rendering (projects survive unanchored)."""
    init = S.create_initiative(M.InitiativeCreate(title="Home"), ALICE)
    project = _make_project(
        ve_conn, ALICE, "Anchored project", status="Draft",
        initiative_id=init["id"],
    )
    _set_project_updated(ve_conn, project["id"], _iso_days_ago(10))
    task = _make_task(ve_conn, ALICE, "Anchored task", project_id=project["id"])
    _set_dates(ve_conn, task["id"], updated=_iso_days_ago(10))
    feed = svc.compute_nudges(ALICE)
    assert {n["entity_id"] for n in feed} == {project["id"], task["id"]}
    assert VE.delete_initiative(init["id"], ALICE) is True
    assert VE.get_project(project["id"], ALICE)["initiative_id"] is None
    feed2 = svc.compute_nudges(ALICE)
    assert {n["entity_id"] for n in feed2} == {project["id"], task["id"]}


def test_r25d_commitment_unlinked_and_resurfaces(ve_conn, svc, ft_store):
    """Correction 3 (d) + founder verdict: deleting a task unlinks its
    commitments (linked_task_id = NULL, commitment survives) and an
    OPEN commitment resurfaces as commitment_open on the next compute."""
    task = _make_task(ve_conn, ALICE, "Linked task")
    _set_dates(ve_conn, task["id"], updated=_iso_days_ago(1))
    c = svc.create_commitment(ALICE, "Do the linked thing")
    svc.link_commitment(ALICE, c["id"], task["id"])
    assert svc.compute_nudges(ALICE) == []  # linked: no candidate
    assert VE.delete_task(task["id"], ALICE) is True
    row = ft_store.get_commitment(c["id"], ALICE)
    assert row is not None
    assert row["linked_task_id"] is None
    assert row["status"] == "open"
    assert row["text"] == "Do the linked thing"
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1
    assert feed[0]["kind"] == "commitment_open"
    assert feed[0]["entity_id"] == c["id"]


# ---------------------------------------------------------------------------
# T-R25 extensions (verdict refinement): failure between the two DBs
# ---------------------------------------------------------------------------


def test_r25e_delete_failure_after_unlink(ve_conn, svc, ft_store, monkeypatch):
    """Refinement (e): unlink succeeds + delete raises -> the commitment
    stays unlinked (safe, recoverable) and the task survives; the next
    compute surfaces commitment_open."""
    task = _make_task(ve_conn, ALICE, "Delete fails task")
    _set_dates(ve_conn, task["id"], updated=_iso_days_ago(10))
    c = svc.create_commitment(ALICE, "Promise on a failing delete")
    svc.link_commitment(ALICE, c["id"], task["id"])
    feed = svc.compute_nudges(ALICE)
    assert len(feed) == 1 and feed[0]["kind"] == "stalled"
    real_delete = S.delete_task

    def _boom(task_id, user_id):
        raise RuntimeError("VE delete boom")

    monkeypatch.setattr(S, "delete_task", _boom)
    with pytest.raises(RuntimeError, match="VE delete boom"):
        VE.delete_task(task["id"], ALICE)
    row = ft_store.get_commitment(c["id"], ALICE)
    assert row["linked_task_id"] is None
    assert row["status"] == "open"
    assert VE.get_task(task["id"], ALICE) is not None
    # The next compute surfaces the unlinked commitment as commitment_open.
    monkeypatch.setattr(S, "delete_task", real_delete)
    feed2 = svc.compute_nudges(ALICE)
    kinds = {n["kind"]: n for n in feed2}
    assert "commitment_open" in kinds
    assert kinds["commitment_open"]["entity_id"] == c["id"]


def test_r25f_retry_after_failed_delete(ve_conn, svc, ft_store, monkeypatch):
    """Refinement (f): retrying the delete after (e) succeeds, and
    exactly one commitment_open nudge exists (no duplicates)."""
    task = _make_task(ve_conn, ALICE, "Retry delete task")
    _set_dates(ve_conn, task["id"], updated=_iso_days_ago(10))
    c = svc.create_commitment(ALICE, "Promise on a retried delete")
    svc.link_commitment(ALICE, c["id"], task["id"])
    assert len(svc.compute_nudges(ALICE)) == 1  # the stalled nudge
    real_delete = S.delete_task

    def _boom(task_id, user_id):
        raise RuntimeError("VE delete boom")

    monkeypatch.setattr(S, "delete_task", _boom)
    with pytest.raises(RuntimeError, match="VE delete boom"):
        VE.delete_task(task["id"], ALICE)
    monkeypatch.setattr(S, "delete_task", real_delete)
    feed1 = svc.compute_nudges(ALICE)
    opens1 = [n for n in feed1 if n["kind"] == "commitment_open"]
    assert len(opens1) == 1
    first_id = opens1[0]["id"]
    # Retry the delete: it succeeds, and the next compute shows exactly
    # one commitment_open nudge — the same row, not a duplicate.
    assert VE.delete_task(task["id"], ALICE) is True
    assert VE.get_task(task["id"], ALICE) is None
    feed2 = svc.compute_nudges(ALICE)
    opens2 = [n for n in feed2 if n["kind"] == "commitment_open"]
    assert len(opens2) == 1
    assert opens2[0]["id"] == first_id


def test_r25g_unlink_failure_aborts_delete(ve_conn, svc, ft_store, monkeypatch):
    """Refinement (g): the unlink raising aborts the delete before any
    VE write — the task is NOT deleted and the commitment stays linked."""
    task = _make_task(ve_conn, ALICE, "Unlink fails task")
    _set_dates(ve_conn, task["id"], updated=_iso_days_ago(10))
    c = svc.create_commitment(ALICE, "Promise on a failing unlink")
    svc.link_commitment(ALICE, c["id"], task["id"])

    def _boom(user_id, task_id):
        raise RuntimeError("unlink boom")

    monkeypatch.setattr(ft_store, "unlink_commitments_for_task", _boom)
    with pytest.raises(RuntimeError, match="unlink boom"):
        VE.delete_task(task["id"], ALICE)
    assert VE.get_task(task["id"], ALICE) is not None
    row = ft_store.get_commitment(c["id"], ALICE)
    assert row["linked_task_id"] == task["id"]
