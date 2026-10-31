"""Disagreement records at close time (Increment D, accepted schema
contract §1.5 + §7 E10/W3, native-emission plan Rev 2 §D).

Pure stdlib; no imports from meeting.py, so this module cannot mutate
the record it reads. It answers one question per close: what
incompatibilities did the convener record, as structured evidence —
without ever moving anyone's standing?

Design rules (contract §1.5 + §4.3, plan §D):

- A DisagreementRecord carries exactly six fields: id, claims (≥ 2
  existing claim ids), incompatibility (statement of what conflicts),
  proposer (participant or convener, with attribution), cited_evidence
  (claim ids and/or statements relied on), stage.
- Stage is ``identified`` (claims appear incompatible) or
  ``articulated`` (incompatibility stated explicitly). ``clarified``
  is NEVER a valid capture stage: clarified is reserved for judging,
  never a capture status. Any record attempting stage ``clarified``
  fails E10, as does any record with fewer than two claims, no
  incompatibility statement, or no proposer.
- A disagreement NEVER changes standing. Standing is derived from
  DispositionEvent history only (see transjective_record).
  Disagreement records attach to their targets as evidence and
  nothing else. The ONLY standing effect a disagreement can ever
  have is via a §4.3 contested-standing event, which is Increment
  C's machinery (convener_close over challenge candidates), not
  D's. This module issues no events, reads no standing, and writes
  no standing. In particular, a disagreement record is NOT a
  challenge claim: it does not satisfy the §4.3 bar by itself. The
  bar needs a specific challenge claim, an identified target, a
  not-withdrawn/not-resolved state, and challenge + available
  responses cited — a disagreement record supplies none of those
  on its own.
- Convener-recorded pairs suffice for v1. There is NO model-emitted
  incompatibility parser in this increment, deliberately: no
  model-emitted incompatibility format exists (Increment A blocks
  cover relationship kinds, not incompatibility statements), and
  inventing one would be a prompt change plus a new vocabulary —
  beyond D's scope. A parser is a follow-up, not a stretch goal.
  In v1, disagreement pairs arrive as explicit convener input to
  the close funnel (artifact build); live runs have no producer
  yet, so live artifacts carry no disagreements — honestly empty,
  never reconstructed.
- Constructor vs validator, kept separate on purpose.
  ``build_disagreement`` builds exactly what it is given and refuses
  nothing, so invalid inputs can be fed to the validator in tests
  and preserved-with-report in real records (the contract never
  silently repairs). ``validate_disagreement`` mirrors the §7 E10
  conditions only: unknown claim ids fail E1 and thin/missing
  cited evidence warns W3 through the record validator, not here.
- Contract-text tension, flagged not resolved: §1.5 marks
  cited_evidence "required", but §7 grades its absence as W3
  (warning), not E10 — so a disagreement without evidence is
  conformant-with-warning despite the "required" label. This
  implementation follows §7 (the validator's behavior, unchanged)
  and flags the tension for a future contract verdict; it does
  not invent an E10 for missing evidence.
"""

from __future__ import annotations

__all__ = [
    "STAGES",
    "build_disagreement",
    "validate_disagreement",
]

# Contract §1.5: the only valid capture stages. ``clarified`` is
# reserved for judging and is never emitted here.
STAGES = ("identified", "articulated")


def build_disagreement(
    id: str,
    claims: list[str],
    incompatibility: str,
    proposer: str,
    cited_evidence,
    stage: str,
) -> dict:
    """Build one DisagreementRecord dict with exactly the §1.5 fields.

    No validation happens here by design (see module docstring):
    invalid inputs are built faithfully so the validator can fail
    them with E10/E1/W3 instead of the constructor hiding them.
    ``cited_evidence`` is stored as given (lists are copied) since
    the contract allows claim ids and/or statements.
    """
    return {
        "id": id,
        "claims": list(claims),
        "incompatibility": incompatibility,
        "proposer": proposer,
        "cited_evidence": (
            list(cited_evidence)
            if isinstance(cited_evidence, list)
            else cited_evidence
        ),
        "stage": stage,
    }


def validate_disagreement(d: dict) -> list[str]:
    """Return one "E10" per violated §7 E10 condition, else [].

    Conditions mirrored exactly from the record validator: fewer
    than two claims; no incompatibility statement; no proposer;
    stage outside ("identified", "articulated") — which is how
    stage ``clarified`` fails E10. Unknown claim ids (E1) and
    thin/missing cited evidence (W3) are the record validator's
    business, not this helper's, and are deliberately not reported
    here.
    """
    errors: list[str] = []
    if len(d.get("claims") or []) < 2:
        errors.append("E10")
    if not d.get("incompatibility"):
        errors.append("E10")
    if not d.get("proposer"):
        errors.append("E10")
    if d.get("stage") not in STAGES:
        errors.append("E10")
    return errors
