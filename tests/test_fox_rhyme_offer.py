"""Fox narrative-rhyme offer discipline (rhyme-offer slice, 2026-11-20).

Covers: the ZENAF_FOX_RHYME_OFFER flag reader (default OFF in every
environment, explicit env wins, read per call), the prompt-assembly
gate (guidance present on ordinary Fox Talk with the flag on, absent
with it off, withheld on the meeting path and whenever the canonical
tier rides, never served to another seat), the frame-budget
invariant (the guidance rides OUTSIDE the capped extra_instructions
frame, exactly like _BEAR_FLOW_LOOP_GUIDANCE, so the 9,000-char cap
is untouched), and content pins on the discipline's load-bearing
fences so the text cannot silently soften.

No model calls anywhere here: every test is deterministic prompt
inspection, in the pattern of tests/test_fox_canonical.py.
"""

from __future__ import annotations

import pytest

from local_ai.conversation import reply as R
from local_ai.conversation.reply import build_voice_prompt

ENV = "ZENAF_FOX_RHYME_OFFER"
GUIDANCE = R._FOX_RHYME_OFFER_GUIDANCE
NO_TRAINING_PREFIX = "Note: this user has no published training data"


def _joined(lines):
    return "\n".join(lines)


def _fox_lines(**kwargs):
    kwargs.setdefault("mode", "base")
    return build_voice_prompt("u1", "maverick", "hello", [], **kwargs)[0]


# ---------------------------------------------------------------------------
# Flag reader
# ---------------------------------------------------------------------------


def test_flag_defaults_off_when_env_unset(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert R.fox_rhyme_offer_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", " TRUE ", "On"])
def test_flag_explicit_on_values(monkeypatch, value):
    monkeypatch.setenv(ENV, value)
    assert R.fox_rhyme_offer_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "2"])
def test_flag_explicit_off_values(monkeypatch, value):
    monkeypatch.setenv(ENV, value)
    assert R.fox_rhyme_offer_enabled() is False


# ---------------------------------------------------------------------------
# Assembly gate
# ---------------------------------------------------------------------------


def test_guidance_absent_by_default_and_byte_identical(monkeypatch):
    # Env unset (the default everywhere) and env explicitly off must
    # both produce the exact pre-slice prompt: no guidance line, and
    # no other drift.
    monkeypatch.delenv(ENV, raising=False)
    unset_lines = _fox_lines()
    monkeypatch.setenv(ENV, "0")
    off_lines = _fox_lines()
    assert GUIDANCE not in unset_lines
    assert GUIDANCE not in off_lines
    assert unset_lines == off_lines


def test_guidance_present_once_and_positioned_when_on(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    lines = _fox_lines()
    # Exactly once, as its own prompt line.
    assert lines.count(GUIDANCE) == 1
    # It rides after the character block and before the downstream
    # no-training note (the _BEAR_FLOW_LOOP_GUIDANCE slot).
    note_idx = next(
        i for i, line in enumerate(lines) if line.startswith(NO_TRAINING_PREFIX)
    )
    assert lines.index(GUIDANCE) < note_idx
    # The rest of the ordinary assembly is undisturbed.
    assert lines[-2] == "User: hello"
    assert lines[-1] == "Maverick:"


def test_guidance_withheld_on_meeting_path(monkeypatch):
    # Meeting turns (canonical=False) never see the discipline, even
    # with the flag on.
    monkeypatch.setenv(ENV, "1")
    lines = _fox_lines(canonical=False)
    assert GUIDANCE not in lines


def test_guidance_withheld_when_canonical_tier_rides(monkeypatch):
    # A converged Fox meeting may run canonical=True under WI-2; the
    # canonical tier is the meeting caller's signal, and the
    # discipline is ordinary-Talk guidance, so it is withheld.
    monkeypatch.setenv(ENV, "1")
    lines = _fox_lines(canonical_tier=True)
    assert GUIDANCE not in lines


@pytest.mark.parametrize(
    "seat", ["mentor", "champion", "guardian", "ambassador", "conductor", "skeptic"]
)
def test_guidance_never_served_to_other_seats(monkeypatch, seat):
    monkeypatch.setenv(ENV, "1")
    lines, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
    assert GUIDANCE not in lines
    assert "Story rhymes" not in _joined(lines)


# ---------------------------------------------------------------------------
# Frame budget: the guidance rides outside the capped frame
# ---------------------------------------------------------------------------


def test_frame_cap_untouched_with_flag_on(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    assert R._EXTRA_INSTRUCTIONS_CAP == 9000
    lines = _fox_lines(extra_instructions="FRAME: " + "x" * 12000)
    # The frame is still capped at exactly 9,000...
    assert any(len(line) == R._EXTRA_INSTRUCTIONS_CAP for line in lines)
    assert ("x" * R._EXTRA_INSTRUCTIONS_CAP) not in _joined(lines)
    # ...and the guidance arrives whole, outside the frame — it is
    # never the content lost to truncation.
    assert GUIDANCE in lines


def test_guidance_size_recorded():
    # The discipline text is prompt-local guidance on the
    # _BEAR_FLOW_LOOP_GUIDANCE scale (~1.1k chars), NOT frame
    # content: it consumes none of the 9,000-char frame budget.
    assert 900 < len(GUIDANCE) < 1400


# ---------------------------------------------------------------------------
# Content fences (the founder's formal instruction, 2026-11-20)
# ---------------------------------------------------------------------------


def test_discipline_fences_pinned():
    # Provisional, first-person, rejectable (ground-never-presume).
    assert '"This reminds me of..."' in GUIDANCE
    assert "wholly theirs to refuse" in GUIDANCE
    # Fit AND failure, every offer.
    assert "names where the rhyme fits AND where it breaks" in GUIDANCE
    # Multiple competing parallels, never ranked.
    assert "unranked" in GUIDANCE
    # No invented progression; a story's next chapter is never the
    # visitor's future.
    assert "Never invent a progression" in GUIDANCE
    assert "never let a story's next chapter pose as their future" in GUIDANCE
    # Abstention: never coin a story-name for a plain fact.
    assert "never coin" in GUIDANCE
    assert "a story-name for a plain fact" in GUIDANCE
    # Diffusion: imagery carried forward and blended, not swapped.
    assert "carry your images forward" in GUIDANCE
    assert "blend and settle" in GUIDANCE
    # The repertoire is real stories, named as examples.
    assert "Sisyphus" in GUIDANCE
    assert "miller's daughter" in GUIDANCE
