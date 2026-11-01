"""Narrative correspondence: synthesis without consolidation (Phase 7, addendum §3).

The steward recognizes the SHAPE of a tension between observations
or interpretations and offers structure — evidence references, the
structural tension, a proposed relationship, a mapping of which
elements parallel which, and the limitations where the analogy
fails — without resolving the tension. The candidate metaphor is
optional and illustrative only: a parable generated from three
observations can never subsequently be cited as a fourth.

Rules enforced here, not merely documented:

- Correspondence is not equivalence. ``limitations`` is required:
  a proposal without a stated breakdown is refused, because
  mythological framing without a breakdown becomes narrative
  imposition.
- Metaphors illuminate evidence, never become evidence. A
  correspondence id (``corr-`` prefix) is not a thread_evidence
  row id, readings can only cite thread_evidence rows (audit
  invariant 1), and no code path writes a correspondence into
  an evidence table. There is no self-referential corroboration
  loop to exploit.
- An analogy's elegance is never evidence for its accuracy.
  Nothing here scores, ranks, or rewards a correspondence for
  being compelling, adopted, or agreed with.
- Abstention is a complete result. When the evidence cannot
  establish a meaningful relationship — fewer than two refs,
  refs from a single thread, refs that do not resolve to real
  evidence rows — :func:`propose_correspondence` returns an
  abstention outcome and writes NOTHING. No row, no proposal,
  no queue item. The system must not develop a bias toward
  mythologizing ordinary events.
- Seats own expression. The steward offers structure, never
  polished prose, and never delivers a finished parable to the
  user as an authoritative telling. Each seat may adopt the
  proposed metaphor, translate its underlying relationship into
  imagery native to its jurisdiction and register, or decline
  it entirely — via :func:`respond_to_correspondence`. A seat
  response never moves the correspondence's status: only a
  user verdict (through the review layer) accepts or rejects.
- No auto-chaining. Nothing in this module is called from
  discovery, derivation, or sweep: a correspondence is proposed
  only when a caller supplies explicit evidence refs.
- No generation. This module takes no generate_fn and imports
  no generation machinery: proposing structure is a store
  write, and seats express it through their existing
  generation when they choose to.
"""

from __future__ import annotations

from dataclasses import dataclass

from .branches import get_branch
from .models import Correspondence
from .store import NarrativeStore

#: A correspondence needs a tension BETWEEN observations: refs
#: from at least two distinct threads. A single thread's tension
#: is revision's job (Phase 6 schedule), not correspondence.
_MIN_THREADS = 2


@dataclass(frozen=True)
class CorrespondenceOutcome:
    """The complete result of a correspondence proposal attempt.

    Either ``correspondence`` (a proposed row) or ``abstained``
    with a reason — never both, never an exception for
    insufficient evidence. An abstention writes nothing: it is
    a complete result, not a failure, and not a queue item.
    """

    correspondence: Correspondence | None
    abstained: bool = False
    abstention_reason: str | None = None


def _resolve_evidence_threads(
    store: NarrativeStore, user_id: str, evidence_refs: list[str]
) -> dict[str, str]:
    """Map each evidence ref to its thread, or raise.

    Refs here are thread_evidence ROW ids (the only thing
    readings may cite, audit invariant 1). A ref that does
    not resolve to a real evidence row for this user is a
    caller error, not an abstention: the steward never
    proposes structure on evidence it cannot show.
    """
    resolved: dict[str, str] = {}
    for thread in store.threads_for(user_id, limit=None):
        for row in store.evidence_for(user_id, thread.id):
            if row.id in evidence_refs:
                resolved[row.id] = thread.id
    missing = [ref for ref in evidence_refs if ref not in resolved]
    if missing:
        raise ValueError(
            f"correspondence evidence refs do not resolve to "
            f"evidence rows: {missing}"
        )
    return resolved


def propose_correspondence(
    store: NarrativeStore,
    user_id: str,
    *,
    evidence_refs: list[str],
    structural_tension: str,
    proposed_relationship: str,
    candidate_metaphor: str | None = None,
    mapping: dict | None = None,
    limitations: str = "",
    supersedes_id: str | None = None,
) -> CorrespondenceOutcome:
    """Propose a correspondence, or abstain completely.

    Abstains (writing nothing) when: fewer than two evidence
    refs; refs spanning fewer than two threads; or no
    limitations stated (a breakdown is essential — without
    it the framing risks imposing meaning). A missing
    structural tension or proposed relationship is also an
    abstention: the steward does not propose structure it
    cannot state.
    """
    if len(evidence_refs) < _MIN_THREADS:
        return CorrespondenceOutcome(
            correspondence=None,
            abstained=True,
            abstention_reason=(
                "fewer than two evidence refs: no tension "
                "between observations is established"
            ),
        )
    if not structural_tension or not proposed_relationship:
        return CorrespondenceOutcome(
            correspondence=None,
            abstained=True,
            abstention_reason=(
                "structural tension or proposed relationship "
                "not stated: nothing meaningful to propose"
            ),
        )
    if not limitations:
        return CorrespondenceOutcome(
            correspondence=None,
            abstained=True,
            abstention_reason=(
                "no limitations stated: an analogy without a "
                "breakdown risks imposing meaning"
            ),
        )
    resolved = _resolve_evidence_threads(store, user_id, evidence_refs)
    thread_ids = sorted(set(resolved.values()))
    if len(thread_ids) < _MIN_THREADS:
        return CorrespondenceOutcome(
            correspondence=None,
            abstained=True,
            abstention_reason=(
                "evidence refs span a single thread: a "
                "correspondence needs a tension between "
                "observations, not within one story"
            ),
        )
    record = store.create_correspondence(
        user_id,
        thread_ids=thread_ids,
        evidence_refs=list(evidence_refs),
        structural_tension=structural_tension,
        proposed_relationship=proposed_relationship,
        candidate_metaphor=candidate_metaphor,
        mapping=mapping,
        limitations=limitations,
        supersedes_id=supersedes_id,
    )
    return CorrespondenceOutcome(correspondence=record)


def respond_to_correspondence(
    store: NarrativeStore,
    user_id: str,
    correspondence_id: str,
    branch_id: str,
    response: str,
    expression: str = "",
):
    """One seat's adopt / translate / decline on a correspondence.

    Only confirmed branches may respond: the sibling record
    and the deferred branch are candidates, not confirmed
    branches, and reading surfaces are not in the registry
    at all. The response is the seat's own expression — for
    translate, its own imagery is required — and it never
    moves the correspondence's status. A decline here is the
    seat's response, not a disagreement record and not a
    penalty.
    """
    contract = get_branch(branch_id)
    if contract is None:
        raise ValueError(f"unknown branch: {branch_id!r}")
    if contract.status != "confirmed":
        raise ValueError(
            f"branch {branch_id!r} is not a confirmed branch "
            f"(status {contract.status!r}); only confirmed "
            f"branches may respond to a correspondence"
        )
    return store.record_correspondence_response(
        user_id, correspondence_id, branch_id, response, expression
    )
