"""
Hosted-mode configuration for Zenaf.

Local-first remains the default: when none of the ZENAF_* variables below are
set, every function here returns the historical dev behavior and nothing
changes. Setting ZENAF_PROD=1 switches the app into production mode with
hardened defaults — and fails fast at startup when required secrets are
missing.

Environment variables:
    ZENAF_PROD=1                 Enable production mode.
    ZENAF_SECRET_KEY             REQUIRED in prod. App secret (sessions, signing).
    ZENAF_BOOTSTRAP_PASSWORD     REQUIRED in prod. Initial owner account password.
    ZENAF_DB_DIR                 Override the data directory (hosted volume).
    ZENAF_DATA_DIR               Test/hermetic override; wins over ZENAF_DB_DIR.
    ZENAF_LLM_PROVIDER           Default LLM provider id (default: ollama).
                                 Honored by the provider resolver when the user
                                 profile has no explicit default. API keys come
                                 from the existing env names (OPENAI_API_KEY,
                                 ANTHROPIC_API_KEY, GOOGLE_API_KEY, XAI_API_KEY,
                                 or the ZENAF_SYSTEM_* variants).
    PORT                         Listen port (default: 8010).

This module is stdlib-only and has no imports from the rest of local_ai, so it
is safe to import first (api/main.py does so before any router imports).
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def is_prod() -> bool:
    """True when ZENAF_PROD=1 (or true/yes/on)."""
    return (os.environ.get("ZENAF_PROD") or "").strip().lower() in _TRUE_VALUES


def secret_key() -> str:
    """App secret from ZENAF_SECRET_KEY (empty when unset)."""
    return (os.environ.get("ZENAF_SECRET_KEY") or "").strip()


def port() -> int:
    """Listen port from PORT (default 8010)."""
    try:
        return int((os.environ.get("PORT") or "8010").strip())
    except (ValueError, AttributeError):
        return 8010


def data_dir() -> Path:
    """Canonical data directory.

    Precedence: ZENAF_DATA_DIR (tests / hermetic override — never set this in
    prod) > ZENAF_DB_DIR (hosted volume) > repo-local data/ (dev default).
    """
    for var in ("ZENAF_DATA_DIR", "ZENAF_DB_DIR"):
        v = (os.environ.get(var) or "").strip()
        if v:
            return Path(v)
    return _REPO_ROOT / "data"


def default_llm_provider() -> str:
    """Configured default LLM provider id (default: ollama).

    Callers normalize via local_ai.llm.provider_registry.normalize_provider_id.
    This is a default only — an explicit per-user profile setting still wins.
    """
    return (os.environ.get("ZENAF_LLM_PROVIDER") or "ollama").strip().lower() or "ollama"


def session_cookie_secure() -> bool:
    """Session cookies get Secure=True in prod (platform terminates TLS)."""
    return is_prod()


def validate_prod_config() -> None:
    """Fail fast with one clear error when production mode is misconfigured.

    No-op when ZENAF_PROD is unset (local dev).
    """
    if not is_prod():
        return
    problems: list[str] = []
    if not secret_key():
        problems.append(
            "ZENAF_SECRET_KEY is not set. Generate one with: "
            "python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    if not (os.environ.get("ZENAF_BOOTSTRAP_PASSWORD") or "").strip():
        problems.append(
            "ZENAF_BOOTSTRAP_PASSWORD is not set. The dev fallback password "
            "is disabled in production."
        )
    if problems:
        raise RuntimeError(
            "Production configuration invalid (ZENAF_PROD=1):\n- "
            + "\n- ".join(problems)
        )


def _apply_data_dir_alias() -> None:
    """Alias ZENAF_DB_DIR -> ZENAF_DATA_DIR when the latter is unset.

    Some stores honor ZENAF_DATA_DIR (identity) while others anchor to the
    repo data/ dir. The alias lets a single hosted variable work everywhere it
    can; the Docker setup additionally mounts the volume at the repo data/
    dir so every store lands on the volume with no code changes.
    Runs at import time so it precedes any storage-module import.
    """
    if (os.environ.get("ZENAF_DB_DIR") or "").strip() and not (
        os.environ.get("ZENAF_DATA_DIR") or ""
    ).strip():
        os.environ["ZENAF_DATA_DIR"] = os.environ["ZENAF_DB_DIR"].strip()


_apply_data_dir_alias()
