"""Joint Erasure Gate B Increment 1 — conformance suite
(footprint §4, 2026-11-15).

Isolated fixture stores throughout, deterministic, no production
paths, no model calls. Each test instantiates its settled ID:

- T-X42 — caller-owned boundary conformance over the flow-invoked
  store methods (commit counting, second-connection invisibility,
  gate evaluated inside the transaction).
- T-X43 — fault after a step's first destructive statement:
  rollback, byte-identical store, refusal recorded after rollback.
- T-X44 — external write between a store's commit and its
  verification recount: post-boundary arrival, mop-up, no rollback.
- T-X48 — rollback-only semantics (caught-exception fixture +
  propagated-exception control) and the §3.4 site inventory.
- Lifecycle — T-X21 / T-X22 / T-X23 / T-X23b crash seams, the
  T-X01 Increment-1 instance (classification immutability), and
  fingerprint-mismatch refusal with zero destructive writes
  (amended T-X30 / T-X31 shape).
- Coverage — T-X07 / T-X08, carrier byte-equality, labelled
  legacy replay (FPC §7).
- Manifest readers — T-X16 (two-generation instance) and the
  cross-version fixture T-X16b (founder's correction): the legacy
  reader below reproduces the landed 31456f6 reader rule
  textually, from that base's eligibility.py.
- T-X49 (refined, footprint §2.4) — fixture-only cross-store
  recovery evidence incl. negatives (a)–(c). The DCV reserve
  variant is specified but NOT built; nothing here claims real
  provenance/pipeline recovery.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from local_ai.fellowship.observations import ObservationStore
from local_ai.identity import erasure as erasure_mod
from local_ai.identity import service as identity_service
from local_ai.identity.boundary import (
    StoreBoundary,
    register_boundary_state,
    unregister_boundary_state,
)
from local_ai.identity.erasure import (
    COVERAGE_STATEMENT,
    LEGACY_REPLAY_LABEL,
    ErasureRefused,
    _save_operation_row,
    abandon_operation,
    run_erasure_flow,
)
from local_ai.identity.service import grant_scope
from local_ai.identity.signing import sign_mapping
from local_ai.identity.store import IdentityStore
from local_ai.narrative import eligibility as eligibility_mod
from local_ai.narrative.eligibility import (
    read_operation_records,
    render_bound_coverage,
)
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.store import NarrativeStore
from local_ai.presence_ingest.store import PresenceStore

USER = "fx-owner"
USER_B = "fx-other"
T_OLD = "2026-11-15T00:00:00+00:00"
PRE = "2026-11-14T00:00:00+00:00"
SCOPE_S_STORES = erasure_mod.SCOPE_S_STORES


# ---------------------------------------------------------------------
# Fixture environment (the D2 Env pattern: hermetic stores on tmp
# files, the wired delete path, owner resolution pinned).
# ---------------------------------------------------------------------


class Env:
    def __init__(self, tmp_path, *, grant: bool = True):
        self.dir = Path(tmp_path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.istore = IdentityStore(db_path=self.dir / "identity.db")
        identity_service.issue_license(owner_id=USER, store=self.istore)
        if grant:
            grant_scope("delete:execute", store=self.istore)
        self.license_id = self.istore.get_license().license_id
        self.nstore = NarrativeStore(db_path=self.dir / "narrative.db")
        self.ostore = ObservationStore(db_path=self.dir / "observations.db")
        self.pdb = self.dir / "signals.db"
        self.pstore = PresenceStore(db_path=self.pdb)
        self.uploads = self.dir / "uploads"
        self.uploads.mkdir()
        self.log = self.dir / "activity.log"
        self.log.write_text("", encoding="utf-8")

    def _kwargs(self, overrides):
        kwargs = dict(
            store=self.istore,
            requesting_user_id=USER,
            narrative_store=self.nstore,
            observation_store=self.ostore,
            presence_store=self.pstore,
            presence_upload_root=self.uploads,
            presence_db_path=self.pdb,
            log_path=self.log,
            owner_resolver=lambda: USER,
        )
        kwargs.update(overrides)
        return kwargs

    def delete(self, **overrides):
        """The wired path (service.delete_all), as the route calls it."""
        return identity_service.delete_all(
            "DELETE", **self._kwargs(overrides)
        )

    def flow(self, **overrides):
        """The erasure flow directly — staging runs that must see
        the flow's own exceptions propagate unconverted."""
        kwargs = self._kwargs(overrides)
        kwargs.pop("store")
        return run_erasure_flow(identity_store=self.istore, **kwargs)

    def reader(self):
        return read_operation_records(self.istore, USER)

    def add_observation(self, event_ref="ev-old", user=USER):
        return self.ostore.add(
            user_id=user,
            seat="conductor",
            event_ref=event_ref,
            event_kind="conversation_turn",
            evidence="verbatim words",
            evidence_kind="quote",
            interpretation="A reading.",
        )


@pytest.fixture()
def env(tmp_path):
    return Env(tmp_path)


def _seed_material(env):
    """One thread with a steward reading + one observation: the
    classified material the flow must account for."""
    thread = env.nstore.create_thread(
        USER,
        title="seed thread",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-seed")],
    )
    env.nstore.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={"tensions": ["roots vs. road"]},
        evidence_refs=[SourceRef(kind="event", ref_id="ev-seed")],
    )
    env.add_observation(event_ref="ev-seed")
    return thread


# ---------------------------------------------------------------------
# Small exact-state helpers.
# ---------------------------------------------------------------------


def _op_rows(istore, operation_id=None):
    """The operation rows of an identity store, in append order,
    as raw (receipt_id, summary, summary_json, signature) dicts."""
    rows = istore._conn.execute(
        "SELECT receipt_id, summary_json, signature "
        "FROM deletion_receipts ORDER BY rowid"
    ).fetchall()
    out = []
    for row in rows:
        summary = json.loads(row["summary_json"])
        if "operation_id" not in summary:
            continue
        if operation_id and summary["operation_id"] != operation_id:
            continue
        out.append(
            {
                "receipt_id": row["receipt_id"],
                "summary": summary,
                "summary_json": row["summary_json"],
                "signature": row["signature"],
            }
        )
    return out


def _op_row_bytes(istore, operation_id=None):
    return [
        (r["receipt_id"], r["summary_json"], r["signature"])
        for r in _op_rows(istore, operation_id)
    ]


def _table_dump(db_path, exclude=()):
    """Logical dump of a store file (every table's rows, sorted),
    for byte-identity assertions across a rolled-back step. The
    erasure tombstone table is excludable: the flow's barrier
    pre-step writes it OUTSIDE the step boundary, by design."""
    conn = sqlite3.connect(str(db_path))
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        dump = {}
        for table in tables:
            if table in exclude:
                continue
            rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
            dump[table] = sorted(repr(row) for row in rows)
        return dump
    finally:
        conn.close()


def _sql(store, statement, params=()):
    with store._lock:
        store._conn.execute(statement, params)
        store._conn.commit()


# ---------------------------------------------------------------------
# T-X16b fixture: the LEGACY reader — the landed 31456f6 rule,
# reproduced textually from that base's
# local_ai/narrative/eligibility.py::read_operation_records:
# signature verification → different-user skip → erased_at
# required → scope must equal the one token that generation binds
# ("delete:execute") → cross-row erased_at agreement. Standing is
# the latest opened/incomplete operation; completed likewise.
# That generation binds no other token, no scope_version, and no
# store set — its OperationRecord has no such fields.
# ---------------------------------------------------------------------


def legacy_read_operation_records(identity_store, user_id):
    from local_ai.identity.service import _receipt_payload
    from local_ai.identity.signing import verify_mapping

    out = {"standing": None, "completed": None, "conflict": None}
    by_operation = {}
    order = []
    for row in identity_store.list_receipts():  # rowid DESC
        summary = row.summary if isinstance(row.summary, dict) else {}
        operation_id = summary.get("operation_id")
        status = summary.get("op_status")
        if not operation_id or not status:
            continue  # a plain receipt, not an operation row
        if not verify_mapping(_receipt_payload(row), row.signature):
            out["conflict"] = (
                f"operation record {row.receipt_id} for operation "
                f"{operation_id} failed signature verification"
            )
            return out
        if summary.get("covered_user") != user_id:
            continue  # another user's record: skipped, as landed
        erased_at = summary.get("erased_at")
        scope = summary.get("scope")
        if not isinstance(erased_at, str) or not erased_at.strip():
            out["conflict"] = (
                f"operation record {row.receipt_id} carries no "
                "erased_at in its signed binding"
            )
            return out
        if scope != "delete:execute":
            out["conflict"] = (
                f"operation record {row.receipt_id} binds scope "
                f"{scope!r}, not the authorized 'delete:execute'"
            )
            return out
        if operation_id not in by_operation:
            by_operation[operation_id] = {
                "operation_id": str(operation_id),
                "status": str(status),
                "erased_at": erased_at,
                "scope": str(scope),
            }
            order.append(operation_id)
        elif by_operation[operation_id]["erased_at"] != erased_at:
            out["conflict"] = (
                f"operation {operation_id} rows disagree on the "
                "boundary they bind"
            )
            return out
    for operation_id in order:
        record = by_operation[operation_id]
        if record["status"] in ("opened", "incomplete"):
            if out["standing"] is None:
                out["standing"] = record
        elif record["status"] == "completed":
            if out["completed"] is None:
                out["completed"] = record
    return out


# ---------------------------------------------------------------------
# T-X42 helpers: a commit-counting connection, swapped into a
# store in place of its own (identical connect parameters:
# check_same_thread=False + Row factory, as all three stores use).
# ---------------------------------------------------------------------


class CountingConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.real_commits = 0
        self.real_rollbacks = 0

    def commit(self):
        self.real_commits += 1
        super().commit()

    def rollback(self):
        self.real_rollbacks += 1
        super().rollback()


def _swap_counting_conn(store, db_path):
    old = store._conn
    unregister_boundary_state(old)
    old.close()
    conn = sqlite3.connect(
        str(db_path), factory=CountingConnection, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    store._conn = conn
    register_boundary_state(conn, store.boundary_state)
    return conn


def _second_conn(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------
# Lifecycle staging: deterministic crashes at the protocol seams.
# ---------------------------------------------------------------------


def _stage_opened_unclassified(env, monkeypatch):
    """Crash after the opening row, before classification
    persistence (the T-X21 shape): the work-row write raises."""

    def boom(self, operation_id, payload, signature):
        raise RuntimeError("crash before classification persistence")

    with monkeypatch.context() as m:
        m.setattr(IdentityStore, "save_operation_work", boom)
        with pytest.raises(RuntimeError):
            env.flow()
    standing = env.reader().standing
    assert standing is not None
    assert standing.statuses == ["opened"]
    return standing


def _stage_classified(env, monkeypatch):
    """Crash after classification persisted and bound, before the
    executing row (the classified standing shape)."""
    real = erasure_mod._save_operation_row

    def wrapper(store, **kwargs):
        if kwargs.get("status") == "executing":
            raise RuntimeError("crash before the executing row")
        return real(store, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(erasure_mod, "_save_operation_row", wrapper)
        with pytest.raises(RuntimeError):
            env.flow()
    standing = env.reader().standing
    assert standing is not None
    assert standing.statuses == ["opened", "classified"]
    return standing


# ---------------------------------------------------------------------
# T-X42 — boundary conformance over the flow-invoked methods.
# For each store: the step method runs under a StoreBoundary on a
# commit-counting connection; zero real commits reach SQLite
# before boundary exit; a second connection sees none of the
# step's writes before commit and all of them after; the gate is
# evaluated inside the transaction.
# ---------------------------------------------------------------------


def test_tx42_identity_boundary(tmp_path):
    istore = IdentityStore(db_path=tmp_path / "identity.db")
    identity_service.issue_license(owner_id=USER, store=istore)
    grant_scope("delete:execute", store=istore)
    assert len(istore.list_scope_events()) >= 1
    conn = _swap_counting_conn(istore, tmp_path / "identity.db")
    second = _second_conn(tmp_path / "identity.db")
    gate_seen = {}

    def gate():
        gate_seen["in_transaction"] = conn.in_transaction
        return True

    with StoreBoundary(istore.boundary_state, conn, gate=gate) as boundary:
        n_events = len(istore.list_scope_events())
        istore.clear_scope_events()
        istore.terminate_license()
        # Zero commits reached SQLite; the methods' own commit
        # calls were suppressed into the boundary.
        assert conn.real_commits == 0
        assert boundary.suppressed_commits >= 2
        # A second connection sees none of the step's writes.
        assert (
            second.execute("SELECT COUNT(*) FROM scope_events").fetchone()[0]
            == n_events
        )
        assert (
            second.execute(
                "SELECT status FROM license LIMIT 1"
            ).fetchone()[0]
            == "active"
        )
    assert gate_seen["in_transaction"] is True
    # Exactly one real commit: the boundary owner's, at exit.
    assert conn.real_commits == 1
    assert second.execute("SELECT COUNT(*) FROM scope_events").fetchone()[0] == 0
    assert (
        second.execute("SELECT status FROM license LIMIT 1").fetchone()[0]
        == "terminated"
    )
    second.close()


def test_tx42_narrative_boundary(tmp_path):
    nstore = NarrativeStore(db_path=tmp_path / "narrative.db")
    thread = nstore.create_thread(
        USER,
        title="t42 thread",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-42")],
    )
    conn = _swap_counting_conn(nstore, tmp_path / "narrative.db")
    second = _second_conn(tmp_path / "narrative.db")
    gate_seen = {}

    def gate():
        gate_seen["in_transaction"] = conn.in_transaction
        return True

    with StoreBoundary(nstore.boundary_state, conn, gate=gate) as boundary:
        report = nstore.erase_user_material(
            USER, erased_at=T_OLD, operation_id="op-t42", log_path=None
        )
        assert report["threads_deleted"] == 1
        assert conn.real_commits == 0
        assert boundary.suppressed_commits >= 1
        assert (
            second.execute(
                "SELECT COUNT(*) FROM narrative_threads WHERE user_id = ?",
                (USER,),
            ).fetchone()[0]
            == 1
        )
    assert gate_seen["in_transaction"] is True
    assert conn.real_commits == 1
    assert (
        second.execute(
            "SELECT COUNT(*) FROM narrative_threads WHERE user_id = ?",
            (USER,),
        ).fetchone()[0]
        == 0
    )
    assert nstore.get_thread(USER, thread.id) is None
    second.close()


def test_tx42_observations_boundary(tmp_path):
    ostore = ObservationStore(db_path=tmp_path / "observations.db")
    for ref in ("ev-42a", "ev-42b"):
        ostore.add(
            user_id=USER,
            seat="conductor",
            event_ref=ref,
            event_kind="conversation_turn",
            evidence="words",
            evidence_kind="quote",
            interpretation="A reading.",
        )
    conn = _swap_counting_conn(ostore, tmp_path / "observations.db")
    second = _second_conn(tmp_path / "observations.db")
    gate_seen = {}

    def gate():
        gate_seen["in_transaction"] = conn.in_transaction
        return True

    with StoreBoundary(ostore.boundary_state, conn, gate=gate) as boundary:
        deleted = ostore.delete_for_user(USER)
        assert deleted == 2
        assert conn.real_commits == 0
        assert boundary.suppressed_commits >= 1
        assert (
            second.execute(
                "SELECT COUNT(*) FROM observations WHERE user_id = ?",
                (USER,),
            ).fetchone()[0]
            == 2
        )
    assert gate_seen["in_transaction"] is True
    assert conn.real_commits == 1
    assert (
        second.execute(
            "SELECT COUNT(*) FROM observations WHERE user_id = ?", (USER,)
        ).fetchone()[0]
        == 0
    )
    second.close()


# ---------------------------------------------------------------------
# T-X43 — fault injected after a store step's first destructive
# statement: the step rolls back, the store is byte-identical to
# its pre-boundary state, the refusal is recorded in the identity
# store AFTER the rollback, that store's standing is refused, and
# earlier stores' standings are unchanged.
# ---------------------------------------------------------------------


def test_tx43_fault_after_first_destructive_statement(env):
    thread = _seed_material(env)
    dump_before = _table_dump(
        env.dir / "narrative.db", exclude={"steward_erasure_tombstones"}
    )
    nstore = env.nstore

    def rigged(user_id, *, erased_at=None, operation_id="", log_path=None):
        threads = nstore.threads_for(user_id, limit=None)
        assert threads
        # First destructive statement of the step: a real thread
        # deletion through the store's own routed method.
        assert nstore.delete_thread(user_id, threads[0].id)
        raise RuntimeError("fault injected mid-step")

    nstore.erase_user_material = rigged
    receipt = env.delete()

    # The step rolled back: the thread stands, and the store's
    # logical content is identical to its pre-flow state (the
    # tombstone table is excluded — the barrier pre-step writes
    # it outside the boundary, by design).
    assert env.nstore.get_thread(USER, thread.id) is not None
    assert (
        _table_dump(
            env.dir / "narrative.db", exclude={"steward_erasure_tombstones"}
        )
        == dump_before
    )
    assert env.nstore.erasure_recount(USER)["total"] > 0
    # The refusal was recorded after the rollback, naming the
    # store refused; the earlier store (presence) kept its
    # standing from before the failed step.
    refusals = [
        r
        for r in _op_rows(env.istore)
        if r["summary"].get("counts", {}).get("boundary_refusal")
        == "narrative"
    ]
    assert len(refusals) == 1
    assert refusals[0]["summary"]["stores"]["narrative"] == "refused"
    assert refusals[0]["summary"]["stores"]["presence"] == "deleted"
    # The receipt is an incomplete one; narrative never verified.
    assert receipt.summary["coverage"].startswith(
        "This erasure is INCOMPLETE"
    )
    final = env.reader().standing
    assert final is not None and final.status == "incomplete"
    assert final.stores["narrative"] == "incomplete"


# ---------------------------------------------------------------------
# T-X44 — an external write landing between a store's commit and
# its verification recount is a post-boundary arrival: the
# provenance audit routes it to mop-up, no rollback is attempted
# or claimed, and the operation completes with the arrival named
# in the audit counts.
# ---------------------------------------------------------------------


def test_tx44_post_boundary_arrival_mopped_up(env, monkeypatch):
    _seed_material(env)
    real_audit = eligibility_mod.audit_narrative_store
    planted = {}

    def planting_audit(store, user_id, resolver):
        if "removed_first_pass" not in planted:
            # The external write: a pre-boundary rogue thread,
            # planted the way history produces one (barrier
            # lifted, row written, barrier restored — the D2
            # test_14 fixture surgery).
            tomb = store.get_erasure_tombstone(user_id)
            _sql(
                store,
                "DELETE FROM steward_erasure_tombstones WHERE user_id = ?",
                (user_id,),
            )
            _sql(
                store,
                "INSERT INTO narrative_threads (id, user_id, origin, "
                "title, status, created_at, updated_at) VALUES "
                "('thr-late', ?, 'steward_proposal', 'late', "
                "'standing', ?, ?)",
                (user_id, PRE, PRE),
            )
            store.write_erasure_tombstone(
                user_id, tomb["erased_at"], tomb["operation_id"]
            )
            planted["id"] = "thr-late"
        result = real_audit(store, user_id, resolver)
        if "removed_first_pass" not in planted:
            planted["removed_first_pass"] = result["removed"]
        return result

    with monkeypatch.context() as m:
        m.setattr(
            eligibility_mod, "audit_narrative_store", planting_audit
        )
        receipt = env.delete()

    # The arrival was removed by the audit mop-up (not by any
    # rollback), and the operation completed and verified.
    assert planted["removed_first_pass"] == 1
    assert env.nstore.get_thread(USER, "thr-late") is None
    completed = env.reader().completed
    assert completed is not None
    assert completed.stores["narrative"] == "verified"
    # No boundary refusal was recorded for narrative: nothing was
    # rolled back, and nothing claims otherwise.
    assert not [
        r
        for r in _op_rows(env.istore)
        if r["summary"].get("counts", {}).get("boundary_refusal")
        == "narrative"
    ]
    assert receipt.summary["coverage"] == COVERAGE_STATEMENT


# ---------------------------------------------------------------------
# T-X48 — rollback-only semantics. A flow-invoked method rigged
# to write, throw, catch internally, call rollback (suppressed),
# and return success: the boundary still refuses the commit, the
# store is byte-identical, the refusal is recorded, the standing
# is refused. The propagated-exception variant is the control,
# with identical assertions.
# ---------------------------------------------------------------------


def _rig_observations_step(env, *, swallow: bool):
    store = env.ostore

    def rigged(user_id):
        rows = store.list_for_user(user_id)
        # A destructive write inside the boundary, committed
        # through the routed helper (suppressed, never marks).
        store._conn.execute(
            "DELETE FROM observations WHERE user_id = ?", (user_id,)
        )
        store.boundary_state.commit(store._conn)
        if swallow:
            try:
                raise RuntimeError("mid-write failure")
            except RuntimeError:
                # The failure announcement: a rollback call on a
                # failure path, suppressed — and marking the
                # boundary rollback-only.
                store.boundary_state.rollback(store._conn)
            return len(rows)  # claims success
        raise RuntimeError("mid-write failure")

    return rigged


def _assert_tx48_outcome(env, dump_before, receipt):
    assert receipt.summary["coverage"].startswith(
        "This erasure is INCOMPLETE"
    )
    # Byte-identical store (tombstone table excluded: written by
    # the barrier pre-step, outside the boundary).
    assert (
        _table_dump(
            env.dir / "observations.db",
            exclude={"steward_erasure_tombstones"},
        )
        == dump_before
    )
    assert env.ostore.count_for_user(USER) == 2
    refusals = [
        r
        for r in _op_rows(env.istore)
        if r["summary"].get("counts", {}).get("boundary_refusal")
        == "observations"
    ]
    assert len(refusals) == 1
    assert refusals[0]["summary"]["stores"]["observations"] == "refused"


def test_tx48_caught_exception_marks_rollback_only(env, monkeypatch):
    _seed_material(env)
    env.add_observation(event_ref="ev-second")
    dump_before = _table_dump(
        env.dir / "observations.db", exclude={"steward_erasure_tombstones"}
    )
    with monkeypatch.context() as m:
        m.setattr(
            env.ostore,
            "delete_for_user",
            _rig_observations_step(env, swallow=True),
        )
        receipt = env.delete()
    _assert_tx48_outcome(env, dump_before, receipt)


def test_tx48_propagated_exception_control(env, monkeypatch):
    _seed_material(env)
    env.add_observation(event_ref="ev-second")
    dump_before = _table_dump(
        env.dir / "observations.db", exclude={"steward_erasure_tombstones"}
    )
    with monkeypatch.context() as m:
        m.setattr(
            env.ostore,
            "delete_for_user",
            _rig_observations_step(env, swallow=False),
        )
        receipt = env.delete()
    _assert_tx48_outcome(env, dump_before, receipt)


# ---------------------------------------------------------------------
# T-X48 site inventory — every flow-invoked commit/rollback site
# routes through the boundary helper; every routed rollback site
# is an error path. Asserted over the three store modules by AST,
# with the deliberate non-flow-invoked exclusions named exactly.
# ---------------------------------------------------------------------

_FLOW_INVOKED = {
    "local_ai/identity/store.py": {
        "save_license",
        "terminate_license",
        "append_scope_event",
        "clear_scope_events",
        "save_receipt",
        "save_operation_work",
        "delete_operation_work",
    },
    "local_ai/narrative/store.py": {
        "erase_user_material",
        "delete_thread",
        "set_processing_position",
        "vacuum",
        "write_erasure_tombstone",
        "rewrite_erasure_tombstone",
        "set_erasure_tombstone_counts",
    },
    "local_ai/fellowship/observations.py": {
        "write_erasure_tombstone",
        "rewrite_erasure_tombstone",
        "set_erasure_tombstone_counts",
        "vacuum",
        "delete_for_user",
    },
}

# Bare _conn commit/rollback sites that remain BY DESIGN (§3.4
# routes only the flow-invoked set; these methods are never
# invoked by the erasure flow): schema setup and non-flow writers.
_BARE_BY_DESIGN = {
    "local_ai/identity/store.py": set(),
    "local_ai/narrative/store.py": None,  # asserted by exclusion below
    "local_ai/fellowship/observations.py": {
        "__init__",
        "delete_observation",
        "add",
        "set_status",
    },
}


def _module_ast(rel_path):
    path = Path(__file__).resolve().parent.parent / rel_path
    src = path.read_text(encoding="utf-8")
    return src, ast.parse(src)


def _bare_sites(tree):
    """{method_name: [attrs]} for direct self._conn.commit /
    self._conn.rollback calls — the unrouted form."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in ("commit", "rollback")
                    and isinstance(sub.func.value, ast.Attribute)
                    and sub.func.value.attr == "_conn"
                ):
                    out.setdefault(node.name, []).append(sub.func.attr)
    return out


def _routed_sites(tree):
    """{method_name: [attrs]} for boundary-routed commit/rollback
    calls (boundary_state.commit / .rollback, state.rollback)."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in ("commit", "rollback")
                ):
                    value_src = ast.dump(sub.func.value)
                    if "boundary" in value_src or (
                        isinstance(sub.func.value, ast.Name)
                        and sub.func.value.id == "state"
                    ):
                        out.setdefault(node.name, []).append(sub.func.attr)
    return out


def _atomic_delegates(tree):
    """Method names whose bodies delegate to the module's
    _atomic helper (which itself routes through the boundary
    state) — routing by delegation."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "_atomic"
                ):
                    out.add(node.name)
    return out


def test_tx48_site_inventory():
    for rel_path, invoked in _FLOW_INVOKED.items():
        src, tree = _module_ast(rel_path)
        bare = _bare_sites(tree)
        routed = _routed_sites(tree)
        delegates = _atomic_delegates(tree)
        # No flow-invoked method contains a bare site.
        for name in invoked:
            assert name not in bare, (
                f"{rel_path}:{name} carries a bare commit/rollback site"
            )
        # Every flow-invoked writer routes its commit through
        # the helper — directly, or by delegating to _atomic
        # (erase_user_material and the narrative tombstone
        # writers route through their callees).
        for name in invoked - {"erase_user_material"}:
            assert "commit" in routed.get(name, []) or (
                name in delegates
            ), f"{rel_path}:{name} does not route its commit"
        # The bare sites that remain are exactly the named,
        # non-flow-invoked exclusions (identity: none at all).
        expected = _BARE_BY_DESIGN[rel_path]
        if expected is not None:
            assert set(bare) == expected, (
                f"{rel_path}: bare sites {sorted(bare)} != "
                f"designed exclusions {sorted(expected)}"
            )
        else:
            assert not (set(bare) & invoked)
    # Every routed rollback site is an error path: the narrative
    # _atomic helper's rollback calls sit inside its except block,
    # and they are the only routed rollback calls in the stores.
    src, tree = _module_ast("local_ai/narrative/store.py")
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    def in_except(node):
        while id(node) in parents:
            node = parents[id(node)]
            if isinstance(node, ast.ExceptHandler):
                return True
        return False

    routed_rollbacks = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "rollback"
        and (
            "boundary" in ast.dump(node.func.value)
            or (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "state"
            )
        )
    ]
    assert routed_rollbacks, "expected _atomic's routed rollback sites"
    assert all(in_except(node) for node in routed_rollbacks)


# ---------------------------------------------------------------------
# Lifecycle — state derivation from the verified record chain +
# work-row presence (FPC §1), and the crash seams T-X21 / T-X22 /
# T-X23 / T-X23b.
# ---------------------------------------------------------------------


def test_tx21_crash_after_opening_before_classification(env, monkeypatch):
    _seed_material(env)
    standing = _stage_opened_unclassified(env, monkeypatch)
    # Derived state: opened-unclassified; no work row stands.
    assert standing.derive_lifecycle(False) == "opened-unclassified"
    assert not env.istore.has_operation_work(standing.operation_id)
    # The crash deleted nothing.
    assert env.nstore.erasure_recount(USER)["total"] > 0
    assert env.ostore.count_for_user(USER) == 1
    assert env.istore.get_license().status == "active"
    # Retry classifies and completes under the same operation.
    env.delete()
    completed = env.reader().completed
    assert completed is not None
    assert completed.operation_id == standing.operation_id
    assert completed.statuses == [
        "opened",
        "classified",
        "executing",
        "completed",
    ]
    assert completed.derive_lifecycle(False) == "sealed"
    assert not env.istore.has_operation_work(standing.operation_id)


def test_tx22_crash_at_persist_bind_seam(env, monkeypatch):
    _seed_material(env)
    captured = {}

    def staged_save(self, operation_id, payload, signature):
        # The staged-write form of the seam: the work row lands
        # durably WITHOUT its binding row (a direct commit that
        # escapes the persist→bind transaction), then the crash.
        conn = self._conn
        conn.execute(
            "INSERT OR REPLACE INTO erasure_operation_work "
            "(operation_id, payload_json, classification_sha256, "
            "signature, created_at, sealed_at) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            (
                operation_id,
                json.dumps(payload, sort_keys=True),
                str(payload.get("classification_sha256", "")),
                signature,
                str(payload.get("created_at", "")),
            ),
        )
        conn.commit()
        captured["sha"] = payload["classification_sha256"]
        raise RuntimeError("crash at the persist->bind seam")

    with monkeypatch.context() as m:
        m.setattr(IdentityStore, "save_operation_work", staged_save)
        with pytest.raises(RuntimeError):
            env.flow()
    standing = env.reader().standing
    assert standing is not None
    # The bind never landed: the chain still says opened, and the
    # standing work row is UNBOUND — present but ungoverned.
    assert standing.statuses == ["opened"]
    assert env.istore.has_operation_work(standing.operation_id)
    assert standing.derive_lifecycle(True) == "opened-unclassified"
    # Retry discards the unbound row and reclassifies under the
    # fingerprint rule; over unchanged state the reclassification
    # is hash-equal to the crashed capture.
    env.delete()
    completed = env.reader().completed
    assert completed is not None
    assert completed.classification_sha256 == captured["sha"]
    assert completed.statuses == [
        "opened",
        "classified",
        "executing",
        "completed",
    ]
    assert not env.istore.has_operation_work(standing.operation_id)


def test_tx23_seal_destroys_work_row_and_on_sight_cleanup(env):
    _seed_material(env)
    env.delete()
    completed = env.reader().completed
    assert completed is not None
    # The seal committed the completion row and the work row's
    # destruction in one transaction: no work row stands beside
    # a completed record.
    assert completed.derive_lifecycle(False) == "sealed"
    assert not env.istore.has_operation_work(completed.operation_id)
    # The completed row carries the full Increment-1 binding.
    row = _op_rows(env.istore, completed.operation_id)[-1]
    for key in (
        "scope_version",
        "coverage_id",
        "coverage_sha256",
        "source_fingerprint",
        "classification_sha256",
    ):
        assert key in row["summary"], key
    assert row["summary"]["scope"] == erasure_mod.OPERATION_TOKEN
    # Plant the staged-write seal seam: a work row standing
    # beside the completed record. The verified no-op replay
    # destroys it on sight and appends no operation row.
    payload = {
        "operation_id": completed.operation_id,
        "classification": {},
        "scrub_set": [],
        "classification_sha256": completed.classification_sha256,
        "created_at": "2026-11-16T00:00:00+00:00",
        "sealed_at": None,
    }
    env.istore.save_operation_work(
        completed.operation_id, payload, sign_mapping(payload)
    )
    assert env.istore.has_operation_work(completed.operation_id)
    rows_before = _op_row_bytes(env.istore)
    replay = env.delete()
    assert not env.istore.has_operation_work(completed.operation_id)
    assert _op_row_bytes(env.istore) == rows_before
    assert replay.summary["coverage"] == COVERAGE_STATEMENT
    assert "coverage_note" not in replay.summary


def test_tx23b_abandonment_from_classified(env, monkeypatch):
    _seed_material(env)
    standing = _stage_classified(env, monkeypatch)
    assert standing.derive_lifecycle(True) == "classified"
    row = abandon_operation(
        requesting_user_id=USER,
        identity_store=env.istore,
        owner_resolver=lambda: USER,
    )
    summary = row.summary
    # The abandoned row: counts zero, nothing attempted, the
    # classification hash bound, the work row destroyed in the
    # same transaction.
    assert summary["op_status"] == "abandoned"
    assert summary["counts"] == {}
    assert summary["stores"] == {
        name: "not-attempted" for name in SCOPE_S_STORES
    }
    assert summary["classification_sha256"] == (
        standing.classification_sha256
    )
    assert summary["scope"] == erasure_mod.OPERATION_TOKEN
    assert not env.istore.has_operation_work(standing.operation_id)
    recs = env.reader()
    assert recs.abandoned is not None
    assert recs.lifecycle_state(False) == "abandoned"
    assert recs.coverage_standing(False) == "abandoned-in-preparation"
    # Abandonment deleted nothing: it is a pre-execution exit.
    assert env.nstore.erasure_recount(USER)["total"] > 0
    assert env.ostore.count_for_user(USER) == 1
    assert env.istore.get_license().status == "active"


def test_tx23b_abandonment_from_opened_unclassified(env, monkeypatch):
    _seed_material(env)
    standing = _stage_opened_unclassified(env, monkeypatch)
    row = abandon_operation(
        requesting_user_id=USER,
        identity_store=env.istore,
        owner_resolver=lambda: USER,
    )
    assert row.summary["op_status"] == "abandoned"
    assert row.summary["counts"] == {}
    assert env.reader().abandoned is not None
    assert env.nstore.erasure_recount(USER)["total"] > 0


def test_tx23b_abandonment_refusals(env, monkeypatch, tmp_path):
    # From executing: refused — execution has begun; the only
    # exits are completion or the incomplete/resume path.
    _seed_material(env)

    def dead_presence(**kwargs):
        raise RuntimeError("presence step failure")

    with monkeypatch.context() as m:
        m.setattr(erasure_mod, "_wipe_presence", dead_presence)
        env.delete()
    standing = env.reader().standing
    assert standing is not None
    assert standing.derive_lifecycle(
        env.istore.has_operation_work(standing.operation_id)
    ) == "executing"
    rows_before = _op_row_bytes(env.istore)
    with pytest.raises(ErasureRefused):
        abandon_operation(
            requesting_user_id=USER,
            identity_store=env.istore,
            owner_resolver=lambda: USER,
        )
    assert _op_row_bytes(env.istore) == rows_before

    # A legacy standing operation: refused — abandonment is a
    # new-protocol act; no binding is invented for it (FPC §7).
    legacy_env = Env(tmp_path / "legacy")
    _save_operation_row(
        legacy_env.istore,
        license_id=legacy_env.license_id,
        operation_id="op-legacy-open",
        status="opened",
        covered_user=USER,
        erased_at=T_OLD,
        stores={},
        counts={},
    )
    with pytest.raises(ErasureRefused):
        abandon_operation(
            requesting_user_id=USER,
            identity_store=legacy_env.istore,
            owner_resolver=lambda: USER,
        )

    # No standing operation at all: refused.
    empty_env = Env(tmp_path / "empty")
    with pytest.raises(ErasureRefused):
        abandon_operation(
            requesting_user_id=USER,
            identity_store=empty_env.istore,
            owner_resolver=lambda: USER,
        )


def test_tx01_classification_immutable_across_resume(env, monkeypatch):
    """T-X01, Increment-1 instance: a killed-and-resumed run over
    the current store set never reclassifies — execution proceeds
    from the verified work row bound by the classified row."""
    _seed_material(env)
    standing = _stage_classified(env, monkeypatch)
    payload, verified = env.istore.load_operation_work(
        standing.operation_id
    )
    assert verified
    assert payload["classification_sha256"] == (
        standing.classification_sha256
    )
    env.delete()
    completed = env.reader().completed
    assert completed is not None
    # No second classified row was appended on resume, and the
    # sealed hash is the classified row's hash, unchanged.
    assert completed.statuses == [
        "opened",
        "classified",
        "executing",
        "completed",
    ]
    assert completed.classification_sha256 == (
        standing.classification_sha256
    )


def test_fingerprint_mismatch_at_execution_gate_refuses(env, monkeypatch):
    """Closure correction §1 + founder's Gate B condition: a
    post-classification change to a store's classified read set
    refuses at the execution gate, BEFORE the executing row and
    before any destructive step — zero destructive writes."""
    _seed_material(env)
    standing = _stage_classified(env, monkeypatch)
    # An external arrival changes the narrative read set after
    # classification bound its fingerprint.
    env.nstore.create_thread(
        USER,
        title="post-classification arrival",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-late")],
    )
    rows_before = _op_row_bytes(env.istore)
    with pytest.raises(ErasureRefused):
        env.flow()
    # Zero destructive writes, zero new operation rows: the
    # operation remains classified, its work row stands, and all
    # material — classified and arriving alike — is intact.
    assert _op_row_bytes(env.istore) == rows_before
    assert env.reader().standing.statuses == ["opened", "classified"]
    assert env.istore.has_operation_work(standing.operation_id)
    assert env.nstore.erasure_recount(USER)["total"] >= 2
    assert env.ostore.count_for_user(USER) == 1
    assert env.istore.get_license().status == "active"


def test_fingerprint_mismatch_during_capture_refuses(env, monkeypatch):
    """Amended T-X30/T-X31 shape: the bracketed fingerprint checks
    around capture — a change DURING capture discards the
    classification unbound; nothing persists, nothing is deleted,
    the operation remains opened-unclassified."""
    _seed_material(env)
    real_readset = erasure_mod._store_readset
    calls = {"narrative": 0}

    def mutating_readset(name, user, **kwargs):
        if name == "narrative":
            calls["narrative"] += 1
            if calls["narrative"] == 3:
                # Bound computation is call 1, the phase's
                # pre-capture check is call 2; call 3 is the
                # capture read itself.
                env.nstore.create_thread(
                    user,
                    title="concurrent arrival",
                    evidence_refs=[
                        SourceRef(kind="event", ref_id="ev-concurrent")
                    ],
                )
        return real_readset(name, user, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(erasure_mod, "_store_readset", mutating_readset)
        with pytest.raises(ErasureRefused):
            env.flow()
    standing = env.reader().standing
    assert standing is not None
    assert standing.statuses == ["opened"]
    assert standing.derive_lifecycle(False) == "opened-unclassified"
    assert not env.istore.has_operation_work(standing.operation_id)
    # Zero destructive writes: seed and arrival both stand.
    assert env.nstore.erasure_recount(USER)["total"] >= 2
    assert env.ostore.count_for_user(USER) == 1
    assert env.istore.get_license().status == "active"


# ---------------------------------------------------------------------
# Coverage binding (amendment §4) — T-X07 / T-X08, carrier
# byte-equality, and the labelled legacy replay (FPC §7).
# ---------------------------------------------------------------------


def test_tx07_replay_byte_for_byte_after_registry_growth(
    env, monkeypatch
):
    _seed_material(env)
    first = env.delete()
    assert first.summary["coverage"] == COVERAGE_STATEMENT
    # Later registry entries exist (a future wider statement):
    # the completed operation still replays its BOUND statement,
    # byte-for-byte, and no wider-store sentence appears.
    with monkeypatch.context() as m:
        m.setitem(
            erasure_mod.COVERAGE_STATEMENTS,
            "coverage/2",
            "Erased: everything everywhere, including the "
            "provenance and pipeline stores.",
        )
        replay = env.delete()
        assert replay.summary["coverage"] == COVERAGE_STATEMENT
        assert replay.summary["coverage"] == first.summary["coverage"]
        assert "provenance and pipeline" not in replay.summary["coverage"]
        rendered = render_bound_coverage(
            "coverage/1", erasure_mod._coverage_binding()[1]
        )
        assert rendered == COVERAGE_STATEMENT


def test_tx08_tampered_coverage_hash_conflicts(env):
    _seed_material(env)
    env.delete()
    completed = env.reader().completed
    assert completed is not None
    # A signature-valid row (the fixture signs it with the real
    # signer) whose bound coverage hash does not verify against
    # the registry: the reader fails closed.
    _save_operation_row(
        env.istore,
        license_id=env.license_id,
        operation_id=completed.operation_id,
        status="incomplete",
        covered_user=USER,
        erased_at=completed.erased_at,
        stores={},
        counts={},
        scope_token=erasure_mod.OPERATION_TOKEN,
        scope_version=erasure_mod.OPERATION_SCOPE_VERSION,
        coverage_id="coverage/1",
        coverage_sha256="0" * 64,
        source_fingerprint=dict(completed.source_fingerprint),
    )
    assert env.reader().conflict is not None
    # And the flow refuses at the reader, before any step:
    # zero writes to any store.
    identity_before = _table_dump(env.dir / "identity.db")
    narrative_before = _table_dump(env.dir / "narrative.db")
    with pytest.raises(ErasureRefused):
        env.flow()
    assert _table_dump(env.dir / "identity.db") == identity_before
    assert _table_dump(env.dir / "narrative.db") == narrative_before


def test_tx08_unknown_coverage_id_conflicts(tmp_path):
    env = Env(tmp_path)
    _save_operation_row(
        env.istore,
        license_id=env.license_id,
        operation_id="op-unknown-coverage",
        status="opened",
        covered_user=USER,
        erased_at=T_OLD,
        stores={},
        counts={},
        scope_token=erasure_mod.OPERATION_TOKEN,
        scope_version=erasure_mod.OPERATION_SCOPE_VERSION,
        coverage_id="coverage/99",
        coverage_sha256=erasure_mod._coverage_binding()[1],
    )
    assert env.reader().conflict is not None
    # Render-by-id fails closed on both limbs, directly.
    assert render_bound_coverage("coverage/99", "0" * 64) is None
    assert render_bound_coverage("coverage/1", "0" * 64) is None
    assert (
        render_bound_coverage(
            "coverage/1", erasure_mod._coverage_binding()[1]
        )
        == COVERAGE_STATEMENT
    )


def test_coverage_carriers_byte_identical(env):
    """Every utterance of the coverage statement is the same
    bytes: the completion receipt and the route description both
    render the registry's coverage/1 entry."""
    _seed_material(env)
    receipt = env.delete()
    from api.routes.identity_routes import router

    descriptions = [
        route.description
        for route in router.routes
        if getattr(route, "endpoint", None) is not None
        and route.endpoint.__name__ == "delete_everything"
    ]
    assert len(descriptions) == 1
    assert descriptions[0] == receipt.summary["coverage"]
    assert receipt.summary["coverage"] == COVERAGE_STATEMENT
    assert (
        erasure_mod.COVERAGE_STATEMENTS["coverage/1"]
        == COVERAGE_STATEMENT
    )


def test_legacy_replay_is_labelled_reproduction(env):
    """FPC §7: a legacy completion replays the preserved
    coverage/1 text as a LABELLED reproduction — the replay
    writes no operation row and fabricates no binding."""
    stores = {name: "not-attempted" for name in SCOPE_S_STORES}
    _save_operation_row(
        env.istore,
        license_id=env.license_id,
        operation_id="op-legacy-done",
        status="opened",
        covered_user=USER,
        erased_at=T_OLD,
        stores=stores,
        counts={},
    )
    _save_operation_row(
        env.istore,
        license_id=env.license_id,
        operation_id="op-legacy-done",
        status="completed",
        covered_user=USER,
        erased_at=T_OLD,
        stores={name: "verified" for name in SCOPE_S_STORES},
        counts={"narrative_threads": 3},
    )
    env.istore.terminate_license()
    rows_before = _op_row_bytes(env.istore)
    receipt = env.delete()
    assert receipt.summary["coverage"] == COVERAGE_STATEMENT
    assert receipt.summary["coverage_note"] == LEGACY_REPLAY_LABEL
    # The replay wrote nothing to the operation chain, and the
    # record still binds no coverage and no version: grandfathered
    # means grandfathered, not retro-fitted.
    assert _op_row_bytes(env.istore) == rows_before
    completed = env.reader().completed
    assert completed is not None
    assert completed.coverage_id is None
    assert completed.scope_version is None
    assert completed.classification_sha256 is None


# ---------------------------------------------------------------------
# Manifest readers — T-X16 (two-generation instance).
# ---------------------------------------------------------------------


def test_tx16_two_generations_coexist(tmp_path):
    """A legacy delete:execute record and a new delete:execute/1.1
    record in one identity store: the new reader binds both, each
    speaking only the four-store manifest of its generation."""
    istore = IdentityStore(db_path=tmp_path / "identity.db")
    identity_service.issue_license(owner_id=USER, store=istore)
    license_id = istore.get_license().license_id
    four = {name: "verified" for name in SCOPE_S_STORES}
    _save_operation_row(
        istore,
        license_id=license_id,
        operation_id="op-gen-legacy",
        status="completed",
        covered_user=USER,
        erased_at=T_OLD,
        stores=four,
        counts={},
    )
    cov_id, cov_sha = erasure_mod._coverage_binding()
    _save_operation_row(
        istore,
        license_id=license_id,
        operation_id="op-gen-new",
        status="completed",
        covered_user=USER_B,
        erased_at=T_OLD,
        stores=four,
        counts={},
        scope_token=erasure_mod.OPERATION_TOKEN,
        scope_version=erasure_mod.OPERATION_SCOPE_VERSION,
        coverage_id=cov_id,
        coverage_sha256=cov_sha,
        source_fingerprint={name: "ab" * 32 for name in SCOPE_S_STORES},
        classification_sha256="cd" * 32,
    )
    legacy = read_operation_records(istore, USER)
    assert legacy.conflict is None
    assert legacy.completed.scope == erasure_mod.LEGACY_OPERATION_TOKEN
    assert legacy.completed.scope_version is None
    assert set(legacy.completed.stores) == set(SCOPE_S_STORES)
    new = read_operation_records(istore, USER_B)
    assert new.conflict is None
    assert new.completed.scope == erasure_mod.OPERATION_TOKEN
    assert new.completed.scope_version == "1.1"
    assert set(new.completed.stores) == set(SCOPE_S_STORES)
    assert new.completed.coverage_id == "coverage/1"


def test_tx16_cross_checks_fail_closed(tmp_path):
    """Token ↔ scope_version ↔ store-set cross-checks: each
    forgery is conflict, with the reader trusting nothing."""
    cases = {}

    def fresh(name):
        store = IdentityStore(db_path=tmp_path / f"{name}.db")
        identity_service.issue_license(owner_id=USER, store=store)
        return store, store.get_license().license_id

    # Forged scope_version under the /1.1 token.
    store, lic = fresh("forged-version")
    _save_operation_row(
        store,
        license_id=lic,
        operation_id="op-fv",
        status="opened",
        covered_user=USER,
        erased_at=T_OLD,
        stores={},
        counts={},
        scope_token=erasure_mod.OPERATION_TOKEN,
        scope_version="1.0",
    )
    cases["forged scope_version"] = store

    # A store set wider than the token's generation (validly
    # signed — the cross-check, not the signature, refuses it).
    store, lic = fresh("wider")
    _save_operation_row(
        store,
        license_id=lic,
        operation_id="op-wide",
        status="opened",
        covered_user=USER,
        erased_at=T_OLD,
        stores={
            **{name: "not-attempted" for name in SCOPE_S_STORES},
            "provenance": "not-attempted",
        },
        counts={},
    )
    cases["wider store set"] = store

    # Later-generation tokens this binary does not bind.
    for token, version in (("delete:execute/2", "2"), ("delete:execute/3", "3")):
        store, lic = fresh(f"gen{version}")
        _save_operation_row(
            store,
            license_id=lic,
            operation_id=f"op-gen{version}",
            status="opened",
            covered_user=USER,
            erased_at=T_OLD,
            stores={},
            counts={},
            scope_token=token,
            scope_version=version,
        )
        cases[f"token {token}"] = store

    for label, store in cases.items():
        records = read_operation_records(store, USER)
        assert records.conflict is not None, label
        assert records.standing is None, label
        assert records.completed is None, label


def test_tx16_legacy_operation_resumes_and_completes(env):
    """A legacy operation resumes under landed behavior and
    completes over its own store set: its rows keep the landed
    field set exactly — no version, no coverage binding, no
    classification is invented for it (FPC §7)."""
    _seed_material(env)
    _save_operation_row(
        env.istore,
        license_id=env.license_id,
        operation_id="op-legacy-open",
        status="opened",
        covered_user=USER,
        erased_at=T_OLD,
        stores={},
        counts={},
    )
    receipt = env.delete()
    completed = env.reader().completed
    assert completed is not None
    assert completed.operation_id == "op-legacy-open"
    assert completed.statuses == ["opened", "completed"]
    assert completed.scope == erasure_mod.LEGACY_OPERATION_TOKEN
    row = _op_rows(env.istore, "op-legacy-open")[-1]
    for invented in (
        "scope_version",
        "coverage_id",
        "coverage_sha256",
        "source_fingerprint",
        "classification_sha256",
    ):
        assert invented not in row["summary"], invented
    assert receipt.summary["coverage"] == COVERAGE_STATEMENT
    assert env.nstore.erasure_recount(USER)["total"] == 0
    assert env.ostore.count_for_user(USER) == 0


# ---------------------------------------------------------------------
# Cross-version fixture — T-X16b (founder's correction,
# 2026-11-15). Two reader generations against one fixture store
# set: the legacy reader above (the landed rule, textually) and
# the new reader.
# ---------------------------------------------------------------------


def test_tx16b_legacy_reader_refuses_new_generation(env, monkeypatch):
    """Limb 1: a delete:execute/1.1 operation presented to the
    legacy reader is refused — conflict, zero writes, the
    operation's records byte-identical after the attempt."""
    _seed_material(env)
    standing = _stage_classified(env, monkeypatch)
    dump_before = _table_dump(env.dir / "identity.db")
    legacy = legacy_read_operation_records(env.istore, USER)
    assert legacy["conflict"] is not None
    assert legacy["standing"] is None
    assert legacy["completed"] is None
    assert _table_dump(env.dir / "identity.db") == dump_before
    # The new reader reads the same operation without conflict.
    recs = env.reader()
    assert recs.conflict is None
    assert recs.standing.operation_id == standing.operation_id
    assert recs.standing.scope == erasure_mod.OPERATION_TOKEN


def test_tx16b_legacy_operation_read_and_resumed_by_new_reader(env):
    """Limb 2: a supported historical delete:execute operation is
    read by both readers and resumed to completion by the new
    reader under landed semantics — its store set and recorded
    lifecycle exactly as written."""
    _seed_material(env)
    _save_operation_row(
        env.istore,
        license_id=env.license_id,
        operation_id="op-historical",
        status="opened",
        covered_user=USER,
        erased_at=T_OLD,
        stores={},
        counts={},
    )
    legacy = legacy_read_operation_records(env.istore, USER)
    assert legacy["conflict"] is None
    assert legacy["standing"]["operation_id"] == "op-historical"
    receipt = env.delete()
    completed = env.reader().completed
    assert completed is not None
    assert completed.operation_id == "op-historical"
    assert completed.statuses == ["opened", "completed"]
    assert completed.scope_version is None
    assert completed.coverage_id is None
    assert receipt.summary["coverage"] == COVERAGE_STATEMENT
    assert env.nstore.erasure_recount(USER)["total"] == 0


def test_tx16b_neither_generation_widens_or_bypasses(
    env, monkeypatch, tmp_path
):
    """Limb 3: neither generation silently widens the store set
    or bypasses the recorded lifecycle."""
    # (a) A wider-than-four store set GRAFTED onto a signed
    # legacy record (the set was never in its signed payload):
    # both readers fail it on signature verification.
    _save_operation_row(
        env.istore,
        license_id=env.license_id,
        operation_id="op-graft",
        status="opened",
        covered_user=USER,
        erased_at=T_OLD,
        stores={},
        counts={},
    )
    row = _op_rows(env.istore, "op-graft")[0]
    grafted = dict(row["summary"])
    grafted["stores"] = {
        **{name: "not-attempted" for name in SCOPE_S_STORES},
        "provenance": "not-attempted",
    }
    _sql(
        env.istore,
        "UPDATE deletion_receipts SET summary_json = ? "
        "WHERE receipt_id = ?",
        (json.dumps(grafted), row["receipt_id"]),
    )
    assert env.reader().conflict is not None
    assert (
        legacy_read_operation_records(env.istore, USER)["conflict"]
        is not None
    )

    # (b) A new-generation resume that would skip work-row
    # verification: the standing classified operation's work row
    # is corrupted, so execution cannot proceed from it — the
    # flow refuses, deleting nothing.
    env2 = Env(tmp_path / "b")
    _seed_material(env2)
    standing = _stage_classified(env2, monkeypatch)
    payload, verified = env2.istore.load_operation_work(
        standing.operation_id
    )
    assert verified
    tampered = dict(payload)
    tampered["scrub_set"] = ["forged-entry"]
    _sql(
        env2.istore,
        "UPDATE erasure_operation_work SET payload_json = ? "
        "WHERE operation_id = ?",
        (json.dumps(tampered, sort_keys=True), standing.operation_id),
    )
    rows_before = _op_row_bytes(env2.istore)
    with pytest.raises(ErasureRefused):
        env2.flow()
    assert _op_row_bytes(env2.istore) == rows_before
    assert env2.nstore.erasure_recount(USER)["total"] > 0
    assert env2.istore.get_license().status == "active"

    # (c) A new-generation record re-presented under a forged
    # legacy token: the token sits inside the signed payload, so
    # both readers fail it on signature verification.
    env3 = Env(tmp_path / "c")
    _seed_material(env3)
    _stage_opened_unclassified(env3, monkeypatch)
    raw = _op_rows(env3.istore)[0]
    forged = dict(raw["summary"])
    forged["scope"] = erasure_mod.LEGACY_OPERATION_TOKEN
    (tmp_path / "d").mkdir(parents=True, exist_ok=True)
    store4 = IdentityStore(db_path=tmp_path / "d" / "identity.db")
    _sql(
        store4,
        "INSERT INTO deletion_receipts (receipt_id, ts, "
        "license_id, summary_json, signature) VALUES (?, ?, ?, ?, ?)",
        (
            raw["receipt_id"],
            "2026-11-16T00:00:00+00:00",
            env3.license_id,
            json.dumps(forged),
            raw["signature"],
        ),
    )
    assert read_operation_records(store4, USER).conflict is not None
    assert (
        legacy_read_operation_records(store4, USER)["conflict"]
        is not None
    )
    # Control: the unforged record reads cleanly under the new
    # reader in its own store.
    assert env3.reader().conflict is None


# ---------------------------------------------------------------------
# T-X49 (refined, footprint §2.4) — FIXTURE-ONLY cross-store
# recovery evidence. The §2.3 recovery procedure is implemented
# here as fixture machinery over tiny fixture stores, because
# production provenance/pipeline stores do not exist in this
# increment's footprint; nothing in this test touches or claims
# real cross-store recovery (Gate C clarification, 2026-11-15).
# The DCV reserve variant is specified but NOT built.
#
# Fixture shape: a completed, sealed joint operation over a
# fixture pipeline store and a fixture provenance store (work
# row destroyed at sealing — the sealed record below is all that
# remains). The pipeline classification holds two determinate
# local erase entries, one TWIN-HELD entry (held solely because
# its provenance twin was held-class), and one surviving entry
# carrying a same-store key_line_source.entry_id pointer at an
# erased entry. The incident: pipeline.db alone is replaced from
# its pre-erasure byte copy; provenance remains erased.
# ---------------------------------------------------------------------

_PIPE_SCHEMA = (
    "CREATE TABLE entries (id TEXT PRIMARY KEY, disposition TEXT, "
    "twin TEXT, key_line_source TEXT, content TEXT)"
)

_PIPE_PRE_ERASURE = [
    ("pipe-1", "erase", None, None, "alpha"),
    ("pipe-2", "erase", None, None, "beta"),
    ("pipe-3", "hold", "prov-3", None, "gamma"),
    ("pipe-4", "keep", None, '{"entry_id": "pipe-1"}', "delta"),
]

_PIPE_CLASSIFICATION = {
    "pipeline": {
        "entries": [
            {"id": "pipe-1", "kind": "record", "disposition": "erase", "group": ""},
            {"id": "pipe-2", "kind": "record", "disposition": "erase", "group": ""},
            {"id": "pipe-3", "kind": "record", "disposition": "hold", "group": "twin:prov-3"},
            {"id": "pipe-4", "kind": "record", "disposition": "keep", "group": ""},
        ],
        "counts": {"records": 4},
    }
}


def _pipe_payload(rows):
    """The pipeline read-set payload the fingerprint binds:
    exactly what the store's classifier reads, per entry."""
    return {
        "entries": [
            [row[0], row[1], row[2], row[3], row[4]]
            for row in sorted(rows)
        ]
    }


def _pipe_rows(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT id, disposition, twin, key_line_source, content "
            "FROM entries ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _pipe_write(db_path, rows):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE IF EXISTS entries")
        conn.execute(_PIPE_SCHEMA)
        conn.executemany(
            "INSERT INTO entries VALUES (?, ?, ?, ?, ?)", rows
        )
        conn.commit()
    finally:
        conn.close()


def _db_snapshot(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return "\n".join(conn.iterdump())
    finally:
        conn.close()


def _db_hash(db_path):
    return hashlib.sha256(_db_snapshot(db_path).encode("utf-8")).hexdigest()


def _joint_fixture(tmp_path):
    """Build the sealed joint operation and the incident state.
    Returns (pipe_path, prov_path, opening_record)."""
    pipe = tmp_path / "pipeline.db"
    prov = tmp_path / "provenance.db"
    # Pre-erasure byte copy of the pipeline store.
    _pipe_write(pipe, _PIPE_PRE_ERASURE)
    pre_erasure_copy = pipe.read_bytes()
    # The sealed operation's opening record: fingerprint bound
    # over the pre-erasure read set, classification hash bound,
    # lifecycle complete (its work row was destroyed at sealing).
    opening = {
        "operation_id": "op-joint-fixture",
        "statuses": ["opened", "classified", "executing", "completed"],
        "source_fingerprint": {
            "pipeline": erasure_mod._fingerprint_portion(
                _pipe_payload(_PIPE_PRE_ERASURE)
            )
        },
        "classification_sha256": erasure_mod._classification_sha256(
            _PIPE_CLASSIFICATION
        ),
    }
    # Post-erasure state: erase entries gone, twin-held entry
    # untouched, survivor's pointer scrubbed. Provenance erased
    # (prov-3's row among the gone).
    _pipe_write(
        pipe,
        [
            ("pipe-3", "hold", "prov-3", None, "gamma"),
            ("pipe-4", "keep", None, None, "delta"),
        ],
    )
    _pipe_write(prov, [("prov-9", "keep", None, None, "unrelated")])
    # The incident: pipeline.db replaced from its pre-erasure
    # byte copy; provenance remains erased.
    pipe.write_bytes(pre_erasure_copy)
    return pipe, prov, opening


def _fixture_recover(pipe_path, opening, classification):
    """The §2.3 recovery procedure, as fixture machinery:
    quarantine on detection; verify the presented classification
    IS the sealed one (hash-bound) and the restored store's
    fingerprint portion matches the opening record; locally
    re-derive ONLY the determinate entries (twin-dependent
    classes are never locally derivable); erase exactly those;
    scrub same-store pointers at erased entries; name the rest
    unresolved in the reconciled record. Any verification
    failure: zero writes, the whole store stays quarantined."""
    record = {
        "operation_id": opening["operation_id"],
        "standing": "quarantined",
        "erased": [],
        "scrubbed": [],
        "unresolved": [],
        "reason": "",
    }
    if erasure_mod._classification_sha256(classification) != opening[
        "classification_sha256"
    ]:
        record["reason"] = "presented classification is not the sealed one"
        record["unresolved"] = [
            e["id"] for e in classification["pipeline"]["entries"]
        ]
        return record
    rows = _pipe_rows(pipe_path)
    portion = erasure_mod._fingerprint_portion(_pipe_payload(rows))
    if portion != opening["source_fingerprint"]["pipeline"]:
        record["reason"] = "fingerprint portion mismatch"
        record["unresolved"] = [row[0] for row in rows]
        return record
    by_id = {row[0]: row for row in rows}
    entries = classification["pipeline"]["entries"]
    derivable, unprovable = [], []
    for entry in entries:
        row = by_id.get(entry["id"])
        twin_dependent = entry["group"].startswith("twin:") or (
            row is not None and row[2] is not None
        )
        if twin_dependent:
            unprovable.append(entry)
        else:
            derivable.append(entry)
    # Accounting is exact: |read set| = |locally proven| +
    # |unprovable| — asserted by the caller via these lists.
    record["locally_proven"] = [e["id"] for e in derivable]
    record["unprovable"] = [e["id"] for e in unprovable]
    erased = []
    conn = sqlite3.connect(str(pipe_path))
    try:
        for entry in derivable:
            if entry["disposition"] == "erase":
                conn.execute(
                    "DELETE FROM entries WHERE id = ?", (entry["id"],)
                )
                erased.append(entry["id"])
        # Scrub same-store key_line_source pointers at erased
        # entries on the survivors.
        for row in _pipe_rows(pipe_path):
            if row[3]:
                pointer = json.loads(row[3])
                if pointer.get("entry_id") in erased:
                    conn.execute(
                        "UPDATE entries SET key_line_source = NULL "
                        "WHERE id = ?",
                        (row[0],),
                    )
                    record["scrubbed"].append(row[0])
        conn.commit()
    finally:
        conn.close()
    record["erased"] = erased
    record["unresolved"] = [e["id"] for e in unprovable]
    record["standing"] = "reconciled"
    record["reason"] = "partial standing bound: twin-dependent entries unresolved"
    return record


def test_tx49_fixture_recovery(tmp_path):
    pipe, prov, opening = _joint_fixture(tmp_path)
    prov_hash_before = _db_hash(prov)
    twin_row_before = [r for r in _pipe_rows(pipe) if r[0] == "pipe-3"]
    record = _fixture_recover(pipe, opening, _PIPE_CLASSIFICATION)
    assert record["standing"] == "reconciled"
    # Local re-derivation identified exactly the determinate
    # entries, and recovery erased exactly those.
    assert record["erased"] == ["pipe-1", "pipe-2"]
    remaining = {row[0] for row in _pipe_rows(pipe)}
    assert remaining == {"pipe-3", "pipe-4"}
    # Recovered erase counts do not exceed the sealed per-class
    # counts.
    sealed_erases = [
        e
        for e in _PIPE_CLASSIFICATION["pipeline"]["entries"]
        if e["disposition"] == "erase"
    ]
    assert len(record["erased"]) <= len(sealed_erases)
    # Accounting is exact: |read set| = |locally proven| +
    # |unprovable|.
    assert len(_PIPE_PRE_ERASURE) == len(record["locally_proven"]) + len(
        record["unprovable"]
    )
    # The planted key_line_source.entry_id pointer is scrubbed.
    pipe4 = [r for r in _pipe_rows(pipe) if r[0] == "pipe-4"][0]
    assert pipe4[3] is None
    assert record["scrubbed"] == ["pipe-4"]
    # The twin-held entry was NOT erased and NOT re-derived: it
    # stands byte-identical, named unresolved in the record.
    assert [r for r in _pipe_rows(pipe) if r[0] == "pipe-3"] == twin_row_before
    assert record["unresolved"] == ["pipe-3"]
    # Zero counterpart writes: the provenance snapshot is
    # byte-identical after recovery.
    assert _db_hash(prov) == prov_hash_before


def test_tx49_negative_altered_content(tmp_path):
    """Negative (a): one record's disposition-relevant content
    altered in the restored copy → fingerprint mismatch → zero
    writes, the whole store quarantined."""
    pipe, prov, opening = _joint_fixture(tmp_path)
    rows = [list(r) for r in _pipe_rows(pipe)]
    for row in rows:
        if row[0] == "pipe-1":
            row[4] = "alpha-altered"
    _pipe_write(pipe, [tuple(r) for r in rows])
    snapshot_before = _db_snapshot(pipe)
    record = _fixture_recover(pipe, opening, _PIPE_CLASSIFICATION)
    assert record["standing"] == "quarantined"
    assert record["erased"] == []
    assert _db_snapshot(pipe) == snapshot_before


def test_tx49_negative_missing_record(tmp_path):
    """Negative (b): one record missing from the restored copy →
    fingerprint mismatch → zero writes, whole store quarantined."""
    pipe, prov, opening = _joint_fixture(tmp_path)
    rows = [r for r in _pipe_rows(pipe) if r[0] != "pipe-2"]
    _pipe_write(pipe, rows)
    snapshot_before = _db_snapshot(pipe)
    record = _fixture_recover(pipe, opening, _PIPE_CLASSIFICATION)
    assert record["standing"] == "quarantined"
    assert record["erased"] == []
    assert _db_snapshot(pipe) == snapshot_before


def test_tx49_negative_forged_disposition(tmp_path):
    """Negative (c): a forged disposition — the twin-held entry's
    erase attempted on the argument that its twin no longer
    exists (the naive joint re-classification outcome). Refused:
    the presented classification is not the sealed one, and
    twin-dependent classes are never locally derivable. The
    entry stands byte-identical at fixture end."""
    pipe, prov, opening = _joint_fixture(tmp_path)
    forged = json.loads(json.dumps(_PIPE_CLASSIFICATION))
    for entry in forged["pipeline"]["entries"]:
        if entry["id"] == "pipe-3":
            entry["disposition"] = "erase"
            entry["group"] = ""
    snapshot_before = _db_snapshot(pipe)
    record = _fixture_recover(pipe, opening, forged)
    assert record["standing"] == "quarantined"
    assert record["erased"] == []
    assert _db_snapshot(pipe) == snapshot_before
    pipe3 = [r for r in _pipe_rows(pipe) if r[0] == "pipe-3"]
    assert pipe3 == [("pipe-3", "hold", "prov-3", None, "gamma")]
