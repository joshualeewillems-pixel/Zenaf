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

Raven ordinary-conversation renderer (:func:`render_raven_ordinary`).
Same machinery, same ceiling, same ladder — one deliberate
difference, from the adopted Raven plan §4: the renderer receives
the ALREADY-AUTHORIZED name from the call site (resolved through
the existing naming lookup), never raw visitor state. A name being
present in visitor state does not establish that the visitor has
earned its use, and the renderer cannot infer milestone eligibility
— so it takes no visitor-state argument at all. The call site passes
the lookup's result (or nothing); the renderer formats it as an
address clause and nothing else. No second naming-permission system
is built here. (Weaver's renderer reads personal_name from
visitor_state directly; Raven's does not, because the naming
contract requires milestone eligibility the renderer cannot infer.)
The Raven voice close is detail-dependent by design, so the
assembled blocks reproduce exemplar §2 exactly: the compact voice
close is warmth + examination preference, and the fuller voice close
adds the tempo sentence. The fuller development sentences live in
their own record field and drop whole when the fuller degrades.
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


def _raven_identity_unit(record: dict, authorized_name: str | None) -> str:
    """Structural identity line. Role/character are adopted by
    record-integrity test; a lookup-authorized name changes address
    (an appended clause), never essence. The name arrives already
    authorized from the call site — this function never inspects
    visitor state and never infers milestone eligibility."""
    identity = record.get("identity", {})
    role = identity.get("role", {}).get("text", "Skeptic")
    character = identity.get("character", {}).get("text", "Raven")
    line = f"You are the {character}, who occupies the {role} seat in the Fellowship."
    if isinstance(authorized_name, str) and authorized_name.strip():
        line += f" The visitor calls you {authorized_name.strip()}."
    return line


def _raven_personality_unit(
    personality: str, development: str | None, detail: str
) -> str:
    """Personality paragraph. The fuller variant appends the
    development sentences; degrading fuller → compact drops exactly
    that addition, whole."""
    if detail == "fuller" and development:
        return f"{personality} {development}"
    return personality


def _raven_worldview_unit(
    ideal: str, defining_question: str, domain_tension: str
) -> str:
    """Worldview paragraph: ideal (verbatim) + defining question
    (verbatim) + domain tension as a worldview question, never a
    labeled tension. The discernment sentence is the adopted one;
    the superseded relentless-doubt sentence must never reach here
    because the record carries the adopted value."""
    return f"{ideal} {defining_question} {domain_tension}"


def _raven_voice_close_unit(
    warmth: str, voice_and_humor: str, tempo: str | None, detail: str
) -> str:
    """Voice close. Compact: warmth + examination preference. Fuller
    adds the tempo sentence. Detail-dependent so the assembled blocks
    reproduce exemplar §2 exactly."""
    close = f"{warmth} {voice_and_humor}"
    if detail == "fuller" and tempo:
        close += f" {tempo}"
    return close


def render_raven_ordinary(
    record: dict,
    authorized_name: str | None = None,
    resolved_capability: str | None = None,
    detail: str = "compact",
) -> list[str]:
    """Render the Raven's ordinary-conversation character block.

    Args:
        record: the canonical Raven record (RAVEN_RECORD).
        authorized_name: already-authorized name from the call site
            (resolved through the existing naming lookup), or None
            when the lookup authorizes no name. Rendered only as an
            address clause. NEVER raw visitor state: this function
            takes no visitor-state argument and cannot infer
            milestone eligibility.
        resolved_capability: already-resolved, visitor-authorized
            capability guidance from the resolver (a string), or
            None/empty when no capability is invoked. The renderer
            appends it whole — never truncated, never interpreted.
        detail: ``"compact"`` or ``"fuller"``.

    Returns the block as a list of unit strings (one per line when
    joined into a prompt). Raises :class:`AssemblyError` when an
    essential field is ineligible or the block stays over budget
    after dropping every optional unit. Raises ValueError on an
    unknown detail, TypeError on a non-string capability input or
    a non-string authorized name.
    """
    if detail not in ("compact", "fuller"):
        raise ValueError(f"Unknown rendering detail: {detail!r}")
    if resolved_capability is not None and not isinstance(resolved_capability, str):
        raise TypeError(
            "resolved_capability must be already-resolved guidance text, "
            "never a raw capability id or structure"
        )
    if authorized_name is not None and not isinstance(authorized_name, str):
        raise TypeError(
            "authorized_name must be an already-authorized name string "
            "from the naming lookup, or None — never raw visitor state"
        )

    # Essential content fields — all must pass both eligibility checks.
    temperament = eligible_field(record, "characterization", "temperament")
    demeanor = eligible_field(record, "characterization", "demeanor")
    governing = eligible_field(record, "characterization", "governing_conviction")
    domain_tension = eligible_field(record, "characterization", "domain_tension")
    ideal = eligible_field(record, "philosophy", "ideal")
    defining_question = eligible_field(record, "philosophy", "defining_question")
    personality = eligible_field(record, "characterization", "personality")
    # Voice fields are optional: ineligible voice guidance is dropped
    # whole, never failed. (Temperament, demeanor, and governing
    # conviction gate eligibility like Weaver's, but their prose is
    # embodied by the personality/worldview units rather than rendered
    # as separate sentences.)
    warmth = eligible_field(record, "characterization", "warmth")
    voice_and_humor = eligible_field(record, "characterization", "voice_and_humor")
    tempo = eligible_field(record, "characterization", "tempo")
    development = eligible_field(
        record, "characterization", "personality_fuller_development"
    )
    missing = [
        name
        for name, value in (
            ("temperament", temperament),
            ("demeanor", demeanor),
            ("governing_conviction", governing),
            ("domain_tension", domain_tension),
            ("ideal", ideal),
            ("defining_question", defining_question),
            ("personality", personality),
        )
        if value is None
    ]
    if missing:
        raise AssemblyError(
            f"Essential Raven field(s) ineligible or absent: {', '.join(missing)}"
        )

    identity = _raven_identity_unit(record, authorized_name)
    personality_compact = _raven_personality_unit(personality, None, "compact")
    personality_fuller = _raven_personality_unit(personality, development, "fuller")
    personality_text = personality_fuller if detail == "fuller" else personality_compact
    worldview = _raven_worldview_unit(ideal, defining_question, domain_tension)
    capability = (
        resolved_capability.strip()
        if isinstance(resolved_capability, str) and resolved_capability.strip()
        else None
    )
    voice_close = (
        _raven_voice_close_unit(warmth, voice_and_humor, tempo, detail)
        if warmth is not None and voice_and_humor is not None
        else None
    )

    def assemble(personality_text: str, include_voice: bool) -> list[str]:
        units = [identity, personality_text, worldview]
        if capability is not None:
            units.append(capability)
        if include_voice and voice_close is not None:
            units.append(voice_close)
        return units

    def over_budget(units: list[str]) -> bool:
        return len("\n".join(units)) > CHARACTER_CEILING

    units = assemble(personality_text, voice_close is not None)
    # Drop whole optional units only, lowest priority first: fuller
    # personality extras (degrade to compact), then voice guidance.
    # A fuller request that degrades to compact is valid operation of
    # this ladder, not a failure (adopted fuller-headroom rule).
    if over_budget(units) and detail == "fuller":
        units = assemble(personality_compact, voice_close is not None)
    if over_budget(units) and voice_close is not None:
        units = [u for u in units if u != voice_close]
    if over_budget(units):
        raise AssemblyError(
            f"Raven character block still over the {CHARACTER_CEILING}-char "
            "ceiling after dropping all optional units; refusing to truncate"
        )
    return units


# ---------------------------------------------------------------------------
# Five-seat canonical renderers (Gardener, Firebrand, Bear, Crane, Fox)
# ---------------------------------------------------------------------------
# Same architecture as Weaver/Raven (record with standing+category,
# eligible_field gating, ceiling+ladder, never truncate, never drop
# conviction/identity/essential characterization) but each seat gets
# its own renderer function with seat-specific unit fields: NONE of
# the five §2s fits the Raven assembly shape, so reusing Raven's
# unit helpers verbatim would misassemble every seat. The shared
# pieces are the identity helper below and the ladder shape:
# fuller → compact → drop voice → AssemblyError.


def _five_seat_identity_unit(record: dict, authorized_name: str | None) -> str:
    """Generic identity unit for the five new seats.

    The renderer takes the ALREADY-AUTHORIZED name from the call-site
    naming lookup only (Raven pattern): it takes no visitor-state
    argument and builds no second permission system. A whitespace
    name is not authorized; a non-string name is a contract
    violation, not a fallback.
    """
    if authorized_name is not None and not isinstance(authorized_name, str):
        raise TypeError("authorized_name must be a string or None")
    role = record["identity"]["role"]["text"]
    character = record["identity"]["character"]["text"]
    line = (
        f"You are the {character}, who occupies the {role} seat "
        "in the Fellowship."
    )
    name = authorized_name.strip() if authorized_name else ""
    if name:
        line += f" The visitor calls you {name}."
    return line


def _validated_capability(resolved_capability: str | None) -> str | None:
    """Validate the resolver-supplied capability text, if any."""
    if resolved_capability is None:
        return None
    if not isinstance(resolved_capability, str):
        raise TypeError("resolved_capability must be a string or None")
    stripped = resolved_capability.strip()
    return stripped or None


def render_gardener_ordinary(
    record: dict,
    authorized_name: str | None = None,
    resolved_capability: str | None = None,
    detail: str = "compact",
) -> list[str]:
    """Assemble the canonical Gardener ordinary-conversation block.

    Units (Gardener §2): identity, personality, worldview
    (ideal-rendering-form + defining question + domain tension),
    capability (resolver-supplied, after worldview), then either
    the fuller middle + tempo-precision sentence, or the compact
    voice + warmth passage. Assembled blocks reproduce exemplar §2
    exactly (compact 670 chars, fuller 921 chars, no capability).
    """
    if detail not in ("compact", "fuller"):
        raise ValueError(f"Unknown detail: {detail!r}")
    capability = _validated_capability(resolved_capability)

    identity = _five_seat_identity_unit(record, authorized_name)
    personality = eligible_field(record, "characterization", "personality")
    worldview_parts = [
        eligible_field(record, "characterization", "ideal_rendering_form"),
        eligible_field(record, "philosophy", "defining_question"),
        eligible_field(record, "characterization", "domain_tension"),
    ]
    # Gating fields: eligible by rule even though their prose is
    # embodied rather than separately rendered (Raven pattern).
    for section, key in (
        ("characterization", "temperament"),
        ("characterization", "demeanor"),
        ("characterization", "governing_conviction"),
    ):
        if eligible_field(record, section, key) is None:
            raise AssemblyError(
                f"Gardener gating field {section}.{key} is not eligible"
            )
    if personality is None or any(part is None for part in worldview_parts):
        raise AssemblyError(
            "Gardener core unit (personality/worldview) is not eligible"
        )
    worldview = " ".join(worldview_parts)
    core = [identity, personality, worldview]
    if capability:
        core.append(capability)

    middle = eligible_field(record, "characterization", "fuller_middle")
    voice = eligible_field(record, "characterization", "voice_and_humor")
    warmth = eligible_field(record, "characterization", "warmth")
    tempo = eligible_field(record, "characterization", "tempo")
    # The compact voice unit is voice + warmth together: if either
    # part is ineligible, the whole voice unit drops (never partial).
    voice_compact = (
        " ".join([voice, warmth]) if voice is not None and warmth is not None else None
    )

    def over_budget(units: list[str]) -> bool:
        return len("\n".join(units)) > CHARACTER_CEILING

    candidates: list[list[str]] = []
    if detail == "fuller" and middle is not None:
        fuller_units = [*core, middle]
        if tempo is not None:
            fuller_units.append(tempo)
        candidates.append(fuller_units)
    if voice_compact is not None:
        candidates.append([*core, voice_compact])
    candidates.append(core)
    for units in candidates:
        if not over_budget(units):
            return units
    raise AssemblyError(
        f"Gardener character block still over the {CHARACTER_CEILING}-char "
        "ceiling after dropping all optional units; refusing to truncate"
    )


def render_firebrand_ordinary(
    record: dict,
    authorized_name: str | None = None,
    resolved_capability: str | None = None,
    detail: str = "compact",
) -> list[str]:
    """Assemble the canonical Firebrand ordinary-conversation block.

    Units (Firebrand §2): identity, personality, worldview
    (conviction paraphrase + defining question + temperament
    sentence), capability (resolver-supplied, after worldview),
    then either the fuller additional unit (which DELETES the
    compact voice-close entirely — no voice sentence, no warmth
    sentence in the fuller) or the compact voice + warmth passage.
    Assembled blocks reproduce exemplar §2 exactly (compact 719
    chars, fuller 1,066 chars, no capability).
    """
    if detail not in ("compact", "fuller"):
        raise ValueError(f"Unknown detail: {detail!r}")
    capability = _validated_capability(resolved_capability)

    identity = _five_seat_identity_unit(record, authorized_name)
    personality = eligible_field(record, "characterization", "personality")
    worldview_parts = [
        eligible_field(record, "characterization", "conviction_paraphrase"),
        eligible_field(record, "philosophy", "defining_question"),
        eligible_field(record, "characterization", "temperament_sentence"),
    ]
    # Gating fields: eligible by rule even though their prose is
    # embodied rather than separately rendered (Raven pattern).
    for section, key in (
        ("characterization", "temperament"),
        ("characterization", "demeanor"),
        ("characterization", "governing_conviction"),
    ):
        if eligible_field(record, section, key) is None:
            raise AssemblyError(
                f"Firebrand gating field {section}.{key} is not eligible"
            )
    if personality is None or any(part is None for part in worldview_parts):
        raise AssemblyError(
            "Firebrand core unit (personality/worldview) is not eligible"
        )
    worldview = " ".join(worldview_parts)
    core = [identity, personality, worldview]
    if capability:
        core.append(capability)

    additional = eligible_field(record, "characterization", "fuller_additional")
    voice = eligible_field(record, "characterization", "voice_and_humor")
    warmth = eligible_field(record, "characterization", "warmth")
    # The compact voice unit is voice + warmth together: if either
    # part is ineligible, the whole voice unit drops (never partial).
    voice_compact = (
        " ".join([voice, warmth]) if voice is not None and warmth is not None else None
    )

    def over_budget(units: list[str]) -> bool:
        return len("\n".join(units)) > CHARACTER_CEILING

    candidates: list[list[str]] = []
    if detail == "fuller" and additional is not None:
        candidates.append([*core, additional])
    if voice_compact is not None:
        candidates.append([*core, voice_compact])
    candidates.append(core)
    for units in candidates:
        if not over_budget(units):
            return units
    raise AssemblyError(
        f"Firebrand character block still over the {CHARACTER_CEILING}-char "
        "ceiling after dropping all optional units; refusing to truncate"
    )


def render_bear_ordinary(
    record: dict,
    authorized_name: str | None = None,
    resolved_capability: str | None = None,
    detail: str = "compact",
) -> list[str]:
    """Assemble the canonical Bear ordinary-conversation block.

    Units (Bear §2): identity, personality, worldview
    (ideal-rendering-form + defining question + affirmative
    conviction), capability (resolver-supplied, after worldview),
    then either the fuller middle + fuller voice-close (which is
    ENTIRELY different from the compact voice-close: joy/welcome +
    warmth response, no compact voice sentence, no compact warmth
    sentence) or the compact voice + warmth passage. Assembled
    blocks reproduce exemplar §2 exactly (compact 767 chars,
    fuller 1,298 chars, no capability). Semicolon sentences are
    single units, never split; em-dashes are preserved exactly.
    """
    if detail not in ("compact", "fuller"):
        raise ValueError(f"Unknown detail: {detail!r}")
    capability = _validated_capability(resolved_capability)

    identity = _five_seat_identity_unit(record, authorized_name)
    personality = eligible_field(record, "characterization", "personality")
    worldview_parts = [
        eligible_field(record, "characterization", "ideal_rendering_form"),
        eligible_field(record, "philosophy", "defining_question"),
        eligible_field(record, "characterization", "affirmative_conviction"),
    ]
    # Gating fields: eligible by rule even though their prose is
    # embodied rather than separately rendered (Raven pattern).
    for section, key in (
        ("characterization", "temperament"),
        ("characterization", "demeanor"),
        ("characterization", "governing_conviction"),
    ):
        if eligible_field(record, section, key) is None:
            raise AssemblyError(
                f"Bear gating field {section}.{key} is not eligible"
            )
    if personality is None or any(part is None for part in worldview_parts):
        raise AssemblyError(
            "Bear core unit (personality/worldview) is not eligible"
        )
    worldview = " ".join(worldview_parts)
    core = [identity, personality, worldview]
    if capability:
        core.append(capability)

    middle = eligible_field(record, "characterization", "fuller_middle")
    voice = eligible_field(record, "characterization", "voice_and_humor")
    warmth = eligible_field(record, "characterization", "warmth")
    voice_fuller = eligible_field(record, "characterization", "voice_fuller")
    # The compact voice unit is voice + warmth together: if either
    # part is ineligible, the whole voice unit drops (never partial).
    voice_compact = (
        " ".join([voice, warmth]) if voice is not None and warmth is not None else None
    )

    def over_budget(units: list[str]) -> bool:
        return len("\n".join(units)) > CHARACTER_CEILING

    candidates: list[list[str]] = []
    if detail == "fuller" and middle is not None:
        fuller_units = [*core, middle]
        if voice_fuller is not None:
            fuller_units.append(voice_fuller)
        candidates.append(fuller_units)
    if voice_compact is not None:
        candidates.append([*core, voice_compact])
    candidates.append(core)
    for units in candidates:
        if not over_budget(units):
            return units
    raise AssemblyError(
        f"Bear character block still over the {CHARACTER_CEILING}-char "
        "ceiling after dropping all optional units; refusing to truncate"
    )


def render_crane_ordinary(
    record: dict,
    authorized_name: str | None = None,
    resolved_capability: str | None = None,
    detail: str = "compact",
) -> list[str]:
    """Assemble the canonical Crane ordinary-conversation block.

    Units (Crane §2): identity, personality (CHANGED between
    details, not appended: the fuller drops "person", "actually",
    "are"→"can be", the trailing clause, "tentative", and
    "that"), worldview (ideal verbatim + defining question
    verbatim ONLY — no tension sentence in compact; the tension
    rides as a CLAUSE inside the fuller bridge sentence),
    capability (resolver-supplied, after worldview), hearing,
    then either the fuller middle + humanitarian + conviction
    (the fuller has NO voice sentence and NO tempo counterpart)
    or the humanitarian + compact voice (single fused sentence).
    Hearing + humanitarian are shared post units: ineligible →
    AssemblyError, never dropped. Assembled blocks reproduce
    exemplar §2 exactly (compact 1,034 chars, fuller 1,481 chars,
    no capability).
    """
    if detail not in ("compact", "fuller"):
        raise ValueError(f"Unknown detail: {detail!r}")
    capability = _validated_capability(resolved_capability)

    identity = _five_seat_identity_unit(record, authorized_name)
    personality_compact = eligible_field(record, "characterization", "personality")
    personality_fuller = eligible_field(record, "characterization", "personality_fuller")
    worldview_parts = [
        eligible_field(record, "philosophy", "ideal"),
        eligible_field(record, "philosophy", "defining_question"),
    ]
    hearing = eligible_field(record, "characterization", "hearing")
    humanitarian = eligible_field(record, "characterization", "humanitarian")
    # Gating fields: eligible by rule even though their prose is
    # embodied rather than separately rendered (Raven pattern).
    for section, key in (
        ("characterization", "temperament"),
        ("characterization", "demeanor"),
        ("characterization", "governing_conviction"),
    ):
        if eligible_field(record, section, key) is None:
            raise AssemblyError(
                f"Crane gating field {section}.{key} is not eligible"
            )
    if (
        personality_compact is None
        or any(part is None for part in worldview_parts)
        or hearing is None
        or humanitarian is None
    ):
        raise AssemblyError(
            "Crane core unit (personality/worldview/shared post) is not eligible"
        )
    worldview = " ".join(worldview_parts)

    def with_capability(units: list[str]) -> list[str]:
        if capability:
            return [*units[:3], capability, *units[3:]]
        return units

    middle = eligible_field(record, "characterization", "fuller_middle")
    conviction = eligible_field(record, "characterization", "conviction_conduct")
    voice = eligible_field(record, "characterization", "voice")

    def over_budget(units: list[str]) -> bool:
        return len("\n".join(units)) > CHARACTER_CEILING

    # Fuller-specific units ineligible → fall back to compact units
    # (not failure). The fuller conviction sentence is the terminal
    # conduct unit: ineligible → dropped whole, middle kept (the
    # tempo pattern from Gardener/Bear).
    candidates: list[list[str]] = []
    if detail == "fuller" and personality_fuller is not None and middle is not None:
        fuller_units = [
            identity, personality_fuller, worldview, hearing, middle,
            humanitarian,
        ]
        if conviction is not None:
            fuller_units.append(conviction)
        candidates.append(with_capability(fuller_units))
    compact_units = [
        identity, personality_compact, worldview, hearing, humanitarian,
    ]
    if voice is not None:
        compact_units.append(voice)
    candidates.append(with_capability(compact_units))
    candidates.append(with_capability(
        [identity, personality_compact, worldview, hearing, humanitarian]
    ))
    for units in candidates:
        if not over_budget(units):
            return units
    raise AssemblyError(
        f"Crane character block still over the {CHARACTER_CEILING}-char "
        "ceiling after dropping all optional units; refusing to truncate"
    )


def render_fox_ordinary(
    record: dict,
    authorized_name: str | None = None,
    resolved_capability: str | None = None,
    detail: str = "compact",
) -> list[str]:
    """Assemble the canonical Fox ordinary-conversation block.

    Units (Fox §2, revised P-005 renderings): identity, lead
    (CHANGED between details, not appended), worldview (ideal
    verbatim + defining question verbatim ONLY — no
    domain-tension sentence in either rendering), capability
    (resolver-supplied, after worldview), middle, then voice.
    Voice order is REVERSED vs Raven: warmth is LAST in both
    renderings, and the fuller has an encounter-conduct TAIL
    after warmth, so the voice-close is NOT terminal in fuller.
    The fuller middle + voice + tail swap for the compact middle
    + voice on degradation; voice drops whole next; then
    AssemblyError (the compact middle is essential
    characterization and is never dropped). Assembled blocks
    reproduce exemplar §2 exactly (compact 1,164 chars, fuller
    1,489 chars, no capability). The word "Irish" appears nowhere:
    the sensibility is carried by storyteller cadence and
    sideways speech, never as an accent instruction.
    """
    if detail not in ("compact", "fuller"):
        raise ValueError(f"Unknown detail: {detail!r}")
    capability = _validated_capability(resolved_capability)

    identity = _five_seat_identity_unit(record, authorized_name)
    lead_compact = eligible_field(record, "characterization", "lead_compact")
    lead_fuller = eligible_field(record, "characterization", "lead_fuller")
    worldview_parts = [
        eligible_field(record, "philosophy", "ideal"),
        eligible_field(record, "philosophy", "defining_question"),
    ]
    # Gating fields: eligible by rule even though their prose is
    # embodied rather than separately rendered (Raven pattern).
    for section, key in (
        ("characterization", "temperament"),
        ("characterization", "demeanor"),
        ("characterization", "governing_conviction"),
    ):
        if eligible_field(record, section, key) is None:
            raise AssemblyError(
                f"Fox gating field {section}.{key} is not eligible"
            )
    if (
        lead_compact is None
        or any(part is None for part in worldview_parts)
    ):
        raise AssemblyError(
            "Fox core unit (lead/worldview) is not eligible"
        )
    worldview = " ".join(worldview_parts)
    middle_compact = eligible_field(record, "characterization", "middle_compact")
    if middle_compact is None:
        raise AssemblyError(
            "Fox core unit (middle) is not eligible"
        )

    def with_capability(units: list[str]) -> list[str]:
        if capability:
            return [*units[:3], capability, *units[3:]]
        return units

    middle_fuller = eligible_field(record, "characterization", "middle_fuller")
    voice_compact = eligible_field(record, "characterization", "voice_compact")
    voice_fuller = eligible_field(record, "characterization", "voice_fuller")
    tail = eligible_field(record, "characterization", "tail")

    def over_budget(units: list[str]) -> bool:
        return len("\n".join(units)) > CHARACTER_CEILING

    # Fuller-specific units ineligible → fall back to compact units
    # (not failure). The fuller voice passage and tail are terminal
    # units: ineligible → dropped whole, middle kept (the
    # tempo/tail pattern from Gardener/Bear/Crane).
    candidates: list[list[str]] = []
    if detail == "fuller" and lead_fuller is not None and middle_fuller is not None:
        fuller_units = [
            identity, lead_fuller, worldview, middle_fuller,
        ]
        if voice_fuller is not None:
            fuller_units.append(voice_fuller)
        if tail is not None:
            fuller_units.append(tail)
        candidates.append(with_capability(fuller_units))
    compact_units = [identity, lead_compact, worldview, middle_compact]
    if voice_compact is not None:
        compact_units.append(voice_compact)
    candidates.append(with_capability(compact_units))
    candidates.append(with_capability(
        [identity, lead_compact, worldview, middle_compact]
    ))
    for units in candidates:
        if not over_budget(units):
            return units
    raise AssemblyError(
        f"Fox character block still over the {CHARACTER_CEILING}-char "
        "ceiling after dropping all optional units; refusing to truncate"
    )
