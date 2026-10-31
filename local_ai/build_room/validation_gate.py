"""Validation-in-the-loop gate (Increment G, accepted schema contract §9).

The gate REPORTS; it never repairs, never generates declarations, and
never rewrites a capture into conformance (plan Rev 2 correction 4,
binding). Conformance is zero errors; a non-conformant capture is
preserved with its report attached, and the report — not a fix — is
the gate's output.

Two legs, matching the contract's interim/final labeling:

- Interim (during the meeting): after each phase that produced claims,
  the runner validates the adapter-derived record so far and keeps the
  report. Interim reports cover adapter inputs only: proposals, events,
  and close results do not exist yet, so they cannot appear here.
- Final (at close): artifact build runs convener-close and
  ``build_transjective_record`` with ``validation_phase="final"``; the
  section's ``validation`` + ``conformant`` + ``validation_phase``
  fields ARE the final report. This module does not re-implement that
  leg, so the two legs cannot disagree about what validation means.

Neither leg mutates its inputs: the adapter is read-only, the
validator is read-only, and the runner passes ``to_dict()`` snapshots.
A phase that produced no claims gets no interim report — an interim
report over zero claims would be vacuously conformant, which is
exactly the kind of fabricated pass this gate refuses to emit. The
final report covers failed meetings instead.
"""

from __future__ import annotations

from local_ai.build_room.transjective_record import (
    adapt_claims_to_contract_inputs,
    validate_contract_record,
)

__all__ = ["interim_validation_report"]


def interim_validation_report(
    claims,
    *,
    meeting_phase,
    meeting_kind="build_council",
    meeting_rules=None,
):
    """Validate the in-progress record at one phase boundary.

    ``claims`` are claim dicts (the runner passes ``to_dict()``
    snapshots); ``meeting_phase`` is "opening", "response", or
    "revision". Returns the interim report: phase label, meeting
    phase, conformance, errors, warnings, counts, and claim count.
    The input claims are never mutated and no declaration is ever
    generated: a claim without a declaration stays without one, and
    its unknown/missing state is reported, not repaired.
    """
    adapted = adapt_claims_to_contract_inputs(claims)
    record = {
        "claims": list(claims),
        "declarations": adapted["declarations"],
        "target_states": adapted["target_states"],
        "legacy_dispositions": adapted["legacy_dispositions"],
        "exposure": adapted["exposure"],
    }
    report = validate_contract_record(
        record,
        validation_phase="interim",
        meeting_kind=meeting_kind,
        meeting_rules=meeting_rules,
    )
    return {
        "phase": "interim",
        "meeting_phase": meeting_phase,
        "conformant": report["conformant"],
        "errors": report["errors"],
        "warnings": report["warnings"],
        "error_counts": report["error_counts"],
        "warning_counts": report["warning_counts"],
        "claim_count": len([c for c in claims if c.get("id")]),
    }
