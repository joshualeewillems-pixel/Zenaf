"""Rule-based v1 sorter for Agent Intake ("The Sorting").

The contract — ``sort(name, description, instructions, examples) -> SortResult``
— is stable across versions. v1 is keyword/phrase markers: fast,
deterministic, dependency-free, fully testable. v2 upgrades the claiming to
local Ollama; v3 lets the council genuinely deliberate.

Design (from docs/01_TRUTH/AGENT_INTAKE_AND_SORTING.md): the seven strand
agents each make a case ("this belongs to me, because…") or pass. The
strongest claim becomes the primary strand; every placement carries
plain-language reasoning the user can read and argue with.
"""
from __future__ import annotations

import re

from local_ai.strands import STRANDS, strand_keys

from .schema import SortResult, StrandClaim

# Strand keyword/phrase markers, guided by the canonical taglines in
# local_ai/strands.py. Multi-word phrases match as substrings; single words
# match on word boundaries.
_STRAND_MARKERS: dict[str, tuple[str, ...]] = {
    "word": (
        "writing", "write", "writes", "writer", "draft", "drafts", "essay",
        "essays", "blog", "blogging", "copywriting", "copy", "email", "emails",
        "newsletter", "newsletters", "story", "stories", "storytelling",
        "voice", "tone", "wording", "prose", "poetry", "poem", "poems",
        "script", "speech", "speeches", "rhetoric", "grammar", "edit",
        "editing", "editor", "rewrite", "rewriting", "language", "words",
        "article", "articles", "caption", "captions", "headline", "headlines",
        "letter", "letters", "memo", "publication", "author", "narrative",
    ),
    "number": (
        "data", "dataset", "analysis", "analyze", "analyzes", "analyst",
        "analytics", "statistics", "statistical", "stats", "numbers",
        "numeric", "spreadsheet", "spreadsheets", "excel", "math",
        "mathematics", "calculate", "calculation", "forecast", "forecasting",
        "metric", "metrics", "dashboard", "evidence", "research", "pattern",
        "patterns", "logic", "logical", "reasoning", "quantitative", "model",
        "modeling", "probability", "experiment", "experiments", "hypothesis",
        "correlation", "regression", "chart", "charts", "trends",
    ),
    "image": (
        "visual", "visuals", "visualize", "design", "designer", "designing",
        "logo", "logos", "brand identity", "image", "images", "imagery",
        "photo", "photos", "photography", "illustration", "illustrations",
        "drawing", "sketch", "sketching", "layout", "typography", "font",
        "fonts", "color palette", "mockup", "mockups", "wireframe",
        "wireframes", "aesthetic", "aesthetics", "artwork", "poster",
        "posters", "infographic", "infographics", "graphic", "graphics",
        "look and feel", "composition",
    ),
    "sound": (
        "music", "musical", "musician", "song", "songs", "songwriting",
        "songwriter", "lyrics", "lyric", "melody", "melodies", "melodic",
        "audio", "sound", "sounds", "soundscape", "podcast", "podcasts",
        "rhythm", "rhythmic", "beat", "beats", "mixing", "mastering",
        "compose", "composing", "composer", "composition", "instrument",
        "instruments", "instrumental", "guitar", "piano", "drums", "bass",
        "synth", "track", "tracks", "recording", "harmony", "harmonies",
        "chord", "chords", "tempo", "tune",
    ),
    "body": (
        "build", "builds", "building", "builder", "maker", "making", "craft",
        "crafts", "crafting", "handmade", "hand-made", "woodworking",
        "cooking", "cook", "recipe", "recipes", "meal prep", "fitness",
        "workout", "workouts", "exercise", "yoga", "dance", "dancing",
        "gardening", "garden", "repair", "diy", "construction", "physical",
        "hands-on", "prototype", "prototyping", "3d print", "3d printing",
        "sewing", "knitting", "pottery", "bake", "baking", "bread",
    ),
    "people": (
        "team", "teams", "leadership", "leader", "leading", "manager",
        "managing", "management", "coaching", "coach", "mentor", "mentoring",
        "mentorship", "teaching", "teacher", "teach", "workshop", "workshops",
        "facilitate", "facilitation", "facilitator", "community",
        "relationships", "relationship", "networking", "conflict",
        "mediation", "hiring", "hire", "interview", "interviews",
        "interviewing", "feedback", "collaboration", "collaborate",
        "one-on-one", "performance review",
    ),
    "self": (
        "decision", "decisions", "decide", "deciding", "judgment",
        "judgement", "values", "priorities", "prioritize", "goals", "goal",
        "planning", "plan", "strategy", "strategic", "strategist",
        "reflection", "reflect", "journal", "journaling", "diary", "habits",
        "habit", "productivity", "productive", "focus", "time management",
        "life coach", "career", "purpose", "meaning", "clarity", "choice",
        "choices", "choose", "choosing", "vision", "mission", "intention",
        "intentions", "mindfulness", "meditation", "self-improvement",
    ),
}

# Kind markers, read from *how the agent is described* (never asked directly).
_KIND_MARKERS: dict[str, tuple[str, ...]] = {
    "skill": (
        "helps me", "process", "processes", "steps", "step-by-step",
        "template", "templates", "workflow", "workflows", "automate",
        "automation", "procedure", "procedures", "how to", "checklist",
        "checklists", "system for", "every time", "always starts",
    ),
    "talent": (
        "just gets", "taste", "sense of", "naturally", "natural",
        "intuition", "intuitive", "instinct", "instincts", "eye for",
        "ear for", "knack", "gift for", "notices", "surprises me",
    ),
    "project": (
        "working on", "my novel", "my book", "my memoir", "launch",
        "launching", "project", "my course", "my album", "my startup",
        "my business", "thesis", "dissertation", "campaign", "my app",
        "my product", "exhibition", "my film",
    ),
}

# Markers that saturate a strand score to 1.0.
_SCORE_SATURATION = 4.0
# Below this confidence the system should probe, not guess.
_PROBE_THRESHOLD = 0.35

_FACULTY_BY_KEY = {s.key: s.faculty for s in STRANDS}


def _compile(markers: tuple[str, ...]) -> list[tuple[re.Pattern, str]]:
    compiled = []
    for m in markers:
        if " " in m or "-" in m:
            compiled.append((re.compile(re.escape(m)), m))
        else:
            compiled.append((re.compile(r"\b" + re.escape(m) + r"\b"), m))
    return compiled


_STRAND_RES: dict[str, list[tuple[re.Pattern, str]]] = {
    key: _compile(markers) for key, markers in _STRAND_MARKERS.items()
}
_KIND_RES: dict[str, list[tuple[re.Pattern, str]]] = {
    kind: _compile(markers) for kind, markers in _KIND_MARKERS.items()
}


def _matched_markers(
    compiled: list[tuple[re.Pattern, str]], text: str
) -> list[str]:
    """Distinct markers found in text, in marker-list order (deterministic)."""
    return [label for rx, label in compiled if rx.search(text)]


def _strand_reasoning(faculty: str, matched: list[str]) -> str:
    if not matched:
        return f"no clear {faculty} markers — passing"
    shown = ", ".join(matched[:3])
    strength = (
        "strong" if len(matched) >= 3 else "moderate" if len(matched) == 2 else "some"
    )
    return f"mentions {shown} — {strength} {faculty} signals"


def _kind_reasoning(kind: str, matched: list[str]) -> str:
    if kind == "undecided" or not matched:
        return (
            "description doesn't lean clearly toward skill, talent, or project "
            "language — leaving undecided for the user to place"
        )
    shown = ", ".join(f"'{m}'" for m in matched[:3])
    if kind == "skill":
        return f"procedural language ({shown}) — reads as a trained capability"
    if kind == "talent":
        return f"intuition language ({shown}) — reads as an innate aptitude"
    return f"project language ({shown}) — reads as goal-directed work"


def sort(
    name: str,
    description: str,
    instructions: str | None = None,
    examples: list[str] | None = None,
) -> SortResult:
    """Rule-based v1 sort: strand claims + kind classification.

    Deterministic and dependency-free. Scores each strand 0–1 from marker
    hits in the combined text; confidence is the normalized margin between
    the top two strand scores.
    """
    parts = [name or "", description or "", instructions or ""]
    parts.extend(examples or [])
    text = " ".join(p for p in parts if p).lower()

    claims: list[StrandClaim] = []
    for key in strand_keys():
        matched = _matched_markers(_STRAND_RES[key], text)
        score = min(1.0, len(matched) / _SCORE_SATURATION)
        claims.append(
            StrandClaim(
                strand=key,
                score=round(score, 3),
                reasoning=_strand_reasoning(_FACULTY_BY_KEY[key], matched),
            )
        )
    # Deterministic order: score desc, then canonical strand order.
    order = {key: i for i, key in enumerate(strand_keys())}
    claims.sort(key=lambda c: (-c.score, order.get(c.strand, 99)))
    primary = claims[0].strand

    kind_hits: dict[str, list[str]] = {
        kind: _matched_markers(_KIND_RES[kind], text) for kind in ("skill", "talent", "project")
    }
    counts = {k: len(v) for k, v in kind_hits.items()}
    top_count = max(counts.values())
    leaders = [k for k, v in counts.items() if v == top_count]
    if top_count == 0 or len(leaders) != 1:
        kind: str = "undecided"
        kind_matched: list[str] = []
    else:
        kind = leaders[0]
        kind_matched = kind_hits[kind]

    top_score = claims[0].score
    second_score = claims[1].score if len(claims) > 1 else 0.0
    confidence = round((top_score - second_score) / top_score, 3) if top_score > 0 else 0.0

    return SortResult(
        primary_strand=primary,
        claims=claims,
        kind=kind,  # type: ignore[arg-type]
        kind_reasoning=_kind_reasoning(kind, kind_matched),
        linked_projects=[],  # v2: semantic project linking
        confidence=confidence,
        needs_probing=confidence < _PROBE_THRESHOLD,
    )
