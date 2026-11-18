"""Security correction (D-1, D-6, D-14, D-4) — route-level tests.

Deterministic and hermetic: every store lives under tmp_path
(ZENAF_DATA_DIR + patched presence paths), sessions resolve through
a fake token map, and installation-owner resolution is patched at
the single vision-execution storage source every resolver chain
(erasure §9.1, identity store fold, identity routes) consults.

Per route the matrix is: unauthenticated → 401; authenticated
non-owner → 403 with state byte-identical afterwards; the owner →
the pre-existing workflow, unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

OWNER_ID = "sec-owner-1"
OTHER_ID = "sec-other-2"
# get_current_user reads only the zenaf_session cookie on current
# main; OWNER/OTHER/ANON select which session a request carries.
OWNER = "owner-token"
OTHER = "other-token"
ANON = None

_USERS = {
    "owner-token": {"id": OWNER_ID, "email": "owner@local.zenaf"},
    "other-token": {"id": OTHER_ID, "email": "other@example.com"},
}


class Client:
    """TestClient wrapper that sets the session cookie per call."""

    def __init__(self, test_client: TestClient):
        self._c = test_client

    def request(self, method, url, who=ANON, **kwargs):
        self._c.cookies.clear()
        if who is not None:
            self._c.cookies.set("zenaf_session", who)
        return self._c.request(method, url, **kwargs)

    def get(self, url, who=ANON, **kwargs):
        return self.request("GET", url, who, **kwargs)

    def post(self, url, who=ANON, **kwargs):
        return self.request("POST", url, who, **kwargs)

    def delete(self, url, who=ANON, **kwargs):
        return self.request("DELETE", url, who, **kwargs)


def _chatgpt_export_bytes() -> bytes:
    data = [
        {
            "id": "conv-1",
            "title": "Career move",
            "mapping": {
                "n1": {
                    "message": {
                        "author": {"role": "user"},
                        "content": {
                            "parts": [
                                "Should I take the startup offer? "
                                "Email me at jane.doe@example.com."
                            ]
                        },
                        "create_time": 1720000000.0,
                    }
                },
                "n2": {
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"parts": ["Let's weigh the tradeoffs..."]},
                        "create_time": 1720000060.0,
                    }
                },
            },
        }
    ]
    return json.dumps(data).encode()


class Env:
    def __init__(self, tmp_path: Path):
        self.dir = tmp_path
        self.identity_db = tmp_path / "zenaf-data" / "identity" / "identity.db"
        self.signals_db = tmp_path / "presence" / "signals.db"
        self.uploads = tmp_path / "presence" / "uploads"

    def identity_bytes(self) -> bytes | None:
        return self.identity_db.read_bytes() if self.identity_db.exists() else None

    def signals_bytes(self) -> bytes | None:
        return self.signals_db.read_bytes() if self.signals_db.exists() else None

    def upload_files(self) -> list[Path]:
        if not self.uploads.exists():
            return []
        return sorted(p for p in self.uploads.rglob("*") if p.is_file())


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("ZENAF_DATA_DIR", str(tmp_path / "zenaf-data"))
    monkeypatch.setattr(
        "local_ai.vision_execution.service.get_session_user",
        lambda token: _USERS.get(token),
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_owner_user_id",
        lambda: OWNER_ID,
    )
    monkeypatch.setattr(
        "local_ai.presence_ingest.store.DEFAULT_DB_PATH", e.signals_db
    )
    monkeypatch.setattr("local_ai.presence_ingest.service.UPLOAD_ROOT", e.uploads)
    return e


@pytest.fixture()
def client(env):
    from api.routes import identity_routes, ingest_routes

    app = FastAPI()
    app.include_router(identity_routes.router)
    app.include_router(ingest_routes.router)
    return Client(TestClient(app, raise_server_exceptions=False))


def _issue_license_as_owner(client) -> None:
    resp = client.post("/identity/license/issue", OWNER, json={})
    assert resp.status_code == 200, resp.text


def _upload_as_owner(client) -> str:
    resp = client.post(
        "/ingest/upload",
        OWNER,
        files={"file": ("conversations.json", _chatgpt_export_bytes())},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


# ------------------------------------------------------------------- D-6


def _call_kwargs(url: str, session_id: str = "imp-x") -> dict:
    if url.endswith("/upload"):
        return {"files": {"file": ("conversations.json", _chatgpt_export_bytes())}}
    if url.endswith("/scopes"):
        return {"json": {"scope": "train:self", "action": "grant"}}
    if url.endswith("/review"):
        return {"json": {"approvals": {"sig-1": True}}}
    if url.endswith("/contributions"):
        return {
            "json": {
                "claim_id": "clm-x",
                "session_id": session_id,
                "role": "author",
            }
        }
    return {"json": {}}


def test_identity_routes_reject_unauthenticated(client, env):
    calls = [
        ("GET", "/identity/license"),
        ("POST", "/identity/license/issue"),
        ("GET", "/identity/scopes"),
        ("POST", "/identity/scopes"),
        ("GET", "/identity/scopes/check?scope=train:self"),
        ("POST", "/identity/takeout"),
    ]
    for method, url in calls:
        resp = client.request(method, url, ANON, **_call_kwargs(url))
        assert resp.status_code == 401, (method, url, resp.status_code)
    # Nothing was written: no license, no ledger, no store file at all.
    assert env.identity_bytes() is None


def test_identity_routes_reject_non_owner_state_unchanged(client, env):
    _issue_license_as_owner(client)
    before = env.identity_bytes()
    calls = [
        ("GET", "/identity/license"),
        ("POST", "/identity/license/issue"),
        ("GET", "/identity/scopes"),
        ("POST", "/identity/scopes"),
        ("GET", "/identity/scopes/check?scope=train:self"),
        ("POST", "/identity/takeout"),
    ]
    for method, url in calls:
        resp = client.request(method, url, OTHER, **_call_kwargs(url))
        assert resp.status_code == 403, (method, url, resp.status_code)
    assert env.identity_bytes() == before


def test_owner_scope_writes_are_owner_keyed(client, env):
    _issue_license_as_owner(client)
    resp = client.post(
        "/identity/scopes",
        OWNER,
        json={"scope": "train:self", "action": "grant"},
    )
    assert resp.status_code == 200, resp.text
    assert "train:self" in resp.json()["active"]

    resp = client.get("/identity/scopes", OWNER)
    assert resp.status_code == 200
    body = resp.json()
    assert "train:self" in body["active"]
    # The new event is written under the resolved owner's identity,
    # never the global empty-user identity.
    grants = [
        e for e in body["ledger"] if e["scope"] == "train:self" and e["action"] == "grant"
    ]
    assert grants and grants[-1]["user_id"] == OWNER_ID

    resp = client.get("/identity/scopes/check?scope=train:self", OWNER)
    assert resp.json() == {"scope": "train:self", "granted": True}

    resp = client.post(
        "/identity/scopes",
        OWNER,
        json={"scope": "train:self", "action": "revoke"},
    )
    assert resp.status_code == 200
    assert "train:self" not in resp.json()["active"]


def test_legacy_global_tier_preserved_for_owner_only(client, env):
    from local_ai.identity import service as ident
    from local_ai.identity.scopes import check_scope
    from local_ai.identity.store import IdentityStore

    _issue_license_as_owner(client)
    store = IdentityStore()
    try:
        # Historical global grant (pre-correction provenance) + an
        # owner-keyed grant.
        ident.grant_scope("rent:zone:*", store=store)  # user_id="" legacy
        ident.grant_scope("export", store=store, user_id=OWNER_ID)

        # Another account: neither the legacy grant nor the owner's
        # own grant confers anything.
        assert store.active_scopes(user_id=OTHER_ID) == set()
        assert check_scope("rent:zone:*", store=store, user_id=OTHER_ID) is False
        assert store.legacy_global_scopes(OTHER_ID) == set()

        # The owner keeps the permission, represented distinctly as
        # legacy-provenance — preserved, not legitimized.
        assert "rent:zone:*" in store.active_scopes(user_id=OWNER_ID)
        assert store.legacy_global_scopes(OWNER_ID) == {"rent:zone:*"}

        # The installation read (service gates behind owner-gated
        # routes) still folds the union, as before.
        assert check_scope("rent:zone:*", store=store, user_id=None) is True

        inv = ident.legacy_scope_inventory(store=store)
        assert inv["global_events"] >= 1
        assert inv["owner_scopes_effective_only_via_global"] == ["rent:zone:*"]
    finally:
        store.close()

    resp = client.get("/identity/scopes", OWNER)
    body = resp.json()
    assert "rent:zone:*" in body["active"]
    assert body["legacy_global"]["scopes"] == ["rent:zone:*"]


def test_license_bootstrap_owner_first_no_deadlock(client, env):
    # Fresh installation: no license exists yet. The bootstrapped
    # owner account's session is the trusted issuance path.
    assert client.post("/identity/license/issue", ANON, json={}).status_code == 401
    assert client.post("/identity/license/issue", OTHER, json={}).status_code == 403
    resp = client.post("/identity/license/issue", OWNER, json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_id"] == "local-owner"  # IssueBody default
    resp = client.get("/identity/license", OWNER)
    assert resp.status_code == 200
    assert resp.json()["license"] is not None


# ------------------------------------------------------------------ D-14


def test_takeout_owner_only_bundle_contents_unchanged(client, env):
    _issue_license_as_owner(client)
    # No consent scope is granted: takeout must not gain one (the
    # owner's export right is ownership-gated, not scope-gated).
    resp = client.post("/identity/takeout", OWNER)
    assert resp.status_code == 200, resp.text
    bundle = resp.json()
    assert bundle["license"]["owner_id"] == "local-owner"
    assert bundle["license"]["status"] == "active"

    # Contents unchanged by the gate: the route bundle is exactly
    # the service bundle (exported_at timestamp aside).
    from local_ai.identity import service as ident

    direct = ident.build_takeout()
    assert set(bundle) == set(direct)
    for key in direct:
        if key != "exported_at":
            assert bundle[key] == direct[key], key

    # Service level: a named non-owner requester is refused before
    # any bundle is composed; the unparameterized call (existing
    # internal callers) behaves exactly as before.
    from local_ai.identity.erasure import ErasureRefused

    with pytest.raises(ErasureRefused):
        ident.build_takeout(requesting_user_id=OTHER_ID)
    assert ident.build_takeout()["license"]["owner_id"] == "local-owner"


# ------------------------------------------------------------------- D-1


def _ingest_calls(session_id: str, claim_id: str = "clm-x"):
    return [
        ("GET", "/ingest/sources"),
        ("GET", "/ingest/sessions"),
        ("POST", "/ingest/upload"),
        ("GET", f"/ingest/sessions/{session_id}"),
        ("GET", f"/ingest/sessions/{session_id}/candidates"),
        ("POST", f"/ingest/sessions/{session_id}/distill"),
        ("POST", f"/ingest/sessions/{session_id}/review"),
        ("DELETE", f"/ingest/sessions/{session_id}"),
        ("GET", f"/ingest/sessions/{session_id}/contributions"),
        ("POST", f"/ingest/sessions/{session_id}/contributions"),
        ("DELETE", f"/ingest/contributions/{claim_id}"),
    ]


def test_ingest_routes_reject_unauthenticated_before_store_access(client, env):
    _issue_license_as_owner(client)
    for method, url in _ingest_calls("imp-none"):
        resp = client.request(method, url, ANON, **_call_kwargs(url, "imp-none"))
        assert resp.status_code == 401, (method, url, resp.status_code)
    # Owner resolution precedes any access to the singleton presence
    # store: the store file was never even created.
    assert env.signals_bytes() is None
    assert env.upload_files() == []


def test_ingest_non_owner_denied_everywhere_state_unchanged(client, env):
    _issue_license_as_owner(client)
    session_id = _upload_as_owner(client)
    before = env.signals_bytes()
    assert before is not None
    for method, url in _ingest_calls(session_id):
        resp = client.request(method, url, OTHER, **_call_kwargs(url, session_id))
        assert resp.status_code == 403, (method, url, resp.status_code)
    # No reads disclosed, no processing triggered, no standing
    # changed, nothing deleted, no file written.
    assert env.signals_bytes() == before
    assert env.upload_files() == []
    resp = client.get("/ingest/sessions", OWNER)
    assert [s["session_id"] for s in resp.json()] == [session_id]


def test_ingest_owner_workflow_preserved_and_no_raw_retained(client, env):
    _issue_license_as_owner(client)
    session_id = _upload_as_owner(client)

    # D-4: after the import, the uploads location holds no raw
    # export copy — nothing at all.
    assert env.upload_files() == []

    # The owner reads the session back; the stored events are the
    # same redacted output the pre-correction flow produced.
    resp = client.get(f"/ingest/sessions/{session_id}", OWNER)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "parsed"
    from local_ai.presence_ingest.store import PresenceStore

    store = PresenceStore(db_path=env.signals_db)
    try:
        events = store.list_events(session_id)
    finally:
        store.close()
    assert len(events) == 2
    assert all("jane.doe@example.com" not in e.text for e in events)

    # Distillation keeps its operation-specific permission: without
    # train:self the owner is refused by the service scope gate.
    resp = client.post(f"/ingest/sessions/{session_id}/distill", OWNER)
    assert resp.status_code == 403, resp.text

    # With train:self granted (owner-keyed, via the gated route),
    # the request reaches the service layer (stubbed: no model call
    # in tests).
    resp = client.post(
        "/identity/scopes",
        OWNER,
        json={"scope": "train:self", "action": "grant"},
    )
    assert resp.status_code == 200
    from local_ai.presence_ingest import service as presence_service

    calls: list[str] = []
    orig = presence_service.run_distill
    presence_service.run_distill = lambda sid, **kw: calls.append(sid) or 0
    try:
        resp = client.post(f"/ingest/sessions/{session_id}/distill", OWNER)
    finally:
        presence_service.run_distill = orig
    assert resp.status_code == 200, resp.text
    assert calls == [session_id]

    # Contribution claims: owner can write and read; deletion works.
    resp = client.post(
        f"/ingest/sessions/{session_id}/contributions",
        OWNER,
        json={
            "claim_id": "clm-1",
            "session_id": session_id,
            "role": "author",
            "work_title": "Orchard project",
        },
    )
    assert resp.status_code == 201, resp.text
    claim_id = resp.json()["claim_id"]
    resp = client.get(f"/ingest/sessions/{session_id}/contributions", OWNER)
    assert [c["claim_id"] for c in resp.json()] == [claim_id]
    resp = client.delete(f"/ingest/contributions/{claim_id}", OWNER)
    assert resp.status_code == 200

    # Owner deletion of the session still works end to end: the
    # session is marked deleted and its events are gone (the row
    # itself remains as the deletion record — pre-existing semantics).
    resp = client.delete(f"/ingest/sessions/{session_id}", OWNER)
    assert resp.status_code == 200, resp.text
    resp = client.get(f"/ingest/sessions/{session_id}", OWNER)
    assert resp.json()["status"] == "deleted"
    store = PresenceStore(db_path=env.signals_db)
    try:
        assert store.count_events(session_id) == 0
    finally:
        store.close()


def test_ingest_review_owner_changes_standing(client, env):
    _issue_license_as_owner(client)
    session_id = _upload_as_owner(client)

    from local_ai.presence_ingest.schema import TrainingSignal
    from local_ai.presence_ingest.store import PresenceStore

    store = PresenceStore(db_path=env.signals_db)
    try:
        sig = TrainingSignal(
            signal_id="sig-review-1",
            ts_ms=1,
            layer="behavior",
            zone="career",
            actor="user",
            summary="a candidate",
            valence="observed",
            session_id=session_id,
        )
        store.save_candidate_signals([sig])
    finally:
        store.close()

    resp = client.post(
        f"/ingest/sessions/{session_id}/review",
        OTHER,
        json={"approvals": {"sig-review-1": True}},
    )
    assert resp.status_code == 403
    resp = client.post(
        f"/ingest/sessions/{session_id}/review",
        OWNER,
        json={"approvals": {"sig-review-1": True}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["approved"] == 1
