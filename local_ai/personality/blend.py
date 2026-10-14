"""Phase 4: runtime weighting layer — the personality mirror in council seats.

For each council seat, the prompt blends two SEPARATE objects at
prompt-construction time:

  (A) the aspirational default — the built-in persona definition (the ideal
      of the faculty), rendered by the existing seat-prompt builder; and
  (B) the user's published PersonalityProfile — how THEY actually wield
      that faculty (the delta from the ideal).

The two sides are never merged into one object. The blend is structural:
labeled sections in the seat prompt, so the aspirational-vs-actual
comparison stays legible — differentiating the two is itself training
signal (Joshua's directive).

Weighting:
  * Per-strand user-side weight in [0.0, 1.0].
  * Default (auto) scales with profile evidence depth: an empty/thin
    profile means the seat renders exactly as today (pure aspirational).
    Below MIN_EVIDENCE the user section is omitted entirely and the output
    is byte-identical to the unblended seat block.
  * The user can override per strand via the weights API (None = auto).

This module is pure: it never imports the council machinery (no circular
imports). The thin wiring lives next to `_build_council_persona_block`.

The built-in definitions are read-only here — blend functions take the
already-rendered base block (a string), so they cannot mutate the defns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from local_ai.strands import strand_keys

if TYPE_CHECKING:  # pragma: no cover
    from local_ai.personality.schema import PersonalityProfile
    from local_ai.personality.store import PersonalityStore

_STRAND_KEYS: tuple[str, ...] = strand_keys()

#: Below this evidence depth the user side stays fully out — the seat
#: renders exactly as the pure aspirational default (byte-identical).
MIN_EVIDENCE = 0.10

_FINGERPRINT_FIELDS = (
    "risk_bias",
    "exploration_vs_exploitation",
    "time_horizon",
    "evidence_preference",
    "decision_style",
    "conflict_style",
    "failure_tolerance",
)


@dataclass
class BlendContext:
    """Everything one council run needs to blend seats. Resolved once per run."""

    profile: "PersonalityProfile"
    weights: dict[str, float] = field(default_factory=dict)  # strand_key -> user-side weight
    version_count: int = 0
    overrides: dict[str, float | None] = field(default_factory=dict)


def strand_evidence_depth(profile: "PersonalityProfile", strand_key: str) -> float:
    """How much published evidence exists for one strand, in [0.0, 1.0].

    Counts filled "slots" in the strand's profile plus the global voice
    (voice applies to every seat). 15 slots total: 2 reasoning + 7
    fingerprint + 4 list fields (heuristics, domain_map, red_lines,
    examples) + 2 voice.
    """
    sp = profile.strands[strand_key]
    filled = 0
    total = 0

    total += 2
    filled += int(bool(sp.reasoning.descriptors))
    filled += int(bool((sp.reasoning.notes or "").strip()))

    for fname in _FINGERPRINT_FIELDS:
        total += 1
        filled += int(bool((getattr(sp.fingerprint, fname, "") or "").strip()))

    for lst in (sp.heuristics, sp.domain_map, sp.red_lines, sp.examples):
        total += 1
        filled += int(bool(lst))

    total += 2
    filled += int(bool((profile.voice.description or "").strip()))
    filled += int(bool(profile.voice.tags))

    return filled / total if total else 0.0


def default_weight_for_strand(profile: "PersonalityProfile", strand_key: str) -> float:
    """Auto weight: 0 below MIN_EVIDENCE, otherwise the evidence depth."""
    depth = strand_evidence_depth(profile, strand_key)
    if depth < MIN_EVIDENCE:
        return 0.0
    return round(min(1.0, depth), 4)


def resolve_weights(
    store: "PersonalityStore",
    profile: "PersonalityProfile",
) -> tuple[dict[str, float], dict[str, float | None]]:
    """Effective per-strand weights: manual override where set, else auto.

    Returns (effective_weights, overrides). Overrides come from the
    seat_weights table; None means "auto".
    """
    overrides = store.get_weight_overrides()
    effective: dict[str, float] = {}
    for key in _STRAND_KEYS:
        ov = overrides.get(key)
        if ov is None:
            effective[key] = default_weight_for_strand(profile, key)
        else:
            effective[key] = max(0.0, min(1.0, float(ov)))
    return effective, overrides


def resolve_blend_context(
    store: "PersonalityStore",
) -> BlendContext | None:
    """Build the BlendContext for one council run, or None if no blend.

    Returns None when there is no published profile, or when every
    strand's effective weight is 0 (thin/empty profile, or all overridden
    to 0) — callers then render the pure aspirational seat, byte-identical
    to the pre-blend behavior.
    """
    profile = store.get_current()
    if profile is None:
        return None
    effective, overrides = resolve_weights(store, profile)
    if all(w <= 0.0 for w in effective.values()):
        return None
    try:
        version_count = store.version_count()
    except Exception:
        version_count = 0
    return BlendContext(
        profile=profile,
        weights=effective,
        version_count=version_count,
        overrides=overrides,
    )


def _faculty_label(strand_key: str) -> str:
    try:
        from local_ai.strands import strand as _strand

        return _strand(strand_key).faculty
    except Exception:
        return strand_key


def _bullets(items: list[str], max_items: int = 6) -> list[str]:
    return [f"  - {i}" for i in items[:max_items]]


def render_user_section(
    profile: "PersonalityProfile",
    strand_key: str,
    weight: float,
    version_count: int,
) -> str:
    """Render section (B): how this user actually wields the faculty."""

    sp = profile.strands[strand_key]
    lines: list[str] = [
        "---",
        "",
        f"## How this user wields this faculty (observed — user-side weight {weight:.2f})",
        "",
        f"Learned from {version_count} published profile version(s) this user reviewed and approved. "
        "This is how they ACTUALLY use this intelligence style — not the ideal above, the actual. "
        f"The {_faculty_label(strand_key)} seat above is the aspirational standard; what follows is the "
        "person. Where the two differ, that delta is signal, not noise.",
        "",
    ]

    fp = sp.fingerprint
    fp_bits = [
        f"{name}={getattr(fp, name)}"
        for name in _FINGERPRINT_FIELDS
        if (getattr(fp, name, "") or "").strip()
    ]
    if sp.reasoning.descriptors or (sp.reasoning.notes or "").strip():
        rbits = list(sp.reasoning.descriptors)
        if (sp.reasoning.notes or "").strip():
            rbits.append(sp.reasoning.notes.strip())
        lines.append(f"Reasoning patterns: {'; '.join(rbits)}")
    if fp_bits:
        lines.append(f"Decision fingerprint: {'; '.join(fp_bits)}")
    if sp.heuristics:
        lines.append("Heuristics they live by:")
        lines.extend(_bullets(sp.heuristics))
    if sp.domain_map:
        lines.append(
            "Stances: "
            + "; ".join(
                f"{d.domain} — {d.stance}" if d.stance else d.domain for d in sp.domain_map
            )
        )
    if sp.red_lines:
        lines.append("Red lines (never do):")
        for r in sp.red_lines[:6]:
            lines.append(f"  - {r.rule}" + (f" ({r.rationale})" if r.rationale else ""))
    if sp.examples:
        lines.append("In their own patterns:")
        for e in sp.examples[:4]:
            frag = e.fragment.strip() or e.context.strip()
            if frag:
                lines.append(f'  - "{frag}"' + (f" [{e.tag}]" if e.tag else ""))
    voice_bits = []
    if (profile.voice.description or "").strip():
        voice_bits.append(profile.voice.description.strip())
    if profile.voice.tags:
        voice_bits.append("voice tags: " + ", ".join(profile.voice.tags))
    if voice_bits:
        lines.append(f"Their voice: {'; '.join(voice_bits)}")

    lines.extend(
        [
            "",
            "**Blend instruction:** Reason and speak as this seat's aspirational standard "
            "SHAPED by the observed patterns above. Where the user's patterns differ from the "
            "ideal, reflect the user's actual way — the delta is the point. Let the aspirational "
            "sharpen their patterns; do not flatten the person into the generic ideal.",
        ]
    )
    return "\n".join(lines).strip()


def apply_personality_blend(
    base_block: str,
    defn: dict,
    ctx: BlendContext | None,
) -> str:
    """Blend the user profile into an already-rendered seat block.

    Returns `base_block` UNCHANGED (byte-identical) when:
      - ctx is None (no published profile, or all weights 0), or
      - the seat has no strand key (synthesis seats: thinking_partner/zenaf,
        custom non-strand seats), or
      - this strand's effective weight is 0.

    Never mutates `defn` or the built-in definitions.
    """
    if ctx is None:
        return base_block
    strand_key = (defn.get("strand") or "").strip().lower()
    if not strand_key or strand_key not in _STRAND_KEYS:
        return base_block
    weight = ctx.weights.get(strand_key, 0.0)
    if weight <= 0.0:
        return base_block


    framing = (
        f"> This seat blends two lenses: (A) the aspirational ideal of the "
        f"{_faculty_label(strand_key)} faculty below, and (B) how this user actually "
        f"wields it (user-side weight {weight:.2f})."
    )
    user_section = render_user_section(ctx.profile, strand_key, weight, ctx.version_count)
    return f"{framing}\n\n{base_block}\n\n{user_section}".strip()
