"""Prompt packs: story -> per-modality prompts for external tools (spec §3).

Zenaf generates the packs; the user renders them wherever they like.
Each pack is registered as a `prompt_pack` artifact (text, SHA-256),
parented to the story — bracketing the external render step.

Modalities: comic (panel-by-panel), song (lyrics + style), film
(scene beats), image (single prompt). Quote cards are handled in-house
(`quote_cards.py`), not as packs.
"""

from __future__ import annotations

from typing import Any

MODALITIES = ("comic", "song", "film", "image")

_MODALITY_SPECS = {
    "comic": (
        "Write a comic-strip prompt pack: 4-6 panels. For each panel give "
        "a visual prompt (what is seen: characters, composition, mood) in one "
        "or two sentences. Characters: {cast}. End with a style line and a "
        "negative prompt (what to avoid)."
    ),
    "song": (
        "Write a song prompt pack: full lyrics (verse / chorus / verse / "
        "chorus / bridge structure, plain plain-spoken language, no clichés) "
        "drawn from the story's emotional arc, then a style prompt (genre, "
        "tempo, instrumentation, vocal character) for a tool like Suno."
    ),
    "film": (
        "Write a short-film prompt pack: 3-5 scene beats. For each beat give "
        "a visual prompt (shot, action, light, mood) in two or three sentences, "
        "suitable for a tool like Runway or HeyGen. End with an overall style line."
    ),
    "image": (
        "Write a single evocative image prompt: one rich paragraph describing "
        "the scene, composition, light, palette, and mood — suitable for "
        "Midjourney or DALL-E. Then a short negative prompt."
    ),
}

_PACK_PROMPT = """You write prompt packs that turn a personal story into something the user can render in an external creative tool.

Story title: {title}
Story:
---
{narrative}
---
Key line: {key_line}

{style_anchors}

Task: {modality_spec}

Rules:
- Keep every prompt concrete and visual (or sonic, for song): no abstractions, no "the feeling of" — describe what is seen or heard.
- Plain language. Short sentences.
- Respond with ONLY a JSON object: {{"pack_title": "...", "prompts": ["...", "..."], "style_line": "...", "negative_prompt": "..."}}.
  For song, prompts[0] is the lyrics and prompts[1] is the style prompt.
"""


def generate_pack(
    story: dict[str, Any],
    modality: str,
    *,
    style_anchors: str = "",
    variation_of: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Generate one prompt pack for a story. Returns pack content dict.

    Raises ValueError for unknown modalities or bad LLM output,
    RuntimeError if the LLM call fails.
    """
    from local_ai.providers import meta as _meta
    from .stories import _extract_json

    if modality not in MODALITIES:
        raise ValueError(f"unknown modality: {modality}")

    style_block = (
        f"Style anchors from the user's taste: {style_anchors}"
        if style_anchors else "No established style anchors yet — keep the style open and evocative."
    )
    if variation_of:
        style_block += (
            "\nThis is another take on the same story — vary the approach, "
            "angle, or mood from a typical first rendering."
        )
    prompt = _PACK_PROMPT.format(
        title=story.get("title", ""),
        narrative=story.get("narrative", ""),
        key_line=story.get("key_line", ""),
        style_anchors=style_block,
        modality_spec=_MODALITY_SPECS[modality].format(
            cast=", ".join(story.get("archetype_cast") or ["the narrator"])
        ),
    )
    try:
        reply = _meta.generate(
            api_key or "", prompt, model=model, timeout=timeout,
            reasoning_effort="low",
        ).strip()
    except Exception as exc:
        raise RuntimeError(f"pack generation failed: {exc}") from exc

    data = _extract_json(reply)
    prompts = data.get("prompts") or []
    if not isinstance(prompts, list) or not prompts:
        raise ValueError("LLM pack had no prompts.")
    return {
        "modality": modality,
        "pack_title": str(data.get("pack_title") or f"{story.get('title', 'Untitled')} — {modality}").strip()[:120],
        "prompts": [str(p).strip()[:2000] for p in prompts],
        "style_line": str(data.get("style_line") or "").strip()[:500],
        "negative_prompt": str(data.get("negative_prompt") or "").strip()[:500],
        "variation_of": variation_of,
    }
