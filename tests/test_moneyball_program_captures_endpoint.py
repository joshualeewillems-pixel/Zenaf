"""Moneyball program-captures endpoint tests (PR: captures endpoint).

Owner-only, read-only retrieval of this program's deterministic
capture records. No live API calls, no real key values, no spend
anywhere. Fixture ledgers + capture files stand in for the runner's
output; the endpoint's own logic (owner gate, ledger-order meetings
with capture contents, explicit failure never partial data, no side
effects, no transcript/artifact reads) is what these tests pin.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user

OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
OTHER = {"id": "someone-else"}


def _call(app, method: str, path: str) -> tuple[int, dict]:
    scope = {
        "type": "http", "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"content-length", b"0")],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    messages: list[dict] = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages
                     if m["type"] == "http.response.body")
    return start["status"], json.loads(body.decode() or "{}")


def _call_get(app, path: str) -> tuple[int, dict]:
    return _call(app, "GET", path)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store_mod

    monkeypatch.setattr(br_routes, "get_build_room_store_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(ve_store_mod, "get_owner_user_id", lambda: OWNER["id"])
    application = FastAPI()
    application.include_router(br_routes.router)
    return application


def _write_program(store: Path, meetings, captures: dict[str, dict]) -> None:
    store.mkdir(parents=True, exist_ok=True)
    (store / "moneyball_program_ledger.json").write_text(
        json.dumps({
            "cap_usd": 2.0,
            "cumulative_reserved_usd": round(
                sum(m["committed_usd"] for m in meetings), 6
            ),
            "meetings": meetings,
        }) + "\n",
        encoding="utf-8",
    )
    for meeting_id, capture in captures.items():
        (store / f"meeting_{meeting_id}.comparison_capture.json").write_text(
            json.dumps(capture) + "\n", encoding="utf-8"
        )


def _meeting_record(meeting_id, condition="A", committed=0.25):
    return {
        "packet_work_item": f"packet-{meeting_id}",
        "condition": condition,
        "meeting_id": meeting_id,
        "allocation_usd": 0.5,
        "committed_usd": committed,
        "ok": True,
        # Ledger path strings must never leak into the response.
        "artifact_path": "/app/data/should-not-leak.json",
        "capture_path": "/app/data/should-not-leak-either.json",
    }


def _capture(meeting_id, condition="A"):
    return {
        "meeting_id": meeting_id,
        "packet_hash": f"hash-{meeting_id}",
        "packet_work_item": f"packet-{meeting_id}",
        "condition": condition,
        "role_brief_version": "v1" if condition == "B" else None,
        "role_brief_seats": ["Muse"] if condition == "B" else [],
        "base_prompt_hashes": {"phase1": f"base-{meeting_id}"},
        "allocation_usd": 0.5,
        "committed_usd": 0.25,
        "ok": True,
        "transcript": [{"kind": "contribution", "participant": "Muse", "text": "claim text"}],
        "claim_registry": [{"id": "C1", "author": "Muse", "text": "claim text"}],
        "cap_budget": {"committed_usd": 0.25},
        "raw_responses": [{"participant": "Muse", "text": "claim text"}],
        "raw_text_retained": True,
    }


# ---------------------------------------------------------------- gates


def test_captures_non_owner_is_403(app):
    app.dependency_overrides[get_current_user] = lambda: OTHER
    status, body = _call_get(app, "/build-room/program/captures")
    assert status == 403
    assert body["detail"] == "Build-room meetings are owner-only"


def test_captures_unauthenticated_is_401(app):
    status, _ = _call_get(app, "/build-room/program/captures")
    assert status == 401


# ---------------------------------------------------------------- happy path


def test_captures_returns_ledger_meetings_with_capture_contents(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A"), _meeting_record("bbb222", "B")]
    _write_program(store, meetings, {
        "aaa111": _capture("aaa111", "A"),
        "bbb222": _capture("bbb222", "B"),
    })
    status, body = _call_get(app, "/build-room/program/captures")
    assert status == 200, body
    assert body["cap_usd"] == 2.0
    assert body["cumulative_reserved_usd"] == 0.5
    assert body["meetings_completed"] == 2
    # Ledger order preserved.
    assert [m["meeting_id"] for m in body["meetings"]] == ["aaa111", "bbb222"]
    assert [m["condition"] for m in body["meetings"]] == ["A", "B"]
    for m in body["meetings"]:
        assert m["packet_work_item"] == f"packet-{m['meeting_id']}"
        assert m["ok"] is True
        assert m["allocation_usd"] == 0.5
        assert m["committed_usd"] == 0.25
        capture = m["capture"]
        assert capture["meeting_id"] == m["meeting_id"]
        assert capture["claim_registry"][0]["id"] == "C1"
        assert capture["base_prompt_hashes"]["phase1"] == f"base-{m['meeting_id']}"
        assert capture["cap_budget"]["committed_usd"] == 0.25
    assert body["meetings"][1]["capture"]["role_brief_version"] == "v1"
    # No server paths anywhere in the response.
    assert "artifact_path" not in json.dumps(body)
    assert "capture_path" not in json.dumps(body)
    assert "should-not-leak" not in json.dumps(body)
    assert "/app/data" not in json.dumps(body)


def test_captures_does_not_read_transcript_or_artifact_files(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    _write_program(store, meetings, {"aaa111": _capture("aaa111", "A")})
    # Decoy files the endpoint must never open.
    (store / "meeting_aaa111.transcript.json").write_text(
        json.dumps({"marker": "TRANSCRIPT-DECOY"}), encoding="utf-8"
    )
    (store / "meeting_aaa111.draft_artifact.json").write_text(
        json.dumps({"marker": "ARTIFACT-DECOY"}), encoding="utf-8"
    )
    status, body = _call_get(app, "/build-room/program/captures")
    assert status == 200, body
    assert "TRANSCRIPT-DECOY" not in json.dumps(body)
    assert "ARTIFACT-DECOY" not in json.dumps(body)


# ---------------------------------------------------------------- explicit failure, never partial


def test_captures_missing_ledger_is_404(app):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    status, body = _call_get(app, "/build-room/program/captures")
    assert status == 404
    assert "ledger not found" in body["detail"]
    assert "meetings" not in body


def test_captures_missing_capture_fails_whole_request_not_partial(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A"), _meeting_record("bbb222", "B")]
    # Only the first meeting's capture exists: the request must fail
    # outright, never return the first meeting alone.
    _write_program(store, meetings, {"aaa111": _capture("aaa111", "A")})
    status, body = _call_get(app, "/build-room/program/captures")
    assert status == 500, body
    assert "bbb222" in body["detail"]
    assert "claim_registry" not in json.dumps(body)
    assert "meetings" not in body


def test_captures_unreadable_capture_is_500(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    _write_program(store, meetings, {"aaa111": _capture("aaa111", "A")})
    (store / "meeting_aaa111.comparison_capture.json").write_text(
        "{not json", encoding="utf-8"
    )
    status, body = _call_get(app, "/build-room/program/captures")
    assert status == 500, body
    assert "aaa111" in body["detail"]


def test_captures_traversal_meeting_id_is_refused(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("../evil", "A")]
    _write_program(store, meetings, {})
    status, body = _call_get(app, "/build-room/program/captures")
    assert status == 500, body
    assert "invalid meeting_id" in body["detail"]


# ---------------------------------------------------------------- read-only


def test_captures_twice_identical_and_no_side_effects(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A"), _meeting_record("bbb222", "B")]
    _write_program(store, meetings, {
        "aaa111": _capture("aaa111", "A"),
        "bbb222": _capture("bbb222", "B"),
    })
    before_files = sorted(p.name for p in store.iterdir())
    before_ledger = (store / "moneyball_program_ledger.json").read_bytes()
    before_mtime = (store / "moneyball_program_ledger.json").stat().st_mtime_ns
    status1, body1 = _call_get(app, "/build-room/program/captures")
    status2, body2 = _call_get(app, "/build-room/program/captures")
    assert status1 == status2 == 200
    assert body1 == body2
    assert sorted(p.name for p in store.iterdir()) == before_files
    assert (store / "moneyball_program_ledger.json").read_bytes() == before_ledger
    assert (store / "moneyball_program_ledger.json").stat().st_mtime_ns == before_mtime
