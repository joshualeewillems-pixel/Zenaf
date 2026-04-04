"""
Brand Profile: operator-defined identity fields formatted for Brand seat council injection.

Loaded from ``brand-profile.json`` beside ``translation-template.json`` under
``.atria/workspace-identity/v1/``. Merged into the Brand seat persona at persona-build time
(see ``_build_council_persona_block`` in ``atria_tools``), which prefixes the merged body with
``Reference context:``. Wording below is written as **constraints** so the model treats the
profile as binding for that seat.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BRAND_PROFILE_FILENAME = "brand-profile.json"

_MAX_MISSION_CHARS = 8000
_MAX_BODY_CHARS = 4000
_MAX_NOTES_CHARS = 4000
_MAX_DISPLAY_NAME_CHARS = 200
_MAX_AVOID_ITEMS = 24
_MAX_EXAMPLE_ITEMS = 16
_MAX_LINE_CHARS = 800

_brand_cache_path: str | None = None
_brand_cache_mtime: float | None = None
_brand_cache_profile: dict[str, Any] = {}


def _default_identity_v1_dir() -> Path:
    return Path(__file__).resolve().parents[2] / ".atria" / "workspace-identity" / "v1"


def brand_profile_path(base_dir: Path | None = None) -> Path:
    """Path to ``brand-profile.json`` (``base_dir`` defaults to workspace-identity ``v1``)."""
    return (base_dir or _default_identity_v1_dir()) / BRAND_PROFILE_FILENAME


def _cap_str(s: str, max_len: int) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _cap_lines(items: list[str], max_items: int, max_line: int) -> list[str]:
    out: list[str] = []
    for x in items[:max_items]:
        t = _cap_str(x, max_line)
        if t:
            out.append(t)
    return out


def read_brand_profile(base_dir: Path | None = None) -> dict[str, Any]:
    """
    Read ``brand-profile.json`` from workspace identity ``v1``.

    Returns a normalized dict (possibly empty). Missing or invalid files yield ``{}``.
    Cached on file mtime for the resolved path.
    """
    global _brand_cache_path, _brand_cache_mtime, _brand_cache_profile
    path = brand_profile_path(base_dir)
    try:
        st = path.stat()
        mtime = st.st_mtime
    except OSError:
        return {}

    path_key = str(path.resolve())
    if _brand_cache_path == path_key and _brand_cache_mtime == mtime and _brand_cache_profile:
        return dict(_brand_cache_profile)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[brand-profile] read failed %s: %s", path, e)
        return {}

    if not isinstance(raw, dict):
        return {}

    normalized = _normalize_brand_profile(raw)
    _brand_cache_path = path_key
    _brand_cache_mtime = mtime
    _brand_cache_profile = normalized
    return dict(normalized)


def describe_brand_profile_preflight(base_dir: Path | None = None) -> dict[str, Any]:
    """Compact status for council debug / preflight (one read per call; uses cache inside ``read_brand_profile``)."""
    path = brand_profile_path(base_dir)
    profile = read_brand_profile(base_dir)
    dn = profile.get("displayName") if profile else None
    dn_out = str(dn).strip() if dn is not None else ""
    return {
        "brand_profile_loaded": bool(profile),
        "brand_profile_display_name": dn_out or None,
        "brand_profile_path": str(path.resolve()),
    }


def _s(val: Any) -> str:
    if val is None:
        return ""
    t = str(val).strip()
    return t


def _lines_list(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    return [str(x).strip() for x in val if str(x).strip()]


def _normalize_brand_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep load-bearing keys only; cap lengths for prompt safety."""
    mission = _cap_str(
        _s(raw.get("missionStatement") or raw.get("mission_statement")),
        _MAX_MISSION_CHARS,
    )
    audience = _cap_str(_s(raw.get("audience")), _MAX_BODY_CHARS)
    positioning = _cap_str(_s(raw.get("positioning")), _MAX_BODY_CHARS)
    tone = _cap_str(
        _s(raw.get("toneGuidelines") or raw.get("tone_guidelines") or raw.get("tone")),
        _MAX_BODY_CHARS,
    )
    notes = _cap_str(_s(raw.get("notes")), _MAX_NOTES_CHARS)
    display_name = _cap_str(_s(raw.get("displayName") or raw.get("display_name")), _MAX_DISPLAY_NAME_CHARS)

    avoid = _lines_list(raw.get("avoid"))
    if not avoid:
        avoid = _lines_list(raw.get("tabooOrAvoid") or raw.get("taboo_or_avoid"))
    avoid = _cap_lines(avoid, _MAX_AVOID_ITEMS, _MAX_LINE_CHARS)

    lang = _cap_lines(_lines_list(raw.get("languagePreferences") or raw.get("language_preferences")), 16, _MAX_LINE_CHARS)

    examples = _lines_list(raw.get("examplePhrases") or raw.get("example_phrases"))
    examples = _cap_lines(examples, _MAX_EXAMPLE_ITEMS, _MAX_LINE_CHARS)

    out: dict[str, Any] = {}
    if display_name:
        out["displayName"] = display_name
    if mission:
        out["missionStatement"] = mission
    if audience:
        out["audience"] = audience
    if positioning:
        out["positioning"] = positioning
    if tone:
        out["toneGuidelines"] = tone
    if avoid:
        out["avoid"] = avoid
    if lang:
        out["languagePreferences"] = lang
    if examples:
        out["examplePhrases"] = examples
    if notes:
        out["notes"] = notes
    return out


def format_brand_profile_context(profile: dict[str, Any] | None) -> str:
    """
    Format a Brand Profile dict as a single constraint block for the Brand council seat.

    Accepts camelCase or snake_case keys. Returns empty string if nothing substantive is present.
    """
    if not profile or not isinstance(profile, dict):
        return ""

    mission = _s(profile.get("missionStatement") or profile.get("mission_statement"))
    audience = _s(profile.get("audience"))
    positioning = _s(profile.get("positioning"))
    tone = _s(profile.get("toneGuidelines") or profile.get("tone_guidelines") or profile.get("tone"))
    avoid = _lines_list(profile.get("avoid"))
    if not avoid:
        avoid = _lines_list(profile.get("tabooOrAvoid") or profile.get("taboo_or_avoid"))

    lang = _lines_list(profile.get("languagePreferences") or profile.get("language_preferences"))
    examples = _lines_list(profile.get("examplePhrases") or profile.get("example_phrases"))
    notes = _s(profile.get("notes"))

    if not any([mission, audience, positioning, tone, avoid, lang, examples, notes]):
        return ""

    lines: list[str] = [
        "Brand identity constraints (must guide all reasoning in this seat):",
        "",
        "These are mandatory constraints for this seat, not optional background. Apply them to every "
        "judgment, recommendation, and wording choice. If honoring them would conflict with the question "
        "or facts given, say that conflict explicitly instead of silently ignoring these constraints.",
        "",
    ]

    def block(title: str, body: str) -> None:
        lines.extend([title, body, ""])

    if mission:
        block("MISSION (must stay aligned)", mission)
    if audience:
        block("AUDIENCE (must stay aligned)", audience)
    if positioning:
        block("POSITIONING (must stay aligned)", positioning)
    if tone:
        block("TONE (must stay aligned)", tone)
    if lang:
        block("LANGUAGE PREFERENCES (must stay aligned)", "\n".join(f"- {x}" for x in lang))
    if avoid:
        lines.append("MUST AVOID (do not endorse, normalize, or drift toward):")
        lines.extend(f"- {x}" for x in avoid)
        lines.append("")
    if examples:
        block("VOICE SAMPLES (on-brand phrasing only; do not contradict sections above)", "\n".join(f"- {x}" for x in examples))
    if notes:
        block("ADDITIONAL CONSTRAINTS", notes)

    return "\n".join(lines).rstrip()
