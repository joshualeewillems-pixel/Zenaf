"""Aria's grounded expression, Increment 1 — the binding.

The Gate B brief §5 suite as revised by the Founder Clarification
(Aria's Compass Orientation): the derivation covers the ACTIVITY
dimension + recorded relations only, and these tests pin that
scope as hard as they pin the mechanics — unweighed honesty,
boundary absoluteness, no-relation-no-interaction, tension never
rendered as resolution, unpresented claims silent, determinism +
read-only byte-identity, ownership, and graceful degradation with
no recognition proposals present.

(Test 10 of the brief — baseline spot-checks against the existing
suite — is the parent agent's discipline, not this file's.)
"""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

import local_ai.entity_strands as entity_strands
import local_ai.vision_execution.storage as ve_storage
from local_ai.agent_intake.store import AgentStore
from local_ai.atelier import derive_aria_expression
from local_ai.conversation.store import ConversationStore
from local_ai.narrative import SourceRef
from local_ai.narrative.store import NarrativeStore

USER = "user-aria"
OTHER = "user-other"
ENTITY_TYPE = "project"
ENTITY_ID = "proj-garden"
TARGET_REF = f"{ENTITY_TYPE}:{ENTITY_ID}"

WEIGHTS = {
    "Compass": 0.40,
    "Logic": 0.25,
    "Voice": 0.15,
    "Heart": 0.10,
    "Eye": 0.05,
    "Hands": 0.03,
    "Ear": 0.02,
}


# -- fixtures -------------------------------------------------------


@pytest.fixture()
def ve_conn(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    ve_storage.init_db(conn)
    # entity_strands imports get_connection lazily from the storage
    # module at call time — the patch lands there (the pattern
    # tests/test_weaver_round.py's ve_conn fixture uses).
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture()
def conv(tmp_path):
    store = ConversationStore(db_path=str(tmp_path / "conv.db"))
    yield store
    store.close()


@pytest.fixture()
def narr(tmp_path):
    store = NarrativeStore(db_path=str(tmp_path / "narr.db"))
    yield store
    store.close()


@pytest.fixture()
def agent(tmp_path):
    store = AgentStore(db_path=str(tmp_path / "agent.db"), user_id=USER)
    yield store
    store.close()


def _derive(conv, narr, agent, user=USER, entity_id=ENTITY_ID):
    return derive_aria_expression(
        user,
        ENTITY_TYPE,
        entity_id,
        conversation_store=conv,
        narrative_store=narr,
        agent_store=agent,
    )


def _weigh(user=USER, entity_id=ENTITY_ID, weights=None, source="user_stated"):
    entity_strands.set_entity_strands(
        user, ENTITY_TYPE, entity_id, weights or WEIGHTS, source=source
    )


def _thread(narr, user, ref_id, entity_ref=None, title="A thread"):
    thread = narr.create_thread(
        user,
        title=title,
        origin="user_declared",
        evidence_refs=[
            SourceRef(kind="event", ref_id=ref_id, evidence_kind="entity_ref")
        ],
    )
    if entity_ref is not None:
        narr.annotate_evidence_entities(
            user, thread.id, {("event", ref_id): entity_ref}
        )
    return thread


def _source(conv, user, strand, label="Note"):
    thread = conv.resolve_strand_thread(user, strand)
    return conv.add_strand_source(
        user,
        strand,
        thread["conversation_id"],
        "paste",
        "paste",
        label=label,
        excerpt_redacted="some kept material",
    )


def _seed_claim(agent, claim_id, user=USER, agent_id="weav"):
    # Direct-SQL seeding, the tests/test_weaver_round.py pattern:
    # the claim id follows the filing format
    # "{agent}:impression:{strands}:{run_key}".
    with agent._lock:
        agent._conn.execute(
            "INSERT OR IGNORE INTO connected_agents "
            "(agent_id, name, source_platform, description, created_at,"
            " user_id) VALUES (?, ?, 'zenaf', '',"
            " '2026-01-01T00:00:00Z', ?)",
            (agent_id, "Weaver test agent", user),
        )
        agent._conn.execute(
            "INSERT OR REPLACE INTO review_claims "
            "(claim_id, agent_id, claim_type, title, evidence, inference,"
            " detail, status, created_at, updated_at, user_id) "
            "VALUES (?, ?, 'meeting_impression', 'First impression',"
            " 'an answer, word for word', 'a read, word for word', '',"
            " 'pending', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ?)",
            (claim_id, agent_id, user),
        )
        agent._conn.commit()


def _present(conv, claim_id, user=USER, convo="talk-main", agent_id="weav"):
    conv.append_message(
        user,
        convo,
        "conductor",
        "voice",
        "an impression, in the seat's own words",
        context={
            "round_kind": "weaver",
            "round_id": "round-1",
            "round_state": "item",
            "round_claim_id": claim_id,
            "round_agent_id": agent_id,
        },
    )


def _sha(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# -- 1. unweighed honesty --------------------------------------------


def test_1_unweighed_honesty(ve_conn, conv, narr, agent):
    spec = _derive(conv, narr, agent)
    assert spec.coverage["unweighed"] is True
    assert spec.coverage["weights_source"] is None
    # Uniform base: no family differs from another — her blend's
    # differentiation is NOT substituted for the Work's silence.
    assert len(set(spec.capacities.values())) == 1
    assert all(v == 1.0 for v in spec.capacities.values())
    assert len(set(spec.blend.values())) > 1  # the blend itself differs
    assert spec.coverage["dimensions_touched"] == [
        "activity",
        "recorded_relations",
    ]
    assert spec.coverage["dimensions_not_touched"] == ["identity", "purpose"]
    assert spec.coverage["opacity_input"] == "fixture_only"


# -- 2. weighed shaping ----------------------------------------------


def test_2_weighed_shaping_by_ordering_and_bounds(ve_conn, conv, narr, agent):
    _weigh()
    spec = _derive(conv, narr, agent)
    assert spec.coverage["unweighed"] is False
    assert spec.coverage["weights_source"] == "user_stated"
    # capacity_f = blend_f × (1 + weight_f), exactly.
    assert spec.capacities == {
        "Compass": 0.35,
        "Logic": 0.25,
        "Voice": 0.1725,
        "Heart": 0.165,
        "Eye": 0.105,
        "Hands": 0.103,
        "Ear": 0.051,
    }
    # Ordering follows the weights' ordering (the fixture's weights
    # are ordered identically to the blend's, so no crossing).
    by_weight = sorted(WEIGHTS, key=lambda f: -WEIGHTS[f])
    by_capacity = sorted(spec.capacities, key=lambda f: -spec.capacities[f])
    assert by_capacity == by_weight
    # Bounds: never below her base presence, never above double.
    for family, capacity in spec.capacities.items():
        assert spec.blend[family] <= capacity <= 2 * spec.blend[family]


# -- 3. boundary absolute --------------------------------------------


def test_3_boundary_absolute_even_for_dominant_strand(
    ve_conn, conv, narr, agent
):
    _weigh()  # Compass is the dominant strand (0.40)
    _source(conv, USER, "compass")
    _source(conv, USER, "heart")
    conv.add_topic_boundary(USER, "compass", "the money side")
    spec = _derive(conv, narr, agent)
    assert "Compass" not in spec.growth_mask
    assert "Heart" in spec.growth_mask
    assert spec.coverage["boundaries_in_force"] == [
        {"strand": "Compass", "topic": "the money side"}
    ]


# -- 4. no relation, no interaction -----------------------------------


def test_4_no_recorded_relation_no_interaction(ve_conn, conv, narr, agent):
    _weigh()
    _source(conv, USER, "heart")
    _source(conv, USER, "voice")
    _source(conv, USER, "voice", label="Second note")
    # Threads exist — but none is PRECISELY this Work's thread:
    # one belongs to another entity, one carries no annotation.
    _thread(narr, USER, "ev-other", "project:someone-else")
    _thread(narr, USER, "ev-bare", None)
    spec = _derive(conv, narr, agent)
    assert spec.interactions == ()
    assert spec.coverage["narrative_thread_ids"] == []
    assert spec.coverage["narrative_thread_match"] == "none"
    # The inputs were rich (complexity moved) — the emptiness is
    # about relations, not about poverty of record.
    assert spec.complexity["Heart"] >= 1
    assert spec.complexity["Voice"] >= 1


# -- 5. tension, never resolution --------------------------------------


def test_5_contradicted_change_is_tension_never_resolution(
    ve_conn, conv, narr, agent
):
    thread = _thread(narr, USER, "ev-1", TARGET_REF)
    contra = narr.record_change(
        USER,
        thread.id,
        kind="contradicted",
        evidence_refs=[
            SourceRef(kind="event", ref_id="ev-2", evidence_kind="entity_ref")
        ],
    )
    narr.set_change_status(USER, contra.id, "confirmed")
    extended = narr.record_change(
        USER,
        thread.id,
        kind="extended",
        evidence_refs=[
            SourceRef(kind="event", ref_id="ev-3", evidence_kind="entity_ref")
        ],
    )
    narr.set_change_status(USER, extended.id, "confirmed")
    unconfirmed = narr.record_change(
        USER,
        thread.id,
        kind="contradicted",
        evidence_refs=[
            SourceRef(kind="event", ref_id="ev-4", evidence_kind="entity_ref")
        ],
    )
    spec = _derive(conv, narr, agent)
    tensions = [e for e in spec.interactions if e["kind"] == "tension"]
    assert len(tensions) == 1
    assert tensions[0]["source_id"] == contra.id
    assert tensions[0]["change_kind"] == "contradicted"
    changes = [e for e in spec.interactions if e["kind"] == "change"]
    assert [e["source_id"] for e in changes] == [extended.id]
    # Nothing anywhere is ever labelled a resolution, and the
    # unconfirmed change contributes nothing at all.
    all_entries = list(spec.interactions) + list(spec.provisional)
    assert all(e["kind"] != "resolution" for e in all_entries)
    assert all(e["source_id"] != unconfirmed.id for e in all_entries)


# -- 6. unpresented claims are silent -----------------------------------


def test_6_unpresented_claims_contribute_nothing(ve_conn, conv, narr, agent):
    claim_a = "weav:impression:self+people:run1"  # Compass + Heart
    claim_b = "weav:impression:word:run2"  # Voice
    _seed_claim(agent, claim_a)
    _seed_claim(agent, claim_b)

    silent = _derive(conv, narr, agent)
    assert silent.provisional == ()
    assert all(tier == 0 for tier in silent.complexity.values())
    assert silent.coverage["presented_claims_found"] == 0

    _present(conv, claim_a)
    spec = _derive(conv, narr, agent)
    claims = [e for e in spec.provisional if e["kind"] == "impression_claim"]
    assert len(claims) == 1
    assert claims[0]["source_id"] == claim_a
    assert claims[0]["standing"] == "presented_unruled"
    assert claims[0]["strands"] == ["Heart", "Compass"]
    assert spec.complexity["Heart"] == 1
    assert spec.complexity["Compass"] == 1
    assert spec.complexity["Voice"] == 0  # claim B was never presented
    assert spec.coverage["presented_claims_found"] == 1


# -- 7. determinism + read-only ------------------------------------------


def test_7_deterministic_and_read_only(ve_conn, conv, narr, agent, tmp_path):
    _weigh()
    _source(conv, USER, "heart")
    conv.add_topic_boundary(USER, "ear", "not the schedule")
    thread = _thread(narr, USER, "ev-1", TARGET_REF)
    change = narr.record_change(
        USER,
        thread.id,
        kind="extended",
        evidence_refs=[
            SourceRef(kind="event", ref_id="ev-2", evidence_kind="entity_ref")
        ],
    )
    narr.set_change_status(USER, change.id, "confirmed")
    claim = "weav:impression:self:run1"
    _seed_claim(agent, claim)
    _present(conv, claim)

    db_paths = [
        tmp_path / "conv.db",
        tmp_path / "narr.db",
        tmp_path / "agent.db",
    ]
    before = [_sha(p) for p in db_paths]
    first = _derive(conv, narr, agent)
    second = _derive(conv, narr, agent)
    after = [_sha(p) for p in db_paths]
    assert first.to_json() == second.to_json()
    assert first.to_dict() == second.to_dict()
    assert before == after  # the derivation wrote nothing, anywhere


# -- 8. ownership ----------------------------------------------------------


def test_8_other_users_records_never_appear(ve_conn, conv, narr, agent):
    _weigh(user=USER)
    _weigh(
        user=OTHER,
        weights={
            "Ear": 0.70,
            "Compass": 0.10,
            "Logic": 0.05,
            "Voice": 0.05,
            "Heart": 0.04,
            "Eye": 0.03,
            "Hands": 0.03,
        },
    )
    _thread(narr, USER, "ev-1", TARGET_REF)
    _source(conv, USER, "heart")

    theirs = _derive(conv, narr, agent, user=OTHER)
    # The other user reads only their own records: their own
    # weights shape their spec; the first user's thread, sources,
    # and activity are invisible — never borrowed.
    assert theirs.coverage["unweighed"] is False
    assert theirs.capacities["Ear"] == 0.085  # 0.05 blend × 1.70
    assert theirs.interactions == ()
    assert theirs.growth_mask == ()
    assert theirs.coverage["narrative_thread_ids"] == []

    mine = _derive(conv, narr, agent, user=USER)
    assert mine.coverage["narrative_thread_match"] == "precise_dominant_entity"
    assert mine.capacities["Compass"] == 0.35


# -- 9. recognition-absent degradation --------------------------------------


def test_9_no_recognition_proposals_degrades_cleanly(
    ve_conn, conv, narr, agent
):
    claim = "weav:impression:self:run1"
    _seed_claim(agent, claim)
    _present(conv, claim)
    thread = _thread(narr, USER, "ev-1", TARGET_REF)

    spec = _derive(conv, narr, agent)
    assert [e["kind"] for e in spec.provisional] == ["impression_claim"]
    assert spec.coverage["recognition_absent"] is True
    assert spec.coverage["provisional_sources"] == [
        "presented_impression_claims"
    ]

    # When a proposal does exist on the Work's thread, it is read
    # generically — with its source id and standing attached.
    reading = narr.propose_reading(
        USER,
        thread.id,
        author="user",
        reading={"tensions": ["roots vs. road"]},
        evidence_refs=[
            SourceRef(kind="event", ref_id="ev-1", evidence_kind="entity_ref")
        ],
    )
    spec2 = _derive(conv, narr, agent)
    readings = [e for e in spec2.provisional if e["kind"] == "reading"]
    assert len(readings) == 1
    assert readings[0]["source_id"] == reading.id
    assert readings[0]["standing"] == "proposed"
    assert spec2.coverage["recognition_absent"] is False
    assert "thread_proposals" in spec2.coverage["provisional_sources"]


# -- extra: recorded relations render as interactions -----------------------


def test_recorded_relations_render(ve_conn, conv, narr, agent):
    mine = _thread(narr, USER, "ev-1", TARGET_REF, title="The Work")
    other = _thread(narr, USER, "ev-9", "project:neighbour", title="Neighbour")
    link = narr.link_threads(USER, mine.id, other.id)
    accepted = narr.create_correspondence(
        USER,
        thread_ids=[mine.id, other.id],
        evidence_refs=["ev-1", "ev-9"],
        structural_tension="two arcs pull on one fence line",
        proposed_relationship="a shared boundary, kept from both sides",
        limitations="a shape, not a claim about either arc",
    )
    narr.set_correspondence_status(USER, accepted.id, "user_accepted")
    proposed = narr.create_correspondence(
        USER,
        thread_ids=[mine.id, other.id],
        evidence_refs=["ev-1", "ev-9"],
        structural_tension="both arcs pause at the same season",
        proposed_relationship="a shared rest",
        limitations="a shape, not a claim about either arc",
    )
    spec = _derive(conv, narr, agent)
    kinds = {(e["kind"], e["source_id"]) for e in spec.interactions}
    assert ("link", link.id) in kinds
    assert ("correspondence", accepted.id) in kinds
    link_entry = next(e for e in spec.interactions if e["kind"] == "link")
    assert link_entry["standing"] == "recorded"
    assert link_entry["other_thread_id"] == other.id
    # The merely-proposed correspondence stays provisional.
    prov = {(e["kind"], e["source_id"]) for e in spec.provisional}
    assert ("correspondence", proposed.id) in prov
    assert all(e["source_id"] != proposed.id for e in spec.interactions)
