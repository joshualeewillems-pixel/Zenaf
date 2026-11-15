"""Pydantic models for the identity-license system.

An IdentityLicense is the signed declaration that everything Zenaf derives
from the owner is the owner's property. ScopeEvents form the append-only
consent ledger. A DeletionReceipt is the signed proof of what was removed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

ScopeAction = Literal["grant", "revoke"]
LicenseStatus = Literal["active", "terminated"]


class IdentityLicense(BaseModel):
    """The signed ownership declaration for one owner's doppelganger."""

    license_id: str
    owner_id: str
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1
    rights: str  # human-readable declaration
    terms: dict[str, Any] = Field(default_factory=dict)
    signature: str = ""  # hex HMAC over license_id/owner_id/issued_at/rights/terms
    status: LicenseStatus = "active"
    terminated_at: datetime | None = None


class ScopeEvent(BaseModel):
    """One entry in the append-only consent ledger."""

    event_id: str
    scope: str
    action: ScopeAction
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    note: str = ""
    user_id: str = ""  # whose consent; "" = global (pre-multi-user) grant


class DeletionReceipt(BaseModel):
    """Signed proof of a deletion: what was removed, when.

    Also the carrier for the Steward D2 operation rows (internal
    audit residue in the same table): an operation row's summary
    binds covered_user, operation_id, erased_at, and scope inside
    the signed payload. User-facing receipts carry counts, per-store
    status, and the coverage statement only — never a user id and
    never erased-content identifiers.
    """

    receipt_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    license_id: str
    # Steward D2 (packet §9.6 Rev 4): widened from dict[str, int] —
    # operation-record rows and post-D2 receipts carry string values
    # (per-store status lines, the coverage statement, the signed
    # operation binding) alongside the counts. The signing payload
    # shape is unchanged: the whole summary is signed either way.
    summary: dict[str, Any] = Field(default_factory=dict)
    signature: str = ""  # hex HMAC over receipt_id/ts/license_id/summary
