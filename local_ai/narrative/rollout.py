"""Consent rollout criteria: defined, flag-gated, thresholds UNSET (Phase 7).

Base plan §6.3: the steward runs only for flag holders today,
and rollout moves a flag default only when proposal-precision
and verdict-coverage criteria are met — with the criteria
VALUES set in the walkthrough. The walkthrough set no values.
This module therefore defines the MECHANISM and refuses to
invent the numbers:

- :data:`ROLLOUT_THRESHOLDS` is ``None``: unset, by decision
  record, not by omission. There is no setter in this module
  and no default threshold hiding in a constant. Setting
  thresholds requires a walkthrough decision plus a code
  change that names it — deliberately, so no number ever
  appears "as if decided."
- :func:`rollout_status` reports the live inputs (proposal
  precision from Phase 1, verdict coverage over review
  items) alongside the unset thresholds.
- :func:`default_change_permitted` is the gate, and it
  returns ``False`` while thresholds are unset, whatever
  the precision and coverage values are. No caller may
  flip a default through this module today.

What verdict coverage means here: decided review items
(accepted + rejected verdicts in the log) over all review
items ever proposed for the user (pending + decided, where
decided is counted from the verdict log's distinct items).
Unresolved verdicts count as neither decided nor pending
— they are explicit not-deciding, recorded but excluded,
exactly as precision excludes them. Coverage is None when
no review item has ever existed for the user.

No flag default is read, written, or flipped here: the
consent module owns flags, and both steward flags stay
default-off. This module only ever answers "is a default
change permitted?" — and today, the answer is always no.
"""

from __future__ import annotations

from .review import pending_review_items
from .store import NarrativeStore

#: Rollout thresholds: UNSET. The walkthrough decision that
#: would set them (base plan §6.3) has not happened. This is
#: the one remaining walkthrough decision recorded by Phase 7
#: (see the PR body). Do not replace None with numbers
#: without that decision.
ROLLOUT_THRESHOLDS: dict | None = None


def rollout_status(store: NarrativeStore, user_id: str) -> dict:
    """Live rollout inputs + the unset thresholds + the gate.

    Precision comes from the Phase 1 metric (verdict log
    only; it cannot reward convergence). Coverage is
    decided-items / all-items-ever for this user. The gate
    is False while thresholds are unset, unconditionally.
    """
    precision = store.proposal_precision(user_id)
    decided_items = {
        (row.item_kind, row.item_id)
        for row in store.verdicts_for(user_id)
        if row.verdict in ("accepted", "rejected")
    }
    pending = pending_review_items(store, user_id)
    pending_items = {(item.item_kind, item.item_id) for item in pending}
    all_items = decided_items | pending_items
    coverage = (
        (len(decided_items) / len(all_items)) if all_items else None
    )
    return {
        "precision": precision["overall"],
        "verdict_coverage": {
            "decided": len(decided_items),
            "total": len(all_items),
            "coverage": coverage,
        },
        "thresholds": ROLLOUT_THRESHOLDS,
        "default_change_allowed": default_change_permitted(
            precision=precision["overall"]["precision"],
            coverage=coverage,
        ),
        "reason": (
            "thresholds_unset: no default change is permitted "
            "until the walkthrough sets precision and coverage "
            "thresholds"
            if ROLLOUT_THRESHOLDS is None
            else "thresholds set: compare precision and coverage"
        ),
    }


def default_change_permitted(
    *,
    precision: float | None = None,
    coverage: float | None = None,
) -> bool:
    """Whether any flag default may move (the gate).

    False while thresholds are unset — always, regardless
    of the precision and coverage passed in. Once a
    walkthrough decision sets thresholds (as a dict with
    ``precision`` and ``coverage`` keys — the mechanism's
    schema, not values), the gate compares the live inputs
    against them, requiring both to be measured (None never
    passes). Callers must treat False as "no default
    change," not as "try again later."
    """
    if ROLLOUT_THRESHOLDS is None:
        return False
    if precision is None or coverage is None:
        return False
    return (
        precision >= ROLLOUT_THRESHOLDS["precision"]
        and coverage >= ROLLOUT_THRESHOLDS["coverage"]
    )
