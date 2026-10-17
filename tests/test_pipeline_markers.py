"""Narrative-arc marker detection (heuristics, no network)."""

from __future__ import annotations

from local_ai.pipeline import markers
from local_ai.pipeline.markers import detect_markers, pick_suggestion

JOURNEY = (
    "I left my job back in March and started something of my own. The first "
    "months were hard — I failed twice, felt lost and overwhelmed by doubt. "
    "But I kept going, and I finally learned what I actually want from work. "
    "Now I feel grateful for the struggle; it made me stronger and wiser."
)
PUNCHLINE = (
    "I spent an hour crafting the perfect excuse for being late to the meeting, "
    "rehearsing it in the mirror twice. But then I checked my calendar. "
    "Plot twist: today is Saturday. I am hilarious and I love it."
)
EMOTIONAL = (
    "I love her so deeply it aches in my chest. My heart breaks and overflows "
    "at the very same time, tears of pure joy streaming down my face. I have "
    "never felt anything so incredibly overwhelming and tender and true."
)
VISUAL = (
    "The golden light fell across the red door of the old house, long shadows "
    "stretching behind the towering oak tree as the deep blue sky faded above "
    "the green hills. A mirror in the empty room caught the bright sunset."
)
PLAIN = (
    "Went to the store today. Bought milk and bread. The line was short. "
    "Came home and made lunch. Nothing much happened otherwise."
)


def _names(hits):
    return [h["marker"] for h in hits]


def test_heros_journey_fires():
    hits = detect_markers(JOURNEY)
    assert "heros_journey" in _names(hits)
    hit = next(h for h in hits if h["marker"] == "heros_journey")
    assert hit["modality"] == "story"
    assert "hero's journey" in hit["copy"]


def test_punchline_fires():
    hits = detect_markers(PUNCHLINE)
    assert "punchline" in _names(hits)
    hit = next(h for h in hits if h["marker"] == "punchline")
    assert hit["modality"] == "comic"
    assert "comic" in hit["copy"]


def test_emotional_charge_fires():
    hits = detect_markers(EMOTIONAL)
    assert "emotional_charge" in _names(hits)
    hit = next(h for h in hits if h["marker"] == "emotional_charge")
    assert hit["modality"] == "song"
    assert "song" in hit["copy"]


def test_visual_specificity_fires():
    hits = detect_markers(VISUAL)
    assert "visual_specificity" in _names(hits)
    hit = next(h for h in hits if h["marker"] == "visual_specificity")
    assert hit["modality"] == "image"


def test_plain_entry_fires_nothing():
    assert detect_markers(PLAIN) == []
    assert pick_suggestion(PLAIN) is None


def test_pick_suggestion_returns_best_first():
    hit = pick_suggestion(JOURNEY)
    assert hit is not None
    assert hit["marker"] == "heros_journey"


def test_low_precision_marker_is_skipped():
    def precision_of(marker):
        return 0.1 if marker == "heros_journey" else None

    hit = pick_suggestion(JOURNEY, precision_of=precision_of)
    # heros_journey suppressed; nothing else fires on this text
    assert hit is None


def test_high_precision_marker_still_fires():
    def precision_of(marker):
        return 0.9

    hit = pick_suggestion(JOURNEY, precision_of=precision_of)
    assert hit is not None
    assert hit["marker"] == "heros_journey"


def test_empty_text_safe():
    assert detect_markers("") == []
    assert pick_suggestion("") is None
