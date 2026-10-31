"""Deterministic convener-close (Increment C, accepted schema contract §4).

Pure stdlib; no imports from meeting.py, so this module cannot mutate
the record it reads. It answers one question at meeting close: which
disposition proposals may become DispositionEvents, under what
authorization — and which must stay pending, and why.

Design rules (contract §4 + plan Increment C):

- Proposals never mutate standing (§4.1). Only DispositionEvents do,
  and only convener-close issues them. No other step may issue one.
- Acceptance is evidence, not authorization. An explicit acceptance by
  the target author supports an authorized event; it never permits
  arbitrary mutation. Before issuing ANY event, convener-close verifies
  four checks, in this order: (1) the issuer is the convener-close
  process itself; (2) the accepted proposal exists and matches target +
  proposed standing; (3) the applicable §4.2 rule covers this event
  type; (4) the event is chain-correct (prior_standing, sequence, and
  for revised events the revision_claim — E8/E9 prevention). If any
  check fails, no event is issued and the proposal stays pending, with
  a refusal reason naming the failed check.
- Acceptance signal (decided): explicit and claim-based ONLY. An
  acceptance record must identify the TARGET CLAIM, the PROPOSED
  DISPOSITION (proposal id), and the ACCEPTING AUTHOR (verified
  identity). A generic endorsement is insufficient and never counts:
  acceptance records without a proposal id are not acceptances, and
  ``endorses`` declarations never become acceptances (acceptances are
  caller-supplied structured records only — this module never parses
  prose acceptances, which would be inference dressed as evidence).
- No auto-trigger: a proposal's absence from any final active set
  never triggers withdrawal or supersession. The final active set is
  a report, not a trigger. Standing changes only via DispositionEvents.
- User authorizer (decided): build-council close must NOT accept
  ``user`` as a meeting-level disposition authorizer (E7). Product
  meetings may accept user acceptance only with a cited decision
  (validator-consistent); product user authority is otherwise
  deferred, not built here.
- The target author's own revision is NOT acceptance. Per contract
  §8, a SPEC-style disposition (``revised``, by=<revision claim>) FAILS
  E7: a claim is not an authorizer. This module never reads the legacy
  ``disposition`` / ``disposition_by`` fields: C4 authorial disposition
  is an observation, never an authorization.
- Contested-standing is structural (§4.3), not authorizational: a
  qualifying challenge (specific challenge, identified target, not
  withdrawn/resolved, challenge + available responses cited) records
  contest; the convener never judges whether the challenge is correct.
  Contested-standing means disputed — NOT disproven, NOT demoted.
- No precedence hierarchy in v1: proposal-driven events issue first
  (input order), then contested-standing events (challenge order).
  A target may carry several events in one close; derivation is
  last-wins by sequence. Ordering across types is mechanical, not a
  judgment about which outcome matters more. Note the consequence is
  defensible, not arbitrary: a revision does not resolve a challenge
  (only an event on the challenge itself does), so a target revised
  and still challenged derives contested-standing.
- Supersession needs a cited meeting rule in force. The runner passes
  no rule registry, so runner-extracted supersession proposals stay
  pending until a rule-citation input exists; this module never
  invents a rule. That is a known limitation, not a gap to paper over.
- Validator gap, documented not fixed: the validator checks acceptance
  AUTHOR identity for convener-close events but does not verify the
  acceptance cites a matching proposal. Convener-close enforces that
  linkage itself (check 2); a hand-built record could pass validator
  E7 while violating check 2. Changing validator behavior is out of
  C's scope (no validation-in-the-loop gate); the gap is unreachable
  through this module, which always links basis to proposal.
"""

from __future__ import annotations

from local_ai.build_room.transjective_record import STANDING_VALUES

__all__ = [
    "extract_proposals",
    "convener_close",
]

# Kinds whose revision-phase declarations propose a revision of the
# target. A proposal changes nothing; the acceptance gate (check 2/3)
# is what protects standing, so inclusion here costs list noise only.
_REVISED_KINDS = ("corrects", "extends", "integrates")
# Legacy relationship labels (multi- or single-target) that propose a
# move. ``reclassifies`` is deliberately absent: a downgrade is not a
# move. ``endorses`` is deliberately absent: an endorsement is not a
# defense, and generic endorsement never counts as acceptance.
_REVISED_LABELS = ("proposes_revision_of", "revised")
_WITHDRAWN_LABELS = ("supports_withdrawal_of", "withdrawn")
_ISSUABLE_STANDINGS = tuple(s for s in STANDING_VALUES if s != "open")


def _author(claim: dict) -> str:
    return claim.get("participant", "") or claim.get("author", "") or ""


def _claim_ids(claims: list[dict]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for claim in claims:
        cid = claim.get("id", "")
        if cid and cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def extract_proposals(
    claims: list[dict], declarations: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Derive disposition proposals + challenge candidates from claims.

    Deterministic and read-only. Inputs are claim dicts (as produced
    by ``Claim.to_dict()``) plus adapter declarations (source_claim /
    target_claim / kind). Rules, in order:

    - ``supersedes`` field -> superseded proposal (superseding claim
      is the claim itself; no rule is cited, so it stays pending
      until a rule-citation input exists).
    - ``withdraws`` field -> withdrawn proposal.
    - Legacy multi/single-target labels: ``proposes_revision_of`` /
      ``revised`` (revision phase only) -> revised proposal;
      ``supports_withdrawal_of`` / ``withdrawn`` -> withdrawn proposal.
    - Declarations: ``defends`` -> maintained proposal (the C94 shape:
      a defense is a proposal, never an enactment); ``corrects`` /
      ``extends`` / ``integrates`` from a revision-phase source ->
      revised proposal (revision_claim is the source); ``challenges``
      -> challenge candidate, not a proposal.
    - ``endorses`` / ``repeats`` / ``requests-evidence`` / ``other``
      -> nothing. In particular, endorsements never become
      acceptances or maintain proposals.

    Proposal ids are ``prop:<source>:<target>:<standing>``; first wins
    on collision. Every proposal carries evidence (its source claim),
    so W4 (thin proposals) never fires on extracted proposals.
    """
    by_id: dict[str, dict] = {}
    for claim in claims:
        cid = claim.get("id", "")
        if cid and cid not in by_id:
            by_id[cid] = claim

    proposals: list[dict] = []
    seen_proposals: set[str] = set()

    def add_proposal(
        source: str,
        target: str,
        standing: str,
        *,
        revision_claim: str | None = None,
        superseding_claim: str | None = None,
    ) -> None:
        if source not in by_id or target not in by_id or source == target:
            return
        pid = f"prop:{source}:{target}:{standing}"
        if pid in seen_proposals:
            return
        seen_proposals.add(pid)
        proposal: dict[str, object] = {
            "id": pid,
            "proposer": _author(by_id[source]),
            "target_claim": target,
            "proposed_standing": standing,
            "evidence": [source],
        }
        if revision_claim:
            proposal["revision_claim"] = revision_claim
        if superseding_claim:
            proposal["superseding_claim"] = superseding_claim
        proposals.append(proposal)

    # Pass 1: explicit claim fields and legacy labels.
    for claim in claims:
        src = claim.get("id", "")
        if not src or src not in by_id:
            continue
        if claim.get("supersedes"):
            add_proposal(src, claim["supersedes"], "superseded",
                         superseding_claim=src)
        if claim.get("withdraws"):
            add_proposal(src, claim["withdraws"], "withdrawn")
        targets: list[str] = list(claim.get("relationship_targets") or [])
        if not targets and claim.get("relationship_target"):
            targets = [claim["relationship_target"]]
        label = claim.get("relationship", "")
        if label in _REVISED_LABELS and claim.get("phase") == "revision":
            for tgt in targets:
                add_proposal(src, tgt, "revised", revision_claim=src)
        elif label in _WITHDRAWN_LABELS:
            for tgt in targets:
                add_proposal(src, tgt, "withdrawn")

    # Pass 2: declarations (native Increment A + adapter-derived).
    challenges: list[dict] = []
    seen_challenges: set[tuple[str, str]] = set()
    phase_by_id = {cid: by_id[cid].get("phase", "") for cid in by_id}
    for decl in declarations:
        src = decl.get("source_claim", "")
        tgt = decl.get("target_claim", "")
        kind = decl.get("kind", "")
        if not src or not tgt or src == tgt:
            continue
        if src not in by_id or tgt not in by_id:
            continue
        if kind == "defends":
            add_proposal(src, tgt, "maintained")
        elif kind in _REVISED_KINDS and phase_by_id.get(src) == "revision":
            add_proposal(src, tgt, "revised", revision_claim=src)
        elif kind == "challenges":
            if (src, tgt) not in seen_challenges:
                seen_challenges.add((src, tgt))
                responses = [
                    d.get("source_claim", "")
                    for d in declarations
                    if d.get("target_claim") == src
                    and d.get("source_claim", "") not in ("", src)
                ]
                challenges.append({
                    "challenge_claim": src,
                    "target": tgt,
                    "response_claims": responses,
                })
    return proposals, challenges


def _check_existing_chain(existing_events: list[dict]) -> str | None:
    """Mirror the validator's E9 chain rules over existing events.

    Returns a detail string on break, else None. Gaps in sequence are
    fine (monotonic + unique is the rule, not contiguity); duplicate
    sequences or prior_standing mismatches are breaks.
    """
    ordered = sorted(
        existing_events,
        key=lambda e: e.get("sequence") if isinstance(e.get("sequence"), int) else 0,
    )
    sequences = [e.get("sequence") for e in existing_events]
    if len(sequences) != len(set(sequences)) and sequences:
        return "existing event sequences are not unique"
    per_target: dict[str, list[dict]] = {}
    for event in ordered:
        per_target.setdefault(event.get("target_claim", ""), []).append(event)
    for tgt, chain in per_target.items():
        if chain[0].get("prior_standing") != "open":
            return (f"existing event chain for {tgt} does not start "
                    f"from open")
        for prev, cur in zip(chain, chain[1:]):
            if cur.get("prior_standing") != prev.get("new_standing"):
                return (f"existing event chain break for {tgt}: "
                        f"prior_standing does not match previous "
                        f"new_standing")
    return None


def _derive_standing(
    claim_ids: list[str],
    events: list[dict],
) -> dict[str, str]:
    """Last-wins derivation from an ordered event history."""
    standing = {cid: "open" for cid in claim_ids}
    ordered = sorted(
        events,
        key=lambda e: e.get("sequence") if isinstance(e.get("sequence"), int) else 0,
    )
    for event in ordered:
        tgt = event.get("target_claim", "")
        new = event.get("new_standing", "")
        if tgt in standing and new in STANDING_VALUES:
            standing[tgt] = new
    return standing


def convener_close(
    claims: list[dict],
    proposals: list[dict],
    acceptances: list[dict],
    challenges: list[dict],
    *,
    meeting_kind: str = "build_council",
    meeting_rules: tuple[str, ...] | list[str] = (),
    existing_events: list[dict] | None = None,
    issuer: str = "convener-close",
) -> dict:
    """Execute deterministic convener-close over one meeting's inputs.

    ``claims`` are claim dicts (id / participant / author).
    ``proposals`` are DispositionProposal dicts. ``acceptances`` are
    structured records {target_claim, proposal_id, accepting_author,
    [claim_id], [user_decision]}. ``challenges`` are {challenge_claim,
    target, [response_claims]}. ``existing_events`` are already-issued
    events the new events chain onto (empty for a fresh close).

    Returns {events, proposals, refusals, unmatched_acceptances,
    derived_standing, existing_chain_broken}. Every proposal is
    accounted for: issued as exactly one event, or refused with a
    reason naming the failed check. Refusals are reports, not triggers:
    a refused proposal changes nothing.
    """
    claim_ids = _claim_ids(claims)
    by_id: dict[str, dict] = {}
    for claim in claims:
        cid = claim.get("id", "")
        if cid and cid not in by_id:
            by_id[cid] = claim
    rules = list(meeting_rules or [])
    existing = list(existing_events or [])

    refusals: list[dict] = []
    unmatched_acceptances: list[dict] = []

    def refuse(proposal: dict, reason: str) -> None:
        refusals.append({
            "proposal_id": proposal.get("id", ""),
            "target_claim": proposal.get("target_claim", ""),
            "proposed_standing": proposal.get("proposed_standing", ""),
            "reason": reason,
        })

    # Pre-pass: dedupe proposals (first wins). Duplicates and id-less
    # records are refused here, so the main loop never sees them.
    deduped_proposals: list[dict] = []
    _seen_pids: set[str] = set()
    for _prop in proposals:
        if not isinstance(_prop, dict):
            refusals.append({
                "proposal_id": "",
                "target_claim": "",
                "proposed_standing": "",
                "reason": "proposal is not a structured record",
            })
            continue
        _pid = _prop.get("id", "")
        if not _pid:
            refusals.append({
                "proposal_id": "",
                "target_claim": "",
                "proposed_standing": "",
                "reason": "proposal without id",
            })
            continue
        if _pid in _seen_pids:
            refusals.append({
                "proposal_id": _pid,
                "target_claim": _prop.get("target_claim", ""),
                "proposed_standing": _prop.get("proposed_standing", ""),
                "reason": "duplicate proposal id; first proposal kept",
            })
            continue
        _seen_pids.add(_pid)
        deduped_proposals.append(_prop)

    # Global gate (check 1): only convener-close issues events.
    if issuer != "convener-close":
        for prop in deduped_proposals:
            refuse(prop, "issuer is not convener-close; no event issued")
        return {
            "events": [],
            "proposals": deduped_proposals,
            "refusals": refusals,
            "unmatched_acceptances": list(acceptances),
            "derived_standing": _derive_standing(claim_ids, existing),
            "existing_chain_broken": None,
        }

    # Global gate (check 4, pre-condition): never build on a broken
    # chain. Validation (E9) flags the break independently; close
    # refuses to compound it.
    chain_break = _check_existing_chain(existing)
    if chain_break is not None:
        for prop in deduped_proposals:
            refuse(prop, f"existing event chain broken ({chain_break}); "
                         f"close issued nothing")
        return {
            "events": [],
            "proposals": deduped_proposals,
            "refusals": refusals,
            "unmatched_acceptances": list(acceptances),
            "derived_standing": _derive_standing(claim_ids, existing),
            "existing_chain_broken": chain_break,
        }

    # Index structured acceptances; anything else is not an
    # acceptance (generic endorsement insufficient, by definition).
    proposals_by_id: dict[str, dict] = {}
    for prop in deduped_proposals:
        proposals_by_id[prop.get("id", "")] = prop
    acceptance_by_proposal: dict[str, list[dict]] = {}
    for acc in acceptances:
        if not isinstance(acc, dict):
            unmatched_acceptances.append({
                "acceptance": acc,
                "reason": "acceptance is not a structured record",
            })
            continue
        pid = acc.get("proposal_id", "")
        tgt = acc.get("target_claim", "")
        author = acc.get("accepting_author", "")
        if not pid:
            unmatched_acceptances.append({
                "acceptance": acc,
                "reason": "acceptance without proposal id is not an "
                          "acceptance (generic endorsement insufficient)",
            })
            continue
        if not tgt or not author:
            unmatched_acceptances.append({
                "acceptance": acc,
                "reason": "acceptance without target claim or accepting "
                          "author is not an acceptance",
            })
            continue
        if acc.get("claim_id") and acc["claim_id"] not in by_id:
            unmatched_acceptances.append({
                "acceptance": acc,
                "reason": "acceptance cites unknown claim",
            })
            continue
        if pid not in proposals_by_id:
            unmatched_acceptances.append({
                "acceptance": acc,
                "reason": "acceptance cites unknown proposal",
            })
            continue
        acceptance_by_proposal.setdefault(pid, []).append(acc)

    events: list[dict] = []
    standing = _derive_standing(claim_ids, existing)
    sequences = [e.get("sequence") for e in existing
                 if isinstance(e.get("sequence"), int)]
    next_seq = (max(sequences) + 1) if sequences else 0
    issued_contested_keys: set[tuple[str, str]] = set()

    def issue_event(
        target: str,
        new_standing: str,
        basis: dict,
        *,
        authorizer: str = "convener-close",
        revision_claim: str | None = None,
    ) -> dict:
        nonlocal next_seq
        event: dict[str, object] = {
            "event_id": f"evt:{next_seq}",
            "target_claim": target,
            "prior_standing": standing.get(target, "open"),
            "new_standing": new_standing,
            "authorizer": authorizer,
            "authorizing_basis": basis,
            "sequence": next_seq,
        }
        next_seq += 1
        if revision_claim:
            event["revision_claim"] = revision_claim
        events.append(event)
        standing[target] = new_standing
        return event

    # Proposal-driven events, in input order.
    for prop in deduped_proposals:
        pid = prop.get("id", "")
        tgt = prop.get("target_claim", "")
        new = prop.get("proposed_standing", "")
        if tgt not in by_id:
            refuse(prop, "proposal targets unknown claim")
            continue
        if not prop.get("proposer"):
            refuse(prop, "proposal without proposer")
            continue
        if new not in _ISSUABLE_STANDINGS:
            refuse(prop, f"proposed standing {new!r} is not issuable "
                         f"(open is never set by an event)")
            continue
        if new in ("revised", "withdrawn", "maintained"):
            # Check 2: a linked acceptance naming this proposal and
            # this target. Check 3: its author must be the target
            # author (or, product-only, the user with a cited
            # decision).
            linked = acceptance_by_proposal.get(pid, [])
            target_matched = [a for a in linked
                              if a.get("target_claim") == tgt]
            if not linked:
                refuse(prop, "no linked acceptance; proposal stays pending")
                continue
            if not target_matched:
                refuse(prop, "acceptance target mismatch; proposal stays "
                             "pending")
                continue
            target_author = _author(by_id[tgt])
            accepted = None
            saw_user_refusal = False
            saw_other_author = False
            for acc in target_matched:
                author = acc.get("accepting_author", "")
                if author == "user" and meeting_kind != "product":
                    saw_user_refusal = True
                    continue
                if author == "user" and not acc.get("user_decision"):
                    saw_user_refusal = True
                    continue
                if author == "user" and meeting_kind == "product":
                    # Product-only user authorization (validator-
                    # consistent): the cited decision is the basis.
                    accepted = acc
                    break
                if author == target_author and target_author:
                    accepted = acc
                    break
                saw_other_author = True
            if accepted is None:
                if saw_other_author:
                    refuse(prop, "acceptance by non-author; proposal "
                                 "stays pending")
                elif saw_user_refusal:
                    if meeting_kind != "product":
                        refuse(prop, "user authorizer invalid in "
                                     "build-council meeting")
                    else:
                        refuse(prop, "user acceptance without cited "
                                     "decision")
                else:
                    refuse(prop, "no linked acceptance; proposal stays "
                                 "pending")
                continue
            if new == "revised" and not prop.get("revision_claim"):
                refuse(prop, "revised proposal without revision claim "
                             "(E8)")
                continue
            basis: dict[str, object] = {
                "proposal_ids": [pid],
                "acceptance": {
                    "author": accepted.get("accepting_author", ""),
                    "proposal_id": pid,
                },
            }
            if accepted.get("claim_id"):
                basis["acceptance"]["claim_id"] = accepted["claim_id"]
            # The validator only accepts "convener-close" or "user"
            # authorizers; a target-author acceptance issues through
            # convener-close, never under the participant's own name.
            if accepted.get("accepting_author") == "user":
                basis["user_decision"] = accepted.get("user_decision")
                event_authorizer = "user"
            else:
                event_authorizer = "convener-close"
            issue_event(
                tgt, new, basis,
                authorizer=event_authorizer,
                revision_claim=prop.get("revision_claim"),
            )
        elif new == "superseded":
            rule = prop.get("meeting_rule")
            sup = prop.get("superseding_claim", "")
            if not rule or rule not in rules:
                refuse(prop, "supersession without cited meeting rule "
                             "in force; proposal stays pending")
                continue
            if not sup or sup not in by_id:
                refuse(prop, "supersession without superseding claim; "
                             "proposal stays pending")
                continue
            issue_event(tgt, "superseded", {
                "proposal_ids": [pid],
                "meeting_rule": rule,
                "superseding_claim": sup,
            })
        elif new == "contested-standing":
            # Contested proposals ride the same §4.3 bar as standalone
            # challenges; the proposal alone authorizes nothing.
            qualifying = _qualifying_challenge(
                challenges, tgt, standing_events(existing, events), by_id)
            if qualifying is None:
                refuse(prop, "no §4.3-qualifying challenge for contested-"
                             "standing proposal; proposal stays pending")
                continue
            issue_event(tgt, "contested-standing", {
                "proposal_ids": [pid],
                "challenge": qualifying,
            })
            issued_contested_keys.add(
                (qualifying["challenge_claim"], tgt))

    # Standalone challenges, in input order (no proposal needed: the
    # §4.3 bar, not an acceptance, is the authorization).
    for chal in challenges:
        if not isinstance(chal, dict):
            continue
        cclaim = chal.get("challenge_claim", "")
        tgt = chal.get("target", "")
        if not cclaim or not tgt or cclaim == tgt:
            continue
        if (cclaim, tgt) in issued_contested_keys:
            continue
        if cclaim not in by_id or tgt not in by_id:
            continue
        detail = _contested_bar_detail(
            cclaim, tgt, standing_events(existing, events))
        if detail is not None:
            continue
        basis_challenge: dict[str, object] = {
            "challenge_claim": cclaim,
            "target": tgt,
        }
        responses = [r for r in (chal.get("response_claims") or [])
                     if r in by_id]
        if responses:
            basis_challenge["response_claims"] = responses
        issue_event(tgt, "contested-standing", {
            "challenge": basis_challenge,
        })
        issued_contested_keys.add((cclaim, tgt))

    return {
        "events": events,
        "proposals": deduped_proposals,
        "refusals": refusals,
        "unmatched_acceptances": unmatched_acceptances,
        "derived_standing": standing,
        "existing_chain_broken": None,
    }


def standing_events(existing: list[dict], issued: list[dict]) -> list[dict]:
    """Combined event history for bar checks (existing + issued)."""
    return list(existing) + list(issued)


def _contested_bar_detail(
    challenge_claim: str, target: str, events: list[dict]
) -> str | None:
    """§4.3 structural bar over an event history. None when it holds.

    Legs: challenge identified (caller's job to cite an existing
    claim); target identified and distinct; challenge not withdrawn
    or superseded by any event in the history. Correctness is never
    judged. Response citation is basis content, not a bar leg.
    """
    for event in events:
        if (event.get("target_claim") == challenge_claim
                and event.get("new_standing") in ("withdrawn", "superseded")):
            return "challenge has been withdrawn or superseded"
    return None


def _qualifying_challenge(
    challenges: list[dict], target: str, events: list[dict],
    by_id: dict,
) -> dict | None:
    """First challenge for target passing the §4.3 bar, else None."""
    for chal in challenges:
        if not isinstance(chal, dict):
            continue
        cclaim = chal.get("challenge_claim", "")
        if not cclaim or chal.get("target") != target or cclaim == target:
            continue
        if _contested_bar_detail(cclaim, target, events) is not None:
            continue
        basis_challenge: dict[str, object] = {
            "challenge_claim": cclaim,
            "target": target,
        }
        responses = [r for r in (chal.get("response_claims") or [])
                     if r in by_id]
        if responses:
            basis_challenge["response_claims"] = responses
        return basis_challenge
    return None
