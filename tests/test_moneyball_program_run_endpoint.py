"""Moneyball program-run endpoint tests (PR: run endpoint, code only).

No live API calls, no real key values, no spend anywhere. The program
runner is replaced by fakes via monkeypatch; the endpoint's own logic
(gates, cap/confirm refusal, single-shot ledger, 409 on concurrent
start, ledger-derived status) is what these tests pin. The runner
itself is covered by tests/test_moneyball_role_only_build.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user
from local_ai.build_room import moneyball_program
from local_ai.build_room.moneyball_program import (
    PACKET_SHA256,
    PROGRAM_MEETING_COUNT,
    build_program_specs,
    load_packet_file,
    load_program_packets,
)
from local_ai.build_room.program_runner import ProgramResult, packet_hash
from local_ai.build_room.role_briefs import (
    ROLE_BRIEF_VERSION,
    role_prompt_extras,
)

OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
OTHER = {"id": "someone-else"}


def _call(app, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    raw = json.dumps(payload).encode() if payload is not None else b""
    scope = {
        "type": "http", "http_version": "1.1", "method": method, "scheme": "http",
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


def _call_post(app, path: str, payload: dict) -> tuple[int, dict]:
    return _call(app, "POST", path, payload)


def _call_get(app, path: str) -> tuple[int, dict]:
    return _call(app, "GET", path)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store_mod

    monkeypatch.setattr(br_routes, "get_build_room_store_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(ve_store_mod, "get_owner_user_id", lambda: OWNER["id"])
    moneyball_program.PROGRAM_TRACKER.reset()
    application = FastAPI()
    application.include_router(br_routes.router)
    return application


def _wait_finished(timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = moneyball_program.PROGRAM_TRACKER.snapshot()
        if snap is not None and snap["state"] == "finished":
            return snap
        time.sleep(0.05)
    raise AssertionError("program thread did not finish in time")


def _ledger_payload(meetings, cap_usd=2.0):
    return {
        "cap_usd": cap_usd,
        "cumulative_reserved_usd": round(
            sum(m["committed_usd"] for m in meetings), 6
        ),
        "meetings": meetings,
    }


def _meeting_record(i, condition="A"):
    return {
        "packet_work_item": f"packet-{i}",
        "condition": condition,
        "meeting_id": f"meeting-{i}",
        "allocation_usd": 0.5,
        "committed_usd": 0.25,
        "ok": True,
        "artifact_path": "/app/data/should-not-leak.json",
        "capture_path": "/app/data/should-not-leak-either.json",
    }


# ---------------------------------------------------------------- gates


def test_route_non_owner_is_403(app):
    app.dependency_overrides[get_current_user] = lambda: OTHER
    status, _ = _call_post(app, "/build-room/program/run", {"cap_usd": 2.0, "confirm": True})
    assert status == 403
    status, _ = _call_get(app, "/build-room/program/status")
    assert status == 403


def test_route_unauthenticated_is_401(app):
    status, _ = _call_post(app, "/build-room/program/run", {"cap_usd": 2.0, "confirm": True})
    assert status == 401


# ---------------------------------------------------------------- refusal


def test_missing_or_nonpositive_cap_is_refused_and_starts_nothing(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    for payload in ({"confirm": True}, {}, {"cap_usd": 0, "confirm": True}, {"cap_usd": -5, "confirm": True}):
        status, _ = _call_post(app, "/build-room/program/run", payload)
        assert status == 422, payload
    assert moneyball_program.PROGRAM_TRACKER.snapshot() is None
    assert not (tmp_path / "store" / "moneyball_program_ledger.json").exists()


def test_missing_or_false_confirm_is_400_and_starts_nothing(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    for payload in ({"cap_usd": 2.0}, {"cap_usd": 2.0, "confirm": False}):
        status, _ = _call_post(app, "/build-room/program/run", payload)
        assert status == 400, payload
    assert moneyball_program.PROGRAM_TRACKER.snapshot() is None
    assert not (tmp_path / "store" / "moneyball_program_ledger.json").exists()


def test_pricing_expired_is_400_and_starts_nothing(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    monkeypatch.setattr(br_routes, "pricing_expired", lambda *a: True)
    status, body = _call_post(app, "/build-room/program/run", {"cap_usd": 2.0, "confirm": True})
    assert status == 400
    assert "expired" in body["detail"]
    assert moneyball_program.PROGRAM_TRACKER.snapshot() is None


# ---------------------------------------------------------------- start


def test_owner_start_runs_fixed_program(app, tmp_path, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    seen: dict = {}

    def fake_run_program(specs, *, cap_usd, ledger_path, store_dir, **kwargs):
        seen["specs"] = specs
        seen["cap_usd"] = cap_usd
        seen["ledger_path"] = ledger_path
        seen["store_dir"] = store_dir
        return ProgramResult(status="completed", cap_usd=cap_usd,
                             cumulative_reserved_usd=0.0, meetings=[])

    monkeypatch.setattr(br_routes, "run_program", fake_run_program)
    status, body = _call_post(app, "/build-room/program/run", {"cap_usd": 2.0, "confirm": True})
    assert status == 202, body
    assert body["state"] == "started"
    assert body["cap_usd"] == 2.0
    assert body["run_id"]
    assert [m["condition"] for m in body["meetings"]] == ["A", "B", "A", "B", "A", "B"]
    snap = _wait_finished()
    assert snap["result_status"] == "completed"

    specs = seen["specs"]
    assert len(specs) == PROGRAM_MEETING_COUNT
    assert seen["cap_usd"] == 2.0
    assert seen["ledger_path"] == tmp_path / "store" / "moneyball_program_ledger.json"
    assert seen["store_dir"] == tmp_path / "store"
    expected_work_items = [
        "Build-Council Room series M2 — steward increment E scope",
        "Zenaf build-council — Weaver encounter architecture audit evaluation (single meeting, packet-only)",
        "Build-Council Room — adapter/referral spec review",
    ]
    for i, work_item in enumerate(expected_work_items):
        pair = specs[2 * i: 2 * i + 2]
        assert [s.condition for s in pair] == ["A", "B"]
        # Same packet OBJECT across A/B: byte identity, not just equality.
        assert pair[0].packet is pair[1].packet
        assert packet_hash(pair[0].packet) == packet_hash(pair[1].packet)
        assert pair[0].packet.work_item == work_item
        assert pair[0].role_prompt_extras is None
        assert pair[0].role_brief_version is None
        assert pair[1].role_prompt_extras == role_prompt_extras()
        assert "GPT" not in pair[1].role_prompt_extras
        assert pair[1].role_brief_version == ROLE_BRIEF_VERSION
        assert pair[0].tools_enabled is False and pair[1].tools_enabled is False
        assert pair[0].principal.account_user_id == OWNER["id"]
    assert [s.estimated_reservation_usd for s in specs] == [
        0.224, 0.224, 0.255, 0.255, 0.241, 0.241,
    ]


def test_concurrent_start_is_409(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    gate = threading.Event()

    def fake_run_program(specs, *, cap_usd, ledger_path, store_dir, **kwargs):
        gate.wait(timeout=10)
        return ProgramResult(status="completed", cap_usd=cap_usd,
                             cumulative_reserved_usd=0.0, meetings=[])

    monkeypatch.setattr(br_routes, "run_program", fake_run_program)
    status, _ = _call_post(app, "/build-room/program/run", {"cap_usd": 2.0, "confirm": True})
    assert status == 202
    status, body = _call_post(app, "/build-room/program/run", {"cap_usd": 2.0, "confirm": True})
    assert status == 409
    assert "already active" in body["detail"]
    gate.set()
    _wait_finished()


def test_second_start_after_recorded_meeting_is_409(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    (store / "moneyball_program_ledger.json").write_text(
        json.dumps(_ledger_payload([_meeting_record(1)])) + "\n", encoding="utf-8"
    )
    status, body = _call_post(app, "/build-room/program/run", {"cap_usd": 2.0, "confirm": True})
    assert status == 409
    assert "already run" in body["detail"]
    assert moneyball_program.PROGRAM_TRACKER.snapshot() is None


def test_ledger_cap_mismatch_is_409(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    (store / "moneyball_program_ledger.json").write_text(
        json.dumps(_ledger_payload([], cap_usd=1.0)) + "\n", encoding="utf-8"
    )
    status, body = _call_post(app, "/build-room/program/run", {"cap_usd": 2.0, "confirm": True})
    assert status == 409
    assert "cap mismatch" in body["detail"]


def test_thread_exception_surfaces_in_status(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER

    def fake_run_program(specs, *, cap_usd, ledger_path, store_dir, **kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(br_routes, "run_program", fake_run_program)
    status, _ = _call_post(app, "/build-room/program/run", {"cap_usd": 2.0, "confirm": True})
    assert status == 202
    snap = _wait_finished()
    assert "RuntimeError" in snap["error"]
    status, body = _call_get(app, "/build-room/program/status")
    assert status == 200
    assert body["state"] == "error"
    assert "RuntimeError" in body["error"]


# ---------------------------------------------------------------- status


def test_status_not_started_without_ledger(app):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    status, body = _call_get(app, "/build-room/program/status")
    assert status == 200
    assert body["state"] == "not_started"
    assert body["cap_usd"] is None
    assert body["cumulative_reserved_usd"] == 0.0
    assert body["remaining_usd"] is None
    assert body["meetings"] == []


def test_status_reports_ledger_without_leaking_paths(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    (store / "moneyball_program_ledger.json").write_text(
        json.dumps(_ledger_payload([_meeting_record(1), _meeting_record(2, "B")])) + "\n",
        encoding="utf-8",
    )
    status, body = _call_get(app, "/build-room/program/status")
    assert status == 200
    # No live thread and 2 of 6 meetings: interrupted (e.g. restarted).
    assert body["state"] == "interrupted"
    assert body["cap_usd"] == 2.0
    assert body["cumulative_reserved_usd"] == 0.5
    assert body["remaining_usd"] == 1.5
    assert body["meetings_completed"] == 2
    assert [m["condition"] for m in body["meetings"]] == ["A", "B"]
    assert "artifact_path" not in json.dumps(body)
    assert "capture_path" not in json.dumps(body)


def test_status_completed_with_full_ledger(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    (store / "moneyball_program_ledger.json").write_text(
        json.dumps(_ledger_payload([_meeting_record(i) for i in range(6)])) + "\n",
        encoding="utf-8",
    )
    status, body = _call_get(app, "/build-room/program/status")
    assert status == 200
    assert body["state"] == "completed"
    assert body["meetings_completed"] == 6


# ---------------------------------------------------------------- packets


def test_vendored_packets_match_recorded_hashes():
    packets_dir = Path(moneyball_program.__file__).resolve().parent / "moneyball_packets"
    for key, digest in PACKET_SHA256.items():
        path = packets_dir / f"{key}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, key


def test_program_packets_are_pinned_and_ab_identical():
    packets = load_program_packets()
    assert sorted(packets) == ["audit", "m2", "spec"]
    specs = build_program_specs(principal=None)
    for i in range(3):
        pair = specs[2 * i: 2 * i + 2]
        assert pair[0].packet is pair[1].packet
        assert packet_hash(pair[0].packet) == packet_hash(pair[1].packet)
    assert specs[0].packet.work_item.startswith("Build-Council Room series M2")
    assert specs[2].packet.work_item.startswith("Zenaf build-council")
    assert specs[4].packet.work_item.startswith("Build-Council Room — adapter")


def test_load_packet_rejects_malformed(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"work_item": "x"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_packet_file(bad)
    bad.write_text(
        json.dumps({"work_item": "x", "question": "y", "context": "not-a-list"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_packet_file(bad)
