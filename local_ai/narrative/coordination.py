"""Context-availability contract (addendum I2 + availability-vs-delivery).

Availability is NOT delivery. The default pattern is:

    eligible evidence → consent/relevance assessment →
    authorized context retrieval → existing seat generation.

``prepare_context`` implements the middle two steps and returns
retrievable context; it never sends, pushes, or generates anything.
There is no generation function anywhere on this path — structurally,
not by policy: the function takes no ``generate_fn`` and the module
imports no generation machinery. A branch encounters available
context during its own next authorized interaction (Phase 2 wiring);
in Phase 1, availability is proven with fixtures only.

Revalidation rule: every preparation re-reads BOTH consent flags and
recomputes relevance fresh. A stored assessment from an earlier
preparation is never consulted for the decision — prior eligibility
does not permanently authorize subsequent disclosure, so revoked
consent or changed relevance closes availability immediately.
Caching and precomputation remain allowed for the assessment record
itself; they never substitute for the fresh check.

Decline is not a function here, deliberately: declining context is
a branch simply not retrieving or not using what was made
available. It creates no row, no flag, and no record of any kind —
a consequence-free non-act. Tests assert the zero-row property
rather than calling a decline endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass

from .branches import get_branch
from .consent import (
    coordination_allowed,
    steward_consent_allowed,
    steward_coordination_allowed,
)
from .models import DiscrepancyFlag, RelevanceAssessment
from .relevance import assess_relevance
from .store import NarrativeStore


@dataclass(frozen=True)
class ContextAvailability:
    """The outcome of one context preparation.

    ``available`` is True only when consent, contract, thread, and
    relevance all pass at preparation time. When unavailable,
    ``context`` is None — no thread content leaks through a denied
    preparation, not even a title. ``assessment`` is the stored
    relevance row (None when consent closed before assessment, or
    when the branch/thread gates failed first).
    """

    available: bool
    reason: str
    assessment: RelevanceAssessment | None = None
    derivation_allowed: bool = False
    coordination_allowed_flag: bool = False
    context: dict | None = None


def prepare_context(
    store: NarrativeStore,
    user_id: str,
    branch_id: str,
    *,
    thread_id: str | None = None,
    candidate_text: str = "",
    candidate_entity_refs: tuple[str, ...] | list[str] = (),
    candidate_strand_weights: dict | None = None,
    attended_entity_refs: tuple[str, ...] | list[str] = (),
    attended_thread_ids: tuple[str, ...] | list[str] = (),
    connection=None,
) -> ContextAvailability:
    """Prepare retrievable context for one branch, or refuse it.

    Raises ``ValueError`` for an unknown branch id (a registry
    configuration error). Every other failure is a returned
    ``available=False`` with a reason code — never an exception
    carrying thread content, and never a partial payload.
    """
    contract = get_branch(branch_id)
    if contract is None:
        raise ValueError(f"unknown branch: {branch_id!r}")
    derivation = steward_consent_allowed(user_id, connection=connection)
    coordination_flag = steward_coordination_allowed(
        user_id, connection=connection
    )
    if "coordination" not in contract.capabilities:
        return ContextAvailability(
            available=False,
            reason="branch_not_coordination_contracted",
            derivation_allowed=derivation,
            coordination_allowed_flag=coordination_flag,
        )
    if not (derivation and coordination_flag):
        # No coordination work happens at all when consent is
        # closed: no assessment row, no relevance computation.
        return ContextAvailability(
            available=False,
            reason="consent_closed",
            derivation_allowed=derivation,
            coordination_allowed_flag=coordination_flag,
        )
    thread = None
    if thread_id is not None:
        thread = store.get_thread(user_id, thread_id)
        if thread is None:
            return ContextAvailability(
                available=False,
                reason="thread_not_found",
                derivation_allowed=derivation,
                coordination_allowed_flag=coordination_flag,
            )
    result = assess_relevance(
        branch_id,
        candidate_text=candidate_text,
        candidate_entity_refs=candidate_entity_refs,
        candidate_strand_weights=candidate_strand_weights,
        candidate_thread_id=thread_id,
        attended_entity_refs=attended_entity_refs,
        attended_thread_ids=attended_thread_ids,
    )
    assessment = store.record_relevance_assessment(
        user_id,
        branch_id,
        thread_id=thread_id,
        evidence_refs=candidate_entity_refs,
        relevant=result.relevant,
        reasons=result.reasons,
        inputs=result.inputs,
    )
    if not result.relevant:
        return ContextAvailability(
            available=False,
            reason="relevance_not_established",
            assessment=assessment,
            derivation_allowed=derivation,
            coordination_allowed_flag=coordination_flag,
        )
    context = None
    if thread is not None:
        # Bounded, store-read-only thread summary. Richer prepared
        # context (readings, renderings) is Phase 2's
        # narrative_context_for; Phase 1 proves availability, not
        # rendering.
        context = {
            "thread_id": thread.id,
            "title": thread.title,
            "status": thread.status,
            "scope": thread.scope,
            "strand_weights": thread.strand_weights or {},
            "origin": thread.origin,
            "created_at": thread.created_at,
        }
    return ContextAvailability(
        available=True,
        reason="available",
        assessment=assessment,
        derivation_allowed=derivation,
        coordination_allowed_flag=coordination_flag,
        context=context,
    )


def coordination_gate(
    user_id: str,
    *,
    connection=None,
) -> bool:
    """Both consent flags, re-read now (see consent.py)."""
    return coordination_allowed(user_id, connection=connection)


def record_discrepancy_flag(
    store: NarrativeStore,
    user_id: str,
    assessment_id: str,
    branch_id: str,
    *,
    objection: str = "",
    evidence_refs: tuple[str, ...] | list[str] = (),
) -> DiscrepancyFlag:
    """Record a flag-only discrepancy objection.

    Delegates to the store, which validates that the assessment
    exists for this user and never modifies it. The flag preserves
    the original assessment (by id), the objection, and supporting
    evidence references; it changes no shared evidence, triggers
    no model generation, and initiates no adjudication. Declining
    context is not a flag: there is no decline-recording function
    by design.
    """
    return store.record_discrepancy_flag(
        user_id,
        assessment_id,
        branch_id,
        objection=objection,
        evidence_refs=evidence_refs,
    )
