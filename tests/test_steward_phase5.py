"""Narrative Steward Phase 5 — tree + suggestions expression (audit S5).

Acceptance, from the reconciled architecture §5 Phase 5 and the phase
brief:

- Fixture thread renders in the panel (active, cast-matched, with
  latest confirmed change + both I4 axes).
- No thread → panel identical to today's static behavior (empty lists
  per seat; the frontend renders no section).
- Mint suggestion over a thread-touching conversation cites the thread
  id; mint with no thread state behaves exactly as today (prompt and
  shaped items byte-identical).
- Demo fragment has exactly one fate: RETIRED — the strand-signal
  line builder is gone, and the reader section no longer takes it.
"""

from __future__ import annotations

import inspect
import json

import pytest

from local_ai.narrative import NarrativeStore
from local_ai.narrative.read_model import (
    active_thread_summaries,
    panel_thread_state,
)
from local_ai.narrative.refs import SourceRef

USER = "phase5-user"
OTHER = "phase5-other"


@pytest.fixture
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _ref(n):
    return SourceRef(kind="claim", ref_id=f"claim-{n}", evidence_kind="quote")


def _thread(store, status, title, cast, n):
    thread = store.create_thread(
        USER,
        origin="user_declared",
        title=title,
        cast=[{"seat": s} for s in cast],
        evidence_refs=[_ref(n)],
    )
    if status != "nascent":
        store.set_thread_status(USER, thread.id, status)
    return store.get_thread(USER, thread.id)


def _change(store, thread_id, kind, n, status=None):
    change = store.record_change(
        USER, thread_id, kind=kind, evidence_refs=[_ref(n)]
    )
    # record_change already creates "proposed"; only move when asked
    # for a different status.
    if status is not None and status != "proposed":
        store.set_change_status(USER, change.id, status)
    return change


def _snapshot(store):
    return store.snapshot_for_read(USER)


# -- Tree panels ------------------------------------------------------------


def test_panel_renders_active_cast_thread_with_confirmed_change(store):
    thread = _thread(store, "active", "The long walk", ["mentor"], 1)
    _change(store, thread.id, "extended", 2, status="confirmed")
    _change(store, thread.id, "milestone", 3, status="proposed")
    reading = store.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={"tensions": ["a vs b"], "open_questions": [], "milestones": []},
        evidence_refs=[_ref(1)],
    )
    store.accept_reading(USER, reading.id)

    panels = panel_thread_state(_snapshot(store))
    rows = panels["mentor"]
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == thread.id
    assert row["title"] == "The long walk"
    assert row["status"] == "active"
    # Developmental axis: latest confirmed change only (proposed ignored).
    assert row["latest_confirmed_change"]["kind"] == "extended"
    assert row["latest_confirmed_change"]["created_at"]
    # Epistemic axis: standing reading + counts, never a completion score.
    assert row["standing_reading"] is True
    assert row["proposed_changes"] == 1
    assert row["confirmed_changes"] == 1
    assert "completion" not in json.dumps(row)


def test_panel_excludes_non_active_and_non_cast_threads(store):
    _thread(store, "dormant", "Sleeping story", ["mentor"], 11)
    _thread(store, "nascent", "Unaccepted proposal", ["mentor"], 12)
    _thread(store, "active", "Champion's story", ["champion"], 13)
    panels = panel_thread_state(_snapshot(store))
    assert panels["mentor"] == []
    assert [r["title"] for r in panels["champion"]] == ["Champion's story"]


def test_panel_no_threads_is_empty_for_every_seat(store):
    panels = panel_thread_state(_snapshot(store))
    assert panels  # every seat keyed
    assert all(rows == [] for rows in panels.values())


def test_panel_newest_first_and_proposed_only_has_no_confirmed_change(store):
    older = _thread(store, "active", "Older story", ["mentor"], 21)
    _change(store, older.id, "extended", 22, status="confirmed")
    newer = _thread(store, "active", "Newer story", ["mentor"], 23)
    _change(store, newer.id, "milestone", 24, status="proposed")
    rows = panel_thread_state(_snapshot(store))["mentor"]
    assert [r["title"] for r in rows] == ["Newer story", "Older story"]
    assert rows[0]["latest_confirmed_change"] is None
    assert rows[0]["proposed_changes"] == 1
    assert rows[0]["confirmed_changes"] == 0
    assert rows[1]["latest_confirmed_change"]["kind"] == "extended"


def test_active_thread_summaries_capped_newest_first(store):
    for i in range(3):
        _thread(store, "active", f"Story {i}", ["mentor"], 30 + i)
    summaries = active_thread_summaries(_snapshot(store))
    assert [s["title"] for s in summaries] == ["Story 2", "Story 1", "Story 0"]
    assert all(s["status"] == "active" for s in summaries)
    assert all(set(s) == {"id", "title", "status"} for s in summaries)


def test_tree_panels_route_serves_panels_and_empty_for_other_user(
    store, tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.routes.steward_routes as steward_routes
    from api.routes.auth_routes import get_current_user

    thread = _thread(store, "active", "Routed story", ["mentor"], 41)
    _change(store, thread.id, "extended", 42, status="confirmed")

    app = FastAPI()
    app.include_router(steward_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": USER}
    monkeypatch.setattr(
        steward_routes,
        "get_narrative_store",
        lambda: NarrativeStore(db_path=tmp_path / "narrative.db"),
    )
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/steward/tree-panels")
    assert resp.status_code == 200
    panels = resp.json()["panels"]
    assert [r["title"] for r in panels["mentor"]] == ["Routed story"]
    assert panels["mentor"][0]["latest_confirmed_change"]["kind"] == "extended"
    assert panels["champion"] == []

    # Another user sees empty panels, never the first user's threads.
    app2 = FastAPI()
    app2.include_router(steward_routes.router)
    app2.dependency_overrides[get_current_user] = lambda: {"id": OTHER}
    client2 = TestClient(app2, raise_server_exceptions=False)
    resp2 = client2.get("/steward/tree-panels")
    assert resp2.status_code == 200
    assert all(rows == [] for rows in resp2.json()["panels"].values())


# -- Mint re-basing ----------------------------------------------------------


def _mint_payload(thread_id=None):
    item = {
        "title": "A turning point",
        "moment": "The night the decision landed.",
        "source_quote": "I finally said it out loud.",
        "why": "Worth keeping.",
    }
    if thread_id is not None:
        item["thread_id"] = thread_id
    return {
        "trainable_moments": [],
        "project_proposals": [],
        "mint_suggestions": [item],
    }


def _fake_gen(payload, prompts):
    def gen(prompt, **kw):
        prompts.append(prompt)
        return json.dumps(payload)

    return gen


def _turns():
    return [{"role": "user", "body": "I finally said it out loud.", "archetype_id": "mentor"}]


def test_mint_cites_known_thread_id():
    from local_ai.conversation import suggestions as sugg

    out = sugg.generate_suggestions(
        _turns(),
        generate_fn=_fake_gen(_mint_payload("thr-1"), []),
        user_id=USER,
        threads=[{"id": "thr-1", "title": "The long walk", "status": "active"}],
    )
    mint = out["mint_suggestions"][0]
    assert mint["thread_id"] == "thr-1"
    assert mint["thread_note"] == "This moment belongs to your The long walk thread."


def test_mint_drops_unknown_thread_id_and_matches_today_shape():
    from local_ai.conversation import suggestions as sugg

    out_today = sugg.generate_suggestions(
        _turns(), generate_fn=_fake_gen(_mint_payload(), []), user_id=USER
    )
    out_unknown = sugg.generate_suggestions(
        _turns(),
        generate_fn=_fake_gen(_mint_payload("thr-invented"), []),
        user_id=USER,
        threads=[{"id": "thr-1", "title": "The long walk", "status": "active"}],
    )
    assert out_unknown["mint_suggestions"][0] == out_today["mint_suggestions"][0]
    assert "thread_id" not in out_unknown["mint_suggestions"][0]
    assert "thread_note" not in out_unknown["mint_suggestions"][0]


def test_mint_no_thread_state_prompt_and_shape_identical_to_today():
    from local_ai.conversation import suggestions as sugg

    prompts_none, prompts_empty, prompts_threads = [], [], []
    out_none = sugg.generate_suggestions(
        _turns(),
        generate_fn=_fake_gen(_mint_payload(), prompts_none),
        user_id=USER,
        threads=None,
    )
    out_empty = sugg.generate_suggestions(
        _turns(),
        generate_fn=_fake_gen(_mint_payload(), prompts_empty),
        user_id=USER,
        threads=[],
    )
    out_threads = sugg.generate_suggestions(
        _turns(),
        generate_fn=_fake_gen(_mint_payload("thr-1"), prompts_threads),
        user_id=USER,
        threads=[{"id": "thr-1", "title": "The long walk", "status": "active"}],
    )
    # No thread state: prompt byte-identical whether None or [].
    assert prompts_none[0] == prompts_empty[0]
    assert out_none == out_empty
    # Thread state present: prompt names the thread, shape cites it.
    assert "thr-1" in prompts_threads[0]
    assert "The long walk" in prompts_threads[0]
    assert prompts_threads[0] != prompts_none[0]
    assert out_threads["mint_suggestions"][0]["thread_id"] == "thr-1"
    # A mint item without a thread id, even with threads present, is
    # shaped exactly as today.
    out_no_cite = sugg.generate_suggestions(
        _turns(),
        generate_fn=_fake_gen(_mint_payload(), []),
        user_id=USER,
        threads=[{"id": "thr-1", "title": "The long walk", "status": "active"}],
    )
    assert out_no_cite["mint_suggestions"][0] == out_none["mint_suggestions"][0]


# -- Demo fragment: exactly one fate — RETIRED ------------------------------


def test_demo_fragment_retired_no_third_path():
    import inspect

    from api.routes import demo_routes as dr

    # The strand-signal line builder is gone, not moved elsewhere.
    assert not hasattr(dr, "_strand_signal_line")
    # The reader section no longer takes a strand signal at all.
    params = list(inspect.signature(dr._progression_reader_section).parameters)
    assert params == ["window_lines", "register_flag"]
    # The reader itself still judges with restraint and a strict verdict.
    section = dr._progression_reader_section(["Visitor: hi"], None)
    assert "Judge the ARC" in section
    assert "An empty verdict is common and valid" in section
    assert "VERDICT:" in section
    assert "Strand analysis" not in section
