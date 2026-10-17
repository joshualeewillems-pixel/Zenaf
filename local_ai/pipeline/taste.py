"""tasteCompass bootstrap — graduated ask → suggest → propose.

The system moves from asking to proposing as taste data accumulates:
  ask      (0 observations): three questions with generic suggestions.
  suggest  (1-4):           same questions, personalized suggestions.
  propose  (5+):             declarative proposals, not questions.

In every stage the answers, confirmations, and tweaks feed tasteCompass
as taste observations. Preference elicitation is training data —
onboarding and the training loop are the same flow (spec §3).
"""

from __future__ import annotations

import re
from typing import Any

from .store import PipelineStore

#: Observation counts bounding the stages.
SUGGEST_MIN = 1
PROPOSE_MIN = 5

QUESTIONS = [
    {
        "id": "modality",
        "question": "What would you like to make out of it?",
        "generic_suggestions": ["song", "picture", "comic strip", "movie"],
    },
    {
        "id": "style",
        "question": "In what style?",
        "generic_suggestions": ["rock", "Van Gogh", "manga", "Quentin Tarantino"],
    },
    {
        "id": "tools",
        "question": "What tools will you use to make it?",
        "generic_suggestions": ["Suno", "ChatGPT", "Midjourney", "HeyGen"],
    },
]


def get_stage(store: PipelineStore, user_id: str) -> str:
    """ask | suggest | propose, from observation count."""
    n = store.count_observations(user_id)
    if n >= PROPOSE_MIN:
        return "propose"
    if n >= SUGGEST_MIN:
        return "suggest"
    return "ask"


def _profile_lists(store: PipelineStore, user_id: str) -> dict[str, list[str]]:
    profile = store.get_taste_profile(user_id)
    return {
        "styles": list(profile.get("style_anchors") or []),
        "tools": list(profile.get("tools") or []),
        "modalities": list(profile.get("modalities") or []),
    }


def personalized_suggestions(
    store: PipelineStore, user_id: str
) -> dict[str, list[str]]:
    """For the suggest stage: the user's own past answers as suggestions,
    falling back to generic ones where there's nothing yet."""
    known = _profile_lists(store, user_id)
    out: dict[str, list[str]] = {}
    for q in QUESTIONS:
        key = {"modality": "modalities", "style": "styles", "tools": "tools"}[q["id"]]
        seen = known.get(key) or []
        merged = list(dict.fromkeys([*seen, *q["generic_suggestions"]]))
        out[q["id"]] = merged[:6]
    return out


def build_proposal(
    store: PipelineStore,
    user_id: str,
    markers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Declarative proposal for the propose stage.

    The marker detector says *what* the moment wants to become; tasteCompass
    says *how* — in the user's voice, tools, and lineage of influences.
    """
    known = _profile_lists(store, user_id)
    markers = markers or []
    top_modality = markers[0]["modality"] if markers else None

    modality = top_modality or (known["modalities"][0] if known["modalities"] else "song")
    style = known["styles"][0] if known["styles"] else "your style"
    tool = known["tools"][0] if known["tools"] else "your tools"

    modality_label = {
        "story": "story", "comic": "comic", "song": "song",
        "image": "image", "film": "short film",
    }.get(modality, modality)

    copy = (
        f"This would make an excellent {modality_label} — "
        f"{tool}, {style} vibe. Want me to write the pack?"
    )
    return {
        "copy": copy,
        "modality": modality,
        "style": style,
        "tool": tool,
    }


def _extract_terms(answer: str) -> list[str]:
    """Pull candidate style/tool/modality terms out of a free-text answer."""
    bits = [
        b.strip().strip("\"'.,") for b in re.split(r"[,;/\n]| or ", answer or "")
    ]
    return [b for b in bits if b][:6]


def record_answers(
    store: PipelineStore, user_id: str, answers: dict[str, str]
) -> dict[str, Any]:
    """Store the three answers as taste observations and fold them into the
    profile. Returns the updated profile."""
    profile = store.get_taste_profile(user_id)
    styles = list(profile.get("style_anchors") or [])
    tools = list(profile.get("tools") or [])
    modalities = list(profile.get("modalities") or [])

    for q in QUESTIONS:
        answer = (answers.get(q["id"]) or "").strip()
        if not answer:
            continue
        store.add_taste_observation(user_id, q["question"], answer)
        terms = _extract_terms(answer)
        target = {"modality": modalities, "style": styles, "tools": tools}[q["id"]]
        for term in terms:
            if term and term.lower() not in {t.lower() for t in target}:
                target.append(term)

    summary_bits = []
    if modalities:
        summary_bits.append(f"makes {', '.join(modalities[:3])}")
    if styles:
        summary_bits.append(f"in styles like {', '.join(styles[:3])}")
    if tools:
        summary_bits.append(f"with {', '.join(tools[:3])}")
    summary = "; ".join(summary_bits)
    if summary:
        summary = "User " + summary + "."

    return store.save_taste_profile(
        user_id,
        summary=summary,
        style_anchors=styles[-12:],
        tools=tools[-12:],
        modalities=modalities[-12:],
        observation_count=store.count_observations(user_id),
    )


def record_confirmation(
    store: PipelineStore, user_id: str, tweak: str | None = None
) -> dict[str, Any]:
    """A proposal confirm (optionally with a tweak like 'make it more rock')
    is training signal: the tweak is stored as a taste observation."""
    if tweak and tweak.strip():
        store.add_taste_observation(
            user_id, "Proposal tweak", tweak.strip()
        )
        terms = _extract_terms(tweak)
        profile = store.get_taste_profile(user_id)
        styles = list(profile.get("style_anchors") or [])
        for term in terms:
            if term and term.lower() not in {t.lower() for t in styles}:
                styles.append(term)
        return store.save_taste_profile(
            user_id,
            summary=profile.get("summary") or "",
            style_anchors=styles[-12:],
            tools=list(profile.get("tools") or []),
            modalities=list(profile.get("modalities") or []),
            observation_count=store.count_observations(user_id),
        )
    return store.get_taste_profile(user_id)


def style_anchors_for_prompt(store: PipelineStore, user_id: str) -> str:
    """Style anchors rendered for pack-generation prompts."""
    known = _profile_lists(store, user_id)
    bits = []
    if known["styles"]:
        bits.append("Style references: " + ", ".join(known["styles"][:5]))
    if known["tools"]:
        bits.append("Target tools: " + ", ".join(known["tools"][:5]))
    return "; ".join(bits)
