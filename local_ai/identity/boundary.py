"""Joint Erasure Gate B Increment 1: the caller-owned transaction
boundary (four-gap §1; Gate B proposal Part 1 §1; closure
correction §1).

The contract, in one place:

- **Owner.** The erasure flow owns the boundary, per store, through
  a :class:`StoreBoundary` context on that store's own connection.
  It opens the transaction and commits or rolls back only at its
  own exit. Store methods never own the boundary.
- **Open.** The owner first asserts the connection is
  transaction-free (a checkable invariant of the landed code:
  every public write method commits before returning), then issues
  ``BEGIN IMMEDIATE`` — the storage engine's own per-file write
  transaction, so the gate check, the destructive step, and the
  recount run against the state the lock holds still, whether or
  not other writers cooperate (closure correction §1). The gate
  check, when supplied, is evaluated INSIDE the transaction.
- **Participation.** While a boundary stands on a store, every
  commit/rollback call site in that store resolves through the
  store's :class:`BoundaryState` helper: under a standing boundary
  the helper **suppresses** the call (the invoked method
  participates in the owner's transaction). A suppressed
  **rollback** sets the boundary's rollback-only mark — in the
  audited stores rollback is called from failure paths only, so a
  method that fails mid-write, catches its exception, calls
  rollback, and returns normally has announced its failure through
  exactly the call the helper suppresses; the mark makes that
  announcement impossible to lose (proposal Part 1 §1). A
  suppressed **commit** never marks: it is the normal success
  path.
- **Exit.** Marked, or any exception propagating out of the step →
  ``ROLLBACK``; the store is byte-identical to its pre-boundary
  state, and the refusal is handed to the ``on_refusal`` callback
  AFTER the rollback completes, never inside the boundary that
  failed (four-gap §1(d)). Unmarked → ``COMMIT``; what happens
  after commit is verification's business, never a rollback
  pretext (four-gap §1(e)).
- **Backstop.** A commit that nevertheless reaches SQLite
  mid-boundary is a build defect, not a runtime case (four-gap
  §1(c)): the owner asserts the connection remains in the boundary
  transaction at exit (and via :meth:`StoreBoundary.assert_intact`
  between invoked methods); a broken assertion aborts the step and
  is raised as a severity defect (:class:`BoundaryRefused` with
  ``defect=True``), never papered over as an ordinary refusal.

No cross-store atomicity is claimed anywhere: the flow takes the
stores in its fixed step order, one boundary at a time.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any, Callable


class BoundaryRefused(Exception):
    """The boundary refused the step.

    The store was rolled back to its pre-boundary state (except in
    the ``defect`` case, where an unrouted commit escaped and the
    transaction no longer exists to roll back — that is precisely
    why it is a severity defect and not an ordinary refusal).
    """

    def __init__(self, reason: str, *, defect: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.defect = defect


class BoundaryState:
    """The participation state one store holds (four-gap §1(c)).

    Every commit/rollback site in a participating store routes
    through :meth:`commit` / :meth:`rollback` here. With no
    boundary standing, both pass through to the connection, so
    non-flow behavior is untouched. While a boundary stands, a
    commit is suppressed; a rollback is suppressed AND marks the
    boundary rollback-only.
    """

    def __init__(self, store_name: str = "") -> None:
        self.store_name = store_name
        self.boundary: StoreBoundary | None = None
        self.rollback_only = False
        self.refusal_reason: str | None = None

    # -- routing (the single choke point per store) ----------------

    def commit(self, conn: sqlite3.Connection) -> None:
        if self.boundary is not None:
            self.boundary.note_suppressed_commit()
            return
        conn.commit()

    def rollback(self, conn: sqlite3.Connection) -> None:
        if self.boundary is not None:
            self.boundary.mark_rollback_only(
                "a participating method called rollback inside the "
                "boundary (rollback is a failure signal under a "
                "standing boundary)"
            )
            return
        conn.rollback()

    # -- owner-side helpers -----------------------------------------

    def mark_rollback_only(self, reason: str) -> None:
        if self.boundary is not None:
            self.boundary.mark_rollback_only(reason)


class StoreBoundary:
    """One caller-owned ``BEGIN IMMEDIATE`` boundary on one store.

    ``gate`` (optional) is evaluated inside the transaction at
    open; a falsy return (or an exception) refuses the step before
    any destructive statement runs. ``on_refusal`` (optional) is
    invoked with the refusal reason after any rollback completes.
    """

    def __init__(
        self,
        state: BoundaryState,
        conn: sqlite3.Connection,
        *,
        gate: Callable[[], bool] | None = None,
        on_refusal: Callable[[str], None] | None = None,
    ) -> None:
        self._state = state
        self._conn = conn
        self._gate = gate
        self._on_refusal = on_refusal
        self.suppressed_commits = 0

    # -- participation signals ---------------------------------------

    def note_suppressed_commit(self) -> None:
        self.suppressed_commits += 1

    def mark_rollback_only(self, reason: str) -> None:
        if not self._state.rollback_only:
            self._state.rollback_only = True
            self._state.refusal_reason = reason

    # -- backstop ------------------------------------------------------

    def assert_intact(self) -> None:
        """Four-gap §1(c): the connection must still be inside the
        boundary transaction. A broken assertion is a severity
        defect — an unrouted commit reached SQLite mid-boundary."""
        if self._state.boundary is not self:
            raise BoundaryRefused(
                "boundary no longer standing during its own step",
                defect=True,
            )
        if not self._conn.in_transaction:
            raise BoundaryRefused(
                "connection left the boundary transaction mid-step: "
                "an unrouted commit reached SQLite (severity defect)",
                defect=True,
            )

    # -- context manager ----------------------------------------------

    def __enter__(self) -> StoreBoundary:
        if self._state.boundary is not None:
            raise BoundaryRefused(
                "a boundary already stands on this store; boundaries "
                "do not nest",
                defect=True,
            )
        if self._conn.in_transaction:
            raise BoundaryRefused(
                "connection is not transaction-free at boundary "
                "open (four-gap §1(b) invariant broken)",
                defect=True,
            )
        self._conn.execute("BEGIN IMMEDIATE")
        self._state.boundary = self
        self._state.rollback_only = False
        self._state.refusal_reason = None
        if self._gate is not None:
            try:
                passed = bool(self._gate())
            except Exception as exc:  # noqa: BLE001 — gate failure refuses
                reason = f"gate check raised inside the boundary: {exc}"
                self._rollback_and_clear()
                self._notify_refusal(reason)
                raise BoundaryRefused(reason) from exc
            if not passed:
                reason = (
                    "gate check failed inside the boundary: the "
                    "store's fingerprint portion does not match the "
                    "bound classification"
                )
                self._rollback_and_clear()
                self._notify_refusal(reason)
                raise BoundaryRefused(reason)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            if exc_type is not None:
                reason = (
                    self._state.refusal_reason
                    or f"step raised inside the boundary: {exc}"
                )
                self._rollback_and_clear()
                self._notify_refusal(reason)
                return False  # the step's exception propagates
            if not self._conn.in_transaction:
                # Backstop: an unrouted commit escaped. The
                # transaction is gone; there is nothing to roll
                # back, and claiming otherwise would be the lie
                # this contract exists to prevent.
                self._clear()
                reason = (
                    "connection left the boundary transaction "
                    "before boundary exit: an unrouted commit "
                    "reached SQLite (severity defect)"
                )
                self._notify_refusal(reason)
                raise BoundaryRefused(reason, defect=True)
            if self._state.rollback_only:
                reason = self._state.refusal_reason or (
                    "boundary marked rollback-only"
                )
                self._rollback_and_clear()
                self._notify_refusal(reason)
                raise BoundaryRefused(reason)
            self._conn.commit()
            self._clear()
            return False
        finally:
            if self._state.boundary is self:
                self._state.boundary = None

    # -- internals ------------------------------------------------------

    def _rollback_and_clear(self) -> None:
        try:
            if self._conn.in_transaction:
                self._conn.rollback()
        finally:
            self._clear()

    def _clear(self) -> None:
        if self._state.boundary is self:
            self._state.boundary = None
        self._state.rollback_only = False
        self._state.refusal_reason = None

    def _notify_refusal(self, reason: str) -> None:
        if self._on_refusal is not None:
            self._on_refusal(reason)


# ---------------------------------------------------------------------------
# Connection → state registry
#
# Module-level helpers (the narrative store's ``_atomic``) hold a
# connection, not a store; the registry lets them resolve the
# participating store's state for that connection. A state with no
# boundary standing passes every call through, so registration is
# behavior-free outside a boundary. Stores unregister on close.
# ---------------------------------------------------------------------------

_REGISTRY: dict[int, BoundaryState] = {}
_REGISTRY_LOCK = threading.Lock()


def register_boundary_state(
    conn: sqlite3.Connection, state: BoundaryState
) -> None:
    with _REGISTRY_LOCK:
        _REGISTRY[id(conn)] = state


def unregister_boundary_state(conn: sqlite3.Connection) -> None:
    with _REGISTRY_LOCK:
        _REGISTRY.pop(id(conn), None)


def boundary_state_for(conn: sqlite3.Connection) -> BoundaryState | None:
    with _REGISTRY_LOCK:
        return _REGISTRY.get(id(conn))
