"""Council archetype system — the visible council seats as strand amalgamations.

Each archetype is a weight vector across the 7 strands, not a single strand.
The strands (Voice, Logic, Eye, Ear, Hands, Heart, Compass) are the backyard —
trained directly by signals. The archetypes (Mentor, Champion, Guardian,
Maverick, Ambassador, Conductor, Skeptic) are the front — the council seats
the user talks to, each blending multiple strands.

Design: ~/workspace/zenaf-council-archetype-plan.md
Approved by Joshua 2026-10-16.

Naming: weight keys use plain-spoken strand names ("Voice", "Logic", etc.).
PLAIN_TO_KEY maps them to the lowercase strand keys used in code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Plain-spoken strand name -> lowercase strand key (see local_ai/strands.py).
PLAIN_TO_KEY: dict[str, str] = {
    "Voice": "word",
    "Logic": "number",
    "Eye": "image",
    "Ear": "sound",
    "Hands": "body",
    "Heart": "people",
    "Compass": "self",
}

# Reverse mapping: lowercase key -> plain-spoken name.
KEY_TO_PLAIN: dict[str, str] = {v: k for k, v in PLAIN_TO_KEY.items()}

#: Strands below this weight are omitted from prompt weaving (noise floor).
WEIGHT_FLOOR = 0.05

#: Epsilon for weight-sum validation.
_SUM_EPSILON = 1e-6

#: Canonical voice color per archetype id — used everywhere the voice appears:
#: landing demo chips, Foundation voice console, chat accents, Living Tree
#: branches, journal story cast. Distinct from strand colors (strands.py).
#: The user-weave accent marks visitor/user words woven into a voice's reply.
VOICE_COLORS: dict[str, str] = {
    "mentor": "#c9a86a",      # deep gold — the long view
    "champion": "#c96a5a",    # ember red — courage, action
    "guardian": "#7ba889",    # warm green — care, protection
    "maverick": "#9a7bc9",    # electric violet — pattern-breaking
    "ambassador": "#7aa3b8",  # sky blue — the public face
    "conductor": "#8a8a93",   # neutral slate — synthesis
    "skeptic": "#6b6b76",     # ash gray — the uncomfortable question
}

#: Accent for user/visitor words woven into a voice's reply ([[u]] spans).
USER_WEAVE_COLOR = "#e8a33d"  # bright amber — "your words"


def voice_color(archetype_id: str) -> str:
    """Canonical hex color for an archetype voice. Falls back to slate."""
    return VOICE_COLORS.get((archetype_id or "").strip().lower(), "#8a8a93")


@dataclass
class CouncilArchetype:
    """One council seat archetype — a strand weight vector plus prompt frame."""

    id: str                          # stable id: "mentor", "champion", ...
    display_name: str                # user-customizable after unlock milestones
    strand_weights: dict[str, float] | None  # 7-vector summing to 1.0; None = computed (Skeptic)
    prompt_frame: str                # role description for council prompts
    parent_id: str | None = None     # for sub-personality twigs; None for stock
    is_stock: bool = True            # True for the 7 defaults

    def __post_init__(self) -> None:
        if self.strand_weights is not None:
            total = sum(self.strand_weights.values())
            if abs(total - 1.0) > _SUM_EPSILON:
                raise ValueError(
                    f"Archetype {self.id}: strand_weights sum to {total}, expected 1.0"
                )
            unknown = set(self.strand_weights) - set(PLAIN_TO_KEY)
            if unknown:
                raise ValueError(
                    f"Archetype {self.id}: unknown strand names {sorted(unknown)}"
                )


def _w(**kwargs: float) -> dict[str, float]:
    """Shorthand for building weight vectors with plain-spoken keys."""
    return dict(kwargs)


STOCK_ARCHETYPES: tuple[CouncilArchetype, ...] = (
    CouncilArchetype(
        id="mentor",
        display_name="Mentor",
        strand_weights=_w(Compass=0.35, Logic=0.30, Voice=0.15, Heart=0.10,
                          Eye=0.05, Ear=0.03, Hands=0.02),
        prompt_frame=(
            "The long view, the advisor. You hold the question of where this is going — "
            "read the terrain, name what matters, and keep choices pointed at what the user "
            "actually wants. Speak with the steadiness of someone who has seen how stories end."
        ),
    ),
    CouncilArchetype(
        id="champion",
        display_name="Champion",
        strand_weights=_w(Hands=0.35, Compass=0.30, Logic=0.15, Heart=0.10,
                          Voice=0.05, Eye=0.03, Ear=0.02),
        prompt_frame=(
            "Courage, will, the one who says do it. You fight for the user's aims — "
            "name the brave move, cut through hesitation, and push toward action. "
            "Bold, direct, allergic to dithering."
        ),
    ),
    CouncilArchetype(
        id="guardian",
        display_name="Guardian",
        strand_weights=_w(Heart=0.35, Hands=0.25, Compass=0.20, Voice=0.10,
                          Eye=0.05, Logic=0.03, Ear=0.02),
        prompt_frame=(
            "Holds the people impact. You ask who gets helped and who gets hurt — "
            "the human cost and care in every choice. Warm, protective, unwilling to "
            "treat people as abstractions."
        ),
    ),
    CouncilArchetype(
        id="maverick",
        display_name="Maverick",
        strand_weights=_w(Voice=0.30, Eye=0.25, Logic=0.20, Compass=0.15,
                          Ear=0.05, Heart=0.03, Hands=0.02),
        prompt_frame=(
            "Lateral thinking, challenges the frame. You question the question itself — "
            "what if the premises are wrong, what hasn't been considered, what would a "
            "complete outsider see? Independent, pattern-breaking, allergic to groupthink."
        ),
    ),
    CouncilArchetype(
        id="ambassador",
        display_name="Ambassador",
        strand_weights=_w(Voice=0.30, Eye=0.25, Heart=0.20, Compass=0.15,
                          Logic=0.05, Ear=0.03, Hands=0.02),
        prompt_frame=(
            "The public face. You consider how things land out there — reputation, "
            "relationships, the story others will tell. Diplomatic, image-aware, "
            "attuned to the social field around every decision."
        ),
    ),
    CouncilArchetype(
        id="conductor",
        display_name="Conductor",
        strand_weights=_w(Compass=0.25, Logic=0.20, Voice=0.15, Heart=0.15,
                          Eye=0.10, Hands=0.10, Ear=0.05),
        prompt_frame=(
            "Synthesizes after the others speak. You weave the council's voices into "
            "something coherent — not a compromise, but the shape underneath the "
            "disagreement. Balanced, integrative, oriented toward what actually works."
        ),
    ),
    CouncilArchetype(
        id="skeptic",
        display_name="Skeptic",
        strand_weights=None,  # computed dynamically — see compute_skeptic_weights
        prompt_frame=(
            "Names what's being avoided. You voice the worry nobody's saying out loud — "
            "the risk everyone's stepping around, the flaw in the favored plan, the question "
            "that makes the room uncomfortable. Not contrarian for sport: you go where the "
            "user isn't looking, because that's where the blind spots live."
        ),
    ),
)

_BY_ID: dict[str, CouncilArchetype] = {a.id: a for a in STOCK_ARCHETYPES}


def get_archetype(archetype_id: str) -> CouncilArchetype | None:
    """Look up a stock archetype by id. Returns None for unknown ids."""
    return _BY_ID.get((archetype_id or "").strip().lower())


def stock_archetype_ids() -> tuple[str, ...]:
    """Ids of the 7 stock archetypes, in canonical order."""
    return tuple(a.id for a in STOCK_ARCHETYPES)


def archetype_blend_lines(archetype_id: str) -> list[str]:
    """Prompt lines describing an archetype's strand blend.

    Returns [] for unknown archetype ids or the Skeptic (dynamic weights).
    Each line names a strand above WEIGHT_FLOOR with its weight and tagline.
    """
    arch = get_archetype(archetype_id)
    if arch is None or arch.strand_weights is None:
        return []
    from local_ai.strands import strand as _strand

    lines: list[str] = []
    for plain_name, weight in sorted(
        arch.strand_weights.items(), key=lambda kv: kv[1], reverse=True
    ):
        if weight < WEIGHT_FLOOR:
            continue
        key = PLAIN_TO_KEY[plain_name]
        try:
            tagline = _strand(key).tagline
        except KeyError:
            tagline = ""
        pct = int(round(weight * 100))
        if tagline:
            lines.append(f"- {plain_name} ({pct}%): {tagline}")
        else:
            lines.append(f"- {plain_name} ({pct}%)")
    return lines


def build_archetype_prompt_lines(
    archetype_id: str,
    weights_override: dict[str, float] | None = None,
    display_name_override: str | None = None,
) -> list[str]:
    """Full prompt lines for an archetype seat: frame + strand blend.

    Returns [] for unknown archetype ids. `weights_override` (plain-spoken
    name -> weight) replaces the stock vector — used for the Skeptic's
    dynamically computed weights. `display_name_override` replaces the
    stock display name (user-renamed seats).
    """
    arch = get_archetype(archetype_id)
    if arch is None:
        return []
    from local_ai.strands import strand as _strand

    name = (display_name_override or arch.display_name).strip() or arch.display_name
    lines = [f"Archetype: {name} — {arch.prompt_frame}"]

    weights = weights_override if weights_override is not None else arch.strand_weights
    if weights:
        blend: list[str] = []
        for plain_name, weight in sorted(weights.items(), key=lambda kv: kv[1], reverse=True):
            if weight < WEIGHT_FLOOR:
                continue
            key = PLAIN_TO_KEY.get(plain_name)
            tagline = ""
            if key:
                try:
                    tagline = _strand(key).tagline
                except KeyError:
                    pass
            pct = int(round(weight * 100))
            if tagline:
                blend.append(f"- {plain_name} ({pct}%): {tagline}")
            else:
                blend.append(f"- {plain_name} ({pct}%)")
        if blend:
            lines.append("Strand blend (faculties this seat draws on, by weight):")
            lines.extend(blend)
    return lines


def compute_skeptic_weights_from_depths(
    depths: dict[str, float],
) -> dict[str, float]:
    """Skeptic weight vector from per-strand training depth scores.

    `depths` maps lowercase strand keys to 0..100 depth scores (as from
    compute_training_depth). Inverts: the user's deepest strands get the
    lowest Skeptic weight; the shallowest get the highest. Normalized to
    sum to 1.0. Pure function — easy to test.

    Keys of the returned dict are plain-spoken strand names.
    """
    # Invert: high depth -> low weight. Add 1 to avoid division by zero
    # and to keep untrained strands from dominating absolutely.
    inverted: dict[str, float] = {}
    for key in PLAIN_TO_KEY.values():
        score = depths.get(key, 0.0)
        plain = KEY_TO_PLAIN[key]
        inverted[plain] = 1.0 / (1.0 + max(0.0, score))
    total = sum(inverted.values())
    if total <= 0:
        # Degenerate: uniform fallback.
        n = len(inverted)
        return {k: 1.0 / n for k in inverted}
    return {k: v / total for k, v in inverted.items()}


def compute_skeptic_weights(user_id: str | None) -> dict[str, float]:
    """Dynamic Skeptic weight vector for a user.

    Loads per-strand training depth and inverts it (see
    compute_skeptic_weights_from_depths). Never raises: on any failure
    (no user, no license, no data) returns a uniform distribution.
    Keys are plain-spoken strand names.
    """
    n = len(PLAIN_TO_KEY)
    uniform = {plain: 1.0 / n for plain in PLAIN_TO_KEY}
    if not user_id:
        return uniform
    try:
        from local_ai.personality.depth import compute_training_depth
        from local_ai.personality.store import PersonalityStore
        from local_ai.presence_ingest.store import PresenceStore
        from local_ai.identity.service import get_license

        lic = get_license()
        signals: list = []
        if lic is not None and getattr(lic, "status", "") == "active":
            signals_store = PresenceStore()
            sessions = {s.session_id: s for s in signals_store.list_sessions()}
            for sig in signals_store.list_signals(status="approved"):
                sess = sessions.get(sig.session_id)
                prov = (sess.provenance if sess else {}) or {}
                if prov.get("license_id") == lic.license_id:
                    signals.append(sig)
            signals_store.close()

        store = PersonalityStore(user_id)
        try:
            profile = store.get_current()
            versions: list = []
            for meta in store.list_versions():
                v = store.get_version(meta["version"])
                if v is not None:
                    versions.append((meta["version"], v))
            depths = compute_training_depth(
                signals=signals, profile=profile, versions=versions
            )
            scores = {k: d.score for k, d in depths.items()}
        finally:
            store.close()
        return compute_skeptic_weights_from_depths(scores)
    except Exception:
        return uniform
