"""Skeptic (Raven) first meeting — keystone 1, written but NOT available.

Scope of this PR (approved 2026-10-28, revised parallel scope +
corrections): the Skeptic's first-meeting script + authored
definition, prompt-local reference slice, and the proof that the
meeting cannot begin. What this file pins:

- Script data: Raven's introduction (four bubbles, verbatim, name
  withheld until the reveal), no question bank, one reveal
  following the existing ceremony (name + demeanor + invitation;
  no motto, no flaw, nobody else introduced).
- Identity verified against the code, not re-asserted: role
  Skeptic / character Raven (archetypes.py, keystones.py seed
  data), ideal / question / shadow (ARCHETYPE_PHILOSOPHY), and
  jurisdiction focus (SEAT_JURISDICTIONS).
- Frames: every integrity invariant carried (naming / reveal
  timing, direct-answer-first, grounding, no invented training,
  recognition, parser contract); choreography cleaned in the
  Weaver P1 pattern (permission + judgment-based yielding, never
  a prescribed yield procedure; no-checklist as a principle;
  read-back unmandated except the delimiter + Strands line).
- Reference slice: the orientation draft's delimited slice
  (PR #254, draft only) embedded prompt-locally, verbatim, on
  both live frames — in the Weaver #252 guidance-constant pattern.
  It migrates to the uncapped section after PR #255 merges.
- Availability: the script is deliberately NOT in SCRIPTS, so
  get_script is None, state reports has_script False, and begin
  refuses — even for a seeded user whose Weaver keystone 1 is
  Done. Registering the script is the availability flip, proven
  by the monkeypatched control (reverted after the test).
- Budget: both composed runtime frames fit the voice builder's
  8000-char extra_instructions cap with at least 300 chars
  headroom on the engage path at the none-met baseline (the same
  basis as Weaver's 7613), and fit the 12500 fallback cap with
  room to spare — so no frame is silently truncated and the
  honesty guard (last line of the capability block) survives.

No steward record exists for this seat and none is required:
the definition builds from the script object directly. No live
runs, no model spending: every test here is headless. The
behavioral specs (no-tension visitor, all-six introductions,
visitor closure incl. the loop case, ten-turn continuity,
volunteer initiative, yielding, no mechanical inquisitiveness,
counterfactual difference) live in
docs/skeptic-first-meeting-behavioral-specs.md, for a later
separately authorized live run.
"""

from __future__ import annotations

import dataclasses
import threading

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import (
    MeetingError,
    MeetingService,
    MeetingStore,
)
from local_ai.conversation.store import ConversationStore
from local_ai.council import archetypes as ARCH
from local_ai.council import capabilities as CAP
from local_ai.council import jurisdictions as JX
from local_ai.council import keystones as KD
from local_ai.council import meetings as MT
from local_ai.council import steward_records as SR
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import service as ve


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
    )


def _seeded_user(email="skeptic-meet@example.com"):
    user = ve.create_user_account(email, "pw", "Meet")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _definition():
    return ENC.get_definition(MT.SKEPTIC_FIRST_MEETING)


def _runtime_engage(definition):
    """The engage frame exactly as the runtime hands it to generation:
    definition engage + Zenaf note + naming note + capability block."""
    frame = definition.engage_frame
    frame += "\n\n" + ENC._ZENAF_QUESTION_NOTE
    frame += "\n\n" + ENC._naming_note(definition)
    if definition.capability_context:
        frame += "\n\n" + definition.capability_context
    return frame


# ---------------------------------------------------------------------------
# Script data: introduction, bank, reveal, ceremony.
# ---------------------------------------------------------------------------


def test_script_identity_and_opening():
    script = MT.SKEPTIC_FIRST_MEETING
    assert script.archetype_id == "skeptic"
    assert script.keystone_index == 1
    assert script.character == "Raven"
    assert script.opening == MT.SKEPTIC_INTRODUCTION
    assert len(script.opening) == 4
    # His habit, owned plainly — the payoff of the Weaver's locked
    # skeptic allusion ("Someone leaves question marks in my
    # margins. Never answers. Just the marks.").
    assert "question marks in the margins" in " ".join(script.opening)
    assert "Never answers. Just the marks." in " ".join(script.opening)
    # Reveal timing: the name is withheld from the opening.
    assert "Raven" not in " ".join(script.opening)
    # Defining question + invitation: visitor material is the subject.
    assert "what are we assuming?" in " ".join(script.opening).lower()
    # No question bank by design (Weaver shape): examination of
    # visitor material, not an interrogation to work through.
    assert script.questions == ()


def test_reveal_follows_existing_ceremony():
    script = MT.SKEPTIC_FIRST_MEETING
    assert len(script.reveal) == 3
    joined = " ".join(script.reveal)
    # Canonical name + demeanor, then an invitation — not a
    # completion declaration.
    assert "I'm the Raven." in joined
    assert "what a belief rests on" in joined
    assert script.reveal[-1].startswith("Come back when")
    assert "complete" not in joined.lower()
    # No motto, no flaw, nobody else introduced.
    for other in ("Gardener", "Firebrand", "Bear", "Crane", "Fox", "Weaver"):
        assert other not in joined
    # Demeanor is the seed data's, verbatim (keystones.py).
    seed = next(s for s in KD.SEATS if s["seat_ref"] == "skeptic")
    assert script.demeanor == seed["demeanor"]
    assert script.demeanor == (
        "Flint-eyed, unimpressed by performance; "
        "asks the question no one wants."
    )


def test_identity_verified_against_code():
    phil = ARCH.ARCHETYPE_PHILOSOPHY["skeptic"]
    assert phil["ideal"].startswith("Truth through examination")
    assert phil["question"] == "What are we assuming?"
    assert "Paralysis and cynicism" in phil["shadow"]
    jur = JX.SEAT_JURISDICTIONS["skeptic"]
    assert "what the user's beliefs actually rest on" in jur.focus
    assert "Dry, exact, citation-minded" in jur.register.diction
    assert ARCH.WARMTH_REGISTERS["skeptic"].startswith(
        "Your warmth register: none."
    )
    # The runtime's naming table agrees: role skeptic -> Raven.
    assert ENC._SEAT_CHARACTER_NAMES["skeptic"] == "Raven"


# ---------------------------------------------------------------------------
# Definition assembly: authored builder, gate, no steward, no spill.
# ---------------------------------------------------------------------------


def test_definition_assembles_from_script():
    definition = _definition()
    assert definition.archetype_id == "skeptic"
    assert definition.keystone_index == 1
    assert definition.character == "Raven"
    assert definition.opening == MT.SKEPTIC_INTRODUCTION
    assert definition.question_bank == ()
    # Objectives reuse runtime-known ids only (check_objectives
    # would never satisfy a new id, so a new gate id would brick
    # the impression permanently).
    assert [o.id for o in definition.objectives] == [
        "engaged_exchange",
        "shared_work_exchange",
        "impression_offered",
        "impression_answered",
    ]
    # Impression gate: the shared-work exchange, Skeptic description.
    assert definition.impression_gate_objective == "shared_work_exchange"
    # Generic close shape: no close floor added by this PR.
    assert definition.close_floor_objectives == ()
    assert definition.reveal == MT.SKEPTIC_FIRST_MEETING.reveal
    assert definition.wrap_line == ENC._SKEPTIC_WRAP_LINE
    assert definition.fallback_line == ENC._SKEPTIC_FALLBACK_LINE
    # The retired pause is Conductor-only: no pause paragraphs, so
    # the allusion pool is empty by design (fellowship knowledge
    # rides in the guidance slice, not proximity cues).
    assert definition.pause_body == ()
    assert definition.allusion_pool == ()
    assert definition.orientation_frame
    assert definition.orientation_facts
    # Capability context is the registry's Skeptic slice.
    assert "Review queue" in definition.capability_context


def test_no_steward_record_for_this_seat():
    # Steward consolidation was Weaver-only; this seat consults no
    # steward source and needs none to function.
    assert not [n for n in dir(SR) if n.startswith("SKEPTIC")]
    definition = _definition()
    again = ENC.build_skeptic_k1_definition(MT.SKEPTIC_FIRST_MEETING)
    assert definition == again


def test_skeptic_guidance_on_no_other_seat():
    weaver = ENC.get_definition(MT.get_script("conductor", 1))
    generic = ENC.build_definition(MT.get_script("conductor", 1))
    for text in (weaver.turn_frame, weaver.engage_frame,
                 generic.turn_frame, generic.engage_frame):
        assert "Skeptic first-meeting guidance" not in text
        assert "not every workaround smooths a falsehood" not in text


# ---------------------------------------------------------------------------
# Frames: invariants verbatim, choreography cleaned (P1 pattern).
# ---------------------------------------------------------------------------


def test_reveal_timing_in_every_frame():
    script = MT.SKEPTIC_FIRST_MEETING
    for name, frame in (
        ("encounter", script.encounter_frame),
        ("readback", script.readback_frame),
        ("correction", script.correction_frame),
        ("reply", script.readback_reply_frame),
    ):
        assert "Do not reveal your name yet" in frame, name


def test_readback_invariants_and_parser_contract():
    script = MT.SKEPTIC_FIRST_MEETING
    readback = script.readback_frame
    # Grounding: substantive material only, never courtesies.
    assert "ONLY in their substantive material" in readback
    assert "Never ground it in the courtesies of the meeting" in readback
    # Evidence/expression separation.
    assert (
        "never let their first-person words come out of your mouth "
        "as your own statement" in readback
    )
    # Position, not summary; separation is the read.
    assert "take a POSITION" in readback
    assert "what they said from what they concluded" in readback
    # No invented training.
    assert (
        "Nothing from this meeting trains anything until it goes "
        "through review like everything else" in readback
    )
    # Parser contract: delimiter (via the engage glue) + Strands line.
    definition = _definition()
    assert "containing only ---" in definition.engage_frame
    assert "Strands: <names>" in readback
    assert "Strands: <names>" in script.correction_frame
    # The contract actually splits: reply movement / impression
    # movement on ---, Strands trailer off the impression.
    runtime = ENC.EncounterRuntime(definition)
    reply, impression, had_delim = runtime._split_reply_and_impression(
        "A direct answer.\n---\nA first impression.\nStrands: Logic, Compass"
    )
    assert had_delim and reply == "A direct answer."
    claim, strands = ENC.split_strands_trailer(impression)
    assert claim == "A first impression."
    assert strands == ["Logic", "Compass"]


def test_readback_unmandated_but_strands_kept():
    # P1: contrast, doubt-point, and sentence count are available
    # shapes, not mandatory moves — but the delimiter + Strands
    # line stay, so parser detection survives.
    readback = MT.SKEPTIC_FIRST_MEETING.readback_frame
    assert "where it still applies" in readback  # contrast, conditional
    assert "Keep it brief." in readback  # no "three to five sentences"
    assert "Three to five sentences" not in readback
    assert "Strands: <names>" in readback


def test_recognition_note_in_reply_frame():
    reply = MT.SKEPTIC_FIRST_MEETING.readback_reply_frame
    assert "completes the recognition in itself" in reply
    assert "do not soften a rejection into assent" in reply
    assert "do not reframe their words more flatteringly" in reply
    # The runtime's own recognition note (appended on the
    # recognition paths) says the same, independently.
    assert "completes the recognition in itself" in ENC._RECOGNITION_NOTE


def test_permission_and_judgment_yielding_not_procedure():
    script = MT.SKEPTIC_FIRST_MEETING
    definition = _definition()
    for name, text in (
        ("turn", definition.turn_frame),
        ("encounter", script.encounter_frame),
    ):
        assert "you may volunteer" in text.lower(), name
        assert "by judgment, never by a prescribed procedure" in text, name
        # No prescribed yield procedure anywhere in the frames.
        assert "follow these steps" not in text.lower(), name
        assert "step 1" not in text.lower(), name
    # The old blanket no-restatement ban is gone (anti-presumption
    # governs substance; no-double-read governs structure).
    assert (
        "Do NOT restate, summarize, or interpret their answer back"
        not in script.encounter_frame
    )
    assert "Do not say your read twice" in script.encounter_frame


def test_no_checklist_principle_and_direct_answer():
    definition = _definition()
    for name, text in (
        ("turn", definition.turn_frame),
        ("engage", definition.engage_frame),
    ):
        assert "Don't reduce your friends to a feature checklist" in text, name
        assert (
            "Answer a direct question first, in plain words, before "
            "any interpretation of it" in text
        ), name
        assert "no mandatory sequence, no checklist" in text, name


def test_no_mechanical_inquisitiveness():
    script = MT.SKEPTIC_FIRST_MEETING
    assert "no question-bank, no mechanical inquisitiveness" in (
        script.encounter_frame
    )
    assert "A question is a tool, never a rhythm" in script.encounter_frame


# ---------------------------------------------------------------------------
# Reference slice, prompt-local, verbatim, on both live frames.
# ---------------------------------------------------------------------------


def test_slice_present_verbatim_on_both_frames():
    definition = _definition()
    # The orientation draft's delimited slice, word for word
    # (line wraps joined): card line, six own-side pair lines,
    # agency lines.
    slice_phrases = (
        "Raven (Skeptic) — Truth through examination.",
        "Asks: What are we assuming?",
        "Shadow: paralysis and cynicism.",
        "a meaning yielded is not automatically sunk-cost storytelling. (Pair 6.)",
        "certainty is not the claim, evidence and suspicion are the question. (Pair 11.)",
        "I challenge the premise and yield the stewardship decision. (Pair 15.)",
        "ask rung by rung which is actually broken, not whether the whole reframe grades out. (Pair 18.)",
        "a held truth is not automatically an unexamined one. (Pair 20.)",
        "not every workaround smooths a falsehood. (Pair 21.)",
        "pursue the unasked question and the anchor of a belief",
        "answer direct questions directly, naming the assumption and what would change my mind.",
    )
    for name, text in (
        ("turn", definition.turn_frame),
        ("engage", definition.engage_frame),
    ):
        for phrase in slice_phrases:
            assert phrase in text, (name, phrase)


def test_guidance_restraints_and_proposed_slice():
    definition = _definition()
    for name, text in (
        ("turn", definition.turn_frame),
        ("engage", definition.engage_frame),
    ):
        # Opportunity wording, not a mandatory sequence.
        assert (
            "this meeting gives the visitor an opportunity to "
            "encounter your distinctive personality" in text
        ), name
        # No gates, no counting, no manufacture.
        assert "No orientation question, no mode, no counting probes" in text, name
        assert "Never manufacture a problem or press for a tension" in text, name
        assert "simply enjoy meeting someone new" in text, name
        # Relationship-led introduction, emergent never a tour, by role.
        assert "admiration and friction together, emergent, never a tour" in text, name
        assert "Refer to seats not yet met by role" in text, name
        assert "names come only after meeting" in text, name
        # Framework, not classification.
        assert "as an available framework, never a classification" in text, name
        assert "no pair assignment is required" in text, name
        assert "The 21 relationships are analogies, not diagnoses" in text, name
        # Layer A honesty floor.
        assert "outside the ten-turn window, say you don't remember" in text, name
        # Capability honesty.
        assert "planned means planned, never available" in text, name
        assert "never described as verified" in text, name
        # System slice: PROPOSED throughout, never decided.
        assert "Your system slice, PROPOSED" in text, name
        assert "not decided, never present it as decided" in text, name
        assert (
            "what a belief rests on — anchors versus inheritance, "
            "assumptions, and the question nobody in the room is asking"
            in text
        ), name


def test_runtime_composition_carries_standing_notes():
    definition = _definition()
    runtime = ENC.EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(ENC.EncounterState(), "Hello.")
    # No registry ground line rides the frame anymore: #262's
    # Conductor refinement dropped the appended focus line as a
    # duplication (focus rides the identity block for migrated
    # seats). The Skeptic is unmigrated, so its frame currently
    # carries no registry ground line — restore-or-migrate is a
    # follow-up decision, not settled here.
    assert "Your ground — what naturally draws your attention" not in turn_frame
    assert "what the user's beliefs actually rest on" not in turn_frame
    # Standing Zenaf note + naming note ride every turn frame.
    assert ENC._ZENAF_QUESTION_NOTE in turn_frame
    assert "Other seats: roles until met. None met yet." in turn_frame
    # Capability block rides too (registry Skeptic slice).
    assert "Review queue" in turn_frame
    # Thread-trailer instruction rides the recognition paths
    # (runtime-appended constant, not frame text).
    assert "[[thread:open]]" in ENC._THREAD_TRAILER_INSTRUCTION
    assert "[[thread:settled]]" in ENC._THREAD_TRAILER_INSTRUCTION


# ---------------------------------------------------------------------------
# Budget: both composed frames fit the voice builder's 8000 cap.
# ---------------------------------------------------------------------------


def test_composed_frames_fit_the_voice_builder_cap():
    definition = _definition()
    runtime = ENC.EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(ENC.EncounterState(), "Hello.")
    assert len(turn_frame) < 8000
    engage = _runtime_engage(definition)
    # Proposal gate: at least 300 chars headroom, and the honesty
    # guard — last line of the capability block — is never the
    # first content lost (it survives at the tail of the frame).
    assert len(engage) <= 7700, len(engage)
    assert len(engage) < 8000
    assert engage.rstrip().endswith(CAP.HONESTY_GUARD.strip())
    assert "Your system slice, PROPOSED" in engage
    # And the 12500 fallback cap, with room to spare.
    assert len(engage) < 12500
    assert len(turn_frame) < 12500


def test_no_per_generation_duplicates():
    # The appended guidance adds no new occurrence of the
    # reveal-timing rule (Weaver #252 duplicate guard, Skeptic in
    # kind): each script frame carries it exactly once, and the
    # engage definition carries it exactly twice — once per
    # movement the single generation contains (encounter reply,
    # read-back), not twice within either movement.
    script = MT.SKEPTIC_FIRST_MEETING
    for frame in (
        script.encounter_frame,
        script.readback_frame,
        script.correction_frame,
        script.readback_reply_frame,
    ):
        assert frame.lower().count("do not reveal your name yet") == 1
    assert "do not reveal your name yet" not in (
        ENC._SKEPTIC_REFERENCE_GUIDANCE.lower()
    )
    definition = _definition()
    assert definition.turn_frame.lower().count(
        "do not reveal your name yet") == 1
    assert definition.engage_frame.lower().count(
        "do not reveal your name yet") == 2


# ---------------------------------------------------------------------------
# Availability: written but NOT visitor-accessible (the gate test).
# ---------------------------------------------------------------------------


def test_script_deliberately_unregistered():
    assert MT.get_script("skeptic", 1) is None
    assert MT.has_script("skeptic", 1) is False
    assert ("skeptic", 1) not in MT.SCRIPTS
    # The script object itself exists and assembles — the data is
    # written; only the registry entry is withheld.
    assert MT.SKEPTIC_FIRST_MEETING is not None
    assert ENC.get_definition(MT.SKEPTIC_FIRST_MEETING) is not None


def test_meeting_not_beginnable_even_after_weaver_done(ve_ctx, tmp_path, monkeypatch):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    # The begin guard checks the script BEFORE the entry gate, so a
    # seeded user gets the honest not-written refusal whether or
    # not the Weaver's keystone 1 is Done.
    with pytest.raises(MeetingError, match="isn't written yet"):
        svc.start(uid, "skeptic")
    # Mark the Weaver's keystone 1 Done: the entry gate now passes,
    # the chain task exists — and the ONLY remaining block is the
    # withheld registration. Begin still refuses, honestly.
    from local_ai.conversation.meeting import _seat_keystone_tasks

    conductor_tasks = _seat_keystone_tasks(uid, "conductor")
    assert conductor_tasks and conductor_tasks[0]["status"] != "Done"
    ve.update_task(
        conductor_tasks[0]["id"],
        ve_models.TaskUpdate(status="Done"),
        uid,
    )
    assert _seat_keystone_tasks(uid, "conductor")[0]["status"] == "Done"
    # A Skeptic keystone task was seeded (so the chain check passes).
    assert _seat_keystone_tasks(uid, "skeptic")
    with pytest.raises(MeetingError, match="isn't written yet"):
        svc.start(uid, "skeptic")
    state = svc.state(uid, "skeptic")
    assert state["has_script"] is False
    assert state["character"] is None
    # Control: registering the script is exactly the availability
    # flip — with it registered, the begin guard returns the script
    # (monkeypatch reverts the registration after this test).
    monkeypatch.setitem(MT.SCRIPTS, ("skeptic", 1), MT.SKEPTIC_FIRST_MEETING)
    script = svc._check_beginnable(uid, "skeptic", 1)
    assert script is MT.SKEPTIC_FIRST_MEETING
