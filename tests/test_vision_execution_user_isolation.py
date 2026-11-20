"""Track B isolation — owner scoping for persons, assets, capacity.

Scope plan §6.4 + ownership migration brief §8: two users' rows are
invisible to each other; quarantined rows (user_id NULL) are invisible
to every user; cross-user references are refused; the capacity profile
is attributed WITH its person; an asset is never auto-attributed from
its owner person. The migration test (brief §6.1 step 5) proves a
pre-migration database migrates cleanly with all rows byte-identical
except the new NULL user_id.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.auth_routes import get_current_user
from api.routes import vision_execution as ve_routes
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import service as ve_service
from local_ai.vision_execution import storage as ve_storage


A = "user-a"
B = "user-b"


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    db_path = tmp_path / "ve.db"
    conn = ve_storage.open_sqlite_with_ve_pragmas(db_path)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    ve_storage.init_db(conn)
    yield conn
    conn.close()


def _app_for(user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(ve_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": user_id,
        "email": f"{user_id}@example.com",
    }
    return TestClient(app, raise_server_exceptions=False)


def _seed_quarantined(ve_ctx, table: str, row: tuple) -> None:
    """Insert a legacy row with user_id NULL (as the migration leaves it)."""
    cols = {
        "persons": "(id, name, role, relationship_type, contact_info, strengths,"
                   " needs, wants, availability, notes, created_at, updated_at)",
        "assets": "(id, name, asset_type, owner_id, status, availability, cost,"
                  " time_availability, linked_idea_ids, linked_initiative_ids,"
                  " linked_project_ids, notes, created_at, updated_at)",
        "capacity_profiles": "(person_id, weekly_capacity_hours, created_at, updated_at)",
    }[table]
    placeholders = ", ".join("?" * len(row))
    ve_ctx.execute(f"INSERT INTO {table} {cols} VALUES ({placeholders})", row)
    ve_ctx.commit()


# ---------------------------------------------------------------------------
# Storage-level isolation
# ---------------------------------------------------------------------------


class TestStorageIsolation:
    def test_persons_invisible_across_users(self, ve_ctx):
        p = ve_storage.create_person(ve_models.PersonCreate(name="Alice"), A)
        assert ve_storage.get_person(p["id"], B) is None
        assert ve_storage.list_persons(B) == []
        assert ve_storage.list_persons(A)[0]["id"] == p["id"]
        assert ve_storage.update_person(p["id"], ve_models.PersonUpdate(role="x"), B) is None
        assert ve_storage.delete_person(p["id"], B) is False
        assert ve_storage.get_person(p["id"], A) is not None

    def test_assets_invisible_across_users(self, ve_ctx):
        a = ve_storage.create_asset(ve_models.AssetCreate(name="Truck"), A)
        assert ve_storage.get_asset(a["id"], B) is None
        assert ve_storage.list_assets(B) == []
        assert ve_storage.update_asset(a["id"], ve_models.AssetUpdate(status="x"), B) is None
        assert ve_storage.delete_asset(a["id"], B) is False
        assert ve_storage.get_asset(a["id"], A) is not None

    def test_capacity_invisible_across_users(self, ve_ctx):
        p = ve_storage.create_person(ve_models.PersonCreate(name="Bob"), A)
        ve_storage.upsert_capacity_profile(
            ve_models.CapacityProfileUpsert(person_id=p["id"], weekly_capacity_hours=10), A
        )
        assert ve_storage.get_capacity_profile(p["id"], B) is None
        assert ve_storage.list_capacity_profiles(B) == []
        assert ve_storage.get_capacity_profile(p["id"], A)["weekly_capacity_hours"] == 10

    def test_capacity_attributed_with_its_person(self, ve_ctx):
        """The profile's owner is the person's owner, not whoever calls."""
        p = ve_storage.create_person(ve_models.PersonCreate(name="Carol"), A)
        cap = ve_storage.upsert_capacity_profile(
            ve_models.CapacityProfileUpsert(person_id=p["id"], weekly_capacity_hours=15), A
        )
        assert cap["user_id"] == A
        # Another user cannot upsert a profile for someone else's person.
        with pytest.raises(ValueError, match="Person not found"):
            ve_storage.upsert_capacity_profile(
                ve_models.CapacityProfileUpsert(person_id=p["id"], weekly_capacity_hours=99), B
            )
        assert ve_storage.get_capacity_profile(p["id"], A)["weekly_capacity_hours"] == 15

    def test_asset_never_auto_attributed_from_owner_person(self, ve_ctx):
        """The asset's owner is the session user, never the owner person.
        (The owner person and the session user happen to agree here; the
        cross-user half — B cannot reference A's person at all — is what
        makes the rule observable.)"""
        p = ve_storage.create_person(ve_models.PersonCreate(name="Dave"), A)
        a = ve_storage.create_asset(
            ve_models.AssetCreate(name="Van", owner_id=p["id"]), A
        )
        assert a["user_id"] == A
        assert a["owner_id"] == p["id"]
        # B cannot create an asset pointing at A's person.
        with pytest.raises(ValueError, match="Person not found"):
            ve_storage.create_asset(ve_models.AssetCreate(name="Van2", owner_id=p["id"]), B)
        # B cannot re-point an existing asset at A's person either.
        b_asset = ve_storage.create_asset(ve_models.AssetCreate(name="Bike"), B)
        with pytest.raises(ValueError, match="Person not found"):
            ve_storage.update_asset(
                b_asset["id"], ve_models.AssetUpdate(owner_id=p["id"]), B
            )

    def test_quarantined_rows_invisible_to_everyone(self, ve_ctx):
        _seed_quarantined(
            ve_ctx, "persons",
            ("q-person", "Quinn", "", "", "", "", "", "", "", "",
             "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        _seed_quarantined(
            ve_ctx, "assets",
            ("q-asset", "Quarry", "", None, "", "", "", "",
             "[]", "[]", "[]", "", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        _seed_quarantined(
            ve_ctx, "capacity_profiles",
            ("q-person", 8.0, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        for uid in (A, B):
            assert ve_storage.get_person("q-person", uid) is None
            assert ve_storage.get_asset("q-asset", uid) is None
            assert ve_storage.get_capacity_profile("q-person", uid) is None
            assert all(r["id"] != "q-person" for r in ve_storage.list_persons(uid))
            assert all(r["id"] != "q-asset" for r in ve_storage.list_assets(uid))
            assert ve_storage.update_person(
                "q-person", ve_models.PersonUpdate(role="x"), uid
            ) is None
            assert ve_storage.delete_person("q-person", uid) is False
            assert ve_storage.delete_asset("q-asset", uid) is False

    def test_delete_person_cascade_is_owner_scoped(self, ve_ctx):
        """Deleting A's person detaches only A's rows that reference it;
        B's rows that reference the same person id are untouched."""
        p = ve_storage.create_person(ve_models.PersonCreate(name="Erin"), A)
        # B has an asset whose owner_id happens to be the same person id
        # (only possible by direct SQL — the API refuses it). The cascade
        # must not detach it.
        ve_ctx.execute(
            "INSERT INTO assets (id, name, asset_type, owner_id, status, availability,"
            " cost, time_availability, linked_idea_ids, linked_initiative_ids,"
            " linked_project_ids, notes, created_at, updated_at, user_id)"
            " VALUES ('b-asset', 'B Van', '', ?, '', '', '', '', '[]', '[]', '[]', '',"
            " '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ?)",
            (p["id"], B),
        )
        ve_ctx.commit()
        a_asset = ve_storage.create_asset(
            ve_models.AssetCreate(name="A Van", owner_id=p["id"]), A
        )
        ve_storage.upsert_capacity_profile(
            ve_models.CapacityProfileUpsert(person_id=p["id"], weekly_capacity_hours=5), A
        )
        assert ve_storage.delete_person(p["id"], A) is True
        assert ve_storage.get_asset("b-asset", B)["owner_id"] == p["id"]
        assert ve_storage.get_asset(a_asset["id"], A)["owner_id"] is None
        assert ve_storage.get_capacity_profile(p["id"], A) is None


# ---------------------------------------------------------------------------
# HTTP-level isolation (the routes enforce it end to end)
# ---------------------------------------------------------------------------


class TestHttpIsolation:
    def test_http_persons_isolation(self, ve_ctx):
        ca, cb = _app_for(A), _app_for(B)
        created = ca.post("/vision-execution/persons", json={"name": "HTTP Alice"})
        assert created.status_code == 200, created.text
        pid = created.json()["id"]
        assert created.json()["user_id"] == A
        assert cb.get(f"/vision-execution/persons/{pid}").status_code == 404
        assert cb.get("/vision-execution/persons").json() == []
        assert cb.patch(f"/vision-execution/persons/{pid}", json={"role": "x"}).status_code == 404
        assert cb.delete(f"/vision-execution/persons/{pid}").status_code == 404
        assert ca.get(f"/vision-execution/persons/{pid}").status_code == 200

    def test_http_assets_isolation_and_cross_user_owner(self, ve_ctx):
        ca, cb = _app_for(A), _app_for(B)
        person = ca.post("/vision-execution/persons", json={"name": "HTTP Bob"})
        pid = person.json()["id"]
        created = ca.post(
            "/vision-execution/assets", json={"name": "HTTP Van", "owner_id": pid}
        )
        assert created.status_code == 200, created.text
        aid = created.json()["id"]
        assert created.json()["user_id"] == A
        assert cb.get(f"/vision-execution/assets/{aid}").status_code == 404
        assert cb.get("/vision-execution/assets").json() == []
        # B cannot create an asset pointing at A's person.
        resp = cb.post("/vision-execution/assets", json={"name": "Sneak", "owner_id": pid})
        assert resp.status_code == 404

    def test_http_capacity_isolation(self, ve_ctx):
        ca, cb = _app_for(A), _app_for(B)
        person = ca.post("/vision-execution/persons", json={"name": "HTTP Carol"})
        pid = person.json()["id"]
        up = ca.put(
            "/vision-execution/capacity-profiles",
            json={"person_id": pid, "weekly_capacity_hours": 30},
        )
        assert up.status_code == 200, up.text
        assert up.json()["user_id"] == A
        assert cb.get(f"/vision-execution/capacity-profiles/{pid}").status_code == 404
        assert cb.get("/vision-execution/capacity-profiles").json() == []
        # B cannot upsert a profile for A's person.
        resp = cb.put(
            "/vision-execution/capacity-profiles",
            json={"person_id": pid, "weekly_capacity_hours": 1},
        )
        assert resp.status_code == 404

    def test_http_quarantined_rows_invisible(self, ve_ctx):
        _seed_quarantined(
            ve_ctx, "persons",
            ("q-http", "Quinn", "", "", "", "", "", "", "", "",
             "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        for uid in (A, B):
            client = _app_for(uid)
            assert client.get("/vision-execution/persons/q-http").status_code == 404
            assert all(r["id"] != "q-http" for r in client.get("/vision-execution/persons").json())


# ---------------------------------------------------------------------------
# Migration test (brief §6.1 step 5)
# ---------------------------------------------------------------------------


class TestMigrationQuarantine:
    def test_premigration_db_migrates_with_null_user_id(self, tmp_path, monkeypatch):
        """A database with pre-migration rows (no user_id column) migrates
        cleanly; all rows carry user_id IS NULL afterward; row count and
        every other column are byte-identical before and after."""
        db = tmp_path / "legacy.db"
        raw = sqlite3.connect(db)
        raw.execute(
            "CREATE TABLE persons (id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',"
            " role TEXT NOT NULL DEFAULT '', relationship_type TEXT NOT NULL DEFAULT '',"
            " contact_info TEXT NOT NULL DEFAULT '', strengths TEXT NOT NULL DEFAULT '',"
            " needs TEXT NOT NULL DEFAULT '', wants TEXT NOT NULL DEFAULT '',"
            " availability TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',"
            " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        raw.execute(
            "CREATE TABLE capacity_profiles (person_id TEXT PRIMARY KEY,"
            " weekly_capacity_hours REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL, FOREIGN KEY (person_id) REFERENCES persons(id))"
        )
        raw.execute(
            "CREATE TABLE assets (id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',"
            " asset_type TEXT NOT NULL DEFAULT '', owner_id TEXT,"
            " status TEXT NOT NULL DEFAULT '', availability TEXT NOT NULL DEFAULT '',"
            " cost TEXT NOT NULL DEFAULT '', time_availability TEXT NOT NULL DEFAULT '',"
            " linked_idea_ids TEXT NOT NULL DEFAULT '[]',"
            " linked_initiative_ids TEXT NOT NULL DEFAULT '[]',"
            " linked_project_ids TEXT NOT NULL DEFAULT '[]',"
            " notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL, FOREIGN KEY (owner_id) REFERENCES persons(id))"
        )
        raw.execute(
            "INSERT INTO persons VALUES ('p1','Alice','r','rel','c','s','n','w','a','no',"
            "'2026-01-01T00:00:00Z','2026-01-02T00:00:00Z')"
        )
        raw.execute(
            "INSERT INTO capacity_profiles VALUES ('p1', 12.5,"
            "'2026-01-01T00:00:00Z','2026-01-02T00:00:00Z')"
        )
        raw.execute(
            "INSERT INTO assets VALUES ('a1','Truck','vehicle','p1','Active','x','y','z',"
            "'[]','[]','[]','n','2026-01-01T00:00:00Z','2026-01-02T00:00:00Z')"
        )
        raw.commit()
        before = {
            t: [tuple(r) for r in raw.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()]
            for t in ("persons", "capacity_profiles", "assets")
        }
        raw.close()
        monkeypatch.setattr(ve_storage, "get_connection", lambda: sqlite3.connect(db))
        conn = ve_storage.open_sqlite_with_ve_pragmas(db)
        ve_storage.init_db(conn)
        for t in ("persons", "capacity_profiles", "assets"):
            after = [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()]
            assert [r[:-1] for r in after] == before[t], t
            assert all(r[-1] is None for r in after), t
        # No backfill: the quarantined rows stay invisible to any user.
        assert ve_storage.get_person("p1", A) is None
        assert ve_storage.get_asset("a1", A) is None
        conn.close()

    def test_service_create_person_keyword_user_id(self, ve_ctx):
        """The mining_chat §10 call shape resolves and writes owned rows."""
        p = ve_service.create_person(
            ve_models.PersonCreate(name="Mined"), user_id=A
        )
        assert p["user_id"] == A
        a = ve_service.create_asset(
            ve_models.AssetCreate(name="Mined Asset"), user_id=A
        )
        assert a["user_id"] == A
