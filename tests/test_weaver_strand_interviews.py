"""Weaver strand interview tests (rev2, as accepted).

Covers the pure strand modules (keys, orientation, C1 evidence,
C2 boundaries, guidance), the ConversationStore strand tables, and
the strand routes + Talk-path integration via TestClient. The LLM is
faked everywhere; the store uses a tmp SQLite file. No live model
calls, no network.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.conversation_routes as conv_routes
import local_ai.conversation.reply as reply_mod
import local_ai.conversation.service as service_mod
from api.routes.auth_routes import get_current_user
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.strand_interviews.boundaries import (
    normalize_topic,
    recognize_explicit_boundary,
)
from local_ai.strand_interviews.evidence import classify_claim, tier3_eligible
from local_ai.strand_interviews.guidance import strand_guidance_block
from local_ai.strand_interviews.keys import (
    DESIGN_STRAND_KEYS,
    DESIGN_TO_TAXONOMY,
    TAXONOMY_TO_DESIGN,
    is_valid_strand_key,
    validate_strand_key,
)
from local_ai.strand_interviews.orientation import orientation_for

ALICE = {"id": "user-alice", "email": "alice@x", "display_name": "Alice"}
BOB = {"id": "user-bob", "email": "bob@x", "display_name": "Bob"}


def _fake_generate(prompt: str, **kwargs) -> str:
    return "Fake reply."


def _store(tmp_path) -> ConversationStore:
    return ConversationStore(db_path=tmp_path / "conv.db")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = _store(tmp_path)
    svc = ConversationService(store, generate_fn=_fake_generate)
    monkeypatch.setattr(conv_routes, "_store", lambda: store)
    monkeypatch.setattr(conv_routes, "_service", lambda: svc)
    monkeypatch.setattr(reply_mod, "_default_generate", _fake_generate)
    app = FastAPI()
    app.include_router(conv_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ALICE
    c = TestClient(app)
    yield c, store, svc
    store.close()


# -- keys ----------------------------------------------------------------------


def test_design_keys_are_seven_and_map_both_ways():
    assert DESIGN_STRAND_KEYS == (
        "heart",
        "hands",
        "logic",
        "voice",
        "ear",
        "compass",
        "eye",
    )
    assert set(DESIGN_TO_TAXONOMY) == set(DESIGN_STRAND_KEYS)
    assert set(TAXONOMY_TO_DESIGN) == set(DESIGN_TO_TAXONOMY.values())
    # Founder's definitions: Ear is music/rhythm/listening (OQ1 resolved).
    assert DESIGN_TO_TAXONOMY["ear"] == "sound"
    assert DESIGN_TO_TAXONOMY["heart"] == "people"
    assert DESIGN_TO_TAXONOMY["compass"] == "self"


def test_validate_strand_key_rejects_unknown_and_taxonomy_keys():
    assert validate_strand_key(" Heart ") == "heart"
    assert is_valid_strand_key("eye") is True
    assert is_valid_strand_key("people") is False  # taxonomy, not a strand key
    for bad in ("", "dreams", "people", "sound", "HEARTS", 12, None):
        with pytest.raises(ValueError):
            validate_strand_key(bad)  # type: ignore[arg-type]


# -- orientation (C3) ------------------------------------------------------------


def test_orientation_fresh_is_roots_panel_model():
    # Seven-roots panel model (founder, 2026-11-12): concise question
    # + one short invitation + talk line. Heart's wording is the
    # founder's verbatim.
    orientation = orientation_for("heart", is_fresh=True)
    assert orientation["definition"] == "things you care about"
    assert orientation["is_fresh"] is True
    assert orientation["resume"] is None
    assert orientation["question"] == "What matters to you?"
    assert orientation["invitation"] == (
        "Who and what do you care about, and why? Explore the people, "
        "passions, values, and experiences that hold a special place "
        "in your life."
    )
    assert orientation["talk_line"] == (
        "Talk with the Conductor about something you care about. There's no "
        "right answer, and you can follow the conversation wherever "
        "it leads."
    )
    assert orientation["opening_question"] is None
    # Nonbinding: no claim that anything will be remembered or acted on.
    invitation = orientation["invitation"]
    assert "I'll note" not in invitation and "I'll save" not in invitation


def test_orientation_fresh_panel_copy_present_for_all_seven_roots():
    # Every root carries the full panel model; each talk line names
    # the Conductor (founder's ruling 2026-11-12: role, not personal name) and carries the same reassurance close.
    for key in DESIGN_STRAND_KEYS:
        orientation = orientation_for(key, is_fresh=True)
        assert orientation["question"], key
        assert orientation["invitation"], key
        assert orientation["talk_line"], key
        assert orientation["talk_line"].startswith("Talk with the Conductor about"), key
        assert orientation["talk_line"].endswith(
            "There's no right answer, and you can follow the "
            "conversation wherever it leads."
        ), key
        assert orientation["opening_question"] is None
    # The seven questions are distinct — each root its own center.
    questions = {
        orientation_for(key, is_fresh=True)["question"]
        for key in DESIGN_STRAND_KEYS
    }
    assert len(questions) == 7


def test_orientation_returning_is_resume_only_no_opener_no_greeting():
    orientation = orientation_for("heart", is_fresh=False)
    assert orientation["is_fresh"] is False
    assert orientation["resume"] is True
    assert orientation["opening_question"] is None
    assert orientation["question"] is None
    assert orientation["talk_line"] is None
    assert "where you left off" in orientation["invitation"]
    assert "Hello" not in orientation["invitation"]


def test_orientation_rejects_unknown_key():
    with pytest.raises(ValueError):
        orientation_for("dreams", is_fresh=True)


# -- C1 evidence -----------------------------------------------------------------


def test_c1_intention_grounds_on_one_clear_declaration():
    assert tier3_eligible("intention", declarations=1).eligible is True
    assert tier3_eligible("intention", declarations=1).evidence_strength == (
        "one clear declaration"
    )
    assert tier3_eligible("intention", declarations=0).eligible is False


def test_c1_stable_disposition_needs_recurrence_plus_confirmation():
    assert tier3_eligible("stable", recurrence=1, confirmations=1).eligible is False
    assert tier3_eligible("stable", recurrence=2, confirmations=0).eligible is False
    assert tier3_eligible("stable", recurrence=2, confirmations=1).eligible is True
    assert tier3_eligible("recurring", recurrence=2, confirmations=1).eligible is True


def test_c1_borderline_proposed_only_with_strength_stated():
    no_grounding = tier3_eligible("borderline")
    assert no_grounding.eligible is False
    assert no_grounding.must_state_strength is True
    grounded = tier3_eligible("borderline", declarations=1)
    assert grounded.eligible is True
    assert grounded.must_state_strength is True


def test_c1_unknown_kind_is_borderline():
    assert classify_claim("wobbly") == "borderline"
    assert tier3_eligible("wobbly").eligible is False


# -- C2 boundaries ---------------------------------------------------------------


def test_c2_explicit_boundary_words_record_a_topic():
    assert recognize_explicit_boundary("Never ask me about my favorite song again.") == (
        "my favorite song"
    )
    assert recognize_explicit_boundary("Don't bring up my divorce.") == "my divorce"
    assert recognize_explicit_boundary("Never mention work trips.") == "work trips"


def test_c2_ordinary_declines_never_record_a_topic():
    # The verdict's normative song example: "Not feeling that question
    # right now" about a favorite song must NOT prohibit a genuinely
    # new question about music six months later.
    assert recognize_explicit_boundary("Not feeling that question right now.") is None
    assert recognize_explicit_boundary("Not now.") is None
    assert recognize_explicit_boundary("Not that question.") is None
    assert recognize_explicit_boundary("Never ask me that again.") is None
    assert recognize_explicit_boundary("I don't want to talk about it.") is None
    assert recognize_explicit_boundary("I've had enough of your poking around.") is None


def test_c2_normalize_topic_dedupes():
    assert normalize_topic("My Favorite Song") == normalize_topic("my favorite song!")
    assert normalize_topic("  work   trips  ") == "work trips"


# -- guidance --------------------------------------------------------------------


def test_guidance_block_carries_pattern_pressure_and_thresholds():
    block = strand_guidance_block("ear")
    assert "Ear" in block
    assert "ONE question at a time" in block
    assert "no guilt" in block
    assert "one clear declaration" in block
    assert "recurrence" in block


def test_guidance_block_renders_boundaries_and_sources_bounded():
    block = strand_guidance_block(
        "heart",
        boundaries=[{"topic": "my divorce"}],
        sources=[
            {
                "kind": "paste",
                "label": "Note",
                "excerpt": "I care about quiet mornings.",
            }
        ],
    )
    assert "my divorce" in block
    assert "do NOT raise these topics" in block
    assert "quiet mornings" in block
    long_topic = "x" * 5000
    block = strand_guidance_block("heart", boundaries=[{"topic": long_topic}])
    assert len(block) < 5000


# -- store: strand threads --------------------------------------------------------


def test_store_resolve_is_idempotent_and_per_strand(tmp_path):
    store = _store(tmp_path)
    try:
        first = store.resolve_strand_thread("user-alice", "heart")
        assert first["is_fresh"] is True
        second = store.resolve_strand_thread("user-alice", "heart")
        assert second["conversation_id"] == first["conversation_id"]
        assert second["is_fresh"] is True  # still no messages
        other = store.resolve_strand_thread("user-alice", "ear")
        assert other["conversation_id"] != first["conversation_id"]
        # Per-user isolation: another user gets a different thread.
        bobs = store.resolve_strand_thread("user-bob", "heart")
        assert bobs["conversation_id"] != first["conversation_id"]
        # Reverse lookup.
        assert store.get_strand_key_for_conversation(
            "user-alice", first["conversation_id"]
        ) == "heart"
        assert store.get_strand_key_for_conversation("user-alice", "talk-nope") is None
        assert store.get_strand_key_for_conversation(
            "user-bob", first["conversation_id"]
        ) is None
    finally:
        store.close()


def test_store_resolve_fresh_flips_after_a_message(tmp_path):
    store = _store(tmp_path)
    try:
        resolved = store.resolve_strand_thread("user-alice", "voice")
        cid = resolved["conversation_id"]
        store.append_message("user-alice", cid, "conductor", "user", "hello")
        again = store.resolve_strand_thread("user-alice", "voice")
        assert again["conversation_id"] == cid
        assert again["is_fresh"] is False
    finally:
        store.close()


def test_store_clear_keeps_mapping(tmp_path):
    store = _store(tmp_path)
    try:
        resolved = store.resolve_strand_thread("user-alice", "logic")
        cid = resolved["conversation_id"]
        store.append_message("user-alice", cid, "conductor", "user", "hi")
        store.clear_conversation("user-alice", cid)
        again = store.resolve_strand_thread("user-alice", "logic")
        assert again["conversation_id"] == cid
        assert again["is_fresh"] is True
    finally:
        store.close()


def test_store_boundaries_idempotent_and_reopenable(tmp_path):
    store = _store(tmp_path)
    try:
        first = store.add_topic_boundary("user-alice", "heart", "my divorce")
        second = store.add_topic_boundary("user-alice", "heart", "My Divorce!")
        assert second["id"] == first["id"]  # deduped by normalized topic
        assert [b["topic"] for b in store.list_topic_boundaries("user-alice", "heart")] == [
            "my divorce"
        ]
        assert store.list_topic_boundaries("user-alice", "ear") == []
        assert store.delete_topic_boundary("user-alice", first["id"]) is True
        assert store.list_topic_boundaries("user-alice", "heart") == []
        assert store.delete_topic_boundary("user-alice", first["id"]) is False
        assert store.delete_topic_boundary("user-bob", first["id"]) is False
        with pytest.raises(ValueError):
            store.add_topic_boundary("user-alice", "heart", "   ")
    finally:
        store.close()


def test_store_sources_are_per_strand(tmp_path):
    store = _store(tmp_path)
    try:
        heart = store.resolve_strand_thread("user-alice", "heart")
        store.add_strand_source(
            "user-alice", "heart", heart["conversation_id"], "paste", "paste",
            label="Note", excerpt_redacted="quiet mornings",
        )
        assert len(store.list_strand_sources("user-alice", "heart")) == 1
        assert store.list_strand_sources("user-alice", "ear") == []
        assert store.list_strand_sources("user-bob", "heart") == []
        with pytest.raises(ValueError):
            store.add_strand_source(
                "user-alice", "heart", heart["conversation_id"], "link", "https://x"
            )
    finally:
        store.close()


# -- routes: resolve (T1 / T1b) ----------------------------------------------------


def test_resolve_is_fresh_and_orientation_present(client):
    c, store, _ = client
    r = c.get("/conversation/strand/heart")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["strand_key"] == "heart"
    assert body["strand_name"] == "Heart"
    assert "things you care about" in body["definition"]
    assert body["is_fresh"] is True
    assert body["conversation_id"].startswith("talk-")
    assert body["orientation"]["question"] == "What matters to you?"
    assert body["orientation"]["invitation"].startswith(
        "Who and what do you care about, and why?"
    )
    assert body["orientation"]["talk_line"] == (
        "Talk with the Conductor about something you care about. There's no "
        "right answer, and you can follow the conversation wherever "
        "it leads."
    )
    assert body["orientation"]["opening_question"] is None
    assert body["boundaries"] == []
    assert body["sources"] == []
    assert "reply" not in body  # no generated turn on open


def test_resolve_makes_zero_model_calls(client, monkeypatch):
    """T1b: opening a strand thread must never generate."""
    c, store, svc = client

    def _boom(prompt: str, **kwargs):
        raise AssertionError("model called on strand open")

    monkeypatch.setattr(svc, "_generate_fn", _boom)
    r = c.get("/conversation/strand/ear")
    assert r.status_code == 200, r.text
    cid = r.json()["conversation_id"]
    assert store.count_messages("user-alice", cid) == 0


def test_resolve_rejects_unknown_strand(client):
    c, _, _ = client
    assert c.get("/conversation/strand/dreams").status_code == 422
    assert c.get("/conversation/strand/people").status_code == 422


def test_resolve_is_owner_scoped(client, monkeypatch):
    """Another user's resolve never returns Alice's thread."""
    c, store, _ = client
    alice = c.get("/conversation/strand/heart").json()
    # Rebind the current user to Bob and resolve the same strand.
    from api.routes.auth_routes import get_current_user as _gcu

    c.app.dependency_overrides[_gcu] = lambda: BOB
    bob = c.get("/conversation/strand/heart").json()
    assert bob["conversation_id"] != alice["conversation_id"]
    assert bob["is_fresh"] is True


# -- routes: turn in a strand thread -----------------------------------------------


def test_turn_in_strand_thread_carries_guidance_and_keeps_key(client, monkeypatch):
    c, store, svc = client
    cid = c.get("/conversation/strand/heart").json()["conversation_id"]
    prompts: list[str] = []

    def _capture(prompt: str, **kwargs):
        prompts.append(prompt)
        return "Fake reply."

    monkeypatch.setattr(svc, "_generate_fn", _capture)
    r = c.post(
        "/conversation/turn",
        json={
            "archetype_id": "conductor",
            "message": "I care about quiet mornings.",
            "conversation_id": cid,
            "context": {"strand_key": "heart"},
        },
    )
    assert r.status_code == 200, r.text
    assert prompts, "generation path was not used"
    assert "Heart" in prompts[0]
    assert "ONE question at a time" in prompts[0]
    msgs = c.get("/conversation", params={"conversation_id": cid}).json()["messages"]
    assert msgs[0]["body"] == "I care about quiet mornings."
    assert msgs[0]["context"]["strand_key"] == "heart"


def test_turn_rejects_forged_or_mismatched_strand_key(client):
    c, _, _ = client
    heart = c.get("/conversation/strand/heart").json()["conversation_id"]
    ear = c.get("/conversation/strand/ear").json()["conversation_id"]
    # Unknown strand key.
    r = c.post(
        "/conversation/turn",
        json={
            "archetype_id": "conductor",
            "message": "hi",
            "conversation_id": heart,
            "context": {"strand_key": "dreams"},
        },
    )
    assert r.status_code == 422, r.text
    # Heart's thread with Ear's key: mismatch.
    r = c.post(
        "/conversation/turn",
        json={
            "archetype_id": "conductor",
            "message": "hi",
            "conversation_id": heart,
            "context": {"strand_key": "ear"},
        },
    )
    assert r.status_code == 422, r.text
    # Ear's thread with Heart's key: mismatch.
    r = c.post(
        "/conversation/turn",
        json={
            "archetype_id": "conductor",
            "message": "hi",
            "conversation_id": ear,
            "context": {"strand_key": "heart"},
        },
    )
    assert r.status_code == 422, r.text
    # A foreign conversation id with a valid key: also a mismatch.
    r = c.post(
        "/conversation/turn",
        json={
            "archetype_id": "conductor",
            "message": "hi",
            "conversation_id": "talk-00000000000000000000000000000000",
            "context": {"strand_key": "heart"},
        },
    )
    assert r.status_code == 422, r.text


def test_turn_scrubs_strand_key_for_other_seats(client):
    c, _, _ = client
    cid = c.get("/conversation/strand/heart").json()["conversation_id"]
    r = c.post(
        "/conversation/turn",
        json={
            "archetype_id": "mentor",
            "message": "plan my week",
            "conversation_id": cid,
            "context": {"strand_key": "heart"},
        },
    )
    assert r.status_code == 200, r.text
    msgs = c.get("/conversation", params={"conversation_id": cid}).json()["messages"]
    assert "strand_key" not in (msgs[0]["context"] or {})


def test_turn_records_explicit_boundary_but_not_ordinary_decline(client):
    c, store, _ = client
    cid = c.get("/conversation/strand/heart").json()["conversation_id"]
    r = c.post(
        "/conversation/turn",
        json={
            "archetype_id": "conductor",
            "message": "Never ask me about my divorce again.",
            "conversation_id": cid,
            "context": {"strand_key": "heart"},
        },
    )
    assert r.status_code == 200, r.text
    assert [b["topic"] for b in store.list_topic_boundaries("user-alice", "heart")] == [
        "my divorce"
    ]
    # Ordinary decline: no boundary recorded.
    r = c.post(
        "/conversation/turn",
        json={
            "archetype_id": "conductor",
            "message": "Not feeling that question right now.",
            "conversation_id": cid,
            "context": {"strand_key": "heart"},
        },
    )
    assert r.status_code == 200, r.text
    assert len(store.list_topic_boundaries("user-alice", "heart")) == 1


def test_turn_guidance_includes_active_boundary_and_file_excerpt(client, monkeypatch):
    c, store, svc = client
    cid = c.get("/conversation/strand/ear").json()["conversation_id"]
    store.add_topic_boundary("user-alice", "ear", "work trips")
    store.add_strand_source(
        "user-alice", "ear", cid, "file", "sess-1", label="Playlist notes"
    )
    monkeypatch.setattr(
        service_mod,
        "_read_file_source_excerpts",
        lambda session_id: ["redacted event: a song about rain"],
    )
    prompts: list[str] = []

    def _capture(prompt: str, **kwargs):
        prompts.append(prompt)
        return "Fake reply."

    monkeypatch.setattr(svc, "_generate_fn", _capture)
    r = c.post(
        "/conversation/turn",
        json={
            "archetype_id": "conductor",
            "message": "I love songs about rain.",
            "conversation_id": cid,
            "context": {"strand_key": "ear"},
        },
    )
    assert r.status_code == 200, r.text
    assert "work trips" in prompts[0]
    assert "a song about rain" in prompts[0]


def test_strand_thread_appears_in_conductor_list_after_a_turn(client):
    """R1 interplay: a strand thread is an ordinary Weaver Talk thread."""
    c, _, _ = client
    cid = c.get("/conversation/strand/compass").json()["conversation_id"]
    c.post(
        "/conversation/turn",
        json={
            "archetype_id": "conductor",
            "message": "I wonder about meaning.",
            "conversation_id": cid,
            "context": {"strand_key": "compass"},
        },
    )
    r = c.get("/conversation/list", params={"seat": "conductor"})
    assert r.status_code == 200, r.text
    ids = [entry["conversation_id"] for entry in r.json()["conversations"]]
    assert cid in ids


# -- routes: boundaries ------------------------------------------------------------


def test_boundary_endpoints_add_and_reopen(client):
    c, _, _ = client
    r = c.post("/conversation/strand/heart/boundaries", json={"topic": "my divorce"})
    assert r.status_code == 200, r.text
    boundary_id = r.json()["id"]
    # Idempotent re-add returns the same row.
    r2 = c.post("/conversation/strand/heart/boundaries", json={"topic": "My Divorce!"})
    assert r2.status_code == 200
    assert r2.json()["id"] == boundary_id
    # Resolve payload now carries it.
    assert [b["topic"] for b in c.get("/conversation/strand/heart").json()["boundaries"]] == [
        "my divorce"
    ]
    r = c.delete(f"/conversation/strand/heart/boundaries/{boundary_id}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    assert c.get("/conversation/strand/heart").json()["boundaries"] == []
    assert c.delete(f"/conversation/strand/heart/boundaries/{boundary_id}").status_code == 404
    assert c.post("/conversation/strand/heart/boundaries", json={"topic": "  "}).status_code == 422
    assert c.post("/conversation/strand/dreams/boundaries", json={"topic": "x"}).status_code == 422


# -- routes: sources -----------------------------------------------------------------


def test_paste_source_is_redacted_at_capture(client):
    c, _, _ = client
    r = c.post(
        "/conversation/strand/heart/sources",
        json={
            "kind": "paste",
            "text": "Reach me at alice@example.com or 415-555-0132. I care about mornings.",
            "label": "Note",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "paste"
    assert "alice@example.com" not in body["excerpt"]
    assert "415-555-0132" not in body["excerpt"]
    assert "mornings" in body["excerpt"]
    listed = c.get("/conversation/strand/heart/sources").json()["sources"]
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]
    assert c.post(
        "/conversation/strand/heart/sources", json={"kind": "paste", "text": "   "}
    ).status_code == 422
    assert c.post(
        "/conversation/strand/heart/sources", json={"kind": "link", "text": "x"}
    ).status_code == 422


class _FakeSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.file_name = "notes.pdf"


class _FakeIngestStore:
    def __init__(self, sessions: dict):
        self._sessions = sessions

    def get_session(self, session_id: str):
        return self._sessions.get(session_id)


def test_file_source_requires_known_session(client, monkeypatch):
    c, _, _ = client
    monkeypatch.setattr(
        conv_routes,
        "_ingest_store",
        lambda: _FakeIngestStore({"sess-1": _FakeSession("sess-1")}),
    )
    r = c.post(
        "/conversation/strand/ear/sources",
        json={"kind": "file", "ingest_session_id": "sess-unknown"},
    )
    assert r.status_code == 404, r.text
    r = c.post(
        "/conversation/strand/ear/sources",
        json={"kind": "file", "ingest_session_id": "sess-1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "file"
    assert r.json()["label"] == "notes.pdf"
    # Cross-strand isolation: the file source is in Ear, not Heart.
    assert c.get("/conversation/strand/heart/sources").json()["sources"] == []
    assert len(c.get("/conversation/strand/ear/sources").json()["sources"]) == 1


def test_strand_resolve_needs_no_meeting_state(client):
    """T8: resolve works on a fresh store with no meeting ever started."""
    c, store, _ = client
    r = c.get("/conversation/strand/eye")
    assert r.status_code == 200, r.text
    assert r.json()["is_fresh"] is True
