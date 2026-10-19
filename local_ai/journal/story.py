"""Journal entries rendered as archetype stories.

The user journals conversationally. We analyze the entry through the 7 strands,
identify which council archetypes are active (by matching strand weight patterns),
and render the entry as a short metaphorical story — a scene where the active
archetypes appear as characters in dialogue.

Like Inside Out meets journaling: your inner council dramatized.

Comic-strip contract (for the future renderer):
    Each cast member carries an `avatar_url` (None when the seat's avatar is
    still locked — the ??? state). The comic renderer MUST honor this field:
      - avatar_url present -> draw the character using that image.
      - avatar_url None    -> draw an amorphous cloud shape: undefined,
        mysterious, the visual equivalent of the ??? silhouette placeholder
        in the UI. The ??? silhouette (UI) and the amorphous cloud (comics)
        are the same concept at different fidelities — an undiscovered face.
    Never invent a face for a locked seat. The cloud IS the character until
    the user unlocks the avatar milestone (10 depth points per seat).
"""

from __future__ import annotations

import math

from local_ai.agent_intake.sorter import sort as _sort_text
from local_ai.council.archetypes import (
    KEY_TO_PLAIN,
    PLAIN_TO_KEY,
    STOCK_ARCHETYPES,
    compute_skeptic_weights,
    get_archetype,
)

#: Cosine similarity threshold for an archetype to join the cast.
#: 7-dim sparse vectors typically score 0.4-0.7; 0.45 gives 2-3 voices
#: for mixed entries while keeping single-voice entries focused.
CAST_THRESHOLD = 0.45

#: Maximum characters in the cast.
MAX_CAST_SIZE = 3

#: Target story length in words.
STORY_MIN_WORDS = 150
STORY_MAX_WORDS = 250

#: Canonical plain-spoken strand order for vector alignment.
_STRAND_ORDER: tuple[str, ...] = (
    "Voice", "Logic", "Eye", "Ear", "Hands", "Heart", "Compass",
)


def analyze_entry_strands(text: str) -> dict[str, float]:
    """Score a journal entry against the 7 strands.

    Uses the rule-based sorter (deterministic, no LLM call). Returns weights
    keyed by plain-spoken strand name, normalized to sum to 1.0. Empty dict
    if nothing scores.
    """
    text = (text or "").strip()
    if not text:
        return {}
    result = _sort_text(name="", description=text)
    # result.strand_weights is keyed by lowercase strand key -> score
    plain_weights: dict[str, float] = {}
    for key, score in (result.strand_weights or {}).items():
        plain = KEY_TO_PLAIN.get(key)
        if plain and score > 0:
            plain_weights[plain] = float(score)
    total = sum(plain_weights.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in plain_weights.items()}


def _to_vector(weights: dict[str, float]) -> tuple[float, ...]:
    """Align a plain-spoken weight dict to the canonical 7-vector."""
    return tuple(weights.get(name, 0.0) for name in _STRAND_ORDER)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Cosine similarity between two 7-vectors. 0.0 if either is zero."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def detect_active_archetypes(
    strand_weights: dict[str, float],
    user_id: str | None = None,
) -> list[tuple[str, float]]:
    """Match an entry's strand weights against archetype vectors.

    Returns a ranked list of (archetype_id, cosine_similarity), highest first.
    The Skeptic's dynamic weights are computed for the user when available;
    otherwise it is skipped (its vector is user-specific).
    """
    entry_vec = _to_vector(strand_weights)
    if all(v == 0 for v in entry_vec):
        return []

    scored: list[tuple[str, float]] = []
    for arch in STOCK_ARCHETYPES:
        if arch.strand_weights is not None:
            sim = _cosine(entry_vec, _to_vector(arch.strand_weights))
            scored.append((arch.id, sim))

    # Skeptic: dynamic per-user weights (uniform fallback inside).
    try:
        skeptic_weights = compute_skeptic_weights(user_id, mode="trained")
        sim = _cosine(entry_vec, _to_vector(skeptic_weights))
        scored.append(("skeptic", sim))
    except Exception:
        pass

    scored.sort(key=lambda kv: kv[1], reverse=True)
    return scored


def select_cast(
    ranked: list[tuple[str, float]],
    threshold: float = CAST_THRESHOLD,
    max_size: int = MAX_CAST_SIZE,
) -> list[tuple[str, float]]:
    """Pick the story's cast from ranked archetype similarities.

    Takes the top `max_size` archetypes at or above `threshold`. If none
    clear the threshold, falls back to the single closest match.
    """
    cast = [(aid, sim) for aid, sim in ranked[:max_size] if sim >= threshold]
    if not cast and ranked:
        cast = [ranked[0]]
    return cast


def build_cast(
    cast: list[tuple[str, float]],
    user_id: str | None = None,
) -> list[dict]:
    """Enrich a cast with display names and avatar URLs for rendering.

    Returns a list of dicts: {id, name, similarity, avatar_url}. The
    avatar_url is the seat's unlocked custom avatar, or None when locked
    (??? state). Comic-strip and future visual renderers MUST use this
    field per the module docstring contract: avatar when present,
    amorphous cloud when None. Never raises.
    """
    from local_ai.council.naming import get_avatar_url, get_display_name

    out: list[dict] = []
    for archetype_id, similarity in cast:
        arch = get_archetype(archetype_id)
        if arch is None:
            continue
        out.append(
            {
                "id": arch.id,
                "name": get_display_name(user_id, archetype_id),
                "similarity": round(similarity, 3),
                "avatar_url": get_avatar_url(user_id, archetype_id),
            }
        )
    return out


def _build_story_prompt(
    entry_text: str,
    cast: list[tuple[str, float]],
    user_id: str | None = None,
) -> str:
    """Build the Meta LLM prompt that renders the entry as a scene.

    Character names honor user-renamed seats (naming unlock milestones)
    when user_id is given; stock names otherwise.
    """
    from local_ai.council.naming import get_display_name

    characters: list[str] = []
    for archetype_id, similarity in cast:
        arch = get_archetype(archetype_id)
        if arch is None:
            continue
        characters.append(
            f"**{get_display_name(user_id, archetype_id)}**: {arch.prompt_frame}"
        )
    cast_block = "\n\n".join(characters)

    return f"""You are a storyteller. Below is someone's journal entry, followed by a cast of characters — inner voices, each with a distinct way of seeing the world.

Your task: render the journal entry as a short metaphorical SCENE (150-250 words) where these characters appear in dialogue, reacting to what happened in the entry. Not a clinical analysis — a living scene, like a moment from a film. The characters should sound like themselves: let their distinct voices come through in what they say and notice.

JOURNAL ENTRY:
\"\"\"
{entry_text.strip()}
\"\"\"

CAST:
{cast_block}

Write the scene now. Keep it to 150-250 words. No preamble, no explanation — just the story."""


def render_archetype_story(
    entry_text: str,
    cast: list[tuple[str, float]],
    api_key: str | None = None,
    model: str | None = None,
    timeout: int = 120,
    user_id: str | None = None,
) -> str:
    """Render a journal entry as an archetype story via the Meta LLM.

    `cast` is a list of (archetype_id, similarity) from `select_cast`.
    `user_id` lets character names honor user-renamed seats.
    Raises RuntimeError if the Meta API key is not configured or the call fails.
    """
    if not cast:
        raise ValueError("Cannot render a story with an empty cast.")
    from local_ai.providers import meta as _meta

    prompt = _build_story_prompt(entry_text, cast, user_id=user_id)
    return _meta.generate(api_key, prompt, model=model, timeout=timeout).strip()
