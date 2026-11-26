"""Board declarations (Board interaction pass, 2026-11-25) — tests.

Rivers and Holds leave the Campaign Board's provisional session
state and become recorded, conversational acts:

  (a) declaration state is DERIVED from the caller's own decision
      records (latest river event wins; withdrawal supersedes;
      holds keyed by their placing decision, moved/removed by id);
  (b) the derivation is owner-scoped in both directions — another
      owner's decisions never fold into the caller's state;
  (c) the [[declare]] tail parses fail-closed: a malformed act
      writes nothing, a grammar failure drops the whole tail, and
      the tail is stripped from the visible reply on every path;
  (d) at the service seam, acts are honored only on a champion turn
      whose live context is the Campaign Board with a staged
      project, and only against that project;
  (e) carriage: on the board sheet the staged project's declaration
      state rides in the subject block; on any other sheet it does
      not.

No real model generation anywhere: service turns use a capturing
fake generate_fn. Conventions: ALICE = "u1" (owner), BOB = "u2".
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from local_ai.conversation import subject_context as SC
from local_ai.conversation.declaration_tail import parse_declaration_tail
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.vision_execution import declarations as D
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve_service
from local_ai.vision_execution import storage as S

ALICE = "u1"
BOB = "u2"


@pytest.fixture()
def ve_conn(monkeypatch: pytest.MonkeyPatch):
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


def _make_project(user: str, title: str, **kw) -> dict:
    return ve_service.create_project(M.ProjectCreate(title=title, **kw), user)


def _make_task(user: str, title: str, **kw) -> dict:
    return ve_service.create_task(M.TaskCreate(title=title, **kw), user)


def _decide(user: str, project_id: str, dtype: str, payload: dict) -> dict:
    return D.record_declaration(user, project_id, dtype, payload)


# ---------------------------------------------------------------------------
# (a)+(b) derivation from decision records
# ---------------------------------------------------------------------------


def test_fold_latest_river_wins_and_withdrawal_supersedes(ve_conn):
    p = _make_project(ALICE, "River project")
    _decide(ALICE, p["id"], D.RIVER_DECLARATION, {"start": "2026-12-06", "end": "2026-12-09"})
    state = D.derive_project_declarations(ALICE, p["id"])
    assert state["river"]["start"] == "2026-12-06"
    assert state["river"]["end"] == "2026-12-09"

    _decide(ALICE, p["id"], D.RIVER_DECLARATION, {"start": "2027-01-03", "end": "2027-01-05"})
    state = D.derive_project_declarations(ALICE, p["id"])
    assert state["river"]["start"] == "2027-01-03"

    _decide(ALICE, p["id"], D.RIVER_WITHDRAWAL, {})
    state = D.derive_project_declarations(ALICE, p["id"])
    assert state["river"] is None

    # A declaration after the withdrawal stands again.
    _decide(ALICE, p["id"], D.RIVER_DECLARATION, {"start": "2027-02-01", "end": "2027-02-02"})
    state = D.derive_project_declarations(ALICE, p["id"])
    assert state["river"]["start"] == "2027-02-01"


def test_fold_holds_placed_moved_removed(ve_conn):
    p = _make_project(ALICE, "Hold project")
    placed = _decide(ALICE, p["id"], D.HOLD_PLACED, {"at": "2026-12-07"})
    other = _decide(ALICE, p["id"], D.HOLD_PLACED, {"at": "2026-12-12"})
    state = D.derive_project_declarations(ALICE, p["id"])
    assert [h["id"] for h in state["holds"]] == [placed["id"], other["id"]]

    _decide(ALICE, p["id"], D.HOLD_MOVED, {"hold_id": placed["id"], "at": "2026-12-20"})
    state = D.derive_project_declarations(ALICE, p["id"])
    moved = [h for h in state["holds"] if h["id"] == placed["id"]]
    assert moved[0]["at"] == "2026-12-20"

    _decide(ALICE, p["id"], D.HOLD_REMOVED, {"hold_id": placed["id"]})
    state = D.derive_project_declarations(ALICE, p["id"])
    assert [h["id"] for h in state["holds"]] == [other["id"]]

    # Moving a hold that does not stand is a no-op in the fold.
    _decide(ALICE, p["id"], D.HOLD_MOVED, {"hold_id": placed["id"], "at": "2026-12-25"})
    state = D.derive_project_declarations(ALICE, p["id"])
    assert [h["id"] for h in state["holds"]] == [other["id"]]


def test_fold_ignores_other_types_and_is_owner_scoped(ve_conn):
    p = _make_project(ALICE, "Scoped project")
    _decide(BOB, p["id"], D.RIVER_DECLARATION, {"start": "2026-12-06", "end": "2026-12-09"})
    _decide(ALICE, p["id"], "scales_weighing", {"start": "2026-01-01", "end": "2026-01-02"})
    state = D.derive_project_declarations(ALICE, p["id"])
    assert state == {"river": None, "holds": []}
    # Bob's own read of his own decision still folds for Bob.
    bob_state = D.derive_project_declarations(BOB, p["id"])
    assert bob_state["river"]["start"] == "2026-12-06"


# ---------------------------------------------------------------------------
# (c) the tail parser — fail-closed, strip-always
# ---------------------------------------------------------------------------


def test_parser_happy_path_and_strip():
    text = (
        "The window is settled, then.\n\n[[declare]]\n"
        "declare-window | project=p1 | start=2026-12-06 | end=2026-12-09\n"
        "place-hold | project=p1 | at=2026-12-07"
    )
    r = parse_declaration_tail(text)
    assert r.status == "ok"
    assert r.body == "The window is settled, then."
    assert [a["verb"] for a in r.acts] == ["declare-window", "place-hold"]


def test_parser_no_marker_is_byte_identical():
    text = "An ordinary reply mentioning [[declare]] in prose stays speech."
    r = parse_declaration_tail(text)
    assert r.status == "absent"
    assert r.body == text
    assert r.acts == []


def test_parser_malformed_act_drops_only_that_act():
    text = (
        "Words.\n\n[[declare]]\n"
        "declare-window | project=p1 | start=soon | end=2026-12-09\n"
        "remove-hold | hold=h9"
    )
    r = parse_declaration_tail(text)
    assert r.status == "ok"
    assert [a["verb"] for a in r.acts] == ["remove-hold"]
    assert "[[declare]]" not in r.body


def test_parser_prose_in_tail_drops_whole_tail():
    text = "Words.\n\n[[declare]]\ndeclare-window | project=p1 | start=2026-12-06 | end=2026-12-09\nand then some prose"
    r = parse_declaration_tail(text)
    assert r.status == "grammar_failure"
    assert r.acts == []
    assert r.body == "Words."


def test_parser_end_before_start_is_an_act_failure():
    text = "Words.\n\n[[declare]]\ndeclare-window | project=p1 | start=2026-12-09 | end=2026-12-06"
    r = parse_declaration_tail(text)
    assert r.acts == []
    assert r.body == "Words."


# ---------------------------------------------------------------------------
# (d) the service seam — honored only for the staged project, in board turns
# ---------------------------------------------------------------------------


def _board_turn(conv_store, user: str, context, reply: str, message: str = "Set the river for December 6 to 9."):
    seen: dict[str, str] = {}

    def _capture(prompt, **kw):
        seen["prompt"] = prompt
        return reply

    svc = ConversationService(conv_store, generate_fn=_capture)
    result = svc.turn(
        user, "champion", message,
        conversation_id=f"c-board-{id(context)}-{abs(hash(reply)) % 99999}",
        context=context,
    )
    return result, seen.get("prompt", "")


def test_seam_records_declaration_for_staged_project(ve_conn, conv_store):
    p = _make_project(ALICE, "Staged project")
    reply = (
        "Done — the river stands December 6 to 9.\n\n[[declare]]\n"
        f"declare-window | project={p['id']} | start=2026-12-06 | end=2026-12-09"
    )
    result, prompt = _board_turn(
        conv_store, ALICE,
        {"sheet_type": "campaign_board", "entity_type": "project", "entity_id": p["id"]},
        reply,
    )
    # The instruction block reached Valen on the board turn.
    assert "[[declare]]" in prompt
    # The tail is stripped from the visible reply.
    assert "[[declare]]" not in result.reply.reply
    assert "the river stands" in result.reply.reply
    state = D.derive_project_declarations(ALICE, p["id"])
    assert state["river"]["start"] == "2026-12-06"
    assert state["river"]["end"] == "2026-12-09"


def test_seam_refuses_act_naming_another_project(ve_conn, conv_store):
    p = _make_project(ALICE, "Staged project")
    other = _make_project(ALICE, "Other project")
    reply = (
        "Done.\n\n[[declare]]\n"
        f"declare-window | project={other['id']} | start=2026-12-06 | end=2026-12-09"
    )
    result, _ = _board_turn(
        conv_store, ALICE,
        {"sheet_type": "campaign_board", "entity_type": "project", "entity_id": p["id"]},
        reply,
    )
    assert "[[declare]]" not in result.reply.reply
    assert D.derive_project_declarations(ALICE, other["id"])["river"] is None
    assert D.derive_project_declarations(ALICE, p["id"])["river"] is None


def test_seam_strips_but_never_actuates_off_board(ve_conn, conv_store):
    p = _make_project(ALICE, "Off-board project")
    reply = (
        "Done.\n\n[[declare]]\n"
        f"declare-window | project={p['id']} | start=2026-12-06 | end=2026-12-09"
    )
    svc = ConversationService(conv_store, generate_fn=lambda prompt, **kw: reply)
    result = svc.turn(
        ALICE, "champion", "Set the river.",
        conversation_id="c-offboard-1",
        context={"sheet_type": "bench", "entity_type": "project", "entity_id": p["id"]},
    )
    assert "[[declare]]" not in result.reply.reply
    assert D.derive_project_declarations(ALICE, p["id"])["river"] is None


def test_seam_task_subject_actuates_against_its_project(ve_conn, conv_store):
    p = _make_project(ALICE, "Task parent project")
    t = _make_task(ALICE, "A step", project_id=p["id"])
    reply = (
        "Placed.\n\n[[declare]]\n"
        f"place-hold | project={p['id']} | at=2026-12-07"
    )
    result, _ = _board_turn(
        conv_store, ALICE,
        {"sheet_type": "campaign_board", "entity_type": "task", "entity_id": t["id"]},
        reply,
    )
    assert "[[declare]]" not in result.reply.reply
    state = D.derive_project_declarations(ALICE, p["id"])
    assert len(state["holds"]) == 1
    assert state["holds"][0]["at"] == "2026-12-07"


def test_seam_move_and_remove_hold_round_trip(ve_conn, conv_store):
    p = _make_project(ALICE, "Round trip project")
    placed = _decide(ALICE, p["id"], D.HOLD_PLACED, {"at": "2026-12-07"})
    ctx = {"sheet_type": "campaign_board", "entity_type": "project", "entity_id": p["id"]}
    reply = f"Moved.\n\n[[declare]]\nmove-hold | hold={placed['id']} | at=2026-12-15"
    _board_turn(conv_store, ALICE, ctx, reply, message="Move the hold to December 15.")
    state = D.derive_project_declarations(ALICE, p["id"])
    assert state["holds"][0]["at"] == "2026-12-15"
    reply = f"Removed.\n\n[[declare]]\nremove-hold | hold={placed['id']}"
    _board_turn(conv_store, ALICE, ctx, reply, message="Take the hold off.")
    state = D.derive_project_declarations(ALICE, p["id"])
    assert state["holds"] == []


# ---------------------------------------------------------------------------
# (e) carriage — declaration state rides on the board sheet only
# ---------------------------------------------------------------------------


def test_carriage_carries_declaration_state_on_board(ve_conn):
    p = _make_project(ALICE, "Carriage project")
    _decide(ALICE, p["id"], D.RIVER_DECLARATION, {"start": "2026-12-06", "end": "2026-12-09"})
    placed = _decide(ALICE, p["id"], D.HOLD_PLACED, {"at": "2026-12-07"})
    block = SC.build_subject_context(
        ALICE,
        {"sheet_type": "campaign_board", "entity_type": "project", "entity_id": p["id"]},
    )
    assert block is not None
    assert "Board declarations for this project" in block
    assert "River — declared window: 2026-12-06 to 2026-12-09" in block
    assert f"2026-12-07 (hold {placed['id']})" in block


def test_carriage_names_empty_state_on_board(ve_conn):
    p = _make_project(ALICE, "Undeclared project")
    block = SC.build_subject_context(
        ALICE,
        {"sheet_type": "campaign_board", "entity_type": "project", "entity_id": p["id"]},
    )
    assert block is not None
    assert "River — no window declared" in block
    assert "Holds — none placed" in block


def test_carriage_no_declaration_lines_off_board(ve_conn):
    p = _make_project(ALICE, "Bench project")
    _decide(ALICE, p["id"], D.RIVER_DECLARATION, {"start": "2026-12-06", "end": "2026-12-09"})
    block = SC.build_subject_context(
        ALICE,
        {"sheet_type": "bench", "entity_type": "project", "entity_id": p["id"]},
    )
    assert block is not None
    assert "Board declarations" not in block
    assert "River —" not in block
