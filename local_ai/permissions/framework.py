"""The permission framework check (Slice 1, foundation).

Implements Rev2 §2.5's five steps as amended by C1.8 (step 4) and
C4.3 (step 2), plus the implementation clarification's three-way
pause distinction (I.1):

1. Is the capability registered? If not, fail closed: no asking, no
   capture, no action. (Mirrors ``check_scope`` returning False for
   unknown scopes, and the steward gate resolving unknown to False.)
2. Is the global pause override set? If so, do not START new covered
   operations — regardless of stance. The underlying stance is not
   consulted for starting, and is not modified. Two carve-outs from
   clarification I.1, kept distinct from a new start:
   - answering an EXISTING instance request (``is_existing_instance``)
     may complete FOR THAT INSTANCE ONLY — it never writes a stance
     change and never starts a new operation;
   - explicitly CHANGING a standing permission is a stance-store
     write (``store.set_stance``), not a framework-check outcome:
     it succeeds while paused but takes no effect for new operations
     until un-pause.
3. What is the effective stance for the instance's scope rows
   (most-restrictive join across rows of ONE capability)? Ask me →
   surface the instance for a decision and act only on a yes (or a
   correction). Just do it → act within the recorded scope limits,
   without asking. Don't do it → do not act.
4. (C1.8) Does the instance fall in a consequential class, and if
   so, is it covered by an explicit authorization contract within
   its limits? Covered and within limits → proceed under the stance.
   Not covered, exceeding limits, or in a C1.6 never-coverable class
   → per-transaction confirmation with justification shown. A
   Just-do-it stance never overrides C1.6, and never covers an
   instance outside its contract. NOTE (Slice 1 bound): the
   contract's step-4 SHAPE lands here; contract enforcement —
   execution-time re-checks (I.2), atomic cap accounting (I.3) —
   lands in Slice 6.
5. Does the act cross a capability boundary? If so, it requires
   that neighbor capability's own authorization (or its exception
   confirmation). A remember authorization never smuggles a train,
   publish, share, spend, or execute. Slice 1 evaluates neighbor
   stances (steps 1–3) and joins them most-restrictively; neighbor
   wiring per subsystem lands in Slice 6.

The check is lookups only: registry + stance store + pause record.
No model calls, no scope-ledger access, no subsystem calls. No call
site is required to call the check yet (Slice 1 bound) — wiring
lands per capability in later slices.

Outcomes: "proceed" (act within scope), "ask" (surface for a
decision; act only on yes/correction), "confirm" (per-transaction
confirmation with justification, step 4), "deny" (do not act).
"proceed" with ``instance_only=True`` is the I.1 rule-1 case only:
honored for that instance, never a standing authorization.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .registry import (
    ASK_ME,
    DONT_DO_IT,
    JUST_DO_IT,
    NEVER_COVERABLE_CLASSES,
    STANCES,
    get_capability,
    is_registered,
    is_valid_row,
)
from .store import get_pause, get_stance

#: Restrictiveness for joining outcomes: deny > confirm > ask > proceed.
_OUTCOME_RANK = {"deny": 4, "confirm": 3, "ask": 2, "proceed": 1}


@dataclass(frozen=True)
class AuthorizationContract:
    """An explicit authorization contract, step-4 shape (C1.4).

    States, in the same plain words the user saw, the limits a
    consequential instance must stay within. Slice 1 checks the
    instance's stated consequential attributes against these limits;
    Slice 6 adds execution-time re-checks and atomic cap accounting.

    A contract with NO bounds at all covers nothing (fail closed):
    an unbounded "contract" is a wish, not a contract (C1.4).
    """

    capability: str
    recipients: tuple[str, ...] | None = None
    audience: str | None = None
    amount_cap: float | None = None
    period: str | None = None
    schedule: str | None = None
    policy: str | None = None

    def has_bounds(self) -> bool:
        return any(
            value is not None
            for value in (
                self.recipients,
                self.audience,
                self.amount_cap,
                self.period,
                self.schedule,
                self.policy,
            )
        )

    def covers(self, instance: Mapping[str, Any] | None) -> bool:
        """True iff every consequential attribute the instance states
        is within this contract's limits.

        An instance attribute the contract does not bound is NOT
        covered (a new recipient, a new audience, an amount over the
        cap, an off-schedule send). Unknown instance attributes are
        ignored only when they are not consequential attributes;
        every consequential attribute present is checked.
        """
        if not self.has_bounds():
            return False
        instance = instance or {}
        recipients = instance.get("recipients")
        if recipients is not None:
            if self.recipients is None:
                return False
            if not set(recipients) <= set(self.recipients):
                return False
        audience = instance.get("audience")
        if audience is not None:
            if self.audience is None and self.recipients is None:
                return False
            allowed = (
                {self.audience} if self.audience is not None
                else set(self.recipients or ())
            )
            if audience not in allowed:
                return False
        amount = instance.get("amount")
        if amount is not None:
            if self.amount_cap is None:
                return False
            try:
                if float(amount) > float(self.amount_cap):
                    return False
            except (TypeError, ValueError):
                return False
        schedule = instance.get("schedule")
        if schedule is not None and self.schedule != schedule:
            return False
        policy = instance.get("policy")
        if policy is not None and self.policy != policy:
            return False
        return True


@dataclass(frozen=True)
class FrameworkDecision:
    """One framework-check outcome. ``outcome`` is the verdict;
    ``reason`` is the step that produced it; ``details`` carries the
    evidence (effective stance, per-row stances, boundary results).
    """

    outcome: str  # "proceed" | "ask" | "confirm" | "deny"
    capability: str
    stance: str | None
    reason: str
    instance_only: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        """True for proceed (including instance-only proceed)."""
        return self.outcome == "proceed"


def most_restrictive_join(stances: Sequence[str]) -> str:
    """Most-restrictive join across scope rows of ONE capability.

    Order: Don't do it > Ask me > Just do it. A permissive row never
    overrides a restrictive row (Rev2 §2.1). Unknown stance strings
    join as Don't do it (fail closed: an unrecognized stored value
    must not liberalize the outcome). Empty input joins to
    Don't do it (no rows consulted = no authorization shown).
    """
    rank = {DONT_DO_IT: 3, ASK_ME: 2, JUST_DO_IT: 1}
    best = DONT_DO_IT
    best_rank = 0
    for stance in stances:
        r = rank.get(stance, 3)
        if r > best_rank:
            best_rank = r
            best = stance if stance in rank else DONT_DO_IT
    return best


def effective_stance(
    user_id: str,
    capability: str,
    scope_rows: Sequence[str] | None,
    *,
    connection: sqlite3.Connection | None = None,
) -> tuple[str, dict[str, str]]:
    """Effective stance + per-row stances for an instance's rows.

    Rows with no user-set stance record fall back to the
    capability's registry default (Rev2 §2.1: a capability with no
    user-set stance behaves as its default). Rows that are not rows
    of the capability resolve to Don't do it for that row (fail
    closed) and are flagged in the returned mapping's caller-side
    details by ``framework_check``.

    ``scope_rows=None`` means the capability's single row for
    single-row capabilities; for multi-row capabilities the caller
    must name rows — ``framework_check`` turns an unnamed multi-row
    call into a denial rather than guessing.
    """
    entry = get_capability(capability)
    if entry is None:
        raise ValueError(f"unregistered capability: {capability!r}")
    if scope_rows is None:
        if entry.row_scheme == "per_commitment":
            raise ValueError(
                f"capability {capability} requires explicit scope rows"
            )
        if len(entry.rows) != 1:
            raise ValueError(
                f"capability {capability} requires explicit scope rows"
            )
        scope_rows = ["all"]
    per_row: dict[str, str] = {}
    for row_key in scope_rows:
        if not is_valid_row(capability, row_key):
            per_row[row_key] = DONT_DO_IT
            continue
        record = get_stance(user_id, capability, row_key, connection=connection)
        if record is None:
            per_row[row_key] = entry.default_stance
        else:
            stance = record.get("stance")
            per_row[row_key] = stance if stance in STANCES else DONT_DO_IT
    return most_restrictive_join(list(per_row.values())), per_row


def _stance_outcome(stance: str) -> str:
    if stance == DONT_DO_IT:
        return "deny"
    if stance == ASK_ME:
        return "ask"
    return "proceed"


def _join_outcomes(outcomes: Sequence[str]) -> str:
    best = "proceed"
    for outcome in outcomes:
        if _OUTCOME_RANK.get(outcome, 4) > _OUTCOME_RANK[best]:
            best = outcome
    return best


def framework_check(
    user_id: str,
    capability_id: str,
    *,
    scope_rows: Sequence[str] | None = None,
    connection: sqlite3.Connection | None = None,
    is_existing_instance: bool = False,
    consequential_class: str | None = None,
    contract: AuthorizationContract | None = None,
    instance: Mapping[str, Any] | None = None,
    neighbor_checks: Sequence[tuple[str, Sequence[str] | None]] | None = None,
) -> FrameworkDecision:
    """Run the five-step framework check for a NEW covered operation.

    ``neighbor_checks`` is a list of (capability_id, scope_rows) the
    act would cross into; each neighbor's own stance (steps 1–3) is
    evaluated and joined most-restrictively with the self outcome.
    """
    # Step 1: registered? (R8 fail-closed; R7 is unregistered.)
    entry = get_capability(capability_id)
    if entry is None:
        return FrameworkDecision(
            outcome="deny",
            capability=capability_id,
            stance=None,
            reason="unregistered_capability",
            details={"note": "S7: an unregistered capability produces nothing"},
        )

    # Step 2: pause override, checked BEFORE stance (C4.3).
    pause = get_pause(user_id, connection=connection)
    if pause.get("paused"):
        if is_existing_instance:
            # I.1 rule 1: an already-surfaced ask may be answered
            # while paused, and its answer is honored FOR THAT
            # INSTANCE ONLY. This never writes a stance change and
            # never authorizes a new operation.
            return FrameworkDecision(
                outcome="proceed",
                capability=capability_id,
                stance=None,
                reason="existing_instance_under_pause",
                instance_only=True,
                details={"paused": True},
            )
        return FrameworkDecision(
            outcome="deny",
            capability=capability_id,
            stance=None,
            reason="paused",
            details={"paused": True},
        )

    # Step 3: effective stance (most-restrictive join).
    try:
        stance, per_row = effective_stance(
            user_id, capability_id, scope_rows, connection=connection
        )
    except ValueError:
        return FrameworkDecision(
            outcome="deny",
            capability=capability_id,
            stance=None,
            reason="unspecified_scope_rows",
            details={"note": "multi-row capability requires explicit scope rows"},
        )
    self_outcome = _stance_outcome(stance)
    if self_outcome == "deny":
        return FrameworkDecision(
            outcome="deny",
            capability=capability_id,
            stance=stance,
            reason="stance_dont_do_it",
            details={"per_row": per_row},
        )
    if self_outcome == "ask":
        # The ask IS the per-instance decision surface; a
        # consequential instance in Ask me still asks (it does not
        # get a second, separate confirmation layer in Slice 1).
        return FrameworkDecision(
            outcome="ask",
            capability=capability_id,
            stance=stance,
            reason="stance_ask_me",
            details={"per_row": per_row, "consequential_class": consequential_class},
        )

    # Step 4 (C1.8): consequential class + contract coverage.
    # Reached only under Just do it: Ask me already asks, Don't do
    # it already denies, and neither is overridden by a contract.
    if consequential_class is not None:
        if consequential_class in NEVER_COVERABLE_CLASSES:
            return FrameworkDecision(
                outcome="confirm",
                capability=capability_id,
                stance=stance,
                reason="consequential_never_coverable",
                details={
                    "per_row": per_row,
                    "consequential_class": consequential_class,
                },
            )
        if contract is None or not contract.covers(instance):
            return FrameworkDecision(
                outcome="confirm",
                capability=capability_id,
                stance=stance,
                reason="consequential_not_covered",
                details={
                    "per_row": per_row,
                    "consequential_class": consequential_class,
                },
            )
        step4_outcome = "proceed"
        step4_reason = "contract_covered"
    else:
        step4_outcome = "proceed"
        step4_reason = "stance_just_do_it"

    # Step 5: boundary neighbors require their own authorization.
    neighbor_outcomes: list[str] = []
    neighbor_details: dict[str, Any] = {}
    for neighbor_id, neighbor_rows in neighbor_checks or ():
        if not is_registered(neighbor_id):
            neighbor_outcomes.append("deny")
            neighbor_details[neighbor_id] = "unregistered_capability"
            continue
        neighbor_pause = get_pause(user_id, connection=connection)
        if neighbor_pause.get("paused"):
            neighbor_outcomes.append("deny")
            neighbor_details[neighbor_id] = "paused"
            continue
        try:
            neighbor_stance, neighbor_per_row = effective_stance(
                user_id, neighbor_id, neighbor_rows, connection=connection
            )
        except ValueError:
            neighbor_outcomes.append("deny")
            neighbor_details[neighbor_id] = "unspecified_scope_rows"
            continue
        neighbor_outcomes.append(_stance_outcome(neighbor_stance))
        neighbor_details[neighbor_id] = {
            "stance": neighbor_stance,
            "per_row": neighbor_per_row,
        }
    joined = _join_outcomes([step4_outcome, *neighbor_outcomes])
    if joined == "deny":
        denied = [
            nid
            for nid, outcome in zip(
                [n[0] for n in (neighbor_checks or ())], neighbor_outcomes
            )
            if outcome == "deny"
        ]
        return FrameworkDecision(
            outcome="deny",
            capability=capability_id,
            stance=stance,
            reason="boundary_neighbor_denied",
            details={
                "per_row": per_row,
                "step4": step4_reason,
                "denied_neighbors": denied,
                "neighbors": neighbor_details,
            },
        )
    if joined == "ask":
        return FrameworkDecision(
            outcome="ask",
            capability=capability_id,
            stance=stance,
            reason="boundary_neighbor_ask_me",
            details={
                "per_row": per_row,
                "step4": step4_reason,
                "neighbors": neighbor_details,
            },
        )
    return FrameworkDecision(
        outcome="proceed",
        capability=capability_id,
        stance=stance,
        reason=step4_reason,
        details={"per_row": per_row, "neighbors": neighbor_details},
    )
