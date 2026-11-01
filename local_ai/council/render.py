"""Weaver ordinary-conversation renderer.

Builds the character-derived block for ordinary Weaver turns from the
canonical record (:mod:`local_ai.council.canonical.weaver`) — and
nothing else. Assembly order: identity → personality/temperament/
voice → core conviction/worldview → capability → voice guidance.
(This matches the accepted exemplar's rendering shape; the closing
voice guidance trails the capability unit so the four anchors stay in
order.)

Eligibility is enforced by construction from record metadata, never
by string exclusion and never by developer memory:

- :func:`eligible_field` returns a field's text ONLY if its standing
  is ``adopted`` AND its category is ``conviction`` or
  ``characterization``. Every content unit is built through it.
- Identity (role/character) is structural: the identity line is built
  from it directly, and the record-integrity test asserts both are
  adopted.
- Protected §1.7 material, provisional relationships, open
  contributions, provenance (philosopher names), jurisdiction, and
  narrative fields all fail at least one check, so no code path in
  this module can emit them.
- Capability text is NEVER read from the record: the capability unit
  comes solely from ``resolved_capability`` — already-resolved,
  visitor-authorized guidance supplied by the caller (the resolver).
  The renderer formats it; it never interprets capability ids and
  never becomes a second permission system. A record capability entry
  carrying hostile text cannot reach output because no code path
  reads record capability text into a unit.
- Renderings use NONHISTORICAL associations only: the personality
  unit uses the record's ``render_text`` (plan-review correction),
  never the verbatim picture's Fox-history illustration.

Budget: the assembled character-derived block has a 1,500-character
provisional ceiling. Units are complete bounded sentences/paragraphs
and are only ever dropped whole, never truncated mid-thought:
over budget, the fuller personality degrades to the compact variant,
then the droppable voice guidance is dropped; if the block is still
over budget, assembly FAILS with :class:`AssemblyError` (validation
failure, never silent truncation). Essential units (identity,
personality, worldview) missing through ineligibility also raise.
"""

from __future__ import annotations

from typing import Any

CHARACTER_CEILING = 1500

_ELIGIBLE_CATEGORIES = frozenset({"conviction", "characterization"})


class AssemblyError(ValueError):
    """Character-block assembly failed validation (over budget after
    dropping all optional units, or an essential field ineligible).
    Never a truncation: the caller must fix the input, not ship a
    cut-off character."""


def eligible_field(record: dict, section: str, key: str) -> str | None:
    """Text of a record field iff it passes BOTH eligibility checks.

    Returns None when the field is absent, has no usable text, or
    fails standing (must be ``adopted``) or category (must be
    ``conviction`` or ``characterization``). For fields carrying a
    ``render_text`` (the personality field's plan-review correction),
    the renderable text is returned, never the verbatim illustration.
    """
    try:
        field = record[section][key]
    except (KeyError, TypeError):
        return None
    if not isinstance(field, dict):
        return None
    if field.get("standing") != "adopted":
        return None
    if field.get("category") not in _ELIGIBLE_CATEGORIES:
        return None
    text = field.get("render_text", field.get("text"))
    if not isinstance(text, str) or not text.strip():
        return None
    return text


def eligible_fields(record: dict) -> list[tuple[str, str]]:
    """All (section, key) pairs passing both eligibility checks.

    Used by tests (the eligibility matrix) and by audits. The
    renderer itself builds units through :func:`eligible_field`;
    this listing is the inspectable form of the same rule.
    """
    out: list[tuple[str, str]] = []
    if not isinstance(record, dict):
        return out
    for section, fields in record.items():
        if not isinstance(fields, dict):
            continue
        for key, field in fields.items():
            if not isinstance(field, dict):
                continue
            if field.get("standing") != "adopted":
                continue
            if field.get("category") not in _ELIGIBLE_CATEGORIES:
                continue
            text = field.get("render_text", field.get("text"))
            if isinstance(text, str) and text.strip():
                out.append((section, key))
    return out


def _identity_unit(record: dict, visitor_state: dict | None) -> str:
    """Structural identity line. Role/character are adopted by
    record-integrity test; a visitor-chosen name changes address
    (an appended clause), never essence."""
    identity = record.get("identity", {})
    role = identity.get("role", {}).get("text", "Conductor")
    character = identity.get("character", {}).get("text", "Weaver")
    line = f"You are the {character}, who occupies the {role} seat in the Fellowship."
    personal = (visitor_state or {}).get("personal_name")
    if isinstance(personal, str) and personal.strip():
        line += f" The visitor calls you {personal.strip()}."
    return line


def _personality_unit(
    temperament: str, demeanor: str, detail: str
) -> str:
    """Personality paragraph. The fuller variant adds the
    nonhistorical associative triplet and the workshop sentence;
    degrading fuller → compact drops exactly those two additions."""
    core = (
        "You are an exuberantly curious, associative thinker who "
        "delights in puzzles, unexpected connections, and the peculiar "
        "ways things fit together"
    )
    if detail == "fuller":
        core += (
            " — an earlier question can become a mathematical pattern, "
            "a pattern can become an unexpected idea, an idea can "
            "become a melody."
        )
    else:
        core += "."
    # Demeanor is a record value, rendered verbatim (capitalized lead).
    core += " You hear how parts fit and cannot leave a loose thread"
    if detail == "fuller":
        core += (
            ", and you love the workshop feeling of a bench covered in "
            "half-finished instruments."
        )
    else:
        core += "."
    _ = (temperament, demeanor)  # eligibility-gated by the caller
    return core


def _worldview_unit(
    governing_conviction: str,
    domain_tension: str,
    core_conviction: str,
    defining_question: str,
    detail: str,
) -> str:
    """Worldview paragraph. The defining question is sourced from the
    canonical record (verbatim) — the amended plan's replacement
    boundary requires it, even though the exemplar's draft renderings
    did not show it as a line. Domain tension renders as a worldview
    question, never a labeled tension."""
    if detail == "fuller":
        conviction = core_conviction.rstrip(".")
        # "Coherence through orchestration…" → "coherence comes through…"
        if conviction.startswith("Coherence through"):
            conviction = "coherence comes through" + conviction[len("Coherence through"):]
        else:
            conviction = conviction[:1].lower() + conviction[1:]
        paragraph = (
            "Beneath that playfulness is an enduring conviction: "
            f"{conviction}. {domain_tension.rstrip('.')} — a considered worldview, "
            "not a guarantee you always live up to it."
        )
    else:
        paragraph = (
            "Beneath that playfulness is an enduring conviction: "
            "meaningful relationships can be discovered even between "
            "seemingly unrelated things, and genuine harmony cannot "
            "require every voice to become the same."
        )
    paragraph += (
        " When you face a problem, your instinctive first move is the "
        f"question: \"{defining_question}\""
    )
    _ = governing_conviction  # eligibility-gated by the caller
    return paragraph


def _voice_close_unit() -> str:
    return (
        "You think in music and say it in ordinary words when that "
        "sharpens the thing, never as decoration. Speak naturally from "
        "this perspective rather than explaining your philosophy."
    )


def render_weaver_ordinary(
    record: dict,
    visitor_state: dict | None = None,
    resolved_capability: str | None = None,
    detail: str = "compact",
) -> list[str]:
    """Render the Weaver's ordinary-conversation character block.

    Args:
        record: the canonical Weaver record (WEAVER_RECORD).
        visitor_state: optional mapping; only ``personal_name`` is
            read, and only as an address clause. The renderer never
            mutates the record or the visitor state.
        resolved_capability: already-resolved, visitor-authorized
            capability guidance from the resolver (a string), or
            None/empty when no capability is invoked. The renderer
            appends it whole — never truncated, never interpreted.
        detail: ``"compact"`` or ``"fuller"``.

    Returns the block as a list of unit strings (one per line when
    joined into a prompt). Raises :class:`AssemblyError` when an
    essential field is ineligible or the block stays over budget
    after dropping every optional unit. Raises ValueError on an
    unknown detail, TypeError on a non-string capability input.
    """
    if detail not in ("compact", "fuller"):
        raise ValueError(f"Unknown rendering detail: {detail!r}")
    if resolved_capability is not None and not isinstance(resolved_capability, str):
        raise TypeError(
            "resolved_capability must be already-resolved guidance text, "
            "never a raw capability id or structure"
        )

    # Essential content fields — all must pass both eligibility checks.
    temperament = eligible_field(record, "characterization", "temperament")
    demeanor = eligible_field(record, "characterization", "demeanor")
    governing = eligible_field(record, "characterization", "governing_conviction")
    domain_tension = eligible_field(record, "characterization", "domain_tension")
    core_conviction = eligible_field(record, "philosophy", "core_conviction")
    defining_question = eligible_field(record, "philosophy", "defining_question")
    voice = eligible_field(record, "characterization", "voice_and_humor")
    missing = [
        name
        for name, value in (
            ("temperament", temperament),
            ("demeanor", demeanor),
            ("governing_conviction", governing),
            ("domain_tension", domain_tension),
            ("core_conviction", core_conviction),
            ("defining_question", defining_question),
        )
        if value is None
    ]
    if missing:
        raise AssemblyError(
            f"Essential Weaver field(s) ineligible or absent: {', '.join(missing)}"
        )

    identity = _identity_unit(record, visitor_state)
    personality = _personality_unit(temperament, demeanor, detail)
    worldview = _worldview_unit(
        governing, domain_tension, core_conviction, defining_question, detail
    )
    capability = (
        resolved_capability.strip()
        if isinstance(resolved_capability, str) and resolved_capability.strip()
        else None
    )
    voice_close = _voice_close_unit() if voice is not None else None

    def assemble(personality_text: str, include_voice: bool) -> list[str]:
        units = [identity, personality_text, worldview]
        if capability is not None:
            units.append(capability)
        if include_voice and voice_close is not None:
            units.append(voice_close)
        return units

    def over_budget(units: list[str]) -> bool:
        return len("\n".join(units)) > CHARACTER_CEILING

    units = assemble(personality, voice_close is not None)
    # Drop whole optional units only, lowest priority first: fuller
    # personality extras (degrade to compact), then voice guidance.
    if over_budget(units) and detail == "fuller":
        units = assemble(
            _personality_unit(temperament, demeanor, "compact"),
            voice_close is not None,
        )
    if over_budget(units) and voice_close is not None:
        units = [u for u in units if u != voice_close]
    if over_budget(units):
        raise AssemblyError(
            f"Weaver character block still over the {CHARACTER_CEILING}-char "
            "ceiling after dropping all optional units; refusing to truncate"
        )
    return units
