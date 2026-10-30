"""Mentor (Gardener) first meeting — STAGED, not visitor-accessible.

The script lives in local_ai/council/meetings.py (MENTOR_FIRST_MEETING)
and assembles through the authored definition builder in
local_ai/conversation/encounter.py (build_mentor_k1_definition, the
Weaver #252 prompt-local pattern: the reference slice appended to the
turn and engage frames at build time). It is deliberately NOT
registered in meetings.SCRIPTS — registration is the availability
switch, and this round ships no gate change — so the meeting service
refuses the Mentor exactly as for an unwritten seat. These tests pin
that conjunction: the script exists AND the meeting cannot begin.

Frame sizes measured here (2026-10-28, this branch):
- reference slice: 2,259 chars (draft slice block 1,088 + framing /
  governing-aim paragraph)
- definition turn frame: 4,011; composed runtime turn frame: 5,587
  (headroom 2,413 against the 8,000 extra_instructions cap)
- definition engage frame: 6,371; composed engage frame: 7,647
  (headroom 353 against the 8,000 cap — above the 300 minimum, and
  comparable to the Weaver's 7,613 / 387; headroom 4,853 against the
  proposal's 12,500 fallback cap)
The composed engage frame is what _generate_framed passes as
extra_instructions, so it — not the bare definition frame — is the
binding measurement: at 7,647 nothing truncates, and the honesty
guard (last line of the capability block, last in the composition)
is never the first content lost. PR #255 merged the uncapped
fellowship_reference section, and the six-seat references build
(2026-10-29) puts the Gardener's full relational sketches there —
adapted from the corrected comparison doc §4, plus the shared
doctrine constant, plus a build-time-computed availability note —
while the compressed slice STAYS prompt-local on the capped frames
(Weaver pattern: slice and reference coexist). The capped frame
sizes above are therefore unchanged by that build. Recognition is
decoupled (F1): a settled verdict never closes; completion is
visitor-controlled (see test_mentor_recognition_moment).

No steward wiring: the Mentor builder reads meetings.py only (no
steward record source, no S1 wiring). No live runs, no model calls:
every assertion here is over data and frame strings.
"""

from __future__ import annotations

import threading

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import (
    MeetingError,
    MeetingService,
    MeetingStore,
)
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (test_meetings pattern)."""
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
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
    )


def _seeded_user(email="mentor-staged@example.com"):
    user = ve.create_user_account(email, "pw", "Mentor")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _definition():
    return ENC.get_definition(MT.MENTOR_FIRST_MEETING)


def _composed_engage(definition):
    frame = definition.engage_frame
    frame += "\n\n" + ENC._ZENAF_QUESTION_NOTE
    frame += "\n\n" + ENC._naming_note(definition)
    if definition.capability_context:
        frame += "\n\n" + definition.capability_context
    return frame


# ---------------------------------------------------------------------------
# The script itself: Gardener's voice, Weaver template shape.
# ---------------------------------------------------------------------------


def test_script_identity_and_shape():
    script = MT.MENTOR_FIRST_MEETING
    assert script.archetype_id == "mentor"
    assert script.keystone_index == 1
    assert script.character == "Gardener"
    # Demeanor matches the keystone seed data for the Mentor.
    assert script.demeanor == "Patient, unhurried; sees seasons, not days."
    # Scripted opening: six bubbles, delivered verbatim, and he waits.
    assert len(script.opening) == 6
    assert script.opening[0].startswith("Ah, there you are! Come, come.")
    assert script.opening[-1].endswith("Perhaps not everything we cultivate is meant to bloom.")
    # Reveal timing: no name spoken before the reveal.
    assert "Gardener" not in " ".join(script.opening)
    assert "Gardener" not in script.encounter_frame
    # The question bank is retired by design (Weaver pattern): the
    # visitor's own material is the subject, not an interrogation.
    assert script.questions == ()
    # ONE reveal, existing ceremony structure: met / name + demeanor /
    # invitation — no variants, no new ceremony types.
    assert len(script.reveal) == 3
    assert script.reveal[1].startswith("I'm the Gardener.")
    assert "seasons, not days" in script.reveal[1]
    assert "gate is never locked" in script.reveal[2]
    # Orientation paragraphs are context, not a delivered block: the
    # first pays off the Weaver's locked mentor allusion from the
    # Gardener's side; no character names (traces, not introductions).
    assert len(script.orientation) == 4
    assert "Things set aside here get tended" in script.orientation[0]
    for name in ("Gardener", "Weaver", "Firebrand", "Bear", "Fox", "Crane", "Raven"):
        assert name not in " ".join(script.orientation), name


def test_definition_assembles_like_weaver():
    definition = _definition()
    assert definition.archetype_id == "mentor"
    assert definition.character == "Gardener"
    assert definition.opening == MT.MENTOR_FIRST_MEETING.opening
    assert definition.question_bank == ()
    # Generic first-meeting objectives: no Weaver-only impression gate
    # or close floor smuggled in as a per-seat default.
    assert [o.id for o in definition.objectives] == [
        "engaged_exchange",
        "impression_offered",
        "impression_answered",
    ]
    assert definition.impression_gate_objective == ""
    assert definition.close_floor_objectives == ()
    # Decoupled recognition (six-seat references build, 2026-10-29):
    # a settled verdict never closes; the recognition moment is a
    # live-generated introduction on impression-answered (see
    # test_mentor_recognition_moment for the gateless verification).
    assert definition.decoupled_recognition is True
    assert definition.fellowship_reference != ""
    # Allusion pool: his four orientation paragraphs as proximity cues.
    assert len(definition.allusion_pool) == 4
    assert definition.wrap_line.startswith("I've kept you long enough")
    assert definition.fallback_line.startswith("Forgive me")


# ---------------------------------------------------------------------------
# Prompt-control cleanup, Mentor's voice (Weaver P1 pattern).
# ---------------------------------------------------------------------------


def test_prompt_control_cleanup():
    definition = _definition()
    turn = definition.turn_frame
    # Permission + judgment-based yielding, never a prescribed procedure.
    assert "You may volunteer a topic from your interests or relationships" in turn
    assert "use judgment about rhythm, never a prescribed procedure" in turn
    assert "prescribed yield" not in turn.lower()
    # No-checklist, as a principle, not a procedure.
    assert "Don't reduce your friends to a feature checklist" in turn
    # Intentions, not a checklist or coverage obligation.
    assert "intentions, not speeches" in turn
    assert "never interrupt a meaningful exchange" in turn
    # Opportunity wording: the slice header states the prohibition as
    # a negation — knowledge available, never a required sequence.
    assert "never a mandatory introduction sequence, checklist, or coverage obligation" in turn
    # Direct-answer-first (C38), verbatim Weaver-v3 sentence.
    assert "Answer a direct question first, in plain words, before any interpretation of it" in turn
    # Ten-turn-window honesty floor, prompt-local (no PR #255 dependency).
    assert "say plainly that you don't remember it rather than inventing it" in turn
    # Shadow named as a prohibition, never performed.
    assert "never withhold a straight answer to stay necessary" in definition.engage_frame
    assert "Never hand over an answer they could arrive at themselves" in definition.engage_frame


# ---------------------------------------------------------------------------
# Integrity invariants, verbatim, on the assembled runtime paths.
# ---------------------------------------------------------------------------


def test_integrity_invariants_on_runtime_paths():
    definition = _definition()
    runtime = ENC.EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(ENC.EncounterState(), "Hello.")
    engage = _composed_engage(definition)
    # Naming: roles until met (runtime note, one line, both paths).
    assert "Other seats: roles until met. None met yet." in turn_frame
    assert "Other seats: roles until met. None met yet." in engage
    # Direct-answer-first about Zenaf (standing note, both paths).
    assert "answer plainly first" in turn_frame
    assert "answer plainly first" in engage
    # Honesty guard (capability block, last line, last in composition).
    assert "Never present a planned capability as available" in turn_frame
    assert "Never present a planned capability as available" in engage
    assert engage.rstrip().endswith(
        "Never present a planned capability as available, a hypothetical "
        "as an action, or a gated capability as immediately usable."
    )
    # Grounding: read-back grounds ONLY in substantive material.
    assert "Ground the impression ONLY in their substantive material" in engage
    assert "Never ground it in the courtesies of the meeting" in engage
    # Reveal timing: no name in the live frames before the reveal.
    assert "Do not reveal your name yet" in turn_frame
    assert turn_frame.count("Do not reveal your name yet") == 1
    assert "Do not reveal your name yet" in engage
    assert engage.count("Do not reveal your name yet") == 1
    # No invented training: an impression is a proposal, never a claim.
    assert "an impression is a proposal, never a filed claim" in engage
    # Recognition note and trailer instruction (runtime constants that
    # ride the recognition / post-recognition generations).
    assert "completes the recognition in itself" in ENC._RECOGNITION_NOTE
    assert "[[thread:open]]" in ENC._THREAD_TRAILER_INSTRUCTION
    assert "[[thread:settled]]" in ENC._THREAD_TRAILER_INSTRUCTION


# ---------------------------------------------------------------------------
# Parser contract: delimiter + Strands line survive, unmandated read-back.
# ---------------------------------------------------------------------------


def test_parser_contract_delimiter_and_strands():
    definition = _definition()
    # The engage glue permits the impression after a --- delimiter line.
    assert "place a line containing only ---" in definition.engage_frame
    # The read-back frame mandates the Strands bookkeeping line exactly.
    assert "in exactly this form: 'Strands: <names>'" in definition.impression_frame
    assert "in exactly this form: 'Strands: <names>'" in definition.correction_frame
    # And the runtime actually splits that shape.
    runtime = ENC.EncounterRuntime(definition)
    reply, impression, had_delim = runtime._split_reply_and_impression(
        "A reply in his own voice.\n---\nA first impression, held at doubt.\nStrands: Heart, Compass"
    )
    assert had_delim is True
    assert reply == "A reply in his own voice."
    claim, strands = ENC.split_strands_trailer(impression)
    assert claim == "A first impression, held at doubt."
    assert strands == ["Heart", "Compass"]
    # Read-back unmandated: contrast and doubt-point are available
    # shapes, sentence count is soft — but delimiter + Strands stay
    # mandatory (asserted above). No hard "three to five sentences".
    assert "Three to five sentences" not in definition.impression_frame
    assert "Keep it to a few sentences" in definition.impression_frame


# ---------------------------------------------------------------------------
# Reference slice: prompt-local, both live frames, generic path clean.
# ---------------------------------------------------------------------------


def test_reference_slice_prompt_local_on_both_frames():
    definition = _definition()
    # Draft slice content, all three dimensions.
    for text in (definition.turn_frame, definition.engage_frame):
        assert "Wisdom through cultivation" in text
        assert "What can this teach us?" in text
        assert "Firebrand: she ends seasons in decisions" in text
        assert "Bear: he keeps the conditions growth needs" in text
        assert "Fox: he tests trellis vs cage" in text
        assert "Crane: she repairs bridges where I mine lessons" in text
        assert "Weaver: she rebalances the whole where I deepen one thread" in text
        assert "Raven: he audits whether growth is real" in text
        assert "answer direct questions directly" in text
        # System slice marked PROPOSED, never decided.
        assert "a PROPOSED mapping, not decided" in text
        assert "growth over time" in text
        # Slice is DRAFT, canonical text awaits Joshua's verdict.
        assert "DRAFT ONLY" in text
    # Weaver #252 pattern: only the authored builder appends it.
    generic = ENC.build_definition(MT.MENTOR_FIRST_MEETING)
    assert "Wisdom through cultivation" not in generic.turn_frame
    assert "Wisdom through cultivation" not in generic.engage_frame


# ---------------------------------------------------------------------------
# Fellowship reference: uncapped sketches + shared doctrine + computed note.
# ---------------------------------------------------------------------------


def test_fellowship_reference_sketches_shared_doctrine_computed_note():
    definition = _definition()
    ref = definition.fellowship_reference
    # All six other seats, in the Gardener's own voice (corrected
    # doc §4, adapted — perspective with friction intact, not the
    # drafting formula).
    for role in ("Firebrand", "Bear", "Fox", "Crane", "Weaver", "Raven"):
        assert role in ref, role
    assert "She thinks I delay. I think she harvests early." in ref
    assert "which walls are shelter and which are starvation" in ref
    assert "I defend the trellis, and he questions it" in ref
    assert "She won't let me get away with that" in ref
    assert "She still disagrees. Good." in ref
    assert "The timing is the argument." in ref
    # Not merely instrumental: mention line + no-invented-memories.
    assert "affection, exasperation, curiosity, admiration" in ref
    assert "Never invent shared memories" in ref
    assert "a playful guess is a guess, not a fact" in ref
    # Shared doctrine, composed from the ONE common constant: naming
    # three ways apart + no-arrangement. No per-seat direct-question
    # paragraph — that precedence is already shared machinery.
    assert "always sayable" in ref
    assert "answer with the role, never with a description alone" in ref
    assert "unlock only when you have met them" in ref
    assert "a third, separate state" in ref
    assert "You cannot arrange meetings with other seats" in ref
    assert "no such action exists" in ref
    assert "never offer to set one up" in ref
    assert "A direct question comes first" not in ref
    assert "An impression never displaces an answer" not in ref
    # NO slice content in the reference: the growth-over-time slice
    # is PROPOSED, never decided (G5), and slices do not appear in
    # references at all.
    assert "growth over time" not in ref
    assert "PROPOSED" not in ref
    # Blind spot never stated, hinted, or scaffolded (LAST REVEAL
    # KEYSTONE): the Revision 2 self-diagnosis wording is absent.
    assert "instrumentalizes" not in ref
    # Availability note, COMPUTED from the gates at build, minus self.
    # All-six release truth: every other seat is open now.
    note = ref.splitlines()[-1]
    assert note.startswith("First-meeting openness right now")
    assert "Firebrand — open now" in note
    assert "Bear — open now" in note
    assert "Fox — open now" in note
    assert "Crane — open now" in note
    assert "Weaver — open now" in note
    assert "Raven — open now" in note
    assert "Gardener —" not in note
    # The new material rides the uncapped section only: capped
    # frames carry neither the sketches nor the note.
    for text in (definition.turn_frame, definition.engage_frame):
        assert "She thinks I delay" not in text
        assert "First-meeting openness right now" not in text
        assert "You cannot arrange meetings" not in text


def test_availability_note_is_computed_not_snapshot(monkeypatch):
    # Releasing the Guardian changes the note with no text edit.
    # The test pins the gate view in-process (including the held
    # set, empty since the all-six release) — its subject is that
    # the note is computed, not the real sets.
    import local_ai.council.meetings as MT_mod

    monkeypatch.setattr(
        MT_mod, "RELEASED_FIRST_MEETING_SEATS",
        frozenset({"conductor", "guardian"}),
    )
    monkeypatch.setattr(
        MT_mod, "HELD_FIRST_MEETINGS",
        frozenset({("champion", 1)}),
    )
    note = ENC._fellowship_availability_note("mentor")
    assert "Bear — open now" in note
    assert "Firebrand — held, not open yet" in note


# ---------------------------------------------------------------------------
# Frame sizes + headroom, measured (not claimed).
# ---------------------------------------------------------------------------


def test_frame_sizes_and_headroom_measured():
    definition = _definition()
    runtime = ENC.EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(
        ENC.EncounterState(), "I have a project I set aside months ago."
    )
    engage = _composed_engage(definition)
    # Binding cap: reply.build_voice_prompt truncates
    # extra_instructions at 8,000 chars. Both composed paths fit with
    # at least 300 chars headroom (proposal minimum).
    assert len(definition.turn_frame) == 4011
    # #262 dropped the appended jurisdiction line from _turn_frame
    # (298 chars + separator = 300), so the composed turn frame is
    # 300 smaller than originally measured; definition frame unchanged.
    assert len(turn_frame) == 5287
    assert len(turn_frame) < 8000
    assert 8000 - len(turn_frame) == 2713
    # #262's P1 rewrites tightened one engage impression instruction
    # (243 chars shorter); re-measured. Headroom grew, still >= 300.
    assert len(definition.engage_frame) == 6128
    assert len(engage) == 7404
    assert len(engage) < 8000
    assert 8000 - len(engage) == 596
    assert 8000 - len(engage) >= 300
    # Proposal fallback cap, for the record: reference + slice together
    # exceed 12,500 (PR #254 warning) — this branch carries the slice
    # only, prompt-locally, and fits both caps; the full reference
    # awaits the uncapped placement after PR #255 merges.
    assert len(engage) < 12500
    assert len(ENC._MENTOR_REFERENCE_SLICE) == 2259


# ---------------------------------------------------------------------------
# BUILDING == AVAILABLE (all-six release): registered, released.
# ---------------------------------------------------------------------------


def test_meeting_visitor_accessible():
    # The script object exists, and the registry — the availability
    # switch — now carries it (all-six release, 2026-10-29).
    assert MT.MENTOR_FIRST_MEETING in MT.SCRIPTS.values()
    assert MT.get_script("mentor", 1) is not None
    assert MT.has_script("mentor", 1) is True


def test_meeting_service_begins_mentor_start(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    # Seeded user without the Weaver's keystone 1 Done: the refusal
    # is the entry order, not a missing registration — the script
    # is registered (all-six release) and the state reports it.
    with pytest.raises(MeetingError, match="Weaver opens the council"):
        svc.start(uid, "mentor")
    state = svc.state(uid, "mentor")
    assert state["has_script"] is True
    assert state["character"] == "Gardener"
    assert state["status"] == "not_started"
    # With the Weaver's keystone 1 Done, the meeting begins.
    from local_ai.conversation.meeting import _seat_keystone_tasks
    from local_ai.vision_execution import models as ve_models

    conductor_tasks = _seat_keystone_tasks(uid, "conductor")
    assert conductor_tasks and conductor_tasks[0]["status"] != "Done"
    ve.update_task(
        conductor_tasks[0]["id"],
        ve_models.TaskUpdate(status="Done"),
        uid,
    )
    assert _seat_keystone_tasks(uid, "conductor")[0]["status"] == "Done"
    state = svc.start(uid, "mentor")
    assert state["status"] == "active"


def test_no_steward_wiring_for_mentor():
    # The authored builder takes the script only; it never consults
    # the steward record source (Weaver consolidation was Weaver-only).
    import inspect

    src = inspect.getsource(ENC.build_mentor_k1_definition)
    assert "steward" not in src
    assert "weaver_steward_active" not in src
