"""Weave W1 producer — Firebrand proposal-to-task, deterministic tests.

Founder verdict 2026-11-05 ~20:34 PT: APPROVED FOR BOUNDED
IMPLEMENTATION AS A DRAFT PR, WITH REFINEMENTS. Covers, per the
verdict and the W1 design (2026-11-04):

- C-1 evidence-quote verification (verbatim prose span, <=500 chars,
  the block itself never counts; stored quote is the normalized form)
- C-2 grounding flag as lexical correspondence ("words_matched" /
  "summarized", never verified meaning; None on legacy rows)
- original_* snapshot in the SAME INSERT, never editable
- approve provenance (origin_seat / conversation / message set;
  origin_claim_id NULL; origin_decision_id NULL per Refinement 2 /
  Q4; responsible_seat NULL; seat_ref "" — Guard A)
- parent availability at edit AND approval (Q5), terminal parents
  block (Q1, Refinement 1: Done / Dropped / completed / Closed)
- atomic idempotent approval incl. the concurrent-approval race
- keystone guards (Guard A: no seat_ref write; Guard B: no keystone
  project creation)
- ownership (foreign / missing message, non-champion seat, client
  seat claims ignored — the seat is read from the message itself)

No real model generation anywhere: route tests use TestClient + tmp
SQLite + tmp ConversationStore, mirroring
tests/test_firebrand_task_context.py. The 400-before-409 precedence
is pinned: a missing/foreign parent at approval reads 400 (the
existing ownership convention, test_t16), a terminal parent reads
409 with guidance.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import vision_execution as ve_routes
from api.routes.auth_routes import get_current_user
from local_ai.conversation.store import ConversationStore
from local_ai.vision_execution import models as M
from local_ai.vision_execution import obligations as OB
from local_ai.vision_execution import storage as S

ALICE = {"id": "u1"}
BOB = {"id": "u2"}

# Default prose: the whole paragraph, so the default quote covers the
# default title ("Call the clinic") exactly -> words_matched.
DEFAULT_PROSE = "We should call the clinic today."
DEFAULT_TITLE = "Call the clinic"


@pytest.fixture()
def ve_conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    S.init_db(conn)
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture()
def conv_store(tmp_path: Path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ve_conn, conv_store):
    monkeypatch.setattr(ve_routes, "_conversation_store", lambda: conv_store)
    app = FastAPI()
    app.include_router(ve_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ALICE
    c = TestClient(app)
    yield c


@pytest.fixture()
def ve_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "race.db"
    monkeypatch.setattr(S, "_DB_PATH", db)
    yield db


def _body(prose, title=DEFAULT_TITLE, parent=None, timeframe="tentative", due=None, notes="Ask about referral"):
    block = json.dumps(
        {
            "proposals": [
                {
                    "title": title,
                    "parent_task_id": parent,
                    "timeframe_commitment": timeframe,
                    "due_date": due,
                    "notes": notes,
                }
            ]
        }
    )
    return f"{prose}\n```task-proposal\n{block}\n```"


def _message(conv_store, user="u1", convo="talk-1", body=None, seat="champion", role="voice"):
    conv_store.ensure_conversation(user, convo)
    return conv_store.append_message(user, convo, seat, role, body if body is not None else _body(DEFAULT_PROSE))


def _record_payload(msg, quote=DEFAULT_PROSE, **over):
    payload = {
        "conversation_id": "talk-1",
        "source_message_id": msg["id"],
        "block_index": 0,
        "proposal_index": 0,
        "title": DEFAULT_TITLE,
        "parent_task_id": None,
        "timeframe_commitment": "tentative",
        "due_date": None,
        "notes": "Ask about referral",
        "evidence_quote": quote,
    }
    payload.update(over)
    return payload


def _seed_proposal(conv_store, title=DEFAULT_TITLE, quote=DEFAULT_PROSE, parent=None):
    msg = _message(conv_store, body=_body(DEFAULT_PROSE, title=title, parent=parent))
    return S.record_task_proposal(
        "u1",
        {
            "conversation_id": "talk-1",
            "source_message_id": msg["id"],
            "block_index": 0,
            "proposal_index": 0,
            "title": title,
            "parent_task_id": parent,
            "timeframe_commitment": "tentative",
            "due_date": None,
            "notes": "Ask about referral",
            "evidence_quote": quote,
        },
        conversation_store=conv_store,
    )


# -- C-1: evidence-quote verification -----------------------------------------


def test_w1_quote_verbatim_records_with_normalized_quote(client, ve_conn, conv_store):
    msg = _message(conv_store, body=_body("Call   the\nclinic today."))
    r = client.post(
        "/vision-execution/task-proposals",
        json=_record_payload(msg, quote="Call   the\nclinic"),
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["evidence_quote"] == "Call the clinic"
    assert row["original_title"] == DEFAULT_TITLE
    assert row["grounding_flag"] == "words_matched"


def test_w1_quote_missing_empty_overlong_nonverbatim_rejected(client, ve_conn, conv_store):
    # Missing (no key at all) -> 400, no row.
    msg = _message(conv_store)
    payload = _record_payload(msg)
    del payload["evidence_quote"]
    r = client.post("/vision-execution/task-proposals", json=payload)
    assert r.status_code == 400
    # Empty after normalization -> 400.
    r = client.post("/vision-execution/task-proposals", json=_record_payload(msg, quote="   \n  "))
    assert r.status_code == 400
    # Non-verbatim (words nowhere in the prose) -> 400.
    r = client.post("/vision-execution/task-proposals", json=_record_payload(msg, quote="Email the dentist"))
    assert r.status_code == 400
    # A span of the BLOCK itself never counts as prose evidence.
    r = client.post(
        "/vision-execution/task-proposals",
        json=_record_payload(msg, quote='"title": "Call the clinic"'),
    )
    assert r.status_code == 400
    assert client.get("/vision-execution/task-proposals", params={"conversation_id": "talk-1"}).json()["proposals"] == []


def test_w1_quote_over_500_chars_rejected(client, ve_conn, conv_store):
    prose = ("Alpha " * 120).strip()  # 719 chars normalized
    msg = _message(conv_store, body=_body(prose))
    quote = prose[:501]  # a genuine substring, but over the cap
    assert len(quote) == 501
    r = client.post("/vision-execution/task-proposals", json=_record_payload(msg, quote=quote))
    assert r.status_code == 400
    assert client.get("/vision-execution/task-proposals", params={"conversation_id": "talk-1"}).json()["proposals"] == []


def test_w1_quote_block_with_no_preceding_prose_rejected(client, ve_conn, conv_store):
    msg = _message(conv_store, body=_body("").replace("\n```task-proposal", "```task-proposal"))
    # Body starts with the fence: there is no prose at all.
    assert msg["body"].startswith("```task-proposal")
    r = client.post("/vision-execution/task-proposals", json=_record_payload(msg, quote="Call the clinic"))
    assert r.status_code == 400
    assert client.get("/vision-execution/task-proposals", params={"conversation_id": "talk-1"}).json()["proposals"] == []


def test_w1_rerecord_with_different_quote_returns_stored_row_unchanged(client, ve_conn, conv_store):
    msg = _message(conv_store)
    first = client.post("/vision-execution/task-proposals", json=_record_payload(msg, quote=DEFAULT_PROSE))
    assert first.status_code == 200, first.text
    # A different (even invalid) quote on re-record: stored row wins,
    # no C-1 check, nothing overwritten.
    second = client.post(
        "/vision-execution/task-proposals",
        json=_record_payload(msg, quote="not in the prose at all"),
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["evidence_quote"] == DEFAULT_PROSE


# -- Ownership / seat ----------------------------------------------------------


def test_w1_non_champion_seat_rejected(client, ve_conn, conv_store):
    msg = _message(conv_store, seat="mentor")
    r = client.post("/vision-execution/task-proposals", json=_record_payload(msg))
    assert r.status_code == 400


def test_w1_client_seat_claim_ignored_seat_read_from_message(client, ve_conn, conv_store):
    msg = _message(conv_store)  # champion voice message
    payload = _record_payload(msg)
    payload["seat"] = "mentor"  # client claim; the server must ignore it
    r = client.post("/vision-execution/task-proposals", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["seat"] == "champion"


def test_w1_foreign_and_missing_message_read_404(client, ve_conn, conv_store):
    # Bob's message, recorded as Alice.
    bob_msg = _message(conv_store, user="u2")
    r = client.post("/vision-execution/task-proposals", json=_record_payload(bob_msg))
    assert r.status_code == 404
    # Fabricated message id.
    msg = _message(conv_store)
    r = client.post(
        "/vision-execution/task-proposals",
        json=_record_payload(msg, source_message_id="no-such-message"),
    )
    assert r.status_code == 404


# -- Provenance on approve ------------------------------------------------------


def test_w1_approve_writes_origins_and_nulls(client, ve_conn, conv_store):
    msg = _message(conv_store)
    rec = client.post("/vision-execution/task-proposals", json=_record_payload(msg)).json()
    r = client.post(f"/vision-execution/task-proposals/{rec['id']}/approve")
    assert r.status_code == 200, r.text
    task = r.json()["task"]
    assert task["origin_seat"] == "champion"
    assert task["origin_conversation_id"] == "talk-1"
    assert task["origin_message_id"] == msg["id"]
    assert task["origin_claim_id"] is None
    # Refinement 2 (Q4): no proposal-specific column exists, so the
    # proposal row's id is NOT stored in origin_decision_id — an
    # intentionally null field beats a misleading one.
    assert task["origin_decision_id"] is None
    assert task["responsible_seat"] is None
    # Guard A: the deliberation-path write to seat_ref is removed.
    assert task["seat_ref"] == ""
    # The proposal row itself is the anchor.
    prop = r.json()["proposal"]
    assert prop["created_task_id"] == task["id"]
    assert prop["original_title"] == DEFAULT_TITLE
    assert prop["evidence_quote"] == DEFAULT_PROSE


def test_w1_legacy_pending_proposal_approves_with_null_originals(client, ve_conn, conv_store):
    # A pre-W1 row: all W0B columns NULL (direct insert, no backfill).
    msg = _message(conv_store)
    conn = ve_conn
    now = S._now()
    conn.execute(
        "INSERT INTO task_proposals (id, user_id, conversation_id, source_message_id, "
        "block_index, proposal_index, seat, title, parent_task_id, timeframe_commitment, "
        "due_date, notes, state, created_task_id, created_at, updated_at, decided_at) "
        "VALUES (?, ?, ?, ?, 0, 0, 'champion', ?, NULL, 'tentative', NULL, '', 'pending', NULL, ?, ?, NULL)",
        ("legacy-1", "u1", "talk-1", msg["id"], DEFAULT_TITLE, now, now),
    )
    conn.commit()
    listed = client.get("/vision-execution/task-proposals", params={"conversation_id": "talk-1"}).json()["proposals"]
    assert len(listed) == 1
    assert listed[0]["evidence_quote"] is None
    assert listed[0]["original_title"] is None
    assert listed[0]["grounding_flag"] is None
    r = client.post("/vision-execution/task-proposals/legacy-1/approve")
    assert r.status_code == 200, r.text
    task = r.json()["task"]
    assert task["origin_seat"] == "champion"
    assert task["origin_message_id"] == msg["id"]
    assert task["seat_ref"] == ""
    prop = r.json()["proposal"]
    assert prop["original_title"] is None
    assert prop["evidence_quote"] is None


def test_w1_manual_task_has_null_origins(client, ve_conn, conv_store):
    task = S.create_task(M.TaskCreate(title="Manual"), "u1")
    assert task["origin_seat"] is None
    assert task["origin_conversation_id"] is None
    assert task["origin_message_id"] is None
    assert task["origin_decision_id"] is None
    assert task["responsible_seat"] is None


# -- Originals immutability ------------------------------------------------------


def test_w1_originals_snapshot_and_patch_immutability(client, ve_conn, conv_store):
    msg = _message(conv_store)
    rec = client.post("/vision-execution/task-proposals", json=_record_payload(msg)).json()
    assert rec["original_title"] == DEFAULT_TITLE
    assert rec["original_parent_task_id"] is None
    assert rec["original_timeframe_commitment"] == "tentative"
    assert rec["original_due_date"] is None
    assert rec["original_notes"] == "Ask about referral"
    # PATCH the live fields; the originals must be byte-identical.
    parent = S.create_task(M.TaskCreate(title="Parent"), "u1")
    edited = client.patch(
        f"/vision-execution/task-proposals/{rec['id']}",
        json={"title": "Edited title", "parent_task_id": parent["id"], "notes": "Edited notes"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Edited title"
    assert edited.json()["parent_task_id"] == parent["id"]
    assert edited.json()["original_title"] == DEFAULT_TITLE
    assert edited.json()["original_parent_task_id"] is None
    assert edited.json()["original_notes"] == "Ask about referral"
    # PATCH keys naming original_* are ignored (never a write path).
    forged = S.update_task_proposal(
        "u1", rec["id"], {"title": "Edited again", "original_title": "Forged"}
    )
    assert forged["title"] == "Edited again"
    assert forged["original_title"] == DEFAULT_TITLE


# -- Grounding flag --------------------------------------------------------------


def test_w1_grounding_flag_words_matched_summarized_negation(client, ve_conn, conv_store):
    # Fully covered -> words_matched (default body/quote).
    msg = _message(conv_store)
    rec = client.post("/vision-execution/task-proposals", json=_record_payload(msg)).json()
    assert rec["grounding_flag"] == "words_matched"
    # Novel title word -> summarized.
    msg2 = _message(conv_store, body=_body("Prose here.", title="Email the clinic"))
    rec2 = client.post(
        "/vision-execution/task-proposals",
        json=_record_payload(msg2, quote="Prose here.", title="Email the clinic"),
    ).json()
    assert rec2["grounding_flag"] == "summarized"
    # Negation is invisible to the lexical check (documented limit):
    # "don't call the clinic" as quote, "Call the clinic" as title.
    msg3 = _message(conv_store, body=_body("Don't call the clinic"))
    rec3 = client.post(
        "/vision-execution/task-proposals",
        json=_record_payload(msg3, quote="Don't call the clinic"),
    ).json()
    assert rec3["grounding_flag"] == "words_matched"


def test_w1_grounding_flag_recomputes_on_edited_title(client, ve_conn, conv_store):
    msg = _message(conv_store)
    rec = client.post("/vision-execution/task-proposals", json=_record_payload(msg)).json()
    assert rec["grounding_flag"] == "words_matched"
    client.patch(f"/vision-execution/task-proposals/{rec['id']}", json={"title": "Email the clinic"})
    listed = client.get("/vision-execution/task-proposals", params={"conversation_id": "talk-1"}).json()["proposals"]
    assert listed[0]["title"] == "Email the clinic"
    assert listed[0]["grounding_flag"] == "summarized"
    # And back to a covered title recomputes the other way.
    client.patch(f"/vision-execution/task-proposals/{rec['id']}", json={"title": "Call the clinic"})
    listed = client.get("/vision-execution/task-proposals", params={"conversation_id": "talk-1"}).json()["proposals"]
    assert listed[0]["grounding_flag"] == "words_matched"


# -- Terminal-status helper (Refinement 1) ---------------------------------------


def test_w1_terminal_parent_status_helper():
    for status in ("Done", "done", "Dropped", "dropped", "completed", "Completed", "Closed", "closed", "COMPLETED", "shipped", "won", "complete"):
        assert S._is_terminal_parent_status(status) is True, status
    for status in ("Todo", "In Progress", "Blocked", "In progress", "todo", None, "", "   "):
        assert S._is_terminal_parent_status(status) is False, status


# -- Parent availability at edit AND approval (Q1/Q5) ------------------------------


@pytest.mark.parametrize("status", ["Done", "Dropped", "completed", "Closed"])
def test_w1_approve_terminal_parent_409_proposal_stays_pending(client, ve_conn, conv_store, status):
    parent = S.create_task(M.TaskCreate(title="Parent"), "u1")
    # Direct SQL: "completed"/"Closed" are not in the TaskUpdate
    # Literal, but they are real stored statuses the helper must catch.
    ve_conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, parent["id"]))
    ve_conn.commit()
    rec = _seed_proposal(conv_store, parent=parent["id"])
    r = client.post(f"/vision-execution/task-proposals/{rec['id']}/approve")
    assert r.status_code == 409, r.text
    assert "Parent task is no longer available" in r.json()["detail"]
    assert "choose a different parent" in r.json()["detail"]
    listed = client.get("/vision-execution/task-proposals", params={"conversation_id": "talk-1"}).json()["proposals"]
    assert listed[0]["state"] == "pending"
    assert listed[0]["created_task_id"] is None
    assert [t["id"] for t in client.get("/vision-execution/tasks").json()] == [parent["id"]]


@pytest.mark.parametrize("status", ["Todo", "In Progress", "Blocked"])
def test_w1_approve_active_parent_ok(client, ve_conn, conv_store, status):
    parent = S.create_task(M.TaskCreate(title="Parent", status=status), "u1")
    rec = _seed_proposal(conv_store, parent=parent["id"])
    r = client.post(f"/vision-execution/task-proposals/{rec['id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["task"]["parent_task_id"] == parent["id"]


def test_w1_approve_null_parent_ok(client, ve_conn, conv_store):
    rec = _seed_proposal(conv_store, parent=None)
    r = client.post(f"/vision-execution/task-proposals/{rec['id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["task"]["parent_task_id"] is None


def test_w1_approve_missing_or_foreign_parent_stays_400(client, ve_conn, conv_store):
    # Deleted parent between recording and approval: 400 (the existing
    # ownership convention — test_t16 pins this; 409 is for terminal
    # parents only, per the 400-before-409 precedence).
    parent = S.create_task(M.TaskCreate(title="Parent"), "u1")
    rec = _seed_proposal(conv_store, parent=parent["id"])
    S.delete_task(parent["id"], "u1")
    r = client.post(f"/vision-execution/task-proposals/{rec['id']}/approve")
    assert r.status_code == 400
    listed = client.get("/vision-execution/task-proposals", params={"conversation_id": "talk-1"}).json()["proposals"]
    assert listed[0]["state"] == "pending"
    # Foreign parent: same 400 (rejected at record time).
    other = S.create_task(M.TaskCreate(title="Bob parent"), "u2")
    msg = _message(conv_store, body=_body(DEFAULT_PROSE, title="Third", parent=other["id"]))
    r = client.post(
        "/vision-execution/task-proposals",
        json=_record_payload(msg, title="Third", parent_task_id=other["id"]),
    )
    assert r.status_code == 400


def test_w1_patch_to_terminal_parent_400_null_parent_passes(client, ve_conn, conv_store):
    parent = S.create_task(M.TaskCreate(title="Parent"), "u1")
    rec = _seed_proposal(conv_store)
    # Active parent: fine.
    r = client.patch(f"/vision-execution/task-proposals/{rec['id']}", json={"parent_task_id": parent["id"]})
    assert r.status_code == 200, r.text
    # Terminal parent: 400.
    S.update_task(parent["id"], M.TaskUpdate(status="Done"), "u1")
    r = client.patch(f"/vision-execution/task-proposals/{rec['id']}", json={"parent_task_id": parent["id"]})
    assert r.status_code == 400
    assert r.json()["detail"] == "Parent task is unavailable"
    # Null parent always passes (dropping the parent).
    r = client.patch(f"/vision-execution/task-proposals/{rec['id']}", json={"parent_task_id": None})
    assert r.status_code == 200, r.text
    assert r.json()["parent_task_id"] is None


# -- Atomic idempotent approval ----------------------------------------------------


def test_w1_sequential_reapprove_returns_winners_task_one_task(client, ve_conn, conv_store):
    rec = _seed_proposal(conv_store)
    first = client.post(f"/vision-execution/task-proposals/{rec['id']}/approve")
    assert first.status_code == 200, first.text
    second = client.post(f"/vision-execution/task-proposals/{rec['id']}/approve")
    assert second.status_code == 200, second.text
    assert second.json()["task"]["id"] == first.json()["task"]["id"]
    assert len(client.get("/vision-execution/tasks").json()) == 1


def test_w1_concurrent_approvals_exactly_one_task(ve_file, conv_store):
    rec = _seed_proposal(conv_store)
    barrier = threading.Barrier(2)
    results: dict = {}

    def approve(slot):
        barrier.wait()
        try:
            results[slot] = S.approve_task_proposal("u1", rec["id"])
        except Exception as e:  # noqa: BLE001 — collected, asserted below
            results[slot] = e

    threads = [threading.Thread(target=approve, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(not isinstance(v, Exception) for v in results.values()), results
    assert results[0]["task"]["id"] == results[1]["task"]["id"]
    assert len(S.list_tasks("u1")) == 1


# -- Keystone guards -----------------------------------------------------------------


def test_w1_guard_a_seat_ref_empty_task_excluded_from_keystone_chain(ve_conn, conv_store):
    from local_ai.conversation import meeting as meeting_mod
    from local_ai.vision_execution import keystone_seeding

    keystone_seeding.seed_meet_your_council("u1")
    initiative = keystone_seeding.find_keystone_initiative("u1")
    assert initiative is not None
    projects = [p for p in S.list_projects("u1") if p.get("initiative_id") == initiative["id"]]
    assert len(projects) == 7
    # The seeded champion tasks are still there (4 in the chain).
    mine = meeting_mod._seat_keystone_tasks("u1", "champion")
    assert len(mine) == 4
    assert all(t["seat_ref"] == "champion" for t in mine)
    # A W1-style task (seat_ref "") in a keystone project is NOT a
    # keystone task — it is excluded from the chain.
    stray = S.create_task(
        M.TaskCreate(title="W1 stray", project_id=projects[0]["id"], seat_ref=""),
        "u1",
    )
    mine_after = meeting_mod._seat_keystone_tasks("u1", "champion")
    assert len(mine_after) == 4
    assert stray["id"] not in {t["id"] for t in mine_after}


def test_w1_guard_b_rejects_keystone_project(ve_conn, conv_store):
    from local_ai.vision_execution import keystone_seeding

    # No keystone initiative: any project passes.
    project = S.create_project(M.ProjectCreate(title="Plain"), "u1")
    S._reject_keystone_project(project["id"], "u1")
    S._reject_keystone_project(None, "u1")
    # With a seeded keystone initiative: its projects reject, others pass.
    keystone_seeding.seed_meet_your_council("u1")
    initiative = keystone_seeding.find_keystone_initiative("u1")
    keystone_project = next(
        p for p in S.list_projects("u1") if p.get("initiative_id") == initiative["id"]
    )
    with pytest.raises(ValueError, match="keystone project"):
        S._reject_keystone_project(keystone_project["id"], "u1")
    S._reject_keystone_project(project["id"], "u1")


def test_w1_pre_w1_seat_ref_rows_not_rewritten(ve_conn, conv_store):
    # A Capability-B-era task (seat_ref "champion", no origins) is
    # left exactly as it is by W1 operations — no migration, no rewrite.
    legacy = S.create_task(M.TaskCreate(title="B-era", seat_ref="champion"), "u1")
    rec = _seed_proposal(conv_store)
    S.approve_task_proposal("u1", rec["id"])
    again = S.get_task(legacy["id"], "u1")
    assert again is not None
    assert again["seat_ref"] == "champion"
    assert again["origin_seat"] is None


# -- Instruction sentence --------------------------------------------------------------


def test_w1_firebrand_instruction_carries_evidence_sentence():
    assert (
        "Describe the proposal in prose first: the card the user approves "
        "shows those exact words as the evidence for the task."
        in OB.PROPOSAL_INSTRUCTION
    )
