"""
If a ``ZENAF_*`` environment variable is unset, copy from the legacy ``ATRIA_*`` name.

Helps after the product rename when `.env` or deployment still uses old names.
Idempotent; only fills empty ``ZENAF_*`` values.
"""

from __future__ import annotations

import os

# Standard vendor env names used by SDKs / operators; backfill from ATRIA_* after rename.
_ACCOUNT_VENDOR_ALIASES: tuple[tuple[str, str], ...] = (
    ("ANTHROPIC_API_KEY", "ATRIA_ANTHROPIC_API_KEY"),
    ("GOOGLE_API_KEY", "ATRIA_GOOGLE_API_KEY"),
    ("GEMINI_API_KEY", "ATRIA_GEMINI_API_KEY"),
    ("XAI_API_KEY", "ATRIA_XAI_API_KEY"),
)

# (zenaf_name, atria_name) — zenaf wins if already set (even empty string is "set" for strip check)
_ALIASES: tuple[tuple[str, str], ...] = (
    ("ZENAF_SETTINGS_ENCRYPTION_KEY", "ATRIA_SETTINGS_ENCRYPTION_KEY"),
    ("ZENAF_BOOTSTRAP_PASSWORD", "ATRIA_BOOTSTRAP_PASSWORD"),
    ("ZENAF_PHIL_BOOTSTRAP_PASSWORD", "ATRIA_PHIL_BOOTSTRAP_PASSWORD"),
    ("ZENAF_SYSTEM_OPENAI_KEY", "ATRIA_SYSTEM_OPENAI_KEY"),
    ("ZENAF_SYSTEM_ANTHROPIC_API_KEY", "ATRIA_SYSTEM_ANTHROPIC_API_KEY"),
    ("ZENAF_SYSTEM_GOOGLE_API_KEY", "ATRIA_SYSTEM_GOOGLE_API_KEY"),
    ("ZENAF_SYSTEM_XAI_API_KEY", "ATRIA_SYSTEM_XAI_API_KEY"),
    ("ZENAF_SYSTEM_EXECUTION_KEY", "ATRIA_SYSTEM_EXECUTION_KEY"),
    ("ZENAF_COUNCIL_MODEL", "ATRIA_COUNCIL_MODEL"),
    ("ZENAF_SOIL_ROOT", "ATRIA_SOIL_ROOT"),
    ("ZENAF_LEARNING_PERSIST_PATH", "ATRIA_LEARNING_PERSIST_PATH"),
    ("ZENAF_LEARNING_PERSIST_MAX_MB", "ATRIA_LEARNING_PERSIST_MAX_MB"),
    ("ZENAF_OPERATOR_BRIEF_ENABLED", "ATRIA_OPERATOR_BRIEF_ENABLED"),
    ("ZENAF_WORKSPACE_LABEL", "ATRIA_WORKSPACE_LABEL"),
    ("ZENAF_VE_DB", "ATRIA_VE_DB"),
)


def is_legacy_atria_import_disabled() -> bool:
    """
    When true (env ``ZENAF_DISABLE_LEGACY_ATRIA_IMPORT`` = 1/true/yes/on):

    - Skip copying ``~/.atria`` and repo ``.atria/workspace-identity`` into ``.zenaf`` (API startup).
    - Skip mirroring LLM profile/credentials from ``owner@local.atria`` / ``phil@local.atria`` into Zenaf accounts.

    Browser localStorage migration in the frontend is unchanged (runs in the client only).
    """
    v = (os.environ.get("ZENAF_DISABLE_LEGACY_ATRIA_IMPORT") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


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
