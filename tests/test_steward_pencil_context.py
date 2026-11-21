"""Pencil-standing steward observations for the Jynx (founder ruling
2026-11-21, rhyme scoping Addendum 23).

The channel under test is deliberately narrow:

- Master switch ``ZENAF_STEWARD_PENCIL`` default OFF: with it off,
  preparation returns before any store read, and the provider
  returns None without touching the store.
- With it on, every facts-layer gate applies unchanged: branch
  contract, BOTH consent flags, per-thread relevance re-validation,
  standing (active/dormant) threads only.
- What travels is a PROPOSED reading's pattern language (tensions,
  open questions), framed in the block as pencil standing. No
  reading id, no evidence ref, no milestone, no evidence text.
- The Weaver's facts-only path is untouched by this module's
  existence (covered by test_steward_phase2.py, including its
  facts-not-interpretations test).
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from local_ai.narrative import NarrativeStore
from local_ai.narrative.context import (
    PENCIL_BRANCH_ID,
    jynx_context_provider,
    pencil_context_enabled,
    pencil_context_for,
)
from local_ai.narrative.refs import SourceRef

USER = "user-1"

FLAGS_ON = {"steward_derivation": True, "steward_coordination": True}
FLAGS_OFF = {"steward_derivation": False, "steward_coordination": False}

CLAIM_REF = SourceRef(kind="claim", ref_id="claim-9", evidence_kind="quote")
EVENT_REF = SourceRef(kind="event", ref_id="evt-8", evidence_kind="entity_ref")

TENSION = "progress that does not feel like freedom"
QUESTION = "what would count as closer?"


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


@pytest.fixture()
def pencil_on(monkeypatch):
    monkeypatch.setenv("ZENAF_STEWARD_PENCIL", "1")


def _perm_conn(flags_by_user):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-11-21T00:00:00Z"),
        )
    conn.commit()
    return conn


def _active_thread_with_proposed_reading(store, user=USER):
    thread = store.create_thread(
        user, origin="user_declared", title="The long climb",
        evidence_refs=(EVENT_REF,),
    )
    store.annotate_evidence_entities(
        user, thread.id, {("event", "evt-8"): "person:quinlin"}
    )
    store.set_thread_status(user, thread.id, "active")
    reading = store.propose_reading(
        user, thread.id, author="steward",
        reading={
            "tensions": [TENSION],
            "open_questions": [QUESTION],
            "milestones": ["a milestone that must not travel"],
        },
        evidence_refs=(CLAIM_REF,),
    )
    return store.get_thread(user, thread.id), reading


def _prepare(store, conn, **kw):
    return pencil_context_for(
        store, USER, PENCIL_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn, **kw,
    )


# -- the master switch ---------------------------------------------------------


def test_switch_default_off(store):
    assert pencil_context_enabled() is False
    thread, _ = _active_thread_with_proposed_reading(store)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = _prepare(store, conn)
    assert prepared.available is False
    assert prepared.reason == "pencil_flag_off"
    assert prepared.block is None


def test_provider_returns_none_and_never_touches_store_when_off():
    provider = jynx_context_provider(store=None)
    assert provider(USER, "quinlin", []) is None


# -- gates, with the switch on ---------------------------------------------------


def test_consent_closed_serves_nothing(store, pencil_on):
    _active_thread_with_proposed_reading(store)
    conn = _perm_conn({USER: FLAGS_OFF})
    prepared = _prepare(store, conn)
    assert prepared.available is False
    assert prepared.reason == "consent_closed"
    assert prepared.block is None


def test_pencil_block_carries_pattern_language_marked_uncertain(store, pencil_on):
    thread, reading = _active_thread_with_proposed_reading(store)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = _prepare(store, conn)
    assert prepared.available is True
    block = prepared.block
    assert "pencil" in block.lower()
    assert "not facts" in block
    assert thread.title in block
    assert TENSION in block
    assert QUESTION in block
    # Nothing citable travels: no reading id, no evidence ref ids.
    assert reading.id not in block
    assert "claim-9" not in block
    assert "evt-8" not in block
    # Milestones are fact-class (what has happened); they do not travel.
    assert "a milestone that must not travel" not in block


def test_nascent_thread_never_contributes(store, pencil_on):
    thread = store.create_thread(
        USER, origin="user_declared", title="Unborn thread",
        evidence_refs=(EVENT_REF,),
    )
    store.annotate_evidence_entities(
        USER, thread.id, {("event", "evt-8"): "person:quinlin"}
    )
    store.propose_reading(
        USER, thread.id, author="steward",
        reading={"tensions": [TENSION]},
        evidence_refs=(CLAIM_REF,),
    )
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = _prepare(store, conn)
    assert prepared.available is False
    assert prepared.block is None


def test_accepted_reading_alone_is_not_pencil_material(store, pencil_on):
    from local_ai.narrative.review import apply_verdict

    thread, reading = _active_thread_with_proposed_reading(store)
    apply_verdict(store, USER, f"reading:{reading.id}", "accepted")
    assert store.readings_for(USER, thread.id, status="proposed") == []
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = _prepare(store, conn)
    assert prepared.available is False
    assert prepared.reason == "no_pencil_material"
    assert prepared.block is None


def test_irrelevant_thread_not_served(store, pencil_on):
    _active_thread_with_proposed_reading(store)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = pencil_context_for(
        store, USER, PENCIL_BRANCH_ID,
        attended_text="an unrelated message about plumbing",
        connection=conn,
    )
    assert prepared.available is False
    assert prepared.block is None


def test_provider_serves_block_when_fully_gated_open(store, pencil_on):
    _active_thread_with_proposed_reading(store)
    conn = _perm_conn({USER: FLAGS_ON})
    provider = jynx_context_provider(store=store, connection=conn)
    block = provider(USER, "thinking about quinlin again", [])
    assert block is not None
    assert TENSION in block


def test_unknown_branch_raises(store, pencil_on):
    conn = _perm_conn({USER: FLAGS_ON})
    with pytest.raises(ValueError):
        pencil_context_for(store, USER, "seat:nope", connection=conn)
