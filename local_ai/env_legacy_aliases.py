"""
Environment variable aliases (previously bridged legacy ATRIA_* names).

Clean break 2026-10-16: the ATRIA_* fallbacks have been removed. This module
is kept as a no-op so existing imports don't break.
"""

from __future__ import annotations

import os

# No legacy aliases remain. Tuples kept (empty) for API compatibility.
_ACCOUNT_VENDOR_ALIASES: tuple[tuple[str, str], ...] = ()

# (zenaf_name, atria_name) — all Atria fallbacks removed in the clean break.
_ALIASES: tuple[tuple[str, str], ...] = ()


def is_legacy_atria_import_disabled() -> bool:
    """
    Deprecated: always returns True (legacy Atria import is permanently disabled).
    Kept for backward compatibility with any remaining callers.
    """
    return True


def apply_zenaf_env_legacy_aliases() -> list[tuple[str, str]]:
    """
    Apply aliases in-process. Returns list of (dest_key, source_key) pairs that were applied.
    """
    applied: list[tuple[str, str]] = []
    for zenaf, atria in _ALIASES:
        cur = (os.environ.get(zenaf) or "").strip()
        if cur:
            continue
        legacy = (os.environ.get(atria) or "").strip()
        if not legacy:
            continue
        os.environ[zenaf] = os.environ[atria]
        applied.append((zenaf, atria))
    for primary, legacy in _ACCOUNT_VENDOR_ALIASES:
        cur = (os.environ.get(primary) or "").strip()
        if cur:
            continue
        leg = (os.environ.get(legacy) or "").strip()
        if not leg:
            continue
        os.environ[primary] = os.environ[legacy]
        applied.append((primary, legacy))
    return applied
