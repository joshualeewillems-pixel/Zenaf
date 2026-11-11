"""Fellowship derivation consent gate — Phase 0 consent correction.

Covers the audit's acceptance criteria (§6.4 of
zenaf-derive-observations-consent-enforcement-audit-2026-11-09.md):

- flag off (default), missing row, malformed permissions_json, or
  unreadable store: the event is still recorded on the activity
  log, zero observation rows are created, and the generation
  function is never invoked;
- flag on: derivation proceeds exactly as today (same pre-filter,
  same prompts, same rows, same statuses);
- flag flipped on → off between scheduling and running: the
  scheduled run skips (the gate is checked at run time, not at
  schedule time);
- install_default_pipeline always installs a gating reader; a
  pipeline constructed directly without a reader derives ungated
  only as the documented test/tool direct-drive mode (same as
  steward);
- the new flag persists through a write/read round trip (the
  Slice 1 dead-flag regression test, applied to the new key);
  a legacy row without the key reads False everywhere and the
  read-rewrite never invents True.

All generations are fake/counting. Stores are tmp SQLite files.
No surface is touched: no UI, no dialogue, no steward change.
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

import local_ai.fellowship.derivation as derivation_mod
from local_ai.fellowship import derivation, events
from local_ai.fellowship.consent import fellowship_consent_allowed
from local_ai.fellowship.derivation import DerivationPipeline
from local_ai.fellowship.events import FellowshipEvent
from local_ai.fellowship.observations import ObservationStore

USER = "user-1"

# Conductor-focus text (from test_fellowship_observations.py):
# the pre-filter makes the conductor a candidate for this event.
WEAVER_MESSAGE = (
    "I keep juggling three projects and nothing fits together — the "
    "priorities keep competing and the whole plan feels like it is detuning."
)


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (real path)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return ve_store


@pytest.fixture(autouse=True)
def _no_background_derivation():
    """Keep stray pipelines from deriving in this module: install a
    pipeline whose scheduler never runs its callback, and restore
    whatever was installed afterwards. Tests install their own
    inside the test body."""
    old = derivation._PIPELINE
    derivation.install_default_pipeline(
        store=None, generate_fn=None, scheduler=lambda fn: None
    )
    yield
    derivation._PIPELINE = old


def _perm_conn(tmp_path, flags_by_user):
    """A tmp permissions DB (VE storage shape, minimal DDL)."""
    db = tmp_path / "perm.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT PRIMARY KEY, consent_given INTEGER, "
        "consent_version TEXT, consent_at TEXT, "
        "permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES "
            "(?, 1, 'permissions-v1', NULL, ?, '')",
            (user_id, json.dumps(flags)),
        )
    conn.commit()
    return conn


def _obs_store(tmp_path) -> ObservationStore:
    return ObservationStore(tmp_path / "observations.db")


def _event(event_id="evt-1", text=WEAVER_MESSAGE, user=USER) -> FellowshipEvent:
    return FellowshipEvent(
        id=event_id,
        kind=events.CONVERSATION_TURN,
        user_id=user,
        entity_type="conversation",
        entity_id="skeleton",
        evidence_text=text,
        summary="Conversation turn with the conductor voice.",
        payload={"archetype_id": "conductor"},
    )


class _CountingGen:
    def __init__(self, text: str = "A reading."):
        self.text = text
        self.prompts: list = []

    def __call__(self, prompt: str, **kwargs) -> str:
        self.prompts.append((prompt, kwargs))
        return self.text


# -- consent reader -----------------------------------------------------------


def test_consent_gate_reads_flag_only(tmp_path):
    """Gate truth table: on only when the flag itself is true."""
    conn = _perm_conn(
        tmp_path,
        {
            "u-on": {"fellowship_derivation": True},
            "u-off": {"fellowship_derivation": False},
            "u-missing": {"behavioral_tracking": True},
            "u-bad": {},
            "u-nonbool": {"fellowship_derivation": "yes"},
        },
    )
    # Malformed JSON row for u-bad: rewrite its blob unparseable.
    conn.execute(
        "UPDATE user_permissions_settings SET permissions_json = 'not-json' "
        "WHERE user_id = 'u-bad'"
    )
    conn.commit()
    assert fellowship_consent_allowed("u-on", connection=conn) is True
    assert fellowship_consent_allowed("u-off", connection=conn) is False
    assert fellowship_consent_allowed("u-missing", connection=conn) is False
    assert fellowship_consent_allowed("u-bad", connection=conn) is False
    assert fellowship_consent_allowed("u-nonbool", connection=conn) is False
    assert fellowship_consent_allowed("u-ghost", connection=conn) is False
    assert fellowship_consent_allowed("", connection=conn) is False
    assert fellowship_consent_allowed(None, connection=conn) is False
    # A non-dict JSON blob also fails closed.
    conn.execute(
        "UPDATE user_permissions_settings SET permissions_json = '[1, 2]' "
        "WHERE user_id = 'u-off'"
    )
    conn.commit()
    assert fellowship_consent_allowed("u-off", connection=conn) is False


# -- pipeline gate ------------------------------------------------------------


def test_install_default_pipeline_always_gates(tmp_path, monkeypatch):
    """The installed pipeline always gates: its default reader is
    the production reader, and a flag-off user derives nothing
    through it while a flag-on user derives as today."""
    import local_ai.vision_execution.storage as ve_storage

    conn = _perm_conn(tmp_path, {USER: {"fellowship_derivation": False}})
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    store = _obs_store(tmp_path)
    gen = _CountingGen()
    try:
        pipe = derivation_mod.install_default_pipeline(
            store=store,
            generate_fn=gen,
            scheduler=lambda fn: fn(),
        )
        assert pipe._consent_reader is fellowship_consent_allowed
        pipe.schedule(_event("evt-1"))
        assert gen.prompts == []
        assert store.list_for_user(USER) == []
        conn.execute(
            "UPDATE user_permissions_settings SET permissions_json = ? "
            "WHERE user_id = ?",
            (json.dumps({"fellowship_derivation": True}), USER),
        )
        conn.commit()
        pipe.schedule(_event("evt-2"))
        assert len(gen.prompts) >= 1
        rows = store.list_for_user(USER)
        assert len(rows) == len(gen.prompts)
        assert any(row.seat == "conductor" for row in rows)
        assert all(row.status == "pending" for row in rows)
    finally:
        derivation._PIPELINE = None


def test_gate_checked_at_run_time(tmp_path, monkeypatch):
    """A withdrawal between scheduling and running is respected:
    the gate is checked in _run, not in schedule."""
    import local_ai.vision_execution.storage as ve_storage

    conn = _perm_conn(tmp_path, {USER: {"fellowship_derivation": True}})
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    store = _obs_store(tmp_path)
    gen = _CountingGen()
    pending: list = []
    try:
        pipe = derivation_mod.install_default_pipeline(
            store=store,
            generate_fn=gen,
            scheduler=lambda fn: pending.append(fn),
        )
        pipe.schedule(_event("evt-1"))
        assert pending, "schedule must defer the run, not run it"
        # Withdraw consent before the deferred run executes.
        conn.execute(
            "UPDATE user_permissions_settings SET permissions_json = ? "
            "WHERE user_id = ?",
            (json.dumps({"fellowship_derivation": False}), USER),
        )
        conn.commit()
        for fn in pending:
            fn()
        assert gen.prompts == []
        assert store.list_for_user(USER) == []
    finally:
        derivation._PIPELINE = None


def test_gate_failure_fails_closed(tmp_path):
    """A consent reader that raises closes the gate — and the
    failure never escapes the pipeline."""
    store = _obs_store(tmp_path)
    gen = _CountingGen()

    def _raising_reader(user_id: str) -> bool:
        raise RuntimeError("permissions store down")

    pipe = DerivationPipeline(
        store=store,
        generate_fn=gen,
        scheduler=lambda fn: fn(),
        consent_reader=_raising_reader,
    )
    pipe.schedule(_event("evt-1"))
    assert gen.prompts == []
    assert store.list_for_user(USER) == []


def test_direct_pipeline_without_reader_derives_ungated(tmp_path):
    """Direct-drive mode (tests/tools only): a pipeline built
    directly without a reader derives ungated, same as steward.
    The production install never does this — see
    test_install_default_pipeline_always_gates."""
    store = _obs_store(tmp_path)
    gen = _CountingGen()
    pipe = DerivationPipeline(
        store=store,
        generate_fn=gen,
        scheduler=lambda fn: fn(),
    )
    pipe.schedule(_event("evt-1"))
    assert len(gen.prompts) >= 1
    rows = store.list_for_user(USER)
    assert len(rows) == len(gen.prompts)


# -- flag persistence (Slice 1 dead-flag regression, new key) -----------------


def test_flag_survives_write_read_roundtrip(ve_ctx):
    """REGRESSION TEST for the inventory §1.4 dead-flag defect,
    applied to the new key: without a key-list entry,
    ``normalize_user_permission_prefs`` would drop
    ``fellowship_derivation`` on write AND on read, and the gate
    would always read False. Post-fix, the flag round-trips and
    the fellowship gate reads True through the production row."""
    import local_ai.vision_execution.storage as ve_store

    user_id = "u-fellow"
    # Direct normalize check: the key survives normalization now.
    assert ve_store.normalize_user_permission_prefs(
        {"fellowship_derivation": True}
    )["fellowship_derivation"] is True
    # Full round-trip through upsert → get (the production path).
    ve_store.upsert_user_permissions_settings(
        user_id,
        permissions={
            "steward_derivation": False,
            "fellowship_derivation": True,
        },
        consent_acknowledged=False,
        consent_version="",
    )
    settings = ve_store.get_user_permissions_settings(user_id)
    assert settings["permissions"]["fellowship_derivation"] is True
    assert settings["permissions"]["steward_derivation"] is False
    # And the fellowship gate — which reads the raw blob — sees it.
    raw = sqlite3.connect(str(ve_ctx._DB_PATH))
    try:
        assert fellowship_consent_allowed(user_id, connection=raw) is True
    finally:
        raw.close()


def test_legacy_row_without_flag_reads_false(ve_ctx):
    """A pre-fix-shaped row — a blob with NO fellowship_derivation
    key at all — must read False through BOTH production paths:
    the normalized settings read and the raw-blob fellowship gate.
    No production writer could have stored True pre-fix (upsert
    and the get read-rewrite both normalize through the key list,
    which lacked the key; the consent gate is read-only), so a
    legacy row is key-absent, and key-absent is False everywhere.
    The read-rewrite stores the normalized False — it never
    invents True."""
    import local_ai.vision_execution.storage as ve_store

    user_id = "u-legacy"
    ve_store.upsert_user_permissions_settings(
        user_id,
        permissions={"steward_derivation": True},
        consent_acknowledged=False,
        consent_version="",
    )
    # Rewrite the stored blob to the pre-fix shape: the key absent
    # entirely (as every row stored before this correction is).
    conn = sqlite3.connect(str(ve_ctx._DB_PATH))
    try:
        conn.execute(
            "UPDATE user_permissions_settings SET permissions_json = ? "
            "WHERE user_id = ?",
            (json.dumps({"steward_derivation": True}), user_id),
        )
        conn.commit()
        # Raw-blob gate: absent key is False, even with steward on.
        assert fellowship_consent_allowed(user_id, connection=conn) is False
    finally:
        conn.close()
    # Normalized settings read: absent key defaults to False, and
    # the read-rewrite stores the normalized False.
    settings = ve_store.get_user_permissions_settings(user_id)
    assert settings["permissions"]["fellowship_derivation"] is False
    assert settings["permissions"]["steward_derivation"] is True
    raw = sqlite3.connect(str(ve_ctx._DB_PATH))
    try:
        stored = json.loads(
            raw.execute(
                "SELECT permissions_json FROM user_permissions_settings "
                "WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
        )
        assert stored["fellowship_derivation"] is False
    finally:
        raw.close()
