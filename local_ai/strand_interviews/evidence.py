"""Evidence thresholds proportional to the claim (rev2 C1, as corrected).

The threshold governs when a durable (tier-3) proposal is EARNED, never
whether approval is needed — approval is always required for the
durable tier. This module is the testable rule; the noting producer
(Slice 3 permission work) is the caller that will apply it when a
tier-3 proposal is surfaced. Nothing in this build calls it from a
production path yet: the strand prompt guidance carries the same
thresholds in prose (see guidance.py), and this module pins the rule
so a future caller cannot quietly weaken it.

Rules (verdict correction C1):
- A statement about a SPECIFIC EXPRESSED INTENTION may be grounded in
  ONE CLEAR DECLARATION. Example: "I want to become a hospice
  chaplain" — an important, explicit aspiration on its first occurrence.
- A statement about a RECURRING PREFERENCE, STABLE PERSONALITY TRAIT,
  or ENDURING WORLDVIEW requires STRONGER evidence: recurrence across
  the thread AND confirmation in the user's own words.
- Borderline claims (where the claim's strength is ambiguous) must be
  proposed WITH their evidence strength stated, so the user judges with
  full information — never silently promoted to the stronger class,
  never silently demoted to avoid proposing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ClaimKind = Literal["intention", "recurring", "stable", "borderline"]

#: Claim kinds the rule knows. Anything else is borderline by design:
#: an unclassifiable claim is proposed only with its strength stated.
_KNOWN_KINDS: frozenset[str] = frozenset(
    {"intention", "recurring", "stable", "borderline"}
)


@dataclass(frozen=True)
class Tier3Eligibility:
    """Whether a tier-3 proposal has earned proposal, and on what basis."""

    eligible: bool
    evidence_strength: str
    must_state_strength: bool = False


def classify_claim(claim_kind: str | None) -> ClaimKind:
    """Map a caller-supplied claim kind to a ClaimKind.

    Unknown or empty kinds are borderline: the cautious class, never
    the permissive one.
    """
    normalized = (claim_kind or "").strip().lower()
    if normalized in _KNOWN_KINDS:
        return normalized  # type: ignore[return-value]
    return "borderline"


def tier3_eligible(
    claim_kind: str | None,
    *,
    declarations: int = 0,
    confirmations: int = 0,
    recurrence: int = 0,
) -> Tier3Eligibility:
    """Decide whether a durable insight proposal is earned.

    ``declarations`` counts clear declarations of the claimed thing in
    the user's own words; ``confirmations`` counts times the user
    confirmed the reading in their own words; ``recurrence`` counts
    distinct exchanges in which the pattern recurred.
    """
    kind = classify_claim(claim_kind)
    if kind == "intention":
        if declarations >= 1:
            return Tier3Eligibility(
                eligible=True,
                evidence_strength="one clear declaration",
            )
        return Tier3Eligibility(
            eligible=False,
            evidence_strength="no clear declaration yet",
        )
    if kind in ("recurring", "stable"):
        if recurrence >= 2 and confirmations >= 1:
            return Tier3Eligibility(
                eligible=True,
                evidence_strength=(
                    "recurrence across the thread plus confirmation "
                    "in the user's own words"
                ),
            )
        return Tier3Eligibility(
            eligible=False,
            evidence_strength=(
                "recurring/stable claims need recurrence across the "
                "thread and confirmation in the user's own words"
            ),
        )
    # Borderline: propose only with the strength stated.
    if declarations >= 1 or recurrence >= 1:
        return Tier3Eligibility(
            eligible=True,
            evidence_strength=(
                "borderline — evidence strength ambiguous; "
                "propose only with this strength stated"
            ),
            must_state_strength=True,
        )
    return Tier3Eligibility(
        eligible=False,
        evidence_strength="borderline with no grounding yet",
        must_state_strength=True,
    )
