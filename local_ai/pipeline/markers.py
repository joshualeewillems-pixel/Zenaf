"""Narrative-arc marker detection — the nudge system that never nags.

Pure heuristics (deterministic, no LLM, ~free). Each marker scores 0..1;
a marker fires when its score clears its threshold. The nudge is always
specific to the modality the markers point at — specificity is the
anti-nagging mechanism (spec §2).

Markers:
  heros_journey      -> "story"  (departure / struggle / return phases)
  punchline          -> "comic"  (setup + twist/contrast, humor signals)
  emotional_charge   -> "song"   (emotion lexicon density, intensifiers)
  visual_specificity -> "image"  (concrete visual nouns, color, spatial words)

A marker with measured precision < PRECISION_FLOOR (after enough
suggestions) stops firing — the detector tunes itself from dismissals.
"""

from __future__ import annotations

import re
from typing import Any

# Marker -> (threshold, modality, suggestion copy)
MARKERS: dict[str, dict[str, Any]] = {
    "heros_journey": {
        "threshold": 0.6,
        "modality": "story",
        "copy": "This follows a hero's journey — want to make it a story?",
    },
    "punchline": {
        "threshold": 0.55,
        "modality": "comic",
        "copy": "This would make a hilarious comic.",
    },
    "emotional_charge": {
        "threshold": 0.6,
        "modality": "song",
        "copy": "There's a lot of emotion here — this would make a beautiful song.",
    },
    "visual_specificity": {
        "threshold": 0.6,
        "modality": "image",
        "copy": "This would make a striking image.",
    },
}

#: Markers with measured precision below this (after MIN_SUGGESTIONS_FOR_STATS
#: suggestions) stop firing.
PRECISION_FLOOR = 0.25
MIN_SUGGESTIONS_FOR_STATS = 5

_DEPARTURE = (
    "left", "quit", "started", "began", "decided", "journey", "first time",
    "new chapter", "turning point", "crossroads", "leaving", "embarked",
)
_STRUGGLE = (
    "struggle", "hard", "difficult", "failed", "afraid", "scared", "doubt",
    "pain", "lost", "stuck", "battle", "fight", "overwhelmed", "anxious",
    "challenge", "obstacle",
)
_RETURN = (
    "learned", "realized", "finally", "now i", "understand", "home",
    "grateful", "peace", "accept", "stronger", "wiser", "arrived",
)
_HUMOR = (
    "haha", "lol", "lmao", "funny", "hilarious", "joke", "plot twist",
    "punchline", "ironic", "ironically", "absurd", "ridiculous",
)
_CONTRAST = (
    "but then", "however", "instead", "plot twist", "turns out",
    "little did", "or so i thought", "of course",
)
_EMOTION = (
    "love", "grief", "joy", "anger", "angry", "fear", "tears", "crying",
    "cried", "heart", "soul", "ache", "longing", "hope", "despair",
    "euphoria", "rage", "tender", "devastat", "overjoyed", "heartbreak",
    "miss ", "missing",
)
_INTENSIFIERS = (
    "so ", "very", "incredibly", "deeply", "utterly", "completely",
    "overwhelming", "intense",
)
_VISUAL_NOUNS = (
    "light", "shadow", "color", "red", "blue", "green", "gold", "golden",
    "dark", "bright", "sky", "sea", "ocean", "tree", "trees", "mountain",
    "face", "eyes", "hands", "room", "street", "city", "sunset", "sunrise",
    "rain", "snow", "fire", "mirror", "window", "door", "garden", "forest",
    "river", "bridge", "photograph", "picture", "painting", "canvas",
)
_SPATIAL = (
    "above", "below", "behind", "beside", "across", "through", "between",
    "towering", "tiny", "vast", "empty", "crowded",
)


def _contains_any(text: str, words: tuple[str, ...]) -> int:
    return sum(1 for w in words if w in text)


def _score_heros_journey(text: str) -> float:
    """Coverage of the three phases: departure, struggle, return."""
    phases = [
        _contains_any(text, _DEPARTURE) > 0,
        _contains_any(text, _STRUGGLE) > 0,
        _contains_any(text, _RETURN) > 0,
    ]
    covered = sum(phases)
    if covered < 2:
        return 0.0
    # 2 phases -> 0.65, 3 phases -> 1.0 (plus a length sanity check)
    words = len(text.split())
    if words < 40:
        return 0.0
    return 0.65 if covered == 2 else 1.0


def _score_punchline(text: str) -> float:
    humor = _contains_any(text, _HUMOR)
    contrast = _contains_any(text, _CONTRAST)
    score = 0.0
    if humor:
        score += 0.45
    if contrast:
        score += 0.35
    # Short punchy closer: last sentence under 12 words ending with ! or .
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if sentences and len(sentences[-1].split()) <= 12 and len(sentences) >= 3:
        score += 0.2
    return min(1.0, score)


def _score_emotional_charge(text: str) -> float:
    words = text.split()
    if not words:
        return 0.0
    n = len(words)
    emotion_hits = _contains_any(text, _EMOTION)
    intensifier_hits = _contains_any(text, _INTENSIFIERS)
    exclamations = text.count("!")
    # Density-based: emotion words per 100 words, capped.
    density = min(1.0, (emotion_hits / max(n, 1)) * 25)
    score = density * 0.6
    score += min(0.25, intensifier_hits * 0.08)
    score += min(0.15, exclamations * 0.05)
    # Needs a minimum length to be a song, not a status update.
    if n < 40:
        score *= 0.5
    return min(1.0, score)


def _score_visual_specificity(text: str) -> float:
    words = text.split()
    if not words:
        return 0.0
    n = len(words)
    visual_hits = _contains_any(text, _VISUAL_NOUNS)
    spatial_hits = _contains_any(text, _SPATIAL)
    density = min(1.0, ((visual_hits + spatial_hits) / max(n, 1)) * 18)
    if n < 40:
        density *= 0.5
    return min(1.0, density)


_SCORERS = {
    "heros_journey": _score_heros_journey,
    "punchline": _score_punchline,
    "emotional_charge": _score_emotional_charge,
    "visual_specificity": _score_visual_specificity,
}


def detect_markers(text: str) -> list[dict[str, Any]]:
    """Score all markers; return those above threshold, best first.

    Each result: {marker, score, modality, copy}.
    """
    lowered = (text or "").lower()
    fired = []
    for marker, scorer in _SCORERS.items():
        score = scorer(lowered)
        meta = MARKERS[marker]
        if score >= meta["threshold"]:
            fired.append({
                "marker": marker,
                "score": round(score, 3),
                "modality": meta["modality"],
                "copy": meta["copy"],
            })
    fired.sort(key=lambda m: m["score"], reverse=True)
    return fired


def pick_suggestion(
    text: str,
    *,
    precision_of: Any = None,
) -> dict[str, Any] | None:
    """The single best suggestion for an entry, or None.

    `precision_of` is an optional callable marker -> float | None (measured
    precision); markers below PRECISION_FLOOR with enough data are skipped.
    """
    for hit in detect_markers(text):
        if precision_of is not None:
            precision = precision_of(hit["marker"])
            if precision is not None and precision < PRECISION_FLOOR:
                continue
        return hit
    return None
