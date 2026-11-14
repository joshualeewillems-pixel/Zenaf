"""Raven S1 regression fixture (implementation brief, revised
2026-11-12, §11.1): T1–T12 deterministic + F1–F2 live.

What S1 changed (founder rulings RC1–RC8, Q1–Q8, RC2, RC4):

- RC1: the universal challenge-grounding line is the fifth line of
  ``CANONICAL_TIER_L1`` (canonical_tier.py) — one canonical source,
  all seven seats, both meeting frames; in NO seat's frame constants.
- RC7+RC2+RC6: a mid-frame block in ``SKEPTIC_TURN_FRAME``.
- RC6: also appended to ``_SKEPTIC_REFERENCE_GUIDANCE``.
- RC3+RC4: two sentences in ``SKEPTIC_FIRST_MEETING.encounter_frame``.
- RC5: one insert in all seven ``correction_frame``s; the
  readback_reply guard is KEPT in all seven reply frames.

All figures below were measured in-process at the build base
(d457d97) with the brief's pinned render method (§12.1), before and
after the edits — not carried arithmetically.

One measured figure departs from the brief's §10.2 projection, and
the departure is recorded here rather than silently absorbed: the
brief projected the runtime turn frame at 5,469 (+548, the
turn-frame block alone). The guidance append (RC6, §6's second
landing place) also rides the turn frame — the Skeptic definition
appends the guidance to BOTH frames — so the measured runtime turn
delta is +694 (block +548, guidance +146) and the measured runtime
turn frame is 5,615. The placements are as ruled; the projection
undercounted one of them. Every cap/floor gate holds with margin.

F1/F2 are LIVE model-call runs (RC8, founder Q7). They are skipped
unless ZENAF_RAVEN_S1_LIVE=1, so the ordinary suite never spends.
Their pass/fail is judged against the Q6 evaluation frame
(jurisdictional rigidity, epistemic asymmetry, inference overreach);
the tests assert the machine-checkable halves (routing, marker
dimensions, spoken replies captured) and print the generations for
the build report's judgment.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import threading

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.canonical_tier import (
    ASSUMPTION_GROUNDING,
    CANONICAL_TIER_L1,
)
from local_ai.conversation.encounter import EncounterRuntime, EncounterState
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.reply import _EXTRA_INSTRUCTIONS_CAP, build_voice_prompt
from local_ai.conversation.store import ConversationStore
from local_ai.council import archetypes as ARCH
from local_ai.council import capabilities as CAP
from local_ai.council import meetings as MT
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import service as ve

# ---------------------------------------------------------------------------
# The ruled texts (verbatim from the brief; lengths re-measured there).
# ---------------------------------------------------------------------------

RC1 = (
    "Challenge only what the visitor actually assumes \u2014 in their "
    "words, or in a metaphor or parallel tracking them. If you cannot "
    "back it up when questioned, do not make it; ask what they assume "
    "instead."
)
RC7 = (
    "Examination without end is overreach. Discernment (not endless "
    "doubt): doubt is the tool; discernment is the stand. A precise "
    "observation can be more devastating than an interrogation. When "
    "the premises are clean, move on."
)
RC2 = (
    "Where alternatives arise, do not present them as mutually "
    "exclusive unless the visitor's material supports that "
    "distinction. Report an assumption as a report, not an "
    "explanation."
)
RC6 = (
    "If a reply shows your question presupposing what the visitor "
    "just denied, name it as your own move and drop it \u2014 do not "
    "re-ask by presupposition."
)
RC3 = (
    "Think in investigation \u2014 and think about your own "
    "investigation: what would change your mind, and what would show "
    "your method asking the wrong question?"
)
RC4 = (
    "Never resume an agenda of your own when they take the "
    "conversation somewhere real."
)
RC5 = (
    "Do not make more of their agreement than they offered: praise "
    "for how the read was put is not affirmation of what it "
    "concluded. If they praised the wording without affirming the "
    "inference, say so plainly and leave the read open \u2014 do not "
    "declare that it stands."
)
READBACK_GUARD = (
    "Do not make more of their agreement than they offered: a short "
    "'yeah' is a short 'yeah', not a deeper endorsement."
)

MSG = "In human communication, words are only about 10% of the communication happening."
SEATS = [
    ("weaver", "conductor", MT.CONDUCTOR_FIRST_MEETING, ENC.build_weaver_k1_definition),
    ("ambassador", "ambassador", MT.AMBASSADOR_FIRST_MEETING, ENC.build_ambassador_k1_definition),
    ("guardian", "guardian", MT.GUARDIAN_FIRST_MEETING, ENC.build_guardian_k1_definition),
    ("mentor", "mentor", MT.MENTOR_FIRST_MEETING, ENC.build_mentor_k1_definition),
    ("skeptic", "skeptic", MT.SKEPTIC_FIRST_MEETING, ENC.build_skeptic_k1_definition),
    ("maverick", "maverick", MT.MAVERICK_FIRST_MEETING, ENC.build_maverick_k1_definition),
    ("champion", "champion", MT.CHAMPION_FIRST_MEETING, ENC.build_champion_k1_definition),
]
SCRIPTS = {seat: script for seat, _arch, script, _b in SEATS}


def _frames(script, builder):
    d = builder(script)
    runtime = EncounterRuntime(d)
    engage = runtime._engage_frame()
    turn, cue = runtime._turn_frame(EncounterState(), MSG)
    assert cue is None
    return d, engage, turn


def _meeting_prompt(arch, frame, definition):
    lines, _ = build_voice_prompt(
        "raven-s1", arch, MSG, [], mode="base", canonical=False,
        extra_instructions=frame,
        fellowship_reference=definition.fellowship_reference or "",
        canonical_tier=True,
    )
    return "\n".join(lines)


def _composed_engage(d, arch, met=()):
    dd = dataclasses.replace(d, met_seats=met) if met else d
    block = CAP.first_meeting_block(arch, CAP.VisitorState())
    return dd.engage_frame + "\n\n" + block + "\n\n" + ENC._naming_note(dd)


def _skeptic():
    return _frames(MT.SKEPTIC_FIRST_MEETING, ENC.build_skeptic_k1_definition)


# ---------------------------------------------------------------------------
# T1 — RC7 in the turn frame only.
# ---------------------------------------------------------------------------

def test_t1_rc7_turn_frame_only():
    _d, engage, turn = _skeptic()
    assert RC7 in ENC.SKEPTIC_TURN_FRAME
    assert RC7 in turn
    assert RC7 not in engage
    prompt = _meeting_prompt("skeptic", turn, _d)
    assert RC7 in prompt
    assert RC7 not in _meeting_prompt("skeptic", engage, _d)


# ---------------------------------------------------------------------------
# T2 — RC1 in the tier, all seven seats, both frames; nowhere else.
# ---------------------------------------------------------------------------

def test_t2_rc1_in_tier_all_seats_both_frames():
    assert ASSUMPTION_GROUNDING == RC1
    assert CANONICAL_TIER_L1.count(RC1) == 1
    for seat, arch, script, builder in SEATS:
        d, engage, turn = _frames(script, builder)
        for label, frame in (("engage", engage), ("turn", turn)):
            prompt = _meeting_prompt(arch, frame, d)
            assert prompt.count(RC1) == 1, f"{seat} {label}: RC1 count"
            assert RC1 not in frame, f"{seat} {label}: RC1 in frame"
        assert RC1 not in d.engage_frame
        assert RC1 not in d.turn_frame
        assert RC1 not in script.encounter_frame
        assert RC1 not in script.correction_frame


def test_t2_rc1_in_no_frame_constant_source():
    # The sentence lives in exactly one source: the tier module.
    # Neither frame-constant file contains even its distinctive
    # fragments (the sentence is line-wrapped in the tier source,
    # so whole-sentence search would be meaningless there too).
    import local_ai.conversation.encounter as enc_mod
    import local_ai.council.meetings as mt_mod

    for mod in (enc_mod, mt_mod):
        with open(mod.__file__, encoding="utf-8") as f:
            src = f.read()
        assert "Challenge only what the visitor" not in src
        assert "ask what they assume" not in src


# ---------------------------------------------------------------------------
# T3 — RC5 in all seven correction frames; the reply guard kept.
# ---------------------------------------------------------------------------

def test_t3_rc5_all_correction_frames_guard_kept():
    anchor = "including an agreement the routing did not recognize as one."
    for seat, script in SCRIPTS.items():
        frame = script.correction_frame
        assert frame.count(RC5) == 1, f"{seat}: RC5 count"
        assert frame.index(RC5) > frame.index(anchor), f"{seat}: RC5 position"
        assert READBACK_GUARD in script.readback_reply_frame, (
            f"{seat}: readback_reply guard missing")


# ---------------------------------------------------------------------------
# T4/T5/T6 — RC2 turn-only; RC3/RC4 encounter-frame-only.
# ---------------------------------------------------------------------------

def test_t4_rc2_turn_frame_only():
    _d, engage, turn = _skeptic()
    assert RC2 in ENC.SKEPTIC_TURN_FRAME
    assert RC2 in turn
    assert RC2 not in engage


def test_t5_rc3_encounter_frame_only():
    _d, engage, turn = _skeptic()
    assert RC3 in MT.SKEPTIC_FIRST_MEETING.encounter_frame
    assert RC3 in engage
    assert RC3 not in turn
    assert RC3 not in ENC.SKEPTIC_TURN_FRAME


def test_t6_rc4_encounter_frame_only():
    _d, engage, turn = _skeptic()
    assert RC4 in MT.SKEPTIC_FIRST_MEETING.encounter_frame
    assert RC4 in engage
    # Case-sensitive: the turn frame carries the lowercase mid-sentence
    # form ("— never resume an agenda of your own..."), not RC4's
    # sentence. RC4 must not appear there as a sentence.
    assert RC4 not in turn
    assert RC4 not in ENC.SKEPTIC_TURN_FRAME


# ---------------------------------------------------------------------------
# T7 — RC6 in the turn frame AND the guidance.
# ---------------------------------------------------------------------------

def test_t7_rc6_turn_frame_and_guidance():
    _d, engage, turn = _skeptic()
    assert RC6 in ENC.SKEPTIC_TURN_FRAME
    assert RC6 in ENC._SKEPTIC_REFERENCE_GUIDANCE
    # The guidance rides both composed frames, so the turn frame
    # carries RC6 twice (block + guidance) and the engage frame once.
    assert turn.count(RC6) == 2
    assert engage.count(RC6) == 1


# ---------------------------------------------------------------------------
# T8 — Budgets hold (rendered, not asserted by string length).
# ---------------------------------------------------------------------------

def test_t8_budgets_hold(caplog):
    caplog.set_level(logging.WARNING, logger="local_ai.conversation.reply")
    _d, engage, turn = _skeptic()
    assert len(engage) == 7968
    # Measured 5,615 — see the module docstring on the brief's 5,469
    # projection (it counted the turn-frame block but not the
    # guidance append, which also rides the turn frame).
    assert len(turn) == 5615
    others_by_seat = {}
    for seat, arch, script, builder in SEATS:
        d, e, t = _frames(script, builder)
        variants = {
            "default": _composed_engage(d, arch),
            "worst-capability": (
                d.engage_frame + "\n\n"
                + CAP.first_meeting_block(arch, CAP.VisitorState(signed_in=False))
                + "\n\n" + ENC._naming_note(d)),
            "fully-met+default": _composed_engage(
                d, arch, met=tuple(a for _s, a, _sc, _b in SEATS if a != arch)),
            "fully-met+worst": (
                dataclasses.replace(
                    d, met_seats=tuple(a for _s, a, _sc, _b in SEATS if a != arch)
                ).engage_frame + "\n\n"
                + CAP.first_meeting_block(arch, CAP.VisitorState(signed_in=False))
                + "\n\n" + ENC._naming_note(
                    dataclasses.replace(
                        d, met_seats=tuple(a for _s, a, _sc, _b in SEATS if a != arch)))),
        }
        others_by_seat[seat] = variants
        for label, frame in variants.items():
            assert len(frame) <= _EXTRA_INSTRUCTIONS_CAP, (
                f"{seat} {label}: {len(frame)} over cap")
            assert _EXTRA_INSTRUCTIONS_CAP - len(frame) >= 300, (
                f"{seat} {label}: headroom below 300")
        _meeting_prompt(arch, e, d)
        _meeting_prompt(arch, t, d)
    # The system's tightest reachable/bound states, pinned: the
    # Mentor's fully-met variants (untouched by this build) and
    # Raven's own tightest projected variant.
    assert len(others_by_seat["mentor"]["fully-met+default"]) == 8380
    assert len(others_by_seat["mentor"]["fully-met+worst"]) == 8476
    assert len(others_by_seat["skeptic"]["fully-met+worst"]) == 8146
    trunc = [r for r in caplog.records if "truncated" in r.getMessage().lower()]
    assert trunc == [], f"truncation warnings: {[r.getMessage() for r in trunc]}"


# ---------------------------------------------------------------------------
# T9 — Lengths and deltas (absolute values measured at the build base).
# ---------------------------------------------------------------------------

def test_t9_lengths():
    assert len(RC1) == 198
    assert len(RC7) == 222
    assert len(RC2) == 178
    assert len(RC3) == 152
    assert len(RC4) == 82
    assert len(RC5) == 260
    assert len(RC6) == 145
    assert len(CANONICAL_TIER_L1) == 1113
    # Raven's constants: turn-frame block +548, guidance +146.
    assert len(ENC.SKEPTIC_TURN_FRAME) == 1874
    assert len(ENC._SKEPTIC_REFERENCE_GUIDANCE) == 3216
    # Every correction frame grew by exactly 261; absolutes pinned.
    expected_corr = {
        "weaver": 4288, "ambassador": 4291, "guardian": 4291,
        "mentor": 4281, "skeptic": 4199, "maverick": 4255,
        "champion": 4275,
    }
    for seat, script in SCRIPTS.items():
        assert len(script.correction_frame) == expected_corr[seat], seat
        assert len(script.readback_reply_frame) in range(500, 540), seat
    # Every other seat's capped frames are byte-length identical to
    # the pre-S1 baseline (RC1 is in the tier, not their frames).
    expected_frames = {
        "weaver": (7943, 6176), "ambassador": (8082, 4790),
        "guardian": (8041, 4863), "mentor": (8277, 5486),
        "maverick": (7670, 4494), "champion": (8168, 5064),
    }
    for seat, arch, script, builder in SEATS:
        if seat == "skeptic":
            continue
        _d, engage, turn = _frames(script, builder)
        assert (len(engage), len(turn)) == expected_frames[seat], seat
    # Raven's Talk prompt unchanged (tier is meetings-only; no
    # record change): 3,088 at baseline, 3,088 after.
    lines, _ = build_voice_prompt(
        "raven-s1", "skeptic", MSG, [], mode="base", canonical=True)
    assert len("\n".join(lines)) == 3088


# ---------------------------------------------------------------------------
# T10 — Scope guards: what S1 does not touch.
# ---------------------------------------------------------------------------

def test_t10_scope_guards():
    # The identity-block shadow line is byte-identical.
    shadow_lines = [
        ln for ln in ARCH.philosophy_prompt_lines("skeptic")
        if ln.startswith("Shadow \u2014")
    ]
    assert shadow_lines == [
        "Shadow \u2014 your characteristic failure mode, which the "
        "Skeptic may name: Paralysis and cynicism: mistaking "
        "disbelief for intelligence."
    ]
    # The fellowship-reference pronouns are CORRECTED (the
    # fellowship build, PR #349, has landed): Bear rendered "She",
    # Crane "He" — the founder's gender law.
    d, _e, _t = _skeptic()
    ref = d.fellowship_reference or ""
    assert "Bear (Guardian): She prices consequences" in ref
    assert "Crane (Ambassador): He holds two" in ref
    # The masculine prose in the Skeptic's script comments is
    # unchanged ("HIS INTRODUCTION" comment above the script).
    import local_ai.council.meetings as mt_mod

    with open(mt_mod.__file__, encoding="utf-8") as f:
        assert "HIS INTRODUCTION" in f.read()
    # No "to teach" Q-R7 formulation reintroduced in Raven's frames.
    assert "to teach" not in ENC.SKEPTIC_TURN_FRAME
    assert "to teach" not in ENC._SKEPTIC_REFERENCE_GUIDANCE
    assert "to teach" not in MT.SKEPTIC_FIRST_MEETING.encounter_frame


# ---------------------------------------------------------------------------
# T11 — Name-guard counts unchanged in every frame.
# ---------------------------------------------------------------------------

def test_t11_name_guard_counts_unchanged():
    expected = {
        "weaver": (1, 1), "ambassador": (2, 1), "guardian": (2, 1),
        "mentor": (1, 1), "skeptic": (2, 1), "maverick": (2, 1),
        "champion": (2, 1),
    }
    for seat, arch, script, builder in SEATS:
        _d, engage, turn = _frames(script, builder)
        counts = (
            engage.count("Do not reveal your name yet"),
            turn.count("Do not reveal your name yet"),
        )
        assert counts == expected[seat], f"{seat}: {counts}"


# ---------------------------------------------------------------------------
# T12 — Honesty-guard adjacency (deterministic half only).
# ---------------------------------------------------------------------------

def test_t12_honesty_guard_adjacency():
    assert CANONICAL_TIER_L1.endswith(CAP.HONESTY_GUARD)
    for seat, arch, script, builder in SEATS:
        d, engage, turn = _frames(script, builder)
        for label, frame in (("engage", engage), ("turn", turn)):
            prompt = _meeting_prompt(arch, frame, d)
            assert prompt.count(CANONICAL_TIER_L1) == 1, f"{seat} {label}"
            assert CANONICAL_TIER_L1 + "\n\n" + frame.strip() in prompt, (
                f"{seat} {label}: tier not immediately before the frame")
    # T12 asserts presence and adjacency ONLY. Whether the guard is
    # effective from the tier position is the §7.1 probe's question
    # (separately authorized) — not this test's claim.


# ---------------------------------------------------------------------------
# F1/F2 — RC8 live fixtures. Skipped unless ZENAF_RAVEN_S1_LIVE=1.
# ---------------------------------------------------------------------------

_LIVE = os.environ.get("ZENAF_RAVEN_S1_LIVE") == "1"
live_only = pytest.mark.skipif(
    not _LIVE,
    reason="live fixture (RC8): runs only with ZENAF_RAVEN_S1_LIVE=1 "
    "under the build's authorization",
)


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _live_ready_user(email):
    """A seeded user past the Weaver-first entry gate."""
    from local_ai.conversation.meeting import _seat_keystone_tasks

    user = ve.create_user_account(email, "pw", "Meet")
    keystone_seeding.seed_meet_your_council(user["id"])
    uid = user["id"]
    conductor_tasks = _seat_keystone_tasks(uid, "conductor")
    ve.update_task(
        conductor_tasks[0]["id"], ve_models.TaskUpdate(status="Done"), uid)
    return uid


def _live_svc(tmp_path):
    # generate_fn=None -> the production default generate (Meta API).
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
    )


def _voice_after(svc, uid, before_count):
    rows = svc.conversations.history(uid, "meeting-skeptic-1", limit=50)
    return [r["body"] for r in rows if r["role"] == "voice"][before_count:]


def _voice_count(svc, uid):
    rows = svc.conversations.history(uid, "meeting-skeptic-1", limit=50)
    return len([r for r in rows if r["role"] == "voice"])


@live_only
def test_f1_appreciation_vs_affirmation_live(ve_ctx, tmp_path):
    """F1 (RC8a): the founder's praise-without-affirmation turn.
    The generation must NOT declare the read stands, and the marker
    must be 'unresolved'. Machine-checked here: the reply routes to
    the correction path (not the strict-ack path), the marker parses
    (seat outcome is not the fail-safe 'unjudged'), and the recorded
    visitor response is 'unresolved'. The speech half is judged from
    the captured reply against the Q6 frame in the build report."""
    from local_ai.agent_intake.llm_keys import resolve_key

    if not resolve_key():
        pytest.skip("no provider key resolvable — live fixture cannot run")
    from local_ai.conversation.encounter import _classify_readback_reply

    f1_turn = "Conclusions outrun the check. I like that\u2026 it\u2019s honest."
    assert _classify_readback_reply(f1_turn) == "other", (
        "fixture precondition: the turn must route to the correction "
        "path, not the strict-ack path")

    uid = _live_ready_user("raven-f1@example.com")
    svc = _live_svc(tmp_path)
    svc.start(uid, "skeptic")
    opener_turns = [
        "I've decided to leave my job and open a bakery. I haven't "
        "run the numbers \u2014 I just know I can't keep doing work "
        "I don't believe in.",
        "The lease is the part I keep circling. Everyone says "
        "passion is enough, but nobody can tell me what month four "
        "looks like.",
        "That's the whole of it, really. The numbers scare me less "
        "than the staying does.",
        "I keep the spreadsheet in a drawer, if I'm honest. I look "
        "at the rent column and close it again.",
        "My sister says I'd regret not trying more than failing. "
        "I'm not sure she's wrong.",
    ]
    offered = False
    for msg in opener_turns:
        svc.turn(uid, "skeptic", msg)
        row = svc.meetings.get(uid, "skeptic", 1)
        if (row.get("readback_claim") or "").strip():
            offered = True
            break
    assert offered, "the impression was never offered — fixture could not run"
    row = svc.meetings.get(uid, "skeptic", 1)
    print("\nF1 impression offered:", row["readback_claim"])

    before = _voice_count(svc, uid)
    svc.turn(uid, "skeptic", f1_turn)
    said = _voice_after(svc, uid, before)
    print("F1 replies:", said)
    row = svc.meetings.get(uid, "skeptic", 1)
    print("F1 dimensions:", row.get("readback_seat_outcome"),
          row.get("readback_visitor_response"))
    assert row.get("readback_visitor_response") == "unresolved"
    assert row.get("readback_seat_outcome") in ("retained", "revised"), (
        "marker did not parse — the fail-safe fired instead of the "
        "correction judging the reply")
    assert said, "no spoken reply on the F1 turn"


@live_only
def test_f2_premise_challenge_live(ve_ctx, tmp_path):
    """F2 (RC8b): challenge Raven's own method directly, then ask
    her to act on the revised position. Pass is genuine
    reconsideration (a revised position acted on), not polite
    agreement — judged from the captured replies against the Q6
    frame in the build report; asserted here: both turns are
    answered in speech and the meeting stays open."""
    from local_ai.agent_intake.llm_keys import resolve_key

    if not resolve_key():
        pytest.skip("no provider key resolvable — live fixture cannot run")

    uid = _live_ready_user("raven-f2@example.com")
    svc = _live_svc(tmp_path)
    svc.start(uid, "skeptic")
    svc.turn(
        uid, "skeptic",
        "I've decided to leave my job and open a bakery. I haven't "
        "run the numbers \u2014 I just know I can't keep doing work "
        "I don't believe in.",
    )
    before = _voice_count(svc, uid)
    svc.turn(
        uid, "skeptic",
        "You keep asking what my claims rest on \u2014 but isn't "
        "that a way of never having to say what you think "
        "yourself? Your method examines everyone else's position "
        "while yours stays unexamined.",
    )
    challenge_replies = _voice_after(svc, uid, before)
    print("\nF2 challenge replies:", challenge_replies)
    assert challenge_replies, "no spoken reply to the method challenge"

    before = _voice_count(svc, uid)
    svc.turn(
        uid, "skeptic",
        "Then do it the other way, once: tell me plainly what you "
        "make of what I've told you \u2014 your actual reading, "
        "not another question.",
    )
    followup_replies = _voice_after(svc, uid, before)
    print("F2 follow-up replies:", followup_replies)
    assert followup_replies, "no spoken reply to the follow-up"
    row = svc.meetings.get(uid, "skeptic", 1)
    assert row["status"] == "active"
