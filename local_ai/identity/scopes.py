"""Granular, revocable consent scopes. Default-deny.

Scopes gate every use of the owner's identity-derived data:
- train:self      — distill imported presence into training signals
- rent:zone:*     — rental prefix; the rental layer will check rent:zone:<name>
- export          — takeout (currently informational; takeout is a right)
- delete:execute  — confirm full deletion

The ledger is append-only; active_scopes() folds grants/revokes.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from . import ScopeDenied

if TYPE_CHECKING:
    from .store import IdentityStore

KNOWN_SCOPES: dict[str, str] = {
    "train:self": (
        "Use my data to train my doppelganger. Gates distillation of "
        "imported presence into candidate training signals."
    ),
    "rent:zone:*": (
        "Allow rental of my doppelganger in a zone. Prefix pattern — the "
        "rental layer checks rent:zone:<name>; a rent:zone:* grant covers "
        "all zones, a rent:zone:<name> grant covers one."
    ),
    "export": "Export everything Zenaf holds about me (takeout).",
    "delete:execute": "Confirm full deletion of my data (requires typing DELETE).",
}

_ZONE_GRANT_RE = re.compile(r"rent:zone:([A-Za-z0-9][A-Za-z0-9_-]*)")


def validate_scope(scope: str) -> str:
    """Normalize and validate a scope string. Raises ValueError if unknown."""
    s = (scope or "").strip()
    if not s:
        raise ValueError("Scope must be a non-empty string.")
    if s in KNOWN_SCOPES:
        return s
    if _ZONE_GRANT_RE.fullmatch(s):
        return s
    raise ValueError(
        f"Unknown scope '{s}'. Known scopes: {', '.join(sorted(KNOWN_SCOPES))} "
        "or rent:zone:<name>."
    )


def check_scope(
    scope: str, *, store: IdentityStore | None = None, user_id: str | None = None
) -> bool:
    """True iff `scope` is currently granted. Default-deny.

    A rent:zone:<name> check also passes on an active rent:zone:* grant.
    Unknown scope strings simply return False — deny, don't crash.
    Per-user when user_id is given (that user's grants + global grants).
    """
    s = (scope or "").strip()
    if not s:
        return False
    from .store import IdentityStore as _Store

    store = store or _Store()
    active = store.active_scopes(user_id=user_id)
    if s in active:
        return True
    if s.startswith("rent:zone:") and "rent:zone:*" in active:
        return True
    return False


def require_scope(
    scope: str, *, store: IdentityStore | None = None, user_id: str | None = None
) -> None:
    """Raise ScopeDenied unless `scope` is currently granted."""
    if not check_scope(scope, store=store, user_id=user_id):
        raise ScopeDenied(scope)
