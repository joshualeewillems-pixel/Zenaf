"""Decisions security remediation — owner-scoped reads, fail-closed writes,
council-context isolation (verdict 2026-11-05).

Scope of the repair, precisely: decision-record reads are secured at the
storage layer (SQL predicate, required validated owner). The activity-log
residual is a SEPARATE unresolved security question and is NOT addressed
here; nothing in this file claims the repair eliminates every
decision-related exposure.

Deterministic only; no live model generation. The council negative fixture
drives run_council with a stubbed provider that records the assembled
prompts, so the test exercises the ACTUAL assembled context, not merely
a helper's filtered output.
"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI

from api.routes.auth_routes import get_current_user
from api.routes import vision_execution as ve_routes
from local_ai.judgment_substrate import SubjectRef
from local_ai.llm.execution_principal import authenticated_account_principal
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import storage as ve_storage


# -- VE fixture (same pattern as tests/test_decision_context.py) -------------


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    db_path = tmp_path / "ve.db"
    conn = ve_storage.open_sqlite_with_ve_pragmas(db_path)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    ve_storage.init_db(conn)
    yield conn
    conn.close()


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


def _make_decision(ve_ctx, uid: str, entity_id: str, decision_type: str = "priority_change") -> str:
    out = ve_storage.create_decision(
        ve_models.DecisionCreate(
            user_id=uid,
            entity_type="project",
            entity_id=entity_id,
            decision_type=decision_type,
            final_values_snapshot={"priority": "high"},
        )
    )
    return str(out["id"])


@pytest.fixture()
def two_users(ve_ctx):
    """User A and user B, each with a project (distinctive title) and a
    decision linked to their own project."""
    uid_a = _make_user(ve_ctx, "a@example.com")
    uid_b = _make_user(ve_ctx, "b@example.com")
    pid_a = _make_project(ve_ctx, uid_a, "ALPHA-ONLY project title")
    pid_b = _make_project(ve_ctx, uid_b, "BRAVO-ONLY project title")
    did_a = _make_decision(ve_ctx, uid_a, pid_a)
    did_b = _make_decision(ve_ctx, uid_b, pid_b)
    return {
        "uid_a": uid_a,
        "uid_b": uid_b,
        "pid_a": pid_a,
        "pid_b": pid_b,
        "did_a": did_a,
        "did_b": did_b,
    }


# -- storage boundary: owner required, validated, enforced in SQL -----------


def test_list_decisions_requires_valid_owner(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    # Each owner sees exactly their own row.
    rows_a = ve_storage.list_decisions(uid_a)
    assert [r["id"] for r in rows_a] == [two_users["did_a"]]
    rows_b = ve_storage.list_decisions(uid_b)
    assert [r["id"] for r in rows_b] == [two_users["did_b"]]
    # An unrelated owner sees nothing — not an error, not the rows.
    assert ve_storage.list_decisions("someone-else") == []
    # A required parameter is not a valid identity: empty / None rejected.
    with pytest.raises(ValueError):
        ve_storage.list_decisions("")
    with pytest.raises(ValueError):
        ve_storage.list_decisions(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ve_storage.list_decisions("   ")
    # Missing the positional entirely is a TypeError (required, not optional).
    with pytest.raises(TypeError):
        ve_storage.list_decisions()  # type: ignore[call-arg]


def test_get_decision_scoped_and_indistinguishable(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    did_a = two_users["did_a"]
    got = ve_storage.get_decision(did_a, uid_a)
    assert got is not None and got["id"] == did_a
    # Foreign id is indistinguishable from a missing one (404, not 403):
    # both return None, never confirming existence to a non-owner.
    assert ve_storage.get_decision(did_a, uid_b) is None
    assert ve_storage.get_decision("no-such-id", uid_a) is None
    with pytest.raises(ValueError):
        ve_storage.get_decision(did_a, "")
    with pytest.raises(ValueError):
        ve_storage.get_decision(did_a, None)  # type: ignore[arg-type]


def test_create_decision_rejects_empty_owner(ve_ctx):
    uid = _make_user(ve_ctx, "c@example.com")
    pid = _make_project(ve_ctx, uid, "Some project")
    with pytest.raises(ValueError):
        ve_storage.create_decision(
            ve_models.DecisionCreate(
                user_id="",
                entity_type="project",
                entity_id=pid,
                decision_type="priority_change",
            )
        )
    # The internal write model itself requires a real owner string:
    # None is rejected by validation, so no NULL-owner row can be built
    # through the model layer either.
    with pytest.raises(Exception):
        ve_models.DecisionCreate(
            user_id=None,  # type: ignore[arg-type]
            entity_type="project",
            entity_id=pid,
            decision_type="priority_change",
        )
    assert ve_storage.list_decisions(uid) == []


def test_null_owner_row_invisible_to_every_scoped_read(ve_ctx, two_users):
    uid_a = two_users["uid_a"]
    conn = ve_ctx
    conn.execute(
        "INSERT INTO decisions (id, user_id, entity_type, entity_id, decision_type, "
        "ai_proposal_snapshot, final_values_snapshot, created_at) "
        "VALUES (?, NULL, 'project', ?, 'priority_change', NULL, NULL, '2026-11-05T00:00:00Z')",
        ("null-owner-row", two_users["pid_a"]),
    )
    conn.commit()
    # Invisible to every scoped read — no owner can claim it.
    assert all(r["id"] != "null-owner-row" for r in ve_storage.list_decisions(uid_a))
    assert all(r["id"] != "null-owner-row" for r in ve_storage.list_decisions(two_users["uid_b"]))
    assert ve_storage.get_decision("null-owner-row", uid_a) is None


def test_ownership_filter_applies_before_limit(ve_ctx, two_users):
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    # Five newer decisions for B; A's single decision is older. A post-query
    # filter with limit=3 would return [] (B's rows fill the window);
    # a SQL WHERE before LIMIT returns A's row.
    for i in range(5):
        _make_decision(ve_ctx, uid_b, two_users["pid_b"], decision_type=f"extra_{i}")
    rows = ve_storage.list_decisions(uid_a, limit=3)
    assert [r["id"] for r in rows] == [two_users["did_a"]]


def test_decisions_user_created_index_explicit_call_only(ve_ctx):
    conn = ve_ctx
    # A fresh init_db does NOT create the index — the migration helper is
    # explicit-call only and is never auto-run.
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_decisions_user_created'"
    ).fetchone() is None
    ve_storage.migrate_decisions_user_created_index(conn)
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_decisions_user_created'"
    ).fetchone() is not None
    # Idempotent: a second call is a no-op, not an error.
    ve_storage.migrate_decisions_user_created_index(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='idx_decisions_user_created'"
    ).fetchone()[0] == 1


# -- API: POST accepts legacy payloads; ownership comes from the session ---


def _run_asgi(app, method: str, path: str, payload: dict | None = None):
    """Drive one request through the app's ASGI interface (no httpx here)."""
    import asyncio
    import json

    body = json.dumps(payload).encode() if payload is not None else b""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")] if payload is not None else [],
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


def test_route_post_accepts_user_id_null_payload_and_stamps_session_owner(ve_ctx, two_users):
    uid_a = two_users["uid_a"]
    ve_storage.upsert_user_permissions_settings(
        uid_a,
        permissions={"profile_learning": True},
        consent_acknowledged=True,
        consent_version="test-v1",
    )
    app = FastAPI()
    app.include_router(ve_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": uid_a}

    # Legacy payload shape: older clients still send user_id: null.
    # The request model carries no ownership field; it must be accepted
    # and the row stamped with the AUTHENTICATED id, never the payload's.
    status, body = _run_asgi(
        app,
        "POST",
        "/vision-execution/decisions",
        {
            "user_id": None,
            "entity_type": "project",
            "entity_id": two_users["pid_a"],
            "decision_type": "priority_change",
            "final_values_snapshot": {"priority": "high"},
        },
    )
    assert status == 200, body
    assert body["user_id"] == uid_a

    # And a payload that tries to claim another owner is still stamped
    # with the session user — client-supplied ownership is ignored.
    status, body = _run_asgi(
        app,
        "POST",
        "/vision-execution/decisions",
        {
            "user_id": two_users["uid_b"],
            "entity_type": "project",
            "entity_id": two_users["pid_a"],
            "decision_type": "priority_change",
        },
    )
    assert status == 200, body
    assert body["user_id"] == uid_a

    # GET is owner-scoped: the session user sees their rows only.
    status, body = _run_asgi(app, "GET", "/vision-execution/decisions")
    assert status == 200, body
    assert {row["id"] for row in body} >= {two_users["did_a"]}
    assert two_users["did_b"] not in {row["id"] for row in body}


# -- council negative fixture: the actual assembled context ----------------


class _CapturingProvider:
    """Deterministic stub: records every assembled prompt, returns canned text."""

    def __init__(self):
        self.prompts: list[str] = []
        self.model = "fake-test-model"
        self.council_provider_id = "fake"

    def generate(self, prompt, timeout=None, **_kw):
        self.prompts.append(prompt)
        return "Guide:\nA short grounded answer.\n"


def test_council_negative_fixture(ve_ctx, two_users, monkeypatch):
    from local_ai import zenaf_tools

    provider = _CapturingProvider()
    monkeypatch.setattr(
        "local_ai.llm.resolver.get_council_provider_for_principal",
        lambda *a, **k: provider,
    )
    uid_a, uid_b = two_users["uid_a"], two_users["uid_b"]
    pid_a = two_users["pid_a"]

    # -- Council under A's authenticated principal, about A's project. --
    # subject_ref carries A's title (caller-supplied); the decision lines
    # and the decisions block must come from storage, owner-scoped to A.
    result_a = zenaf_tools.run_council(
        "What is the next step for this project?",
        context="Decide the next step.",
        included_roles=["guide"],
        subject_ref=SubjectRef(entity_type="project", entity_id=pid_a, title="ALPHA-ONLY project title"),
        execution_principal=authenticated_account_principal(uid_a),
        council_user_id=uid_a,
    )
    assert isinstance(result_a, str) and result_a.strip()
    assert provider.prompts, "the stubbed provider received no seat prompt"
    joined_a = "\n".join(provider.prompts)
    # A's decision material IS present (own context works): the decisions
    # block header, a decision line naming A's project, and the working
    # memory "Related decisions" section.
    assert "Recent decisions relevant to your role" in joined_a
    # Decision lines render as "Decision <last-3-of-id>: <summary> ...".
    assert re.search(r"Decision [0-9a-f]{3}: ALPHA-ONLY project title", joined_a)
    assert "Related decisions:" in joined_a
    # B's decision snapshots and B's entity details are ABSENT.
    assert "BRAVO-ONLY project title" not in joined_a

    # -- Anonymous council invocation (no principal, no user id). --
    # The subject_ref here deliberately carries NO title: any ALPHA/BRAVO
    # occurrence would then prove a storage leak, since the only other
    # source of those strings is the stored rows.
    provider.prompts.clear()
    result_anon = zenaf_tools.run_council(
        "What is the next step for this project?",
        context="Decide the next step.",
        included_roles=["guide"],
        subject_ref=SubjectRef(entity_type="project", entity_id=pid_a),
        execution_principal=None,
        council_user_id=None,
    )
    assert isinstance(result_anon, str) and result_anon.strip()
    assert provider.prompts, "the stubbed provider received no seat prompt"
    joined_anon = "\n".join(provider.prompts)
    # NO decision-derived material from either user. (The bare word
    # "Decision" can appear in persona/constraints prose, so the precise
    # markers are the block header, the "Related decisions" section, and
    # the rendered "Decision <id>:" line format.)
    assert "Recent decisions relevant to your role" not in joined_anon
    assert "Related decisions:" not in joined_anon
    assert re.search(r"Decision [0-9a-f]{3}:", joined_anon) is None
    assert "ALPHA-ONLY project title" not in joined_anon
    assert "BRAVO-ONLY project title" not in joined_anon


def test_decision_helpers_fail_closed_without_owner(ve_ctx, two_users):
    from local_ai import zenaf_tools

    # Helper-level: no owner means no rows and no block, never an
    # unscoped read — even though rows exist in the store.
    assert zenaf_tools.collect_decision_context("Guide", user_id=None) == []
    assert zenaf_tools.collect_decision_context("Guide", user_id="") == []
    assert zenaf_tools._format_decision_context_block("Guide", user_id=None) is None
    assert zenaf_tools._collect_decision_rows(None) == []
    # With the owner, the same helpers return the owner's rows.
    items = zenaf_tools.collect_decision_context("Guide", user_id=two_users["uid_a"])
    assert len(items) == 1
    assert items[0]["summary"] == "ALPHA-ONLY project title"
    block = zenaf_tools._format_decision_context_block("Guide", user_id=two_users["uid_a"])
    assert block is not None and "ALPHA-ONLY project title" in block
    assert "BRAVO-ONLY project title" not in block
