"""Track B containment — authentication on the Vision Execution routes.

Scope plan §5 / §6 (ruling 7): anonymous requests return 401 before any
service or storage access; all previously protected routes remain
protected; unauthorized requests cannot invoke side effects; authenticated
workflows remain functional. Deterministic only; no live requests, no
model calls, no real credentials.

Covers the 19 Track B endpoints (POST /radar/items is Track A's and is
not re-tested here):
- 11 Tier 1 (§2.1): persons x5, assets x5, PUT /capacity-profiles.
- 3 legacy extract routes (§2.2) + 1 pick-directory route (§2.4):
  conditional registration — absent (404) with ZENAF_PROD=1, present and
  authenticated otherwise.
- 4 workspace-identity endpoints (§2.3): auth + scan-root allowlist.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.auth_routes import get_current_user
from api.routes import vision_execution as ve_routes
from local_ai import hosted_config
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import service as ve_service
from local_ai.vision_execution import storage as ve_storage
from local_ai.workspace_identity import snapshot as wi_snapshot
from local_ai.workspace_identity import translation_template as wi_template


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
def identity_dir(tmp_path, monkeypatch):
    """Redirect the workspace-identity file writes to a tmp dir."""
    d = tmp_path / "identity"
    d.mkdir()
    monkeypatch.setattr(
        wi_snapshot, "default_workspace_identity_dir", lambda repo_root=None: d
    )
    monkeypatch.setattr(
        wi_template, "_default_identity_dir", lambda: d
    )
    return d


def _make_app(authenticated: bool) -> TestClient:
    app = FastAPI()
    app.include_router(ve_routes.router)
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: {
            "id": "test-user-a",
            "email": "a@example.com",
        }
    return TestClient(app, raise_server_exceptions=False)


def _seed_person(ve_ctx, name="Seed Person") -> str:
    pid = ve_models.new_id()
    ve_ctx.execute(
        "INSERT INTO persons (id, name, role, relationship_type, contact_info,"
        " strengths, needs, wants, availability, notes, created_at, updated_at, user_id)"
        " VALUES (?, ?, '', '', '', '', '', '', '', '', '2026-01-01T00:00:00Z',"
        " '2026-01-01T00:00:00Z', 'test-user-a')",
        (pid, name),
    )
    ve_ctx.commit()
    return pid


def _seed_asset(ve_ctx, name="Seed Asset") -> str:
    aid = ve_models.new_id()
    ve_ctx.execute(
        "INSERT INTO assets (id, name, asset_type, owner_id, status, availability,"
        " cost, time_availability, linked_idea_ids, linked_initiative_ids,"
        " linked_project_ids, notes, created_at, updated_at, user_id)"
        " VALUES (?, ?, '', NULL, '', '', '', '', '[]', '[]', '[]', '',"
        " '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'test-user-a')",
        (aid, name),
    )
    ve_ctx.commit()
    return aid


def _seed_capacity(ve_ctx, person_id: str, hours: float = 10.0) -> None:
    ve_ctx.execute(
        "INSERT INTO capacity_profiles (person_id, weekly_capacity_hours,"
        " created_at, updated_at, user_id) VALUES (?, ?, '2026-01-01T00:00:00Z',"
        " '2026-01-01T00:00:00Z', 'test-user-a')",
        (person_id, hours),
    )
    ve_ctx.commit()


def _row_count(ve_ctx, table: str) -> int:
    return ve_ctx.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---------------------------------------------------------------------------
# §5.1 — Anonymous requests return 401, no data accessed or modified
# ---------------------------------------------------------------------------


class TestAnonymousPersons:
    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("get", "/vision-execution/persons", None),
            ("get", "/vision-execution/persons/{pid}", None),
            ("post", "/vision-execution/persons", {"name": "X"}),
            ("patch", "/vision-execution/persons/{pid}", {"name": "Y"}),
            ("delete", "/vision-execution/persons/{pid}", None),
        ],
    )
    def test_anonymous_persons_401_no_change(self, ve_ctx, method, path, body):
        pid = _seed_person(ve_ctx)
        before = ve_ctx.execute(
            "SELECT * FROM persons WHERE id = ?", (pid,)
        ).fetchone()
        client = _make_app(authenticated=False)
        url = path.format(pid=pid)
        resp = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
        assert resp.status_code == 401
        assert _row_count(ve_ctx, "persons") == 1
        after = ve_ctx.execute(
            "SELECT * FROM persons WHERE id = ?", (pid,)
        ).fetchone()
        assert tuple(after) == tuple(before)


class TestAnonymousAssets:
    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("get", "/vision-execution/assets", None),
            ("get", "/vision-execution/assets/{aid}", None),
            ("post", "/vision-execution/assets", {"name": "X"}),
            ("patch", "/vision-execution/assets/{aid}", {"name": "Y"}),
            ("delete", "/vision-execution/assets/{aid}", None),
        ],
    )
    def test_anonymous_assets_401_no_change(self, ve_ctx, method, path, body):
        aid = _seed_asset(ve_ctx)
        before = ve_ctx.execute(
            "SELECT * FROM assets WHERE id = ?", (aid,)
        ).fetchone()
        client = _make_app(authenticated=False)
        url = path.format(aid=aid)
        resp = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
        assert resp.status_code == 401
        assert _row_count(ve_ctx, "assets") == 1
        after = ve_ctx.execute(
            "SELECT * FROM assets WHERE id = ?", (aid,)
        ).fetchone()
        assert tuple(after) == tuple(before)


class TestAnonymousCapacity:
    def test_anonymous_capacity_put_401_no_change(self, ve_ctx):
        pid = _seed_person(ve_ctx)
        _seed_capacity(ve_ctx, pid, hours=10.0)
        client = _make_app(authenticated=False)
        resp = client.put(
            "/vision-execution/capacity-profiles",
            json={"person_id": pid, "weekly_capacity_hours": 99.0},
        )
        assert resp.status_code == 401
        row = ve_ctx.execute(
            "SELECT weekly_capacity_hours FROM capacity_profiles WHERE person_id = ?",
            (pid,),
        ).fetchone()
        assert row[0] == 10.0

    def test_capacity_get_controls(self, ve_ctx):
        """The two authenticated GET /capacity-profiles routes are the
        control: anonymous 401, authenticated 200."""
        pid = _seed_person(ve_ctx)
        _seed_capacity(ve_ctx, pid)
        anon = _make_app(authenticated=False)
        assert anon.get("/vision-execution/capacity-profiles").status_code == 401
        assert anon.get(f"/vision-execution/capacity-profiles/{pid}").status_code == 401
        auth = _make_app(authenticated=True)
        assert auth.get("/vision-execution/capacity-profiles").status_code == 200
        assert auth.get(f"/vision-execution/capacity-profiles/{pid}").status_code == 200


class TestAnonymousWorkspaceIdentity:
    def test_anonymous_workspace_identity_401_no_side_effect(
        self, ve_ctx, identity_dir, monkeypatch
    ):
        # Seed a template file so the PUT test can prove it is untouched.
        template_path = identity_dir / "translation-template.json"
        template_path.write_text(json.dumps({"preferredPhrases": ["seed"]}))
        before_mtime = template_path.stat().st_mtime
        before_content = template_path.read_text()

        calls: list[str] = []
        real_builder = wi_snapshot.build_workspace_identity_snapshot

        def spy_builder(*args, **kwargs):
            calls.append("builder")
            return real_builder(*args, **kwargs)

        monkeypatch.setattr(
            wi_snapshot, "build_workspace_identity_snapshot", spy_builder
        )
        client = _make_app(authenticated=False)
        assert client.get("/vision-execution/workspace-identity").status_code == 401
        assert (
            client.get("/vision-execution/workspace-identity/translation-template").status_code
            == 401
        )
        assert (
            client.put(
                "/vision-execution/workspace-identity/translation-template",
                json={"preferredPhrases": ["pwned"]},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/vision-execution/workspace-identity/scan",
                json={"roots": [str(identity_dir)], "mode": "light_refresh"},
            ).status_code
            == 401
        )
        # The 401 arrives before any directory walk.
        assert calls == []
        # No snapshot file written; the template file is byte-identical.
        assert not (identity_dir / "snapshot.json").exists()
        assert template_path.read_text() == before_content
        assert template_path.stat().st_mtime == before_mtime


# ---------------------------------------------------------------------------
# §5.1 (hosted gating) — extract routes + pick-directory
# ---------------------------------------------------------------------------


class TestHostedGating:
    EXTRACT_PATHS = [
        "/vision-execution/extract-segment-summary",
        "/vision-execution/extract-meeting-segments",
        "/vision-execution/extract-meeting-synthesis",
    ]
    PICK_PATH = "/vision-execution/workspace-identity/pick-directory"

    def _extract_bodies(self):
        return {
            "/vision-execution/extract-segment-summary": {"notes": "hello"},
            "/vision-execution/extract-meeting-segments": {"segment_texts": ["hello"]},
            "/vision-execution/extract-meeting-synthesis": {"segment_summaries": []},
        }

    def test_prod_routes_absent_404(self, ve_ctx, monkeypatch):
        """With ZENAF_PROD=1, the four routes are absent from the route
        table: anonymous AND authenticated requests get 404."""
        monkeypatch.setenv("ZENAF_PROD", "1")
        importlib.reload(ve_routes)
        try:
            app = FastAPI()
            app.include_router(ve_routes.router)
            app.dependency_overrides[get_current_user] = lambda: {
                "id": "test-user-a",
                "email": "a@example.com",
            }
            client = TestClient(app, raise_server_exceptions=False)
            # A second app without overrides for the anonymous half.
            app_anon = FastAPI()
            app_anon.include_router(ve_routes.router)
            anon = TestClient(app_anon, raise_server_exceptions=False)
            bodies = self._extract_bodies()
            for path in self.EXTRACT_PATHS:
                assert client.post(path, json=bodies[path]).status_code == 404
                assert anon.post(path, json=bodies[path]).status_code == 404
            assert client.post(self.PICK_PATH).status_code == 404
            assert anon.post(self.PICK_PATH).status_code == 404
        finally:
            monkeypatch.delenv("ZENAF_PROD", raising=False)
            importlib.reload(ve_routes)

    def test_dev_routes_present_and_anonymous_401(self, ve_ctx):
        """Without ZENAF_PROD, the routes are present and anonymous
        requests get 401 (the auth dependency)."""
        client = _make_app(authenticated=False)
        bodies = self._extract_bodies()
        for path in self.EXTRACT_PATHS:
            assert client.post(path, json=bodies[path]).status_code == 401
        assert client.post(self.PICK_PATH).status_code == 401


# ---------------------------------------------------------------------------
# §5.2 — 401 precedes service/storage access (spy test)
# ---------------------------------------------------------------------------


class TestSpy401PrecedesAccess:
    def test_anonymous_401_with_zero_service_calls(self, ve_ctx, monkeypatch):
        calls: list[str] = []

        def spy(name):
            def _spy(*args, **kwargs):
                calls.append(name)
                raise AssertionError(f"service function {name} must not run for anonymous requests")

            return _spy

        for fn in [
            "list_persons", "get_person", "create_person", "update_person",
            "delete_person", "list_assets", "get_asset", "create_asset",
            "update_asset", "delete_asset", "upsert_capacity_profile",
            "list_capacity_profiles", "get_capacity_profile",
        ]:
            monkeypatch.setattr(ve_service, fn, spy(fn))
        monkeypatch.setattr(
            wi_snapshot,
            "build_workspace_identity_snapshot",
            spy("build_workspace_identity_snapshot"),
        )
        client = _make_app(authenticated=False)
        pid = _seed_person(ve_ctx)
        aid = _seed_asset(ve_ctx)
        for method, url, body in [
            ("get", "/vision-execution/persons", None),
            ("get", f"/vision-execution/persons/{pid}", None),
            ("post", "/vision-execution/persons", {"name": "X"}),
            ("patch", f"/vision-execution/persons/{pid}", {"name": "Y"}),
            ("delete", f"/vision-execution/persons/{pid}", None),
            ("get", "/vision-execution/assets", None),
            ("get", f"/vision-execution/assets/{aid}", None),
            ("post", "/vision-execution/assets", {"name": "X"}),
            ("patch", f"/vision-execution/assets/{aid}", {"name": "Y"}),
            ("delete", f"/vision-execution/assets/{aid}", None),
            ("put", "/vision-execution/capacity-profiles", {"person_id": pid, "weekly_capacity_hours": 5}),
            ("get", "/vision-execution/capacity-profiles", None),
            ("get", f"/vision-execution/capacity-profiles/{pid}", None),
            ("get", "/vision-execution/workspace-identity", None),
            ("post", "/vision-execution/workspace-identity/scan", {"roots": [], "mode": "light_refresh"}),
        ]:
            resp = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
            assert resp.status_code == 401, (method, url, resp.status_code)
        assert calls == []


# ---------------------------------------------------------------------------
# §5.3 — Invalid / expired session → 401
# ---------------------------------------------------------------------------


class TestInvalidSession:
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/vision-execution/persons", None),
            ("post", "/vision-execution/assets", {"name": "X"}),
            ("put", "/vision-execution/capacity-profiles", {"person_id": "p", "weekly_capacity_hours": 1}),
            ("post", "/vision-execution/workspace-identity/scan", {"roots": [], "mode": "light_refresh"}),
        ],
    )
    def test_bogus_session_cookie_401(self, ve_ctx, method, url, body):
        client = _make_app(authenticated=False)
        client.cookies.set("zenaf_session", "bogus-token-that-matches-nothing")
        resp = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
        assert resp.status_code == 401
        assert "invalid" in resp.json().get("detail", "").lower() or "authenticated" in resp.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# §5.4 — Authenticated workflows remain functional
# ---------------------------------------------------------------------------


class TestAuthenticatedWorkflows:
    def test_authenticated_persons_crud(self, ve_ctx):
        client = _make_app(authenticated=True)
        created = client.post(
            "/vision-execution/persons",
            json={"name": "Functional Person", "role": "tester"},
        )
        assert created.status_code == 200, created.text
        pid = created.json()["id"]
        got = client.get(f"/vision-execution/persons/{pid}")
        assert got.status_code == 200
        assert got.json()["name"] == "Functional Person"
        listed = client.get("/vision-execution/persons")
        assert any(p["id"] == pid for p in listed.json())
        updated = client.patch(f"/vision-execution/persons/{pid}", json={"role": "lead"})
        assert updated.status_code == 200
        assert updated.json()["role"] == "lead"
        deleted = client.delete(f"/vision-execution/persons/{pid}")
        assert deleted.status_code == 200
        assert client.get(f"/vision-execution/persons/{pid}").status_code == 404

    def test_authenticated_assets_crud(self, ve_ctx):
        client = _make_app(authenticated=True)
        created = client.post(
            "/vision-execution/assets",
            json={"name": "Functional Asset", "asset_type": "tool"},
        )
        assert created.status_code == 200, created.text
        aid = created.json()["id"]
        assert client.get(f"/vision-execution/assets/{aid}").status_code == 200
        assert client.get("/vision-execution/assets").status_code == 200
        updated = client.patch(f"/vision-execution/assets/{aid}", json={"status": "active"})
        assert updated.status_code == 200
        assert updated.json()["status"] == "active"
        assert client.delete(f"/vision-execution/assets/{aid}").status_code == 200
        assert client.get(f"/vision-execution/assets/{aid}").status_code == 404

    def test_authenticated_capacity_upsert(self, ve_ctx):
        pid = _seed_person(ve_ctx)
        client = _make_app(authenticated=True)
        resp = client.put(
            "/vision-execution/capacity-profiles",
            json={"person_id": pid, "weekly_capacity_hours": 20.0},
        )
        assert resp.status_code == 200, resp.text
        row = ve_ctx.execute(
            "SELECT weekly_capacity_hours FROM capacity_profiles WHERE person_id = ?",
            (pid,),
        ).fetchone()
        assert row[0] == 20.0

    def test_authenticated_workspace_scan(self, ve_ctx, identity_dir, tmp_path, monkeypatch):
        """Authenticated scan of a permitted tmp root writes a snapshot
        under the (redirected) identity dir and returns a packet."""
        scan_root = tmp_path / "scan-me"
        scan_root.mkdir()
        (scan_root / "notes.md").write_text("# hello\n")
        (scan_root / "sub").mkdir()
        (scan_root / "sub" / "thing.txt").write_text("x")
        monkeypatch.setenv("ZENAF_SCAN_ALLOWED_ROOTS", str(scan_root))
        client = _make_app(authenticated=True)
        resp = client.post(
            "/vision-execution/workspace-identity/scan",
            json={"roots": [str(scan_root)], "mode": "light_refresh"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("ok") is True
        assert body.get("workspacePacket") is not None
        assert (identity_dir / "snapshot.json").exists()

    def test_authenticated_template_read_write(self, ve_ctx, identity_dir):
        client = _make_app(authenticated=True)
        put = client.put(
            "/vision-execution/workspace-identity/translation-template",
            json={"preferredPhrases": ["auth-wrote-this"]},
        )
        assert put.status_code == 200, put.text
        assert put.json().get("ok") is True
        got = client.get("/vision-execution/workspace-identity/translation-template")
        assert got.status_code == 200
        assert "auth-wrote-this" in got.json()["template"].get("preferredPhrases", [])

    def test_extract_meeting_auth_gate_shape(self, ve_ctx):
        """POST /extract-meeting was already protected (§6.2 control):
        anonymous 401, authenticated reaches the handler (shape only —
        no model call is asserted here)."""
        client_anon = _make_app(authenticated=False)
        assert client_anon.post(
            "/vision-execution/extract-meeting", json={"text": "hi"}
        ).status_code == 401
        client_auth = _make_app(authenticated=True)
        resp = client_auth.post("/vision-execution/extract-meeting", json={"text": "hi"})
        assert resp.status_code != 401, resp.text


# ---------------------------------------------------------------------------
# §5.5 — Scan-root allowlist
# ---------------------------------------------------------------------------


class TestScanRootAllowlist:
    def test_builder_rejects_out_of_allowlist_root(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        with pytest.raises(wi_snapshot.ScanRootsRejectedError):
            wi_snapshot.build_workspace_identity_snapshot(
                [str(outside)], repo_root=allowed, allowed_roots=[allowed]
            )

    def test_builder_rejects_mixed_roots_fail_closed(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "a.txt").write_text("a")
        outside = tmp_path / "outside"
        outside.mkdir()
        with pytest.raises(wi_snapshot.ScanRootsRejectedError):
            wi_snapshot.build_workspace_identity_snapshot(
                [str(allowed), str(outside)],
                repo_root=allowed,
                allowed_roots=[allowed],
            )

    def test_builder_allows_permitted_root(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "a.txt").write_text("a")
        snap = wi_snapshot.build_workspace_identity_snapshot(
            [str(allowed)], repo_root=allowed, allowed_roots=[allowed]
        )
        assert snap["sourceRoots"] == [str(allowed)]

    def test_builder_default_allowlist_is_repo_root(self, tmp_path):
        """With allowed_roots=None the only permitted root is repo_root."""
        repo = tmp_path / "repo"
        repo.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        with pytest.raises(wi_snapshot.ScanRootsRejectedError):
            wi_snapshot.build_workspace_identity_snapshot(
                [str(outside)], repo_root=repo
            )
        snap = wi_snapshot.build_workspace_identity_snapshot(
            [str(repo)], repo_root=repo
        )
        assert snap["sourceRoots"] == [str(repo)]

    def test_builder_rejects_symlink_escape(self, tmp_path):
        """A symlink inside the allowed tree that points outside it is
        resolved before the containment check and refused."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("s")
        link = allowed / "escape"
        link.symlink_to(outside, target_is_directory=True)
        with pytest.raises(wi_snapshot.ScanRootsRejectedError):
            wi_snapshot.build_workspace_identity_snapshot(
                [str(link)], repo_root=allowed, allowed_roots=[allowed]
            )

    def test_scan_allowed_roots_config(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        root.mkdir()
        extra = tmp_path / "extra"
        extra.mkdir()
        monkeypatch.setenv("ZENAF_SCAN_ALLOWED_ROOTS", str(extra))
        roots = hosted_config.scan_allowed_roots(root)
        assert str(root) in {str(r) for r in roots}
        assert str(extra) in {str(r) for r in roots}

    def test_scan_allowed_roots_skips_missing(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        root.mkdir()
        monkeypatch.setenv(
            "ZENAF_SCAN_ALLOWED_ROOTS", "/does/not/exist,/also/missing"
        )
        roots = hosted_config.scan_allowed_roots(root)
        assert [str(r) for r in roots] == [str(root)]

    def test_scan_allowed_roots_env_none(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        root.mkdir()
        monkeypatch.delenv("ZENAF_SCAN_ALLOWED_ROOTS", raising=False)
        roots = hosted_config.scan_allowed_roots(root)
        assert [str(r) for r in roots] == [str(root)]

    def test_http_scan_out_of_allowlist_403(self, ve_ctx, identity_dir, tmp_path):
        """The route maps ScanRootsRejectedError to 403 (authenticated,
        so the 401 gate is not the cause)."""
        client = _make_app(authenticated=True)
        resp = client.post(
            "/vision-execution/workspace-identity/scan",
            json={"roots": [str(tmp_path)], "mode": "light_refresh"},
        )
        assert resp.status_code == 403, resp.text
        assert not (identity_dir / "snapshot.json").exists()


# ---------------------------------------------------------------------------
# §6.2 — Previously protected routes remain protected
# ---------------------------------------------------------------------------


class TestPreviouslyProtectedRoutes:
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/vision-execution/radar", None),
            ("get", "/vision-execution/projects", None),
            ("get", "/vision-execution/capacity-profiles", None),
            ("post", "/vision-execution/extract-meeting", {"text": "hi"}),
            ("post", "/vision-execution/prompt-signals", {"context": "hi"}),
        ],
    )
    def test_previously_protected_still_401(self, ve_ctx, method, url, body):
        client = _make_app(authenticated=False)
        resp = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
        assert resp.status_code == 401, (method, url, resp.status_code)
