"""Identity-license service: issue/verify, consent ledger, takeout, deletion.

Ownership model:
- issue_license() is idempotent and must precede any import of the user's
  presence — the license is what makes imported data *theirs*.
- Every use is gated by scopes (default-deny, revocable).
- build_takeout() exports everything; delete_all() removes everything and
  returns a signed receipt.

What persists after delete_all, and why:
- The tombstoned license row (status='terminated'): proof a license existed
  and was ended — prevents silent re-issuance confusion and keeps the audit
  trail coherent.
- The signed deletion receipt: the user's proof of exactly what was removed.
Everything else — uploads, events, signals, consent ledger — is gone.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import LicenseRequired, ScopeDenied, identity_data_dir
from .models import DeletionReceipt, IdentityLicense, ScopeEvent
from .scopes import check_scope, require_scope, validate_scope
from .signing import sign_mapping, verify_mapping
from .store import IdentityStore

RIGHTS_TEXT = """\
Identity License — Zenaf

All training signals, profiles, snapshots, and other data derived from the
owner's digital presence and interactions within Zenaf are the exclusive
property of the owner. Zenaf acts solely as custodian: it may process this
data only within the consent scopes the owner has explicitly granted, and
every grant is revocable at any time.

Nothing derived from the owner may be used to train third-party models,
sold, or shared with any party. The owner may export everything at any time
(takeout) and may demand complete deletion, for which a signed receipt is
issued. Data imported from other services is re-anchored under this license
on import: it becomes the owner's property here, regardless of where it
came from.
"""

DEFAULT_TERMS: dict[str, Any] = {
    "third_party_training": False,
    "sale_of_data": False,
    "rental_default": "deny",
    "data_residency": "local",
}


def _license_payload(lic: IdentityLicense) -> dict[str, Any]:
    return {
        "license_id": lic.license_id,
        "owner_id": lic.owner_id,
        "issued_at": lic.issued_at.isoformat(),
        "rights": lic.rights,
        "terms": lic.terms,
    }


def _receipt_payload(receipt: DeletionReceipt) -> dict[str, Any]:
    return {
        "receipt_id": receipt.receipt_id,
        "ts": receipt.ts.isoformat(),
        "license_id": receipt.license_id,
        "summary": receipt.summary,
    }


def _presence_data_dir() -> Path:
    """Presence-ingest data dir, honoring ZENAF_DATA_DIR like identity does."""
    override = os.environ.get("ZENAF_DATA_DIR")
    if override:
        return Path(override) / "presence_ingest"
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / "data" / "presence_ingest"


# -- license -----------------------------------------------------------


def issue_license(
    owner_id: str = "local-owner", *, store: IdentityStore | None = None
) -> IdentityLicense:
    """Issue the identity license. Idempotent: returns the existing one."""
    store = store or IdentityStore()
    existing = store.get_license()
    if existing is not None and existing.status == "active":
        return existing
    lic = IdentityLicense(
        license_id=f"lic-{uuid4().hex[:12]}",
        owner_id=(owner_id or "local-owner").strip() or "local-owner",
        issued_at=datetime.now(timezone.utc),
        version=1,
        rights=RIGHTS_TEXT,
        terms=dict(DEFAULT_TERMS),
    )
    lic.signature = sign_mapping(_license_payload(lic))
    store.save_license(lic)
    return lic


def get_license(*, store: IdentityStore | None = None) -> IdentityLicense | None:
    store = store or IdentityStore()
    return store.get_license()


def verify_license(*, store: IdentityStore | None = None) -> bool:
    """True iff an active license exists and its signature verifies."""
    store = store or IdentityStore()
    lic = store.get_license()
    if lic is None or lic.status != "active":
        return False
    return verify_mapping(_license_payload(lic), lic.signature)


# -- consent ledger ----------------------------------------------------


def grant_scope(
    scope: str, note: str = "", *, store: IdentityStore | None = None
) -> list[str]:
    """Grant a scope. Raises ValueError for unknown scope strings."""
    store = store or IdentityStore()
    s = validate_scope(scope)
    store.append_scope_event(
        ScopeEvent(
            event_id=f"se-{uuid4().hex[:12]}",
            scope=s,
            action="grant",
            ts=datetime.now(timezone.utc),
            note=note or "",
        )
    )
    return sorted(store.active_scopes())


def revoke_scope(
    scope: str, note: str = "", *, store: IdentityStore | None = None
) -> list[str]:
    """Revoke a scope. Raises ValueError for unknown scope strings."""
    store = store or IdentityStore()
    s = validate_scope(scope)
    store.append_scope_event(
        ScopeEvent(
            event_id=f"se-{uuid4().hex[:12]}",
            scope=s,
            action="revoke",
            ts=datetime.now(timezone.utc),
            note=note or "",
        )
    )
    return sorted(store.active_scopes())


# -- takeout -----------------------------------------------------------


def build_takeout(
    *,
    store: IdentityStore | None = None,
    presence_store: Any = None,
) -> dict[str, Any]:
    """Export everything Zenaf holds about the owner.

    Takeout is a right, not a privilege: no scope is required, but a license
    must exist. The bundle includes the signed license, the full consent
    ledger, all approved training signals, and import-session summaries.
    """
    store = store or IdentityStore()
    lic = store.get_license()
    if lic is None:
        raise LicenseRequired()

    # Lazy import: presence_ingest must never import identity at module level
    # in a way that cycles back. identity -> presence_ingest stays one-way
    # and lazy.
    if presence_store is None:
        from local_ai.presence_ingest.store import PresenceStore

        presence_store = PresenceStore()
        _close_pstore = True
    else:
        _close_pstore = False
    try:
        signals = presence_store.list_signals(status="approved")
        sessions = presence_store.list_sessions()
    finally:
        if _close_pstore:
            presence_store.close()

    return {
        "takeout_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "license": lic.model_dump(mode="json"),
        "signature_valid": verify_mapping(_license_payload(lic), lic.signature),
        "scope_ledger": [e.model_dump(mode="json") for e in store.list_scope_events()],
        "training_signals": [s.model_dump(mode="json") for s in signals],
        "import_sessions": [s.model_dump(mode="json") for s in sessions],
        "counts": {
            "scope_events": len(store.list_scope_events()),
            "approved_signals": len(signals),
            "import_sessions": len(sessions),
        },
    }


# -- deletion ----------------------------------------------------------


def delete_all(
    confirmation: str,
    *,
    store: IdentityStore | None = None,
    presence_store: Any = None,
    presence_upload_root: Path | None = None,
    presence_db_path: Path | None = None,
) -> DeletionReceipt:
    """Delete everything derived from the owner. Returns a signed receipt.

    Requires confirmation == "DELETE" (exactly) and the delete:execute scope.
    Removes: presence-ingest uploads, the presence-ingest database, and the
    consent ledger. Keeps: the tombstoned license row and the signed receipt
    (see module docstring for why).
    """
    if confirmation != "DELETE":
        raise ValueError('Deletion requires confirmation == "DELETE".')
    store = store or IdentityStore()
    require_scope("delete:execute", store=store)

    pdata = _presence_data_dir()
    db_path = Path(presence_db_path) if presence_db_path else pdata / "signals.db"
    upload_root = (
        Path(presence_upload_root) if presence_upload_root else pdata / "uploads"
    )

    pstore = presence_store
    _close_pstore = False
    if pstore is None:
        from local_ai.presence_ingest.store import PresenceStore

        # Tolerate a missing DB (nothing imported yet).
        pstore = PresenceStore(db_path=db_path)
        _close_pstore = True
    try:
        sessions = pstore.list_sessions()
        n_events = sum(pstore.count_events(s.session_id) for s in sessions)
        n_signals = sum(
            pstore.count_signals(s.session_id) for s in sessions
        )
    finally:
        if _close_pstore:
            pstore.close()

    n_scope_events = len(store.list_scope_events())
    lic = store.get_license()
    license_id = lic.license_id if lic else "none"

    shutil.rmtree(upload_root, ignore_errors=True)
    try:
        db_path.unlink(missing_ok=True)
    except OSError:
        pass

    store.clear_scope_events()
    if lic is not None:
        store.terminate_license()

    receipt = DeletionReceipt(
        receipt_id=f"del-{uuid4().hex[:12]}",
        ts=datetime.now(timezone.utc),
        license_id=license_id,
        summary={
            "import_sessions": len(sessions),
            "presence_events": n_events,
            "training_signals": n_signals,
            "scope_events": n_scope_events,
        },
    )
    receipt.signature = sign_mapping(_receipt_payload(receipt))
    store.save_receipt(receipt)
    return receipt
