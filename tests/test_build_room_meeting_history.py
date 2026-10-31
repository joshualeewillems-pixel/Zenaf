"""Meeting-history retrieval endpoint tests (retrieval-history PR).

Owner-only, read-only retrieval of stored build-council meeting
records from the store dir — the one complete source for standalone
AND program meetings. No live API calls, no real key values, no
spend anywhere. Fixture store files stand in for the runner's
output; the endpoints' own logic (owner gate, verbatim content,
explicit 404/500 never silent omission, mtime ordering, bounded
paging, no side effects) is what these tests pin.

Deliberately NOT covered here: /program/captures behavior (pinned
by its own test files, run unflagged in verification) and any
write path — these endpoints have none.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user

OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
OTHER = {"id": "someone-else"}


def _call(app, method: str, path: str) -> tuple[int, dict]:
    # Split "?..." off so FastAPI parses the query parameters.
    raw_path, _, query = path.partition("?")
    scope = {
        "type": "http", "http_version": "1.1", "method": method, "scheme": "http",
        "path": raw_path, "raw_path": path.encode(),
        "query_string": query.encode(),
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


def _transcript(meeting_id, texts=("first claim", "second claim")):
    entries = [{"kind": "convene", "participant": None, "text": "convene text"}]
    entries += [
        {"kind": "contribution", "participant": "Muse", "text": text}
        for text in texts
    ]
    return {"meeting_id": meeting_id, "entries": entries}


def _artifact(meeting_id, work_item="fix the thing", ok=True, n_claims=2):
    return {
        "meeting_id": meeting_id,
        "work_item": work_item,
        "question": "what should change?",
        "claim_registry": [
            {"id": f"C{i + 1}", "author": "Muse", "text": f"claim {i + 1}"}
            for i in range(n_claims)
        ],
        "ok": ok,
        "transjective_record": {
            "validation_phase": "final",
            "conformant": False,
            "validation": {"errors": [{"code": "E6"}]},
        },
        "transjective_validation_reports": [
            {"phase": "opening", "conformant": True, "errors": []}
        ],
    }


def _write_meeting(store: Path, meeting_id, transcript=None,
                   artifact=None, capture=None) -> None:
    store.mkdir(parents=True, exist_ok=True)
    if transcript is not None:
        (store / f"meeting_{meeting_id}.transcript.json").write_text(
            json.dumps(transcript) + "\n", encoding="utf-8"
        )
    if artifact is not None:
        (store / f"meeting_{meeting_id}.draft_artifact.json").write_text(
            json.dumps(artifact) + "\n", encoding="utf-8"
        )
    if capture is not None:
        (store / f"meeting_{meeting_id}.comparison_capture.json").write_text(
            json.dumps(capture) + "\n", encoding="utf-8"
        )


def _write_fixture_store(store: Path) -> None:
    """One standalone meeting, one program meeting, one transcript-only
    meeting, one broken-artifact meeting, one broken-transcript meeting."""
    _write_meeting(store, "aaa111",
                   transcript=_transcript("aaa111"),
                   artifact=_artifact("aaa111"))
    _write_meeting(store, "bbb222",
                   transcript=_transcript("bbb222", ("program claim",)),
                   artifact=_artifact("bbb222", work_item="program work",
                                      ok=False, n_claims=1),
                   capture={"meeting_id": "bbb222"})
    _write_meeting(store, "ccc333",
                   transcript=_transcript("ccc333", ("lone transcript",)))
    # Malformed files must be RAW malformed text, not a JSON string.
    _write_meeting(store, "ddd444",
                   transcript=_transcript("ddd444", ("broken artifact",)))
    _write_raw(store, "meeting_ddd444.draft_artifact.json", "{not json")
    _write_meeting(store, "eee555",
                   artifact=_artifact("eee555", work_item="broken transcript"))
    _write_raw(store, "meeting_eee555.transcript.json", "{not json")


def _write_raw(store: Path, name: str, text: str) -> None:
    store.mkdir(parents=True, exist_ok=True)
    (store / name).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- gates


def test_history_non_owner_is_403(app):
    app.dependency_overrides[get_current_user] = lambda: OTHER
    for path in ("/build-room/meetings",
                 "/build-room/meetings/aaa111/transcript",
                 "/build-room/meetings/aaa111/artifact"):
        status, body = _call_get(app, path)
        assert status == 403, path
        assert body["detail"] == "Build-room meetings are owner-only"


def test_history_unauthenticated_is_401(app):
    status, _ = _call_get(app, "/build-room/meetings")
    assert status == 401


# ---------------------------------------------------------------- content endpoints


def test_transcript_returns_entries_verbatim(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    _write_fixture_store(tmp_path / "store")
    status, body = _call_get(app, "/build-room/meetings/aaa111/transcript")
    assert status == 200, body
    assert body == _transcript("aaa111")


def test_artifact_returns_stored_sections(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    _write_fixture_store(tmp_path / "store")
    status, body = _call_get(app, "/build-room/meetings/aaa111/artifact")
    assert status == 200, body
    assert body == _artifact("aaa111")
    # Artifact-only sections ride through verbatim.
    assert body["transjective_record"]["validation_phase"] == "final"
    assert body["transjective_validation_reports"][0]["phase"] == "opening"


def test_unknown_id_is_404_naming_the_id(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    _write_fixture_store(tmp_path / "store")
    for path in ("/build-room/meetings/zzz999/transcript",
                 "/build-room/meetings/zzz999/artifact"):
        status, body = _call_get(app, path)
        assert status == 404, path
        assert "zzz999" in body["detail"]


def test_broken_transcript_is_500_naming_the_meeting(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    _write_fixture_store(tmp_path / "store")
    status, body = _call_get(app, "/build-room/meetings/eee555/transcript")
    assert status == 500, body
    assert "eee555" in body["detail"]
    # The artifact side is unaffected by the broken transcript.
    status, body = _call_get(app, "/build-room/meetings/eee555/artifact")
    assert status == 200, body
    assert body["work_item"] == "broken transcript"


def test_meeting_id_path_validation_rejects_separators():
    store = Path("/tmp/never-read")
    for bad_id in ("", "a/b", "a\\b", "../evil"):
        try:
            br_routes._meeting_file_path_for(store, bad_id, "transcript")
        except Exception as exc:  # noqa: BLE001 — assert on status below
            assert getattr(exc, "status_code", None) == 400, bad_id
        else:
            raise AssertionError(f"accepted bad id: {bad_id!r}")


# ---------------------------------------------------------------- history list


def test_history_lists_standalone_and_program(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    _write_fixture_store(tmp_path / "store")
    status, body = _call_get(app, "/build-room/meetings")
    assert status == 200, body
    assert body["total"] == 5
    assert body["offset"] == 0
    assert body["limit"] == 50
    by_id = {m["meeting_id"]: m for m in body["meetings"]}
    # Standalone meeting: full fields, no capture flag.
    standalone = by_id["aaa111"]
    assert standalone["work_item"] == "fix the thing"
    assert standalone["question"] == "what should change?"
    assert standalone["ok"] is True
    assert standalone["claim_count"] == 2
    assert standalone["has_transcript"] is True
    assert standalone["has_artifact"] is True
    assert standalone["has_capture"] is False
    # Program meeting: same shape, capture flag set. No ledger needed:
    # the list reads the store dir, not the ledger.
    program = by_id["bbb222"]
    assert program["work_item"] == "program work"
    assert program["ok"] is False
    assert program["claim_count"] == 1
    assert program["has_capture"] is True
    # No server paths anywhere in the response.
    assert "/app/data" not in json.dumps(body)
    assert str(tmp_path) not in json.dumps(body)


def test_history_transcript_only_entry_has_null_fields(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    _write_fixture_store(tmp_path / "store")
    status, body = _call_get(app, "/build-room/meetings")
    assert status == 200, body
    entry = next(m for m in body["meetings"] if m["meeting_id"] == "ccc333")
    assert entry["work_item"] is None
    assert entry["question"] is None
    assert entry["ok"] is None
    assert entry["claim_count"] is None
    assert entry["has_transcript"] is True
    assert entry["has_artifact"] is False
    assert "error" not in entry


def test_history_broken_artifact_entry_has_error_not_omission(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    _write_fixture_store(tmp_path / "store")
    status, body = _call_get(app, "/build-room/meetings")
    assert status == 200, body
    entry = next(m for m in body["meetings"] if m["meeting_id"] == "ddd444")
    assert "error" in entry
    assert entry["has_artifact"] is True
    # The broken file does not take the rest of the list down.
    assert body["total"] == 5


def test_history_order_is_mtime_desc(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    _write_meeting(store, "old001", transcript=_transcript("old001"),
                   artifact=_artifact("old001", work_item="old"))
    _write_meeting(store, "new002", transcript=_transcript("new002"),
                   artifact=_artifact("new002", work_item="new"))
    # Force explicit mtimes: old first, new second.
    os.utime(store / "meeting_old001.draft_artifact.json", ns=(10**9, 10**9))
    os.utime(store / "meeting_new002.draft_artifact.json", ns=(2 * 10**9, 2 * 10**9))
    status, body = _call_get(app, "/build-room/meetings")
    assert status == 200, body
    assert [m["meeting_id"] for m in body["meetings"]] == ["new002", "old001"]
    assert body["order"] == "mtime_desc"


def test_history_paging_and_bounds(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    _write_fixture_store(tmp_path / "store")
    status, body = _call_get(app, "/build-room/meetings?limit=2")
    assert status == 200, body
    assert len(body["meetings"]) == 2
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    status, body = _call_get(app, "/build-room/meetings?offset=4&limit=2")
    assert status == 200, body
    assert len(body["meetings"]) == 1
    assert body["offset"] == 4
    # Offset beyond the total is an empty page with the total.
    status, body = _call_get(app, "/build-room/meetings?offset=99")
    assert status == 200, body
    assert body["meetings"] == []
    assert body["total"] == 5
    # Limit clamps to the documented max.
    status, body = _call_get(app, "/build-room/meetings?limit=9999")
    assert status == 200, body
    assert body["limit"] == 200
    # Negatives are 400.
    for path in ("/build-room/meetings?offset=-1",
                 "/build-room/meetings?limit=-1"):
        status, _ = _call_get(app, path)
        assert status == 400, path


def test_history_empty_store_is_empty_list(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    (tmp_path / "store").mkdir(parents=True, exist_ok=True)
    status, body = _call_get(app, "/build-room/meetings")
    assert status == 200, body
    assert body == {"meetings": [], "total": 0, "offset": 0, "limit": 50,
                    "order": "mtime_desc"}


# ---------------------------------------------------------------- read-only


def test_history_reads_twice_identical_and_no_side_effects(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    _write_fixture_store(store)
    before_files = sorted(p.name for p in store.iterdir())
    before_bytes = {p.name: p.read_bytes() for p in store.iterdir()}
    before_mtimes = {p.name: p.stat().st_mtime_ns for p in store.iterdir()}
    status1, body1 = _call_get(app, "/build-room/meetings")
    status2, body2 = _call_get(app, "/build-room/meetings")
    status3, body3 = _call_get(app, "/build-room/meetings/aaa111/transcript")
    status4, body4 = _call_get(app, "/build-room/meetings/aaa111/artifact")
    assert status1 == status2 == status3 == status4 == 200
    assert body1 == body2
    assert sorted(p.name for p in store.iterdir()) == before_files
    for name, data in before_bytes.items():
        assert (store / name).read_bytes() == data
        assert (store / name).stat().st_mtime_ns == before_mtimes[name]
