"""
Shared data access policy for content derived from external systems (mailbox, files, etc.).

Two boundaries:
- Trusted local: modules and users running inside Atria on trusted infrastructure.
- External egress: anything that sends content outside that boundary (remote APIs, web, telemetry, etc.).

Three tiers:
- Tier A (operational): metadata, summary, lane, judgment refs, status, action history — default for UI and orchestration.
- Tier B (sanitized): cleaned/normalized text; lower exposure, not legally de-identified; for triage/reasoning when raw not needed.
- Tier C (raw): full unsanitized content; restricted, explicitly justified use only.

Callers declare the minimum tier they need. Tier C requires an explicit justification.
This module is primarily about preventing accidental outward leakage and governing **external-bound**
calls; it should not unnecessarily cripple trusted local workflows.
No auth/UI in this module; this is an internal policy primitive for future modules/tools.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

# Access levels (what a function/module is requesting)
AccessLevel = Literal["metadata_only", "sanitized_text", "raw_content_required"]
Destination = Literal["local", "external"]

# Named constants for clarity
METADATA_ONLY: AccessLevel = "metadata_only"
SANITIZED_TEXT: AccessLevel = "sanitized_text"
RAW_CONTENT_REQUIRED: AccessLevel = "raw_content_required"
DEST_LOCAL: Destination = "local"
DEST_EXTERNAL: Destination = "external"


# Tier labels for logging/docs
class DataTier(str, Enum):
    A_OPERATIONAL = "operational"
    B_SANITIZED = "sanitized"
    C_RAW = "raw"


def access_level_to_tier(level: AccessLevel) -> DataTier:
    if level == RAW_CONTENT_REQUIRED:
        return DataTier.C_RAW
    if level == SANITIZED_TEXT:
        return DataTier.B_SANITIZED
    return DataTier.A_OPERATIONAL


def tier_satisfies(available: DataTier, requested: AccessLevel) -> bool:
    """True if the available tier satisfies the requested access level."""
    need = access_level_to_tier(requested)
    order = (DataTier.A_OPERATIONAL, DataTier.B_SANITIZED, DataTier.C_RAW)
    return order.index(available) >= order.index(need)


# Default: most operations use A or B; C requires explicit justification
_RAW_JUSTIFICATIONS: set[str] = set()


def request_access(
    level: AccessLevel,
    *,
    justification: str | None = None,
    allow_without_justification: bool = False,
    destination: Destination = DEST_LOCAL,
) -> bool:
    """
    Check whether the requested access level is allowed.

    Within the trusted local boundary (destination='local'):
    - metadata_only, sanitized_text: always allowed (internal policy primitive; no auth).
    - raw_content_required: allowed when justification is provided (non-empty string)
      or allow_without_justification is True (e.g. tests, tightly-controlled flows).

    For external egress (destination='external'):
    - Same rules, but callers should treat this as a hard gate before sending content out.

    Returns True if access is allowed. Caller can use this to decide whether to pass
    Tier B/C content to a downstream. Does not raise; log or enforce in the caller if needed.
    """
    # Tier A/B are always allowed by this module; higher-level auth/ACLs are out of scope.
    if level in (METADATA_ONLY, SANITIZED_TEXT):
        return True
    if level != RAW_CONTENT_REQUIRED:
        return True
    if allow_without_justification:
        return True
    j = (justification or "").strip()
    if not j:
        return False
    _RAW_JUSTIFICATIONS.add(j)  # optional: audit trail of justifications used
    return True


def require_access(
    level: AccessLevel,
    *,
    justification: str | None = None,
    allow_without_justification: bool = False,
    destination: Destination = DEST_LOCAL,
) -> None:
    """
    Require that the requested access is allowed; raise ValueError if Tier C is requested
    without justification (unless allow_without_justification).
    """
    if not request_access(
        level,
        justification=justification,
        allow_without_justification=allow_without_justification,
        destination=destination,
    ):
        raise ValueError(
            "raw_content_required access must provide a non-empty justification (e.g. task name or reason)"
        )

