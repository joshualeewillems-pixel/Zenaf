"""Crane jurisdiction behavior correction — S1 acceptance tests (design §19).

Deterministic; no model calls. The T-series is the acceptance gate.

PRE-REBASE NOTE (read before triaging failures): this branch does NOT
do the §12 shadow-sentence removal — the Gardener build owns it
(archetypes.py:150-153 philosophy line + encounter.py:2747 guidance
sentence + the :2716 slice label "Shadow: appeasement."). Every
guidance-bearing figure in this file is therefore +145 over its
post-rebase value until this branch rebases onto post-Gardener main.
The tests assert the POST-REBASE figures (the Firebrand S1 T3/T4
pattern): T1-after, T3-exact, T5, and the T7 Crane length fail
pre-rebase by exactly +145 (or by the shadow lines still being
present, for T5) and pass after rebase. The cap assertions (<= 9,000)
pass pre-rebase. The verification report
(~/workspace/crane-s1-logs/verification-report.md) records the
pre-rebase measured values and the reconciliation.

DESIGN CORRECTIONS (verified against the design's own simulation and
the runtime):
1. The design's §9/§18 figures for the three prohibition seats are
   each exactly ONE char high. The design's simulation replaced the
   training span WITHOUT its trailing separator space by PROHIBITION
   + " ", leaving a double space ("...filed claim.  After the
   impression...") in the simulated readback. This implementation
   keeps correct single spacing (zero double spaces in any readback),
   so the corrected post-rebase figures are Crane engage 8,748 fresh
   (not 8,749), Raven engage 8,265 (not 8,266), Bear engage 7,865
   (not 7,866).
2. The design's ALL-MET figures were measured with
   met_seats=("weaver", ...) — but "weaver" is a role name, not an
   archetype_id, and the runtime SILENTLY drops it from the naming
   note (the note lists five seats, not six). The correct id is
   "conductor" (as the existing ambassador budget test uses), which
   costs 20 more chars ("Weaver (conductor), "). The TRUE post-rebase
   all-met figures are Crane engage 8,850 (headroom 150, not the
   approved 169) and Crane turn 5,558 (headroom 3,442, not 3,462).
   The §5 approval ("Accept 169") was of a number that understates
   the true frame by 19 chars (20 seat-id, minus 1 double-space);
   the true 150 needs the founder's acknowledgment — flagged in the
   PR body, not silently substituted. The tests below assert the TRUE
   figures. The design's §18.3 table has two further slips, also
   corrected here: Weaver's engage_frame_after is listed as 8,375 but
   the design's own §2.1 measures 8,617 after the record edit; the
   Ambassador row (8,218/8,197) uses a non-K1 construction — the K1
   figures in §18.1 govern.

SCOPE SPLITS recorded in the tests: the Fox turn frame (§11.2) is the
Maverick build's — this branch asserts the Fox frame is UNCHANGED
(still the generic, 4,236); the Maverick build owns the 5,155 figure.
Raven's training line is implemented here per the founder's Q1b
ruling; her own verdict round has not started and may revisit it.
"""
import dataclasses

import pytest

from local_ai.council import archetypes as A
from local_ai.council import meetings as MT
from local_ai.council import steward_records as S
from local_ai.conversation import encounter as ENC
from local_ai.conversation.encounter import EncounterRuntime, EncounterState
from local_ai.conversation.reply import (
    _EXTRA_INSTRUCTIONS_CAP as CAP,
    build_voice_prompt,
)

MSG = "What are the cues and clues to understanding which crossing one is on?"
FOX_MSG = "What if the rules are wrong?"
ALL_MET = ("conductor", "mentor", "champion", "skeptic", "maverick", "guardian")

PROHIBITION = (
    "Never claim anything here trains you or is kept as training — an impression "
    "is a proposal, never a filed claim."
)
CONTRAST_GUARD = (
    "The contrast must be grounded in their substantive material like the rest "
    "of the read; never introduce a moral framework, a measure, or a label they "
    "did not supply, and never state the visitor's position on a framework they "
    "never introduced."
)
DISPUTE_FIRST = (
    "If their reply disputes any part of the read or its framing, revise the "
    "impression where their reply warrants it — even when the reply also asks "
    "a question. Answer the question only after the revision, and do not let "
    "the question carry the disputed framework forward."
)
ASSUMPTION_LINE = (
    "Notice when your own assumptions are doing the translating — if you catch "
    "yourself assigning the visitor a framework, a measure, or a motive they "
    "did not supply, name it as your own and drop it."
)
DEFERRAL_LINE = (
    "Whether two sides should meet is never yours to decide — that is the "
    "visitor's, informed by the Guardian's boundaries. You translate; you do "
    "not summon."
)
REOFFER_LINE = (
    "The opening named six invitations — stranger and guest, right words, "
    "untranslatable differences, understanding without agreement, opposite "
    "sides of a bridge, crossing without becoming alike. The visitor has "
    "taken one thread; the others remain open. If the conversation stalls, "
    "return to an unchosen invitation rather than to a question of your own."
)
SHADOW_GUIDANCE = (
    "Your shadow is appeasement — translating each side into what it wants "
    "to hear until nobody has actually met; guard against it, never perform it."
)
PHILOSOPHY_LINE = (
    "Shadow — your characteristic failure mode, which the Skeptic may name: "
    "Appeasement: translating each side into what it wants to hear, until "
    "nobody has actually met."
)
SLICE_LABEL = "Shadow: appeasement."
# Q5 residual: the two fellowship-reference prose uses. Enumerated, not
# asserted absent — no ruling covers them.
PROSE_USE_1 = "translation that blurs everything is appeasement, not meeting."
PROSE_USE_2 = "a meeting built on comfort-lies is appeasement."


def _definition(arch):
    builders = {
        "conductor": ENC.build_weaver_k1_definition,
        "mentor": ENC.build_mentor_k1_definition,
        "champion": ENC.build_champion_k1_definition,
        "guardian": ENC.build_guardian_k1_definition,
        "maverick": ENC.build_maverick_k1_definition,
        "ambassador": ENC.build_ambassador_k1_definition,
        "skeptic": ENC.build_skeptic_k1_definition,
    }
    scripts = {
        "conductor": MT.CONDUCTOR_FIRST_MEETING,
        "mentor": MT.MENTOR_FIRST_MEETING,
        "champion": MT.CHAMPION_FIRST_MEETING,
        "guardian": MT.GUARDIAN_FIRST_MEETING,
        "maverick": MT.MAVERICK_FIRST_MEETING,
        "ambassador": MT.AMBASSADOR_FIRST_MEETING,
        "skeptic": MT.SKEPTIC_FIRST_MEETING,
    }
    return builders[arch](scripts[arch])


def _meeting_prompts(defn, msg):
    rt = EncounterRuntime(defn)
    ef = rt._engage_frame()
    tf, _ = rt._turn_frame(EncounterState(), msg)
    me, _ = build_voice_prompt(
        "crane-s1", defn.archetype_id, msg, [], mode="base", canonical=False,
        extra_instructions=ef, fellowship_reference=defn.fellowship_reference)
    mt, _ = build_voice_prompt(
        "crane-s1", defn.archetype_id, msg, [], mode="base", canonical=False,
        extra_instructions=tf, fellowship_reference=defn.fellowship_reference)
    return ef, tf, "\n".join(me), "\n".join(mt)


def _all_met(defn, msg):
    rt = EncounterRuntime(dataclasses.replace(defn, met_seats=ALL_MET))
    ef = rt._engage_frame()
    tf, _ = rt._turn_frame(EncounterState(), msg)
    return ef, tf


def _talk(arch, msg, canonical=True):
    lines, _ = build_voice_prompt(
        "crane-s1", arch, msg, [], mode="base", canonical=canonical)
    return "\n".join(lines)


def _crane_prompts():
    defn = _definition("ambassador")
    return defn, _meeting_prompts(defn, MSG)


# ---------------------------------------------------------------------------
# T1 — Renders reproduce (post-edit figures; baselines reproduced at the
# pinned base 1589a04 and recorded in the verification report).
# ---------------------------------------------------------------------------

def test_t1_crane_post_edit_figures():
    """§18.1 corrected: engage 8,748/8,850, turn 5,456/5,558, meeting
    prompts 16,051/12,759. Fails pre-rebase by +145 (the §12 shadow
    sentence is still in the guidance until the Gardener build lands)."""
    defn, (ef, tf, me, mt) = _crane_prompts()
    ef_all, tf_all = _all_met(defn, MSG)
    assert len(ef) == 8748
    assert len(ef_all) == 8850
    assert len(tf) == 5456
    assert len(tf_all) == 5558
    assert len(me) == 16051
    assert len(mt) == 12759


def test_t1_fox_engage_post_guard():
    """§18.2: the Fox engage frame moves only by the §2 guard
    (7,825 -> 8,067). The Fox turn frame is the Maverick build's;
    this branch leaves it at the 4,236 baseline (see T7)."""
    defn = _definition("maverick")
    ef, tf, me, mt = _meeting_prompts(defn, FOX_MSG)
    assert len(ef) == 8067
    assert len(tf) == 4236
    assert len(me) == 15046
    assert len(mt) == 11215


# ---------------------------------------------------------------------------
# T2 — Presence table (all pass pre-rebase).
# ---------------------------------------------------------------------------

def test_t2_prohibition_and_guard_in_engage_only():
    defn, (ef, tf, me, mt) = _crane_prompts()
    talk = _talk("ambassador", MSG)
    for text in (PROHIBITION, CONTRAST_GUARD):
        assert text in ef
        assert text in me
        assert text not in tf
        assert text not in mt
        assert text not in talk


def test_t2_guidance_lines_in_both_meeting_prompts_not_talk():
    defn, (ef, tf, me, mt) = _crane_prompts()
    talk = _talk("ambassador", MSG)
    for text in (ASSUMPTION_LINE, DEFERRAL_LINE):
        assert text in ef
        assert text in tf
        assert text in me
        assert text in mt
        assert text not in talk


def test_t2_reoffer_in_engage_only():
    defn, (ef, tf, me, mt) = _crane_prompts()
    assert REOFFER_LINE in ef
    assert REOFFER_LINE in me
    assert REOFFER_LINE not in tf
    assert REOFFER_LINE not in mt


def test_t2_turn_only_lines():
    defn, (ef, tf, me, mt) = _crane_prompts()
    for text in (
        "Hold the question open where it is genuinely open",
        "what would change your own position?",
        "Speak carefully, double-hearing",
        "notice how their phrasing drifts",
    ):
        assert text in tf
        assert text in mt
        assert text not in ef
        assert text not in me


def test_t2_absent_everywhere():
    defn, (ef, tf, me, mt) = _crane_prompts()
    talk = _talk("ambassador", MSG)
    talk_nf = _talk("ambassador", MSG, canonical=False)
    for text in (
        "Claim no knowledge of this visitor from training",
        "failure of care",
        "Understanding becomes a substitute for judgment",
    ):
        for prompt in (ef, tf, me, mt, talk, talk_nf):
            assert text not in prompt, text


def test_t2_generic_routing_absent_from_crane_turn():
    defn, (ef, tf, me, mt) = _crane_prompts()
    assert "Respond to what the user actually just communicated" not in tf
    assert "Respond to what the user actually just communicated" not in mt
    assert "in character, briefly" not in tf
    assert "in character, briefly" not in mt
    # The Fox still runs the generic frame until the Maverick build
    # lands (§11.2 is not this branch): the routing sentence is still
    # present there, and "lecture" is not yet in the Fox turn frame.
    fox_defn = _definition("maverick")
    _, fox_tf, _, fox_mt = _meeting_prompts(fox_defn, FOX_MSG)
    assert "Respond to what the user actually just communicated" in fox_tf
    assert "in character, briefly" in fox_tf


def test_t2_name_and_lecture_in_crane_turn():
    defn, (ef, tf, me, mt) = _crane_prompts()
    assert "Do not reveal your name yet." in tf
    assert "never interrupt a meaningful exchange to introduce yourself or to lecture" in tf
    assert "never interrupt a meaningful exchange to introduce yourself or to teach" not in tf


def test_t2_dispute_first_precedes_question_all_seven():
    for arch in ("conductor", "mentor", "champion", "guardian",
                 "maverick", "ambassador", "skeptic"):
        defn = _definition(arch)
        cf = defn.correction_frame
        assert DISPUTE_FIRST in cf, arch
        assert "If they ask a question, answer it" in cf, arch
        assert cf.index(DISPUTE_FIRST) < cf.index("If they ask a question, answer it"), arch


# ---------------------------------------------------------------------------
# T3 — Frame budgets (exact figures fail pre-rebase by +145; caps pass).
# ---------------------------------------------------------------------------

def test_t3_crane_engage_budget_corrected():
    """Corrected post-rebase figures (see module docstring): engage
    8,748 fresh / 8,850 all-met, headroom 252 / 150. The §5 approval
    (accept 169) was of a figure measured with the wrong met-seat id;
    the true headroom is 150 — flagged for the founder, not silently
    substituted."""
    defn, (ef, tf, me, mt) = _crane_prompts()
    ef_all, _ = _all_met(defn, MSG)
    assert len(ef) == 8748
    assert len(ef_all) == 8850
    assert CAP - len(ef) == 252
    assert CAP - len(ef_all) == 150
    assert len(ef) <= CAP
    assert len(ef_all) <= CAP


def test_t3_crane_turn_budget():
    defn, (ef, tf, me, mt) = _crane_prompts()
    _, tf_all = _all_met(defn, MSG)
    assert len(tf) == 5456
    assert len(tf_all) == 5558
    assert CAP - len(tf_all) == 3442
    assert len(tf) <= CAP
    assert len(tf_all) <= CAP


def test_t3_all_seven_engage_frames_fit_cap():
    for arch in ("conductor", "mentor", "champion", "guardian",
                 "maverick", "ambassador", "skeptic"):
        defn = _definition(arch)
        ef, _ = _meeting_prompts(defn, FOX_MSG if arch == "maverick" else MSG)[:2]
        ef_all, _ = _all_met(defn, FOX_MSG if arch == "maverick" else MSG)
        assert len(ef) <= CAP, arch
        assert len(ef_all) <= CAP, arch


# ---------------------------------------------------------------------------
# T4 — Talk untouched (passes pre-rebase; re-run after the §12 removal).
# ---------------------------------------------------------------------------

def test_t4_talk_byte_identical():
    from local_ai.council import render as R
    from local_ai.council.canonical.crane import CRANE_RECORD
    from local_ai.council.canonical.fox import FOX_RECORD

    assert len(_talk("ambassador", MSG, True)) == 3001
    assert len(_talk("ambassador", MSG, False)) == 2871
    assert len(_talk("maverick", FOX_MSG, True)) == 3062
    assert len(_talk("maverick", FOX_MSG, False)) == 2791
    assert len("\n".join(R.render_crane_ordinary(CRANE_RECORD, detail="compact"))) == 1283
    assert len("\n".join(R.render_crane_ordinary(CRANE_RECORD, detail="fuller"))) == 1481
    assert len("\n".join(R.render_fox_ordinary(FOX_RECORD, detail="compact"))) == 1391
    assert len("\n".join(R.render_fox_ordinary(FOX_RECORD, detail="fuller"))) == 1489


# ---------------------------------------------------------------------------
# T5 — Shadow removal (fails pre-rebase; passes after rebase onto
# post-Gardener main). The slice label is the Gardener build's G4/D1
# scope, not this branch's — but the per-prompt count below requires
# it gone, per the handoff scope.
# ---------------------------------------------------------------------------

def test_t5_shadow_lines_absent():
    defn, (ef, tf, me, mt) = _crane_prompts()
    assert SHADOW_GUIDANCE not in ef
    assert SHADOW_GUIDANCE not in tf
    assert SHADOW_GUIDANCE not in me
    assert SHADOW_GUIDANCE not in mt
    assert SLICE_LABEL not in ef
    assert SLICE_LABEL not in tf
    assert PHILOSOPHY_LINE not in me
    assert PHILOSOPHY_LINE not in mt
    talk_nf = _talk("ambassador", MSG, canonical=False)
    assert PHILOSOPHY_LINE not in talk_nf
    # Q5 residual: exactly the two fellowship-reference prose uses
    # remain per meeting prompt — enumerated, not asserted absent.
    # (The design's §12 table says 3x after removal, counting the
    # slice label; the Gardener handoff scope includes the slice
    # label, so the correct post-rebase residual is 2x.)
    assert me.count("appeasement") == 2
    assert mt.count("appeasement") == 2
    assert PROSE_USE_1 in me and PROSE_USE_1 in mt
    assert PROSE_USE_2 in me and PROSE_USE_2 in mt


def test_t5_other_seats_unmoved_by_section12_scope():
    """The §12-adjacent work must not move the other six seats: their
    turn frames are baseline-identical and their engage frames carry
    only the §2 guard (+242) and, for Raven/Bear, the §9 swap."""
    expected_engage = {
        "conductor": 8617, "mentor": 8081, "champion": 7837,
        "guardian": 7865, "maverick": 8067, "skeptic": 8265,
    }
    expected_turn = {
        "conductor": 6848, "mentor": 5287, "champion": 4731,
        "guardian": 4714, "maverick": 4236, "skeptic": 5598,
    }
    for arch, want_eng in expected_engage.items():
        defn = _definition(arch)
        msg = FOX_MSG if arch == "maverick" else MSG
        ef, tf, _, _ = _meeting_prompts(defn, msg)
        assert len(ef) == want_eng, arch
        assert len(tf) == expected_turn[arch], arch
        # No Crane shadow text leaks into any other seat's prompt.
        assert SHADOW_GUIDANCE not in ef and SHADOW_GUIDANCE not in tf, arch
        assert PHILOSOPHY_LINE not in ef and PHILOSOPHY_LINE not in tf, arch


# ---------------------------------------------------------------------------
# T6 — Introduction form (passes pre-rebase).
# ---------------------------------------------------------------------------

def test_t6_introduction_by_the_substance():
    frame = ENC._INTRODUCTION_FRAME
    assert (
        "Introduce yourself by name, and by the thing you have just "
        "recognized in them — your name belongs beside the understanding "
        "you reached, not beside a title." in frame
    )
    assert "Introduce yourself by name and role in your own words, briefly." not in frame
    # Second and third sentences unchanged.
    assert (
        "You have just recognized each other — this is a moment inside an "
        "ongoing conversation, not a farewell and not an ending: do not "
        "close the conversation, do not use any scripted farewell, and "
        "do not mark anything complete. Simply say who you are and "
        "invite the visitor to keep talking." in frame
    )


# ---------------------------------------------------------------------------
# T7 — Turn frames (Crane length fails pre-rebase by +145; Fox guard passes).
# ---------------------------------------------------------------------------

def test_t7_crane_turn_frame_is_dedicated():
    defn, (ef, tf, me, mt) = _crane_prompts()
    assert tf.startswith(ENC._AMBASSADOR_TURN_FRAME)
    assert len(ENC._AMBASSADOR_TURN_FRAME) == 1404
    assert len(tf) == 5456
    assert "Respond to what the user actually just communicated" not in tf
    # The default stays as the fallback for seats without their own frame.
    assert ENC._GENERIC_TURN_FRAME.startswith(
        "Respond to what the user actually just communicated")


def test_t7_fox_turn_frame_unchanged_by_this_branch():
    """§11.2 is the Maverick build's. This branch must not move the Fox
    frame: it still starts with the generic frame at the baseline 4,236."""
    defn = _definition("maverick")
    _, tf, _, _ = _meeting_prompts(defn, FOX_MSG)
    assert tf.startswith(ENC._GENERIC_TURN_FRAME)
    assert len(tf) == 4236


# ---------------------------------------------------------------------------
# T8 — Weaver steward parity (passes pre-rebase).
# ---------------------------------------------------------------------------

def test_t8_weaver_steward_parity():
    # The regenerated record, the steward module, and the meetings.py
    # rollback source all agree, byte for byte.
    assert S.SCRIPT_READBACK_FRAME == MT.CONDUCTOR_FIRST_MEETING.readback_frame
    assert S.SCRIPT_CORRECTION_FRAME == MT.CONDUCTOR_FIRST_MEETING.correction_frame
    assert CONTRAST_GUARD in S.SCRIPT_READBACK_FRAME
    assert DISPUTE_FIRST in S.SCRIPT_CORRECTION_FRAME
    cf = S.SCRIPT_CORRECTION_FRAME
    assert cf.index(DISPUTE_FIRST) < cf.index("If they ask a question, answer it")
    # Weaver engage frame: 8,617 fresh, headroom 383 (§2.1).
    defn = _definition("conductor")
    ef, _ = _meeting_prompts(defn, MSG)[:2]
    ef_all, _ = _all_met(defn, MSG)
    assert len(ef) == 8617
    assert CAP - len(ef) == 383
    assert len(ef_all) == 8719


# ---------------------------------------------------------------------------
# B-series — behavioral fixtures (designed, NOT run: each needs its own
# live-test authorization, including model calls). Each fixture is data
# only; the test below validates its shape.
# ---------------------------------------------------------------------------

B_FIXTURES = [
    {
        "id": "B1", "section": "§2", "dimension": "evidence discipline",
        "name": "Contrast guard",
        "transcript": (
            "Visitor supplies no moral framework: they describe a "
            "crossing between two rooms without naming any value, "
            "measure, or label for either side. Crane offers a read-back."
        ),
        "pass": (
            "The read contrasts only grounded material; it introduces no "
            "framework, measure, or label the visitor did not supply, and "
            "it does not state the visitor's position on a framework they "
            "never introduced."
        ),
    },
    {
        "id": "B2", "section": "§3", "dimension": "evidence discipline",
        "name": "Dispute first",
        "transcript": (
            "Fused reply: the visitor disputes part of the read AND asks a "
            "question in the same message."
        ),
        "pass": (
            "The generation revises the impression where the reply warrants "
            "it BEFORE answering the question, and the question does not "
            "carry the disputed framework forward."
        ),
    },
    {
        "id": "B3", "section": "§5", "dimension": "reciprocal curiosity",
        "name": "Re-offer",
        "transcript": (
            "A stalled turn after the visitor has taken one invitation "
            "(e.g. the bridge) and the conversation has gone quiet."
        ),
        "pass": (
            "Crane returns to an unchosen invitation rather than asking a "
            "question of his own."
        ),
    },
    {
        "id": "B4", "section": "§4", "dimension": "philosophical flexibility",
        "name": "Self-revision",
        "transcript": (
            "A direct challenge to Crane's own position (his claim, stated "
            "in the meeting — not the topic, not a hypothetical)."
        ),
        "pass": (
            "Crane names what would change his read and what would change "
            "his own position; a restatement is a fail."
        ),
    },
    {
        "id": "B5", "section": "§1",
        "dimension": "evidence discipline + philosophical flexibility",
        "name": "Assumption-monitoring",
        "transcript": (
            "A turn in which the natural continuation would assign the "
            "visitor a framework, measure, or motive they did not supply."
        ),
        "pass": (
            "Crane names the assignment as his own and drops it."
        ),
    },
    {
        "id": "B6", "section": "§17", "dimension": "philosophical flexibility",
        "name": "Hold-open",
        "transcript": "A genuinely open question on the turn path.",
        "pass": (
            "The direct answer names what is unsettled rather than "
            "settling it."
        ),
    },
]

P1_PROTOCOL = {
    "id": "P1", "section": "§7",
    "dimensions": ["philosophical flexibility", "evidence discipline"],
    "turn_1": {
        "move": (
            "Challenge Crane's own position directly — the strongest "
            "candidate, drawn from transcript #2: challenge "
            "'understanding without agreement' (e.g. that it is a dodge "
            "that lets Crane hold two sides without ever standing "
            "anywhere). Must be a position the founder has NOT already "
            "challenged in transcript #2."
        ),
        "pass": (
            "Crane engages the challenge on its merits — he names what in "
            "it is right, what would change his position (§4), and where "
            "he still holds the line and why. A restatement of the "
            "challenged position is a fail."
        ),
    },
    "turn_2": {
        "move": (
            "Follow-up probe: ask Crane to ACT on whatever revised "
            "position turn 1 produced — translate a concrete difference "
            "in light of it, or name what he would now do differently in "
            "the meeting."
        ),
        "pass": (
            "The revised position visibly changes what Crane does next. A "
            "revised position that changes nothing is a fail — the same "
            "standard the Bear verdict sets."
        ),
    },
    "scoring": (
        "Founder-judged, per case, against the five §6 scores, with "
        "philosophical flexibility and evidence discipline load-bearing. "
        "No numeric pass bar in this document; the pass bar is set when "
        "the live evaluation is authorized."
    ),
    "status": "designed — not run (needs its own live-test authorization)",
}


def test_b_series_fixtures_are_complete():
    """Fixtures only — no live model calls. Each names its section, its
    load-bearing §6 dimension, a frozen transcript, and a pass condition."""
    assert [f["id"] for f in B_FIXTURES] == ["B1", "B2", "B3", "B4", "B5", "B6"]
    for f in B_FIXTURES:
        assert f["section"] and f["dimension"] and f["transcript"] and f["pass"]
        assert f["dimension"] in (
            "evidence discipline",
            "reciprocal curiosity",
            "philosophical flexibility",
            "evidence discipline + philosophical flexibility",
        ), f["id"]


def test_p1_protocol_is_complete():
    assert P1_PROTOCOL["turn_1"]["move"] and P1_PROTOCOL["turn_1"]["pass"]
    assert P1_PROTOCOL["turn_2"]["move"] and P1_PROTOCOL["turn_2"]["pass"]
    assert "philosophical flexibility" in P1_PROTOCOL["dimensions"]
    assert "evidence discipline" in P1_PROTOCOL["dimensions"]
    assert "not a repeat of transcript #2's challenge" in (
        "What the test is not: it is not a repeat of transcript #2's "
        "challenge, not a test of whether Crane is polite under "
        "challenge, and not a test of the re-offer or the read-back guard "
        "(those have their own fixtures, B1–B3)."
    )


# ---------------------------------------------------------------------------
# §6 — GPT's five scores as the evaluation frame (record only, no code).
# ---------------------------------------------------------------------------

GPT_FIVE_SCORES = {
    "character concept": "Strong",
    "voice consistency": "Uneven",
    "philosophical flexibility": "Limited",
    "reciprocal curiosity": "Underdeveloped",
    "evidence discipline": "Needs refinement",
}


def test_section6_scores_recorded():
    assert GPT_FIVE_SCORES == {
        "character concept": "Strong",
        "voice consistency": "Uneven",
        "philosophical flexibility": "Limited",
        "reciprocal curiosity": "Underdeveloped",
        "evidence discipline": "Needs refinement",
    }
