"""
Optional operator brief for council alignment (file-based, not workspace translation).

- Operator priority: short, concrete preference block for fast council (what we optimize for,
  tradeoffs, constraints). Used in council packet only; label "Operator priorities:".
  Source: ``operator_brand_brief.md`` next to this module unless disabled (see env below).
- Philosophical orientation: mission/worldview/values. Folded into the taste layer:
  injected alongside tasteCompass for the four taste-relative council seats
  (Seer, Songwriter, Storyteller, Mediator). Guide/Patternist/Maker have no taste
  channel and never receive it.

Environment:

- ``ZENAF_OPERATOR_BRIEF_ENABLED`` — If ``0``, ``false``, ``no``, or ``off`` (case-insensitive),
  operator priority and philosophical orientation loaders return empty strings without reading
  the file (even if present). Default when unset: enabled (backward compatible).
"""

import os
from pathlib import Path

# Operator priority: keep council block short and concrete (max words in source section).
MAX_OPERATOR_PRIORITY_WORDS = 120
# Philosophical orientation: longer, for optional use outside fast council.
MAX_PHILOSOPHICAL_WORDS = 300

_BRIEF_NAME = "operator_brand_brief.md"
_cache_priority: str | None = None
_cache_philosophy: str | None = None


def _operator_brief_loading_enabled() -> bool:
    raw = (os.environ.get("ZENAF_OPERATOR_BRIEF_ENABLED", "") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def _read_brief() -> str:
    """Read raw brief content; empty string if missing or unreadable."""
    try:
        base = Path(__file__).resolve().parent
        path = base / _BRIEF_NAME
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _extract_section(text: str, section_markers: tuple[str, ...], max_words: int) -> str:
    """
    Find first section whose heading is in section_markers; return its body, capped at max_words.
    Body is from end of heading line until next ## or end of file.
    """
    for marker in section_markers:
        idx = text.find(marker)
        if idx == -1:
            continue
        rest = text[idx + len(marker) :].strip()
        next_h = rest.find("\n## ")
        if next_h != -1:
            rest = rest[:next_h]
        rest = rest.strip()
        if not rest:
            continue
        words = rest.split()
        if len(words) <= max_words:
            return rest
        return " ".join(words[:max_words])
    return ""


def load_operator_priority() -> str:
    """
    Short, concrete operator-priority block for fast council (optimize for, tradeoffs, constraints).
    Sections tried in order: ## Operator priority, ## Priority profile, ## Council context.
    Cached. Returns empty string if disabled via env, file missing, or no section found.
    """
    if not _operator_brief_loading_enabled():
        return ""
    global _cache_priority
    if _cache_priority is not None:
        return _cache_priority
    raw = _read_brief()
    block = _extract_section(
        raw,
        ("## Operator priority", "## Priority profile", "## Council context", "## council context"),
        MAX_OPERATOR_PRIORITY_WORDS,
    ).strip()
    _cache_priority = block
    return _cache_priority


def load_philosophical_orientation() -> str:
    """
    Mission / worldview / values block. Folded into the taste layer: injected alongside
    tasteCompass for the four taste-relative council seats (Seer, Songwriter, Storyteller,
    Mediator) via the persona prompt builder in zenaf_tools.py. Guide/Patternist/Maker
    have no taste channel and never receive it.
    Sections tried: ## Philosophical orientation, ## Mission & worldview, ## Distilled.
    Cached. Returns empty string if disabled via env, file missing, or no section found.
    """
    if not _operator_brief_loading_enabled():
        return ""
    global _cache_philosophy
    if _cache_philosophy is not None:
        return _cache_philosophy
    raw = _read_brief()
    block = _extract_section(
        raw,
        ("## Philosophical orientation", "## Mission & worldview", "## Distilled"),
        MAX_PHILOSOPHICAL_WORDS,
    ).strip()
    _cache_philosophy = block
    return _cache_philosophy


def load_operator_context() -> str:
    """
    Returns the operator priority block. This is the primary entry point;
    call load_operator_priority() or load_philosophical_orientation() explicitly for clarity.
    """
    return load_operator_priority()
