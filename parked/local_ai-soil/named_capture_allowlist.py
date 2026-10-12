"""Closed allowlist for capture_source=named_system_capture (spec §6).

Only these names may be used with named_system_capture. New surfaces must be
added here and documented in SOIL_LAYER_FILESYSTEM_SPEC.md — not an open category.
"""

from __future__ import annotations

# Explicit, reviewable ids (snake_case). Do not accept arbitrary strings at call sites.
NAMED_SYSTEM_CAPTURE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "ve_ui_soil_capture",  # future: explicit Vision & Execution UI "save to soil"
        "dev_soil_export",  # explicit dev / operator export tool (e.g. trace → soil)
        "promotion_helper",  # approved helper that records promotion-related notes
    }
)


def validate_named_capture_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise ValueError("capture_name is required when capture_source is named_system_capture")
    if n not in NAMED_SYSTEM_CAPTURE_ALLOWLIST:
        allowed = ", ".join(sorted(NAMED_SYSTEM_CAPTURE_ALLOWLIST))
        raise ValueError(
            f"capture_name {n!r} is not allowed for named_system_capture. "
            f"Allowlist: {allowed}"
        )
    return n
