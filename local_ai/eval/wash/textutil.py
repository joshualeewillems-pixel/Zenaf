"""Deterministic text helpers for the wash harness.

Everything here is pure and deterministic: normalization for frozen-judgment
matching, Jaccard word similarity for the dedupe check, and speaker-prefix
resolution for the attribution check. No model, no network, no state.

Pin notes (design §6.3): the speaker regex mirrors
``local_ai/vision_execution/meeting_evidence_pipeline.py:478``
(``_SPEAKER_LINE_RE``); the Jaccard similarity mirrors
``local_ai/vision_execution/entity_judgment_primitives.py:201``
(``jaccard_word_similarity``) with the same stopword set. Both are mirrored,
not imported — the harness never imports pipeline HEAD.
"""

from __future__ import annotations

import re

# Curly quotes normalize to straight quotes for matching ONLY (the same
# discipline as the noting producer: normalization for matching, the stored
# passage stays verbatim). Exactness itself is a strict substring check on
# the raw segment text (validator.py); these helpers serve the frozen
# semantic-equivalence judgments.
_CURLY_TO_STRAIGHT = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
)

_STOPWORDS = frozenset({"a", "an", "the", "and", "or", "of", "for", "in", "on"})

_SPEAKER_LINE_RE = re.compile(
    r"^(speaker\s+[a-z0-9]+)\s*(?:\(\s*\d{1,2}:\d{2}\s*\))?\s*[:\-]?\s*(.*)$",
    re.IGNORECASE,
)


def normalize_text(text: str) -> str:
    """Lowercase, straighten quotes/dashes, strip punctuation, collapse space.

    Used ONLY for frozen-judgment matching (does an emitted row express a
    gold proposition; does a quote equal a gold supporting quote). The stored
    text and the exactness check always use the raw, verbatim strings.
    """
    s = (text or "").translate(_CURLY_TO_STRAIGHT).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def texts_equivalent(a: str, b: str) -> bool:
    """True when two wordings are the same proposition after normalization."""
    return bool(a and b) and normalize_text(a) == normalize_text(b)


def word_set(text: str) -> set[str]:
    """Normalized word set minus the pipeline's dedupe stopwords."""
    return set(normalize_text(text).split()) - _STOPWORDS


def jaccard_word_similarity(a: str, b: str) -> float:
    """Jaccard overlap of word sets, 0..1 (dedupe similarity, §2.2, 0.72)."""
    wa, wb = word_set(a), word_set(b)
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def split_speaker_line(line: str) -> tuple[str, str | None]:
    """Return (content, speaker_label) for ``Speaker A: ...`` diarized lines.

    Mirrors ``_line_without_speaker_prefix`` (pipeline :484): the ``Speaker
    A`` prefix (optionally with a ``(12:34)`` timestamp) is stripped and the
    label returned. Lines without a speaker prefix return ``(line, None)``.
    The label is returned as written in the segment (``Speaker A``).
    """
    stripped = (line or "").strip()
    m = _SPEAKER_LINE_RE.match(stripped)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return stripped, None


def segment_has_explicit_speakers(segment_text: str) -> bool:
    """True when at least one non-empty line carries a speaker prefix."""
    for line in (segment_text or "").split("\n"):
        if not line.strip():
            continue
        _, speaker = split_speaker_line(line)
        if speaker is not None:
            return True
    return False


def resolve_quote_speaker(segment_text: str, quote: str) -> tuple[str | None, bool]:
    """Resolve a quote to the speaker of the line it appears on.

    Returns ``(speaker_label_or_None, is_ambiguous)``. ``is_ambiguous`` is
    True when the quote occurs on more than one line (design §2.1.2: the
    harness flags a quote matching more than one span as a diagnostic) or
    when the quote occurs on a line with no speaker prefix. ``speaker`` is
    None when the segment has no explicit speaker boundaries at all.
    """
    if not quote or not segment_text:
        return None, False
    lines = [ln for ln in segment_text.split("\n") if ln.strip()]
    hits: list[str | None] = []
    for line in lines:
        if quote in line:
            _, speaker = split_speaker_line(line)
            hits.append(speaker)
    if not hits:
        return None, False
    if len(hits) > 1:
        return None, True
    return hits[0], hits[0] is None


def count_quote_occurrences(segment_text: str, quote: str) -> int:
    """How many times the exact quote string occurs in the segment text."""
    if not quote or not segment_text:
        return 0
    return segment_text.count(quote)
