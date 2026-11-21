"""Shared reference carriage — seat-general scope (carriage-general, 2026-11-20).

The founder's architectural correction made the story-reference
repertoire Fellowship-wide (one shared archive; PR #398/#399 had
carried it Fox-only), and the pacing refinement rewrote the
guidance as one SHARED text: references are vocabulary, not
obligation — silent or passing by default, claim-bound by the
cards, disclosed progressively. This build generalizes the
carriage to the two-seat test scope (maverick + skeptic) behind
the same default-OFF flag (ZENAF_FOX_RHYME_OFFER; the name is
historical — the staging secret exists under it).

Covers: the eligible-seat scope pin; byte-exact pins of the shared
guidance and the Fox-only addendum (founder-approved texts,
2026-11-20 — they may not be paraphrased); the carriage helper's
gates; the skeptic's assembly (guidance + cards exactly once, in
order, outside the frame cap, with the flag on; absent and
byte-identical with it off; withheld on the meeting path and
whenever the canonical tier rides); the other five seats never
receiving any carriage part; and the Fox addendum riding after
the cards for the Fox only.

No model calls anywhere here: deterministic prompt inspection, in
the pattern of tests/test_fox_rhyme_offer.py.
"""

from __future__ import annotations

import pytest

from local_ai.conversation import reply as R
from local_ai.conversation.reply import build_voice_prompt
from local_ai.conversation.rhyme_cards import rhyme_cards_block

ENV = "ZENAF_FOX_RHYME_OFFER"
GUIDANCE = R._SHARED_REFERENCE_GUIDANCE
ADDENDUM = R._FOX_REFERENCE_ADDENDUM
BLOCK = rhyme_cards_block()
NO_TRAINING_PREFIX = "Note: this user has no published training data"

# Founder-approved texts (2026-11-20), pinned byte-exact: the
# pacing direction is a ruling, not a draft — any wording change
# must arrive as a new ruling, not an edit that slips past review.
EXPECTED_GUIDANCE = "Shared story references — a shelf the whole Fellowship may draw from. The cards below are curated references, in pencil: faithful accounts with their limits attached. They are vocabulary, not obligation. Most turns, let them work silently, or surface as a passing allusion — no naming, no explaining. Offer more — a brief comparison, an explored analogy — only when it genuinely serves what the visitor is living, and save the full examination for when they ask, or a distinction truly changes the meaning. What a card says binds what you may claim: never assert what its account does not support, never smooth its variants into one story, and correct a misunderstanding plainly when one arises. When no card adds anything, simply answer — do not announce that nothing fits. Prefer developing an image already alive in the conversation over introducing a new reference. Never invent a progression: a story's next chapter is not the visitor's future. Several parallels may rest on the table at once, unranked; the visitor alone adopts one. Speak of them in your own voice, at your own frequency — the shelf is shared; the telling is yours."
EXPECTED_ADDENDUM = 'Your own way with them: paint first when painting serves — surface metaphor early, and as the conversation deepens carry your images forward, let them blend and settle toward the one thing, instead of swapping in a new one each turn.'

OTHER_SEATS = ["mentor", "champion", "guardian", "ambassador", "conductor"]


def _joined(lines):
    return "\n".join(lines)


def _lines(seat, **kwargs):
    kwargs.setdefault("mode", "base")
    return build_voice_prompt("u1", seat, "hello", [], **kwargs)[0]


# ---------------------------------------------------------------------------
# Scope + exact texts
# ---------------------------------------------------------------------------


def test_carriage_scope_is_the_two_seat_test_scope():
    assert R._REFERENCE_CARRIAGE_SEATS == frozenset({"maverick", "skeptic"})


def test_shared_guidance_text_is_byte_exact():
    assert GUIDANCE == EXPECTED_GUIDANCE


def test_fox_addendum_text_is_byte_exact():
    assert ADDENDUM == EXPECTED_ADDENDUM


# ---------------------------------------------------------------------------
# The helper's gates (unit level)
# ---------------------------------------------------------------------------


def test_helper_returns_nothing_with_flag_off(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    for seat in ("maverick", "skeptic"):
        assert (
            R._reference_carriage_lines(
                seat, seat_canonical=True, canonical_tier=False
            )
            == []
        )


def test_helper_returns_nothing_for_ineligible_seat(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    for seat in OTHER_SEATS:
        assert (
            R._reference_carriage_lines(
                seat, seat_canonical=True, canonical_tier=False
            )
            == []
        )


def test_helper_returns_nothing_without_canonical_assembly(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    for seat in ("maverick", "skeptic"):
        assert (
            R._reference_carriage_lines(
                seat, seat_canonical=False, canonical_tier=False
            )
            == []
        )


def test_helper_returns_nothing_when_canonical_tier_rides(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    for seat in ("maverick", "skeptic"):
        assert (
            R._reference_carriage_lines(
                seat, seat_canonical=True, canonical_tier=True
            )
            == []
        )


def test_helper_line_shape_and_order(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    # Skeptic: guidance, then cards — nothing else.
    assert R._reference_carriage_lines(
        "skeptic", seat_canonical=True, canonical_tier=False
    ) == ["", GUIDANCE, "", BLOCK]
    # Fox: guidance, cards, then the Fox addendum after the cards.
    assert R._reference_carriage_lines(
        "maverick", seat_canonical=True, canonical_tier=False
    ) == ["", GUIDANCE, "", BLOCK, "", ADDENDUM]


# ---------------------------------------------------------------------------
# Skeptic assembly (Severine — the second seat of the test scope)
# ---------------------------------------------------------------------------


def test_skeptic_carriage_present_once_in_order_when_on(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    lines = _lines("skeptic")
    assert lines.count(GUIDANCE) == 1
    assert lines.count(BLOCK) == 1
    # Cards immediately after the guidance (one blank separator).
    assert lines.index(BLOCK) == lines.index(GUIDANCE) + 2
    # The carriage rides before the downstream no-training note.
    note_idx = next(
        i for i, line in enumerate(lines) if line.startswith(NO_TRAINING_PREFIX)
    )
    assert lines.index(BLOCK) < note_idx
    # The rest of the ordinary assembly is undisturbed.
    assert lines[-2] == "User: hello"
    assert lines[-1].endswith(":")


def test_skeptic_absent_by_default_and_byte_identical(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    unset_lines = _lines("skeptic")
    monkeypatch.setenv(ENV, "0")
    off_lines = _lines("skeptic")
    assert GUIDANCE not in unset_lines
    assert BLOCK not in unset_lines
    assert "Story cards you carry" not in _joined(unset_lines)
    assert unset_lines == off_lines


def test_skeptic_withheld_on_meeting_path(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    lines = _lines("skeptic", canonical=False)
    assert GUIDANCE not in lines
    assert BLOCK not in lines
    assert "Story cards you carry" not in _joined(lines)


def test_skeptic_withheld_when_canonical_tier_rides(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    lines = _lines("skeptic", canonical_tier=True)
    assert GUIDANCE not in lines
    assert BLOCK not in lines
    assert "Story cards you carry" not in _joined(lines)


def test_skeptic_frame_cap_untouched_with_flag_on(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    assert R._EXTRA_INSTRUCTIONS_CAP == 9000
    lines = _lines("skeptic", extra_instructions="FRAME: " + "x" * 12000)
    # The frame is still capped at exactly 9,000...
    assert any(len(line) == R._EXTRA_INSTRUCTIONS_CAP for line in lines)
    assert ("x" * R._EXTRA_INSTRUCTIONS_CAP) not in _joined(lines)
    # ...and the guidance and the whole cards block arrive anyway,
    # outside the frame.
    assert GUIDANCE in lines
    assert BLOCK in lines


# ---------------------------------------------------------------------------
# The other five seats never receive any part of the carriage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seat", OTHER_SEATS)
def test_other_seats_never_receive_carriage(monkeypatch, seat):
    monkeypatch.setenv(ENV, "1")
    lines = _lines(seat)
    assert GUIDANCE not in lines
    assert BLOCK not in lines
    assert ADDENDUM not in lines
    joined = _joined(lines)
    assert "a shelf the whole Fellowship may draw from" not in joined
    assert "Story cards you carry" not in joined
    assert "Your own way with them" not in joined


# ---------------------------------------------------------------------------
# The Fox addendum: Fox only, after the cards
# ---------------------------------------------------------------------------


def test_fox_addendum_present_after_cards_for_maverick(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    lines = _lines("maverick")
    assert lines.count(ADDENDUM) == 1
    # Immediately after the cards block (one blank separator).
    assert lines.index(ADDENDUM) == lines.index(BLOCK) + 2


def test_fox_addendum_absent_for_skeptic(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    lines = _lines("skeptic")
    assert ADDENDUM not in lines
    assert "Your own way with them" not in _joined(lines)


def test_fox_addendum_absent_with_flag_off(monkeypatch):
    monkeypatch.setenv(ENV, "0")
    lines = _lines("maverick")
    assert ADDENDUM not in lines
    assert "Your own way with them" not in _joined(lines)
