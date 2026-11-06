"""C1a write-authority infrastructure tests (brief §16).

Every test is deterministic: no model calls, no network, no live
staging writes. Tests run against isolated tmp SQLite databases (the
``tmp_path`` pattern), seeded with fixture rows; flip tests run
against scratch copies, never the live file.

The flip PATH itself (the C2 migration transaction that moves rows)
is NOT built in C1a — so these tests drive it through the test-only
fixture flip in this file (``_fixture_flip`` / ``_fixture_flip_txn``),
which performs exactly the §11.3 ordered steps against the C1a-built
machinery (attempt record → fingerprint inside the transaction →
node-row inserts → authority row → attempt marked flipped). The
fixture flip is test code, not production code: no flip may run in
C1a outside a test.

C1b tests (T-G5, T-G6, T-R1–T-R4, T-P1–T-P6, T-S1–T-S5, T-T1a–T-T4,
T-H1–T-H2) are OUT of scope for C1a — they test the read shim,
projection, census, tombstones, and historical-read path, which C1a
does not build. They are named here as C1b scope, not dropped.
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as S

UID = "u1"
REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures + small helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the VE SQLite DB per test (same pattern as
    test_unified_node_projection)."""
    import local_ai.vision_execution.storage as ve_store

    ve_db = tmp_path / "ve.db"
    monkeypatch.setattr(ve_store, "_DB_PATH", ve_db)
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {"db_path": ve_db}


@pytest.fixture()
def conv_store(tmp_path):
    """A real (tmp-file) conversation store, for proposal fixtures."""
    from local_ai.conversation.store import ConversationStore

    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


def _raw(db_path):
    """A raw sqlite3 connection to the test DB (lock-holding, direct
    SQL, cross-connection visibility checks)."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _count(conn, table, where="", params=()):
    row = conn.execute(f"SELECT COUNT(*) FROM {table} {where}", params).fetchone()
    return int(row[0])


def _history_events(conn, subtree_id=None):
    """Ledger history events, in order (event, detail_json)."""
    if subtree_id is None:
        rows = conn.execute(
            "SELECT event, detail_json FROM ledger_history ORDER BY rowid"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT event, detail_json FROM ledger_history "
            "WHERE subtree_id = ? ORDER BY rowid",
            (subtree_id,),
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _ledger(conn, subtree_id):
    return S._ledger_row(conn, subtree_id)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _seed_subtree(uid, *, n_tasks=1, with_idea=True, with_checklist=True,
                  with_steps=True, with_seats=True, prefix=""):
    """Build one legacy subtree: idea → initiative → project → tasks,
    plus an optional checklist on the idea and execution steps scoped
    to the initiative / project. Returns the ids."""
    idea_id = None
    if with_idea:
        idea = S.create_idea(
            M.IdeaCreate(title=f"{prefix}idea", status="Captured"), uid
        )
        idea_id = idea["id"]
    seats = (
        [M.InitiativeSeat(role="mentor", estimated_effort="2h", notes="seat")]
        if with_seats
        else []
    )
    init = S.create_initiative(
        M.InitiativeCreate(
            source_idea_id=idea_id,
            title=f"{prefix}initiative",
            status="Active",
            seats=seats,
        ),
        uid,
    )
    initiative_id = init["id"]
    proj = S.create_project(
        M.ProjectCreate(
            initiative_id=initiative_id, title=f"{prefix}project",
            status="Active",
        ),
        uid,
    )
    project_id = proj["id"]
    task_ids = []
    for i in range(n_tasks):
        task = S.create_task(
            M.TaskCreate(
                project_id=project_id, title=f"{prefix}task-{i}",
                status="Todo",
            ),
            uid,
        )
        task_ids.append(task["id"])
    item_id = item2_id = None
    if with_checklist and idea_id is not None:
        item = S.create_checklist_item(uid, idea_id, f"{prefix}check-1")
        item_id = item["id"]
        item2 = S.create_checklist_item(uid, idea_id, f"{prefix}check-2")
        item2_id = item2["id"]
    step_id = step2_id = None
    if with_steps:
        step = S.create_execution_step(
            uid, S.EXECUTION_STEPS_SCOPE_INITIATIVE, initiative_id,
            f"{prefix}step-1", None,
        )
        step_id = step["id"]
        step2 = S.create_execution_step(
            uid, S.EXECUTION_STEPS_SCOPE_PROJECT, project_id,
            f"{prefix}step-2", None,
        )
        step2_id = step2["id"]
    return {
        "uid": uid,
        "idea_id": idea_id,
        "initiative_id": initiative_id,
        "project_id": project_id,
        "task_ids": task_ids,
        "task_id": task_ids[0] if task_ids else None,
        "item_id": item_id,
        "item2_id": item2_id,
        "step_id": step_id,
        "step2_id": step2_id,
    }


def _seed_proposal(uid, conv_store, parent_task_id, title, *, convo="talk-1"):
    """Record one pending proposal whose parent is ``parent_task_id``,
    via a real champion message in a real conversation store (the
    C1 provenance path, as in test_firebrand_task_context)."""
    body = (
        "Prose here.\n```task-proposal\n"
        + json.dumps({"proposals": [{
            "title": title,
            "parent_task_id": parent_task_id,
            "timeframe_commitment": "tentative",
            "due_date": None,
            "notes": "Ask about referral",
        }]})
        + "\n```"
    )
    conv_store.ensure_conversation(uid, convo)
    msg = conv_store.append_message(uid, convo, "champion", "voice", body)
    payload = {
        "conversation_id": convo,
        "source_message_id": msg["id"],
        "block_index": 0,
        "proposal_index": 0,
        "title": title,
        "parent_task_id": parent_task_id,
        "timeframe_commitment": "tentative",
        "due_date": None,
        "notes": "Ask about referral",
        "evidence_quote": "Prose here.",
    }
    return S.record_task_proposal(uid, payload, conversation_store=conv_store)


def _seed_rich_fixture(uid, conv_store, *, prefix=""):
    """A subtree plus two pending proposals parented to its task (one
    for update, one for approve). Used by the guard / freeze tests."""
    fx = _seed_subtree(uid, prefix=prefix)
    fx["proposal_id"] = _seed_proposal(
        uid, conv_store, fx["task_id"], f"{prefix}proposal-update"
    )["id"]
    fx["proposal2_id"] = _seed_proposal(
        uid, conv_store, fx["task_id"], f"{prefix}proposal-approve"
    )["id"]
    return fx


# ---------------------------------------------------------------------------
# Test-only flip + node-write helpers (NOT production code)
# ---------------------------------------------------------------------------


class AlreadyFlippedError(Exception):
    """Test-local: the fixture flip found authority='node' already.
    The brief names no production error for this case (C2 to name
    it); the fixture flip refuses rather than double-flipping."""


class _FixtureFlipCheckFailed(Exception):
    """Test-local: an injected pre-commit check failure (T-X3)."""


def _fixture_prepare_flip(subtree_id, *, authorization_ref="auth-test",
                          operator="test"):
    """Release the pause for the subtree and record the attempt.
    Returns the attempt id. The attempt is `recorded` afterwards."""
    S.release_migration_pause_for_subtree(
        subtree_id, authorization_ref, operator
    )
    attempt = S.record_flip_attempt(subtree_id, authorization_ref, operator)
    return attempt["attempt_id"]


def _insert_node_row(conn, form, user_id, now):
    """One node-form dict → one `nodes` row (the flip's own insert)."""
    cols = list(S._NODE_FORM_FIELDS)
    vals = []
    for key in cols:
        value = form.get(key)
        if key == "dependency_ids":
            vals.append(json.dumps(value or []))
        elif key == "tags":
            vals.append(json.dumps(value) if value is not None else None)
        else:
            vals.append(value)
    conn.execute(
        f"INSERT INTO nodes ({', '.join(cols)}, user_id, created_at, updated_at) "
        f"VALUES ({', '.join('?' * (len(cols) + 3))})",
        vals + [user_id, now, now],
    )


def _fixture_flip_txn(conn, subtree_id, attempt_id, user_id, *,
                      pre_commit_hook=None, mark_attempt=True,
                      write_flip_event=True, fail_before_commit=False,
                      authorization_ref="auth-test", operator="test"):
    """The fixture flip transaction (§11.3 ordered steps): check the
    authority (refuse if already 'node'), compute the fingerprint
    INSIDE the transaction, insert the node rows + seats, create the
    authority row (version 1, fingerprint hash + canonical JSON),
    optionally run a pre-commit hook (race tests hold the transaction
    open here), write the `flip_committed` history entry, and mark
    the attempt `flipped`. Commits on clean exit; rolls back on any
    failure (the node rows + ledger row are atomic with the flip).

    ``mark_attempt=False`` leaves the attempt `recorded` (T-X5 /
    T-RC1 case (b)/(c): the flip committed but the process died
    before the attempt could be observed). ``write_flip_event=False``
    omits the `flip_committed` entry (T-RC1 case (c): inconsistent).
    ``fail_before_commit=True`` raises after the inserts (T-X3)."""
    flipped_at = S._now()
    with S.ve_write_transaction(conn, purpose="fixture_flip"):
        if S._ledger_authority(conn, subtree_id) == "node":
            raise AlreadyFlippedError(
                f"subtree {subtree_id} already has node authority"
            )
        fp = S.compute_legacy_subtree_fingerprint(
            conn, subtree_id, flipped_at=flipped_at
        )
        doc = json.loads(fp["canonical_json"])
        now = S._now()
        for form in doc["nodes"]:
            _insert_node_row(conn, form, user_id, now)
        for seat in doc["node_seats"]:
            conn.execute(
                "INSERT INTO node_seats (id, node_id, role, "
                "assigned_person_id, estimated_effort, notes, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    seat["id"], seat["node_id"], seat["role"],
                    seat.get("assigned_person_id"),
                    seat.get("estimated_effort"), seat.get("notes") or "",
                    now, now,
                ),
            )
        conn.execute(
            "INSERT INTO migration_ledger (subtree_id, authority, version, "
            "fingerprint_sha256, fingerprint_canonical_json, flipped_at, "
            "flip_authorization_ref, created_at, updated_at) "
            "VALUES (?, 'node', 1, ?, ?, ?, ?, ?, ?)",
            (
                subtree_id, fp["sha256"], fp["canonical_json"], flipped_at,
                authorization_ref, now, now,
            ),
        )
        if fail_before_commit:
            raise _FixtureFlipCheckFailed("census mismatch (injected)")
        if pre_commit_hook is not None:
            pre_commit_hook()
        if write_flip_event:
            S._append_ledger_history(
                conn,
                subtree_id=subtree_id,
                event="flip_committed",
                actor=operator,
                detail={
                    "attempt_id": attempt_id,
                    "fingerprint_sha256": fp["sha256"],
                },
            )
        if mark_attempt:
            conn.execute(
                "UPDATE flip_attempts SET state = 'flipped', ended_at = ? "
                "WHERE attempt_id = ?",
                (now, attempt_id),
            )
        S._commit_if_owner(conn)
    return {
        "attempt_id": attempt_id,
        "fingerprint_sha256": fp["sha256"],
        "canonical_json": fp["canonical_json"],
    }


def _fixture_flip(subtree_id, user_id, **kwargs):
    """Release + record + flip, in the calling thread. Returns the
    flip result dict (attempt id, fingerprint hash, canonical JSON)."""
    attempt_id = _fixture_prepare_flip(subtree_id)
    return _fixture_flip_txn(
        S.get_connection(), subtree_id, attempt_id, user_id, **kwargs
    )


def _bump_version_and_fingerprint(conn, subtree_id):
    """The C2 node-write contract, test-only: bump the authority
    version, then recompute + re-store the fingerprint in the SAME
    transaction. The version is updated BEFORE the recompute because
    the canonical document binds the version."""
    ledger = S._ledger_row(conn, subtree_id)
    new_version = (ledger["version"] or 0) + 1
    conn.execute(
        "UPDATE migration_ledger SET version = ? WHERE subtree_id = ?",
        (new_version, subtree_id),
    )
    fp = S.compute_subtree_fingerprint(conn, subtree_id)
    conn.execute(
        "UPDATE migration_ledger SET fingerprint_sha256 = ?, "
        "fingerprint_canonical_json = ?, updated_at = ? "
        "WHERE subtree_id = ?",
        (fp["sha256"], fp["canonical_json"], S._now(), subtree_id),
    )


def _fixture_insert_node(conn, subtree_id, form, user_id):
    """Test-only node write (the §5.5 `create_node` contract, for
    tests only): guard + insert + version bump in one transaction.
    Callers hold the helper transaction."""
    S._guard_node_write(conn, subtree_id, target_id=form["id"],
                        target_kind="node")
    _insert_node_row(conn, form, user_id, S._now())
    _bump_version_and_fingerprint(conn, subtree_id)


def _fixture_update_node(conn, subtree_id, node_id, user_id, **fields):
    """Test-only node write (the §5.5 `update_node` contract, for
    tests only): guard + update + version bump + fingerprint
    re-store in one transaction. Callers hold the helper
    transaction."""
    S._guard_node_write(conn, subtree_id, target_id=node_id,
                        target_kind="node")
    sets = ", ".join(f"{key} = ?" for key in fields)
    args = list(fields.values()) + [S._now(), node_id, user_id]
    conn.execute(
        f"UPDATE nodes SET {sets}, updated_at = ? "
        "WHERE id = ? AND user_id = ?",
        args,
    )
    _bump_version_and_fingerprint(conn, subtree_id)


def _test_only_rollback_proof(conn, subtree_id):
    """Test-only rollback PROOF (T-F4–T-F8): recompute the fingerprint
    from the node rows inside a transaction and compare it with the
    stored fingerprint + canonical document. Returns (ok, reason).
    The production rollback operation is NOT C1a — this proves only
    the machinery the rollback depends on (version + fingerprint)."""
    with S.ve_write_transaction(conn, purpose="test_only_rollback_proof"):
        ledger = S._ledger_row(conn, subtree_id)
        if ledger is None:
            return False, "no authority row"
        try:
            recomputed = S.compute_subtree_fingerprint(conn, subtree_id)
        except ValueError as exc:
            return False, f"recompute failed: {exc}"
        if recomputed["sha256"] != ledger["fingerprint_sha256"]:
            return False, "fingerprint mismatch"
        if recomputed["canonical_json"] != ledger["fingerprint_canonical_json"]:
            return False, "canonical document mismatch"
        return True, "proof ok"

# ---------------------------------------------------------------------------
# The 26-write harness (T-G1 / T-G2 / T-FZ1)
# ---------------------------------------------------------------------------


def _all_writes(fx, conv_store):
    """One attempt per class-A writer against the fixture subtree.
    Returns a list of (name, thunk). Deletes run last (they destroy
    the fixture for later writes). ``create_idea`` and
    ``create_initiative`` are NOT in this list: they create brand-new
    rows / subtree roots, so they never target a flipped subtree's
    legacy row — they are asserted separately (they must succeed
    even while another subtree is flipped)."""
    uid = fx["uid"]
    idea_id = fx["idea_id"]
    initiative_id = fx["initiative_id"]
    project_id = fx["project_id"]
    task_id = fx["task_id"]
    item_id = fx["item_id"]
    item2_id = fx["item2_id"]
    step_id = fx["step_id"]
    proposal_id = fx["proposal_id"]
    proposal2_id = fx["proposal2_id"]
    return [
        ("update_idea",
         lambda: S.update_idea(idea_id, M.IdeaUpdate(title="idea-2"), uid)),
        ("create_checklist_item",
         lambda: S.create_checklist_item(uid, idea_id, "new-check")),
        ("update_checklist_item",
         lambda: S.update_checklist_item(item_id, uid, title="check-2")),
        ("add_checklist_dependency",
         lambda: S.add_checklist_dependency(item_id, item2_id, uid)),
        ("remove_checklist_dependency",
         lambda: S.remove_checklist_dependency(item_id, item2_id, uid)),
        ("mark_checklist_superseded",
         lambda: S.mark_checklist_superseded(idea_id, uid)),
        ("update_initiative",
         lambda: S.update_initiative(
             initiative_id, M.InitiativeUpdate(title="init-2"), uid)),
        ("create_execution_step",
         lambda: S.create_execution_step(
             uid, S.EXECUTION_STEPS_SCOPE_INITIATIVE, initiative_id,
             "new-step", None)),
        ("update_execution_step",
         lambda: S.update_execution_step(step_id, uid, {"title": "step-2"})),
        ("materialize_execution_steps",
         lambda: S.materialize_execution_steps(
             uid, S.EXECUTION_STEPS_SCOPE_INITIATIVE, initiative_id,
             ["m1"], "user", replace=True)),
        ("reorder_execution_steps",
         lambda: S.reorder_execution_steps(
             uid, S.EXECUTION_STEPS_SCOPE_INITIATIVE, initiative_id,
             [step_id])),
        ("create_project",
         lambda: S.create_project(
             M.ProjectCreate(initiative_id=initiative_id, title="p2",
                             status="Active"), uid)),
        ("update_project",
         lambda: S.update_project(
             project_id, M.ProjectUpdate(title="proj-2"), uid)),
        ("create_task",
         lambda: S.create_task(
             M.TaskCreate(project_id=project_id, title="t2",
                          status="Todo"), uid)),
        ("update_task",
         lambda: S.update_task(
             task_id, M.TaskUpdate(title="task-2"), uid)),
        ("record_task_proposal",
         lambda: _seed_proposal(uid, conv_store, task_id, "proposal-3")),
        ("update_task_proposal",
         lambda: S.update_task_proposal(
             uid, proposal_id, {"title": "proposal-2"})),
        ("approve_task_proposal",
         lambda: S.approve_task_proposal(uid, proposal2_id)),
        # -- destructive writes last --
        ("delete_idea", lambda: S.delete_idea(idea_id, uid)),
        ("delete_checklist_item",
         lambda: S.delete_checklist_item(item_id, uid)),
        ("delete_execution_step",
         lambda: S.delete_execution_step(step_id, uid)),
        ("delete_initiative",
         lambda: S.delete_initiative(initiative_id, uid)),
        ("delete_project", lambda: S.delete_project(project_id, uid)),
        ("delete_task", lambda: S.delete_task(task_id, uid)),
    ]


def _run_writes(writes):
    """Run each thunk; return {name: (kind, detail)} where kind is
    'ok' or the exception class name."""
    outcomes = {}
    for name, thunk in writes:
        try:
            thunk()
            outcomes[name] = ("ok", None)
        except Exception as exc:  # noqa: BLE001 - the harness records it
            outcomes[name] = (type(exc).__name__, str(exc))
    return outcomes


# ---------------------------------------------------------------------------
# 16.1 Concurrency (the race tests)
# ---------------------------------------------------------------------------


def _race_flip_vs_writer(ve_ctx, *, flip_first, hold_seconds=0.05):
    """One flip-vs-writer race. ``flip_first=True`` holds the flip
    open while the writer attempts (writer must be refused);
    ``flip_first=False`` lets the writer commit before the flip
    starts (the flip's fingerprint must include the writer's value).
    Returns (flip_result, writer_outcome) where writer_outcome is
    ('ok', title) or ('error', ExceptionClassName)."""
    db_path = ve_ctx["db_path"]
    fx = _seed_subtree(UID, prefix="race-")
    subtree_id = fx["initiative_id"]
    task_id = fx["task_id"]
    attempt_id = _fixture_prepare_flip(subtree_id)
    barrier = threading.Barrier(2)
    flip_holding = threading.Event()
    writer_done = threading.Event()
    results = {}

    def flip_thread():
        conn = S.get_connection()
        barrier.wait(timeout=10)
        if not flip_first:
            # Let the writer commit first; the flip must include it.
            writer_done.wait(timeout=10)

        def hook():
            flip_holding.set()
            time.sleep(hold_seconds)

        try:
            results["flip"] = _fixture_flip_txn(
                conn, subtree_id, attempt_id, UID, pre_commit_hook=hook
            )
        except Exception as exc:  # noqa: BLE001 - recorded for assert
            results["flip"] = exc

    def writer_thread():
        barrier.wait(timeout=10)
        if flip_first:
            # Attempt only once the flip is holding the lock.
            flip_holding.wait(timeout=10)
        try:
            S.update_task(task_id, M.TaskUpdate(title="writer-value"), UID)
            results["writer"] = ("ok", "writer-value")
        except Exception as exc:  # noqa: BLE001 - recorded for assert
            results["writer"] = ("error", type(exc).__name__)
        finally:
            writer_done.set()

    ta = threading.Thread(target=flip_thread)
    tb = threading.Thread(target=writer_thread)
    ta.start()
    tb.start()
    ta.join(timeout=30)
    tb.join(timeout=30)
    assert not ta.is_alive() and not tb.is_alive(), "race threads hung"
    return results.get("flip"), results.get("writer"), fx


def test_t_c1_legacy_write_vs_subtree_flip_raced(ve_ctx):
    """T-C1: exactly one ordering prevails in every run — either the
    writer commits before the flip (and the flip's census includes
    the writer's value) or the writer is refused after the flip
    commits (named error, nothing written). Zero runs show a
    post-flip legacy mutation. N = 50 (25 per ordering)."""
    for i in range(25):
        # Writer first: the flip's fingerprint must include the
        # writer's value (the T-C1 adaptation: the fingerprint
        # includes B's value — the census is C1b).
        flip, writer, fx = _race_flip_vs_writer(ve_ctx, flip_first=False)
        assert writer == ("ok", "writer-value"), f"run {i}: {writer}"
        assert isinstance(flip, dict), f"run {i}: flip failed: {flip}"
        conn = S.get_connection()
        recomputed = S.compute_subtree_fingerprint(conn, fx["initiative_id"])
        assert recomputed["sha256"] == flip["fingerprint_sha256"]
        doc = json.loads(recomputed["canonical_json"])
        titles = {n["id"]: n["title"] for n in doc["nodes"]}
        assert titles[fx["task_id"]] == "writer-value"
    for i in range(25):
        # Flip first: the writer must be refused, nothing written.
        flip, writer, fx = _race_flip_vs_writer(ve_ctx, flip_first=True)
        assert isinstance(flip, dict), f"run {i}: flip failed: {flip}"
        assert writer == ("error", "MigratedNodeWriteRefused"), (
            f"run {i}: {writer}"
        )
        conn = S.get_connection()
        task = S.get_task(fx["task_id"], UID)
        assert task["title"] != "writer-value"


def test_t_c2_two_flips_same_subtree_raced(ve_ctx):
    """T-C2 (adapted — pinned finding): the brief's 'one failed
    attempt recorded' is not literally realizable under §8.2 (a
    `recorded` attempt blocks ALL other recordings globally, so the
    race loser has no attempt row). This test pins the realizable
    invariant: exactly one flip, exactly one `flip_committed`
    event; the loser fails with `UnresolvedFlipAttempt` (record
    refused) or the already-flipped refusal. Plus a sequential
    already-flipped phase: record, flip, record again with a new
    release, the migration transaction finds authority='node' →
    refuse → attempt marked failed_before_commit."""
    fx = _seed_subtree(UID, prefix="c2-")
    subtree_id = fx["initiative_id"]
    barrier = threading.Barrier(2)
    outcomes = []

    def racer():
        barrier.wait(timeout=10)
        try:
            attempt_id = _fixture_prepare_flip(subtree_id)
            _fixture_flip_txn(
                S.get_connection(), subtree_id, attempt_id, UID
            )
            outcomes.append(("flipped", attempt_id))
        except Exception as exc:  # noqa: BLE001 - recorded for assert
            outcomes.append((type(exc).__name__, str(exc)))

    threads = [threading.Thread(target=racer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    flipped = [o for o in outcomes if o[0] == "flipped"]
    assert len(flipped) == 1, f"exactly one flip expected: {outcomes}"
    losers = [o for o in outcomes if o[0] != "flipped"]
    assert len(losers) == 1
    assert losers[0][0] in ("UnresolvedFlipAttempt", "AlreadyFlippedError"), (
        f"loser outcome: {losers[0]}"
    )
    conn = S.get_connection()
    events = [e for e, _ in _history_events(conn, subtree_id)]
    assert events.count("flip_committed") == 1
    assert _ledger(conn, subtree_id)["authority"] == "node"
    # If the loser recorded an attempt, the flip path marks it
    # failed_before_commit (a refused flip never leaves a `recorded`
    # attempt behind) — and a failed_before_commit attempt is still
    # unresolved (§8.2 block set) until the operator reconciles it,
    # so close each one to `reconciled` before asserting the list is
    # empty.
    unresolved = S.list_unresolved_attempts()
    for attempt in unresolved:
        S.mark_attempt_failed_before_commit(
            attempt["attempt_id"], "flip refused: subtree already flipped",
            "test",
        )
        S.close_attempt_reconciled(
            attempt["attempt_id"], "race loser: no flip performed", "test"
        )
    assert S.list_unresolved_attempts() == []

    # Sequential already-flipped phase (fresh subtree, same shape).
    fx2 = _seed_subtree(UID, prefix="c2b-")
    sub2 = fx2["initiative_id"]
    _fixture_flip(sub2, UID)
    attempt2 = _fixture_prepare_flip(sub2)
    with pytest.raises(AlreadyFlippedError):
        _fixture_flip_txn(S.get_connection(), sub2, attempt2, UID)
    S.mark_attempt_failed_before_commit(
        attempt2, "flip refused: subtree already flipped", "test"
    )
    assert S.get_flip_attempt(attempt2)["state"] == "failed_before_commit"
    assert _ledger(S.get_connection(), sub2)["authority"] == "node"


def test_t_c3_writer_blocked_then_refused_by_held_open_flip(ve_ctx):
    """T-C3: a legacy write issued while a flip transaction is held
    open blocks, then is refused after the flip commits — never
    SQLITE_BUSY within the 5 s busy_timeout."""
    fx = _seed_subtree(UID, prefix="c3-")
    subtree_id = fx["initiative_id"]
    attempt_id = _fixture_prepare_flip(subtree_id)
    started = threading.Event()
    outcome = {}

    def flip_thread():
        def hook():
            started.set()
            # FIXED short hold (1 s), not an event wait: the main
            # thread can only release the flip AFTER the writer
            # returns, and the writer blocks on BEGIN IMMEDIATE while
            # the flip holds — an event wait deadlocks into the 5 s
            # busy_timeout. The writer, issued while the flip holds,
            # blocks ~1 s, then proceeds after the flip commits and
            # is refused by the guard.
            time.sleep(1.0)

        _fixture_flip_txn(
            S.get_connection(), subtree_id, attempt_id, UID,
            pre_commit_hook=hook,
        )

    t = threading.Thread(target=flip_thread)
    t.start()
    assert started.wait(timeout=10), "flip never reached the hold"
    start = time.monotonic()
    with pytest.raises(S.MigratedNodeWriteRefused):
        S.update_task(fx["task_id"], M.TaskUpdate(title="too-late"), UID)
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, f"write took {elapsed:.2f}s (busy_timeout is 5s)"
    t.join(timeout=10)
    assert not t.is_alive()
    assert S.get_task(fx["task_id"], UID)["title"] != "too-late"


def test_t_c4_approve_racing_a_flip(ve_ctx, conv_store):
    """T-C4 (adapted — pinned finding): approve either creates the
    legacy task before the flip (and the flip migrates it) or is
    refused post-flip with MigratedNodeWriteRefused (C1a has no
    node-write path, so the D5 branch refuses rather than creating
    a node). Never both, never neither, never a task in the wrong
    representation."""
    # Approve first: the created task is inside the flipped subtree.
    fx = _seed_rich_fixture(UID, conv_store, prefix="c4a-")
    subtree_id = fx["initiative_id"]
    proposal_id = fx["proposal2_id"]
    out = S.approve_task_proposal(UID, proposal_id)
    assert out["task"]["id"]
    created_id = out["task"]["id"]
    flip = _fixture_flip(subtree_id, UID)
    conn = S.get_connection()
    doc = json.loads(
        S.compute_subtree_fingerprint(conn, subtree_id)["canonical_json"]
    )
    assert created_id in {n["id"] for n in doc["nodes"]}

    # Flip first: the approval is refused, no task created.
    fx2 = _seed_rich_fixture(UID, conv_store, prefix="c4b-")
    sub2 = fx2["initiative_id"]
    _fixture_flip(sub2, UID)
    before = _count(S.get_connection(), "tasks")
    with pytest.raises(S.MigratedNodeWriteRefused):
        S.approve_task_proposal(UID, fx2["proposal2_id"])
    assert _count(S.get_connection(), "tasks") == before
    assert S.get_flip_attempt(flip["attempt_id"])["state"] == "flipped"


def test_t_c5_writer_blocked_then_unblocked_by_held_open_flip(ve_ctx):
    """T-C5: a flip transaction is held open; a legacy write to an
    UNRELATED subtree blocks on the lock, then proceeds after the
    flip commits — never SQLITE_BUSY within the 5 s timeout."""
    fx = _seed_subtree(UID, prefix="c5a-")
    other = _seed_subtree(UID, prefix="c5b-")
    subtree_id = fx["initiative_id"]
    attempt_id = _fixture_prepare_flip(subtree_id)
    started = threading.Event()

    def flip_thread():
        def hook():
            started.set()
            # FIXED short hold (1 s) — see T-C3: an event wait
            # deadlocks against the writer's BEGIN IMMEDIATE block.
            time.sleep(1.0)

        _fixture_flip_txn(
            S.get_connection(), subtree_id, attempt_id, UID,
            pre_commit_hook=hook,
        )

    t = threading.Thread(target=flip_thread)
    t.start()
    assert started.wait(timeout=10), "flip never reached the hold"
    start = time.monotonic()
    out = S.update_task(
        other["task_id"], M.TaskUpdate(title="unrelated-write"), UID
    )
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, f"write took {elapsed:.2f}s"
    assert out["title"] == "unrelated-write"
    t.join(timeout=10)
    assert not t.is_alive()


def test_t_c6_writer_with_short_timeout_fails_cleanly(ve_ctx):
    """T-C6: same setup as T-C5, but the writer's connection uses
    busy_timeout=100. The write fails with SQLITE_BUSY after ~100
    ms; no partial write, no corruption, no half-committed state."""
    fx = _seed_subtree(UID, prefix="c6-")
    subtree_id = fx["initiative_id"]
    attempt_id = _fixture_prepare_flip(subtree_id)
    release = threading.Event()
    started = threading.Event()

    def flip_thread():
        def hook():
            started.set()
            release.wait(timeout=10)

        _fixture_flip_txn(
            S.get_connection(), subtree_id, attempt_id, UID,
            pre_commit_hook=hook,
        )

    t = threading.Thread(target=flip_thread)
    t.start()
    assert started.wait(timeout=10), "flip never reached the hold"
    outcome = {}

    def short_writer():
        # A connection with busy_timeout=100 on this thread: pre-seed
        # the thread-local cache so get_connection() returns it.
        db_path = ve_ctx["db_path"]
        conn = sqlite3.connect(str(db_path), check_same_thread=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=100")
        S._thread_local.conn = conn
        S._thread_local.db_path_resolved = str(db_path.resolve())
        start = time.monotonic()
        try:
            S.update_task(
                fx["task_id"], M.TaskUpdate(title="short-timeout"), UID
            )
            outcome["result"] = "ok"
        except Exception as exc:  # noqa: BLE001 - recorded for assert
            outcome["result"] = type(exc).__name__
            outcome["detail"] = str(exc)
        outcome["elapsed"] = time.monotonic() - start
        conn.close()

    w = threading.Thread(target=short_writer)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    release.set()
    t.join(timeout=10)
    assert outcome["result"] == "OperationalError", outcome
    assert "database is locked" in outcome["detail"]
    assert outcome["elapsed"] < 1.0, f"took {outcome['elapsed']:.2f}s"
    assert S.get_task(fx["task_id"], UID)["title"] != "short-timeout"
    # No corruption: the DB still answers reads and the flip landed.
    assert _ledger(S.get_connection(), subtree_id)["authority"] == "node"


def test_t_c7_readers_proceed_during_held_open_flip(ve_ctx):
    """T-C7: a read (get_task / list_tasks) issued while a flip
    transaction is held open returns under WAL read concurrency —
    it does not block on the writer's lock."""
    fx = _seed_subtree(UID, prefix="c7-")
    subtree_id = fx["initiative_id"]
    attempt_id = _fixture_prepare_flip(subtree_id)
    release = threading.Event()
    started = threading.Event()

    def flip_thread():
        def hook():
            started.set()
            release.wait(timeout=10)

        _fixture_flip_txn(
            S.get_connection(), subtree_id, attempt_id, UID,
            pre_commit_hook=hook,
        )

    t = threading.Thread(target=flip_thread)
    t.start()
    assert started.wait(timeout=10), "flip never reached the hold"
    start = time.monotonic()
    task = S.get_task(fx["task_id"], UID)
    listed = S.list_tasks(user_id=UID)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"read blocked {elapsed:.2f}s on the flip"
    assert task is not None and task["id"] == fx["task_id"]
    assert any(row["id"] == fx["task_id"] for row in listed)
    release.set()
    t.join(timeout=10)
    assert not t.is_alive()


def test_t_c8_flip_duration_bounded_by_subtree_size(ve_ctx):
    """T-C8: flip fixture subtrees of 1, 23, and 200 nodes; the
    helper transaction's hold time (including the in-transaction
    fingerprint) stays well under the 5 s busy_timeout for the
    C2-sized subtree (23 tasks). Growth is pinned by the canonical
    document size (deterministic), not by wall-clock ordering."""
    timings = {}
    sizes = {}
    for n in (1, 23, 200):
        fx = _seed_subtree(UID, n_tasks=n, prefix=f"c8-{n}-")
        subtree_id = fx["initiative_id"]
        attempt_id = _fixture_prepare_flip(subtree_id)
        conn = S.get_connection()
        start = time.monotonic()
        result = _fixture_flip_txn(conn, subtree_id, attempt_id, UID)
        timings[n] = time.monotonic() - start
        sizes[n] = len(result["canonical_json"])
        assert timings[n] < 5.0, f"{n}-node flip took {timings[n]:.2f}s"
    assert sizes[1] < sizes[23] < sizes[200]
    assert timings[23] < 5.0


def test_t_c9_explicit_busy_failure_surfaces_as_500(ve_ctx):
    """T-C9 [NEW]: a write that times out on the lock, driven through
    the API test client (real app + TestClient). The response is 500
    with {"detail": "database is locked"} (§12.3); the database is
    unchanged (no partial write). Proves the busy failure is
    explicit, clean, and distinguishable from a domain refusal
    (409/423)."""
    from fastapi.testclient import TestClient

    from api.main import app
    from api.routes.auth_routes import get_current_user

    db_path = ve_ctx["db_path"]
    fx = _seed_subtree(UID, prefix="c9-")
    project_id = fx["project_id"]
    before = _count(S.get_connection(), "tasks")
    app.dependency_overrides[get_current_user] = lambda: {
        "id": UID, "email": "u1@x", "display_name": "U1",
    }
    try:
        client = TestClient(app, raise_server_exceptions=False)
        # Warm up first: initializes the DB + the app's thread-local
        # connection BEFORE the lock is taken.
        warm = client.get("/vision-execution/ideas")
        assert warm.status_code == 200, warm.text
        # Hold the write lock with a raw connection.
        raw = _raw(db_path)
        raw.execute("BEGIN IMMEDIATE")
        try:
            start = time.monotonic()
            resp = client.post(
                "/vision-execution/tasks",
                json={
                    "project_id": project_id,
                    "title": "blocked-write",
                    "status": "Todo",
                },
            )
            elapsed = time.monotonic() - start
        finally:
            raw.rollback()
            raw.close()
        assert elapsed >= 4.0, f"busy wait too short: {elapsed:.2f}s"
        assert elapsed < 10.0, f"busy wait too long: {elapsed:.2f}s"
        assert resp.status_code == 500, resp.text
        assert resp.json() == {"detail": "database is locked"}, resp.text
        assert _count(S.get_connection(), "tasks") == before
    finally:
        app.dependency_overrides.pop(get_current_user, None)

# ---------------------------------------------------------------------------
# 16.2 Guard tests (write-authority refusal)
# ---------------------------------------------------------------------------


def test_t_g1_every_writer_refused_on_flipped_subtree(ve_ctx, conv_store):
    """T-G1: every writer class (§15.7) attempts a write to a flipped
    subtree's legacy row. Every attempt is refused fail-closed with
    MigratedNodeWriteRefused; nothing written; the ledger unchanged
    (no new history except the refusal records)."""
    fx = _seed_rich_fixture(UID, conv_store, prefix="g1-")
    subtree_id = fx["initiative_id"]
    flip = _fixture_flip(subtree_id, UID)
    conn = S.get_connection()
    history_before = _history_events(conn, subtree_id)
    outcomes = _run_writes(_all_writes(fx, conv_store))
    assert set(outcomes) == {
        "update_idea", "create_checklist_item", "update_checklist_item",
        "add_checklist_dependency", "remove_checklist_dependency",
        "mark_checklist_superseded", "update_initiative",
        "create_execution_step", "update_execution_step",
        "materialize_execution_steps", "reorder_execution_steps",
        "create_project", "update_project", "create_task", "update_task",
        "record_task_proposal", "update_task_proposal",
        "approve_task_proposal", "delete_idea", "delete_checklist_item",
        "delete_execution_step", "delete_initiative", "delete_project",
        "delete_task",
    }, set(outcomes)
    for name, (kind, detail) in outcomes.items():
        assert kind == "MigratedNodeWriteRefused", f"{name}: {kind} {detail}"
        assert subtree_id in (detail or ""), f"{name}: subtree not named"
    # Nothing written: the legacy rows are exactly as seeded.
    assert S.get_task(fx["task_id"], UID)["title"] == "g1-task-0"
    assert S.get_idea(fx["idea_id"], UID)["title"] == "g1-idea"
    assert S.get_project(fx["project_id"], UID)["title"] == "g1-project"
    # The ledger's authority/fingerprint are untouched by refusals.
    ledger = _ledger(conn, subtree_id)
    assert ledger["authority"] == "node"
    assert ledger["fingerprint_sha256"] == flip["fingerprint_sha256"]
    # Every refusal is recorded exactly once in history.
    refused = [e for e, _ in _history_events(conn, subtree_id)
               if e == "write_refused"]
    assert len(refused) == len(outcomes)


def test_t_g2_every_writer_succeeds_on_unflipped_subtree(ve_ctx, conv_store):
    """T-G2: the same writer classes against an unflipped subtree.
    Every attempt succeeds; the rows are written; the ledger records
    no refusal. (Each write runs against a fresh fixture: the
    destructive writes would otherwise destroy the fixture for the
    next write. delete_project uses an empty project — §6 refuses
    a taskful project even unflipped.)"""
    for name, _thunk in _all_writes(
        _seed_rich_fixture(UID, conv_store, prefix="g2-"), conv_store
    ):
        fx = _seed_rich_fixture(UID, conv_store, prefix="g2-")
        writes = dict(_all_writes(fx, conv_store))
        if name == "delete_project":
            # The §6 guard refuses a taskful project even unflipped;
            # T-D2 pins the empty-project delete. Use an empty
            # project here so the write itself is the thing tested.
            empty = S.create_project(
                M.ProjectCreate(initiative_id=fx["initiative_id"],
                                title="g2-empty", status="Active"), UID)
            writes[name] = lambda: S.delete_project(empty["id"], UID)
        kind, detail = _run_writes([(name, writes[name])])[name]
        assert kind == "ok", f"{name}: {kind} {detail}"
    conn = S.get_connection()
    refused = [e for e, _ in _history_events(conn) if e == "write_refused"]
    assert refused == []


def test_t_g3_root_create_against_flipped_subtree_scope(ve_ctx):
    """T-G3 (proceed half — pinned finding): a root create (no
    parent, no project) is a legacy write per §5.1 step 1, so it
    proceeds even while a subtree is flipped. The refusal half —
    refusing a root create that belongs to the flipped subtree's
    scope — has no rule in the brief (the root-assignment rule is a
    C1b census decision), so it is recorded here as an open
    question, not asserted."""
    fx = _seed_subtree(UID, prefix="g3-")
    _fixture_flip(fx["initiative_id"], UID)
    task = S.create_task(
        M.TaskCreate(project_id=None, parent_task_id=None,
                     title="root-task", status="Todo"), UID)
    assert task["id"]
    assert S.get_task(task["id"], UID)["title"] == "root-task"
    # OPEN QUESTION (brief §16.2 T-G3): no rule states when a root
    # create belongs to a flipped subtree's scope. C1b's census
    # decides; until then the proceed half is the implemented rule.


def test_t_g4_child_write_naming_flipped_parent_refused(ve_ctx):
    """T-G4: a checklist-item / execution-step write naming a flipped
    parent is refused — the parent's subtree governs the child — and
    the refusal names the parent's subtree."""
    fx = _seed_subtree(UID, prefix="g4-")
    subtree_id = fx["initiative_id"]
    _fixture_flip(subtree_id, UID)
    with pytest.raises(S.MigratedNodeWriteRefused) as excinfo:
        S.create_checklist_item(UID, fx["idea_id"], "child-of-flipped")
    assert subtree_id in str(excinfo.value)
    assert excinfo.value.subtree_id == subtree_id
    with pytest.raises(S.MigratedNodeWriteRefused) as excinfo:
        S.create_execution_step(
            UID, S.EXECUTION_STEPS_SCOPE_INITIATIVE, subtree_id,
            "child-step", None)
    assert excinfo.value.subtree_id == subtree_id
    with pytest.raises(S.MigratedNodeWriteRefused) as excinfo:
        S.update_execution_step(fx["step_id"], UID, {"title": "x"})
    assert excinfo.value.subtree_id == subtree_id


def test_t_fz1_frozen_subtree_legacy_write(ve_ctx, conv_store):
    """T-FZ1 [NEW]: a flipped subtree whose attempt is
    failed_after_commit is write-frozen. Every legacy write is
    refused with SubtreeWriteFrozen (423), NOT
    MigratedNodeWriteRefused — the freeze is diagnosable by the
    error alone (§10.2)."""
    fx = _seed_rich_fixture(UID, conv_store, prefix="fz1-")
    subtree_id = fx["initiative_id"]
    flip = _fixture_flip(subtree_id, UID)
    S.record_verification_result(
        flip["attempt_id"], False, "post-commit census mismatch", "test"
    )
    assert S.get_flip_attempt(flip["attempt_id"])["state"] == (
        "failed_after_commit"
    )
    outcomes = _run_writes(_all_writes(fx, conv_store))
    for name, (kind, detail) in outcomes.items():
        assert kind == "SubtreeWriteFrozen", f"{name}: {kind} {detail}"
        assert subtree_id in (detail or ""), f"{name}: subtree not named"
    conn = S.get_connection()
    frozen_refusals = [
        e for e, _ in _history_events(conn, subtree_id)
        if e == "write_frozen_refusal"
    ]
    assert len(frozen_refusals) == len(outcomes)


def test_t_fz2_frozen_subtree_node_write_and_unrelated_subtree(ve_ctx):
    """T-FZ2 [NEW]: the freeze blocks node writes too, and does not
    leak to other subtrees. A node write via the fixture helper is
    refused with SubtreeWriteFrozen; a legacy write to an unrelated
    unflipped subtree succeeds (§10.1)."""
    fx = _seed_subtree(UID, prefix="fz2a-")
    other = _seed_subtree(UID, prefix="fz2b-")
    subtree_id = fx["initiative_id"]
    flip = _fixture_flip(subtree_id, UID)
    S.record_verification_result(
        flip["attempt_id"], False, "post-commit census mismatch", "test"
    )
    conn = S.get_connection()
    # Node write to the frozen subtree: refused with the freeze.
    doc = json.loads(flip["canonical_json"])
    form = dict(doc["nodes"][0])
    form["id"] = M.new_id()
    form["title"] = "frozen-node-write"
    with S.ve_write_transaction(conn, purpose="fz2-node-write"):
        with pytest.raises(S.SubtreeWriteFrozen):
            _fixture_insert_node(conn, subtree_id, form, UID)
    # Legacy write to the unrelated unflipped subtree: succeeds.
    out = S.update_task(
        other["task_id"], M.TaskUpdate(title="unrelated-ok"), UID
    )
    assert out["title"] == "unrelated-ok"


def test_t_d1_delete_project_with_tasks_refused(ve_ctx):
    """T-D1 [NEW]: delete_project with N tasks is refused with
    ProjectHasTasks (409, detail names N); nothing deleted; the
    ledger records the refusal (§6)."""
    fx = _seed_subtree(UID, n_tasks=3, prefix="d1-")
    project_id = fx["project_id"]
    conn = S.get_connection()
    with pytest.raises(S.ProjectHasTasks) as excinfo:
        S.delete_project(project_id, UID)
    assert excinfo.value.task_count == 3
    assert excinfo.value.project_id == project_id
    assert "3" in str(excinfo.value)
    assert S.get_project(project_id, UID) is not None
    assert _count(conn, "tasks", "WHERE project_id = ?", (project_id,)) == 3
    events = [e for e, _ in _history_events(conn)]
    assert "write_refused" in events


def test_t_d2_delete_project_empty_succeeds(ve_ctx):
    """T-D2 [NEW]: delete_project with zero tasks deletes (steps +
    project row), as today."""
    fx = _seed_subtree(UID, prefix="d2-")
    empty = S.create_project(
        M.ProjectCreate(initiative_id=fx["initiative_id"], title="empty",
                        status="Active"), UID)
    step = S.create_execution_step(
        UID, S.EXECUTION_STEPS_SCOPE_PROJECT, empty["id"], "doomed", None)
    assert S.delete_project(empty["id"], UID) is True
    assert S.get_project(empty["id"], UID) is None
    assert S.get_execution_step(step["id"], UID) is None
    # The taskful project is untouched.
    assert S.get_project(fx["project_id"], UID) is not None


# ---------------------------------------------------------------------------
# 16.3 Transaction ownership
# ---------------------------------------------------------------------------


def test_t_o1_only_the_owner_commits(ve_ctx):
    """T-O1: a guarded write inside a helper transaction is visible
    only inside the transaction until the owner commits; the inner
    commit is a no-op."""
    conn = S.get_connection()
    fx = _seed_subtree(UID, prefix="o1-")
    other = _raw(ve_ctx["db_path"])
    try:
        with S.ve_write_transaction(conn, purpose="t_o1") as handle:
            assert handle.is_owner
            task = S.create_task(
                M.TaskCreate(project_id=fx["project_id"], title="o1-task",
                             status="Todo"), UID)
            # Visible on this connection (same transaction)...
            assert S.get_task(task["id"], UID) is not None
            # ...but not from another connection until the owner
            # commits.
            row = other.execute(
                "SELECT id FROM tasks WHERE id = ?", (task["id"],)
            ).fetchone()
            assert row is None
        # After the owner's clean exit: committed, visible everywhere.
        row = other.execute(
            "SELECT id FROM tasks WHERE id = ?", (task["id"],)
        ).fetchone()
        assert row is not None
    finally:
        other.close()


def test_t_o2_inner_function_cannot_prematurely_commit(ve_ctx):
    """T-O2: inside a helper transaction, a converted CRUD function's
    commit path is exercised — the transaction is still open
    afterwards (conn.in_transaction), and the half-finished state is
    not visible to another connection."""
    conn = S.get_connection()
    fx = _seed_subtree(UID, prefix="o2-")
    other = _raw(ve_ctx["db_path"])
    try:
        with S.ve_write_transaction(conn, purpose="t_o2"):
            task = S.create_task(
                M.TaskCreate(project_id=fx["project_id"], title="o2-task",
                             status="Todo"), UID)
            assert conn.in_transaction
            row = other.execute(
                "SELECT id FROM tasks WHERE id = ?", (task["id"],)
            ).fetchone()
            assert row is None
        assert S.get_task(task["id"], UID) is not None
    finally:
        other.close()


def test_t_o3_inner_function_cannot_roll_back_callers_transaction(ve_ctx,
                                                                  conv_store):
    """T-O3: the approve path's rowcount==0 branch, called nested
    inside a helper transaction, must not roll back the caller's
    transaction. The nested rollback raises; the error propagates to
    the owner, which rolls back the whole transaction."""
    fx = _seed_rich_fixture(UID, conv_store, prefix="o3-")
    # Approve the proposal once, so a second approval hits the
    # rowcount==0 branch.
    S.approve_task_proposal(UID, fx["proposal2_id"])
    conn = S.get_connection()
    with pytest.raises(RuntimeError, match="nested _rollback_if_owner"):
        with S.ve_write_transaction(conn, purpose="t_o3"):
            task = S.create_task(
                M.TaskCreate(project_id=fx["project_id"], title="o3-task",
                             status="Todo"), UID)
            assert conn.in_transaction
            # The inner approve hits rowcount==0; its rollback is
            # nested, so it raises instead of rolling back.
            S.approve_task_proposal(UID, fx["proposal2_id"])
    # The owner rolled back the WHOLE transaction on the error: the
    # task written before the inner failure is gone.
    assert S.get_task(task["id"], UID) is None


# The class-A function names (§15.1) — the T-O4 / T-O4d AST checks use
# this list, not a hardcoded copy of the brief's table.
_CLASS_A = (
    "create_idea", "update_idea", "delete_idea",
    "create_checklist_item", "update_checklist_item",
    "delete_checklist_item", "add_checklist_dependency",
    "remove_checklist_dependency", "mark_checklist_superseded",
    "create_initiative", "update_initiative", "delete_initiative",
    "create_execution_step", "update_execution_step",
    "delete_execution_step", "materialize_execution_steps",
    "reorder_execution_steps",
    "create_project", "update_project", "delete_project",
    "create_task", "update_task", "delete_task",
    "record_task_proposal", "update_task_proposal",
    "approve_task_proposal",
)


def _parse_storage_ast():
    path = REPO_ROOT / "local_ai" / "vision_execution" / "storage.py"
    return ast.parse(path.read_text(), filename=str(path))


def _called_names(node):
    """All plain function names called anywhere under ``node``."""
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _calls_inside_helper(fn_node):
    """Function names called inside a `with ve_write_transaction`
    block in this function."""
    names = set()
    for child in ast.walk(fn_node):
        if not isinstance(child, ast.With):
            continue
        is_helper = any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Name)
            and item.context_expr.func.id == "ve_write_transaction"
            for item in child.items
        )
        if is_helper:
            names |= _called_names(child)
    return names


def _functions_with_bare_commit(tree):
    """Functions whose body contains a bare `conn.commit()` call —
    the class C/D set (§15.3/§15.4), derived from the code rather
    than a hardcoded list."""
    out = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "commit"
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "conn"
            ):
                out.add(node.name)
                break
    return out


def test_t_o4_static_call_graph_no_new_nesting_path():
    """T-O4: (a) no storage CRUD function calls another storage CRUD
    function; (b) no class C/D function is called from inside a
    helper transaction; (c) no migration function is called from
    inside a helper transaction. Fails the suite if any new nesting
    path appears."""
    tree = _parse_storage_ast()
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    # (a) No class-A function calls another class-A function. The
    # designed exception is the shared private `_insert_task`
    # (create_task / approve_task_proposal both use it) — it is not
    # a class-A function, so it does not appear here.
    for name in _CLASS_A:
        called = _called_names(functions[name])
        others = (set(_CLASS_A) - {name}) & called
        assert not others, f"{name} calls class-A: {sorted(others)}"
    # (b) + (c) No class C/D (bare-commit) or migration function is
    # called from inside a helper transaction, anywhere in the file.
    # The two sanctioned exceptions are the helper itself (re-entrant
    # nesting is the designed entry) and `_commit_if_owner` (the only
    # commit path allowed inside a helper).
    bare_commit = _functions_with_bare_commit(tree)
    migrations = {
        name for name in functions if name.startswith("_migrate_")
    }
    forbidden = (bare_commit | migrations) - {
        "ve_write_transaction", "_commit_if_owner",
    }
    for name, node in functions.items():
        inside = _calls_inside_helper(node)
        bad = inside & forbidden
        assert not bad, f"{name} calls {sorted(bad)} inside a helper"


def test_t_o4d_static_post_commit_effects_outside_helper():
    """T-O4d [NEW]: no call to `_log_ve_entity_activity`,
    `upsert_node_vitality`, or `append_node_judgment` occurs inside
    a `with ve_write_transaction` block (§4.4). Also: approve is
    never nested (no `approve_task_proposal` call inside a helper
    block, in storage or the service layer)."""
    tree = _parse_storage_ast()
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    effects = {
        "_log_ve_entity_activity",
        "upsert_node_vitality",
        "append_node_judgment",
    }
    for name, node in functions.items():
        inside = _calls_inside_helper(node)
        bad = inside & effects
        assert not bad, f"{name} calls {sorted(bad)} inside a helper"
        assert "approve_task_proposal" not in inside, (
            f"{name} calls approve_task_proposal inside a helper"
        )
    # The service layer never wraps a call in a helper either (§4.5).
    service_path = (
        REPO_ROOT / "local_ai" / "vision_execution" / "service.py"
    )
    service_tree = ast.parse(
        service_path.read_text(), filename=str(service_path)
    )
    for node in ast.walk(service_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "ve_write_transaction", (
                "service.py must not open a helper transaction (§4.5)"
            )
    # Class B (signals): ownership-only — no helper, no guard.
    signals_path = REPO_ROOT / "local_ai" / "signals" / "storage.py"
    signals_src = signals_path.read_text()
    assert "ve_write_transaction" not in signals_src
    assert "_guard_" not in signals_src
    assert "V._commit_if_owner(conn)" in signals_src

# ---------------------------------------------------------------------------
# 16.4 Crash windows (+ the subprocess worker for T-X1 / T-X2)
# ---------------------------------------------------------------------------

_SUBPROCESS_SCRIPT = '''\
"""C1a test worker (subprocess): flip-hold (T-X1) and try-record
(T-X2 / T-PA2 / T-PA5). Run by the test with the repo root as argv[1].
Imports this test module for the fixture flip — the flip logic lives
in exactly one place (the test file)."""
import json
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(sys.argv[1])
sys.path.insert(0, str(REPO_ROOT))

import tests.test_c1a_write_authority as T
import local_ai.vision_execution.storage as S


def main():
    mode = sys.argv[2]
    db_path = Path(sys.argv[3])
    S._DB_PATH = db_path
    S._DB_DIR = db_path.parent
    S._thread_local = threading.local()
    if mode == "flip_hold":
        subtree_id, user_id, marker = sys.argv[4], sys.argv[5], sys.argv[6]
        attempt_id = T._fixture_prepare_flip(subtree_id)
        conn = S.get_connection()

        def hook():
            Path(marker).write_text("inside-flip", encoding="utf-8")
            time.sleep(120)  # the parent kills us while we hold the lock

        T._fixture_flip_txn(
            conn, subtree_id, attempt_id, user_id, pre_commit_hook=hook
        )
        print(json.dumps({"outcome": "flipped", "attempt_id": attempt_id}))
    elif mode == "try_record":
        subtree_id = sys.argv[4]
        try:
            S.release_migration_pause_for_subtree(
                subtree_id, "auth-test", "test"
            )
            attempt = S.record_flip_attempt(subtree_id, "auth-test", "test")
            print(json.dumps(
                {"outcome": "recorded", "attempt_id": attempt["attempt_id"]}
            ))
        except Exception as exc:  # noqa: BLE001 - reported as JSON
            print(json.dumps(
                {"outcome": type(exc).__name__, "detail": str(exc)}
            ))
    elif mode == "try_record_norelease":
        subtree_id = sys.argv[4]
        try:
            attempt = S.record_flip_attempt(subtree_id, "auth-test", "test")
            print(json.dumps(
                {"outcome": "recorded", "attempt_id": attempt["attempt_id"]}
            ))
        except Exception as exc:  # noqa: BLE001 - reported as JSON
            print(json.dumps(
                {"outcome": type(exc).__name__, "detail": str(exc)}
            ))
    else:
        raise ValueError(f"unknown mode {mode!r}")


main()
'''


def _write_worker_script(tmp_path):
    script = tmp_path / "c1a_flip_worker.py"
    script.write_text(_SUBPROCESS_SCRIPT, encoding="utf-8")
    return script


def _run_worker(script, *args, timeout=30):
    proc = subprocess.Popen(
        [sys.executable, str(script), str(REPO_ROOT), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise AssertionError(
            f"worker timed out after {timeout}s\nstdout: {out}\nstderr: {err}"
        )
    assert proc.returncode == 0, (
        f"worker rc={proc.returncode}\nstdout: {out}\nstderr: {err}"
    )
    return json.loads(out.strip().splitlines()[-1])


def test_t_x1_kill_process_mid_flip(ve_ctx, tmp_path):
    """T-X1: a subprocess performs a flip with a test hook that pauses
    between the attempt commit and the flip commit; the parent kills
    the subprocess at that point. The attempt stays `recorded`; the
    subtree authority is unchanged (legacy); no node rows are
    half-written; no further flip proceeds after restart (T-PA5)."""
    fx = _seed_subtree(UID, prefix="x1-")
    subtree_id = fx["initiative_id"]
    script = _write_worker_script(tmp_path)
    marker = tmp_path / "inside-flip.marker"
    proc = subprocess.Popen(
        [sys.executable, str(script), str(REPO_ROOT), "flip_hold",
         str(ve_ctx["db_path"]), subtree_id, UID, str(marker)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 30
        while not marker.exists():
            if proc.poll() is not None:
                out, err = proc.communicate()
                raise AssertionError(
                    f"worker exited early rc={proc.returncode}\n{out}\n{err}"
                )
            assert time.monotonic() < deadline, (
                "worker never reached the flip hold"
            )
            time.sleep(0.1)
        # The attempt is committed (recorded) and the flip txn is open.
        attempts = S.list_unresolved_attempts()
        assert len(attempts) == 1
        assert attempts[0]["state"] == "recorded"
        attempt_id = attempts[0]["attempt_id"]
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
    conn = S.get_connection()
    assert S.get_flip_attempt(attempt_id)["state"] == "recorded"
    assert _ledger(conn, subtree_id) is None
    assert _count(conn, "nodes") == 0
    assert _count(conn, "node_seats") == 0
    with pytest.raises(S.UnresolvedFlipAttempt):
        _fixture_prepare_flip(subtree_id)


def test_t_x2_restart_with_unresolved_attempt(ve_ctx, tmp_path):
    """T-X2: a test database holds a `recorded` attempt; a fresh
    process opens it and attempts a flip (same subtree and a
    different subtree). Both flips are refused (global block for
    `recorded`). The attempt record survives the restart — it is a
    committed ledger row, not process state."""
    fx = _seed_subtree(UID, prefix="x2a-")
    other = _seed_subtree(UID, prefix="x2b-")
    attempt_id = _fixture_prepare_flip(fx["initiative_id"])
    script = _write_worker_script(tmp_path)
    for subtree_id in (fx["initiative_id"], other["initiative_id"]):
        result = _run_worker(
            script, "try_record", str(ve_ctx["db_path"]), subtree_id
        )
        assert result["outcome"] == "UnresolvedFlipAttempt", result
    assert S.get_flip_attempt(attempt_id)["state"] == "recorded"


def test_t_x3_failure_before_flip_commit(ve_ctx):
    """T-X3: a flip whose required check fails before commit (census
    mismatch injected). The migration transaction rolls back
    (subtree unchanged, legacy authority); the attempt is
    `failed_before_commit` in a post-rollback transaction; the pause
    is engaged; a retry is refused until recovery review closes the
    attempt."""
    fx = _seed_subtree(UID, prefix="x3-")
    subtree_id = fx["initiative_id"]
    attempt_id = _fixture_prepare_flip(subtree_id)
    conn = S.get_connection()
    with pytest.raises(_FixtureFlipCheckFailed):
        _fixture_flip_txn(
            conn, subtree_id, attempt_id, UID, fail_before_commit=True
        )
    assert _ledger(conn, subtree_id) is None
    assert _count(conn, "nodes") == 0
    S.mark_attempt_failed_before_commit(
        attempt_id, "census mismatch (injected)", "test"
    )
    assert S.get_flip_attempt(attempt_id)["state"] == "failed_before_commit"
    assert S.migration_pause_status()["state"] == "paused"
    with pytest.raises(S.UnresolvedFlipAttempt):
        _fixture_prepare_flip(subtree_id)
    S.close_attempt_reconciled(
        attempt_id, "reviewed: census mismatch was a bad fixture", "test"
    )
    attempt2 = _fixture_prepare_flip(subtree_id)
    assert S.get_flip_attempt(attempt2)["state"] == "recorded"


def test_t_x4_failure_after_flip_commit(ve_ctx):
    """T-X4: a flip commits, then a post-commit verification fails
    (injected census mismatch after commit). Node authority is
    preserved (never reversed automatically); the pause is engaged;
    the subtree is write-frozen (§10); recovery review is required.
    The attempt row + status name the failed check (the C1a half of
    the R-D3 diagnostics; the C1b minimal-diagnostics surface is
    out of scope)."""
    fx = _seed_subtree(UID, prefix="x4-")
    subtree_id = fx["initiative_id"]
    flip = _fixture_flip(subtree_id, UID)
    out = S.record_verification_result(
        flip["attempt_id"], False, "census mismatch: node count 5 != 6",
        "test",
    )
    assert out["state"] == "failed_after_commit"
    assert "census mismatch" in (out["failure_detail"] or "")
    assert _ledger(S.get_connection(), subtree_id)["authority"] == "node"
    assert S.migration_pause_status()["state"] == "paused"
    with pytest.raises(S.SubtreeWriteFrozen):
        S.update_task(fx["task_id"], M.TaskUpdate(title="x"), UID)
    unresolved = S.list_unresolved_attempts()
    assert any(
        a["attempt_id"] == flip["attempt_id"] for a in unresolved
    )


def test_t_x5_uncertain_outcome_reconciled_by_inspection(ve_ctx):
    """T-X5: (a) a `recorded` attempt with the ledger authority row
    showing `node` (flip committed, process died before the test
    could observe it) is treated as failure-after-commit; (b) a
    `recorded` attempt with the authority row showing `legacy` is
    marked `failed_before_commit`. Neither auto-retries, reverses
    authority, or assumes the flip failed."""
    fx = _seed_subtree(UID, prefix="x5a-")
    sub_a = fx["initiative_id"]
    att_a = _fixture_prepare_flip(sub_a)
    _fixture_flip_txn(
        S.get_connection(), sub_a, att_a, UID, mark_attempt=False
    )
    result = S.determine_recorded_attempt(att_a, "test")
    assert result["determination"] == "failed_after_commit"
    assert S.get_flip_attempt(att_a)["state"] == "failed_after_commit"
    assert _ledger(S.get_connection(), sub_a)["authority"] == "node"

    fx2 = _seed_subtree(UID, prefix="x5b-")
    sub_b = fx2["initiative_id"]
    att_b = _fixture_prepare_flip(sub_b)
    result = S.determine_recorded_attempt(att_b, "test")
    assert result["determination"] == "failed_before_commit"
    assert S.get_flip_attempt(att_b)["state"] == "failed_before_commit"
    assert _ledger(S.get_connection(), sub_b) is None


def test_t_rc1_recovery_procedure_end_to_end(ve_ctx):
    """T-RC1 [NEW]: the §9 procedure, end to end, on three fixture
    states. (a) `recorded` + authority `legacy` + no flip event →
    determined `failed_before_commit`, closed `reconciled`. (b)
    `recorded` + authority `node` + flip event → determined
    `failed_after_commit`, subtree frozen, closed `reconciled`.
    (c) `recorded` + authority `node` + no flip event
    (inconsistent) → the procedure stops at Step 4: no marking, no
    engagement, attempt stays `recorded`, a `recovery_blocked`
    history entry is written. Proves §9.4."""
    conn = S.get_connection()

    # (a) recorded + legacy + no flip event.
    fx_a = _seed_subtree(UID, prefix="rc1a-")
    att_a = _fixture_prepare_flip(fx_a["initiative_id"])
    result = S.determine_recorded_attempt(att_a, "test")
    assert result["determination"] == "failed_before_commit"
    out = S.close_attempt_reconciled(
        att_a, "flip did not commit; safe to retry", "test"
    )
    assert out["state"] == "reconciled"
    assert out["resolution"] == "flip did not commit; safe to retry"

    # (b) recorded + node + flip event.
    fx_b = _seed_subtree(UID, prefix="rc1b-")
    sub_b = fx_b["initiative_id"]
    att_b = _fixture_prepare_flip(sub_b)
    _fixture_flip_txn(conn, sub_b, att_b, UID, mark_attempt=False)
    result = S.determine_recorded_attempt(att_b, "test")
    assert result["determination"] == "failed_after_commit"
    with pytest.raises(S.SubtreeWriteFrozen):
        S.update_task(fx_b["task_id"], M.TaskUpdate(title="x"), UID)
    out = S.close_attempt_reconciled(
        att_b, "leave flipped; node authority stands", "test"
    )
    assert out["state"] == "reconciled"

    # (c) recorded + node + NO flip event (inconsistent).
    fx_c = _seed_subtree(UID, prefix="rc1c-")
    sub_c = fx_c["initiative_id"]
    att_c = _fixture_prepare_flip(sub_c)
    _fixture_flip_txn(
        conn, sub_c, att_c, UID, mark_attempt=False, write_flip_event=False
    )
    result = S.determine_recorded_attempt(att_c, "test")
    assert result["determination"] == "inconsistent"
    assert S.get_flip_attempt(att_c)["state"] == "recorded"
    assert _ledger(conn, sub_c)["authority"] == "node"
    events = [e for e, _ in _history_events(conn, sub_c)]
    assert "recovery_blocked" in events
    # Nothing was engaged or marked: the pause state is whatever it
    # was, and the attempt is still unresolved.
    assert S.get_flip_attempt(att_c) in S.list_unresolved_attempts()


# ---------------------------------------------------------------------------
# 16.5 Pause
# ---------------------------------------------------------------------------


def test_t_pa1_fresh_database_paused_by_default(ve_ctx):
    """T-PA1: a fresh database starts PAUSED; a flip attempt is
    refused with MigrationPaused."""
    status = S.migration_pause_status()
    assert status["state"] == "paused"
    fx = _seed_subtree(UID, prefix="pa1-")
    with pytest.raises(S.MigrationPaused):
        S.record_flip_attempt(fx["initiative_id"], "auth-test", "test")


def test_t_pa2_failed_check_engages_pause_durably(ve_ctx, tmp_path):
    """T-PA2: a failed required check during a flip attempt engages
    the pause durably (via the flip-attempt record in a
    post-rollback transaction). A subsequent flip attempt is refused
    until an explicit unpause — from this process and from a fresh
    process."""
    fx = _seed_subtree(UID, prefix="pa2-")
    subtree_id = fx["initiative_id"]
    attempt_id = _fixture_prepare_flip(subtree_id)
    conn = S.get_connection()
    with pytest.raises(_FixtureFlipCheckFailed):
        _fixture_flip_txn(
            conn, subtree_id, attempt_id, UID, fail_before_commit=True
        )
    S.mark_attempt_failed_before_commit(
        attempt_id, "census mismatch (injected)", "test"
    )
    assert S.migration_pause_status()["state"] == "paused"
    # No release → MigrationPaused (the pause is engaged).
    with pytest.raises(S.MigrationPaused):
        S.record_flip_attempt(subtree_id, "auth-test", "test")
    # Fresh process, same file, no release → MigrationPaused too.
    script = _write_worker_script(tmp_path)
    result = _run_worker(
        script, "try_record_norelease", str(ve_ctx["db_path"]), subtree_id
    )
    assert result["outcome"] == "MigrationPaused", result
    # A release exists but the failed_before_commit attempt blocks
    # this subtree until it is reconciled.
    with pytest.raises(S.UnresolvedFlipAttempt):
        _fixture_prepare_flip(subtree_id)
    S.close_attempt_reconciled(attempt_id, "reviewed", "test")
    attempt2 = _fixture_prepare_flip(subtree_id)
    assert S.get_flip_attempt(attempt2)["state"] == "recorded"


def test_t_pa3_unpause_scoped_to_one_subtree(ve_ctx):
    """T-PA3: an unpause (release) scoped to one subtree does not
    authorize a flip on a different subtree."""
    fx_a = _seed_subtree(UID, prefix="pa3a-")
    fx_b = _seed_subtree(UID, prefix="pa3b-")
    S.release_migration_pause_for_subtree(
        fx_a["initiative_id"], "auth-test", "test"
    )
    with pytest.raises(S.MigrationPaused):
        S.record_flip_attempt(fx_b["initiative_id"], "auth-test", "test")


def test_t_pa4_node_write_while_paused_proceeds(ve_ctx):
    """T-PA4: while paused, a write to a migrated node proceeds (or
    is refused for its own invalidity) — never redirected to the
    legacy tables. The global pause stays engaged: a release is a
    scoped exception, not an unpause."""
    fx = _seed_subtree(UID, prefix="pa4-")
    subtree_id = fx["initiative_id"]
    flip = _fixture_flip(subtree_id, UID)
    assert S.migration_pause_status()["state"] == "paused"
    conn = S.get_connection()
    legacy_before = S.get_task(fx["task_id"], UID)["title"]
    with S.ve_write_transaction(conn, purpose="pa4-node-write"):
        _fixture_update_node(
            conn, subtree_id, fx["task_id"], UID, title="node-write-ok"
        )
        S._commit_if_owner(conn)
    node = conn.execute(
        "SELECT title FROM nodes WHERE id = ?", (fx["task_id"],)
    ).fetchone()
    assert node[0] == "node-write-ok"
    assert S.get_task(fx["task_id"], UID)["title"] == legacy_before
    assert flip["attempt_id"]  # the flip's attempt is unaffected


def test_t_pa5_unresolved_attempt_blocks_flips_after_restart(ve_ctx,
                                                             tmp_path):
    """T-PA5: a `recorded` attempt blocks flips after a restart — a
    second, unrelated subtree's flip is likewise refused while a
    `recorded` attempt exists (global block); a
    `failed_before_commit` attempt blocks only its own subtree."""
    fx = _seed_subtree(UID, prefix="pa5a-")
    other = _seed_subtree(UID, prefix="pa5b-")
    attempt_id = _fixture_prepare_flip(fx["initiative_id"])
    script = _write_worker_script(tmp_path)
    for subtree_id in (fx["initiative_id"], other["initiative_id"]):
        result = _run_worker(
            script, "try_record", str(ve_ctx["db_path"]), subtree_id
        )
        assert result["outcome"] == "UnresolvedFlipAttempt", result
    # After the attempt is determined failed_before_commit, only its
    # own subtree is blocked.
    S.mark_attempt_failed_before_commit(attempt_id, "reviewed", "test")
    with pytest.raises(S.UnresolvedFlipAttempt):
        _fixture_prepare_flip(fx["initiative_id"])
    attempt_other = _fixture_prepare_flip(other["initiative_id"])
    assert S.get_flip_attempt(attempt_other)["state"] == "recorded"


def test_t_pa6_only_reconciliation_lifts_a_freeze(ve_ctx):
    """T-PA6 [NEW]: only reconciliation lifts a freeze. Fixture
    subtree frozen (failed_after_commit). (a) A pause release for
    the subtree does NOT lift it — a write is still refused with
    SubtreeWriteFrozen (§10.4). (b) Closing the attempt to
    `reconciled` lifts it — a node write proceeds (§10.5). (A
    legacy write stays refused after reconciliation: the subtree
    is flipped, so its authority is node.)"""
    fx = _seed_subtree(UID, prefix="pa6-")
    subtree_id = fx["initiative_id"]
    flip = _fixture_flip(subtree_id, UID)
    S.record_verification_result(
        flip["attempt_id"], False, "post-commit census mismatch", "test"
    )
    conn = S.get_connection()
    S.release_migration_pause_for_subtree(
        subtree_id, "auth-test", "test"
    )
    with pytest.raises(S.SubtreeWriteFrozen):
        S.update_task(fx["task_id"], M.TaskUpdate(title="still-frozen"), UID)
    with S.ve_write_transaction(conn, purpose="pa6-node-write"):
        with pytest.raises(S.SubtreeWriteFrozen):
            _fixture_update_node(
                conn, subtree_id, fx["task_id"], UID, title="still-frozen"
            )
    S.close_attempt_reconciled(
        flip["attempt_id"], "leave flipped; node authority stands", "test"
    )
    with S.ve_write_transaction(conn, purpose="pa6-node-write-2"):
        _fixture_update_node(
            conn, subtree_id, fx["task_id"], UID, title="reconciled-ok"
        )
        S._commit_if_owner(conn)
    node = conn.execute(
        "SELECT title FROM nodes WHERE id = ?", (fx["task_id"],)
    ).fetchone()
    assert node[0] == "reconciled-ok"
    with pytest.raises(S.MigratedNodeWriteRefused):
        S.update_task(fx["task_id"], M.TaskUpdate(title="legacy-no"), UID)


# ---------------------------------------------------------------------------
# 16.6 Ledger
# ---------------------------------------------------------------------------


def test_t_l1_empty_store_invariants(ve_ctx):
    """T-L1 [NEW]: a fresh C1a database. nodes / node_bullets /
    node_seats empty; migration_ledger empty; migration_pause is
    paused; the guard refuses nothing (no flipped subtrees) and no
    read changes anything."""
    conn = S.get_connection()
    assert _count(conn, "nodes") == 0
    assert _count(conn, "node_bullets") == 0
    assert _count(conn, "node_seats") == 0
    assert _count(conn, "migration_ledger") == 0
    assert _count(conn, "flip_attempts") == 0
    assert S.migration_pause_status()["state"] == "paused"
    fx = _seed_subtree(UID, prefix="l1-")
    # The guard refuses nothing: a legacy write succeeds.
    out = S.update_task(fx["task_id"], M.TaskUpdate(title="l1-ok"), UID)
    assert out["title"] == "l1-ok"
    assert _count(conn, "nodes") == 0
    # A read changes nothing (byte-level: the six source tables plus
    # the ledger tables are identical before and after reads).
    before = {
        table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        for table in (
            "ideas", "initiatives", "projects", "tasks",
            "checklist_items", "execution_steps", "nodes",
            "migration_ledger", "ledger_history",
        )
    }
    S.get_task(fx["task_id"], UID)
    S.list_tasks(user_id=UID)
    S.get_idea(fx["idea_id"], UID)
    after = {
        table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        for table in before
    }
    assert before == after


def test_t_l2_authority_row_and_version_increment(ve_ctx):
    """T-L2 [NEW]: a fixture flip creates the ledger row with
    authority='node', version=1, fingerprint hash + canonical JSON;
    a subsequent node write in the same subtree (test helper) bumps
    the version in the same transaction as the write, and the
    stored fingerprint is re-stored to match a fresh recompute."""
    fx = _seed_subtree(UID, prefix="l2-")
    subtree_id = fx["initiative_id"]
    flip = _fixture_flip(subtree_id, UID)
    conn = S.get_connection()
    ledger = _ledger(conn, subtree_id)
    assert ledger["authority"] == "node"
    assert ledger["version"] == 1
    assert ledger["fingerprint_sha256"] == flip["fingerprint_sha256"]
    assert ledger["fingerprint_canonical_json"] == flip["canonical_json"]
    assert ledger["flipped_at"]
    with S.ve_write_transaction(conn, purpose="l2-node-write"):
        _fixture_update_node(
            conn, subtree_id, fx["task_id"], UID, title="l2-node-write"
        )
        S._commit_if_owner(conn)
    ledger = _ledger(conn, subtree_id)
    assert ledger["version"] == 2
    recomputed = S.compute_subtree_fingerprint(conn, subtree_id)
    assert ledger["fingerprint_sha256"] == recomputed["sha256"]
    assert ledger["fingerprint_canonical_json"] == (
        recomputed["canonical_json"]
    )


def test_t_l3_attempt_record_durability_across_restart(ve_ctx):
    """T-L3 [NEW]: the attempt row survives a simulated crash
    (connection close + reopen — the durable half; the kill-based
    half is T-X1, the fresh-process half is T-X2)."""
    fx = _seed_subtree(UID, prefix="l3-")
    attempt_id = _fixture_prepare_flip(fx["initiative_id"])
    # Simulate a restart: drop every cached connection and reopen.
    S._thread_local.conn = None
    S._thread_local.db_path_resolved = None
    fresh = S.get_connection()
    assert S.get_flip_attempt(attempt_id)["state"] == "recorded"
    assert _count(fresh, "flip_attempts") == 1


def test_t_l4_append_only_history_enforcement(ve_ctx):
    """T-L4 [NEW]: no UPDATE/DELETE statement against
    `ledger_history` exists in local_ai/ + api/ (static half), and
    a direct runtime attempt fails (runtime half — the two BEFORE
    triggers). Corrections are new history entries, never edits
    (§2.3)."""
    pattern = re.compile(
        r"\bUPDATE\s+ledger_history\b|\bDELETE\s+FROM\s+ledger_history\b"
    )
    hits = []
    for root in (REPO_ROOT / "local_ai", REPO_ROOT / "api"):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                hits.append(str(path))
    assert hits == [], f"UPDATE/DELETE against ledger_history in: {hits}"
    # Runtime half: seed one history entry, then try to mutate it.
    fx = _seed_subtree(UID, prefix="l4-")
    _fixture_flip(fx["initiative_id"], UID)
    conn = S.get_connection()
    row = conn.execute(
        "SELECT history_id FROM ledger_history LIMIT 1"
    ).fetchone()
    assert row is not None
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "UPDATE ledger_history SET event = 'x' WHERE history_id = ?",
            (row[0],),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "DELETE FROM ledger_history WHERE history_id = ?", (row[0],)
        )
    conn.rollback()
    assert _count(conn, "ledger_history") > 0


# ---------------------------------------------------------------------------
# 16.7 Fingerprint and rollback proofs
# ---------------------------------------------------------------------------


def test_t_f1_fingerprint_determinism(ve_ctx):
    """T-F1: the fingerprint for a fixture subtree is identical when
    computed twice, and after a no-op re-serialization."""
    fx = _seed_subtree(UID, prefix="f1-")
    conn = S.get_connection()
    # The flip-time fingerprint binds flipped_at, which defaults to
    # "now" — two bare calls drift. Determinism means: same inputs
    # (same flipped_at) → same hash. Pass one fixed flipped_at.
    flipped_at = "2026-11-06T12:00:00+00:00"
    first = S.compute_legacy_subtree_fingerprint(
        conn, fx["initiative_id"], flipped_at=flipped_at
    )
    second = S.compute_legacy_subtree_fingerprint(
        conn, fx["initiative_id"], flipped_at=flipped_at
    )
    assert first == second
    # No-op re-serialization: parse the canonical JSON and re-dump
    # it through the same canonical encoder.
    doc = json.loads(first["canonical_json"])
    redumped = S._canonical_json(doc)
    assert redumped == first["canonical_json"]
    assert S._sha256_hex(redumped) == first["sha256"]


def test_t_f2_fingerprint_sensitivity(ve_ctx):
    """T-F2: changing one content field (title, status, one
    dependency, one origin field) changes the hash."""
    conn = S.get_connection()

    flipped_at = "2026-11-06T12:00:00+00:00"

    def baseline():
        fx = _seed_subtree(UID, prefix="f2-")
        return fx, S.compute_legacy_subtree_fingerprint(
            conn, fx["initiative_id"], flipped_at=flipped_at
        )

    def recompute(fx):
        return S.compute_legacy_subtree_fingerprint(
            conn, fx["initiative_id"], flipped_at=flipped_at
        )["sha256"]

    fx, base = baseline()
    conn.execute(
        "UPDATE tasks SET title = ? WHERE id = ?",
        ("changed-title", fx["task_id"]),
    )
    assert recompute(fx) != base["sha256"]

    fx, base = baseline()
    conn.execute(
        "UPDATE tasks SET status = 'Done' WHERE id = ?", (fx["task_id"],)
    )
    assert recompute(fx) != base["sha256"]

    fx, base = baseline()
    other = S.create_task(
        M.TaskCreate(project_id=fx["project_id"], title="dep-target",
                     status="Todo"), UID)
    conn.execute(
        "UPDATE tasks SET dependency_ids = ? WHERE id = ?",
        (json.dumps([other["id"]]), fx["task_id"]),
    )
    assert recompute(fx) != base["sha256"]

    fx, base = baseline()
    conn.execute(
        "UPDATE tasks SET origin_seat = 'champion' WHERE id = ?",
        (fx["task_id"],),
    )
    assert recompute(fx) != base["sha256"]


def test_t_f3_fingerprint_insensitivity_to_clock_touch(ve_ctx):
    """T-F3: changing ONLY updated_at (a clock touch with no content
    change) leaves the hash unchanged — updated_at is excluded
    (§11.4). Both the legacy-side and the node-side recompute."""
    fx = _seed_subtree(UID, prefix="f3-")
    conn = S.get_connection()
    flipped_at = "2026-11-06T12:00:00+00:00"
    base = S.compute_legacy_subtree_fingerprint(
        conn, fx["initiative_id"], flipped_at=flipped_at
    )
    conn.execute(
        "UPDATE tasks SET updated_at = '2099-01-01T00:00:00' WHERE id = ?",
        (fx["task_id"],),
    )
    assert S.compute_legacy_subtree_fingerprint(
        conn, fx["initiative_id"], flipped_at=flipped_at
    )["sha256"] == base["sha256"]
    flip = _fixture_flip(fx["initiative_id"], UID)
    conn.execute(
        "UPDATE nodes SET updated_at = '2099-01-01T00:00:00' WHERE id = ?",
        (fx["task_id"],),
    )
    assert S.compute_subtree_fingerprint(
        conn, fx["initiative_id"]
    )["sha256"] == flip["fingerprint_sha256"]


def test_t_fp1_fingerprint_computed_inside_transaction(ve_ctx):
    """T-FP1 [NEW]: race a concurrent writer against a fixture flip.
    The writer commits before the flip's BEGIN IMMEDIATE (its
    content must be inside the fingerprint); a second writer
    attempts after (refused). The recorded hash matches the
    post-flip node rows exactly — including the first writer's
    change, excluding the refused second writer's. A
    pre-transaction fingerprint would fail this test whenever the
    first writer's timing varies (§11.2)."""
    flip, writer, fx = _race_flip_vs_writer(ve_ctx, flip_first=False)
    assert writer == ("ok", "writer-value")
    assert isinstance(flip, dict)
    conn = S.get_connection()
    recomputed = S.compute_subtree_fingerprint(conn, fx["initiative_id"])
    assert recomputed["sha256"] == flip["fingerprint_sha256"]
    doc = json.loads(recomputed["canonical_json"])
    titles = {n["id"]: n["title"] for n in doc["nodes"]}
    assert titles[fx["task_id"]] == "writer-value"
    with pytest.raises(S.MigratedNodeWriteRefused):
        S.update_task(fx["task_id"], M.TaskUpdate(title="too-late"), UID)
    assert S.compute_subtree_fingerprint(
        conn, fx["initiative_id"]
    )["sha256"] == flip["fingerprint_sha256"]


def test_t_f9_fingerprint_catches_version_bypass_mutation(ve_ctx):
    """T-F9: mutate a content field via direct SQL (bypassing the
    version increment — the version is deliberately left unmoved),
    then recompute and attempt the rollback proof. The fingerprint
    changes while the version is unmoved; the proof fails on the
    fingerprint (not the version). The version-bypass is caught."""
    fx = _seed_subtree(UID, prefix="f9-")
    subtree_id = fx["initiative_id"]
    _fixture_flip(subtree_id, UID)
    conn = S.get_connection()
    version_before = _ledger(conn, subtree_id)["version"]
    conn.execute(
        "UPDATE nodes SET title = 'bypassed' WHERE id = ?",
        (fx["task_id"],),
    )
    conn.commit()
    assert _ledger(conn, subtree_id)["version"] == version_before
    ok, reason = _test_only_rollback_proof(conn, subtree_id)
    assert ok is False
    assert reason == "fingerprint mismatch"


def test_t_f10_fingerprint_covers_typed_attributes_and_bullets(ve_ctx):
    """T-F10: changing one typed-attribute field (priority,
    description, notes) and one bullet (progressive need) on a
    fixture node changes the fingerprint in both cases. A field
    class the store holds but the fingerprint omits is a failure."""
    fx = _seed_subtree(UID, prefix="f10-")
    subtree_id = fx["initiative_id"]
    flip = _fixture_flip(subtree_id, UID)
    conn = S.get_connection()
    base = flip["fingerprint_sha256"]
    originals = conn.execute(
        "SELECT priority, description, notes FROM nodes WHERE id = ?",
        (fx["task_id"],),
    ).fetchone()
    for field, value in (
        ("priority", "P0"),
        ("description", "a description"),
        ("notes", "some notes"),
    ):
        conn.execute(
            f"UPDATE nodes SET {field} = ? WHERE id = ?",
            (value, fx["task_id"]),
        )
        conn.commit()
        changed = S.compute_subtree_fingerprint(conn, subtree_id)["sha256"]
        assert changed != base, f"{field} change did not move the hash"
        # Restore the ORIGINAL value (not None — the legacy task's
        # description/notes default to "", so restoring None would
        # itself move the hash).
        conn.execute(
            f"UPDATE nodes SET {field} = ? WHERE id = ?",
            (originals[field], fx["task_id"]),
        )
        conn.commit()
        assert S.compute_subtree_fingerprint(
            conn, subtree_id
        )["sha256"] == base
    # One bullet (progressive need) on the task node.
    conn.execute(
        "INSERT INTO node_bullets (id, node_id, content, standing, "
        "position, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (M.new_id(), fx["task_id"], "a need", "open", 0,
         S._now(), S._now()),
    )
    conn.commit()
    assert S.compute_subtree_fingerprint(
        conn, subtree_id
    )["sha256"] != base


def test_t_f4_rollback_clean_proof(ve_ctx):
    """T-F4: rollback with a clean proof — version + fingerprint
    agree after the flip, and still agree after a legitimate node
    write (version bump + fingerprint re-store in one transaction)."""
    fx = _seed_subtree(UID, prefix="f4-")
    subtree_id = fx["initiative_id"]
    _fixture_flip(subtree_id, UID)
    conn = S.get_connection()
    ok, reason = _test_only_rollback_proof(conn, subtree_id)
    assert ok is True, reason
    with S.ve_write_transaction(conn, purpose="f4-node-write"):
        _fixture_update_node(
            conn, subtree_id, fx["task_id"], UID, title="f4-write"
        )
        S._commit_if_owner(conn)
    ok, reason = _test_only_rollback_proof(conn, subtree_id)
    assert ok is True, reason


def test_t_f5_rollback_moved_version(ve_ctx):
    """T-F5: the ledger version was moved (direct SQL, no content
    change, no fingerprint re-store). The proof fails: the canonical
    document binds the version, so the recomputed hash no longer
    matches the stored one."""
    fx = _seed_subtree(UID, prefix="f5-")
    subtree_id = fx["initiative_id"]
    _fixture_flip(subtree_id, UID)
    conn = S.get_connection()
    conn.execute(
        "UPDATE migration_ledger SET version = 7 WHERE subtree_id = ?",
        (subtree_id,),
    )
    conn.commit()
    ok, reason = _test_only_rollback_proof(conn, subtree_id)
    assert ok is False
    assert reason == "fingerprint mismatch"


def test_t_f6_rollback_fingerprint_mismatch(ve_ctx):
    """T-F6: the stored fingerprint itself was tampered with (direct
    SQL). The recompute no longer matches the stored hash; the
    proof fails."""
    fx = _seed_subtree(UID, prefix="f6-")
    subtree_id = fx["initiative_id"]
    _fixture_flip(subtree_id, UID)
    conn = S.get_connection()
    conn.execute(
        "UPDATE migration_ledger SET fingerprint_sha256 = ? "
        "WHERE subtree_id = ?",
        ("0" * 64, subtree_id),
    )
    conn.commit()
    ok, reason = _test_only_rollback_proof(conn, subtree_id)
    assert ok is False
    assert reason == "fingerprint mismatch"


def test_t_f7_rollback_downstream_side_effect(ve_ctx):
    """T-F7: a downstream side effect changed the subtree content
    outside the node-write path (a bullet inserted directly,
    bypassing the version bump + fingerprint re-store). The proof
    fails — the side effect is caught."""
    fx = _seed_subtree(UID, prefix="f7-")
    subtree_id = fx["initiative_id"]
    _fixture_flip(subtree_id, UID)
    conn = S.get_connection()
    conn.execute(
        "INSERT INTO node_bullets (id, node_id, content, standing, "
        "position, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (M.new_id(), fx["task_id"], "side-effect need", "open", 0,
         S._now(), S._now()),
    )
    conn.commit()
    ok, reason = _test_only_rollback_proof(conn, subtree_id)
    assert ok is False
    assert reason == "fingerprint mismatch"


def test_t_f8_rollback_post_flip_deletion(ve_ctx):
    """T-F8: a node was deleted after the flip (direct SQL — there
    is no production `delete_node`). The recompute is missing a
    node; the proof fails."""
    fx = _seed_subtree(UID, prefix="f8-")
    subtree_id = fx["initiative_id"]
    _fixture_flip(subtree_id, UID)
    conn = S.get_connection()
    conn.execute("DELETE FROM nodes WHERE id = ?", (fx["task_id"],))
    conn.commit()
    ok, reason = _test_only_rollback_proof(conn, subtree_id)
    assert ok is False
    assert reason == "fingerprint mismatch"
