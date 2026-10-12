"""Proprietary identity permissions for Zenaf.

Every doppelganger gets a signed identity license declaring that all data
derived from the owner — training signals, profiles, snapshots — is the
owner's exclusive property. Granular, revocable consent scopes gate every
use (distillation, rental, takeout, deletion). One-click takeout and a
signed deletion receipt make ownership real, not rhetorical.

Default-deny throughout: nothing happens without an explicit grant, and
every grant can be taken back.
"""
from __future__ import annotations

import os
from pathlib import Path


class LicenseRequired(RuntimeError):
    """No identity license exists. Issue one before importing anything."""


class ScopeDenied(RuntimeError):
    """A required consent scope is not currently granted."""

    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__(
            f"Scope '{scope}' is not granted. Grant it first: "
            f'POST /identity/scopes {{"scope": "{scope}", "action": "grant"}}.'
        )


def identity_data_dir() -> Path:
    """Resolve the identity data directory.

    Honors ZENAF_DATA_DIR (used by tests for hermetic runs); otherwise anchors
    to <repo>/data/identity so the location is stable regardless of cwd.
    """
    override = os.environ.get("ZENAF_DATA_DIR")
    if override:
        return Path(override) / "identity"
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / "data" / "identity"


__all__ = ["LicenseRequired", "ScopeDenied", "identity_data_dir"]
