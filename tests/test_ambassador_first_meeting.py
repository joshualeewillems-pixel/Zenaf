"""Ambassador (Crane) first meeting — script, frames, parser contract,
budget, and the BUILDING ≠ AVAILABLE gate.

The script is WRITTEN in local_ai/council/meetings.py but deliberately
NOT registered in meetings.SCRIPTS, so no visitor can begin it: the
meeting service refuses with "That meeting isn't written yet" (and,
even if it were registered, the Weaver-first entry gate would still
refuse until the Weaver's keystone 1 is Done). Activation is a
separate PR that adds the one-line registration — nothing else.

Frames follow the Weaver #252 prompt-local pattern: guidance + the
verbatim orientation slice appended to BOTH live generation paths
(turn and engage). The slice is verbatim from the PR #254 orientation
draft's delimited block (DRAFT ONLY — canonical text awaits Joshua's
separate verdict); this file pins its card line, its six pair lines,
and its agency lines, not the draft file itself.

No live runs here: every test is headless, no generation, no spend.
Behavioral specs for a separately authorized live run live in
docs/ambassador-first-meeting-behavioral-specs.md.

Spec 9 (restart-claim supersede, Joshua 2026-10-28) is verified
here in two parts, under the decoupled contract (Crane PR,
2026-10-29): recognition turns never complete the meeting — only
the visitor-controlled complete() does (see
test_crane_recognition_moment.py, which exercises the same flow
with test-only activation). The harness below keeps the
production gate activation exactly as before (script registration
only, no release change), so both tests below remain blocked by
the pre-existing release gate at svc.start — the same failure as
on main, not a failure introduced here — and their bodies already
encode the new contract for when the gate question is separately
decided.
"""

from __future__ import annotations

import dataclasses
import threading

import pytest

from local_ai.agent_intake.store import AgentStore
from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import (
    MeetingError,
    MeetingService,
    MeetingStore,
    _seat_keystone_tasks,
)
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT
from local_ai.council import steward_records as SR
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as ve_models
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


def _seeded_user(email="amb@example.com"):
    user = ve.create_user_account(email, "pw", "Amb")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _definition():
    return ENC.get_definition(MT.AMBASSADOR_FIRST_MEETING)


def _composed_engage(definition):
    """The engage frame as the live path actually sends it: the
    definition's engage frame + the runtime's Zenaf note, naming note,
    and capability context (encounter.handle_turn, substantive path)."""
    return (
        definition.engage_frame
        + "\n\n" + ENC._ZENAF_QUESTION_NOTE
        + "\n\n" + ENC._naming_note(definition)
        + "\n\n" + definition.capability_context
    )


# ---------------------------------------------------------------------------
# The script itself
# ---------------------------------------------------------------------------

def test_script_identity_from_approved_sources():
    script = MT.AMBASSADOR_FIRST_MEETING
    assert script.archetype_id == "ambassador"
    assert script.keystone_index == 1
    assert script.character == "Crane"
    # One-line demeanor, verbatim from the keystone seed data.
    assert script.demeanor == "Curious about the other side; holds two truths lightly."
    # Approved ideal (archetypes.py, revised PR #250) + defining question.
    assert "Understanding across difference" in ENC._AMBASSADOR_REFERENCE_SLICE
    assert "What can bring us together" in script.opening[2]


def test_opening_four_bubbles_no_announcement():
    opening = MT.AMBASSADOR_FIRST_MEETING.opening
    assert len(opening) == 4
    joined = "\n".join(opening)
    # Introductions are earned, not announced: no name, no role, no
    # other seat's character name in the opening.
    assert "Crane" not in joined
    assert "Ambassador" not in joined
    for name in ("Gardener", "Firebrand", "Bear", "Fox", "Weaver", "Raven"):
        assert name not in joined, name
    # Her question is asked outright, and a visitor with nothing to
    # carry is a guest, not a failure to fix.
    assert "What can bring us together" in joined
    assert "nothing you want carried anywhere today" in joined
    # The question bank is retired by design, as the Weaver's was.
    assert MT.AMBASSADOR_FIRST_MEETING.questions == ()
    # The authored definition therefore delivers the opening whole.
    assert _definition().opening == tuple(opening)


def test_reveal_follows_existing_ceremony():
    reveal = MT.AMBASSADOR_FIRST_MEETING.reveal
    assert len(reveal) == 3
    assert "actually heard each other now" in reveal[0]
    # Only name, face-adjacent demeanor: no motto, no flaw, nobody else.
    assert reveal[1].startswith("I'm the Crane")
    assert "I hold two truths lightly" in reveal[1]
    assert "door stands open both ways" in reveal[2]
    for name in ("Gardener", "Firebrand", "Bear", "Fox", "Weaver", "Raven"):
        assert name not in "\n".join(reveal), name


def test_orientation_material_honors_weaver_trace():
    script = MT.AMBASSADOR_FIRST_MEETING
    # The Weaver's ambassador allusion, settled from the Crane's side:
    # the rephrasing is her craft, done in the open.
    assert any("done in the open" in p for p in script.orientation)
    assert "two hands" in script.orientation_facts
    assert "You translate, you do not summon" in script.orientation_facts
    # Orientation answers never name seats: facts name no character.
    for name in ("Gardener", "Firebrand", "Bear", "Fox", "Weaver", "Raven"):
        assert name not in script.orientation_facts, name


# ---------------------------------------------------------------------------
# BUILDING ≠ AVAILABLE — the gate
# ---------------------------------------------------------------------------

def test_script_registered_and_beginnable(ve_ctx, tmp_path):
    assert MT.get_script("ambassador", 1) is not None
    assert MT.has_script("ambassador", 1) is True
    assert ("ambassador", 1) in MT.SCRIPTS
    uid = _seeded_user()
    svc = _svc(tmp_path)
    # Without the Weaver's keystone 1 Done, the entry gate refuses.
    with pytest.raises(MeetingError, match="Weaver opens the council"):
        svc.start(uid, "ambassador")
    state = svc.state(uid, "ambassador")
    assert state["has_script"] is True
    assert state["character"] == "Crane"
    assert state["demeanor"] is None


def test_entry_gate_is_a_second_layer(ve_ctx, tmp_path, monkeypatch):
    """The script is registered (all-six release); the Weaver-first
    entry gate still refuses until the Weaver's keystone 1 is Done —
    gate/keystone semantics for existing seats are unchanged."""
    uid = _seeded_user()
    monkeypatch.setitem(
        MT.SCRIPTS, ("ambassador", 1), MT.AMBASSADOR_FIRST_MEETING)
    svc = _svc(tmp_path)
    with pytest.raises(MeetingError, match="Weaver opens the council"):
        svc.start(uid, "ambassador")


def test_no_steward_wiring_for_this_seat():
    """Steward consolidation was Weaver-only. The steward record source
    still carries only the Weaver's script; the Ambassador's rollback
    source is meetings.py alone, code-only, no migration, no schema."""
    assert SR.SCRIPT_CHARACTER == "Weaver"
    assert MT.AMBASSADOR_FIRST_MEETING.character == "Crane"


# ---------------------------------------------------------------------------
# Frames: guidance + slice on both live paths, invariants verbatim
# ---------------------------------------------------------------------------

def test_guidance_and_slice_on_both_frames():
    definition = _definition()
    for name, text in (("turn", definition.turn_frame),
                       ("engage", definition.engage_frame)):
        # Opportunity wording, not a mandatory sequence.
        assert "opportunity to encounter your distinctive personality" in text, name
        assert "never a mandatory introduction sequence" in text, name
        assert "checklist, or coverage obligation" in text, name
        # Prompt-control cleanup, Weaver P1 pattern.
        assert "Don't reduce your friends to a feature checklist." in text, name
        assert "never by a prescribed procedure" in text, name
        # Direct-answer-first.
        assert "Answer a direct question first, in plain words" in text, name
        # Proposed system slice, marked as proposed, never decided.
        assert "PROPOSED (draft, not decided)" in text, name
        assert "how perspectives meet" in text, name
        assert "Never present that mapping as decided" in text, name
        # The verbatim slice: card line, six pair lines, agency lines.
        assert "Crane (Ambassador) — Understanding across difference" in text, name
        for pair in ("(Pair 4.)", "(Pair 9.)", "(Pair 13.)",
                     "(Pair 16.)", "(Pair 19.)", "(Pair 20.)"):
            assert pair in text, (name, pair)
        assert "answer direct questions directly, in the asker's own terms" in text, name
        # No prescribed yield procedure anywhere, no reveal variants,
        # no second-utterance auto-close, no model-call selector.
        assert "prescribed yield procedure" not in text, name
        assert "auto-close" not in text, name


def test_generic_path_carries_no_ambassador_guidance():
    generic = ENC.build_definition(MT.AMBASSADOR_FIRST_MEETING)
    assert "Don't reduce your friends to a feature checklist." not in generic.turn_frame
    assert "Don't reduce your friends to a feature checklist." not in generic.engage_frame
    assert "Crane (Ambassador)" not in generic.turn_frame
    assert "Crane (Ambassador)" not in generic.engage_frame


def test_no_other_seat_inherits_ambassador_frames():
    weaver = ENC.get_definition(MT.get_script("conductor", 1))
    assert "Don't reduce your friends to a feature checklist." not in weaver.turn_frame
    assert "Don't reduce your friends to a feature checklist." not in weaver.engage_frame
    assert "Crane (Ambassador)" not in weaver.turn_frame
    assert "Crane (Ambassador)" not in weaver.engage_frame
    assert weaver.opening == MT.WEAVER_INTRODUCTION


def test_integrity_invariants_verbatim():
    script = MT.AMBASSADOR_FIRST_MEETING
    for frame in (script.encounter_frame, script.readback_frame,
                  script.correction_frame, script.readback_reply_frame):
        # Reveal timing: the name is never revealed in any frame.
        assert "Do not reveal your name yet." in frame
    # Grounding + doubt-point + sentence count, read-back only.
    assert "Ground the impression ONLY in their substantive material" in script.readback_frame
    assert "Never ground it in the courtesies of the meeting" in script.readback_frame
    assert "the part I may have wrong is…" in script.readback_frame
    assert "never a blanket hedge that names nothing" in script.readback_frame
    assert "Three to five sentences." in script.readback_frame
    assert "Three to five sentences." in script.correction_frame
    # No invented training.
    assert "Claim no knowledge of this visitor from training" in script.readback_frame
    assert "nothing from this meeting trains anything until it goes through review" in script.readback_frame
    # Strands bookkeeping line, exactly the Weaver form, both read frames.
    strands_form = (
        "'Strands: <names>' listing the one or two of the seven strands "
        "(Voice, Logic, Eye, Ear, Hands, Heart, Compass)"
    )
    assert strands_form in script.readback_frame
    assert strands_form in script.correction_frame
    # Read-back unmandated shape discipline: contrast + doubt are
    # available shapes, and the delimiter + Strands line survive.
    assert "contrast the read with your own tendency" in script.readback_frame


def test_parser_contract_delimiter_and_strands():
    assert ENC._DELIMITER == "---"
    runtime = ENC.EncounterRuntime(_definition())
    reply, impression, had_delim = runtime._split_reply_and_impression(
        "A reply that hears both sides.\n---\n"
        "A first impression, held at its doubt point.\nStrands: Voice, Heart"
    )
    assert had_delim is True
    assert reply == "A reply that hears both sides."
    claim, strands = ENC.split_strands_trailer(impression)
    assert claim == "A first impression, held at its doubt point."
    assert strands == ["Voice", "Heart"]
    # A reply-only output (no delimiter, no Strands) is the honest
    # degrade: the impression waits for the exchange that earns it.
    reply2, impression2, had_delim2 = runtime._split_reply_and_impression(
        "A reply with no read yet.")
    assert had_delim2 is False
    claim2, strands2 = ENC.split_strands_trailer(impression2)
    assert strands2 == []
    assert claim2 == "A reply with no read yet."
    # Thread trailer strips cleanly and never reaches the user.
    body, verdict = ENC.split_thread_trailer(
        "A spoken reply.\n[[thread:settled]]")
    assert body == "A spoken reply."
    assert verdict == "settled"


# ---------------------------------------------------------------------------
# Budget — measured, not claimed (see PR description for the table)
# ---------------------------------------------------------------------------

def test_frame_budget_fits_live_cap_with_guard_intact():
    """Binding cap: reply.py truncates extra_instructions to 8000, and
    the meeting path sends the composed engage frame through it. The
    honesty guard rides at the END of the composed frame (capability
    context tail), so it survives only if the composed frame fits.
    Measured here, not asserted from the proposal's arithmetic."""
    definition = _definition()
    composed = _composed_engage(definition)
    assert len(composed) <= 8000
    # The guard is the last content of the composed frame.
    assert composed.rstrip().endswith("immediately usable.")
    # Worst-case naming note: every other seat already met.
    all_met = dataclasses.replace(
        definition,
        met_seats=("conductor", "mentor", "champion",
                   "guardian", "skeptic", "maverick"),
    )
    assert len(_composed_engage(all_met)) <= 8000
    # Turn and post-recognition paths fit with room.
    runtime = ENC.EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(ENC.EncounterState(), "hello")
    assert len(turn_frame) <= 8000
    post_recognition = (
        turn_frame
        + "\n\nNotes on this place, if they ask about it — answer only from these, "
        "plainly, in character, never as someone explaining a system:\n"
        + definition.orientation_facts
        + ENC._RECOGNITION_NOTE + ENC._THREAD_TRAILER_INSTRUCTION
    )
    assert len(post_recognition) <= 8000


def test_fallback_cap_combined_fit_reported_honestly():
    """The 12,500 fallback cap (proposal §2, not in code on origin/main):
    the authored engage frame + the full shared reference (~3,739) +
    a cue (371) fits — but the composed engage frame + reference + cue
    is reported alongside it in the PR description, and the slice
    migrates to the uncapped section after PR #255 merges rather than
    stacking the reference on top of this frame. Neither number is a
    claim of a fit that was not measured."""
    definition = _definition()
    assert len(definition.engage_frame) + 3739 + 371 <= 12500
    assert len(_composed_engage(definition)) + 3739 + 371 <= 12500


# ---------------------------------------------------------------------------
# Spec 9 — restart-claim supersede (Joshua, 2026-10-28)
#
# The script is still unregistered on this branch, so the harness
# activates it test-only (the existing gate test's monkeypatch
# pattern) and satisfies the Weaver-first entry gate by marking the
# Conductor's keystone 1 Done — exactly what a visitor who has met
# the Weaver looks like. The fake generation beats mirror
# tests/test_meeting_impressions.py's conductor fake (read-back on
# the READ-BACK / correction prompts, an engaged reply on ENCOUNTER);
# no test-to-test import, so this file stays self-contained.
# ---------------------------------------------------------------------------

class _SupersedeFakeGen:
    """Same beats as the conductor impression fake: the read-back
    names the Compass and Logic strands, so each run files one
    meeting_impression claim under meeting-ambassador-1."""

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


def _supersede_svc(tmp_path):
    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_SupersedeFakeGen(),
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _supersede_store(tmp_path, uid):
    return AgentStore(tmp_path / "agents.db", user_id=uid)


def _ambassador_ready_user(monkeypatch):
    """Seeded user, script activated test-only, Weaver gate satisfied."""
    uid = _seeded_user(email="amb-supersede@example.com")
    monkeypatch.setitem(
        MT.SCRIPTS, ("ambassador", 1), MT.AMBASSADOR_FIRST_MEETING)
    conductor_tasks = _seat_keystone_tasks(uid, "conductor")
    ve.update_task(
        conductor_tasks[0]["id"], ve_models.TaskUpdate(status="Done"), uid)
    return uid


def _run_ambassador_to_completion(svc, uid, answer, response):
    """Drive one run to completion through the public meeting API
    under the decoupled contract (Crane PR, 2026-10-29): turn 1 is
    substantive (the read lands), turn 2 answers the read-back
    (and becomes the filed claim's evidence), turn 3 is a settled
    thread — which must NOT close a decoupled meeting — and only
    the visitor-controlled complete() completes it, filing the
    claim through the same chokepoint as a runtime close."""
    svc.start(uid, "ambassador")
    svc.turn(uid, "ambassador", answer)
    svc.turn(uid, "ambassador", response)
    state = svc.turn(uid, "ambassador", "Got it.")
    assert state["status"] != "complete"
    state = svc.complete(uid, "ambassador")
    assert state["status"] == "complete"
    return state


def _standing(claims):
    """Current claims: everything not marked superseded. The shared
    mechanism's representation (spec 9's recommendation) is status
    'superseded'; the count below is what the decision pins."""
    return [c for c in claims if c.status != "superseded"]


def test_restart_alone_does_not_supersede(ve_ctx, tmp_path, monkeypatch):
    """Spec 9a: restart archives the run verbatim and touches no
    claim. This test pins it against mechanism change; its run
    currently stops at the pre-existing release gate at svc.start
    (same failure as on main), with the completion step already
    updated to the decoupled contract."""
    uid = _ambassador_ready_user(monkeypatch)
    svc = _supersede_svc(tmp_path)
    _run_ambassador_to_completion(
        svc, uid,
        "I triage by what breaks first if I ignore it.",
        "Mostly right — except I protect mornings first.",
    )
    store = _supersede_store(tmp_path, uid)
    first = store.get_claims("meeting-ambassador-1")
    assert len(first) == 1
    assert first[0].claim_type == "meeting_impression"
    store.update_claim(first[0].id, status="accepted")

    svc.restart(uid, "ambassador")

    claims = store.get_claims("meeting-ambassador-1")
    assert len(claims) == 1
    assert claims[0].id == first[0].id
    assert claims[0].status == "accepted"
    assert len(_standing(claims)) == 1


def test_second_run_supersedes_prior_claim(ve_ctx, tmp_path, monkeypatch):
    """Spec 9b: run 1 files, verdict accepted, restart, run 2 files.
    Expected end state once the shared mechanism lands: the run-1
    row retained (same id/evidence/inference), marked superseded
    with its prior verdict visible in the row, the run-2 claim
    standing, standing count == 1. Shared mechanism (#260) landed.
    Completion here is visitor-controlled (decoupled contract);
    the test remains blocked by the pre-existing release gate at
    svc.start until the gate question is separately decided."""
    uid = _ambassador_ready_user(monkeypatch)
    svc = _supersede_svc(tmp_path)
    _run_ambassador_to_completion(
        svc, uid,
        "I triage by what breaks first if I ignore it.",
        "Mostly right — except I protect mornings first.",
    )
    store = _supersede_store(tmp_path, uid)
    first = store.get_claims("meeting-ambassador-1")
    assert len(first) == 1
    first_claim = first[0]
    store.update_claim(first_claim.id, status="accepted")

    svc.restart(uid, "ambassador")
    _run_ambassador_to_completion(
        svc, uid,
        "Second time: I start with people, not tasks.",
        "And people first means the message, not the task list.",
    )

    claims = store.get_claims("meeting-ambassador-1")
    assert len(claims) == 2  # both rows retained, nothing erased
    by_id = {c.id: c for c in claims}
    old = by_id[first_claim.id]
    assert old.status == "superseded"
    assert "accepted" in old.detail  # prior verdict visible, not silently lost
    assert old.evidence == "Mostly right — except I protect mornings first."
    assert old.inference == first_claim.inference
    new = next(c for c in claims if c.id != first_claim.id)
    assert new.claim_type == "meeting_impression"
    assert new.status == "pending"
    assert new.evidence == "And people first means the message, not the task list."
    standing = _standing(claims)
    assert len(standing) == 1
    assert standing[0].id == new.id
