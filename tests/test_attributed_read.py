"""The shared attributed subject read (Palace capability directions,
founder ruling 2026-11-25 09:51 PT).

One read, three questions for a caller-owned subject, every item
attributed to the home it came from:

* boundary material labelled by STATE — expressed (core-profile
  non-negotiables, strand topic boundaries; both exist WITHOUT being
  placed at the subject), proposed (steward/seat interpretations
  under the mirrored pencil gates, pencil register), established
  (VE decisions + follow-through commitments naming the subject),
  enforceable (permission home + consent flags — enforcement is not
  expression);
* the Kintsugi record — live readings' tensions and open questions,
  derived currency, standing reconsiderations, and the seam marker:
  an interpretation RECONSIDERED with its correction ACCEPTED
  (accepted supersession). The seam marks restored UNDERSTANDING,
  never repaired circumstances; a current tension is an open
  question held and produces NO fracture/damage state anywhere;
* attending seats — by seat-authored reading (attribution is the
  reading's ``author``, never lens affinity) and by conversation
  (context_preparation's scan, ungated: the visitor's own records).

The read writes nothing. Owner-scoped throughout; every failure
mode reads as empty. Conventions: ALICE = "u1", BOB = "u2".
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from local_ai.conversation import attributed_read as AR
from local_ai.conversation.store import ConversationStore
from local_ai.followthrough.store import FollowthroughStore
from local_ai.narrative import NarrativeStore
from local_ai.narrative.refs import SourceRef
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve_service
from local_ai.vision_execution import storage as S

ALICE = "u1"
BOB = "u2"

FLAGS_ON = {"steward_derivation": True, "steward_coordination": True}
FLAGS_OFF = {"steward_derivation": False, "steward_coordination": False}


# ---------------------------------------------------------------------------
# fixtures + seed helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_conn(monkeypatch: pytest.MonkeyPatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    S.init_db(conn)
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture()
def narrative_store(tmp_path: Path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


@pytest.fixture()
def conv_store(tmp_path: Path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


@pytest.fixture()
def ft_store(tmp_path: Path):
    return FollowthroughStore(db_path=tmp_path / "ft.db")


@pytest.fixture()
def pencil_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZENAF_STEWARD_PENCIL", "1")


def _perm_conn(flags_by_user: dict) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-11-24T00:00:00Z"),
        )
    conn.commit()
    return conn


def _make_task(user: str, title: str, **kw) -> dict:
    return ve_service.create_task(M.TaskCreate(title=title, **kw), user)


def _read(store, conv, ft, user, entity_type, entity_id, conn=None):
    return AR.attributed_read_for_subject(
        user,
        entity_type,
        entity_id,
        narrative_store=store,
        conversation_store=conv,
        followthrough_store=ft,
        consent_connection=conn if conn is not None else _perm_conn({user: FLAGS_ON}),
    )


def _thread_naming_task(
    narrative_store,
    user,
    task_id,
    *,
    author="skeptic",
    status="active",
    reading_body=None,
    accept=False,
):
    """A standing thread whose evidence names the task, carrying one
    reading by ``author`` with the given tensions/questions."""
    thread = narrative_store.create_thread(
        user, origin="user_declared", title="The boundary thread",
        evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),),
    )
    narrative_store.annotate_evidence_entities(
        user, thread.id, {("event", "evt-1"): f"task:{task_id}"}
    )
    if status != "nascent":
        narrative_store.set_thread_status(user, thread.id, status)
    reading = narrative_store.propose_reading(
        user, thread.id, author=author,
        reading=reading_body
        or {"tensions": ["Sundays keep colliding with deliveries"],
            "open_questions": ["Where does the weekend actually sit?"]},
        evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),),
    )
    if accept:
        narrative_store.accept_reading(user, reading.id)
    return narrative_store.get_thread(user, thread.id), reading


def _insert_message(store, user, conv, arch, context, created_at="2026-11-20T00:00:00Z"):
    with store._lock:
        store._conn.execute(
            "INSERT INTO messages (id, user_id, conversation_id, archetype_id, "
            "role, body, mode, context_json, created_at) "
            "VALUES (?, ?, ?, ?, 'assistant', 'words', 'trained', ?, ?)",
            (uuid.uuid4().hex[:16], user, conv, arch, json.dumps(context or {}), created_at),
        )
        store._conn.commit()


def _subject_ctx(entity_type: str, entity_id: str) -> dict:
    return {"sheet_type": "living_palace", "entity_type": entity_type, "entity_id": entity_id}


# ---------------------------------------------------------------------------
# resolution + owner isolation
# ---------------------------------------------------------------------------


def test_foreign_subject_reads_as_unresolved(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    result = _read(narrative_store, conv_store, ft_store, BOB, "task", task["id"])
    assert result["resolved"] is False
    assert result["subject"] is None
    assert result["boundaries"]["proposed"] == []
    assert result["kintsugi"] is None
    assert result["guests"]["attending"] == []


def test_unknown_subject_and_type_read_as_unresolved(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", "nope")
    assert result["resolved"] is False
    result = _read(narrative_store, conv_store, ft_store, ALICE, "nonsense", "nope")
    assert result["resolved"] is False


def test_foreign_thread_and_conversation_never_leak(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    # BOB's thread names ALICE's task id; BOB's conversation attends it.
    _thread_naming_task(narrative_store, BOB, task["id"], author="ambassador")
    _insert_message(conv_store, BOB, "c-bob", "ambassador", _subject_ctx("task", task["id"]))
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    assert result["resolved"] is True
    assert result["boundaries"]["proposed"] == []
    assert result["guests"]["attending"] == []
    kintsugi = result["kintsugi"]
    assert kintsugi is not None
    assert all(t["readings"] == [] for t in kintsugi["threads"]) or kintsugi["threads"] == []


# ---------------------------------------------------------------------------
# the steward gates — fail-closed for the gated parts only
# ---------------------------------------------------------------------------


def test_gate_off_by_default_hides_steward_material_only(
    ve_conn, narrative_store, conv_store, ft_store
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="ambassador")
    _insert_message(conv_store, ALICE, "c-1", "ambassador", _subject_ctx("task", task["id"]))
    # No ZENAF_STEWARD_PENCIL: steward material is dark, but the
    # visitor's own conversation attendance still reads.
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    assert result["steward_gate_open"] is False
    assert result["boundaries"]["proposed"] == []
    assert result["kintsugi"] is None
    attending = {g["seat"]: g["via"] for g in result["guests"]["attending"]}
    assert attending == {"ambassador": ["conversation"]}


def test_consent_closed_hides_steward_material(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"])
    result = _read(
        narrative_store, conv_store, ft_store, ALICE, "task", task["id"],
        conn=_perm_conn({ALICE: FLAGS_OFF}),
    )
    assert result["steward_gate_open"] is False
    assert result["boundaries"]["proposed"] == []
    assert result["kintsugi"] is None


def test_one_consent_flag_closed_hides_steward_material(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"])
    half = {"steward_derivation": True, "steward_coordination": False}
    result = _read(
        narrative_store, conv_store, ft_store, ALICE, "task", task["id"],
        conn=_perm_conn({ALICE: half}),
    )
    assert result["steward_gate_open"] is False
    assert result["kintsugi"] is None


def test_nascent_thread_contributes_nothing(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], status="nascent")
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    assert result["boundaries"]["proposed"] == []
    assert result["kintsugi"]["threads"] == []
    assert result["guests"]["attending"] == []


# ---------------------------------------------------------------------------
# boundary states — expressed / established / enforceable
# ---------------------------------------------------------------------------


def test_expressed_items_exist_but_are_not_placed(
    ve_conn, narrative_store, conv_store, ft_store
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    ve_service.create_core_profile(
        M.CoreProfileCreate(name="Core", non_negotiables="No work on Sundays."),
        ALICE,
    )
    conv_store.add_topic_boundary(ALICE, "hands", "pricing")
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    expressed = result["boundaries"]["expressed"]
    profile_items = [i for i in expressed if i["source"] == "core_profile"]
    assert len(profile_items) == 1
    assert profile_items[0]["text"] == "No work on Sundays."
    assert "not placed" in profile_items[0]["placement"]
    strand_items = [i for i in expressed if i["source"] == "strand_topic"]
    assert len(strand_items) == 1
    assert strand_items[0]["topic"] == "pricing"
    assert strand_items[0]["strand_key"] == "hands"


def test_established_items_are_decisions_and_linked_commitments(
    ve_conn, narrative_store, conv_store, ft_store
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    other = _make_task(ALICE, "Book the yard", status="Todo")
    ve_service.create_decision(
        M.DecisionCreate(
            user_id=ALICE, entity_type="task", entity_id=task["id"],
            decision_type="priority_change",
        )
    )
    ve_service.create_decision(
        M.DecisionCreate(
            user_id=ALICE, entity_type="task", entity_id=other["id"],
            decision_type="priority_change",
        )
    )
    linked = ft_store.create_commitment(ALICE, "No Sunday deliveries, ever.")
    ft_store.link_commitment(linked["id"], ALICE, task["id"])
    ft_store.create_commitment(ALICE, "An unlinked promise.")
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    established = result["boundaries"]["established"]
    decisions = [i for i in established if i["source"] == "decision"]
    assert len(decisions) == 1
    assert decisions[0]["decision_type"] == "priority_change"
    commitments = [i for i in established if i["source"] == "commitment"]
    assert len(commitments) == 1
    assert commitments[0]["text"] == "No Sunday deliveries, ever."


def test_enforceable_state_reports_consent_flags(
    ve_conn, narrative_store, conv_store, ft_store
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    enforceable = result["boundaries"]["enforceable"]
    assert enforceable["steward_derivation"] is True
    assert enforceable["steward_coordination"] is True
    result_off = _read(
        narrative_store, conv_store, ft_store, ALICE, "task", task["id"],
        conn=_perm_conn({ALICE: FLAGS_OFF}),
    )
    enforceable_off = result_off["boundaries"]["enforceable"]
    assert enforceable_off["steward_derivation"] is False
    assert enforceable_off["steward_coordination"] is False


# ---------------------------------------------------------------------------
# proposed interpretations + the Kintsugi record
# ---------------------------------------------------------------------------


def test_proposed_interpretations_carry_tensions_and_questions(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="skeptic")
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    proposed = result["boundaries"]["proposed"]
    assert len(proposed) == 1
    item = proposed[0]
    assert item["author"] == "skeptic"
    assert item["status"] == "proposed"
    assert item["tensions"] == ["Sundays keep colliding with deliveries"]
    assert item["open_questions"] == ["Where does the weekend actually sit?"]
    kintsugi = result["kintsugi"]
    assert kintsugi["restoration_of_understanding"] is False
    readings = kintsugi["threads"][0]["readings"]
    assert len(readings) == 1
    assert readings[0]["placement"] == "current"


def test_current_tension_produces_no_damage_state(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    """An enduring tension is an open question held — never a
    fracture. No field anywhere in the read may carry damage
    language for it."""
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"])
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    blob = json.dumps(result).lower()
    for word in ("fracture", "fractured", "damage", "damaged", "crack", "cracked", "broken"):
        assert word not in blob, word
    assert result["kintsugi"]["restoration_of_understanding"] is False


def _reconsideration_lineage(narrative_store, user, task_id, *, accept_correction: bool, kind="contradicted"):
    """Reading A is reconsidered through a ``kind`` change toward
    successor B; B is accepted only when asked."""
    thread, first = _thread_naming_task(
        narrative_store, user, task_id, author="skeptic",
        reading_body={"tensions": ["The yard is the bottleneck"]},
    )
    successor = narrative_store.propose_reading(
        user, thread.id, author="skeptic",
        reading={"tensions": ["The yard is fine; the calendar is the bottleneck"]},
        evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),),
    )
    narrative_store.record_change(
        user, thread.id, kind=kind,
        evidence_refs=(SourceRef(kind="event", ref_id="evt-2", evidence_kind="entity_ref"),),
        prior_reading_id=first.id, new_reading_id=successor.id,
    )
    if accept_correction:
        narrative_store.accept_reading(user, successor.id)
    return thread, first, successor


def test_accepted_supersession_earns_the_seam(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _reconsideration_lineage(narrative_store, ALICE, task["id"], accept_correction=True)
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    assert result["kintsugi"]["restoration_of_understanding"] is True


def test_unaccepted_correction_earns_no_seam(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _reconsideration_lineage(narrative_store, ALICE, task["id"], accept_correction=False)
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    assert result["kintsugi"]["restoration_of_understanding"] is False


def test_plain_extension_earns_no_seam_even_when_accepted(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _reconsideration_lineage(
        narrative_store, ALICE, task["id"], accept_correction=True, kind="extended"
    )
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    assert result["kintsugi"]["restoration_of_understanding"] is False


def test_standing_reconsideration_is_carried(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _, reading = _thread_naming_task(
        narrative_store, ALICE, task["id"], author="guardian", accept=True
    )
    narrative_store.propose_reading_reconsideration(
        ALICE, reading.id, "The delivery facts changed."
    )
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    recs = result["kintsugi"]["threads"][0]["reconsiderations"]
    assert len(recs) == 1
    assert recs[0]["reading_id"] == reading.id
    assert recs[0]["status"] == "proposed"
    assert recs[0]["reason"] == "The delivery facts changed."


# ---------------------------------------------------------------------------
# attending seats
# ---------------------------------------------------------------------------


def test_guests_by_reading_attribute_the_author_never_the_steward(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="ambassador")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="steward")
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    attending = {g["seat"]: g["via"] for g in result["guests"]["attending"]}
    # The Steward is not a seat and never attends as one; Severine's
    # Bench §7 exclusion is Bench law — here the skeptic attends
    # like any seat whose reading names the subject.
    assert attending == {"ambassador": ["reading"]}
    _thread_naming_task(narrative_store, ALICE, task["id"], author="skeptic")
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    attending = {g["seat"]: g["via"] for g in result["guests"]["attending"]}
    assert attending["skeptic"] == ["reading"]


def test_guests_by_conversation_and_both_doors_merge(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    other = _make_task(ALICE, "Book the yard", status="Todo")
    _insert_message(conv_store, ALICE, "c-1", "champion", _subject_ctx("task", task["id"]))
    _insert_message(conv_store, ALICE, "c-2", "maverick", _subject_ctx("task", other["id"]))
    _thread_naming_task(narrative_store, ALICE, task["id"], author="champion")
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    attending = {g["seat"]: g["via"] for g in result["guests"]["attending"]}
    assert attending == {"champion": ["conversation", "reading"]}


# ---------------------------------------------------------------------------
# read-only — the read writes nothing
# ---------------------------------------------------------------------------


def test_read_writes_nothing(ve_conn, narrative_store, conv_store, ft_store, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _reconsideration_lineage(narrative_store, ALICE, task["id"], accept_correction=True)
    conn = narrative_store._conn

    def counts() -> dict[str, int]:
        out = {}
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall():
            out[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        return out

    before = counts()
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    assert result["kintsugi"]["restoration_of_understanding"] is True
    after = counts()
    assert before == after
    assert after.get("relevance_assessments", 0) == before.get(
        "relevance_assessments", 0
    )


def test_broken_narrative_store_degrades_to_empty_steward_material(
    ve_conn, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")

    class ExplodingStore:
        def threads_for(self, *a, **kw):
            raise RuntimeError("store is down")

    result = AR.attributed_read_for_subject(
        ALICE, "task", task["id"],
        narrative_store=ExplodingStore(),
        conversation_store=conv_store,
        followthrough_store=ft_store,
        consent_connection=_perm_conn({ALICE: FLAGS_ON}),
    )
    assert result["resolved"] is True
    assert result["boundaries"]["proposed"] == []
    assert result["kintsugi"]["threads"] == []


# ---------------------------------------------------------------------------
# the route — thin, authenticated, fail-closed
# ---------------------------------------------------------------------------


def _route_client(user_id: str):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes import vision_execution as ve_routes
    from api.routes.auth_routes import get_current_user

    app = FastAPI()
    app.include_router(ve_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}
    return TestClient(app)


def test_route_serves_the_read_shape(ve_conn):
    task = _make_task(ALICE, "Order timber", status="Todo")
    client = _route_client(ALICE)
    res = client.get(f"/vision-execution/attributed-read/task/{task['id']}")
    assert res.status_code == 200
    body = res.json()
    assert body["resolved"] is True
    assert body["subject"]["title"] == "Order timber"
    assert body["kintsugi"] is None  # gate closed by default
    assert body["guests"] == {"attending": []}


def test_route_unknown_type_reads_as_unresolved(ve_conn):
    client = _route_client(ALICE)
    res = client.get("/vision-execution/attributed-read/nonsense/abc")
    assert res.status_code == 200
    assert res.json()["resolved"] is False


def test_route_requires_authentication(ve_conn):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes import vision_execution as ve_routes

    app = FastAPI()
    app.include_router(ve_routes.router)
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/vision-execution/attributed-read/task/abc")
    assert res.status_code == 401
