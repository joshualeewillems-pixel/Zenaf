"""Narrative Steward Phase 2 — Weaver-first prepared context + aspiration bridge.

Covers the base plan Phase 2 acceptance (S2) and the addendum §4/§6
discipline, with no model calls anywhere (all generation is faked):

- P2-A: ``narrative_context_for`` prepares bounded, facts-only
  context for a branch only after Phase 1 consent + relevance
  re-validation at preparation time; unconsented, irrelevant,
  nascent, retired, and archived threads never appear.
- P2-B: one thread rendered for Weaver and Raven shows identical
  fact lines, per-registry framing only, no cross-seat lexicon
  leakage, and no interpretation (reading) text.
- P2-C: the aspiration bridge joins user-stated lines (including
  the Phase 2 Heart fields) only when every inherited gate allows:
  feature flag, ``aspiration_use_in_guidance`` permission, and the
  profile's own ``use_in_guidance`` toggle. Any gate off means no
  aspiration section — never inferred.
- P2-D: the Weaver's chat path consumes prepared context through
  her existing generation (exactly one generation per turn);
  every other seat's prompt is byte-identical with or without the
  wiring; decline writes nothing and manufactures no verdict.
- P2-E: foreground generation counts match the audited baseline
  across the summary-refresh boundary, with context present.
- P2-F: Heart fields exist additively in the aspiration profile
  (old-schema migration, validation, row read).
"""

from __future__ import annotations

import inspect
import json
import sqlite3

import pytest

import local_ai.aspiration_layer as AL
import local_ai.narrative.context as ctx_mod
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.narrative import NarrativeStore
from local_ai.narrative.context import (
    WEAVER_BRANCH_ID,
    attended_refs_for_text,
    narrative_context_for,
    weaver_context_provider,
)
from local_ai.narrative.refs import SourceRef
from local_ai.vision_execution.storage import (
    _aspiration_row_to_dict,
    _migrate_aspiration_tables,
    _validate_aspiration_text_fields,
)

USER = "user-1"
OTHER = "user-2"

FLAGS_ON = {"steward_derivation": True, "steward_coordination": True}
FLAGS_DERIV_ONLY = {"steward_derivation": True, "steward_coordination": False}
FLAGS_COORD_ONLY = {"steward_derivation": False, "steward_coordination": True}
FLAGS_OFF = {"steward_derivation": False, "steward_coordination": False}

CLAIM_REF = SourceRef(kind="claim", ref_id="claim-9", evidence_kind="quote")
EVENT_REF = SourceRef(kind="event", ref_id="evt-8", evidence_kind="entity_ref")


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _perm_conn(flags_by_user):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-10-31T00:00:00Z"),
        )
    conn.commit()
    return conn


def _perm_conn_file(tmp_path, flags_by_user):
    """File-backed permissions DB usable across threads (TestClient
    serves requests on a different thread than the test, and an
    in-memory sqlite connection cannot cross threads — production
    connections are thread-local per get_connection, so this is a
    test-setup concern only)."""
    conn = sqlite3.connect(str(tmp_path / "perm.db"), check_same_thread=False)
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-10-31T00:00:00Z"),
        )
    conn.commit()
    return conn


def _set_flags(conn, user_id, flags):
    conn.execute(
        "UPDATE user_permissions_settings SET permissions_json = ? "
        "WHERE user_id = ?",
        (json.dumps(flags), user_id),
    )
    conn.commit()


def _count(store, table):
    conn = sqlite3.connect(str(store.db_path))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _active_thread_with_ref(store, user=USER, title="Quinlin's school story"):
    """An active thread whose evidence carries person:quinlin."""
    thread = store.create_thread(
        user, origin="user_declared", title=title, evidence_refs=(EVENT_REF,)
    )
    store.annotate_evidence_entities(
        user, thread.id, {("event", "evt-8"): "person:quinlin"}
    )
    store.set_thread_status(user, thread.id, "active")
    return store.get_thread(user, thread.id)


def _no_asp(uid):
    return None


def _no_asp_perm(uid):
    return False


# -- P2-A: preparation gates ---------------------------------------------------


def test_consent_closed_returns_no_content_and_no_assessment_rows(store):
    _active_thread_with_ref(store)
    for flags in (FLAGS_OFF, FLAGS_DERIV_ONLY, FLAGS_COORD_ONLY):
        conn = _perm_conn({USER: flags})
        prepared = narrative_context_for(
            store, USER, WEAVER_BRANCH_ID,
            attended_text="Quinlin's party was wonderful",
            connection=conn,
            aspiration_reader=_no_asp,
            aspiration_permission_check=_no_asp_perm,
        )
        assert prepared.available is False
        assert prepared.reason == "consent_closed"
        assert prepared.block is None
        assert prepared.threads == ()
    # No coordination work at all when consent is closed: zero
    # assessment rows despite three preparations.
    assert _count(store, "steward_relevance_assessments") == 0


def test_unconsented_never_prepares_even_when_relevant(store):
    thread = _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_OFF})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert prepared.block is None
    assert thread.title not in (prepared.block or "")


def test_irrelevant_thread_never_prepared(store):
    _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_text="totally unrelated weather talk",
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert prepared.available is False
    assert prepared.reason == "no_relevant_threads"
    assert prepared.block is None


def test_shared_entity_ref_via_message_text(store):
    thread = _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_text="Quinlin's party was wonderful",
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert prepared.available is True
    assert prepared.reason == "available"
    assert thread.title in prepared.block
    assert prepared.threads[0]["thread_id"] == thread.id
    assert prepared.assessment_ids


def test_shared_entity_ref_via_explicit_attended_refs(store):
    thread = _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert prepared.available is True
    assert thread.title in prepared.block


def test_short_id_tokens_never_attend_via_text(store):
    thread = store.create_thread(
        USER, origin="user_declared", title="Short id thread",
        evidence_refs=(EVENT_REF,),
    )
    store.annotate_evidence_entities(
        USER, thread.id, {("event", "evt-8"): "person:al"}
    )
    store.set_thread_status(USER, thread.id, "active")
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_text="Al was there, of course",
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert prepared.available is False
    assert prepared.block is None


def test_attended_refs_for_text_matching_rules():
    known = ["person:quinlin", "project:next-shift", "person:al", ""]
    attended = attended_refs_for_text(known, "Quinlin and the next shift plan")
    assert attended == frozenset({"person:quinlin", "project:next-shift"})
    assert attended_refs_for_text(known, "Al was there") == frozenset()
    assert attended_refs_for_text(known, "") == frozenset()


def test_non_standing_threads_excluded(store):
    # Nascent (unaccepted proposal), retired, and archived threads
    # with matching refs must never condition a seat.
    for status in ("nascent", "retired", "archived"):
        thread = store.create_thread(
            USER, origin="user_declared", title=f"{status} thread",
            evidence_refs=(EVENT_REF,),
        )
        store.annotate_evidence_entities(
            USER, thread.id, {("event", "evt-8"): "person:quinlin"}
        )
        if status != "nascent":
            if status == "retired":
                store.set_thread_status(
                    USER, thread.id, status, retirement_reason="completed"
                )
            else:
                store.set_thread_status(USER, thread.id, status)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert prepared.available is False
    assert prepared.reason == "no_standing_threads"
    assert prepared.block is None


def test_revoked_consent_closes_availability(store):
    _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    kwargs = dict(
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert narrative_context_for(store, USER, WEAVER_BRANCH_ID, **kwargs).available
    _set_flags(conn, USER, FLAGS_OFF)
    revoked = narrative_context_for(store, USER, WEAVER_BRANCH_ID, **kwargs)
    assert revoked.available is False
    assert revoked.reason == "consent_closed"
    assert revoked.block is None


def test_stale_relevance_closes_availability(store):
    _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    kwargs = dict(
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",), **kwargs,
    ).available
    stale = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_text="unrelated weather talk", **kwargs,
    )
    assert stale.available is False
    assert stale.block is None


def test_unknown_branch_raises(store):
    conn = _perm_conn({USER: FLAGS_ON})
    with pytest.raises(ValueError):
        narrative_context_for(store, USER, "seat:nope", connection=conn)


def test_preparation_writes_only_assessment_rows(store):
    thread = _active_thread_with_ref(store)
    before = {
        table: _count(store, table)
        for table in (
            "narrative_threads", "thread_readings", "thread_changes",
            "steward_discrepancy_flags",
        )
    }
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert prepared.available is True
    after = {
        table: _count(store, table)
        for table in (
            "narrative_threads", "thread_readings", "thread_changes",
            "steward_discrepancy_flags",
        )
    }
    assert after == before
    assert _count(store, "steward_relevance_assessments") >= 1
    assert store.get_thread(USER, thread.id).status == "active"


def test_context_module_has_no_generation_machinery():
    source = inspect.getsource(ctx_mod)
    assert "generate_fn" not in source
    assert "llm" not in source.lower()


# -- P2-B: identical facts, no leakage, no interpretation ----------------------


def _fact_lines(block):
    return [line for line in block.split("\n") if line.startswith("- ")]


def test_same_thread_identical_facts_across_branches(store):
    thread = _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    kwargs = dict(
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    weaver = narrative_context_for(store, USER, "seat:conductor", **kwargs)
    raven = narrative_context_for(store, USER, "seat:skeptic", **kwargs)
    assert weaver.available and raven.available
    assert _fact_lines(weaver.block) == _fact_lines(raven.block)
    assert thread.title in weaver.block and thread.title in raven.block
    assert "Weaver" in weaver.block and "Raven" not in weaver.block
    assert "Raven" in raven.block and "Weaver" not in raven.block
    for name in ("Gardener", "Firebrand", "Bear", "Fox", "Crane"):
        assert name not in weaver.block
        assert name not in raven.block


def test_render_carries_facts_not_interpretations(store):
    thread = _active_thread_with_ref(store)
    store.propose_reading(
        USER, thread.id, author="steward",
        reading={"tensions": ["quintessential zebra interpretation"]},
        evidence_refs=(CLAIM_REF,),
    )
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert prepared.available is True
    assert "quintessential zebra interpretation" not in prepared.block
    assert thread.title in prepared.block
    assert "[active]" in prepared.block


def test_block_bounded_and_capped(store):
    for i in range(6):
        thread = store.create_thread(
            USER, origin="user_declared", title=f"Thread {i}",
            evidence_refs=(EVENT_REF,),
        )
        store.annotate_evidence_entities(
            USER, thread.id, {("event", "evt-8"): "person:quinlin"}
        )
        store.set_thread_status(USER, thread.id, "active")
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert prepared.available is True
    assert len(prepared.threads) == 5
    assert "+1 more relevant thread(s) not shown." in prepared.block
    assert len(prepared.block) <= 2000


# -- P2-C: aspiration bridge ----------------------------------------------------


_PROFILE = {
    "core_aim": "Become a steadier parent",
    "current_edge": "Patience under pressure",
    "current_obstacles": "Running on very little sleep",
    "near_term_aspirations": "Finish the garden beds",
    "long_term_aspirations": "A household that feels calm",
    "heart_loves": "Long walks by the sea",
    "heart_meaning": "Being useful to my kids",
    "heart_commitments": "Show up for Quinlin",
    "use_in_guidance": True,
    "allow_inference": False,
}


def _asp_reader(profile):
    return lambda uid: dict(profile)


def test_aspiration_absent_when_profile_toggle_off(store, monkeypatch):
    _active_thread_with_ref(store)
    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: True)
    profile = dict(_PROFILE, use_in_guidance=False)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_asp_reader(profile),
        aspiration_permission_check=lambda uid: True,
    )
    assert prepared.available is True
    assert prepared.aspiration_included is False
    assert "Become a steadier parent" not in prepared.block
    assert "Long walks by the sea" not in prepared.block


def test_aspiration_absent_when_permission_denied(store, monkeypatch):
    _active_thread_with_ref(store)
    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: True)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_asp_reader(_PROFILE),
        aspiration_permission_check=lambda uid: False,
    )
    assert prepared.aspiration_included is False
    assert "Become a steadier parent" not in prepared.block


def test_aspiration_absent_when_feature_off(store, monkeypatch):
    _active_thread_with_ref(store)
    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: False)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_asp_reader(_PROFILE),
        aspiration_permission_check=lambda uid: True,
    )
    assert prepared.aspiration_included is False
    assert "Become a steadier parent" not in prepared.block


def test_aspiration_present_as_user_stated_lines_only(store, monkeypatch):
    _active_thread_with_ref(store)
    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: True)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_asp_reader(_PROFILE),
        aspiration_permission_check=lambda uid: True,
    )
    assert prepared.available is True
    assert prepared.aspiration_included is True
    for line in (
        "Core aim: Become a steadier parent",
        "Active edge: Patience under pressure",
        "Obstacle now: Running on very little sleep",
        "Loves: Long walks by the sea",
        "Sources of meaning: Being useful to my kids",
        "Commitments: Show up for Quinlin",
    ):
        assert line in prepared.block
    # allow_inference is False and irrelevant: context is not a
    # proposal, and nothing here derived, calibrated, or directed.
    assert "STRATEGIC ADAPTATION" not in prepared.block
    assert "calibration" not in prepared.block.lower()


def test_aspiration_empty_profile_no_section(store, monkeypatch):
    _active_thread_with_ref(store)
    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: True)
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_asp_reader({"use_in_guidance": True}),
        aspiration_permission_check=lambda uid: True,
    )
    assert prepared.available is True
    assert prepared.aspiration_included is False
    assert "stated aspirations" not in prepared.block


# -- P2-F: Heart fields in storage ----------------------------------------------


def test_heart_migration_adds_columns_to_old_schema():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE aspiration_profile ("
        " user_id TEXT PRIMARY KEY, core_aim TEXT NOT NULL DEFAULT '',"
        " growth_domains TEXT NOT NULL DEFAULT '[]',"
        " current_edge TEXT NOT NULL DEFAULT '',"
        " current_obstacles TEXT NOT NULL DEFAULT '',"
        " near_term_aspirations TEXT NOT NULL DEFAULT '',"
        " long_term_aspirations TEXT NOT NULL DEFAULT '',"
        " guidance_preferences TEXT NOT NULL DEFAULT '{}',"
        " anti_goals TEXT NOT NULL DEFAULT '',"
        " use_in_guidance INTEGER NOT NULL DEFAULT 0,"
        " allow_inference INTEGER NOT NULL DEFAULT 0,"
        " updated_at TEXT NOT NULL)"
    )
    _migrate_aspiration_tables(conn)
    columns = {
        row[1] for row in conn.execute(
            "PRAGMA table_info(aspiration_profile)").fetchall()
    }
    assert {"heart_loves", "heart_meaning", "heart_commitments"} <= columns
    # Idempotent: a second run adds nothing and raises nothing.
    _migrate_aspiration_tables(conn)


def test_heart_fields_validated_and_clamped():
    validated = _validate_aspiration_text_fields(
        {
            "heart_loves": "sea walks",
            "heart_meaning": "x" * 13000,
            "heart_commitments": "show up",
            "not_a_field": "dropped",
        }
    )
    assert validated["heart_loves"] == "sea walks"
    assert len(validated["heart_meaning"]) == 12000
    assert validated["heart_commitments"] == "show up"
    assert "not_a_field" not in validated


def test_aspiration_row_dict_missing_heart_keys_reads_empty():
    row = {
        "user_id": USER,
        "core_aim": "",
        "growth_domains": "[]",
        "current_edge": "",
        "current_obstacles": "",
        "near_term_aspirations": "",
        "long_term_aspirations": "",
        "guidance_preferences": "{}",
        "anti_goals": "",
        "use_in_guidance": 0,
        "allow_inference": 0,
        "updated_at": "2026-10-31T00:00:00Z",
    }
    out = _aspiration_row_to_dict(row)
    assert out["heart_loves"] == ""
    assert out["heart_meaning"] == ""
    assert out["heart_commitments"] == ""
    out2 = _aspiration_row_to_dict({**row, "heart_loves": "sea walks"})
    assert out2["heart_loves"] == "sea walks"


# -- P2-D/E: chat-path wiring ----------------------------------------------------


class _CapturingGen:
    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        return "Fake reply."


def _svc(tmp_path, gen, provider=None, subdir="conv"):
    # Each arm gets its own conversation DB: sharing one would let
    # the second arm's prompts see the first arm's history and break
    # the byte-identity comparisons below.
    cstore = ConversationStore(db_path=tmp_path / subdir / "conv.db")
    return ConversationService(
        cstore, generate_fn=gen, steward_context_provider=provider
    )


def _weaver_provider(store, conn):
    return weaver_context_provider(
        store,
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )


def test_weaver_turn_carries_context_and_costs_one_generation(tmp_path, store):
    thread = _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    gen = _CapturingGen()
    svc = _svc(tmp_path, gen, _weaver_provider(store, conn), "with")
    result = svc.turn(USER, "conductor", "Quinlin's party was wonderful")
    assert result.reply.reply == "Fake reply."
    assert len(gen.prompts) == 1
    assert thread.title in gen.prompts[0]
    assert "Steward context" in gen.prompts[0]


def test_other_seat_prompt_byte_identical_with_provider(tmp_path, store):
    _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    provider = _weaver_provider(store, conn)
    for seat in ("mentor", "champion", "guardian", "maverick", "ambassador", "skeptic"):
        gen_with = _CapturingGen()
        svc_with = _svc(tmp_path, gen_with, provider, "with")
        svc_with.turn(USER, seat, "Quinlin's party was wonderful")
        gen_without = _CapturingGen()
        svc_without = _svc(tmp_path, gen_without, None, "without")
        svc_without.turn(USER, seat, "Quinlin's party was wonderful")
        assert gen_with.prompts == gen_without.prompts
        assert "Steward context" not in gen_with.prompts[0]


def test_weaver_turn_without_context_identical_to_no_provider(tmp_path, store):
    _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_OFF})
    provider = _weaver_provider(store, conn)
    gen_with = _CapturingGen()
    svc_with = _svc(tmp_path, gen_with, provider, "with")
    svc_with.turn(USER, "conductor", "Quinlin's party was wonderful")
    gen_without = _CapturingGen()
    svc_without = _svc(tmp_path, gen_without, None, "without")
    svc_without.turn(USER, "conductor", "Quinlin's party was wonderful")
    assert gen_with.prompts == gen_without.prompts
    assert "Steward context" not in gen_with.prompts[0]


def test_weaver_prompt_diff_is_exactly_the_block(tmp_path, store):
    thread = _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    provider = _weaver_provider(store, conn)
    gen_with = _CapturingGen()
    svc_with = _svc(tmp_path, gen_with, provider, "with")
    svc_with.turn(USER, "conductor", "Quinlin's party was wonderful")
    gen_without = _CapturingGen()
    svc_without = _svc(tmp_path, gen_without, None, "without")
    svc_without.turn(USER, "conductor", "Quinlin's party was wonderful")
    with_block = gen_with.prompts[0]
    without_block = gen_without.prompts[0]
    assert thread.title in with_block
    # The block section is ["", block] in the prompt lines: joined,
    # it contributes "\n\n" + block between the preceding line and
    # the "User:" line, so removing exactly that substring must
    # recover the no-context prompt, proving the voice itself
    # (archetype lines, jurisdiction, register) is untouched and
    # only the block is added.
    prepared = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp_perm,
    )
    assert with_block.replace("\n\n" + prepared.block, "", 1) == without_block


def test_decline_is_consequence_free(tmp_path, store):
    thread = _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    gen = _CapturingGen()
    svc = _svc(tmp_path, gen, _weaver_provider(store, conn), "with")
    # The fake generation ignores the context entirely — the seat
    # declines it by not using it. That must write nothing: no
    # flags, no verdicts, no thread changes, no new threads.
    svc.turn(USER, "conductor", "Quinlin's party was wonderful")
    assert _count(store, "steward_discrepancy_flags") == 0
    assert _count(store, "narrative_threads") == 1
    assert _count(store, "thread_readings") == 0
    assert _count(store, "thread_changes") == 0
    assert store.get_thread(USER, thread.id).status == "active"


def test_provider_never_raises(tmp_path, store):
    store.close()
    provider = weaver_context_provider(store)
    assert provider(USER, "hello") is None


def test_generation_counts_match_baseline_across_summary_refresh(tmp_path, store):
    _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    provider = _weaver_provider(store, conn)
    gen_with = _CapturingGen()
    svc_with = _svc(tmp_path, gen_with, provider, "with")
    for _ in range(20):
        svc_with.turn(USER, "conductor", "Quinlin's party was wonderful")
    gen_without = _CapturingGen()
    svc_without = _svc(tmp_path, gen_without, None, "without")
    for _ in range(20):
        svc_without.turn(USER, "conductor", "Quinlin's party was wonderful")
    # 20 reply generations + 1 summary-refresh generation, with or
    # without steward context: availability adds zero generations.
    assert len(gen_with.prompts) == len(gen_without.prompts) == 21
    assert all("Steward context" in p for p in gen_with.prompts[:20])


def test_route_module_wires_weaver_provider():
    import api.routes.conversation_routes as routes_mod

    source = inspect.getsource(routes_mod._service)
    assert "weaver_context_provider" in source
    assert "steward_context_provider" in source


# -- P2-G: route wiring --------------------------------------------------------


def _route_client(tmp_path, monkeypatch, narrative_store, perm_conn):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.routes.conversation_routes as conv_routes
    import api.routes.voice_routes as voice_routes
    import local_ai.conversation.reply as reply_mod
    from api.routes.auth_routes import get_current_user

    gen = _CapturingGen()
    monkeypatch.setattr(reply_mod, "_default_generate", gen)
    provider = _weaver_provider(narrative_store, perm_conn)
    monkeypatch.setattr(voice_routes, "weaver_context_provider", lambda: provider)
    cstore = ConversationStore(db_path=tmp_path / "route-conv.db")
    svc = ConversationService(
        cstore, generate_fn=gen, steward_context_provider=provider
    )
    monkeypatch.setattr(conv_routes, "_service", lambda: svc)
    app = FastAPI()
    app.include_router(conv_routes.router)
    app.include_router(voice_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": USER}
    return TestClient(app), gen


def test_voice_chat_route_weaver_carries_context(tmp_path, store, monkeypatch):
    thread = _active_thread_with_ref(store)
    conn = _perm_conn_file(tmp_path, {USER: FLAGS_ON})
    client, gen = _route_client(tmp_path, monkeypatch, store, conn)
    r = client.post(
        "/voice/chat",
        json={"archetype_id": "conductor", "message": "Quinlin's party was wonderful"},
    )
    assert r.status_code == 200, r.text
    assert thread.title in gen.prompts[0]
    assert "Steward context" in gen.prompts[0]


def test_voice_chat_route_other_seat_no_context(tmp_path, store, monkeypatch):
    _active_thread_with_ref(store)
    conn = _perm_conn({USER: FLAGS_ON})
    client, gen = _route_client(tmp_path, monkeypatch, store, conn)
    r = client.post(
        "/voice/chat",
        json={"archetype_id": "skeptic", "message": "Quinlin's party was wonderful"},
    )
    assert r.status_code == 200, r.text
    assert "Steward context" not in gen.prompts[0]


def test_conversation_turn_route_weaver_carries_context(tmp_path, store, monkeypatch):
    thread = _active_thread_with_ref(store)
    conn = _perm_conn_file(tmp_path, {USER: FLAGS_ON})
    client, gen = _route_client(tmp_path, monkeypatch, store, conn)
    r = client.post(
        "/conversation/turn",
        json={"archetype_id": "conductor", "message": "Quinlin's party was wonderful"},
    )
    assert r.status_code == 200, r.text
    assert thread.title in gen.prompts[0]
    assert "Steward context" in gen.prompts[0]
