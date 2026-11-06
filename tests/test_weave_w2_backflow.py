"""W2 — factual execution backflow (weave): deterministic tests.

The Talk path carries a bounded, owner-scoped execution-state block —
tasks created from THIS conversation, plus their linked parents and
dependencies — between the evidence section and history. No model
calls; every assertion is deterministic against an in-memory store.

Coverage follows the design brief §10:
  A. Assembly (order, history window, kill switch, no-caller byte
     identity).
  B. Rendering (idle/overdue rules, terminal statuses, verbatim
     text, exact header/footer/notices, 80-char titles).
  C. Provenance (approval wording, degradation, ownership).
  D. Selection + traversal (BFS fairness, depth cap, cycles,
     unscoped-read discipline).
  E. Overflow (seed / traversal / length) vs retrieval uncertainty.
  F. Cap + prompt-budget gate (whole records only, notice / omit).
  G. Talk wiring (all seven seats, kill-switch off).

Conventions (same as test_bear_evidence_block.py): dates relative to
the live UTC date (never a pinned TODAY — midnight drift), rows
created through the real storage layer (or the real W1 approve path
for provenance), in-memory VE connection via monkeypatched
S.get_connection, isolated tmp ConversationStore, a capturing fake
generate_fn, ConversationService.turn for end-to-end assembly.

"Firebrand" appears in the tests only where the reconciled brief's
own template text is being quoted; the shipped rule renders the stock
display name ("Champion") — see the PR body for that discrepancy.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from local_ai.conversation import reply as R
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.vision_execution import execution_context as EC
from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as S

ALICE = "test-user-w2"
BOB = "other-user-w2"
TALK = "talk-1"
OTHER_TALK = "talk-2"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_conn(tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    S.init_db(conn)
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture()
def conv_store(tmp_path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


@pytest.fixture(autouse=True)
def kill_switch_on(monkeypatch):
    # Explicitly ON for every test in this file; the kill-switch-off
    # tests override it after the fixture runs.
    monkeypatch.setenv("ZENAF_EXECUTION_CONTEXT", "1")


def _today():
    return datetime.now(timezone.utc).date()


def _now():
    return datetime.now(timezone.utc)


def _set_dates(conn, task_id, *, created=None, updated=None, due=None):
    """Pin a task's timestamps/due date by direct SQL — the storage
    layer always writes "now", so tests control time this way."""
    if created is not None:
        conn.execute(
            "UPDATE tasks SET created_at=? WHERE id=?", (created, task_id)
        )
    if updated is not None:
        conn.execute(
            "UPDATE tasks SET updated_at=? WHERE id=?", (updated, task_id)
        )
    if due is not None:
        conn.execute("UPDATE tasks SET due_date=? WHERE id=?", (due, task_id))
    conn.commit()


def _make_task(conn, user, title, *, origin_convo=None, origin_seat="champion",
               origin_msg="m1", **kw):
    """Create a task through the real storage layer. Origin fields
    only when an origin conversation is given (a manual task has
    none). Returns the freshly read task row."""
    data = M.TaskCreate(title=title, **kw)
    tid = S._insert_task(
        conn,
        data,
        user,
        origin_seat=origin_seat if origin_convo else None,
        origin_conversation_id=origin_convo,
        origin_message_id=origin_msg if origin_convo else None,
    )
    conn.commit()
    return S.get_task(tid, user)


def _block(conn, convo=TALK, **kw):
    block, status = EC.build_execution_context(ALICE, convo, **kw)
    return block, status


def _seed_proposal(conv_store, user, convo, seat, title, *, block_index=0):
    """Seed one pending proposal through the real W1 provenance path:
    a voice message carrying a ```task-proposal block, then
    record_task_proposal against it (triple: source message +
    block_index + proposal_index)."""
    conv_store.ensure_conversation(user, convo)
    body = (
        "Prose here.\n```task-proposal\n"
        + json.dumps(
            {
                "proposals": [
                    {
                        "title": title,
                        "timeframe_commitment": "tentative",
                        "due_date": None,
                        "notes": "W2 seed",
                    }
                ]
            }
        )
        + "\n```"
    )
    msg = conv_store.append_message(user, convo, seat, "voice", body)
    return S.record_task_proposal(
        user,
        {
            "title": title,
            "timeframe_commitment": "tentative",
            "due_date": None,
            "notes": "W2 seed",
            "conversation_id": convo,
            "source_message_id": msg["id"],
            "block_index": block_index,
            "proposal_index": 0,
            # W1 (C-1): the body prose is "Prose here.".
            "evidence_quote": "Prose here.",
        },
        conversation_store=conv_store,
    )


def _approve_proposal(ve_conn, conv_store, user=ALICE, convo=TALK,
                      seat="champion"):
    """Seed + approve one W1 proposal through the real approve path.
    Returns (proposal, task). The task carries origin fields,
    created_task_id on the proposal row, and decided_at."""
    proposal = _seed_proposal(conv_store, user, convo, seat, "Approved task")
    result = S.approve_task_proposal(user, proposal["id"])
    return proposal, result["task"]


def _capture():
    prompts = []

    def fake_generate_fn(prompt, **kwargs):
        prompts.append(prompt)
        return "ok"

    return fake_generate_fn, prompts


def _history(n=12):
    return [
        {"role": "user" if i % 2 == 0 else "voice", "content": f"turn {i}"}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# A. Assembly
# ---------------------------------------------------------------------------


def test_absent_means_byte_identical():
    """No execution block: build_voice_prompt with
    execution_context=None is byte-identical to the same call without
    the parameter (its default). The parameter adds no section."""
    a, _ = R.build_voice_prompt(ALICE, "champion", "hello", _history(3))
    b, _ = R.build_voice_prompt(
        ALICE, "champion", "hello", _history(3), execution_context=None
    )
    assert a == b


def test_four_block_order_pinned(ve_conn):
    """Obligation, invitation, evidence, execution, history — the
    execution block sits between evidence and history, exactly."""
    _make_task(ve_conn, ALICE, "Order task", origin_convo=TALK)
    block, status = _block(ve_conn)
    assert status == "ok"
    prompt, _ = R.build_voice_prompt(
        ALICE,
        "champion",
        "hello",
        _history(3),
        obligation_context="OBLIGATION-SECTION",
        invitation_context="INVITATION-SECTION",
        evidence_context="EVIDENCE-SECTION",
        execution_context=block,
    )
    text = "\n".join(prompt)
    order = [
        text.index("OBLIGATION-SECTION"),
        text.index("INVITATION-SECTION"),
        text.index("EVIDENCE-SECTION"),
        text.index("Execution state"),
        text.index("Conversation so far:"),
    ]
    assert order == sorted(order)


def test_history_window_exactly_ten():
    """Twelve history turns in, exactly the last ten rendered, plus
    the continuity note. The execution block never enlarges the
    window."""
    block = "Execution state — tasks from this conversation."
    prompt, _ = R.build_voice_prompt(
        ALICE, "champion", "hello", _history(12), execution_context=block
    )
    text = "\n".join(prompt)
    lines = text.splitlines()
    for i in range(2, 12):
        assert f"User: turn {i}" in lines or f"Voice: turn {i}" in lines
    assert "User: turn 0" not in lines and "Voice: turn 1" not in lines
    assert "Continuity note" in text


def test_builder_never_calls_assembler(monkeypatch):
    """build_voice_prompt renders the block it is handed; it never
    calls build_execution_context itself. (The brief's §10 test:
    raising assembler → prompt with no block.)"""
    monkeypatch.setattr(
        EC, "build_execution_context", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("assembler must not be called by the builder")
        ),
    )
    prompt, _ = R.build_voice_prompt(ALICE, "champion", "hello", [])
    assert "Execution state" not in "\n".join(prompt)


def test_execution_block_never_displaces_history_or_character(ve_conn):
    """With the block included, all ten history turns and the
    character's own sections are still present — the gate measures
    the fully assembled prompt, so the block can only occupy
    headroom, never displace required content."""
    _make_task(ve_conn, ALICE, "Displace check", origin_convo=TALK)
    block, _ = _block(ve_conn)
    prompt, _ = R.build_voice_prompt(
        ALICE, "champion", "hello", _history(12), execution_context=block
    )
    text = "\n".join(prompt)
    assert "Execution state" in text
    for i in range(2, 12):
        assert f"turn {i}" in text
    assert text.endswith("Champion:")


# ---------------------------------------------------------------------------
# B. Rendering
# ---------------------------------------------------------------------------


def test_idle_thresholds(ve_conn):
    """Idle fires at 7 days, never before. The threshold is named in
    the clause."""
    now = _now()
    for days, fires in ((6, False), (7, True), (8, True)):
        task = _make_task(
            ve_conn, ALICE, f"Idle {days}d", origin_convo=TALK
        )
        _set_dates(
            ve_conn, task["id"],
            updated=(now - timedelta(days=days)).isoformat(),
        )
        block, _ = _block(ve_conn)
        clause = (
            f"No recorded update in {days} days "
            "(idle beyond the 7-day follow-through threshold)."
        )
        assert (clause in block) is fires, f"{days} days: {block}"


def test_done_and_dropped_lines(ve_conn):
    """Terminal statuses render as date facts only — no idle or
    overdue language, ever."""
    now = _now()
    today = _today()
    done = _make_task(ve_conn, ALICE, "Done task", origin_convo=TALK,
                      status="Done")
    _set_dates(ve_conn, done["id"],
               updated=(now - timedelta(days=30)).isoformat(),
               due=(today - timedelta(days=30)).isoformat())
    dropped = _make_task(ve_conn, ALICE, "Dropped task", origin_convo=TALK,
                         status="Dropped")
    _set_dates(ve_conn, dropped["id"],
               updated=(now - timedelta(days=30)).isoformat(),
               due=(today - timedelta(days=30)).isoformat())
    block, _ = _block(ve_conn)
    assert (
        f"Done task — Status Done (last updated "
        f"{(now - timedelta(days=30)).date().isoformat()})." in block
    )
    assert "Dropped task — Status Dropped (recorded)." in block
    assert "idle" not in block and "has passed" not in block


def test_freeform_completed_terminal(ve_conn):
    """The free-form status 'completed' — one of the five D3
    interpretations — renders as a date fact only, via the shared
    W1 terminal helper. (Documented, not normalized: D3.)"""
    now = _now()
    task = _make_task(ve_conn, ALICE, "Completed task", origin_convo=TALK,
                      status="completed")
    _set_dates(ve_conn, task["id"],
               updated=(now - timedelta(days=9)).isoformat(),
               due=(_today() - timedelta(days=9)).isoformat())
    block, _ = _block(ve_conn)
    assert f"Status completed (last updated {now.date().isoformat()})" not in block
    assert (
        f"Completed task — Status completed (last updated "
        f"{(now - timedelta(days=9)).date().isoformat()})." in block
    )
    assert "idle" not in block and "has passed" not in block


def test_overdue_and_tentative_suppression(ve_conn):
    """A non-tentative past-due task gets 'has passed'. A tentative
    past-due task gets the date fact only — ruling 3: tentative
    receives NEITHER idle NOR overdue language."""
    now = _now()
    today = _today()
    overdue = _make_task(ve_conn, ALICE, "Overdue task", origin_convo=TALK)
    _set_dates(ve_conn, overdue["id"], due=(today - timedelta(days=1)).isoformat())
    tentative = _make_task(
        ve_conn, ALICE, "Tentative task", origin_convo=TALK,
        timeframe_commitment="tentative",
    )
    _set_dates(
        ve_conn, tentative["id"],
        updated=(now - timedelta(days=9)).isoformat(),
        due=(today - timedelta(days=1)).isoformat(),
    )
    block, _ = _block(ve_conn)
    assert (
        f"Overdue task — Status Todo. Due date "
        f"{(today - timedelta(days=1)).isoformat()} has passed." in block
    )
    assert (
        f"Tentative task — Status Todo. Due date "
        f"{(today - timedelta(days=1)).isoformat()} (tentative)." in block
    )
    # The tentative record carries no idle clause despite 9 idle days,
    # and no 'has passed' despite a past due date.
    tentative_line = [
        line for line in block.splitlines() if "Tentative task" in line
    ][0]
    assert "idle" not in tentative_line and "has passed" not in tentative_line


def test_null_updated_at_no_idle(ve_conn):
    """A task with no updated_at gets no idle clause (not '0 days')."""
    task = _make_task(ve_conn, ALICE, "No updated task", origin_convo=TALK)
    ve_conn.execute("UPDATE tasks SET updated_at='' WHERE id=?", (task["id"],))
    ve_conn.commit()
    block, _ = _block(ve_conn)
    line = [ln for ln in block.splitlines() if "No updated task" in ln][0]
    assert "idle" not in line


def test_no_forbidden_words(ve_conn):
    """The brief's forbidden interpretations never appear in a
    rendered block. (The prohibition is on the system generating
    them — a user title containing one is data, preserved verbatim;
    see test_hostile_title_stays_on_one_line.)"""
    _make_task(ve_conn, ALICE, "Momentum task", origin_convo=TALK)
    block, _ = _block(ve_conn)
    lowered = block.lower()
    for word in ("stuck", "avoiding", "losing momentum"):
        assert word not in lowered, f"{word!r} leaked into: {block}"


def test_hostile_title_stays_on_one_line(ve_conn):
    """A title containing newlines and 'stuck' renders as data on
    exactly one line — no section escape, no interpretation."""
    task = _make_task(
        ve_conn, ALICE, "First line\nStuck second line", origin_convo=TALK
    )
    block, _ = _block(ve_conn)
    lines = [ln for ln in block.splitlines() if "First line" in ln]
    assert len(lines) == 1
    assert "Stuck second line" in lines[0]
    assert lines[0].count("—") == 1


def test_exact_header_footer_and_notices():
    """The fixed copy is verbatim, exactly as the reconciled brief
    specifies it."""
    assert EC.HEADER == (
        "Execution state — tasks from this conversation. Recorded "
        "execution state and deterministic conditions only. These "
        "records may be incomplete or stale. Do not treat computed "
        "conditions as evidence of motive, commitment, or failure."
    )
    assert EC.PARTIALITY_FOOTER == (
        "Execution context is partial; additional tasks were not included."
    )
    assert EC.RETRIEVAL_FAILURE_NOTICE == (
        "Execution records could not be retrieved for this turn. Their "
        "absence from this context does not indicate that no tasks exist."
    )
    assert EC.BUDGET_NOTICE == (
        "Execution records were omitted from this turn for length. Their "
        "absence from this context does not indicate that no tasks exist."
    )
    assert EC.RETRIEVAL_INCOMPLETE_NOTICE == (
        "Some linked execution records could not be checked. This view "
        "may be incomplete."
    )


def test_title_normalization_80_chars(ve_conn):
    """Titles over 80 chars are cut at 79 + '…' (deterministic
    ellipsis); the stored title is unchanged."""
    long_title = "T" * 100
    task = _make_task(ve_conn, ALICE, long_title, origin_convo=TALK)
    block, _ = _block(ve_conn)
    line = [ln for ln in block.splitlines() if " — Status " in ln][0]
    rendered_title = line.split(" — ")[0]
    assert rendered_title == "T" * 79 + "…"
    assert len(rendered_title) == 80
    assert S.get_task(task["id"], ALICE)["title"] == long_title


# ---------------------------------------------------------------------------
# C. Provenance
# ---------------------------------------------------------------------------


def test_provenance_approved_proposal(ve_conn, conv_store):
    """The strongest wording: an approved proposal, one match,
    resolvable seat → approval date + seat name. The shipped rule
    renders the stock display name ('Champion'), not the brief's
    template word 'Firebrand' — see the PR body."""
    _, task = _approve_proposal(ve_conn, conv_store)
    block, _ = _block(ve_conn)
    today = _today().isoformat()
    assert (
        f"Approved task — Status Todo. Created from a proposal you "
        f"approved on {today} in your conversation with Champion."
        in block
    )
    assert "You decided this" not in block


def test_provenance_no_proposal_degrades(ve_conn):
    """A task with origins but no proposal row → creation wording."""
    task = _make_task(ve_conn, ALICE, "Origin task", origin_convo=TALK)
    created = S.get_task(task["id"], ALICE)["created_at"][:10]
    block, _ = _block(ve_conn)
    assert (
        f"Origin task — Status Todo. Task created on {created}, "
        f"originating from your conversation with Champion." in block
    )


def test_provenance_ambiguity_degrades(ve_conn, conv_store):
    """Two approved proposals pointing at the same task (ambiguous
    reverse lookup) → weaker creation wording, never a guess at
    which proposal."""
    _, task = _approve_proposal(ve_conn, conv_store)
    # A second approved proposal row claiming the same task.
    second = _seed_proposal(conv_store, ALICE, TALK, "champion",
                            "Second proposal")
    ve_conn.execute(
        "UPDATE task_proposals SET created_task_id=?, state='approved', "
        "decided_at=? WHERE id=?",
        (task["id"], _now().isoformat(), second["id"]),
    )
    ve_conn.commit()
    block, _ = _block(ve_conn)
    assert "approved on" not in block
    assert "Task created on" in block


def test_provenance_lookup_failure_degrades(ve_conn, monkeypatch):
    """The proposal lookup raising → creation wording, block still
    present. Provenance is optional enrichment (verdict correction
    3); it never suppresses the block."""
    _make_task(ve_conn, ALICE, "Lookup fail task", origin_convo=TALK)

    def _boom(*a, **k):
        raise RuntimeError("proposal store down")

    monkeypatch.setattr(S, "get_proposals_by_created_task", _boom)
    block, status = _block(ve_conn)
    assert status == "ok"
    assert "Lookup fail task" in block
    assert "Task created on" in block


def test_provenance_linked_task_own_origin(ve_conn):
    """A linked task renders ITS OWN origin (seat + conversation),
    not the seed's."""
    seed = _make_task(ve_conn, ALICE, "Seed task", origin_convo=TALK)
    linked = _make_task(
        ve_conn, ALICE, "Linked task", origin_convo=OTHER_TALK,
        origin_seat="guardian", origin_msg="m-linked",
    )
    ve_conn.execute(
        "UPDATE tasks SET dependency_ids=? WHERE id=?",
        ('["%s"]' % linked["id"], seed["id"]),
    )
    ve_conn.commit()
    created = S.get_task(linked["id"], ALICE)["created_at"][:10]
    block, _ = _block(ve_conn)
    assert (
        f"Linked task — Status Todo. Task created on {created}, "
        f"originating from your conversation with Guardian." in block
    )


def test_provenance_seat_only_and_date_only_and_neither(ve_conn):
    """Provenance degrades through its hierarchy: seat-only,
    date-only, neither — each verified word, never a guess."""
    # Seat-only: empty created_at.
    seat_only = _make_task(
        ve_conn, ALICE, "Seat only task", origin_convo=TALK
    )
    ve_conn.execute(
        "UPDATE tasks SET created_at='' WHERE id=?", (seat_only["id"],)
    )
    # Date-only: unresolvable seat id.
    date_only = _make_task(
        ve_conn, ALICE, "Date only task", origin_convo=TALK,
        origin_seat="not-a-seat",
    )
    # Neither: empty created_at + unresolvable seat.
    neither = _make_task(
        ve_conn, ALICE, "Neither task", origin_convo=TALK,
        origin_seat="not-a-seat",
    )
    ve_conn.execute("UPDATE tasks SET created_at='' WHERE id=?", (neither["id"],))
    ve_conn.commit()
    block, _ = _block(ve_conn)
    assert (
        "Seat only task — Status Todo. Originating from your conversation "
        "with Champion." in block
    )
    created = S.get_task(date_only["id"], ALICE)["created_at"][:10]
    assert (
        f"Date only task — Status Todo. Task created on {created}." in block
    )
    assert "Neither task — Status Todo." in block
    neither_line = [ln for ln in block.splitlines() if "Neither task" in ln][0]
    assert neither_line == "Neither task — Status Todo."


def test_cross_user_proposal_never_matches(ve_conn, conv_store):
    """BOB's approved proposal pointing at ALICE's task id must
    never produce approval wording in ALICE's block — the reverse
    lookup is owner-scoped."""
    victim = _make_task(ve_conn, ALICE, "Victim task", origin_convo=TALK)
    bob_proposal = _seed_proposal(conv_store, BOB, TALK, "champion",
                                  "Bob proposal")
    ve_conn.execute(
        "UPDATE task_proposals SET created_task_id=?, state='approved', "
        "decided_at=? WHERE id=?",
        (victim["id"], _now().isoformat(), bob_proposal["id"]),
    )
    ve_conn.commit()
    block, _ = _block(ve_conn)
    assert "approved on" not in block
    assert "Task created on" in block


# ---------------------------------------------------------------------------
# D. Selection + traversal
# ---------------------------------------------------------------------------


def _link(conn, parent_id, child_id):
    """Append ``child_id`` to a task's dependency_ids (never
    overwrites the existing edges)."""
    row = conn.execute(
        "SELECT dependency_ids FROM tasks WHERE id=?", (parent_id,)
    ).fetchone()
    current = json.loads(row["dependency_ids"]) if row and row["dependency_ids"] else []
    if child_id not in current:
        current.append(child_id)
    conn.execute(
        "UPDATE tasks SET dependency_ids=? WHERE id=?",
        (json.dumps(current), parent_id),
    )
    conn.commit()


def test_seeds_first_then_linked(ve_conn):
    """All seeds render before any linked task, in seed order
    (updated_at DESC — the seed query's order; pinned explicitly
    here because same-instant seeds tie on updated_at)."""
    now = _now()
    s1 = _make_task(ve_conn, ALICE, "Seed A", origin_convo=TALK)
    s2 = _make_task(ve_conn, ALICE, "Seed B", origin_convo=TALK)
    _set_dates(ve_conn, s1["id"], updated=now.isoformat())
    _set_dates(ve_conn, s2["id"],
               updated=(now - timedelta(days=1)).isoformat())
    linked = _make_task(
        ve_conn, ALICE, "Linked A", origin_convo=OTHER_TALK,
        origin_seat="guardian",
    )
    _link(ve_conn, s1["id"], linked["id"])
    block, _ = _block(ve_conn)
    assert block.index("Seed A") < block.index("Seed B") < block.index("Linked A")


def test_long_chain_does_not_starve_other_seed(ve_conn):
    """Breadth-first fairness: seed B's depth-1 link is selected
    before seed A's depth-2 link, however long A's chain is."""
    a = _make_task(ve_conn, ALICE, "Chain A", origin_convo=TALK)
    a1 = _make_task(ve_conn, ALICE, "Chain A1", origin_convo=OTHER_TALK)
    a2 = _make_task(ve_conn, ALICE, "Chain A2", origin_convo=OTHER_TALK)
    b = _make_task(ve_conn, ALICE, "Chain B", origin_convo=TALK)
    b1 = _make_task(ve_conn, ALICE, "Chain B1", origin_convo=OTHER_TALK)
    _link(ve_conn, a["id"], a1["id"])
    _link(ve_conn, a1["id"], a2["id"])
    _link(ve_conn, b["id"], b1["id"])
    block, _ = _block(ve_conn)
    assert block.index("Chain B1") < block.index("Chain A2")


def test_two_paths_counts_once_min_depth(ve_conn):
    """A task reachable by a depth-1 edge and by a depth-2 path is
    rendered once, at minimum depth: it renders in the depth-1 level,
    before any depth-2-only task."""
    seed = _make_task(ve_conn, ALICE, "Seed task", origin_convo=TALK)
    mid = _make_task(ve_conn, ALICE, "Mid task", origin_convo=OTHER_TALK)
    near = _make_task(ve_conn, ALICE, "Near task", origin_convo=OTHER_TALK)
    far = _make_task(ve_conn, ALICE, "Far task", origin_convo=OTHER_TALK)
    _link(ve_conn, seed["id"], mid["id"])
    _link(ve_conn, mid["id"], near["id"])
    _link(ve_conn, seed["id"], near["id"])
    _link(ve_conn, mid["id"], far["id"])
    block, _ = _block(ve_conn)
    assert block.count("Near task") == 1
    assert block.index("Near task") < block.index("Far task")


def test_depth_stops_at_three(ve_conn):
    """A chain of five linked tasks: depths 1–3 selected, depth 4+
    absent."""
    prev = _make_task(ve_conn, ALICE, "Depth 0", origin_convo=TALK)
    for i in range(1, 6):
        nxt = _make_task(
            ve_conn, ALICE, f"Depth {i}", origin_convo=OTHER_TALK
        )
        _link(ve_conn, prev["id"], nxt["id"])
        prev = nxt
    block, _ = _block(ve_conn)
    for i in (1, 2, 3):
        assert f"Depth {i}" in block
    for i in (4, 5):
        assert f"Depth {i}" not in block


def test_cycles_terminate(ve_conn):
    """A two-cycle and a self-dependency terminate; each task renders
    once."""
    a = _make_task(ve_conn, ALICE, "Cycle A", origin_convo=TALK)
    b = _make_task(ve_conn, ALICE, "Cycle B", origin_convo=OTHER_TALK)
    _link(ve_conn, a["id"], b["id"])
    _link(ve_conn, b["id"], a["id"])
    c = _make_task(ve_conn, ALICE, "Cycle C", origin_convo=TALK)
    _link(ve_conn, c["id"], c["id"])
    block, status = _block(ve_conn)
    assert status == "ok"
    assert block.count("Cycle A") == 1
    assert block.count("Cycle B") == 1
    assert block.count("Cycle C") == 1


def test_children_never_followed(ve_conn):
    """Downward links (child tasks via parent_task_id) are NEVER
    traversed — only parent_task_id and dependency_ids, upward."""
    parent = _make_task(ve_conn, ALICE, "Parent task", origin_convo=TALK)
    child = _make_task(
        ve_conn, ALICE, "Child task", origin_convo=OTHER_TALK,
        parent_task_id=parent["id"],
    )
    block, _ = _block(ve_conn)
    assert "Parent task" in block
    assert "Child task" not in block


def test_foreign_and_missing_edges_exclude_and_prune(ve_conn):
    """A foreign edge and a missing edge are excluded with no footer
    and no placeholder. Traversal never passes through an unreadable
    task: a task reachable ONLY through BOB's task stays out."""
    seed = _make_task(ve_conn, ALICE, "Seed task", origin_convo=TALK)
    foreign = _make_task(ve_conn, BOB, "Foreign task", origin_convo=TALK)
    hidden = _make_task(ve_conn, ALICE, "Hidden task", origin_convo=OTHER_TALK)
    ve_conn.execute(
        "UPDATE tasks SET dependency_ids=? WHERE id=?",
        ('["%s"]' % hidden["id"], foreign["id"]),
    )
    ve_conn.execute(
        "UPDATE tasks SET dependency_ids=? WHERE id=?",
        ('["%s", "missing-id"]' % foreign["id"], seed["id"]),
    )
    ve_conn.commit()
    block, status = _block(ve_conn)
    assert status == "ok"
    assert "Seed task" in block
    assert "Foreign task" not in block
    assert "Hidden task" not in block  # pruned: only path is through foreign
    assert "missing-id" not in block
    assert EC.PARTIALITY_FOOTER not in block


def test_read_budget_twenty(ve_conn, monkeypatch):
    """Thirty missing edges: traversal stops at 20 reads total, no
    overflow, no footer — an unreadable edge never establishes
    omission."""
    seed = _make_task(ve_conn, ALICE, "Seed task", origin_convo=TALK)
    missing = [f"missing-{i}" for i in range(30)]
    import json

    ve_conn.execute(
        "UPDATE tasks SET dependency_ids=? WHERE id=?",
        (json.dumps(missing), seed["id"]),
    )
    ve_conn.commit()
    reads = []
    real_get = S.get_task

    def _counting_get(task_id, user_id):
        reads.append((task_id, user_id))
        return real_get(task_id, user_id)

    monkeypatch.setattr(S, "get_task", _counting_get)
    block, status = _block(ve_conn)
    assert status == "ok"
    assert len(reads) <= 20
    assert EC.PARTIALITY_FOOTER not in block
    assert EC.RETRIEVAL_INCOMPLETE_NOTICE not in block


def test_traversal_reads_are_owner_scoped(ve_conn, monkeypatch):
    """Every traversal read passes the caller's user id — no
    unscoped read exists on the path. The seed query is owner-scoped
    by the same store function the whole product uses."""
    seed = _make_task(ve_conn, ALICE, "Seed task", origin_convo=TALK)
    linked = _make_task(ve_conn, ALICE, "Linked task", origin_convo=OTHER_TALK)
    _link(ve_conn, seed["id"], linked["id"])
    seen = []
    real_get = S.get_task

    def _watching_get(task_id, user_id):
        seen.append(user_id)
        return real_get(task_id, user_id)

    monkeypatch.setattr(S, "get_task", _watching_get)
    _block(ve_conn)
    assert seen, "traversal made no reads"
    assert all(uid == ALICE for uid in seen)
    # And the source itself: the module's only task reads are the
    # owner-scoped store calls.
    src = Path(EC.__file__).read_text()
    assert "get_task(" in src
    assert "S.list_tasks(" not in src


# ---------------------------------------------------------------------------
# E. Overflow vs retrieval uncertainty
# ---------------------------------------------------------------------------


def test_seed_overflow_footer(ve_conn):
    """Eleven seeds: ten render, the eleventh establishes overflow,
    the footer fires, no record is summarized."""
    for i in range(11):
        _make_task(ve_conn, ALICE, f"Seed {i:02d}", origin_convo=TALK)
    block, status = _block(ve_conn)
    assert status == "ok"
    assert len([ln for ln in block.splitlines() if " — Status " in ln]) == 10
    assert EC.PARTIALITY_FOOTER in block


def test_traversal_overflow_footer(ve_conn):
    """One seed plus twelve dependencies: ten render, the eleventh
    verified linked task establishes overflow, footer fires."""
    seed = _make_task(ve_conn, ALICE, "Seed task", origin_convo=TALK)
    import json

    deps = [
        _make_task(ve_conn, ALICE, f"Dep {i:02d}", origin_convo=OTHER_TALK)
        for i in range(12)
    ]
    ve_conn.execute(
        "UPDATE tasks SET dependency_ids=? WHERE id=?",
        (json.dumps([d["id"] for d in deps]), seed["id"]),
    )
    ve_conn.commit()
    block, status = _block(ve_conn)
    assert status == "ok"
    assert len([ln for ln in block.splitlines() if " — Status " in ln]) == 10
    assert EC.PARTIALITY_FOOTER in block


def test_unverifiable_edge_no_footer(ve_conn):
    """A seed with only a foreign dependency: no overflow, no footer,
    no placeholder."""
    seed = _make_task(ve_conn, ALICE, "Seed task", origin_convo=TALK)
    foreign = _make_task(ve_conn, BOB, "Foreign task", origin_convo=TALK)
    _link(ve_conn, seed["id"], foreign["id"])
    block, status = _block(ve_conn)
    assert status == "ok"
    assert EC.PARTIALITY_FOOTER not in block
    assert "Foreign task" not in block


def test_length_dropped_footer(ve_conn):
    """Records that do not fit the 2,000-char cap whole are omitted
    and the footer fires — a length-dropped owned record IS an
    established omission."""
    for i in range(10):
        _make_task(ve_conn, ALICE, f"Long task {i} " + "x" * 200,
                   origin_convo=TALK)
    block, status = _block(ve_conn)
    assert status == "ok"
    assert len(block) <= 2000
    assert EC.PARTIALITY_FOOTER in block
    rendered = [ln for ln in block.splitlines() if " — Status " in ln]
    assert 0 < len(rendered) < 10


def test_read_exception_incomplete_notice_not_footer(ve_conn, monkeypatch):
    """A traversal read raising: verified records stay, the
    retrieval-incomplete notice fires, the partiality footer NEVER
    does (verdict correction 2)."""
    seed = _make_task(ve_conn, ALICE, "Seed task", origin_convo=TALK)
    linked = _make_task(ve_conn, ALICE, "Linked task", origin_convo=OTHER_TALK)
    _link(ve_conn, seed["id"], linked["id"])
    real_get = S.get_task

    def _raising_get(task_id, user_id):
        if task_id == linked["id"]:
            raise RuntimeError("read failed")
        return real_get(task_id, user_id)

    monkeypatch.setattr(S, "get_task", _raising_get)
    block, status = _block(ve_conn)
    assert status == "incomplete"
    assert "Seed task" in block
    assert "Linked task" not in block
    assert EC.RETRIEVAL_INCOMPLETE_NOTICE in block
    assert EC.PARTIALITY_FOOTER not in block


def test_seed_exception_failure_notice(ve_conn, monkeypatch):
    """A seed query raising → the full retrieval-failure notice,
    nothing else, status 'failed'."""
    def _boom(*a, **k):
        raise RuntimeError("seed store down")

    monkeypatch.setattr(S, "list_tasks_by_origin_conversation", _boom)
    block, status = _block(ve_conn)
    assert status == "failed"
    assert block == EC.RETRIEVAL_FAILURE_NOTICE


def test_empty_conversation_no_block(ve_conn):
    """No origin tasks in the conversation → (None, 'empty'); the
    Talk path passes None, so no section appears."""
    block, status = _block(ve_conn)
    assert block is None and status == "empty"


# ---------------------------------------------------------------------------
# F. Cap + prompt-budget gate
# ---------------------------------------------------------------------------


def test_whole_records_only_and_cap(ve_conn):
    """Every rendered record ends with a period and is complete; the
    whole block is at most 2,000 chars including header and footer."""
    for i in range(10):
        _make_task(ve_conn, ALICE, f"Task {i} " + "y" * 150, origin_convo=TALK)
    block, _ = _block(ve_conn)
    assert len(block) <= 2000
    assert EC.HEADER in block
    for line in block.splitlines():
        if " — Status " in line:
            assert line.endswith("."), line


def test_footer_always_fits(ve_conn):
    """Even at the cap, the footer is present — its length was
    reserved before any record was fitted."""
    for i in range(10):
        _make_task(ve_conn, ALICE, f"Task {i} " + "z" * 180, origin_convo=TALK)
    block, _ = _block(ve_conn)
    assert len(block) <= 2000
    assert EC.PARTIALITY_FOOTER in block


def _sized_history(target_base):
    """History turns whose assembled prompt length is exactly
    ``target_base``: a probe with three empty turns is measured,
    then the needed content is distributed across them (each turn's
    content is capped at 2,000 chars by the builder, so one turn can
    never reach the budget on its own)."""
    probe, _ = R.build_voice_prompt(
        ALICE, "champion", "hello",
        [{"role": "user" if i % 2 == 0 else "voice", "content": ""}
         for i in range(3)],
    )
    need = target_base - len("\n".join(probe))
    assert 0 < need <= 6000, f"need {need} out of range for 3 turns"
    parts, remaining = [], need
    for _ in range(3):
        take = min(2000, remaining)
        parts.append("h" * take)
        remaining -= take
    assert remaining == 0
    return [
        {"role": "user" if i % 2 == 0 else "voice", "content": parts[i]}
        for i in range(3)
    ]


def test_budget_notice_on_shortfall(caplog):
    """A prompt whose headroom fits the budget notice but not the
    block: the notice replaces the block, and one warning log line
    carries conversation id, block length, headroom."""
    import logging

    block = "EXECUTION-BLOCK-MARKER " + "X" * 477
    assert len(block) == 500
    notice = R._EXECUTION_BUDGET_NOTICE
    # Base length must satisfy: block does NOT fit
    # (base > 8000 - 502) but the notice DOES
    # (base <= 8000 - len(notice) - 2). Aim 10 chars inside the
    # notice-fits boundary.
    target_base = 8000 - len(notice) - 2 - 10
    history = _sized_history(target_base)
    with caplog.at_level(logging.WARNING, logger="local_ai.conversation.reply"):
        prompt, _ = R.build_voice_prompt(
            ALICE, "champion", "hello", history,
            execution_context=block, conversation_id="talk-1",
        )
    text = "\n".join(prompt)
    assert "EXECUTION-BLOCK-MARKER" not in text
    assert notice in text
    assert "h" * 100 in text  # history intact
    warnings = [
        rec for rec in caplog.records
        if "execution_context budget" in rec.getMessage()
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "talk-1" in msg and "block_chars=500" in msg and "headroom=" in msg


def test_budget_omit_when_notice_does_not_fit(caplog):
    """A prompt with almost no headroom: neither block nor notice is
    inserted; one warning log line fires; history is intact."""
    import logging

    block = "EXECUTION-BLOCK-MARKER " + "X" * 477
    notice = R._EXECUTION_BUDGET_NOTICE
    # Base length past the point where even the notice fits.
    target_base = 8000 - len(notice) - 2 + 50
    history = _sized_history(target_base)
    with caplog.at_level(logging.WARNING, logger="local_ai.conversation.reply"):
        prompt, _ = R.build_voice_prompt(
            ALICE, "champion", "hello", history,
            execution_context=block, conversation_id="talk-1",
        )
    text = "\n".join(prompt)
    assert "EXECUTION-BLOCK-MARKER" not in text
    assert notice not in text
    assert "h" * 100 in text
    assert any(
        "execution_context budget" in rec.getMessage()
        for rec in caplog.records
    )


def test_prompt_budget_verification():
    """The gate's premise, pinned: there is NO enforced overall
    character cap on the assembled Talk prompt in this codebase.
    The 8,000-char figure is a policy threshold adopted from the
    first-meeting steward-frame cap, not an enforced assembly cap —
    which is exactly why the gate yields (notice, then omit) instead
    of truncating anything. If this test fails, the premise changed
    and the gate needs re-examination."""
    import re

    src = Path(R.__file__).read_text()
    # No enforced overall cap: no headroom constant is ever defined
    # or assigned (the word appears only in prose comments and in
    # the W2 gate's own local variable).
    assert re.search(r"\bMIN_HEADROOM\s*=", src) is None
    assert re.search(r"(?<!_)HEADROOM\s*=", src) is None
    # The only [:8000] in reply.py is the extra_instructions slice.
    assert src.count("[:8000]") == 1
    assert "extra_instructions" in src[src.index("[:8000]") - 200:
                                        src.index("[:8000]")]


# ---------------------------------------------------------------------------
# G. Talk wiring
# ---------------------------------------------------------------------------


ALL_SEATS = [
    "mentor", "champion", "guardian", "maverick",
    "ambassador", "conductor", "skeptic",
]


def test_service_turn_carries_block_all_seats(ve_conn, conv_store):
    """All seven seats carry the block on an ordinary Talk turn."""
    _make_task(ve_conn, ALICE, "Talk task", origin_convo=TALK)
    fake, prompts = _capture()
    svc = ConversationService(conv_store, generate_fn=fake)
    for arch_id in ALL_SEATS:
        svc.turn(ALICE, arch_id, "hello", conversation_id=TALK)
    assert len(prompts) == 7
    for prompt in prompts:
        assert "Execution state" in prompt
        assert "Talk task" in prompt


def test_service_turn_kill_switch_off(ve_conn, conv_store, monkeypatch):
    """Kill switch OFF: no block for any seat, and the turn is
    byte-identical to a turn with no origin tasks at all."""
    _make_task(ve_conn, ALICE, "Talk task", origin_convo=TALK)
    monkeypatch.setenv("ZENAF_EXECUTION_CONTEXT", "0")
    fake, prompts = _capture()
    svc = ConversationService(conv_store, generate_fn=fake)
    svc.turn(ALICE, "champion", "hello", conversation_id=TALK)
    assert "Execution state" not in prompts[0]
    # And a turn on a conversation with no tasks looks the same.
    svc.turn(ALICE, "champion", "hello", conversation_id="talk-empty")
    assert prompts[0] == prompts[1]


def test_service_turn_no_origin_tasks_no_block(ve_conn, conv_store):
    """A Talk turn on a conversation with no origin tasks carries no
    execution section at all."""
    fake, prompts = _capture()
    svc = ConversationService(conv_store, generate_fn=fake)
    svc.turn(ALICE, "champion", "hello", conversation_id=TALK)
    assert "Execution state" not in prompts[0]
