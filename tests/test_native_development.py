"""Native character development (Increment N1) tests.

The developmental loop's machinery + records, shipped dark behind
ZENAF_NATIVE_DEVELOPMENT. These tests prove, at the record level:

- correction-as-verdict (an explicit correction IS its verdict —
  no second confirmation act; derived interpretations wait pending);
- before/after seizure in the act;
- transformative development (C1): replace / revise / retire —
  never accumulation-only;
- pinned-state independence (C4): a designated character state
  resolves identically whatever the author's current state is;
- reach + authority recorded as separate facts on acts (R-2);
- designation confers neither eligibility nor training
  authorization, and retroactive designation keeps honest temporal
  provenance;
- erasure enumeration membership + tombstoning along the store's
  dependency edges;
- reconstruction verification (P-2) over a real generated turn's
  manifest, with the fingerprint as the verification mechanism,
  and Tier-2 legs named where references are absent;
- the Talk-path wiring: carriage + Tier-1 preservation + manifest
  references for author interactions only, flag-gated — a visitor's
  turn and a flag-off turn carry none of it.

The LLM is faked everywhere; no real provider calls.
"""

from __future__ import annotations

import sqlite3

import pytest

from local_ai.conversation.reply import (
    build_voice_prompt,
    generate_voice_reply,
)
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.development import native_development_enabled
from local_ai.development.reconstruction import (
    assess_tier2,
    verify_from_builder,
    verify_reconstruction,
)
from local_ai.development.service import AuthorshipError, DevelopmentService
from local_ai.development.store import (
    DEV_ERASURE_USER_TABLES,
    DevelopmentStore,
)
from local_ai.feedback.store import FeedbackStore

AUTHOR = "author-1"
OTHER = "someone-else"
CHAR = "mentor"


@pytest.fixture()
def dev(tmp_path):
    store = DevelopmentStore(db_path=tmp_path / "dev.db")
    svc = DevelopmentService(store)
    store.register_authorship(CHAR, AUTHOR)
    return svc, store


def _correct(svc, body, **kw):
    return svc.record_correction(
        author_id=AUTHOR,
        character_id=CHAR,
        verbatim=f"Correction: {body}",
        ops=[{"op": "add", "body": body}],
        **kw,
    )


# -- correction-as-verdict ---------------------------------------------------


def test_explicit_correction_is_its_own_verdict(dev):
    svc, store = dev
    out = _correct(svc, "Holds mornings sacred; never schedule before ten.")
    act, verdict = out["act"], out["verdict"]
    assert act["confirmation_status"] == "verdict"
    assert verdict is not None
    assert verdict["act_id"] == act["id"]
    # No confirmation step exists or is needed: nothing is pending.
    assert svc.pending_confirmations(AUTHOR) == []
    # The material is carried immediately.
    carried = store.carried_material(CHAR, author_id=AUTHOR)
    assert [m["body"] for m in carried] == [
        "Holds mornings sacred; never schedule before ten."
    ]


def test_derived_interpretation_waits_for_confirmation(dev):
    svc, store = dev
    out = svc.record_correction(
        author_id=AUTHOR,
        character_id=CHAR,
        verbatim="Derived: perhaps he distrusts mornings generally.",
        ops=[{"op": "add", "body": "Distrusts mornings generally."}],
        derived=True,
    )
    assert out["verdict"] is None
    assert store.carried_material(CHAR, author_id=AUTHOR) == []
    pending = svc.pending_confirmations(AUTHOR)
    assert [p["id"] for p in pending] == [out["act"]["id"]]
    confirmed = svc.confirm_act(act_id=out["act"]["id"], author_id=AUTHOR)
    assert confirmed["verdict"] is not None
    assert [m["body"] for m in store.carried_material(CHAR, author_id=AUTHOR)] == [
        "Distrusts mornings generally."
    ]
    assert svc.pending_confirmations(AUTHOR) == []


def test_before_and_after_states_seized_in_the_act(dev):
    svc, store = dev
    first = _correct(svc, "First perspective.")
    second = _correct(svc, "Second perspective.")
    v1, v2 = first["verdict"], second["verdict"]
    # The first correction's before state is empty; its after state
    # is a minted character state carrying exactly the material.
    assert v1["before_material"] == []
    assert [m["body"] for m in v1["after_material"]] == ["First perspective."]
    assert v1["after_state_id"].startswith("cs-")
    # The second correction seizes the first state as its before.
    assert v2["before_state_id"] == v1["after_state_id"]
    assert [m["body"] for m in v2["before_material"]] == ["First perspective."]
    assert [m["body"] for m in v2["after_material"]] == [
        "First perspective.",
        "Second perspective.",
    ]
    # The after state is parented on the before state (ancestry).
    after = store.get_character_state(v2["after_state_id"])
    assert after["parent_state_id"] == v1["after_state_id"]
    assert after["content"]["material"] == [
        "First perspective.",
        "Second perspective.",
    ]


def test_creative_act_needs_no_occasion(dev):
    svc, store = dev
    out = svc.record_correction(
        author_id=AUTHOR,
        character_id=CHAR,
        verbatim="A new disposition, brought into being.",
        ops=[],
        targets=[],
        occasion_ref=None,
        kind="creative",
    )
    assert out["act"]["confirmation_status"] == "verdict"
    assert out["act"]["targets"] == []
    assert out["verdict"] is not None


def test_non_author_cannot_correct(dev):
    svc, _store = dev
    with pytest.raises(AuthorshipError):
        svc.record_correction(
            author_id=OTHER,
            character_id=CHAR,
            verbatim="Not mine to correct.",
            ops=[{"op": "add", "body": "Nope."}],
        )


# -- C1: transformative, not accumulative -------------------------------------


def test_replacement_does_not_accumulate(dev):
    svc, store = dev
    first = _correct(svc, "Original phrasing.")
    material_id = first["verdict"]["after_material"][0]["id"]
    svc.record_correction(
        author_id=AUTHOR,
        character_id=CHAR,
        verbatim="Replace it.",
        ops=[{"op": "replace", "material_id": material_id, "body": "New phrasing."}],
    )
    carried = store.carried_material(CHAR, author_id=AUTHOR)
    assert [m["body"] for m in carried] == ["New phrasing."]
    old = store.get_perspective_material(material_id)
    assert old["status"] == "replaced"
    # The old text survives as lineage, never edited in place.
    assert old["body"] == "Original phrasing."


def test_retirement_stops_carriage(dev):
    svc, store = dev
    first = _correct(svc, "Soon to retire.")
    material_id = first["verdict"]["after_material"][0]["id"]
    svc.record_correction(
        author_id=AUTHOR,
        character_id=CHAR,
        verbatim="Retire it.",
        ops=[{"op": "retire", "material_id": material_id}],
    )
    assert store.carried_material(CHAR, author_id=AUTHOR) == []
    assert store.get_perspective_material(material_id)["status"] == "retired"


def test_state_minting_requires_content_complete_referent(dev):
    _svc, store = dev
    with pytest.raises(ValueError):
        store.mint_character_state(
            character_id=CHAR, author_id=AUTHOR, content={"material": []}
        )
    with pytest.raises(ValueError):
        store.mint_character_state(
            character_id=CHAR, author_id=AUTHOR, content={}
        )
    state = store.mint_character_state(
        character_id=CHAR,
        author_id=AUTHOR,
        content={"material": ["Something real."]},
        git_anchor="feb2c9e",
    )
    # Typed as a character state — never the git anchor.
    assert state["id"].startswith("cs-")
    assert state["id"] != "feb2c9e"
    assert state["git_anchor"] == "feb2c9e"


# -- C4: pinned-state independence ---------------------------------------------


def test_pinned_state_resolves_independent_of_current_state(dev):
    svc, store = dev
    first = _correct(svc, "Pinned-era perspective.")
    pinned_id = first["verdict"]["after_state_id"]
    # The author develops the character further; the current state moves.
    second = _correct(svc, "Later perspective.")
    current = svc.resolve_character_state(character_id=CHAR, viewer_id=AUTHOR)
    assert current["id"] == second["verdict"]["after_state_id"]
    # The pinned state still resolves to exactly itself.
    pinned = svc.resolve_character_state(
        character_id=CHAR, viewer_id=AUTHOR, pinned_state_id=pinned_id
    )
    assert pinned["id"] == pinned_id
    assert pinned["content"]["material"] == ["Pinned-era perspective."]
    # Even a stranger's pinned resolution (an evaluation harness
    # naming the state) gets the designated state, not the current one.
    pinned2 = svc.resolve_character_state(
        character_id=CHAR, pinned_state_id=pinned_id
    )
    assert pinned2["id"] == pinned_id


# -- reach + authority (R-2) -----------------------------------------------------


def test_reach_and_authority_are_separate_facts(dev):
    svc, _store = dev
    out = svc.record_correction(
        author_id=AUTHOR,
        character_id=CHAR,
        verbatim="Reach-marked.",
        ops=[{"op": "add", "body": "Marked."}],
        reach="future_model_adaptation",
    )
    act = out["act"]
    assert act["reach"] == "future_model_adaptation"
    assert act["authority"]["account_id"] == AUTHOR
    assert act["authority"]["authorship_relation"] == "author"
    unmarked = svc.record_correction(
        author_id=AUTHOR,
        character_id=CHAR,
        verbatim="Unmarked.",
        ops=[],
        reach=None,
    )
    assert unmarked["act"]["reach"] is None


def test_feedback_row_carries_reach(tmp_path):
    fb = FeedbackStore(db_path=tmp_path / "fb.db")
    row = fb.add_feedback(
        AUTHOR, "resp-1", "local", "mentor", 5, [], "note",
        reach="character_development",
    )
    assert row["reach"] == "character_development"
    listed = fb.list_feedback(AUTHOR)
    assert listed[0]["reach"] == "character_development"
    plain = fb.add_feedback(AUTHOR, "resp-2", "local", "mentor", 4, [], "")
    assert plain["reach"] is None
    with pytest.raises(ValueError):
        fb.add_feedback(AUTHOR, "resp-3", "local", "mentor", 4, [], "", reach="bogus")


# -- designation (family 5) -------------------------------------------------------


def test_designation_confers_nothing(dev):
    svc, _store = dev
    for purpose in ("native_development", "future_model_adaptation"):
        d = svc.designate(
            author_id=AUTHOR,
            character_id=CHAR,
            material_ref="act-123",
            purpose=purpose,
        )
        assert d["confers_eligibility"] is False
        assert d["confers_training_authorization"] is False
    with pytest.raises(ValueError):
        svc.designate(
            author_id=AUTHOR,
            character_id=CHAR,
            material_ref="act-123",
            purpose="train_everything",
        )
    with pytest.raises(AuthorshipError):
        svc.designate(
            author_id=OTHER,
            character_id=CHAR,
            material_ref="act-123",
            purpose="native_development",
        )


def test_retroactive_designation_keeps_honest_times(dev):
    svc, _store = dev
    d = svc.designate(
        author_id=AUTHOR,
        character_id=CHAR,
        material_ref="old-material",
        purpose="native_development",
        origin_time="2026-11-01T00:00:00+00:00",
    )
    assert d["origin_time"] == "2026-11-01T00:00:00+00:00"
    assert d["designation_time"] > d["origin_time"]


def test_designation_scopes_are_registered_vocabulary():
    from local_ai.identity.scopes import KNOWN_SCOPES, validate_scope

    for scope in (
        "designate:native_development",
        "designate:future_model_adaptation",
    ):
        assert validate_scope(scope) == scope
        assert "no training" in KNOWN_SCOPES[scope] or (
            "neither" in KNOWN_SCOPES[scope]
            or "confers no" in KNOWN_SCOPES[scope]
        )


# -- C3: expression linkage ---------------------------------------------------


def test_expression_links_record_relationships_only(dev):
    svc, store = dev
    first = _correct(svc, "Will it hold?")
    act_id = first["act"]["id"]
    for kind in (
        "interaction",
        "expression",
        "unsuccessful_expression",
        "regression",
        "generalization",
    ):
        svc.link_expression(
            author_id=AUTHOR,
            character_id=CHAR,
            linked_kind=kind,
            lineage_act_id=act_id,
            ref="some-turn",
        )
    links = store.expression_links_for_act(act_id)
    assert {l["linked_kind"] for l in links} == {
        "interaction",
        "expression",
        "unsuccessful_expression",
        "regression",
        "generalization",
    }
    with pytest.raises(ValueError):
        svc.link_expression(
            author_id=AUTHOR,
            character_id=CHAR,
            linked_kind="verdict_of_quality",
            lineage_act_id=act_id,
        )


# -- erasure --------------------------------------------------------------------


def test_erasure_enumeration_covers_every_table(tmp_path):
    store = DevelopmentStore(db_path=tmp_path / "dev.db")
    conn = sqlite3.connect(tmp_path / "dev.db")
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert set(DEV_ERASURE_USER_TABLES) == tables


def test_erasure_tombstones_lineage_and_deletes_content(dev):
    svc, store = dev
    out = _correct(svc, "Erase me eventually.")
    store.preserve_components(
        user_id=AUTHOR,
        conversation_id="c1",
        archetype_id=CHAR,
        assistant_message_id="m1",
        manifest_prompt_sha256="abc",
        components={"thread_summary": "secret summary"},
    )
    svc.designate(
        author_id=AUTHOR,
        character_id=CHAR,
        material_ref=out["act"]["id"],
        purpose="native_development",
    )
    # A second author's material is untouched by the first's erasure.
    store.register_authorship(CHAR, OTHER)
    other = DevelopmentService(store)
    other.record_correction(
        author_id=OTHER,
        character_id=CHAR,
        verbatim="Other author's words.",
        ops=[{"op": "add", "body": "Other perspective."}],
    )
    counts = store.erase_user_material(AUTHOR)
    assert counts["preserved_components"] == 1
    assert store.preserved_for_message("m1") is None
    act = store.get_act(out["act"]["id"])
    assert act["verbatim"] == ""  # tombstoned, lineage shell remains
    assert act["id"] == out["act"]["id"]
    carried_other = store.carried_material(CHAR, author_id=OTHER)
    assert [m["body"] for m in carried_other] == ["Other perspective."]


# -- C6: authorship semantics ---------------------------------------------------


def test_authorship_is_not_platform_administration(tmp_path, monkeypatch):
    import local_ai.development.service as svc_mod

    store = DevelopmentStore(db_path=tmp_path / "dev.db")
    svc = DevelopmentService(store)
    monkeypatch.setattr(svc_mod, "_platform_owner_id", lambda: "owner-9")
    # The platform owner bootstraps as author of a foundational character.
    assert svc.is_author(user_id="owner-9", character_id="champion")
    assert not svc.is_author(user_id="visitor-1", character_id="champion")
    # An independently owned character: its creator is its author,
    # with no platform role involved at all.
    store.register_authorship("visitor-made-character", "visitor-1")
    assert svc.is_author(user_id="visitor-1", character_id="visitor-made-character")
    assert not svc.is_author(user_id="owner-9", character_id="visitor-made-character")


# -- carriage ---------------------------------------------------------------------


def test_carriage_block_renders_revisable_standing(dev):
    svc, _store = dev
    _correct(svc, "Carried perspective.")
    block, ids, state_id = svc.carriage_block(character_id=CHAR, author_id=AUTHOR)
    assert block is not None and "Carried perspective." in block
    assert "revisable" in block
    assert len(ids) == 1
    assert state_id is not None and state_id.startswith("cs-")
    # Another account sees no carriage from this author's material.
    block2, ids2, _ = svc.carriage_block(character_id=CHAR, author_id=OTHER)
    assert block2 is None and ids2 == []


def test_uncarried_adopted_is_auditable(dev):
    svc, store = dev
    svc.record_correction(
        author_id=AUTHOR,
        character_id=CHAR,
        verbatim="Adopt but do not carry.",
        ops=[
            {
                "op": "add",
                "body": "Held back.",
                "carriage_disposition": "do_not_carry",
            }
        ],
    )
    block, ids, _ = svc.carriage_block(character_id=CHAR, author_id=AUTHOR)
    assert block is None and ids == []
    held = svc.uncarried_adopted(character_id=CHAR, author_id=AUTHOR)
    assert [m["body"] for m in held] == ["Held back."]


# -- P-1 / P-2: manifest references + reconstruction -------------------------------


class _Capture:
    def __init__(self, reply: str = "Fake reply."):
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        return self.reply


def test_manifest_stamps_question_flag_and_code_ref():
    cap = _Capture()
    out = generate_voice_reply(
        "u1", "mentor", "What should I focus on?",
        [], question=True, generate_fn=cap,
    )
    manifest = out.generation_manifest
    assert manifest["flags"]["question"] is True
    assert "code_ref" in manifest


def test_reconstruction_verifies_against_fingerprint():
    cap = _Capture()
    out = generate_voice_reply(
        "u1", "mentor", "A quiet word about kestrels", [], generate_fn=cap
    )
    manifest = out.generation_manifest

    def rebuild() -> str:
        lines, _meta = build_voice_prompt(
            "u1", "mentor", "A quiet word about kestrels", []
        )
        return "\n".join(lines)

    result = verify_from_builder(manifest, rebuild)
    assert result["verified"] is True
    assert result["expected_prompt_sha256"] == result["rebuilt_prompt_sha256"]
    # And a tampered rebuild fails, by hash.
    bad = verify_reconstruction(manifest, "not the prompt")
    assert bad["verified"] is False


def test_tier2_assessment_names_open_legs():
    # A pre-P-1 manifest: no references at all — every leg is named.
    bare = {"prompt_sha256": "x", "thread_summary_sha256": "y"}
    legs = assess_tier2(bare)
    leg_names = {l["leg"] for l in legs}
    assert "character_state_id" in leg_names
    assert "thread_summary" in leg_names
    # An N1-era manifest: full references + preserved summary.
    full = {
        "prompt_sha256": "x",
        "thread_summary_sha256": "y",
        "refs": {
            "character_state_id": "cs-1",
            "code_ref": "img",
            "capability_slice_id": "mentor",
            "visitor_state_refs": [],
            "service_blocks": {"present": [], "record_ids": {}},
            "history_message_ids": ["m1"],
        },
    }
    preserved = {"components": {"thread_summary": "the summary"}}
    assert assess_tier2(full, preserved_components=preserved) == []


# -- Talk-path wiring ---------------------------------------------------------------


def _talk(tmp_path, monkeypatch, *, flag: bool):
    if flag:
        monkeypatch.setenv("ZENAF_NATIVE_DEVELOPMENT", "1")
    else:
        monkeypatch.delenv("ZENAF_NATIVE_DEVELOPMENT", raising=False)
    monkeypatch.setenv("ZENAF_DEV_DB_PATH", str(tmp_path / "dev.db"))
    cap = _Capture()
    store = ConversationStore(db_path=tmp_path / "conv.db")
    svc = ConversationService(store, generate_fn=cap)
    return svc, store, cap


def _seed_author_material(tmp_path):
    store = DevelopmentStore(db_path=tmp_path / "dev.db")
    store.register_authorship(CHAR, AUTHOR)
    svc = DevelopmentService(store)
    out = svc.record_correction(
        author_id=AUTHOR,
        character_id=CHAR,
        verbatim="Seed the carriage.",
        ops=[{"op": "add", "body": "Holds mornings sacred."}],
    )
    store.close()
    return out


def test_talk_turn_carries_and_preserves_for_author(tmp_path, monkeypatch):
    seeded = _seed_author_material(tmp_path)
    svc, store, cap = _talk(tmp_path, monkeypatch, flag=True)
    result = svc.turn(AUTHOR, CHAR, "Good morning")
    prompt = cap.prompts[0]
    assert "Holds mornings sacred." in prompt
    assert "revisable standing" in prompt
    hist = store.history(AUTHOR, "skeleton")
    assistant = [m for m in hist if m["role"] == "voice"][-1]
    manifest = assistant["context"]["generation_manifest"]
    refs = manifest["refs"]
    assert refs["character_state_id"] == seeded["verdict"]["after_state_id"]
    assert refs["capability_slice_id"] == CHAR
    # A second turn's manifest names the history window's message ids.
    svc.turn(AUTHOR, CHAR, "And in the afternoon?")
    hist = store.history(AUTHOR, "skeleton")
    assistant2 = [m for m in hist if m["role"] == "voice"][-1]
    refs2 = assistant2["context"]["generation_manifest"]["refs"]
    assert refs2["history_message_ids"]
    assert "Holds mornings sacred." in cap.prompts[1]
    # Tier-1 preservation, keyed to the assistant message + manifest.
    dev_store = DevelopmentStore(db_path=tmp_path / "dev.db")
    preserved = dev_store.preserved_for_message(assistant["id"])
    assert preserved is not None
    assert preserved["manifest_prompt_sha256"] == manifest["prompt_sha256"]
    dev_store.close()
    store.close()
    assert result.reply.reply == "Fake reply."


def test_talk_turn_visitor_gets_no_carriage_or_preservation(tmp_path, monkeypatch):
    _seed_author_material(tmp_path)
    svc, store, cap = _talk(tmp_path, monkeypatch, flag=True)
    svc.turn("visitor-9", CHAR, "Good morning")
    assert "Holds mornings sacred." not in cap.prompts[0]
    hist = store.history("visitor-9", "skeleton")
    assistant = [m for m in hist if m["role"] == "voice"][-1]
    dev_store = DevelopmentStore(db_path=tmp_path / "dev.db")
    assert dev_store.preserved_for_message(assistant["id"]) is None
    dev_store.close()
    store.close()


def test_talk_turn_flag_off_is_inert(tmp_path, monkeypatch):
    _seed_author_material(tmp_path)
    svc, store, cap = _talk(tmp_path, monkeypatch, flag=False)
    assert native_development_enabled() is False
    svc.turn(AUTHOR, CHAR, "Good morning")
    assert "Holds mornings sacred." not in cap.prompts[0]
    hist = store.history(AUTHOR, "skeleton")
    assistant = [m for m in hist if m["role"] == "voice"][-1]
    dev_store = DevelopmentStore(db_path=tmp_path / "dev.db")
    assert dev_store.preserved_for_message(assistant["id"]) is None
    dev_store.close()
    store.close()


def test_summary_history_leg(tmp_path):
    store = DevelopmentStore(db_path=tmp_path / "dev.db")
    store.preserve_summary(
        user_id=AUTHOR, conversation_id="c1", archetype_id=CHAR,
        summary="first summary state",
    )
    store.preserve_summary(
        user_id=AUTHOR, conversation_id="c1", archetype_id=CHAR,
        summary="second summary state",
    )
    history = store.summary_history(AUTHOR, "c1", CHAR)
    assert [h["summary"] for h in history] == [
        "first summary state",
        "second summary state",
    ]
    store.close()
