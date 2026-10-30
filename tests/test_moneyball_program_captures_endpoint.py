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


# ---------------------------------------------------------------- paging extension


def _capture_with_claims(meeting_id, n_claims, condition="A"):
    """A capture whose registry mirrors the real shape at scale: the
    largest staging meeting holds 113 claims, so 113 is the paging
    fixture size. Claim text is multi-sentence (~400 chars), the
    order of magnitude a real scored claim occupies serialized."""
    capture = _capture(meeting_id, condition)
    capture["claim_registry"] = [
        {
            "id": f"C{i + 1}",
            "author": "Muse",
            "text": (f"Claim {i + 1}: a substantive scored contribution. " * 8).strip(),
            "phase": "opening",
        }
        for i in range(n_claims)
    ]
    return capture


def test_captures_meeting_filter_returns_only_that_entry_full_capture(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A"), _meeting_record("bbb222", "B")]
    _write_program(store, meetings, {
        "aaa111": _capture("aaa111", "A"),
        "bbb222": _capture("bbb222", "B"),
    })
    status, body = _call_get(app, "/build-room/program/captures?meeting_id=bbb222")
    assert status == 200, body
    # Envelope still describes the whole program; the meetings list
    # holds only the selected entry, full capture intact.
    assert body["cap_usd"] == 2.0
    assert body["cumulative_reserved_usd"] == 0.5
    assert body["meetings_completed"] == 1
    assert [m["meeting_id"] for m in body["meetings"]] == ["bbb222"]
    entry = body["meetings"][0]
    # Meeting-only filter adds NO paging keys: the entry is exactly
    # the unfiltered entry shape.
    assert set(entry.keys()) == {
        "meeting_id", "packet_work_item", "condition", "ok",
        "allocation_usd", "committed_usd", "capture",
    }
    assert entry["capture"]["claim_registry"][0]["id"] == "C1"
    assert entry["capture"]["role_brief_version"] == "v1"


def test_captures_meeting_filter_unknown_id_is_404(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    _write_program(store, meetings, {"aaa111": _capture("aaa111", "A")})
    status, body = _call_get(app, "/build-room/program/captures?meeting_id=zzz999")
    assert status == 404
    assert "zzz999" in body["detail"]
    assert "meetings" not in body


def test_captures_paging_reconstructs_registry_exactly(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    full = _capture_with_claims("aaa111", 113)
    _write_program(store, meetings, {"aaa111": full})
    base = "/build-room/program/captures?meeting_id=aaa111"
    pages = []
    for offset, expected_len in ((0, 40), (40, 40), (80, 33)):
        status, body = _call_get(
            app, f"{base}&claim_offset={offset}&claim_limit=40"
        )
        assert status == 200, body
        assert body["meetings_completed"] == 1
        entry = body["meetings"][0]
        assert entry["claim_total"] == 113
        assert entry["claim_offset"] == offset
        assert entry["claim_limit"] == 40
        sliced = entry["capture"]["claim_registry"]
        assert len(sliced) == expected_len
        # Every non-registry capture field stays complete on a page.
        assert entry["capture"]["meeting_id"] == "aaa111"
        assert entry["capture"]["base_prompt_hashes"]["phase1"] == "base-aaa111"
        pages.append(sliced)
    rebuilt = [claim for page in pages for claim in page]
    assert rebuilt == full["claim_registry"]
    assert json.dumps(rebuilt, sort_keys=True) == json.dumps(
        full["claim_registry"], sort_keys=True
    )
    # Paging actually shrinks the payload: a 40-claim page serializes
    # far under the 256 KB browser text-view cap (and under the full
    # meeting capture), which is the whole point of the feature.
    status, full_body = _call_get(app, base)
    assert status == 200
    status, page_body = _call_get(app, f"{base}&claim_offset=0&claim_limit=40")
    assert status == 200
    assert len(json.dumps(page_body).encode()) < 256 * 1024
    assert len(json.dumps(page_body).encode()) < len(json.dumps(full_body).encode())


def test_captures_paging_offset_beyond_total_is_empty_not_error(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    _write_program(store, meetings, {"aaa111": _capture_with_claims("aaa111", 113)})
    status, body = _call_get(
        app,
        "/build-room/program/captures?meeting_id=aaa111&claim_offset=200&claim_limit=40",
    )
    assert status == 200, body
    entry = body["meetings"][0]
    assert entry["claim_total"] == 113
    assert entry["claim_offset"] == 200
    assert entry["claim_limit"] == 40
    assert entry["capture"]["claim_registry"] == []


def test_captures_paging_negative_values_are_400(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    _write_program(store, meetings, {"aaa111": _capture("aaa111", "A")})
    for query in ("claim_offset=-1", "claim_limit=-5"):
        status, body = _call_get(
            app, f"/build-room/program/captures?meeting_id=aaa111&{query}"
        )
        assert status == 400, body
        assert "negative" in body["detail"]


def test_captures_paging_without_meeting_is_400(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    _write_program(store, meetings, {"aaa111": _capture("aaa111", "A")})
    for query in ("claim_offset=0", "claim_limit=40", "claim_offset=0&claim_limit=40"):
        status, body = _call_get(app, f"/build-room/program/captures?{query}")
        assert status == 400, body
        assert "meeting_id" in body["detail"]


def test_captures_paging_single_param_defaults(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    _write_program(store, meetings, {"aaa111": _capture_with_claims("aaa111", 113)})
    # Offset alone pages to the end of the registry.
    status, body = _call_get(
        app, "/build-room/program/captures?meeting_id=aaa111&claim_offset=100"
    )
    assert status == 200, body
    entry = body["meetings"][0]
    assert entry["claim_offset"] == 100
    assert entry["claim_limit"] == 13
    assert len(entry["capture"]["claim_registry"]) == 13
    assert entry["capture"]["claim_registry"][0]["id"] == "C101"
    # Limit alone starts at the beginning.
    status, body = _call_get(
        app, "/build-room/program/captures?meeting_id=aaa111&claim_limit=10"
    )
    assert status == 200, body
    entry = body["meetings"][0]
    assert entry["claim_offset"] == 0
    assert entry["claim_limit"] == 10
    assert len(entry["capture"]["claim_registry"]) == 10
    assert entry["capture"]["claim_registry"][-1]["id"] == "C10"


def test_captures_paging_limit_zero_is_empty(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    _write_program(store, meetings, {"aaa111": _capture_with_claims("aaa111", 113)})
    status, body = _call_get(
        app, "/build-room/program/captures?meeting_id=aaa111&claim_limit=0"
    )
    assert status == 200, body
    entry = body["meetings"][0]
    assert entry["claim_total"] == 113
    assert entry["claim_limit"] == 0
    assert entry["capture"]["claim_registry"] == []


def test_captures_no_params_shape_is_exactly_the_old_shape(app, tmp_path):
    """Backward compat, pinned: a no-params request returns exactly
    the #278 key sets — no claim_* keys, no extra envelope keys."""
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A"), _meeting_record("bbb222", "B")]
    _write_program(store, meetings, {
        "aaa111": _capture("aaa111", "A"),
        "bbb222": _capture("bbb222", "B"),
    })
    status, body = _call_get(app, "/build-room/program/captures")
    assert status == 200, body
    assert set(body.keys()) == {
        "cap_usd", "cumulative_reserved_usd", "meetings_completed", "meetings",
    }
    for entry in body["meetings"]:
        assert set(entry.keys()) == {
            "meeting_id", "packet_work_item", "condition", "ok",
            "allocation_usd", "committed_usd", "capture",
        }
        assert entry["capture"] == _capture(entry["meeting_id"], entry["condition"])


def test_captures_gate_enforced_on_new_params(app, tmp_path):
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    _write_program(store, meetings, {"aaa111": _capture("aaa111", "A")})
    app.dependency_overrides[get_current_user] = lambda: OTHER
    status, body = _call_get(
        app,
        "/build-room/program/captures?meeting_id=aaa111&claim_offset=0&claim_limit=40",
    )
    assert status == 403
    assert body["detail"] == "Build-room meetings are owner-only"
    app.dependency_overrides.pop(get_current_user, None)
    status, _ = _call_get(
        app, "/build-room/program/captures?meeting_id=aaa111"
    )
    assert status == 401


def test_captures_filtered_request_reads_only_the_selected_capture(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A"), _meeting_record("bbb222", "B")]
    _write_program(store, meetings, {
        "aaa111": _capture("aaa111", "A"),
        "bbb222": _capture("bbb222", "B"),
    })
    # Sibling capture goes missing: the filtered request still serves
    # the selected meeting (the unfiltered request would 500 here).
    (store / "meeting_bbb222.comparison_capture.json").unlink()
    status, body = _call_get(app, "/build-room/program/captures?meeting_id=aaa111")
    assert status == 200, body
    assert [m["meeting_id"] for m in body["meetings"]] == ["aaa111"]
    # But the selected meeting's own missing capture still 500s,
    # naming that meeting — never a silent omission.
    (store / "meeting_aaa111.comparison_capture.json").unlink()
    status, body = _call_get(app, "/build-room/program/captures?meeting_id=aaa111")
    assert status == 500, body
    assert "aaa111" in body["detail"]
    assert "meetings" not in body


def test_captures_paging_non_list_registry_is_500(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    broken = _capture("aaa111", "A")
    broken["claim_registry"] = "not-a-list"
    _write_program(store, meetings, {"aaa111": broken})
    status, body = _call_get(
        app,
        "/build-room/program/captures?meeting_id=aaa111&claim_offset=0&claim_limit=40",
    )
    assert status == 500, body
    assert "aaa111" in body["detail"]
