"""Migration execution route tests (design v2, Joshua).

Execution is backup-first, locked, verified before and after each
write, and collection-level fail-closed. These tests pin each
guarantee: byte-identical verified backups, lock contention
refusing cleanly, partial runs stopping at the first failure with
exact modified / failed / not-attempted accounting, and the route
gates (owner, confirm, lock → 409). No live API calls, no live
store.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user
from local_ai.build_room import migration as migration_mod
from local_ai.build_room.migration import execute_migration
from local_ai.build_room.record_completeness import check_standing_invariants as real_check

OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
OTHER = {"id": "someone-else"}


def _artifact(meeting_id, *, registry=True, standing=False):
    artifact = {
        "status": "DRAFT_EXPERIMENTAL",
        "meeting_id": meeting_id,
        "interactions": [],
    }
    if registry:
        artifact["claim_registry"] = [
            {"id": "C1", "participant": "GPT", "phase": "opening",
             "status": "Observed", "text": "Authority confusion is a risk.",
             "supersedes": None, "withdraws": None,
             "epistemic_assessment": "unresolved", "assessment_sources": []},
        ]
    if standing:
        artifact["claim_standing"] = {"version": 1, "entries": []}
    return artifact


def _write(path: Path, payload) -> None:
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")


def _hash_tree(store: Path) -> dict[str, str]:
    return {
        str(p.relative_to(store)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(store.rglob("*")) if p.is_file()
    }


def _fake_store(store: Path) -> dict[str, Path]:
    store.mkdir(parents=True, exist_ok=True)
    paths = {
        "aaa": store / "meeting_aaa.draft_artifact.json",
        "bbb": store / "meeting_bbb.draft_artifact.json",
        "ccc": store / "meeting_ccc.draft_artifact.json",
    }
    _write(paths["aaa"], _artifact("aaa"))
    _write(paths["bbb"], _artifact("bbb", standing=True))
    _write(paths["ccc"], _artifact("ccc", registry=False))
    _write(store / "meeting_ddd.transcript.json", {"entries": []})
    return paths


def _backup_dirs(store: Path) -> list[Path]:
    backups = store / "backups"
    if not backups.is_dir():
        return []
    return sorted(p for p in backups.iterdir() if p.is_dir())


def _manifest(backup_dir: Path) -> dict:
    return json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- unit


def test_execute_full_run_backs_up_verifies_and_migrates(tmp_path):
    store = tmp_path / "store"
    paths = _fake_store(store)
    originals = {name: path.read_bytes() for name, path in paths.items()}
    report = execute_migration(store)
    assert report["status"] == "completed"
    assert report["feature_flag_changed"] is False
    assert report["totals"]["migrated"] == 1
    assert report["totals"]["already_present"] == 1
    assert report["totals"]["unmigrated"] == 1
    assert report["totals"]["files"] == 3
    # Migrated file gained the section; its registry is untouched.
    migrated = json.loads(paths["aaa"].read_text(encoding="utf-8"))
    assert "claim_standing" in migrated
    assert migrated["claim_registry"] == _artifact("aaa")["claim_registry"]
    # Already-present and unmigrated files byte-identical.
    assert paths["bbb"].read_bytes() == originals["bbb"]
    assert paths["ccc"].read_bytes() == originals["ccc"]
    # Backup: one run dir, byte-identical originals, manifest digests.
    dirs = _backup_dirs(store)
    assert len(dirs) == 1
    manifest = _manifest(dirs[0])
    for name, path in paths.items():
        backup = dirs[0] / path.name
        assert backup.read_bytes() == originals[name]
        assert manifest["files"][path.name] == hashlib.sha256(originals[name]).hexdigest()
    assert manifest["run_id"] == report["run_id"]
    # Lock released.
    assert not (store / ".migration.lock").exists()
    # Backup files are not treated as artifacts by a later inventory.
    from local_ai.build_room.migration import inventory_store_dir
    assert inventory_store_dir(store)["totals"]["files"] == 3


def test_execute_second_run_is_idempotent(tmp_path):
    store = tmp_path / "store"
    paths = _fake_store(store)
    execute_migration(store)
    after_first = _hash_tree(store)
    report = execute_migration(store)
    assert report["status"] == "completed"
    assert report["totals"]["migrated"] == 0
    assert report["totals"]["already_present"] == 2
    assert report["totals"]["unmigrated"] == 1
    # No pre-existing file changed; only a fresh backup directory
    # was added (new keys in the second tree are expected).
    after_second = _hash_tree(store)
    changed = {k for k in after_first if after_second.get(k) != after_first[k]}
    assert changed == set()
    assert len(_backup_dirs(store)) == 2


def test_execute_lock_held_refuses_cleanly(tmp_path):
    store = tmp_path / "store"
    paths = _fake_store(store)
    (store / ".migration.lock").mkdir()
    (store / ".migration.lock" / "lock.json").write_text('{"run_id": "other"}\n')
    before = _hash_tree(store)
    report = execute_migration(store)
    assert report["status"] == "aborted_before_writes"
    assert report["lock_held"] is True
    assert report["totals"]["files"] == 0
    # Nothing written, no backup created, pre-existing lock untouched.
    assert _hash_tree(store) == before
    assert _backup_dirs(store) == []
    assert (store / ".migration.lock" / "lock.json").read_text() == '{"run_id": "other"}\n'


def test_execute_backup_verification_failure_aborts_before_writes(tmp_path, monkeypatch):
    store = tmp_path / "store"
    paths = _fake_store(store)
    before = _hash_tree(store)
    real_copy = shutil.copyfile

    def truncating_copy(src, dst, **kw):
        real_copy(src, dst, **kw)
        data = Path(dst).read_bytes()
        Path(dst).write_bytes(data[: len(data) // 2])

    monkeypatch.setattr(migration_mod.shutil, "copyfile", truncating_copy)
    report = execute_migration(store)
    assert report["status"] == "aborted_before_writes"
    assert "backup failed" in report["reason"]
    assert report["totals"]["migrated"] == 0
    # Artifact files untouched (backup dir itself is new, ignore it).
    for name, path in paths.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before[str(path.relative_to(store))]


def test_execute_prewrite_failure_stops_run_with_exact_accounting(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    for name in ("aaa", "bbb", "ccc"):
        _write(store / f"meeting_{name}.draft_artifact.json", _artifact(name))
    calls = {"n": 0}

    def failing_second(claims_full, interactions, table):
        calls["n"] += 1
        # Call 1: aaa pre-write (pass). Call 2: aaa post-write (pass).
        # Call 3: bbb pre-write (fail).
        if calls["n"] == 3:
            return False, ["forced pre-write failure"]
        return real_check(claims_full, interactions, table)

    monkeypatch.setattr(migration_mod, "check_standing_invariants", failing_second)
    report = execute_migration(store)
    assert report["status"] == "partially_completed"
    by_file = {f["file"]: f for f in report["files"]}
    assert by_file["meeting_aaa.draft_artifact.json"]["verdict"] == "migrated"
    assert by_file["meeting_bbb.draft_artifact.json"]["verdict"] == "verification_failed"
    assert by_file["meeting_ccc.draft_artifact.json"]["verdict"] == "not_attempted"
    assert report["totals"]["migrated"] == 1
    assert report["totals"]["verification_failed"] == 1
    assert report["totals"]["not_attempted"] == 1
    # bbb and ccc never written.
    assert "claim_standing" not in json.loads(
        (store / "meeting_bbb.draft_artifact.json").read_text(encoding="utf-8"))
    assert "claim_standing" not in json.loads(
        (store / "meeting_ccc.draft_artifact.json").read_text(encoding="utf-8"))


def test_execute_postwrite_failure_reports_requires_recovery(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    for name in ("aaa", "bbb"):
        _write(store / f"meeting_{name}.draft_artifact.json", _artifact(name))
    calls = {"n": 0}

    def failing_postwrite(claims_full, interactions, table):
        calls["n"] += 1
        # Call 1: aaa pre-write (pass). Call 2: aaa post-write (fail).
        if calls["n"] == 2:
            return False, ["forced post-write failure"]
        return real_check(claims_full, interactions, table)

    monkeypatch.setattr(migration_mod, "check_standing_invariants", failing_postwrite)
    report = execute_migration(store)
    assert report["status"] == "partially_completed"
    by_file = {f["file"]: f for f in report["files"]}
    assert by_file["meeting_aaa.draft_artifact.json"]["verdict"] == "requires_recovery"
    assert by_file["meeting_bbb.draft_artifact.json"]["verdict"] == "not_attempted"
    # aaa WAS written (that is the recovery state); bbb untouched.
    assert "claim_standing" in json.loads(
        (store / "meeting_aaa.draft_artifact.json").read_text(encoding="utf-8"))
    assert "claim_standing" not in json.loads(
        (store / "meeting_bbb.draft_artifact.json").read_text(encoding="utf-8"))


def test_execute_missing_directory_reports_without_raising():
    report = execute_migration("/nonexistent/store/dir")
    assert report["status"] == "aborted_before_writes"
    assert "error" in report


# ---------------------------------------------------------------- route


def _call_post(app, path: str, payload: dict) -> tuple[int, dict]:
    raw = json.dumps(payload).encode()
    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(raw)).encode())],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    messages: list[dict] = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages
                    if m["type"] == "http.response.body")
    return start["status"], json.loads(body.decode() or "{}")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store_mod

    monkeypatch.setattr(br_routes, "get_build_room_store_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(ve_store_mod, "get_owner_user_id", lambda: OWNER["id"])
    application = FastAPI()
    application.include_router(br_routes.router)
    return application


def test_route_owner_with_confirm_migrates(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    _fake_store(store)
    status, body = _call_post(app, "/build-room/artifacts/migrate", {"confirm": True})
    assert status == 200, body
    assert body["status"] == "completed"
    assert body["totals"]["migrated"] == 1
    assert body["feature_flag_changed"] is False
    assert body["backup_dir"] is not None


def test_route_unauthenticated_is_401(app):
    status, _ = _call_post(app, "/build-room/artifacts/migrate", {"confirm": True})
    assert status == 401


def test_route_non_owner_is_403(app):
    app.dependency_overrides[get_current_user] = lambda: OTHER
    status, _ = _call_post(app, "/build-room/artifacts/migrate", {"confirm": True})
    assert status == 403


def test_route_missing_or_false_confirm_is_400_and_writes_nothing(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    _fake_store(store)
    before = _hash_tree(store)
    for payload in ({}, {"confirm": False}):
        status, _ = _call_post(app, "/build-room/artifacts/migrate", payload)
        assert status == 400
    assert _hash_tree(store) == before
    assert _backup_dirs(store) == []


def test_route_lock_held_is_409(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    _fake_store(store)
    (store / ".migration.lock").mkdir()
    status, body = _call_post(app, "/build-room/artifacts/migrate", {"confirm": True})
    assert status == 409
    assert body["detail"]["status"] == "aborted_before_writes"
    assert body["detail"]["lock_held"] is True
