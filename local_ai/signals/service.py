"""
Signal service (Layer 1). Create, list, update. API uses these.

Owner-scoped (Track C, Option A): ``user_id`` is a required positional
argument on every function, stamped server-side from the authenticated
session — a caller-supplied owner in a payload dict is overwritten,
never trusted.

Fail-closed rollback (founder correction 2, 2026-11-11): no rollback may
restore globally shared Signals access. The rollback path is the
``ZENAF_SIGNALS_DISABLED`` kill switch: when set, every signals
operation raises ``SignalsDisabledError`` — the routes answer 503 and
Radar's signals bucket comes back empty — instead of ever serving the
unscoped pool again. A plain code revert to the pre-scoping behavior is
NOT an acceptable rollback; the procedure is documented in the
implementation report. The flag defaults to unset (signals enabled).
"""
from __future__ import annotations

import os
from typing import Any

from . import models as Mod
from . import storage as St


class SignalsDisabledError(RuntimeError):
    """Signals are disabled by operator rollback (ZENAF_SIGNALS_DISABLED).

    Fail-closed: the caller must surface this as "unavailable", never
    fall back to unscoped reads. Raised by every service entry point
    while the flag is set.
    """


def signals_disabled() -> bool:
    """True when the rollback kill switch is set. Read at call time so
    tests and the rollback procedure can flip it without a restart of
    the process under test (production reads it per request)."""
    return (os.environ.get("ZENAF_SIGNALS_DISABLED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _require_enabled() -> None:
    if signals_disabled():
        raise SignalsDisabledError(
            "signals are disabled by operator rollback (ZENAF_SIGNALS_DISABLED)"
        )


def create_signals(items: list[Mod.SignalCreate], user_id: str) -> list[dict[str, Any]]:
    """Bulk create signals owned by ``user_id``. Returns list of created
    signal dicts (snake_case). Linked references are validated against
    the owner in storage before any insert (founder correction 1)."""
    _require_enabled()
    payloads = []
    for item in items:
        payloads.append({
            "kind": item.kind,
            "title": item.title,
            "detail": item.detail,
            "source": item.source,
            "source_excerpt": item.source_excerpt,
            "source_ref": item.source_ref,
            "confidence": item.confidence,
            "linked_initiative_id": item.linked_initiative_id,
            "linked_project_id": item.linked_project_id,
            "linked_task_id": item.linked_task_id,
            "status": item.status,
        })
    return St.create_signals_bulk(payloads, user_id)


def list_signals(
    user_id: str,
    *,
    status_in: list[str] | None = None,
    status_not_in: list[str] | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """List the caller's signals with optional filters."""
    _require_enabled()
    return St.list_signals(user_id, status_in=status_in, status_not_in=status_not_in, source=source)


def update_signal(signal_id: str, patch: Mod.SignalUpdate, user_id: str) -> dict[str, Any] | None:
    """Update status and/or linked ids. Returns updated signal or None."""
    _require_enabled()
    p = patch.model_dump(by_alias=False, exclude_none=True)
    return St.update_signal(signal_id, p, user_id)
