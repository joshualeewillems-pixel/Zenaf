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
    """Signed proof of a full deletion: what was removed, when."""

    receipt_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    license_id: str
    summary: dict[str, int] = Field(default_factory=dict)
    signature: str = ""  # hex HMAC over receipt_id/ts/license_id/summary
