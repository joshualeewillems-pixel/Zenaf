"""Upload rapid-fire S1 — outcomes, menu actions, promotion tests
(brief §16, T9–T10, T34–T50).

Route tests use TestClient + tmp SQLite (conversation + agent + VE);
the model-call boundary is patched with a raising stub where a test
asserts zero model calls. No live model anywhere. All store calls use
the real ConversationStore API (user_id first; save_* return the full
row dict; append_message returns the message dict).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.agent_routes as agent_routes
import api.routes.conversation_routes as conv_routes
import local_ai.conversation.service as service_mod
import local_ai.conversation.upload_extraction as ue
import local_ai.conversation.upload_round as UR
import local_ai.vision_execution.storage as ve_storage
from api.routes.auth_routes import get_current_user
from local_ai.agent_intake import pipeline as intake_pipeline
from local_ai.agent_intake.store import AgentStore
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.vision_execution.models import ProjectCreate

USER = "u1"
ALICE = {"id": USER}
STRAND = "heart"

TEXT = (
    "The morning light fell across the kitchen table where the letters "
    "had been left in a neat stack. The gardener reads the room slowly, "
    "noticing which seeds are already sprouting."
)
SPAN_A = "The morning light fell across the kitchen table"


@pytest.fixture()
def store(tmp_path: Path) -> ConversationStore:
    s = ConversationStore(db_path=tmp_path / "conv.db")
    yield s
    s.close()


@pytest.fixture()
def agent_store(tmp_path: Path) -> AgentStore:
    s = AgentStore(db_path=tmp_path / "agents.db", user_id=USER)
    yield s
    s.close()


@pytest.fixture()
def ve_conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    ve_storage.init_db(conn)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture()
def route_client(tmp_path, monkeypatch, agent_store, store, ve_conn):
    monkeypatch.setattr(conv_routes, "_store", lambda: store)
    monkeypatch.setattr(conv_routes, "_agent_store", lambda user_id: agent_store)
    monkeypatch.setattr(agent_routes, "_store", lambda user_id: agent_store)
    signals: list[dict] = []
    monkeypatch.setattr(
        intake_pipeline,
        "log_claim_feedback",
        lambda *a, **kw: signals.append({"args": a, "kwargs": kw}),
    )
    app = FastAPI()
    app.include_router(conv_routes.router)
    app.include_router(agent_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ALICE
    client = TestClient(app)
    client.signals = signals  # type: ignore[attr-defined]
    yield client


def _seed_doc(store: ConversationStore, n: int = 1, *, text: str = TEXT):
    convo = store.resolve_strand_thread(USER, STRAND)["conversation_id"]
    src = store.add_strand_source(
        USER, STRAND, convo, kind="paste", ref="paste-1", label="Field notes",
        excerpt_redacted=text[:2000], paste_full_text=text,
    )
    doc = src["id"]
    ids = []
    for i in range(n):
        span = store.save_upload_span(
            USER, doc, 1, "seg-0000", SPAN_A, "redacted", f"seg-0000:0-{len(SPAN_A)}"
        )
        row = store.save_upload_interpretation(
            USER, doc, 1, STRAND, "strand",
            f"Reading {i + 1}: the day moved.",
            [{"span_id": span["span_id"], "role": "primary"}],
            [], "extracted", False, "task", None, None, False,
        )
        ids.append(row["interpretation_id"])
    return convo, doc, ids


def _present(store, convo, interp_id) -> str:
    msg = store.append_message(
        USER, convo, "conductor", "voice", "reply", "talk",
        {"round_kind": "upload", "round_id": "round-1",
         "round_state": "item", "round_interpretation_id": interp_id},
    )
    return msg["id"]


def _act(client, action, interp_id, convo, msg_id, **extra):
    return client.post(
        f"/conversation/upload/outcomes/{interp_id}/{action}",
        json={"conversation_id": convo, "message_id": msg_id, **extra},
    )


# -- extract accept (T9–T10) --------------------------------------------------------


def test_t9_accept_returns_202_plus_job_id(route_client, store, monkeypatch):
    monkeypatch.setattr(
        conv_routes, "start_upload_extraction_job", lambda *a, **k: None
    )
    convo, doc, ids = _seed_doc(store)
    r = route_client.post("/conversation/upload/extract", json={"source_id": doc})
    assert r.status_code == 202
    body = r.json()
    assert body["job"]["job_id"]
    assert store.get_upload_job(USER, body["job"]["job_id"]) is not None


def test_t10_duplicate_accept_returns_live_job(route_client, store, monkeypatch):
    monkeypatch.setattr(
        conv_routes, "start_upload_extraction_job", lambda *a, **k: None
    )
    convo, doc, ids = _seed_doc(store)
    r1 = route_client.post("/conversation/upload/extract", json={"source_id": doc})
    r2 = route_client.post("/conversation/upload/extract", json={"source_id": doc})
    assert r2.status_code == 202
    assert r2.json()["job"]["job_id"] == r1.json()["job"]["job_id"]
    assert len(store.list_upload_jobs(USER, doc)) == 1


# -- menu + card (T34–T41) ----------------------------------------------------------


def test_t34_keep_writes_only_its_effect(route_client, store, ve_conn):
    convo, doc, ids = _seed_doc(store)
    msg = _present(store, convo, ids[0])
    r = _act(route_client, "keep", ids[0], convo, msg)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"]["kind"] == "keep"
    assert body["outcome"]["status"] == "created"
    assert body["outcome"]["ve_kind"] is None
    assert store.get_upload_interpretation(USER, ids[0])["status"] == "ruled"
    # Only that effect: no invitation, no VE record, no claim, no artifact.
    assert store.list_pending_invitations(USER) == []
    assert ve_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert store.list_upload_artifacts(USER, doc) == []


def test_t35_voice_mapping_routes_each_action_to_its_seat(route_client, store, ve_conn):
    # Amendment A2: artifact / undertaking / train return a
    # next_voice redirect to their seat; Talk it through does NOT
    # (Crane joins the open thread — no redirect) but DOES invite
    # Crane, and records nothing.
    cases = [
        ("artifact", "maverick"),
        ("undertaking", "champion"),
        ("train", "conductor"),
    ]
    for action, seat in cases:
        convo, doc, ids = _seed_doc(store, n=1)
        msg = _present(store, convo, ids[0])
        extra = {}
        if action == "artifact":
            extra = {"artifact_kind": "kept-reading"}
        if action == "undertaking":
            extra = {"kind": "task"}
        r = _act(route_client, action, ids[0], convo, msg, **extra)
        assert r.status_code == 200, (action, r.text)
        assert r.json()["next_voice"]["archetype_id"] == seat
        inv = store.list_pending_invitations(USER)
        assert any(v["seat"] == seat for v in inv), action
    convo, doc, ids = _seed_doc(store, n=1)
    msg = _present(store, convo, ids[0])
    r = _act(route_client, "talk", ids[0], convo, msg)
    assert r.status_code == 200, r.text
    assert r.json().get("next_voice") is None
    assert r.json().get("invited_seat") == "ambassador"
    inv = store.list_pending_invitations(USER)
    assert any(v["seat"] == "ambassador" for v in inv)
    assert store.get_upload_interpretation(USER, ids[0])["status"] == "pending"
    assert store.get_upload_outcome_by_interp_kind(USER, ids[0], "explore") is None


def test_t36_remind_and_archive_create_no_invitation(route_client, store):
    convo, doc, ids = _seed_doc(store, n=2)
    msg = _present(store, convo, ids[0])
    r = route_client.post(
        "/conversation/upload/round/reserve",
        json={"conversation_id": convo, "message_id": msg,
              "interpretation_id": ids[0], "snooze_days": 1},
    )
    assert r.status_code == 200, r.text
    assert store.list_pending_invitations(USER) == []
    # Archive-it: reserve never + the outcome row archived, still no invitation.
    msg2 = _present(store, convo, ids[1])
    r2 = route_client.post(
        "/conversation/upload/round/reserve",
        json={"conversation_id": convo, "message_id": msg2,
              "interpretation_id": ids[1], "archive": True},
    )
    assert r2.status_code == 200, r2.text
    assert store.list_pending_invitations(USER) == []
    out = store.get_upload_outcome_by_interp_kind(USER, ids[1], "keep")
    assert out is not None and out["status"] == "archived"
    # Amendment A2: Archive-it closes the reading — the
    # interpretation flips to 'ruled' (it leaves the round queue).
    assert store.get_upload_interpretation(USER, ids[1])["status"] == "ruled"


def test_t37_train_files_pending_claim_invites_weaver_writes_no_signal(
    route_client, store, agent_store, ve_conn
):
    convo, doc, ids = _seed_doc(store)
    msg = _present(store, convo, ids[0])
    r = _act(route_client, "train", ids[0], convo, msg)
    assert r.status_code == 200, r.text
    assert r.json()["next_voice"]["archetype_id"] == "conductor"
    claim_id = f"upload-conductor-{doc}:upload_interpretation:{ids[0]}"
    claims = agent_store.get_claims(f"upload-conductor-{doc}")
    claim = next((c for c in claims if c.id == claim_id), None)
    assert claim is not None
    assert claim.claim_type == "upload_interpretation"
    assert claim.status == "pending"
    assert store.get_upload_interpretation(USER, ids[0])["status"] == "ruled"
    # No training signal: the claim-feedback pipeline was never called.
    assert route_client.signals == []
    # No outcome row, no VE record.
    assert store.list_upload_outcomes(USER, ids[0]) == []
    assert ve_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_t38_item_state_renders_the_verbatim_interpretation(route_client, store):
    convo, doc, ids = _seed_doc(store)
    msg = _present(store, convo, ids[0])
    r = route_client.get(
        "/conversation/upload/item-state",
        params={"conversation_id": convo, "message_id": msg,
                "interpretation_id": ids[0]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["interpretation"]["text"] == "Reading 1: the day moved."
    assert body["interpretation"]["interpretation_id"] == ids[0]


def test_t39_prose_yes_writes_nothing(route_client, store, agent_store, monkeypatch):
    # After an offer, a prose "yes" starts the round — but rules nothing.
    # The offer gate runs on an ordinary turn (invoke starts a round,
    # never offers); the seat must voice the marker for the offer row
    # to be recorded.
    monkeypatch.setenv("ZENAF_UPLOAD_ROUND", "1")
    convo, doc, ids = _seed_doc(store, n=3)
    captured: list = []

    def fake(prompt, **kw):
        captured.append(prompt)
        if "[[round-offer]]" in prompt:
            return "Some readings are waiting for you.\n[[round-offer]]"
        return "noted"

    monkeypatch.setattr(service_mod, "AgentStore", lambda user_id: agent_store)
    svc = ConversationService(store, generate_fn=fake)
    r1 = svc.turn(USER, "conductor", "The garden needs watering today.", convo, "talk")
    assert "[[round-offer]]" in captured[-1]
    r2 = svc.turn(USER, "conductor", "yes", convo, "talk")
    assert r2.round_item is not None  # the round started
    assert store.list_upload_outcomes(USER, ids[0]) == []
    assert store.list_upload_artifacts(USER, doc) == []
    claims = agent_store.get_claims(f"upload-conductor-{doc}")
    assert not any(c.id.endswith(f":upload_interpretation:{ids[0]}") for c in claims)
    assert all(
        store.get_upload_interpretation(USER, i)["status"] == "pending" for i in ids
    )


def test_t40_mount_fetch_cannot_clobber_the_turns_item(route_client, store):
    convo, doc, ids = _seed_doc(store)
    msg = _present(store, convo, ids[0])
    # A nonexistent message id is a 404 (nothing to present).
    r = route_client.get(
        "/conversation/upload/item-state",
        params={"conversation_id": convo, "message_id": "not-the-presenting-message",
                "interpretation_id": ids[0]},
    )
    assert r.status_code == 404
    # A real message that never presented this item is a 409.
    other = store.append_message(
        USER, convo, "conductor", "voice", "an ordinary reply", "talk", {}
    )["id"]
    r409 = route_client.get(
        "/conversation/upload/item-state",
        params={"conversation_id": convo, "message_id": other,
                "interpretation_id": ids[0]},
    )
    assert r409.status_code == 409
    # The presenting message can.
    r2 = route_client.get(
        "/conversation/upload/item-state",
        params={"conversation_id": convo, "message_id": msg,
                "interpretation_id": ids[0]},
    )
    assert r2.status_code == 200
    assert r2.json()["interpretation"]["interpretation_id"] == ids[0]
    # A decided item still returns its state (no standing check here).
    store.set_upload_interpretation_status(USER, ids[0], "ruled")
    r3 = route_client.get(
        "/conversation/upload/item-state",
        params={"conversation_id": convo, "message_id": msg,
                "interpretation_id": ids[0]},
    )
    assert r3.status_code == 200


def test_t41_artifact_and_talk_write_only_their_effects(route_client, store, ve_conn):
    convo, doc, ids = _seed_doc(store, n=2)
    msg = _present(store, convo, ids[0])
    r = _act(
        route_client, "artifact", ids[0], convo, msg,
        artifact_kind="kept-reading",
    )
    assert r.status_code == 200, r.text
    assert len(store.list_upload_artifacts(USER, doc)) == 1
    assert store.list_upload_outcomes(USER, ids[0]) == []
    assert ve_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert ve_conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    # Talk it through (amendment A2): no outcome row, no VE record,
    # and the interpretation stays pending — talking isn't deciding.
    msg2 = _present(store, convo, ids[1])
    r2 = _act(route_client, "talk", ids[1], convo, msg2)
    assert r2.status_code == 200, r2.text
    assert store.list_upload_outcomes(USER, ids[1]) == []
    assert ve_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert ve_conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    assert store.get_upload_interpretation(USER, ids[1])["status"] == "pending"


# -- undertaking + artifact (T42–T46) ------------------------------------------------


def test_t42_replay_returns_existing_outcome_no_second_ve_record(
    route_client, store, ve_conn
):
    convo, doc, ids = _seed_doc(store)
    msg = _present(store, convo, ids[0])
    r1 = _act(route_client, "undertaking", ids[0], convo, msg, kind="task")
    assert r1.status_code == 200, r1.text
    out1 = r1.json()["outcome"]
    assert out1["status"] == "created"
    assert ve_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    # Replay taps the OUTCOME id from the first response — that is
    # the address the replay guard recognizes.
    r2 = _act(route_client, "undertaking", out1["outcome_id"], convo, msg, kind="task")
    assert r2.status_code == 200, r2.text
    assert r2.json()["outcome"]["outcome_id"] == out1["outcome_id"]
    assert ve_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_t42b_stacking_across_kinds_allowed_same_kind_conflicts(route_client, store, ve_conn):
    # Amendment A2: cross-kind stacking is allowed — one outcome
    # per (interpretation, kind); the 409 applies only to a second
    # outcome of the SAME kind.
    convo, doc, ids = _seed_doc(store, n=2)
    msg = _present(store, convo, ids[0])
    r1 = _act(route_client, "keep", ids[0], convo, msg)
    assert r1.status_code == 200, r1.text
    # Talk it through records nothing: 200, and the reading is
    # still open for a verdict (no outcome row of any kind).
    r2 = _act(route_client, "talk", ids[0], convo, msg)
    assert r2.status_code == 200, r2.text
    assert store.get_upload_outcome_by_interp_kind(USER, ids[0], "explore") is None
    # Mine for projects (a DIFFERENT kind) stacks on Keep: 200.
    r3 = _act(route_client, "undertaking", ids[0], convo, msg, kind="task")
    assert r3.status_code == 200, r3.text
    # Keep again via the interpretation id replays the existing
    # keep outcome (same kind, status 'created'): 200, same id.
    r4 = _act(route_client, "keep", ids[0], convo, msg)
    assert r4.status_code == 200, r4.text
    assert r4.json()["outcome"]["outcome_id"] == r1.json()["outcome"]["outcome_id"]
    # The same-kind 409: Archive-it files a keep outcome
    # ('archived') on the second reading; a later Keep on it is
    # refused — a keep outcome already exists, in a non-created
    # status.
    msg2 = _present(store, convo, ids[1])
    r5 = route_client.post(
        "/conversation/upload/round/reserve",
        json={"conversation_id": convo, "message_id": msg2,
              "interpretation_id": ids[1], "archive": True},
    )
    assert r5.status_code == 200, r5.text
    r6 = _act(route_client, "keep", ids[1], convo, msg2)
    assert r6.status_code == 409, r6.text


class _CarrierFailingConnection:
    """A test double: the carrier INSERT dies between the VE insert
    and the carrier insert — the transaction must roll both back."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        if "upload_outcome_creations" in sql:
            raise RuntimeError("killed between the VE insert and the carrier insert")
        return self._conn.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_t43_carrier_and_ve_record_commit_together(route_client, store, ve_conn, monkeypatch):
    from local_ai.vision_execution.storage import approve_upload_outcome

    convo, doc, ids = _seed_doc(store)
    outcome = store.create_upload_outcome(USER, doc, 1, ids[0], "task", None)
    failing = _CarrierFailingConnection(ve_conn)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: failing)
    with pytest.raises(RuntimeError, match="killed between"):
        approve_upload_outcome(
            USER, outcome["outcome_id"], kind="task", title="The day moved",
            detail="Reading 1: the day moved.", store=store,
        )
    # No orphan VE record and no orphan carrier row. Both checks use
    # the raw connection: the module-level getter is still patched
    # to the failing double inside this test.
    assert ve_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert (
        ve_conn.execute(
            "SELECT COUNT(*) FROM upload_outcome_creations WHERE outcome_id = ?",
            (outcome["outcome_id"],),
        ).fetchone()[0]
        == 0
    )
    assert store.get_upload_outcome(USER, outcome["outcome_id"])["status"] == "pending"


def test_t44b_stuck_outcome_retry_reclaims_after_one_hour(store, ve_conn):
    # Amendment A4: a 'creating' outcome with no carrier row may
    # re-take the claim — but only when it is older than one hour.
    # A younger stuck outcome is presumed live and the retry is
    # refused with 'Still creating — check back shortly'.
    from datetime import datetime, timedelta, timezone

    from local_ai.vision_execution.storage import (
        UploadOutcomeStuckError,
        approve_upload_outcome,
    )

    convo, doc, ids = _seed_doc(store)
    old = store.create_upload_outcome(USER, doc, 1, ids[0], "task", None)
    assert store.claim_upload_outcome(USER, old["outcome_id"]) is True
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with store._lock:
        store._conn.execute(
            "UPDATE upload_outcomes SET created_at = ? WHERE outcome_id = ?",
            (stale, old["outcome_id"]),
        )
        store._conn.commit()
    approved = approve_upload_outcome(
        USER, old["outcome_id"], kind="task", title="The day moved",
        detail="Reading 1: the day moved.", store=store,
    )
    assert approved["outcome"]["status"] == "created"
    assert approved["record"], "the VE task record"
    assert ve_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    # A young stuck outcome (a different kind on the same reading —
    # stacking) is presumed live: the retry is refused, nothing is
    # created, and the outcome stays 'creating'.
    young = store.create_upload_outcome(USER, doc, 1, ids[0], "project", None)
    assert store.claim_upload_outcome(USER, young["outcome_id"]) is True
    with pytest.raises(UploadOutcomeStuckError, match="Still creating"):
        approve_upload_outcome(
            USER, young["outcome_id"], kind="project", title="The day moved",
            detail="Reading 1: the day moved.", store=store,
        )
    assert store.get_upload_outcome(USER, young["outcome_id"])["status"] == "creating"
    assert ve_conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0


def test_t44c_reclaim_race_loses_to_another_session(store, ve_conn, monkeypatch):
    # Amendment A4: if the re-claim CAS loses (another session owns
    # the retry), the retry is refused with the §8.2 409 copy.
    from local_ai.vision_execution.storage import ProposalConflict, approve_upload_outcome

    convo, doc, ids = _seed_doc(store)
    outcome = store.create_upload_outcome(USER, doc, 1, ids[0], "task", None)
    assert store.claim_upload_outcome(USER, outcome["outcome_id"]) is True
    # Old enough to pass the one-hour gate, so the retry reaches
    # the re-claim CAS — then loses it.
    from datetime import datetime, timedelta, timezone

    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with store._lock:
        store._conn.execute(
            "UPDATE upload_outcomes SET created_at = ? WHERE outcome_id = ?",
            (stale, outcome["outcome_id"]),
        )
        store._conn.commit()
    # Force the re-claim to lose: the CAS sees 'creating' but
    # returns False (a concurrent retry won it first).
    monkeypatch.setattr(
        store, "reclaim_upload_outcome", lambda user_id, outcome_id: False
    )
    with pytest.raises(ProposalConflict, match="Already decided"):
        approve_upload_outcome(
            USER, outcome["outcome_id"], kind="task", title="The day moved",
            detail="Reading 1: the day moved.", store=store,
        )


def test_t44_creating_outcome_renders_with_no_ve_link(route_client, store, ve_conn):
    convo, doc, ids = _seed_doc(store)
    msg = _present(store, convo, ids[0])
    outcome = store.create_upload_outcome(USER, doc, 1, ids[0], "task", None)
    assert store.claim_upload_outcome(USER, outcome["outcome_id"]) is True
    assert store.get_upload_outcome(USER, outcome["outcome_id"])["status"] == "creating"
    r = route_client.get(
        "/conversation/upload/item-state",
        params={"conversation_id": convo, "message_id": msg,
                "interpretation_id": ids[0]},
    )
    assert r.status_code == 200
    out = r.json()["outcome"]
    assert out is not None
    assert out["status"] == "creating"
    assert out["ve_kind"] is None
    assert out["ve_id"] is None


def test_t45_parentage_chooser_never_applies_without_acceptance(
    store, agent_store, monkeypatch, ve_conn
):
    # Two recent projects: the chooser lists them, the suggestion slot
    # stays null, and nothing is created without a tap. ve_conn keeps
    # the projects in an isolated in-memory VE DB (the real VE DB is
    # shared across runs and must not accumulate test projects).
    import local_ai.vision_execution.storage as vs

    vs.create_project(ProjectCreate(title="Garden"), USER)
    vs.create_project(ProjectCreate(title="Kitchen"), USER)
    convo, doc, ids = _seed_doc(store, n=1)
    monkeypatch.setenv("ZENAF_UPLOAD_ROUND", "1")
    captured: list = []

    def fake(prompt, **kw):
        captured.append(prompt)
        return "noted"

    monkeypatch.setattr(service_mod, "AgentStore", lambda user_id: agent_store)
    svc = ConversationService(store, generate_fn=fake)
    r = svc.turn(USER, "conductor", "What's waiting for me?", convo, "talk")
    assert r.round_item is not None
    titles = [p["title"] for p in r.round_item["rendering"]["parentage_options"]]
    assert set(titles) == {"Kitchen", "Garden"}
    assert r.round_item["rendering"]["parentage_suggestion"] is None
    # Nothing created without a tap.
    assert len(vs.list_projects(USER)) == 2


def test_t46_artifact_creates_no_ve_record_and_no_node(route_client, store, ve_conn):
    convo, doc, ids = _seed_doc(store)
    msg = _present(store, convo, ids[0])
    r = _act(
        route_client, "artifact", ids[0], convo, msg,
        artifact_kind="kept-reading",
    )
    assert r.status_code == 200, r.text
    assert ve_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert ve_conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    assert ve_conn.execute(
        "SELECT COUNT(*) FROM upload_outcome_creations"
    ).fetchone()[0] == 0
    nodes = ve_conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='nodes'"
    ).fetchone()[0]
    if nodes:
        assert ve_conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0


# -- promotion (T47–T50) -------------------------------------------------------------


def _assistant_message(store, convo, body: str) -> str:
    msg = store.append_message(
        USER, convo, "conductor", "voice", body, "talk",
        {"round_kind": "upload", "round_id": "round-1", "round_state": "item"},
    )
    return msg["id"]


def test_t47_promotion_writes_pending_promoted_with_zero_model_calls(
    route_client, store, monkeypatch
):
    monkeypatch.setattr(
        ue, "_ollama_complete",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")),
    )
    convo, doc, ids = _seed_doc(store)
    store.append_message(USER, convo, "conductor", "voice", "user turn", "talk", {})
    msg = _assistant_message(
        store, convo,
        f"Here is a reading: \"{SPAN_A}\". The day moved from order to improvisation.",
    )
    r = route_client.post(
        "/conversation/upload/promote",
        json={"conversation_id": convo, "message_id": msg},
    )
    assert r.status_code == 200, r.text
    assert r.json()["promoted"] is True
    interp = store.get_upload_interpretation(
        USER, r.json()["interpretation"]["interpretation_id"]
    )
    assert interp is not None
    assert interp["status"] == "pending"
    assert interp["origin"] == "promoted"
    # No extraction job was started by the promotion.
    assert store.list_upload_jobs(USER, doc) == []


def test_t48_unresolvable_citation_files_nothing(route_client, store):
    convo, doc, ids = _seed_doc(store)
    msg = _assistant_message(
        store, convo,
        "Here is a reading: \"a passage that is nowhere in the document\".",
    )
    r = route_client.post(
        "/conversation/upload/promote",
        json={"conversation_id": convo, "message_id": msg},
    )
    assert r.status_code == 200, r.text
    assert r.json()["promoted"] is False
    assert "couldn't pin" in r.json()["detail"]
    assert len(store.pending_upload_interpretations(USER, doc, STRAND)) == 1


def test_t49_promoted_interpretation_appears_in_queue_and_can_be_ruled(
    route_client, store
):
    convo, doc, ids = _seed_doc(store)
    msg = _assistant_message(
        store, convo,
        f"A promoted reading: \"{SPAN_A}\". The day moved.",
    )
    r = route_client.post(
        "/conversation/upload/promote",
        json={"conversation_id": convo, "message_id": msg},
    )
    assert r.json()["promoted"] is True
    promoted_id = r.json()["interpretation"]["interpretation_id"]
    queue = UR.compose_upload_queue(
        store, USER, doc, STRAND,
        parked_ids=set(), reserved_ids=set(), round_started_at=None,
    )
    assert any(it["interpretation_id"] == promoted_id for it in queue)
    msg2 = _present(store, convo, promoted_id)
    r2 = _act(route_client, "keep", promoted_id, convo, msg2)
    assert r2.status_code == 200
    assert store.get_upload_interpretation(USER, promoted_id)["status"] == "ruled"


def test_t50_ungrounded_promotion_shows_no_excerpt_and_paste_resolves_past_excerpt(
    route_client, store
):
    # Ungrounded: no quotes at all — the reading files with no cited excerpt.
    convo, doc, ids = _seed_doc(store)
    msg = _assistant_message(
        store, convo, "A reading with no quotation in it at all."
    )
    r = route_client.post(
        "/conversation/upload/promote",
        json={"conversation_id": convo, "message_id": msg},
    )
    assert r.json()["promoted"] is True
    interp = store.get_upload_interpretation(
        USER, r.json()["interpretation"]["interpretation_id"]
    )
    assert interp["evidence_ids"] == []
    # Paste: a quote from past the 2000-char excerpt resolves against
    # the stored full text.
    long_text = ("filler sentence. " * 150) + SPAN_A + " and the day went on."
    convo2 = store.resolve_strand_thread(USER, "logic")["conversation_id"]
    src = store.add_strand_source(
        USER, "logic", convo2, kind="paste", ref="paste-2", label="Long notes",
        excerpt_redacted=long_text[:2000], paste_full_text=long_text,
    )
    doc2 = src["id"]
    assert len(long_text) > 2000 and long_text.index(SPAN_A) > 2000
    msg2 = _assistant_message(
        store, convo2, f"Late in the document: \"{SPAN_A}\"."
    )
    r2 = route_client.post(
        "/conversation/upload/promote",
        json={"conversation_id": convo2, "message_id": msg2},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["promoted"] is True
    interp2 = store.get_upload_interpretation(
        USER, r2.json()["interpretation"]["interpretation_id"]
    )
    assert len(interp2["evidence_ids"]) == 1
