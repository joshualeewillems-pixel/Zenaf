"""Fox story-rhyme cards carriage (rhyme-cards slice, 2026-11-20).

Covers: the seven curated story cards (local_ai/conversation/
rhyme_cards.py) riding in the Fox's ordinary-Talk prompt under the
SAME flag and the SAME assembly conditions as the rhyme-offer
guidance (ZENAF_FOX_RHYME_OFFER, default OFF): present exactly
once, immediately after the guidance, with the flag on; absent and
byte-identical with it off; withheld on the meeting path and
whenever the canonical tier rides; never served to another seat;
and outside the 9,000-char extra_instructions frame cap, arriving
whole. Content pins hold load-bearing verbatim strings from every
card so the carried texts cannot silently drift from the curated
source document.

No model calls anywhere here: deterministic prompt inspection, in
the pattern of tests/test_fox_rhyme_offer.py.
"""

from __future__ import annotations

import pytest

from local_ai.conversation import reply as R
from local_ai.conversation.reply import build_voice_prompt
from local_ai.conversation.rhyme_cards import RHYME_CARDS, rhyme_cards_block

ENV = "ZENAF_FOX_RHYME_OFFER"
GUIDANCE = R._FOX_RHYME_OFFER_GUIDANCE
BLOCK = rhyme_cards_block()
NO_TRAINING_PREFIX = "Note: this user has no published training data"

# Load-bearing verbatim strings, one or more per card, copied from
# the source document (zenaf-stock-root-repertoire-draft-2026-11-20).
CARD_MARKERS = {
    "Sisyphus": [
        "Homer gives no crime, no backstory, no explanation",
        "Pherecydes",
    ],
    "The miller's daughter (Rumpelstiltskin)": [
        "This card must never be used to suggest that the visitor's "
        "own gift secretly did the work",
        "cooking ladle",
    ],
    "Daedalus": [
        "King Cocalus takes up arms in his defence",
        "Perdix",
    ],
    "Icarus": [
        "do not state as source fact that flying low was equally fatal",
    ],
    "Bricks without straw": [
        "You are idle, you are idle",
    ],
    "Psyche's tasks": [
        "Proserpina's beauty",
        "infernal sleep",
    ],
    "Cinderella": [
        "recognizes the beautiful princess he had danced with",
        "Blood is in the shoe",
    ],
}


def _joined(lines):
    return "\n".join(lines)


def _fox_lines(**kwargs):
    kwargs.setdefault("mode", "base")
    return build_voice_prompt("u1", "maverick", "hello", [], **kwargs)[0]


# ---------------------------------------------------------------------------
# Card data
# ---------------------------------------------------------------------------


def test_seven_cards_in_order_with_four_parts_each():
    assert [name for name, _ in RHYME_CARDS] == list(CARD_MARKERS)
    for _name, text in RHYME_CARDS:
        assert "**What happens" in text
        assert "**What shape it makes:**" in text
        assert "**What might fit:**" in text
        assert "**Where it breaks:**" in text


def test_block_contains_every_card_marker():
    for markers in CARD_MARKERS.values():
        for marker in markers:
            assert marker in BLOCK, marker


def test_block_framing_and_size_recorded():
    # The block opens with its framing line (curated references, in
    # pencil) and carries the full seven cards (~18.1k chars). The
    # size pin is a drift alarm, not a budget: the block rides
    # outside the capped frame (see the frame test below).
    assert BLOCK.startswith("Story cards you carry")
    assert "curated references, in pencil" in BLOCK
    assert 17_500 < len(BLOCK) < 19_000


# ---------------------------------------------------------------------------
# Assembly gate (same flag, same conditions as the guidance)
# ---------------------------------------------------------------------------


def test_cards_absent_by_default_and_byte_identical(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    unset_lines = _fox_lines()
    monkeypatch.setenv(ENV, "0")
    off_lines = _fox_lines()
    assert BLOCK not in unset_lines
    assert BLOCK not in off_lines
    assert "Story cards you carry" not in _joined(unset_lines)
    assert unset_lines == off_lines


def test_cards_present_once_after_guidance_when_on(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    lines = _fox_lines()
    # Exactly once, as its own prompt line, immediately after the
    # guidance (one blank separator line between them).
    assert lines.count(BLOCK) == 1
    assert lines.count(GUIDANCE) == 1
    assert lines.index(BLOCK) == lines.index(GUIDANCE) + 2
    # And before the downstream no-training note.
    note_idx = next(
        i for i, line in enumerate(lines) if line.startswith(NO_TRAINING_PREFIX)
    )
    assert lines.index(BLOCK) < note_idx
    # The rest of the ordinary assembly is undisturbed.
    assert lines[-2] == "User: hello"
    assert lines[-1] == "Maverick:"


def test_cards_withheld_on_meeting_path(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    lines = _fox_lines(canonical=False)
    assert BLOCK not in lines
    assert "Story cards you carry" not in _joined(lines)


def test_cards_withheld_when_canonical_tier_rides(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    lines = _fox_lines(canonical_tier=True)
    assert BLOCK not in lines
    assert "Story cards you carry" not in _joined(lines)


@pytest.mark.parametrize(
    "seat", ["mentor", "champion", "guardian", "ambassador", "conductor", "skeptic"]
)
def test_cards_never_served_to_other_seats(monkeypatch, seat):
    monkeypatch.setenv(ENV, "1")
    lines, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
    assert BLOCK not in lines
    joined = _joined(lines)
    assert "Story cards you carry" not in joined
    assert "Proserpina's beauty" not in joined


# ---------------------------------------------------------------------------
# Frame budget: the cards ride outside the capped frame
# ---------------------------------------------------------------------------


def test_frame_cap_untouched_with_flag_on(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    assert R._EXTRA_INSTRUCTIONS_CAP == 9000
    lines = _fox_lines(extra_instructions="FRAME: " + "x" * 12000)
    # The frame is still capped at exactly 9,000...
    assert any(len(line) == R._EXTRA_INSTRUCTIONS_CAP for line in lines)
    assert ("x" * R._EXTRA_INSTRUCTIONS_CAP) not in _joined(lines)
    # ...and the whole cards block arrives anyway, outside the
    # frame — it is never the content lost to truncation.
    assert BLOCK in lines
