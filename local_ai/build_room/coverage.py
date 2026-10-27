"""Coverage assurance for Build-Council Room syntheses (post-Tier 3 HOLD).

Detection-only: given a claim registry, the unresolved-objection list,
and a VALIDATED structured synthesis (kept entries only), compute
which registry-demanded threads the synthesis represents and which it
silently omits. This module never generates, rewrites, or repairs
synthesis content: its inputs are registry + validated output only,
its outputs are claim IDs, kept-entry indices, fixed reason strings,
and fate labels. It has no participant, no prompt, and no generation
capability — by signature, not just by convention.

Rules (amended coverage-assurance design, 2026-10-26):

- Objections: one demand unit per (target, challenger) pair with
  state "unresolved". A unit is covered ONLY when BOTH claim IDs
  appear in the supporting_claims of the SAME kept disagreement
  entry. Target-only or challenger-only citation never covers.
  Responded_to entries are listed under ``not_required``, never
  demanded.
- Proposals: demanded iff status == "Proposed" and disposition NOT
  in ("revised", "withdrawn"). Covered ONLY by recommendation
  entries: citation in supporting_claims, or declared consolidation
  in consolidates_claim_ids (union across entries). Citation in a
  position or disagreement entry never satisfies proposal demand.
- Provenance: a recommendation entry whose consolidates list was
  malformed or cited unknown IDs arrives here carrying a
  ``consolidates_provenance_failure`` marker (set by the contract
  validator, which keeps the entry but ignores the list). Any such
  marker is a provenance failure, and any provenance failure fails
  the verdict — even when every demand unit is otherwise covered.
  The entry itself stays valid and retained; only its unsupported
  consolidation claim cannot count toward acceptance.
- Verdict: "pass" iff objections.omitted is empty AND
  proposals.omitted is empty AND provenance_failures is empty.
  There is no partial credit.
- Mechanical vs substantive: this verdict is MECHANICAL coverage
  only (referenced via citation or declared consolidation). It
  does NOT certify that a recommendation preserves a proposal's
  distinctive contribution — that is human review's judgment.
  A mechanical pass must never be read as production adoption
  without substantive fidelity review.

Acceptance (design §C.3), computed by :func:`artifact_accepted`:
accepted iff every field evaluation is synthesized_complete, or
synthesized_empty with a legitimate empty per the demand sets, AND
coverage.verdict == "pass". A synthesized_partial field is never
valid for acceptance; unparseable / not_evaluated never pass.
Field evaluations are never rewritten by this module.
"""

from __future__ import annotations

import inspect
from typing import Any

LIMITATIONS_COVERAGE_NOTE = "not_checked (Q1 decided 2026-10-26: human review in v1)"

_CONTRACT_FIELDS = ("positions", "disagreements", "recommendations", "limitations")


def _claim_id(claim: Any) -> str:
    if isinstance(claim, dict):
        return claim["id"]
    return claim.id


def _claim_status(claim: Any) -> str:
    if isinstance(claim, dict):
        return claim.get("status", "unknown")
    return getattr(claim, "status", "unknown")


def _claim_disposition(claim: Any) -> str | None:
    if isinstance(claim, dict):
        return claim.get("disposition")
    return getattr(claim, "disposition", None)


def _claim_disposition_by(claim: Any) -> str | None:
    if isinstance(claim, dict):
        return claim.get("disposition_by")
    return getattr(claim, "disposition_by", None)


def _registry_claims(registry: Any) -> list[Any]:
    if registry is None:
        return []
    if isinstance(registry, dict):
        return registry.get("claims", [])
    return list(getattr(registry, "claims", []))


def _entry_supporting_claims(entry: dict) -> list[str]:
    """Supporting claims of a disagreement entry.

    Contract entries carry ``supporting_claims``; legacy
    section-parsed entries carry ``claim_ids``. The fallback is
    what lets coverage be computed over legacy output too (§G.3.5)
    without inventing a second code path.
    """
    claims = entry.get("supporting_claims")
    if isinstance(claims, list):
        return [c for c in claims if isinstance(c, str)]
    claims = entry.get("claim_ids")
    if isinstance(claims, list):
        return [c for c in claims if isinstance(c, str)]
    return []


def check_coverage(registry: Any, unresolved_objections: list[dict],
                   structured: dict[str, list]) -> dict[str, Any]:
    """Compute the coverage verdict for a validated synthesis.

    ``structured`` is the KEPT output of ``parse_synthesis_contract``
    (or, for legacy output, kept positions/disagreements plus empty
    recommendations/limitations). The function reads only; it never
    mutates ``structured``, the registry, or the objection list.
    """
    structured = structured or {}
    disagreements = structured.get("disagreements") or []
    recommendations = structured.get("recommendations") or []

    # --- Objections ---------------------------------------------------
    demanded_obj: list[tuple[str, str]] = []
    not_required_obj: list[dict] = []
    for u in unresolved_objections or []:
        pair = (u.get("claim_id"), u.get("source_claim_id"))
        if u.get("state") == "unresolved":
            demanded_obj.append(pair)
        elif u.get("state") == "responded_to":
            not_required_obj.append({
                "target_claim_id": pair[0],
                "challenger_claim_id": pair[1],
                "state": "responded_to",
            })

    covered_obj: list[dict] = []
    omitted_obj: list[dict] = []
    for target, challenger in demanded_obj:
        covering = [
            idx for idx, entry in enumerate(disagreements)
            if isinstance(entry, dict)
            and target in _entry_supporting_claims(entry)
            and challenger in _entry_supporting_claims(entry)
        ]
        if covering:
            covered_obj.append({
                "target_claim_id": target,
                "challenger_claim_id": challenger,
                "covered_by": covering,
            })
        else:
            omitted_obj.append({
                "target_claim_id": target,
                "challenger_claim_id": challenger,
                "reason": "not_represented",
            })

    # --- Proposals ----------------------------------------------------
    claims = _registry_claims(registry)
    demanded_prop: list[str] = []
    not_required_prop: list[dict] = []
    for claim in claims:
        disp = _claim_disposition(claim)
        if _claim_status(claim) != "Proposed":
            continue
        if disp in ("revised", "withdrawn"):
            not_required_prop.append({
                "proposal_claim_id": _claim_id(claim),
                "fate": disp,
                "disposition_by": _claim_disposition_by(claim),
            })
        else:
            demanded_prop.append(_claim_id(claim))

    # Provenance failures + warnings are read off kept recommendation
    # entries (validator markers for the former, valid-but-non-demand
    # consolidates for the latter). They are metadata, never prose.
    provenance_failures: list[dict] = []
    warnings: list[dict] = []
    cited: dict[str, list[int]] = {}
    consolidated: dict[str, list[int]] = {}
    for idx, entry in enumerate(recommendations):
        if not isinstance(entry, dict):
            continue
        marker = entry.get("consolidates_provenance_failure")
        if isinstance(marker, dict):
            provenance_failures.append({
                "kind": marker.get("kind", "consolidates_malformed"),
                "recommendation_index": idx,
                "detail": marker.get("detail"),
            })
        for cid in entry.get("supporting_claims") or []:
            if isinstance(cid, str):
                cited.setdefault(cid, []).append(idx)
        cons = entry.get("consolidates_claim_ids")
        if isinstance(cons, list):
            for cid in cons:
                if not isinstance(cid, str):
                    continue
                consolidated.setdefault(cid, []).append(idx)
                if cid not in demanded_prop:
                    warnings.append({
                        "kind": "consolidates_non_demand_ids",
                        "recommendation_index": idx,
                        "detail": cid,
                    })

    covered_prop: list[dict] = []
    omitted_prop: list[dict] = []
    for pid in demanded_prop:
        in_cited = pid in cited
        in_cons = pid in consolidated
        if in_cited or in_cons:
            via = ("cited_and_consolidated" if in_cited and in_cons
                   else "cited" if in_cited else "consolidated")
            covering = sorted(set(cited.get(pid, []) + consolidated.get(pid, [])))
            covered_prop.append({
                "proposal_claim_id": pid,
                "covered_by": covering,
                "via": via,
            })
        else:
            omitted_prop.append({
                "proposal_claim_id": pid,
                "reason": "not_represented",
            })

    verdict = ("pass" if not omitted_obj and not omitted_prop
               and not provenance_failures else "fail")
    return {
        "verdict": verdict,
        "objections": {
            "required": [{"target_claim_id": t, "challenger_claim_id": c}
                         for t, c in demanded_obj],
            "covered": covered_obj,
            "omitted": omitted_obj,
            "not_required": not_required_obj,
        },
        "proposals": {
            "required": demanded_prop,
            "covered": covered_prop,
            "omitted": omitted_prop,
            "not_required": not_required_prop,
        },
        "warnings": warnings,
        "provenance_failures": provenance_failures,
        "limitations_coverage": LIMITATIONS_COVERAGE_NOTE,
    }


def artifact_accepted(evaluations: dict[str, str], coverage: dict[str, Any],
                      *, active_claims_empty: bool = False) -> bool:
    """Apply the design §C.3 acceptance rule (validator's gate only).

    Accepted iff every field evaluation is synthesized_complete, or
    synthesized_empty with a legitimate empty per the demand sets,
    AND coverage.verdict == "pass". Legitimate empties: disagreements
    iff no unresolved objections demanded; recommendations iff no
    proposals demanded; positions iff no active claims exist.
    Limitations empties are NOT adjudicated here (Q1: human review).
    A mechanical pass is not production adoption — substantive
    fidelity review is a separate, human judgment (§C.3 note 5).
    """
    if not coverage or coverage.get("verdict") != "pass":
        return False
    objections_empty = not coverage.get("objections", {}).get("required")
    proposals_empty = not coverage.get("proposals", {}).get("required")
    legitimate_empty = {
        "positions": active_claims_empty,
        "disagreements": objections_empty,
        "recommendations": proposals_empty,
        # Limitations: not adjudicated mechanically in v1 (Q1) —
        # an empty limitations field therefore does not block the
        # mechanical gate; its substance is human review's job
        # (§3.2 criterion 5), exactly as the disclosure-note
        # condition already treats it.
        "limitations": True,
    }
    for field in _CONTRACT_FIELDS:
        value = (evaluations or {}).get(field)
        if value == "synthesized_complete":
            continue
        if value == "synthesized_empty" and legitimate_empty[field]:
            continue
        return False
    return True


def coverage_function_signature() -> list[str]:
    """Parameter names of :func:`check_coverage`, for the §G.4 test.

    The coverage function takes (registry, unresolved_objections,
    structured) only — no participant, no prompt, no client — so
    there is no generation capability to misuse.
    """
    return list(inspect.signature(check_coverage).parameters)
