"""Increment F: ?transjective=1 on GET /program/captures.

Read-path only. The default response must stay byte-identical to the
#278 shape (pinned by test_captures_no_params_shape_is_exactly_the_old_shape
in test_moneyball_program_captures_endpoint.py, which this file does not
touch); the flagged response adds exactly one entry key,
"transjective_record", computed on read from the stored capture's FULL
claim_registry — never from a paged slice — and never written back.
No live API calls, no real key values, no spend anywhere.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user

OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
OTHER = {"id": "someone-else"}


def _call(app, method: str, path: str) -> tuple[int, dict]:
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
        "artifact_path": "/app/data/should-not-leak.json",
        "capture_path": "/app/data/should-not-leak-either.json",
    }


def _capture(meeting_id, condition="A", claims=None, **extra):
    capture = {
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
        "claim_registry": claims if claims is not None else [
            {"id": "C1", "author": "Muse", "text": "claim text"},
        ],
        "cap_budget": {"committed_usd": 0.25},
        "raw_responses": [{"participant": "Muse", "text": "claim text"}],
        "raw_text_retained": True,
    }
    capture.update(extra)
    return capture


def _old_claims():
    return [{"id": "C1", "author": "Muse", "text": "claim text"}]


def _native_claims():
    # C1 carries native Increment A + B fields; C2 is plain. C1's text
    # mentions C2, but declared != inferred: only the native
    # declaration may appear for C1.
    return [
        {
            "id": "C1", "author": "Muse", "text": "see C2 here",
            "target_state": "populated", "target_state_set_by": "author",
            "declarations": [
                {"target_claim": "C2", "kind": "extends", "note": "n"},
            ],
            "exposure_ref": {
                "evidence": "present",
                "payload_ref": "payload_evidence:abc",
                "visible_ids": ["C1"],
            },
        },
        {"id": "C2", "author": "Muse", "text": "other"},
    ]


def test_default_shape_unchanged_and_flag_zero_identical(app, tmp_path):
    """Acceptance 1: default (and ?transjective=0) key sets are exactly
    the pinned #278 shape; no transjective_record key anywhere."""
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A"), _meeting_record("bbb222", "B")]
    captures = {
        "aaa111": _capture("aaa111", "A"),
        "bbb222": _capture("bbb222", "B"),
    }
    _write_program(store, meetings, captures)
    for query in ("/build-room/program/captures",
                  "/build-room/program/captures?transjective=0"):
        status, body = _call_get(app, query)
        assert status == 200, body
        assert set(body.keys()) == {
            "cap_usd", "cumulative_reserved_usd", "meetings_completed", "meetings",
        }
        for entry in body["meetings"]:
            assert set(entry.keys()) == {
                "meeting_id", "packet_work_item", "condition", "ok",
                "allocation_usd", "committed_usd", "capture",
            }
            assert entry["capture"] == captures[entry["meeting_id"]]


def test_flag_adds_section_old_capture_nonconformant_intact(app, tmp_path):
    """Acceptance 2 + 4: flagged old capture gets a section; it is
    non-conformant with its report intact — no repair, no upgrade."""
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    capture = _capture("aaa111", "A", claims=_old_claims())
    _write_program(store, meetings, {"aaa111": capture})
    status, body = _call_get(
        app, "/build-room/program/captures?meeting_id=aaa111&transjective=1"
    )
    assert status == 200, body
    entry = body["meetings"][0]
    assert entry["capture"] == capture
    section = entry["transjective_record"]
    assert section["version"] == 1
    assert section["source"] == "adapter"
    assert section["validation_phase"] == "final"
    assert section["conformant"] is False
    codes = {e["code"] for e in section["validation"]["errors"]}
    assert "E12" in codes  # no exposure_ref recorded for C1
    assert section["exposure"]["C1"] == {
        "ref": None, "evidence": "absent", "visible_ids": None,
    }
    assert section["target_states"]["C1"]["state"] == "unknown"
    # Close/correction/disagreement/payload keys appear only when the
    # stored capture carries them; an old capture carries none.
    for key in ("proposals", "events", "close_report", "disagreements",
                "corrections", "payload_evidence"):
        assert key not in section


def test_flag_native_fields_spot_check(app, tmp_path):
    """Acceptance 2: native A + B claim fields flow into the section;
    declared != inferred (C1's in-text C2 mention adds nothing)."""
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    capture = _capture("aaa111", "A", claims=_native_claims())
    _write_program(store, meetings, {"aaa111": capture})
    status, body = _call_get(
        app, "/build-room/program/captures?meeting_id=aaa111&transjective=1"
    )
    assert status == 200, body
    section = body["meetings"][0]["transjective_record"]
    assert section["declarations"] == [
        {"source_claim": "C1", "target_claim": "C2", "kind": "extends",
         "layer": "declared", "note": "n"},
    ]
    assert section["target_states"]["C1"] == {
        "state": "populated", "set_by": "author", "uncertainty_reason": None,
    }
    assert section["exposure"]["C1"] == {
        "ref": "payload_evidence:abc", "evidence": "present",
        "visible_ids": ["C1"],
    }


def test_flag_forwards_close_keys_where_present(app, tmp_path):
    """Acceptance 2: a capture carrying close/correction/disagreement/
    payload keys gets them honored in the section, verbatim."""
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    capture = _capture(
        "aaa111", "A", claims=_old_claims(),
        proposals=[{"proposal_id": "P1"}],
        events=[{"event_id": "E1"}],
        close_report={"refusals": []},
        disagreements=[{"pair": ["C1", "C2"]}],
        corrections=[{"correction_id": "K1"}],
        payload_evidence={"abc": "exact payload text"},
    )
    _write_program(store, meetings, {"aaa111": capture})
    status, body = _call_get(
        app, "/build-room/program/captures?meeting_id=aaa111&transjective=1"
    )
    assert status == 200, body
    section = body["meetings"][0]["transjective_record"]
    assert section["proposals"] == [{"proposal_id": "P1"}]
    assert section["events"] == [{"event_id": "E1"}]
    assert section["close_report"] == {"refusals": []}
    assert section["disagreements"] == [{"pair": ["C1", "C2"]}]
    assert section["corrections"] == [{"correction_id": "K1"}]
    assert section["payload_evidence"] == {"abc": "exact payload text"}


def test_flag_paging_computes_from_full_registry(app, tmp_path):
    """A paged slice must not change the section: it is computed from
    the full registry, so an empty page still reports all claims."""
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    claims = [
        {"id": "C1", "author": "Muse", "text": "one"},
        {"id": "C2", "author": "Muse", "text": "two"},
        {"id": "C3", "author": "Muse", "text": "three"},
    ]
    _write_program(store, meetings, {"aaa111": _capture("aaa111", "A", claims=claims)})
    status, body = _call_get(
        app,
        "/build-room/program/captures?meeting_id=aaa111&claim_limit=0&transjective=1",
    )
    assert status == 200, body
    entry = body["meetings"][0]
    assert entry["capture"]["claim_registry"] == []
    assert entry["claim_total"] == 3
    section = entry["transjective_record"]
    assert set(section["target_states"].keys()) == {"C1", "C2", "C3"}
    assert set(section["exposure"].keys()) == {"C1", "C2", "C3"}


def test_reads_never_rewrite_stored_captures(app, tmp_path):
    """Acceptance 3: capture file bytes identical before and after
    unflagged and flagged reads."""
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A")]
    _write_program(store, meetings, {"aaa111": _capture("aaa111", "A")})
    path = store / "meeting_aaa111.comparison_capture.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    for query in ("/build-room/program/captures",
                  "/build-room/program/captures?meeting_id=aaa111&transjective=1",
                  "/build-room/program/captures?meeting_id=aaa111&transjective=1"
                  "&claim_limit=0"):
        status, _ = _call_get(app, query)
        assert status == 200
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_flag_invalid_value_400(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    _write_program(store, [_meeting_record("aaa111", "A")],
                   {"aaa111": _capture("aaa111", "A")})
    status, body = _call_get(
        app, "/build-room/program/captures?transjective=2"
    )
    assert status == 400, body
    assert "transjective" in body["detail"]
    status, _ = _call_get(app, "/build-room/program/captures?transjective=abc")
    assert status == 422


def test_flag_missing_registry_500_unflagged_unaffected(app, tmp_path):
    """Flagged read of a registry-less capture fails explicitly (500
    naming the meeting); the default read is unaffected."""
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    capture = _capture("aaa111", "A")
    del capture["claim_registry"]
    _write_program(store, [_meeting_record("aaa111", "A")], {"aaa111": capture})
    status, body = _call_get(
        app, "/build-room/program/captures?meeting_id=aaa111&transjective=1"
    )
    assert status == 500, body
    assert "aaa111" in body["detail"]
    status, body = _call_get(
        app, "/build-room/program/captures?meeting_id=aaa111"
    )
    assert status == 200, body
    assert "claim_registry" not in body["meetings"][0]["capture"]


def test_flag_applies_to_all_entries_and_gate_holds(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    meetings = [_meeting_record("aaa111", "A"), _meeting_record("bbb222", "B")]
    _write_program(store, meetings, {
        "aaa111": _capture("aaa111", "A"),
        "bbb222": _capture("bbb222", "B"),
    })
    status, body = _call_get(app, "/build-room/program/captures?transjective=1")
    assert status == 200, body
    assert len(body["meetings"]) == 2
    for entry in body["meetings"]:
        assert entry["transjective_record"]["version"] == 1
    app.dependency_overrides[get_current_user] = lambda: OTHER
    status, _ = _call_get(app, "/build-room/program/captures?transjective=1")
    assert status == 403
