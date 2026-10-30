"""Maverick (Fox) first meeting — keystone 1 (Fellowship
conversational-agency build, 2026-10-28).

What this pins, on origin/main only (no PR #254/#255 code):

- The script exists in meetings.py (the rollback source) with the
  verified identity: archetype "maverick", role Maverick, character
  Fox, and the canonical demeanor from keystones.py — never a
  rename. Opening: four verbatim bubbles ending in his open
  question; no name announced early; no question bank (retired
  by design, as the Weaver's was). Reveal: the existing ceremony
  structure only — canonical name, face, one-line demeanor, and
  nothing else (no motto, no flaw, nobody else introduced),
  closing with an invitation, not a completion declaration.
- The frames assemble through the generic definition plus the
  prompt-local guidance constant (the Weaver #252 pattern): the
  script's frames become the definition's frames, the guidance
  rides both live generation paths (turn and engage), and to no
  other seat.
- Integrity invariants: naming (roles until met), direct-answer-
  first, honesty guard + honesty floor, grounding, reveal timing,
  no invented training, recognition note, and the parser contract
  (the --- delimiter + the Strands bookkeeping line) — the last
  two as the runtime appends/carries them, since the frames
  themselves must not duplicate runtime machinery.
- The reference slice: the Fox's prompt-local slice from the
  orientation draft (PR #254, DRAFT ONLY) is present verbatim in
  content on both frames, marked DRAFT, with the system slice
  marked PROPOSED — never decided. The slice is the last thing
  cut: these tests fail if it is trimmed.
- Availability: the meeting is WRITTEN but NOT visitor-accessible.
  The begin gate refuses it even for a fully eligible user
  (seeded council, Weaver keystone 1 Done) — the exact user for
  whom script existence alone would otherwise make it begin-able.
  Removing the gate entry is the whole release mechanism.
- Frame budget: both composed runtime paths fit the voice
  builder's 8000-character extra-instructions cap, so no frame is
  silently truncated and the honesty guard (last in the capability
  block) is never the content lost. Sizes are asserted as bounds;
  the measured numbers go in the PR description.

No live generation runs here: every assertion is on data, frames,
and the begin gate. The behavioral specs (no-tension visitor,
all-six introductions, closure phrasings, ten-turn continuity,
initiative, yielding, inquisitiveness, counterfactual difference)
live in docs/fellowship-maverick-first-meeting-behavioral-specs.md
and need a separate spending authorization.
"""

from __future__ import annotations

import threading

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import (
    _UNRELEASED_MEETINGS,
    MeetingError,
    MeetingService,
    MeetingStore,
    _seat_keystone_tasks,
)
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT
from local_ai.council.capabilities import HONESTY_GUARD
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


def _maverick_script():
    script = MT.get_script("maverick", 1)
    assert script is not None
    return script


def _maverick_definition():
    return ENC.get_definition(_maverick_script())


def _seeded_user(email="maverick@example.com"):
    user = ve.create_user_account(email, "pw", "Mav")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
    )


# ---------------------------------------------------------------------------
# Identity, opening, reveal — the script as data.
# ---------------------------------------------------------------------------

def test_script_identity_matches_canonical_records():
    script = _maverick_script()
    assert script is MT.MAVERICK_FIRST_MEETING  # meetings.py is the source
    assert script.archetype_id == "maverick"
    assert script.keystone_index == 1
    assert script.character == "Fox"
    assert ENC._SEAT_CHARACTER_NAMES["maverick"] == "Fox"
    # Canonical demeanor, verbatim from keystones.py seed data.
    assert script.demeanor == "Restless, allergic to locked doors; lightning-quick."


def test_opening_six_bubbles_ends_in_his_question_names_nobody():
    script = _maverick_script()
    assert len(script.opening) == 6
    assert script.opening[-1] == "And if that's the case… how much of what we call knowledge is just a particularly convincing drawing?"
    # Introductions are earned, not announced: no name in the opening.
    assert "Fox" not in " ".join(script.opening)
    assert "Maverick" not in " ".join(script.opening)
    # The adopted opening, from his side, naming nobody: maps, sea
    # monsters, knowledge as a convincing drawing.
    assert "You're not lost, are you?" in script.opening[0]
    # No question bank: the visitor's own material is the subject.
    assert script.questions == ()


def test_reveal_is_the_existing_ceremony_only():
    script = _maverick_script()
    assert len(script.reveal) == 3
    text = " ".join(script.reveal)
    assert "I'm the Fox." in text
    assert "restless around locked doors" in text  # demeanor, first person
    # ONLY name + demeanor unlock: no motto, no flaw, nobody else.
    for other in ("Weaver", "Gardener", "Firebrand", "Bear", "Crane", "Raven"):
        assert other not in text
    assert "flaw" not in text.lower()
    # Closes with an invitation, not a completion declaration.
    assert "come back" in script.reveal[-1]
    assert "complete" not in text.lower()


def test_orientation_context_is_cues_not_a_delivered_block():
    script = _maverick_script()
    # The retired-pause shape: paragraphs ride the allusion pool.
    assert len(script.orientation) == 3
    assert "never made for" in script.orientation[0]
    assert "was a wall, not long ago" in script.orientation[1]
    # No accounting templates: quoting the record back is purged.
    assert script.pulled_item_template == ""
    assert script.pulled_where_template == ""
    definition = _maverick_definition()
    assert [c.seat for c in definition.allusion_pool] == [
        "pause:0", "pause:1", "pause:2",
    ]


# ---------------------------------------------------------------------------
# Frames assemble; guidance rides both live paths, Maverick only.
# ---------------------------------------------------------------------------

def test_definition_assembles_from_script_frames():
    script = _maverick_script()
    definition = _maverick_definition()
    assert definition.archetype_id == "maverick"
    assert definition.character == "Fox"
    assert definition.opening == tuple(script.opening)
    assert definition.question_bank == ()
    assert definition.impression_frame == script.readback_frame
    assert definition.correction_frame == script.correction_frame
    assert definition.impression_reply_frame == script.readback_reply_frame
    assert definition.reveal == tuple(script.reveal)
    assert definition.orientation_frame == script.orientation_frame
    assert definition.orientation_facts == script.orientation_facts
    # Generic objectives: no authored impression gate, no close
    # floor added here (unchanged by decoupling).
    assert definition.impression_gate_objective == ""
    assert definition.close_floor_objectives == ()
    # UPDATED for the six-seat build (2026-10-29): decoupled
    # recognition (F1) and the uncapped Fellowship reference —
    # the old coupled, reference-less contract is gone. Detail
    # pins live in test_maverick_fellowship_reference.py and
    # test_maverick_recognition_moment.py.
    assert definition.decoupled_recognition is True
    assert definition.fellowship_reference != ""


def test_guidance_rides_both_frames_and_no_other_seat():
    definition = _maverick_definition()
    for name, text in (("turn", definition.turn_frame),
                       ("engage", definition.engage_frame)):
        assert "opportunity to encounter your distinctive personality" in text, name
        assert "never as a mandatory introduction sequence" in text, name
        assert "by judgment, never by a prescribed procedure" in text, name
        assert "Don't reduce your friends to a feature checklist" in text, name
        assert "never as a tour" in text, name
        assert "names come only after meeting" in text, name
    # The generic path (and the Weaver's authored path) carry none of it.
    generic_weaver = ENC.build_definition(MT.get_script("conductor", 1))
    assert "opportunity to encounter your distinctive personality" not in generic_weaver.turn_frame
    assert "opportunity to encounter your distinctive personality" not in generic_weaver.engage_frame
    weaver = ENC.get_definition(MT.get_script("conductor", 1))
    assert "An unbuilt replacement is my known debt" not in weaver.turn_frame
    assert "An unbuilt replacement is my known debt" not in weaver.engage_frame


# ---------------------------------------------------------------------------
# Integrity invariants.
# ---------------------------------------------------------------------------

def test_direct_answer_first_and_yielding():
    script = _maverick_script()
    assert "answer what they actually said" in script.encounter_frame
    assert "direct answer first, in plain words" in script.encounter_frame
    assert "before any reframing of it" in script.encounter_frame
    definition = _maverick_definition()
    assert "Answer a direct question first, in plain words" in definition.turn_frame
    assert "Answer a direct question first, in plain words" in definition.engage_frame
    # Permission + judgment yielding, never a prescribed procedure.
    assert "never by a prescribed procedure" in script.encounter_frame
    assert "prescribed yield" not in script.encounter_frame.lower()
    assert "yield procedure" not in script.encounter_frame.lower()


def test_honesty_guard_honesty_floor_and_no_invented_training():
    script = _maverick_script()
    definition = _maverick_definition()
    # The capability block carries the standing honesty guard.
    assert HONESTY_GUARD in definition.capability_context
    assert "Never present a planned capability as available" in definition.capability_context
    # Layer A honesty floor, prompt-local on both paths.
    assert "say you don't remember rather than filling the gap" in script.encounter_frame
    assert "say you don't remember rather than filling the gap" in definition.turn_frame
    # No invented training, on both paths.
    assert "nothing trains until review" in script.encounter_frame
    assert "Nothing here trains anything until review" in definition.turn_frame
    # Planned stays planned in the capability rendering itself.
    assert "planned, not available yet" in definition.capability_context


def test_grounding_and_reveal_timing():
    script = _maverick_script()
    assert "Ground anything you offer ONLY in what they actually brought" in script.encounter_frame
    assert "Ground the impression ONLY in their substantive material" in script.readback_frame
    assert "how someone humors a scene is not evidence" in script.readback_frame
    for frame in (script.encounter_frame, script.readback_frame,
                  script.correction_frame, script.readback_reply_frame):
        assert "Do not reveal your name yet" in frame


def test_recognition_note_and_trailer_are_runtime_carried():
    # The recognition note and thread trailer are appended by the
    # runtime on the impression-response path — the script must not
    # contradict them, and the constants must carry the contract.
    assert "completes the recognition in itself" in ENC._RECOGNITION_NOTE
    assert "[[thread:open]]" in ENC._THREAD_TRAILER_INSTRUCTION
    assert "[[thread:settled]]" in ENC._THREAD_TRAILER_INSTRUCTION
    script = _maverick_script()
    assert "completes the recognition in itself" in script.readback_reply_frame
    assert "Do not reveal your name yet" in script.readback_reply_frame


def test_parser_contract_delimiter_and_strands():
    script = _maverick_script()
    definition = _maverick_definition()
    # The engage glue's --- line is the delimiter the runtime splits on.
    assert "---" in ENC._ENGAGE_GLUE
    assert "place a line containing only ---" in ENC._ENGAGE_GLUE
    # The read-back frame ends with the Strands bookkeeping instruction.
    assert "'Strands: <names>'" in script.readback_frame
    assert "'Strands: <names>'" in script.correction_frame
    assert "Voice, Logic, Eye, Ear, Hands, Heart, Compass" in script.readback_frame
    # And the parser actually detects both, on this seat's definition.
    runtime = ENC.EncounterRuntime(definition)
    reply, impression, had_delim = runtime._split_reply_and_impression(
        "A sideways reply.\n---\nA first impression.\nStrands: Compass, Logic")
    assert had_delim
    assert reply == "A sideways reply."
    claim, strands = ENC.split_strands_trailer(impression)
    assert claim == "A first impression."
    assert strands == ["Compass", "Logic"]
    # A reply-only output (no delimiter, no Strands) degrades honestly.
    _, _, had_delim = runtime._split_reply_and_impression("Just a reply.")
    assert not had_delim


def test_naming_note_is_roles_until_met():
    definition = _maverick_definition()
    assert ENC._naming_note(definition) == "Other seats: roles until met. None met yet."
    runtime = ENC.EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(ENC.EncounterState(), "Hello.")
    assert "Other seats: roles until met. None met yet." in turn_frame


# ---------------------------------------------------------------------------
# Reference slice: verbatim content, DRAFT, system slice PROPOSED.
# ---------------------------------------------------------------------------

_SLICE_LINES = (
    "Fox (Maverick) — Possibility through reframing.",
    "What if the rules are wrong?",
    "he cultivates within the situation; I must not read the slow path as captivity with good press. (Pair 3.)",
    "she breaks for a cause where I break from a frame; a chosen stand is not automatically playing the rigged game. (Pair 8.)",
    "he maintains boundaries until a better one exists; maintenance is not making captivity comfortable. (Pair 12.)",
    "she mediates where I refuse; translation is not conforming, and meeting leaves refusal intact. (Pair 16.)",
    "she arranges where I refuse arrangement; a system can still hold passages that weren't written. (Pair 17.)",
    "he verifies where I reframe; verification is not closing the door, it is how a reframe stands. (Pair 18.)",
    "Agency: pursue unchosen rules and untried routes; offer a reframed question and an exit held open; challenge artificial choices; answer direct questions directly.",
    "An unbuilt replacement is my known debt.",
)


def test_slice_present_verbatim_on_both_frames():
    definition = _maverick_definition()
    for line in _SLICE_LINES:
        assert line in definition.turn_frame, line
        assert line in definition.engage_frame, line


def test_slice_marked_draft_and_system_slice_proposed():
    definition = _maverick_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "DRAFT ONLY" in text
        assert "canonical text awaits a separate verdict" in text
        assert "System slice (PROPOSED, not decided" in text
        assert "unchosen rules and untried routes" in text
        # Never presented as decided.
        assert "System slice (PROPOSED, not decided" in text
    # The proposed slice is not smuggled into the script as decided fact.
    assert "PROPOSED" not in _maverick_script().orientation_facts


# ---------------------------------------------------------------------------
# Availability: written, but the begin gate refuses it.
# ---------------------------------------------------------------------------

def test_maverick_released_not_in_unreleased_set():
    assert ("maverick", 1) not in _UNRELEASED_MEETINGS
    assert ("conductor", 1) not in _UNRELEASED_MEETINGS
    assert "maverick" in MT.RELEASED_FIRST_MEETING_SEATS


def test_begin_succeeds_for_a_fully_eligible_user(ve_ctx, tmp_path):
    """The exact user for whom script existence alone would have
    made the meeting begin-able before the release: seeded council,
    Weaver keystone 1 Done, and the Maverick's own keystone chain
    present. After the all-six release (2026-10-29) the begin
    succeeds; the entry-seat rule still refuses before Weaver is
    done."""
    uid = _seeded_user()
    conductor_k1 = _seat_keystone_tasks(uid, "conductor")[0]
    ve.update_task(conductor_k1["id"], ve_models.TaskUpdate(status="Done"), uid)
    assert _seat_keystone_tasks(uid, "maverick"), "maverick chain must exist"
    assert MT.get_script("maverick", 1) is not None, "script is written"
    svc = _svc(tmp_path)
    state = svc.start(uid, "maverick")
    assert state["status"] == "active"
    # And the entry-seat rule still refuses before Weaver is done.
    uid2 = _seeded_user("maverick2@example.com")
    with pytest.raises(MeetingError, match="Weaver opens the council"):
        svc.start(uid2, "maverick")
    # The Conductor's meeting is untouched by the release.
    state = svc.start(uid2, "conductor")
    assert state["status"] == "active"


def test_no_row_without_start_turn_still_refuses(ve_ctx, tmp_path):
    """Turn/complete/restart all refuse without an active/completed
    row, and only start creates one — so even now that the Maverick
    is released, an unstarted meeting still has no path past the
    front door."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    with pytest.raises(MeetingError, match="No meeting is in progress"):
        svc.turn(uid, "maverick", "Hello.")
    assert svc.meetings.get(uid, "maverick", 1) is None


# ---------------------------------------------------------------------------
# Frame budget: measured, both composed paths under the 8000 cap.
# ---------------------------------------------------------------------------

def test_composed_frames_fit_the_voice_builder_cap():
    definition = _maverick_definition()
    runtime = ENC.EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(ENC.EncounterState(), "Hello.")
    assert len(turn_frame) < 8000
    engage_frame = definition.engage_frame
    engage_frame += "\n\n" + ENC._ZENAF_QUESTION_NOTE
    engage_frame += "\n\n" + ENC._naming_note(definition)
    if definition.capability_context:
        engage_frame += "\n\n" + definition.capability_context
    assert len(engage_frame) < 8000
    # The honesty guard sits last in the capability block: under the
    # cap, nothing is truncated, so it can never be the content lost.
    assert engage_frame.rstrip().endswith(HONESTY_GUARD)
