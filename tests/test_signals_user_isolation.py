"""Signals user isolation — Track C, Option A (2026-11-11).

Owner-scoped reads and mutations enforced by SQL predicates; legacy
rows quarantined (user_id IS NULL, invisible to everyone); linked
initiative/project/task references validated against the owner before
any write (founder correction 1); rollback fails closed via the
ZENAF_SIGNALS_DISABLED kill switch (founder correction 2).

Deterministic; isolated temp-file database; no live requests, no real
sessions, no reads of the repo's data/ directory. Follows the
established route-auth test pattern from
tests/test_decisions_security_remediation.py and Track A's
tests/test_signals_routes_auth.py (ve_ctx fixture,
dependency_overrides, raw-ASGI runner).

Anonymous-access criteria (Track A) are covered at the end of this
file: Track A never landed as a separate patch, so this rebuild
carries both the auth containment and the ownership scoping, and the
401 tests live here. Criterion 10 (staging verification) is a
post-merge gate, not a unit test.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI

from api.routes.auth_routes import get_current_user
from api.routes import vision_execution as ve_routes
from local_ai import activity as activity_mod
from local_ai.narrative.sweep import reconstruct_event
from local_ai.signals import models as SigModels
from local_ai.signals import service as SigS
from local_ai.signals import storage as SigSt
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import service as VEService
from local_ai.vision_execution import storage as ve_storage


# -- VE fixture (same pattern as tests/test_decisions_security_remediation.py)


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    db_path = tmp_path / "ve.db"
    conn = ve_storage.open_sqlite_with_ve_pragmas(db_path)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    ve_storage.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture()
def activity_log(tmp_path, monkeypatch):
    """Route the append-only activity log at a tmp path, so actor
    assertions read real log lines without touching the repo log."""
    log_path = tmp_path / "activity.log"
    monkeypatch.setattr(activity_mod, "_activity_log_path", lambda: log_path)
    return log_path


def _make_user(ve_ctx, email: str) -> str:
    user = ve_storage.create_user_account(email, "pw", "Test")
    return str(user["id"])


def _make_project(ve_ctx, uid: str, title: str) -> str:
    ini = ve_storage.create_initiative(
        ve_models.InitiativeCreate(title=f"{title} initiative", brief="b"), uid
    )
    proj = ve_storage.create_project(
        ve_models.ProjectCreate(initiative_id=str(ini["id"]), title=title), uid
    )
    return str(proj["id"])


def _make_initiative(ve_ctx, uid: str, title: str) -> str:
    ini = ve_storage.create_initiative(
        ve_models.InitiativeCreate(title=title, brief="b"), uid
    )
    return str(ini["id"])


def _make_task(ve_ctx, uid: str, title: str) -> str:
    task = ve_storage.create_task(ve_models.TaskCreate(title=title), uid)
    return str(task["id"])


@pytest.fixture()
def two_users(ve_ctx, activity_log):
    """User A and user B, each with a project, an initiative, and a task
    of their own, plus one signal each owned by them.

    Takes activity_log so the fixture's signal creates land in the tmp
    activity log (never the repo log)."""
    uid_a = _make_user(ve_ctx, "a@example.com")
    uid_b = _make_user(ve_ctx, "b@example.com")
    pid_a = _make_project(ve_ctx, uid_a, "ALPHA project")
    pid_b = _make_project(ve_ctx, uid_b, "BRAVO project")
    iid_a = _make_initiative(ve_ctx, uid_a, "ALPHA initiative")
    iid_b = _make_initiative(ve_ctx, uid_b, "BRAVO initiative")
    tid_a = _make_task(ve_ctx, uid_a, "ALPHA task")
    tid_b = _make_task(ve_ctx, uid_b, "BRAVO task")
    sig_a = SigS.create_signals(
        [SigModels.SignalCreate(kind="attention", title="A-signal", source="test")], uid_a
    )[0]
    sig_b = SigS.create_signals(
        [SigModels.SignalCreate(kind="risk", title="B-signal", source="test")], uid_b
    )[0]
    return {
        "uid_a": uid_a, "uid_b": uid_b,
        "pid_a": pid_a, "pid_b": pid_b,
        "iid_a": iid_a, "iid_b": iid_b,
        "tid_a": tid_a, "tid_b": tid_b,
        "sig_a": sig_a, "sig_b": sig_b,
    }


def _make_app(uid: str | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(ve_routes.router)
    if uid is not None:
        app.dependency_overrides[get_current_user] = lambda: {"id": uid}
    return app


def _run_asgi(
    app,
    method: str,
    path: str,
    payload: dict | list | None = None,
    query: str = "",
    cookies: dict | None = None,
):
    """Drive one request through the app's ASGI interface (no httpx here)."""
    body = json.dumps(payload).encode() if payload is not None else b""
    headers: list[tuple[bytes, bytes]] = []
    if payload is not None:
        headers.append((b"content-type", b"application/json"))
    if cookies:
        cookie_value = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", cookie_value.encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(raw.decode() or "{}")


def _signal_payload(**over) -> dict:
    payload = {"kind": "attention", "title": "t", "source": "test"}
    payload.update(over)
    return payload


def _row(conn, table: str, row_id: str):
    return conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()


# -- criterion 1: ownership enforced in SQL -------------------------------


def test_list_scoped_to_caller(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    rows_a = SigS.list_signals(uid_a)
    rows_b = SigS.list_signals(uid_b)
    assert [r["id"] for r in rows_a] == [two_users["sig_a"]["id"]]
    assert [r["id"] for r in rows_b] == [two_users["sig_b"]["id"]]
    assert SigS.list_signals("someone-else") == []
    with pytest.raises(ValueError):
        SigS.list_signals("")
    with pytest.raises(ValueError):
        SigS.list_signals(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        SigS.list_signals()  # type: ignore[call-arg]


def test_get_scoped_to_caller(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    sig_a = two_users["sig_a"]
    assert SigSt.get_signal(sig_a["id"], uid_a)["id"] == sig_a["id"]
    assert SigSt.get_signal(sig_a["id"], uid_b) is None
    assert SigSt.get_signal("missing-id", uid_a) is None


def test_update_scoped_to_caller(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    sig_a = two_users["sig_a"]
    before = tuple(_row(ve_ctx, "signals", sig_a["id"]))
    out = SigS.update_signal(
        sig_a["id"], SigModels.SignalUpdate(status="resolved"), uid_b
    )
    assert out is None
    assert tuple(_row(ve_ctx, "signals", sig_a["id"])) == before


def test_update_predicate_on_final_update(ve_ctx, two_users, monkeypatch):
    """The enforcement point is the UPDATE itself, not the pre-read.
    Stub the pre-read to always return the row (as if it passed), then
    update as a non-owner: the UPDATE's own predicate must still match
    zero rows and return None, leaving the row byte-identical."""
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    sig_a = two_users["sig_a"]
    before = tuple(_row(ve_ctx, "signals", sig_a["id"]))
    real_get = SigSt.get_signal
    monkeypatch.setattr(SigSt, "get_signal", lambda sid, uid: real_get(sid, uid_a))
    out = SigS.update_signal(
        sig_a["id"], SigModels.SignalUpdate(status="resolved"), uid_b
    )
    assert out is None
    assert tuple(_row(ve_ctx, "signals", sig_a["id"])) == before


# -- criterion 2: ownership stamped server-side ----------------------------


def test_create_stamps_session_owner(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    app = _make_app(uid_a)
    status, body = _run_asgi(
        app, "POST", "/vision-execution/signals",
        [_signal_payload(**{"user_id": uid_b, "title": "stamped"})],
    )
    assert status == 200, body
    assert body[0]["user_id"] == uid_a
    assert body[0]["title"] == "stamped"


def test_create_ignores_client_user_id(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    app = _make_app(uid_a)
    status, body = _run_asgi(
        app, "POST", "/vision-execution/signals",
        [_signal_payload(**{"user_id": uid_b})],
    )
    assert status == 200, body
    row = _row(ve_ctx, "signals", body[0]["id"])
    cols = [c[1] for c in ve_ctx.execute("PRAGMA table_info(signals)")]
    assert row[cols.index("user_id")] == uid_a


def test_service_overwrites_payload_user_id(ve_ctx, two_users):
    """A payload dict carrying user_id is ignored at the storage
    boundary: the required argument wins, never the payload."""
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    out = SigSt.create_signals_bulk(
        [{"kind": "attention", "title": "t", "source": "test", "user_id": uid_b}], uid_a
    )
    assert out[0]["user_id"] == uid_a
    assert SigSt.get_signal(out[0]["id"], uid_a)["user_id"] == uid_a
    assert SigSt.get_signal(out[0]["id"], uid_b) is None


# -- criterion 3: quarantine — unknown ownership fails closed -------------

_OLD_SIGNALS_DDL = """
CREATE TABLE signals (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  detail TEXT,
  source TEXT NOT NULL DEFAULT '',
  source_excerpt TEXT,
  source_ref TEXT,
  confidence TEXT,
  linked_initiative_id TEXT,
  linked_project_id TEXT,
  linked_task_id TEXT,
  linked_asset_ids TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'new',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
"""


@pytest.fixture()
def legacy_db(tmp_path, monkeypatch):
    """A pre-migration database: signals rows with NO user_id column at
    all, as staging holds them today. init_db then migrates it."""
    db_path = tmp_path / "legacy.db"
    conn = ve_storage.open_sqlite_with_ve_pragmas(db_path)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    conn.executescript(_OLD_SIGNALS_DDL)
    conn.execute(
        "INSERT INTO signals (id, kind, title, source, status, created_at, updated_at)"
        " VALUES ('sig-old-1', 'risk', 'legacy one', 'meeting-extraction', 'new', '2026-11-01T00:00:00', '2026-11-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO signals (id, kind, title, source, status, created_at, updated_at)"
        " VALUES ('sig-old-2', 'attention', 'legacy two', 'inbox-triage', 'acknowledged', '2026-11-02T00:00:00', '2026-11-02T00:00:00')"
    )
    conn.commit()
    yield conn
    conn.close()


def test_quarantined_rows_invisible_to_everyone(legacy_db):
    # Migrate the legacy database (the fixture rows predate init_db).
    ve_storage.init_db(legacy_db)
    uid_a = _make_user(legacy_db, "a@example.com")
    uid_b = _make_user(legacy_db, "b@example.com")
    sig_a = SigS.create_signals(
        [SigModels.SignalCreate(kind="attention", title="A-signal", source="test")], uid_a
    )[0]
    # The owner's own signal is visible; the legacy rows are not.
    assert [r["id"] for r in SigS.list_signals(uid_a)] == [sig_a["id"]]
    assert SigS.list_signals(uid_b) == []
    assert SigSt.get_signal("sig-old-1", uid_a) is None
    assert SigSt.get_signal("sig-old-1", uid_b) is None
    app = _make_app(uid_a)
    status, body = _run_asgi(
        app, "PATCH", "/vision-execution/signals/sig-old-1", {"status": "resolved"}
    )
    assert status == 404, body
    row = _row(legacy_db, "signals", "sig-old-1")
    assert row["status"] == "new"  # unchanged


def test_quarantine_count_query(legacy_db):
    ve_storage.init_db(legacy_db)
    count = legacy_db.execute(
        "SELECT COUNT(*) FROM signals WHERE user_id IS NULL"
    ).fetchone()[0]
    assert count == 2
    rows = legacy_db.execute(
        "SELECT id, kind, title, source, source_ref, status, created_at"
        " FROM signals WHERE user_id IS NULL ORDER BY created_at DESC"
    ).fetchall()
    assert [r["id"] for r in rows] == ["sig-old-2", "sig-old-1"]


# -- criterion 4: Radar consumes only the caller's signals ----------------


def test_radar_returns_only_caller_signals(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    radar_a = VEService.get_radar(uid_a)
    radar_b = VEService.get_radar(uid_b)
    assert [s["id"] for s in radar_a["signals"]] == [two_users["sig_a"]["id"]]
    assert [s["id"] for s in radar_b["signals"]] == [two_users["sig_b"]["id"]]


def test_radar_excludes_quarantined_rows(legacy_db):
    ve_storage.init_db(legacy_db)
    uid_a = _make_user(legacy_db, "a@example.com")
    radar = VEService.get_radar(uid_a)
    assert [s["id"] for s in radar["signals"]] == []


# -- criterion 5: activity visibility and linked-entity references --------


def test_signal_events_carry_actor(ve_ctx, two_users, activity_log):
    uid_a = two_users["uid_a"]
    sig = SigS.create_signals(
        [SigModels.SignalCreate(kind="attention", title="actor-check", source="test")], uid_a
    )[0]
    SigS.update_signal(
        sig["id"], SigModels.SignalUpdate(status="acknowledged"), uid_a
    )
    lines = [json.loads(line) for line in activity_log.read_text(encoding="utf-8").splitlines()]
    sig_lines = [
        ln for ln in lines
        if ln.get("entity_type") == "signal" and "actor-check" in (ln.get("detail") or "")
    ]
    assert sig_lines, "no signal activity lines were written"
    assert all(ln.get("actor") == uid_a for ln in sig_lines)
    assert all(ln.get("actor") != "system" for ln in sig_lines)
    assert {ln.get("type") for ln in sig_lines} == {"signal_created", "signal_acknowledged"}


def test_signal_events_not_derived_by_sweep(ve_ctx, two_users):
    uid_a = two_users["uid_a"]
    record = {
        "id": "evt-1",
        "type": "signal_created",
        "entity_type": "signal",
        "entity_id": two_users["sig_a"]["id"],
        "actor": uid_a,
        "source": "meeting-extraction",
        "detail": "title=A-signal",
        "created_at": "2026-11-11T00:00:00+00:00",
    }
    assert reconstruct_event(record) is None


def test_flow_readings_rejects_signal(ve_ctx, two_users):
    uid_a = two_users["uid_a"]
    with pytest.raises(ValueError, match="unsupported entity_type"):
        VEService.list_coordination_execution_flow_readings(
            uid_a, "signal", two_users["sig_a"]["id"]
        )


def test_foreign_link_unresolvable(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    # A links their own signal to B's initiative id (allowed at write
    # time only if the link validates — see correction 1 tests; here the
    # read path must not resolve it for A).
    assert ve_storage.get_initiative(two_users["iid_b"], uid_a) is None
    assert ve_storage.get_initiative(two_users["iid_b"], uid_b) is not None


# -- founder correction 1: linked ownership --------------------------------


def test_create_rejects_foreign_initiative_link(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    app = _make_app(uid_a)
    before = len(SigS.list_signals(uid_a))
    status, body = _run_asgi(
        app, "POST", "/vision-execution/signals",
        [_signal_payload(linkedInitiativeId=two_users["iid_b"])],
    )
    assert status == 404, body
    assert len(SigS.list_signals(uid_a)) == before  # no mutation


def test_create_rejects_nonexistent_project_link(ve_ctx, two_users):
    uid_a = two_users["uid_a"]
    app = _make_app(uid_a)
    before = len(SigS.list_signals(uid_a))
    status, body = _run_asgi(
        app, "POST", "/vision-execution/signals",
        [_signal_payload(linkedProjectId="missing-project-id")],
    )
    assert status == 404, body
    assert len(SigS.list_signals(uid_a)) == before


def test_create_rejects_foreign_task_link(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    with pytest.raises(ValueError, match="not owned"):
        SigS.create_signals(
            [SigModels.SignalCreate(
                kind="attention", title="t", source="test",
                linked_task_id=two_users["tid_b"],
            )],
            uid_a,
        )
    assert len(SigS.list_signals(uid_a)) == 1


def test_bulk_create_rejects_without_partial_mutation(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    app = _make_app(uid_a)
    before = len(SigS.list_signals(uid_a))
    status, body = _run_asgi(
        app, "POST", "/vision-execution/signals",
        [
            _signal_payload(title="good-one"),
            _signal_payload(title="bad-one", linkedProjectId=two_users["pid_b"]),
        ],
    )
    assert status == 404, body
    # The good item must NOT have been persisted: no partial mutation.
    assert len(SigS.list_signals(uid_a)) == before
    assert "good-one" not in {r["title"] for r in SigS.list_signals(uid_a)}


def test_patch_rejects_foreign_link(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    sig_a = two_users["sig_a"]
    before = tuple(_row(ve_ctx, "signals", sig_a["id"]))
    app = _make_app(uid_a)
    status, body = _run_asgi(
        app, "PATCH", f"/vision-execution/signals/{sig_a['id']}",
        {"linkedProjectId": two_users["pid_b"]},
    )
    assert status == 404, body
    assert tuple(_row(ve_ctx, "signals", sig_a["id"])) == before


def test_patch_accepts_own_link(ve_ctx, two_users):
    uid_a = two_users["uid_a"]
    sig_a = two_users["sig_a"]
    app = _make_app(uid_a)
    status, body = _run_asgi(
        app, "PATCH", f"/vision-execution/signals/{sig_a['id']}",
        {"linkedProjectId": two_users["pid_a"], "status": "linked"},
    )
    assert status == 200, body
    assert body["linked_project_id"] == two_users["pid_a"]
    assert body["status"] == "linked"


def test_patch_status_only_skips_link_validation(ve_ctx, two_users):
    """A status-only PATCH must not re-validate links the patch does not
    supply: a signal whose stored link predates validation (or was
    written when the linked entity existed) keeps working."""
    uid_a = two_users["uid_a"]
    sig_a = two_users["sig_a"]
    # Seed a legacy-style row carrying a link to a nonexistent entity,
    # as a pre-validation row would.
    conn = ve_ctx
    conn.execute(
        "UPDATE signals SET linked_project_id = ? WHERE id = ?",
        ("gone-project-id", sig_a["id"]),
    )
    conn.commit()
    app = _make_app(uid_a)
    status, body = _run_asgi(
        app, "PATCH", f"/vision-execution/signals/{sig_a['id']}",
        {"status": "acknowledged"},
    )
    assert status == 200, body
    assert body["status"] == "acknowledged"
    assert body["linked_project_id"] == "gone-project-id"


# -- criterion 6: cross-user GET / PATCH / enumeration / Radar ------------


def test_cross_user_get_404(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    sig_a = two_users["sig_a"]
    app_b = _make_app(uid_b)
    status, body = _run_asgi(app_b, "GET", "/vision-execution/signals")
    assert status == 200
    assert {r["id"] for r in body} == {two_users["sig_b"]["id"]}
    # There is no GET-by-id route; the storage boundary is the check.
    assert SigSt.get_signal(sig_a["id"], uid_b) is None
    assert SigSt.get_signal("missing-id", uid_b) is None


def test_cross_user_patch_404_row_unchanged(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    sig_a = two_users["sig_a"]
    before = tuple(_row(ve_ctx, "signals", sig_a["id"]))
    app_b = _make_app(uid_b)
    status, body = _run_asgi(
        app_b, "PATCH", f"/vision-execution/signals/{sig_a['id']}",
        {"status": "resolved"},
    )
    assert status == 404, body
    assert body == {"detail": "Signal not found"}
    assert tuple(_row(ve_ctx, "signals", sig_a["id"])) == before


def test_enumeration_reveals_nothing(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    sig_a = two_users["sig_a"]
    app_b = _make_app(uid_b)
    # Guessed ids (including one adjacent to a known own id) return the
    # same 404 body as a missing id; nothing distinguishes foreign
    # from missing.
    missing_status, missing_body = _run_asgi(
        app_b, "PATCH", "/vision-execution/signals/does-not-exist",
        {"status": "resolved"},
    )
    assert missing_status == 404
    for guessed in (sig_a["id"], sig_a["id"][:-1] + "0", "sig-000000"):
        status, body = _run_asgi(
            app_b, "PATCH", f"/vision-execution/signals/{guessed}",
            {"status": "resolved"},
        )
        assert status == 404, body
        assert body == missing_body


def test_cross_user_radar_isolation(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    app_a, app_b = _make_app(uid_a), _make_app(uid_b)
    _, body_a = _run_asgi(app_a, "GET", "/vision-execution/radar")
    _, body_b = _run_asgi(app_b, "GET", "/vision-execution/radar")
    assert [s["id"] for s in body_a["signals"]] == [two_users["sig_a"]["id"]]
    assert [s["id"] for s in body_b["signals"]] == [two_users["sig_b"]["id"]]


# -- criterion 8: migration and rollback ------------------------------------


def test_migration_preserves_rows(legacy_db):
    before = {
        r["id"]: tuple(r)
        for r in legacy_db.execute(
            "SELECT id, kind, title, detail, source, source_excerpt, source_ref,"
            " confidence, linked_initiative_id, linked_project_id, linked_task_id,"
            " linked_asset_ids, status, created_at, updated_at FROM signals"
        ).fetchall()
    }
    ve_storage.init_db(legacy_db)
    after = {
        r["id"]: tuple(r)
        for r in legacy_db.execute(
            "SELECT id, kind, title, detail, source, source_excerpt, source_ref,"
            " confidence, linked_initiative_id, linked_project_id, linked_task_id,"
            " linked_asset_ids, status, created_at, updated_at FROM signals"
        ).fetchall()
    }
    assert after == before  # row count and every other column byte-identical
    assert all(
        r["user_id"] is None
        for r in legacy_db.execute("SELECT user_id FROM signals").fetchall()
    )


def test_migration_idempotent(legacy_db):
    ve_storage.init_db(legacy_db)
    snap = legacy_db.execute("SELECT * FROM signals ORDER BY id").fetchall()
    ve_storage.init_db(legacy_db)
    assert legacy_db.execute("SELECT * FROM signals ORDER BY id").fetchall() == snap
    cols = [c[1] for c in legacy_db.execute("PRAGMA table_info(signals)")]
    assert cols.count("user_id") == 1


def test_fresh_db_has_column_and_index(ve_ctx):
    cols = [c[1] for c in ve_ctx.execute("PRAGMA table_info(signals)")]
    assert "user_id" in cols
    indexes = [
        r[0]
        for r in ve_ctx.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='signals'"
        )
    ]
    assert "idx_signals_user_id" in indexes


def test_no_backfill_line(legacy_db):
    """The negative that distinguishes quarantine from backfill: after
    migration, no pre-existing row carries a non-NULL user_id."""
    ve_storage.init_db(legacy_db)
    count = legacy_db.execute(
        "SELECT COUNT(*) FROM signals WHERE user_id IS NOT NULL"
    ).fetchone()[0]
    assert count == 0


# -- founder correction 2: fail-closed rollback ----------------------------


def test_rollback_disables_signals_without_restoring_shared_access(
    ve_ctx, two_users, monkeypatch
):
    """With the rollback kill switch set, the signals surface is
    unavailable (503) and Radar's signals bucket is empty — the shared
    pool is never served again. With it unset, normal scoped behavior
    resumes."""
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    monkeypatch.setenv("ZENAF_SIGNALS_DISABLED", "1")
    assert SigS.signals_disabled() is True
    with pytest.raises(SigS.SignalsDisabledError):
        SigS.list_signals(uid_a)
    app_a = _make_app(uid_a)
    for method, path, payload in (
        ("GET", "/vision-execution/signals", None),
        ("POST", "/vision-execution/signals", [_signal_payload()]),
        ("PATCH", f"/vision-execution/signals/{two_users['sig_a']['id']}", {"status": "resolved"}),
    ):
        status, body = _run_asgi(app_a, method, path, payload)
        assert status == 503, (method, path, body)
    _, radar_body = _run_asgi(app_a, "GET", "/vision-execution/radar")
    assert radar_body["signals"] == []
    # No rows leak through any path while disabled — not even the caller's.
    assert "A-signal" not in json.dumps(radar_body)


def test_rollback_flag_defaults_off(ve_ctx, two_users, monkeypatch):
    monkeypatch.delenv("ZENAF_SIGNALS_DISABLED", raising=False)
    assert SigS.signals_disabled() is False
    assert len(SigS.list_signals(two_users["uid_a"])) == 1


# -- criterion 9: authenticated frontend workflows --------------------------


def test_frontend_create_flow(ve_ctx, two_users):
    uid_a = two_users["uid_a"]
    app = _make_app(uid_a)
    status, body = _run_asgi(
        app, "POST", "/vision-execution/signals",
        [{
            "kind": "risk",
            "title": "meeting risk",
            "detail": "d",
            "source": "meeting-extraction",
            "sourceRef": {"type": "meeting", "id": "m1"},
        }],
    )
    assert status == 200, body
    assert body[0]["user_id"] == uid_a
    assert body[0]["source_ref"] == {"type": "meeting", "id": "m1"}


def test_frontend_acknowledge_resolve_dismiss(ve_ctx, two_users):
    uid_a = two_users["uid_a"]
    sig_a = two_users["sig_a"]
    app = _make_app(uid_a)
    status, body = _run_asgi(
        app, "PATCH", f"/vision-execution/signals/{sig_a['id']}",
        {"status": "acknowledged"},
    )
    assert status == 200, body
    assert body["status"] == "acknowledged"
    status, body = _run_asgi(
        app, "PATCH", f"/vision-execution/signals/{sig_a['id']}",
        {"status": "resolved"},
    )
    assert status == 200, body
    assert body["status"] == "resolved"
    # A second signal exercises dismiss.
    sig2 = SigS.create_signals(
        [SigModels.SignalCreate(kind="info", title="t2", source="test")], uid_a
    )[0]
    status, body = _run_asgi(
        app, "PATCH", f"/vision-execution/signals/{sig2['id']}",
        {"status": "dismissed"},
    )
    assert status == 200, body
    assert body["status"] == "dismissed"


def test_frontend_radar_list(ve_ctx, two_users):
    uid_a = two_users["uid_a"]
    app = _make_app(uid_a)
    status, body = _run_asgi(app, "GET", "/vision-execution/radar")
    assert status == 200, body
    assert {s["id"] for s in body["signals"]} == {two_users["sig_a"]["id"]}
    item = body["signals"][0]
    assert item["title"] == "A-signal"
    assert item["severity"] in ("high", "medium")


# -- Track A: anonymous requests are rejected before any access ----------
# (Added on the rebuild against feb2c9e: Track A never landed as a
# separate patch, so its 401 criteria are covered here.)


def test_anonymous_get_signals_401(ve_ctx, two_users):
    app = _make_app()  # no dependency override: the real auth runs
    status, body = _run_asgi(app, "GET", "/vision-execution/signals")
    assert status == 401, body


def test_anonymous_post_signals_401_no_mutation(ve_ctx, two_users):
    before = ve_ctx.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    app = _make_app()
    status, body = _run_asgi(
        app, "POST", "/vision-execution/signals", [_signal_payload()]
    )
    assert status == 401, body
    assert ve_ctx.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == before


def test_anonymous_patch_signal_401_row_unchanged(ve_ctx, two_users):
    sig_a = two_users["sig_a"]
    before = tuple(_row(ve_ctx, "signals", sig_a["id"]))
    app = _make_app()
    status, body = _run_asgi(
        app, "PATCH", f"/vision-execution/signals/{sig_a['id']}",
        {"status": "dismissed"},
    )
    assert status == 401, body
    assert tuple(_row(ve_ctx, "signals", sig_a["id"])) == before


def test_anonymous_401_precedes_service_access(ve_ctx, two_users, monkeypatch):
    """Spy variant: with the service rigged to raise, an anonymous
    request still returns 401 — auth runs before service/storage."""
    def _boom(*a, **k):
        raise AssertionError("service must not be reached anonymously")

    monkeypatch.setattr(ve_routes.SigS, "create_signals", _boom)
    monkeypatch.setattr(ve_routes.SigS, "list_signals", _boom)
    monkeypatch.setattr(ve_routes.SigS, "update_signal", _boom)
    app = _make_app()
    assert _run_asgi(app, "GET", "/vision-execution/signals")[0] == 401
    assert _run_asgi(app, "POST", "/vision-execution/signals", [_signal_payload()])[0] == 401
    assert _run_asgi(
        app, "PATCH", f"/vision-execution/signals/{two_users['sig_a']['id']}",
        {"status": "resolved"},
    )[0] == 401


def test_invalid_session_cookie_401(ve_ctx, two_users):
    app = _make_app()
    status, body = _run_asgi(
        app, "GET", "/vision-execution/signals",
        cookies={"zenaf_session": "not-a-real-session-token"},
    )
    assert status == 401, body
