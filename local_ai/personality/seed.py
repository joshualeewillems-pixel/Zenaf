"""Seed PersonalityProfile candidates from approved TrainingSignals.

The presence-ingest distillation prompt already extracts "values/beliefs
revealed" and "communication and decision-making style" as free text in each
signal's summary/payload_redacted. This module parses what it can with
explicit heuristics — cue-word sentence extraction, keyword zone→strand
mapping — and emits PROPOSED candidates only. Confidence is marked modestly
because the parse is heuristic; the user reviews everything at publish.

Nothing here publishes. Nothing fabricates: every candidate quotes its
source signal and names the heuristic used.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from local_ai.strands import strand_keys

from .schema import CandidateOp, ProfileCandidate

# zone/summary text -> strand key. Conservative on purpose: a miss means the
# signal is skipped (or lands on "self" for values-cues, marked low confidence).
_STRAND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "word": ("word", "writing", "language", "rhetoric", "story", "communicat", "voice", "tone", "brief"),
    "number": ("number", "data", "analy", "metric", "evidence", "quant", "forecast"),
    "image": ("image", "visual", "design", "spatial", "aesthetic", "taste"),
    "sound": ("sound", "music", "rhythm", "audio", "listen"),
    "body": ("body", "craft", "making", "build", "physical", "hands"),
    "people": ("people", "team", "leader", "interpersonal", "manage", "care", "teach"),
    "self": ("self", "judgment", "values", "belief", "decision", "strategy", "direction", "principle"),
}

_VALUES_CUES = ("values", "beliefs", "believes", "principle", "never ", "always ", "non-negotiable")
_STYLE_CUES = ("style", "tone", "sounds like", "phrasing", "concise", "direct", "prefers")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if len(p.strip()) > 12]


def _map_zone_to_strand(zone: str, text: str) -> tuple[str | None, float, str]:
    """Return (strand_key, confidence, how). None when nothing matches."""
    blob = f"{zone} {text}".lower()
    for key in strand_keys():
        for kw in _STRAND_KEYWORDS[key]:
            if kw in blob:
                if kw in zone.lower():
                    return key, 0.45, f"zone {zone!r} matched strand {key!r} by keyword {kw!r}"
                return key, 0.35, f"text matched strand {key!r} by keyword {kw!r}"
    low = blob
    if any(c in low for c in ("values", "beliefs", "judgment", "decision")):
        return "self", 0.30, "no zone match; values/judgment cues mapped to 'self' heuristically"
    return None, 0.0, ""


def _cue_sentences(text: str, cues: tuple[str, ...]) -> list[str]:
    low_cues = cues
    out = []
    for s in _sentences(text):
        ls = s.lower()
        if any(c in ls for c in low_cues):
            out.append(s)
    return out


def seed_from_signals(personality_store, signals_store, user_id: str, limit: int = 200) -> list[ProfileCandidate]:
    """Propose candidates from approved training signals. Never publishes.

    Skips signals already seeded (tracked via candidate `source` markers).
    """
    from .store import PersonalityStore  # noqa: F401  (typing aid only)

    existing_sources = {
        c.source for c in personality_store.list_candidates() if c.source.startswith("seed:signal:")
    }
    signals = signals_store.list_signals(status="approved")
    made: list[ProfileCandidate] = []
    now = datetime.now(timezone.utc)

    for sig in signals[:limit]:
        marker = f"seed:signal:{sig.signal_id}"
        if marker in existing_sources:
            continue
        text = f"{sig.summary}\n{sig.payload_redacted or ''}"
        strand_key, conf, how = _map_zone_to_strand(sig.zone, text)
        if strand_key is None:
            continue

        value_hits = _cue_sentences(text, _VALUES_CUES)
        style_hits = _cue_sentences(text, _STYLE_CUES)

        if value_hits:
            s = value_hits[0][:280]
            made.append(
                ProfileCandidate(
                    candidate_id=f"pc_{uuid.uuid4().hex[:12]}",
                    user_id=user_id,
                    strand_key=strand_key,
                    ops=[CandidateOp(op="add", field="heuristics", value=f"Observed: {s}")],
                    source=marker,
                    confidence=round(conf, 2),
                    rationale=(
                        f"Seeded from approved signal {sig.signal_id} (zone={sig.zone!r}, "
                        f"valence={sig.valence}). {how}. Sentence matched values-cues; "
                        "human review required."
                    ),
                    created_at=now,
                )
            )
        if style_hits:
            s = style_hits[0][:280]
            made.append(
                ProfileCandidate(
                    candidate_id=f"pc_{uuid.uuid4().hex[:12]}",
                    user_id=user_id,
                    strand_key=strand_key,
                    ops=[
                        CandidateOp(
                            op="add",
                            field="examples",
                            value={
                                "context": f"signal {sig.signal_id} ({sig.zone})",
                                "fragment": s,
                                "tag": "style-observation",
                            },
                        )
                    ],
                    source=marker,
                    confidence=round(max(conf - 0.05, 0.2), 2),
                    rationale=(
                        f"Seeded from approved signal {sig.signal_id} (zone={sig.zone!r}). "
                        f"{how}. Sentence matched style-cues; kept as example fragment."
                    ),
                    created_at=now,
                )
            )

    for cand in made:
        personality_store.propose(cand)
    return made
