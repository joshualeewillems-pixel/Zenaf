"""Champion (Firebrand) first meeting — keystone 1.

The script is written and framed here, and the meeting is released
(all-six release, 2026-10-29): the HELD hold was lifted, so the
entry gate no longer refuses it. The behavioral specs for a later,
separately authorized live run live in
docs/champion-first-meeting-behavioral-specs.md — nothing here spends
a model call.

What this pins:
- The script exists, in Firebrand's voice, under the approved role /
  character names (Champion / Firebrand), with the existing reveal
  ceremony and no question bank.
- The authored definition assembles over the script (generic
  objectives; the Weaver's gate and floor are not copied), with the
  prompt-local guidance — including the orientation slice, verbatim
  in substance — on both live generation paths, and on no other
  seat's generic definition; it carries the Fellowship reference on
  the uncapped section and is decoupled (settled never closes;
  completion is visitor-controlled).
- Every integrity invariant rides the frames verbatim (naming,
  direct-answer-first, honesty guard, grounding, reveal timing, no
  invented training, recognition note, trailer instruction), and
  the parser contract (--- delimiter / Strands line) stays intact.
- The meeting is NOT visitor-begin-able: the gate test.
- Frame sizes stay under the voice builder's 8,000-char
  extra-instructions cap with at least 300 chars headroom (stored
  frames; the composed engage frame is measured in the PR
  description, where the reference-fit table also lives).
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
    )


def _seeded_user(email="champ@example.com"):
    user = ve.create_user_account(email, "pw", "Champ")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _script():
    return MT.get_script("champion", 1)


def _definition():
    return ENC.get_definition(_script())


# ------------------------------------------------------------------ script


def test_script_exists_with_approved_names():
    script = _script()
    assert script is not None
    assert script.archetype_id == "champion"
    assert script.keystone_index == 1
    assert script.character == "Firebrand"
    # Card demeanor matches the keystone seat data (keystones.py).
    assert script.demeanor == "Urgent, fierce; picks fights worth having."


def test_opening_is_four_bubbles_in_her_voice_without_a_name():
    script = _script()
    assert len(script.opening) == 4
    joined = " ".join(script.opening)
    assert "forge" in joined
    assert "Name the hill. Name the price." in joined
    # Introductions are earned, not announced: no name in the opening.
    assert "Firebrand" not in joined
    # No question bank: the visitor's own material is the subject.
    assert script.questions == ()


def test_reveal_follows_the_existing_ceremony_only():
    script = _script()
    assert len(script.reveal) == 3
    joined = " ".join(script.reveal)
    assert "I'm the Firebrand." in joined
    assert "pick fights worth having" in joined
    # No motto (the signature line stays offstage), no flaw, and
    # nobody else is introduced: no other seat's character name.
    assert "Before you draw your sword" not in joined
    assert "martyrdom" not in joined
    for name in ("Gardener", "Bear", "Fox", "Crane", "Weaver", "Raven"):
        assert name not in joined
    # It closes with an invitation, not a completion declaration.
    assert script.reveal[-1].startswith("Don't wait for the hill")


def test_orientation_honors_the_weaver_furnace_debt():
    script = _script()
    joined = " ".join(script.orientation)
    assert "comes back stronger" in joined
    assert "doesn't come back at all" in joined
    # A registry fixture, not decoration: the worn bench edge.
    assert "worn smooth" in joined


# -------------------------------------------------------------- definition


def test_definition_assembles_over_the_script():
    definition = _definition()
    assert definition.archetype_id == "champion"
    assert definition.character == "Firebrand"
    assert definition.opening == tuple(_script().opening)
    assert definition.question_bank == ()
    # Generic first-meeting objectives: the Weaver's impression gate
    # and close floor are Weaver-authored, not copied here.
    assert [o.id for o in definition.objectives] == [
        "engaged_exchange",
        "impression_offered",
        "impression_answered",
    ]
    assert definition.impression_gate_objective == ""
    assert definition.close_floor_objectives == ()
    # Decoupled like all seven (F1): recognition is a moment, not a
    # close; the Fellowship reference rides the uncapped section.
    assert definition.decoupled_recognition is True
    assert definition.fellowship_reference
    assert "I break for a cause; he breaks from a frame" in (
        definition.fellowship_reference
    )
    assert definition.wrap_line.startswith("I've kept you long enough")
    assert definition.fallback_line.startswith("Forgive me")
    # Her system slice, rendered from the capability registry.
    assert "Projects and tasks" in definition.capability_context


def test_prompt_local_guidance_rides_both_frames_and_no_other_seat():
    definition = _definition()
    for name, text in (
        ("turn", definition.turn_frame),
        ("engage", definition.engage_frame),
    ):
        assert "opportunity to encounter your distinctive personality" in text, name
        assert "Don't reduce your friends to a feature checklist" in text, name
        assert "Yielding is judgment, not a prescribed procedure" in text, name
        assert "Answer a direct question first, in plain words" in text, name
        assert "vision execution" in text, name
    # The generic path over the same script carries no guidance.
    generic = ENC.build_definition(_script())
    assert "Don't reduce your friends to a feature checklist" not in generic.turn_frame
    assert "Don't reduce your friends to a feature checklist" not in generic.engage_frame


def test_slice_present_on_both_frames():
    definition = _definition()
    fragments = (
        "Firebrand (Champion) — Courage through conviction.",
        "What is worth fighting for?",
        "Gardener: he counsels readiness; I must not read slowness as fear.",
        "Bear: he prices what must survive",
        "Fox: he breaks from the frame where I break for a cause",
        "Crane: she translates where I name a side; translation is not cowardice",
        "Weaver: she sequences where I act; sequencing is not dithering",
        "Raven: he audits whether conviction is earned; evidence-asking is not opposition.",
        "pursue the hill and the tipping point where deliberation becomes avoidance",
    )
    for text in (definition.turn_frame, definition.engage_frame):
        for fragment in fragments:
            assert fragment in text, fragment


# ------------------------------------------------- integrity invariants


def test_invariants_verbatim_in_frames():
    script = _script()
    definition = _definition()
    # Reveal timing: name withheld until the reveal, on every frame.
    for text in (
        script.encounter_frame,
        script.readback_frame,
        script.correction_frame,
        script.readback_reply_frame,
        definition.turn_frame,
    ):
        assert "Do not reveal your name yet." in text
    # Grounding (read-back): substantive material only, never courtesies.
    assert (
        "Ground the impression ONLY in their substantive material: their "
        "undertaking, the positions they actually took, the experiences "
        "they recounted, the choices they described."
    ) in script.readback_frame
    assert "how someone humors a scene is not evidence of how they orient" in (
        script.readback_frame
    )
    # Position, not summary; own words, never spliced first-person words.
    assert "take a POSITION: offer exactly ONE tentative first impression" in (
        script.readback_frame
    )
    assert "never let their first-person words come out of your mouth" in (
        script.readback_frame
    )
    # Doubt held at the exact point, never a blanket hedge.
    assert "name THAT part as the guess" in script.readback_frame
    assert "Never offer a blanket hedge that names nothing" in script.readback_frame
    # Correction replaces; acknowledgment leaves standing.
    assert "The revised impression REPLACES the earlier one" in script.correction_frame
    assert "do not explain any system or bookkeeping" in script.correction_frame
    assert "their answer completes the recognition in itself" in (
        script.readback_reply_frame
    )
    # No invented training: a first impression is a proposal, never a claim.
    for text in (definition.turn_frame, definition.engage_frame):
        assert "Never invent training, history, or evidence for this visitor." in text
        assert "a first impression is a proposal, never a filed claim" in text
        assert "say you don't remember rather than filling it in" in text
    # Honesty guard on capabilities rides the capability context.
    assert "Never present a planned capability as available" in (
        definition.capability_context
    )


def test_naming_note_and_trailer_and_recognition_note_are_runtime_provided():
    definition = _definition()
    # Two-tier naming: roles until met — appended by the runtime to
    # every generation path, not baked into the script.
    assert ENC._naming_note(definition) == "Other seats: roles until met. None met yet."
    # Open-door trailer instruction (post-recognition turns).
    assert "[[thread:open]]" in ENC._THREAD_TRAILER_INSTRUCTION
    assert "[[thread:settled]]" in ENC._THREAD_TRAILER_INSTRUCTION
    # Recognition separated from agreement.
    assert "completes the recognition in itself" in ENC._RECOGNITION_NOTE


def test_parser_contract_delimiter_and_strands():
    definition = _definition()
    # The engage glue: reply first, then a line containing only ---,
    # then the impression as its own movement.
    assert "containing only ---" in definition.engage_frame
    # The read-back frame demands the exact Strands bookkeeping form.
    assert "in exactly this form: 'Strands: <names>'" in definition.impression_frame
    assert "in exactly this form: 'Strands: <names>'" in definition.correction_frame
    # And the runtime's splitter honors that form.
    text, strands = ENC.split_strands_trailer(
        "A position taken in her own words.\nStrands: Compass, Hands"
    )
    assert text == "A position taken in her own words."
    assert strands == ["Compass", "Hands"]


# ------------------------------------------------------------ accessibility


def test_champion_meeting_is_visitor_beginnable(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    # The script exists — state says so honestly — and the hold is
    # lifted (all-six release): the entry order is now the only
    # refusal before the Weaver is met.
    assert svc.state(uid, "champion")["has_script"] is True
    with pytest.raises(MeetingError, match="Weaver opens the council"):
        svc.start(uid, "champion")
    # And it changes nothing for the Conductor, which still begins.
    state = svc.start(uid, "conductor")
    assert state["status"] == "active"
    # With the Weaver's keystone 1 Done, the Champion begins.
    from local_ai.conversation.meeting import _seat_keystone_tasks
    from local_ai.vision_execution.models import TaskUpdate

    tasks = _seat_keystone_tasks(uid, "conductor")
    assert tasks and tasks[0]["status"] != "Done"
    ve.update_task(tasks[0]["id"], TaskUpdate(status="Done"), uid)
    state = svc.start(uid, "champion")
    assert state["status"] == "active"


def test_turn_without_a_begin_is_refused(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    with pytest.raises(MeetingError, match="No meeting is in progress"):
        svc.turn(uid, "champion", "Hello?")


# ------------------------------------------------------------------ budget


def test_frame_sizes_fit_the_voice_builder_cap():
    definition = _definition()
    for name, text in (
        ("turn", definition.turn_frame),
        ("engage", definition.engage_frame),
    ):
        assert len(text) < 8000, name
        assert 8000 - len(text) >= 300, name


# ------------------------------------------- restart / supersede (2026-10-28)
#
# DECISION (Joshua, 2026-10-28): prior-run claims on restart use
# SUPERSEDE — a new run's filed impression replaces the prior run's
# claim, the old row stays visible with its prior verdict preserved,
# nothing is erased, and exactly one standing claim remains. This is
# DISTINCT from the pending-impression discard rule (impressions
# never delivered on voluntary end). Precise semantics: restart
# ALONE does not supersede; supersession happens only at the new
# filing.
#
# OVERLAP NOTE: the authoritative shared supersede mechanism is
# owned by a separate shared-foundation follow-up PR (stacked on
# PR #255). This PR deliberately ships NO filing mechanism of its
# own — a champion-only filing hack would duplicate and fight the
# shared one, and the shared version wins at merge (keep only one
# mechanism). So: the restart-alone clause is tested here as
# passing (it is current behavior), and the at-filing clause is
# covered by a test un-skipped once the shared mechanism (#260)
# landed. The behavioral spec lives in
# docs/champion-first-meeting-behavioral-specs.md, Spec 9.
#
# Harness note: the meeting's HELD hold was lifted in the all-six
# release (2026-10-29). These tests keep the in-process lift
# (monkeypatch) as a belt-and-braces guard, complete the
# Conductor first (the entry-seat guard), then drive the Champion
# arc with a fake voice — no model calls, no live runs.


class _ArcGen:
    """Fake voice: read-back names Compass + Logic, as in
    tests/test_meetings.py and tests/test_meeting_impressions.py."""

    def __call__(self, prompt, **kwargs):
        if "has just corrected your first impression" in prompt:
            return (
                "A first impression, anchored in [[u]]your words[[/u]] — correct me."
                "\nStrands: Compass, Logic"
            )
        if "READ-BACK" in prompt:
            return (
                "A first impression, anchored in [[u]]your words[[/u]] — correct me."
                "\nStrands: Compass, Logic"
            )
        if "ENCOUNTER" in prompt:
            return "An engaged reply that hears two tensions together."
        return "A plain reply."


def _svc_with_agents(tmp_path):
    from local_ai.agent_intake.store import AgentStore

    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_ArcGen(),
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _agents(tmp_path, uid):
    from local_ai.agent_intake.store import AgentStore

    return AgentStore(tmp_path / "agents.db", user_id=uid)


def _run_conductor_to_completion(svc, uid):
    # UPDATED for decoupled recognition (no-scripting build,
    # 2026-10-29): recognition no longer closes — the visitor's
    # own Complete action finishes it (cf.
    # tests/test_conductor_supersede.py).
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I triage by what breaks first if I ignore it.")
    svc.turn(
        uid, "conductor",
        "And in my own work it's the same — what breaks first gets my hands first.",
    )
    state = svc.turn(uid, "conductor", "That's right.")
    if state["status"] != "complete":
        state = svc.turn(uid, "conductor", "Got it.")
    if state["status"] != "complete":
        state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    return state


def _run_champion_to_completion(svc, uid, answer, response):
    # UPDATED for decoupled recognition (six-seat references,
    # 2026-10-29): the Champion is decoupled like all seven, so
    # recognition no longer closes — the visitor's own Complete
    # action finishes it.
    state = svc.start(uid, "champion")
    assert state["status"] == "active"
    svc.turn(uid, "champion", answer)
    svc.turn(uid, "champion", response)
    state = svc.turn(uid, "champion", "Got it.")
    if state["status"] != "complete":
        state = svc.complete(uid, "champion")
    assert state["status"] == "complete"
    return state


def _lift_hold(monkeypatch):
    monkeypatch.setattr(MT, "HELD_FIRST_MEETINGS", frozenset())


def test_restart_alone_does_not_supersede(ve_ctx, tmp_path, monkeypatch):
    """Restart archives verbatim; the run-1 claim stays standing."""
    _lift_hold(monkeypatch)
    uid = _seeded_user("superseed@example.com")
    svc = _svc_with_agents(tmp_path)
    _run_conductor_to_completion(svc, uid)
    _run_champion_to_completion(
        svc, uid,
        "I keep circling whether to quit my job and start the thing.",
        "Mostly right — except the price is my savings, not my pride.",
    )
    store = _agents(tmp_path, uid)
    claims = store.get_claims("meeting-champion-1")
    assert len(claims) == 1
    assert claims[0].claim_type == "meeting_impression"
    assert claims[0].status == "pending"
    # Give it a verdict, so the restart-alone assertion is about a
    # verdict-bearing claim, not just a pending one.
    store.update_claim(claims[0].id, status="accepted")

    state = svc.restart(uid, "champion")
    assert state["status"] == "not_started"
    # The prior run is archived verbatim, not deleted.
    archives = svc.meetings.list_archives(uid, "champion", 1)
    assert len(archives) == 1
    assert archives[0]["readback_claim"].startswith("A first impression")
    # And the run-1 claim is untouched: same row, same verdict,
    # still the standing claim.
    after = store.get_claims("meeting-champion-1")
    assert len(after) == 1
    assert after[0].id == claims[0].id
    assert after[0].status == "accepted"


def test_second_filing_supersedes_prior_claim(ve_ctx, tmp_path, monkeypatch):
    """Two-run sequence (Joshua, 2026-10-28): run 1 files, restart,
    run 2 files — the old claim is retained + superseded with its
    prior verdict visible, the new claim stands, standing count 1.

    SPEC IN CODE FORM: the exact superseded-status vocabulary
    follows the shared mechanism; what is pinned here is the
    decided semantics — row retained (never deleted), prior
    verdict visible in the retained row (never silently
    overwritten), exactly one standing claim afterwards.
    """
    _lift_hold(monkeypatch)
    uid = _seeded_user("superseed2@example.com")
    svc = _svc_with_agents(tmp_path)
    _run_conductor_to_completion(svc, uid)
    _run_champion_to_completion(
        svc, uid,
        "I keep circling whether to quit my job and start the thing.",
        "Mostly right — except the price is my savings, not my pride.",
    )
    store = _agents(tmp_path, uid)
    first = store.get_claims("meeting-champion-1")
    assert len(first) == 1
    store.update_claim(first[0].id, status="accepted")

    svc.restart(uid, "champion")
    _run_champion_to_completion(
        svc, uid,
        "I keep circling whether to take the promotion or leave.",
        "Mostly right — except the hill is the team, not the title.",
    )
    claims = store.get_claims("meeting-champion-1")
    assert len(claims) == 2
    old = [c for c in claims if c.id == first[0].id]
    new = [c for c in claims if c.id != first[0].id]
    assert len(old) == 1 and len(new) == 1
    # Row retained, marked superseded, prior verdict still visible.
    assert old[0].status == "superseded"
    assert "accepted" in (old[0].detail or "") + (old[0].user_note or "")
    # Exactly one standing claim: the new one.
    standing = [c for c in claims if c.status != "superseded"]
    assert standing == new
    assert new[0].status == "pending"
