"""The Weaver's first meeting, rewritten (redesign, Joshua 2026-10-23).

Semantics under test:
  - The opening interrupts the Weaver mid-work on an instrument of seven
    incompatible parts; the encounter question is a DILEMMA (mover /
    planner / doubter — "Who do you listen to?"), not a generic
    priorities question.
  - The read-back is a POSITION with an honest contrast, not a
    paraphrase (the frame instructs exactly that).
  - The reply to the read-back classifies three ways. A CORRECTION
    replaces the stored impression (claim AND strand attribution) and
    the revision is spoken in the room; an ACKNOWLEDGMENT leaves the
    stored impression untouched; an OTHER reply gets one brief engaged
    answer and the impression stands.
  - No system-explaining dialogue: the Weaver never quotes the record
    back, never mentions review/strands/training in spoken lines, and
    the close is an invitation, not a completion declaration.
  - The six fellowship allusions are present verbatim in the script
    data, carry no seat names/titles/animal words, and are recorded as
    debts in the environmental registry — which covers all seven seats
    with a signature, a represents line, and concrete fixtures.
"""

from __future__ import annotations

import json
import re
import threading

import pytest

from local_ai.council import meetings as MT
from local_ai.conversation.meeting import (
    MeetingService,
    MeetingStore,
    _classify_readback_reply,
)
from local_ai.conversation.store import ConversationStore
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


class FakeGen:
    """Answers by beat so tests can see which frame ran."""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "has just corrected your first impression" in prompt:
            return (
                "Say it again, properly: in you, [[u]]planning comes "
                "first[[/u]] — everything arranged before anything moves."
                "\nStrands: Logic"
            )
        if "READ-BACK beat" in prompt:
            return (
                "A first read, held lightly: you [[u]]listen to whoever "
                "the moment asks for[[/u]]. Me, I'd arrange it all first."
                "\nStrands: Compass, Heart"
            )
        if "ENCOUNTER beat" in prompt:
            return "An engaged reply from the bench."
        if "ORIENTATION beat" in prompt:
            return "An in-character answer from the workshop notes."
        if "neither agreeing nor correcting" in prompt:
            return "A brief engaged reply; the impression stands."
        return "A plain reply."


def _svc(tmp_path, gen=None):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=gen or FakeGen(),
    )


def _seeded_user(email="rewrite@example.com"):
    user = ve.create_user_account(email, "pw", "Rewrite")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _to_readback(svc, uid, answer="Intuition, usually — unless something practical is pressing."):
    svc.start(uid, "conductor")
    state = svc.turn(uid, "conductor", answer)
    assert state["stage"] == "readback"
    return state


# ------------------------------------------------------- opening / dilemma


def test_opening_is_a_midwork_interruption(ve_ctx, tmp_path):
    """UPDATED for the encounter runtime (P3): what is DELIVERED at the
    door is the minimal opening — the interruption itself and the
    invitation (the dilemma) — so the user participates within three
    bubbles (Joshua's pacing correction after playing the rewrite:
    the stacked six-bubble opening read as a barrage). The full
    scripted opening still exists as the encounter's bench anchors —
    asserted here as data, where the runtime draws on it."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    script = MT.get_script("conductor", 1)
    bodies = [m["body"] for m in state["messages"]]
    assert bodies == [script.opening[0], script.questions[0]]
    assert "does this look broken to you, or merely unfinished?" in bodies[0]
    # The seven-parts material is bench context now, not a door speech.
    assert "seven rather incompatible things" in script.opening[1]
    assert "Personally, I think we're making progress." in script.opening
    assert not any("seven rather incompatible things" in b for b in bodies)


def test_first_question_is_the_dilemma(ve_ctx, tmp_path):
    script = MT.get_script("conductor", 1)
    dilemma = script.questions[0]
    assert "get moving" in dilemma  # the mover
    assert "planned" in dilemma  # the planner
    assert "misguided" in dilemma  # the doubter
    assert dilemma.rstrip().endswith("Who do you listen to?")
    # The generic priorities question is gone.
    assert not any("competing priorities" in q for q in script.questions)


def test_readback_frame_demands_a_position_with_contrast(ve_ctx, tmp_path):
    script = MT.get_script("conductor", 1)
    frame = script.readback_frame
    assert "POSITION" in frame
    assert "contrast" in frame.lower()
    assert "do not paraphrase" in frame.lower()
    # And the position actually flows: dilemma answer → read-back stage.
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = _to_readback(svc, uid)
    bodies = [m["body"] for m in state["messages"]]
    assert any("A first read, held lightly" in b for b in bodies)
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"].startswith("A first read, held lightly")
    assert json.loads(row["readback_strands"]) == ["Compass", "Heart"]


# ------------------------------------------------------------- correction


def test_classifier_three_way():
    assert _classify_readback_reply("Ok sounds good") == "ack"
    assert _classify_readback_reply("Yeah, that's right") == "ack"
    assert _classify_readback_reply("Yes — that's exactly right.") == "ack"
    assert _classify_readback_reply("Actually, it's the opposite for me.") == "correction"
    assert _classify_readback_reply("Mostly right — except I protect mornings first.") == "correction"
    assert _classify_readback_reply("No — I plan everything first.") == "correction"
    assert _classify_readback_reply("Not quite — more like I follow whoever's calmest.") == "correction"
    assert _classify_readback_reply("Hmm.") == "other"
    assert _classify_readback_reply("Interesting.") == "other"
    assert _classify_readback_reply("Close enough.") == "other"


def test_correction_replaces_the_stored_impression(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = FakeGen()
    svc = _svc(tmp_path, gen)
    _to_readback(svc, uid)
    before = svc.meetings.get(uid, "conductor", 1)
    assert before["readback_claim"].startswith("A first read")

    correction = "Actually no — planning comes first with me, always."
    state = svc.turn(uid, "conductor", correction)
    assert state["stage"] == "orientation"  # the meeting proceeds

    row = svc.meetings.get(uid, "conductor", 1)
    # The stored impression was REPLACED — claim and attribution alike —
    # while the user's correction stands verbatim as their response.
    assert row["readback_claim"].startswith("Say it again, properly")
    assert row["readback_claim"] != before["readback_claim"]
    assert json.loads(row["readback_strands"]) == ["Logic"]
    assert row["readback_response"] == correction
    # The revision was spoken in the room, not just filed silently.
    bodies = [m["body"] for m in state["messages"]]
    assert any(b.startswith("Say it again, properly") for b in bodies)
    assert any("has just corrected your first impression" in p for p in gen.prompts)


def test_acknowledgment_leaves_the_impression_untouched(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _to_readback(svc, uid)
    before = svc.meetings.get(uid, "conductor", 1)

    state = svc.turn(uid, "conductor", "Yeah, that's right.")
    assert state["stage"] == "orientation"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == before["readback_claim"]
    assert row["readback_strands"] == before["readback_strands"]
    assert row["readback_response"] == "Yeah, that's right."


def test_other_reply_engages_and_the_impression_stands(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _to_readback(svc, uid)
    before = svc.meetings.get(uid, "conductor", 1)

    state = svc.turn(uid, "conductor", "Hmm. Interesting.")
    assert state["stage"] == "orientation"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == before["readback_claim"]
    bodies = [m["body"] for m in state["messages"]]
    assert "A brief engaged reply; the impression stands." in bodies


def test_corrected_meeting_still_completes(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _to_readback(svc, uid)
    svc.turn(uid, "conductor", "Actually it's more like I decide alone, then tell people.")
    state = svc.turn(uid, "conductor", "Got it.")
    assert state["status"] == "complete"
    script = MT.get_script("conductor", 1)
    bodies = [m["body"] for m in state["messages"]]
    for paragraph in script.reveal:
        assert paragraph in bodies


# ------------------------------------------------- dialogue purity / close


#: Words of the software layer that must never appear in spoken lines.
_SYSTEM_TALK = re.compile(
    r"\b(review|unfiled|strands?|train(?:s|ing|ed)?|approv\w+|filed|filing)\b",
    re.IGNORECASE,
)


def _dialogue_paragraphs(script):
    return (
        list(script.opening) + list(script.questions)
        + list(script.orientation_intro) + list(script.orientation)
        + list(script.reveal)
    )


def test_dialogue_carries_no_system_explanation(ve_ctx, tmp_path):
    script = MT.get_script("conductor", 1)
    for paragraph in _dialogue_paragraphs(script):
        assert not _SYSTEM_TALK.search(paragraph), paragraph
    # The purged audit-log templates are empty in the rewritten script.
    assert script.pulled_item_template == ""
    assert script.pulled_where_template == ""


def test_close_is_an_invitation_not_a_declaration(ve_ctx, tmp_path):
    script = MT.get_script("conductor", 1)
    closing = script.reveal[-1]
    assert "come back" in closing and "bring it here" in closing
    for declaration in ("meeting is complete", "we're done", "that concludes", "you are dismissed"):
        assert declaration not in closing.lower()


# ---------------------------------------------------- allusions / registry


_LOCKED_ALLUSIONS = {
    "mentor": "Someone keeps tending the things I've set aside. Oddly enough, they're often in better shape when I return.",
    "champion": "A few of my instruments have been through the furnace. Some came back stronger. Others didn't come back at all.",
    "guardian": "Some of my instruments have locks I didn't put there. I've stopped picking them. Whatever's behind them is being kept, not hidden.",
    "ambassador": "Things I say in one room arrive in the next slightly rephrased — and, annoyingly, clearer.",
    "skeptic": "Someone leaves question marks in my margins. Never answers. Just the marks.",
    "maverick": "I keep finding passages where I distinctly remember building walls. I haven't decided whether to be grateful.",
}

#: Seat names, titles, characters, and animals — none may appear in an
#: allusion (word-boundaried, so honest words like "better" pass).
_FORBIDDEN_IN_ALLUSION = re.compile(
    r"\b(weaver|gardener|firebrand|bear|bridge|neighbour|neighbor|fox|"
    r"conductor|mentor|champion|guardian|ambassador|skeptic|maverick|"
    r"crane|elephant|lion|raven|octopus)\b",
    re.IGNORECASE,
)


def test_allusions_present_verbatim_and_clean(ve_ctx, tmp_path):
    script = MT.get_script("conductor", 1)
    dialogue = "\n".join(_dialogue_paragraphs(script))
    for seat, line in _LOCKED_ALLUSIONS.items():
        assert line in dialogue, seat
        assert not _FORBIDDEN_IN_ALLUSION.search(line), (seat, line)
    # Distributed, never dumped: the six live in more than one beat.
    in_opening = [line for line in _LOCKED_ALLUSIONS.values() if line in "\n".join(script.opening)]
    in_orientation = [line for line in _LOCKED_ALLUSIONS.values() if line in "\n".join(script.orientation)]
    assert 0 < len(in_opening) < 6 and 0 < len(in_orientation) < 6


def test_environment_registry_covers_every_seat(ve_ctx, tmp_path):
    from local_ai.council.archetypes import stock_archetype_ids

    assert set(MT.SEAT_ENVIRONMENT) == set(stock_archetype_ids())
    for env in MT.SEAT_ENVIRONMENT.values():
        assert env.signature.strip()
        assert env.represents.strip()
        assert env.fixtures and all(f.strip() for f in env.fixtures)


def test_allusions_are_recorded_as_debts(ve_ctx, tmp_path):
    assert len(MT.WEAVER_ALLUSIONS) == 6
    by_seat = {t.seat: t for t in MT.WEAVER_ALLUSIONS}
    assert set(by_seat) == set(_LOCKED_ALLUSIONS)
    for seat, trace in by_seat.items():
        assert trace.text == _LOCKED_ALLUSIONS[seat]
        assert trace.appears_in.strip()
        assert trace.payoff.strip()
        assert seat in MT.SEAT_ENVIRONMENT
