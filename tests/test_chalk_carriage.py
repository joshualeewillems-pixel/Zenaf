"""OPS-7 [[chalk]] carriage — parser, store, service seam, read route.

Every generation is a recorded output driven through the real
``ConversationService.turn`` with an injected ``generate_fn`` — zero
live model calls (the Stage 1B fixture pattern). The parser tests
are pure; the store tests use a tmp-path SQLite file; the route
tests call the handler with the store factory monkeypatched.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from local_ai.conversation.chalk_store import ChalkStore
from local_ai.conversation.chalk_tail import parse_chalk_tail
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore

USER = "u-chalk"
OTHER_USER = "u-other"
CONVO = "jynx-scroll:project:p1"
MAVERICK = "maverick"

VALID_TAIL = (
    "A workshop, then — walls that remember the tide.\n"
    "\n"
    "[[chalk]]\n"
    "drawing | space=600x800 | title=The workshop that floods\n"
    "stamp | ring | cx=300 | cy=300 | w=400 | tier=0.60\n"
    "stamp | slash | cx=220 | cy=480 | w=200 | angle=52 | tier=0.95\n"
    "stroke | d=M100 600 Q300 560 500 620 | width=3 | tier=0.32"
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_absent_tail_returns_text_byte_identical():
    text = "Just a reply.\nWith two lines."
    parsed = parse_chalk_tail(text)
    assert parsed.status == "absent"
    assert parsed.body == text
    assert parsed.drawings == []


def test_valid_tail_parses_drawing_in_arrival_order():
    parsed = parse_chalk_tail(VALID_TAIL)
    assert parsed.status == "ok"
    assert parsed.body == "A workshop, then — walls that remember the tide."
    assert len(parsed.drawings) == 1
    drawing = parsed.drawings[0]
    assert drawing["title"] == "The workshop that floods"
    assert drawing["space"] == {"w": 600, "h": 800}
    assert drawing["marks"] == [
        {"type": "stamp", "stamp": "ring", "cx": 300, "cy": 300, "w": 400, "tier": 0.6},
        {
            "type": "stamp", "stamp": "slash", "cx": 220, "cy": 480, "w": 200,
            "angle": 52, "tier": 0.95,
        },
        {"type": "stroke", "d": "M100 600 Q300 560 500 620", "width": 3, "tier": 0.32},
    ]
    # No chalk markup survives in the body.
    assert "[[chalk]]" not in parsed.body
    assert "stamp |" not in parsed.body


def test_stamp_defaults_space_and_tier():
    parsed = parse_chalk_tail("Body.\n\n[[chalk]]\ndrawing\nstamp | wave | cx=10 | cy=20 | w=30")
    # A bare `drawing` word is not an instruction line: the tail
    # never opens and the delimiter is hygiene-stripped... the
    # `drawing` header requires its pipe form.
    assert parsed.drawings == []
    parsed = parse_chalk_tail(
        "Body.\n\n[[chalk]]\ndrawing |\nstamp | wave | cx=10 | cy=20 | w=30"
    )
    assert parsed.status == "ok"
    drawing = parsed.drawings[0]
    assert drawing["space"] == {"w": 600, "h": 800}
    assert drawing["title"] is None
    assert drawing["marks"][0]["tier"] == 0.95


def test_multiple_drawings_all_stand():
    text = (
        "Body.\n\n[[chalk]]\n"
        "drawing | title=One\n"
        "stamp | arc | cx=100 | cy=100 | w=200\n"
        "drawing | title=Two\n"
        "stroke | d=M0 0 L600 800 | width=2 | tier=0.60"
    )
    parsed = parse_chalk_tail(text)
    assert parsed.status == "ok"
    assert [d["title"] for d in parsed.drawings] == ["One", "Two"]


def test_bad_drawing_drops_whole_sibling_stands():
    text = (
        "Body.\n\n[[chalk]]\n"
        "drawing | title=Good\n"
        "stamp | ring | cx=300 | cy=300 | w=400\n"
        "drawing | title=Bad\n"
        "stamp | ring | cx=300 | cy=300 | w=400\n"
        "stamp | nosuchstamp | cx=1 | cy=1 | w=10"
    )
    parsed = parse_chalk_tail(text)
    assert parsed.status == "ok"
    # The bad drawing drops WHOLE — its valid first mark does not leak.
    assert [d["title"] for d in parsed.drawings] == ["Good"]
    assert any("drawing_drop" in d for d in parsed.diagnostics)


def test_grammar_failure_prose_inside_tail_drops_everything():
    text = (
        "Body.\n\n[[chalk]]\n"
        "drawing |\n"
        "stamp | ring | cx=300 | cy=300 | w=400\n"
        "and then some prose"
    )
    parsed = parse_chalk_tail(text)
    assert parsed.status == "grammar_failure"
    assert parsed.drawings == []
    assert parsed.body == "Body."


def test_grammar_failure_mark_before_any_drawing():
    parsed = parse_chalk_tail("Body.\n\n[[chalk]]\nstamp | ring | cx=1 | cy=1 | w=10")
    assert parsed.status == "grammar_failure"
    assert parsed.drawings == []


def test_grammar_failure_too_many_drawings():
    one = "drawing |\nstamp | ring | cx=1 | cy=1 | w=10"
    text = "Body.\n\n[[chalk]]\n" + "\n".join([one] * 5)
    parsed = parse_chalk_tail(text)
    assert parsed.status == "grammar_failure"
    assert parsed.drawings == []


def test_grammar_failure_duplicate_delimiter():
    text = "Body.\n\n[[chalk]]\ndrawing |\n[[chalk]]\nstamp | ring | cx=1 | cy=1 | w=10"
    parsed = parse_chalk_tail(text)
    assert parsed.status == "grammar_failure"
    assert parsed.drawings == []


def test_delimiter_followed_by_prose_is_hygiene_strip_only():
    text = "Body mentions the marker.\n[[chalk]]\nAnd keeps talking."
    parsed = parse_chalk_tail(text)
    assert parsed.status == "hygiene_strip"
    assert parsed.drawings == []
    assert "[[chalk]]" not in parsed.body
    assert "And keeps talking." in parsed.body


def test_partial_delimiter_truncation_is_grammar_failure():
    parsed = parse_chalk_tail("A reply that was cut off mid-mark\n[[cha")
    assert parsed.status == "grammar_failure"
    assert parsed.body == "A reply that was cut off mid-mark"


def test_mark_cap_drops_the_drawing_whole():
    marks = "\n".join("stamp | ring | cx=1 | cy=1 | w=10" for _ in range(33))
    parsed = parse_chalk_tail("Body.\n\n[[chalk]]\ndrawing |\n" + marks)
    assert parsed.status == "ok"
    assert parsed.drawings == []


def test_bad_tier_and_bad_path_drop_their_drawing():
    bad_tier = (
        "Body.\n\n[[chalk]]\ndrawing |\n"
        "stamp | ring | cx=1 | cy=1 | w=10 | tier=0.50"
    )
    assert parse_chalk_tail(bad_tier).drawings == []
    bad_path = (
        "Body.\n\n[[chalk]]\ndrawing |\n"
        "stroke | d=M0 0 xploit 9 | width=2 | tier=0.32"
    )
    assert parse_chalk_tail(bad_path).drawings == []
    no_move = (
        "Body.\n\n[[chalk]]\ndrawing |\n"
        "stroke | d=L10 10 L20 20 | width=2 | tier=0.32"
    )
    assert parse_chalk_tail(no_move).drawings == []


def test_empty_drawing_drops_and_delimiter_alone_is_no_change():
    parsed = parse_chalk_tail("Body.\n\n[[chalk]]\ndrawing | title=Nothing drawn")
    assert parsed.status == "ok"
    assert parsed.drawings == []
    parsed = parse_chalk_tail("Body.\n\n[[chalk]]")
    assert parsed.status == "no_change"
    assert parsed.body == "Body."
    assert parsed.drawings == []


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@pytest.fixture()
def chalk_store(tmp_path):
    store = ChalkStore(db_path=tmp_path / "chalk.db")
    yield store
    store.close()


def _record(store, user=USER, title="A drawing"):
    return store.record_drawing(
        user_id=user,
        conversation_id=CONVO,
        title=title,
        space={"w": 600, "h": 800},
        marks=[{"type": "stamp", "stamp": "ring", "cx": 1, "cy": 2, "w": 3, "tier": 0.95}],
        subject_type="project",
        subject_id="p1",
    )


def test_store_round_trip_and_order(chalk_store):
    first = _record(chalk_store, title="First")
    second = _record(chalk_store, title="Second")
    listed = chalk_store.list_drawings(USER)
    assert [d["id"] for d in listed] == [first["id"], second["id"]]
    got = chalk_store.get_drawing(USER, first["id"])
    assert got["subject_type"] == "project"
    assert got["subject_id"] == "p1"
    assert got["marks"][0]["stamp"] == "ring"


def test_store_owner_isolation(chalk_store):
    mine = _record(chalk_store)
    assert chalk_store.get_drawing(OTHER_USER, mine["id"]) is None
    assert chalk_store.list_drawings(OTHER_USER) == []
    assert chalk_store.get_drawing(USER, "no-such-id") is None


def test_store_list_filter_by_conversation(chalk_store):
    # A scroll's sheet carries only its own conversation's drawings
    # (founder, 2026-11-25): the store's read can key on the
    # conversation a drawing was born in.
    mine = _record(chalk_store)
    other_convo = chalk_store.record_drawing(
        user_id=USER,
        conversation_id="jynx-scroll:task:t9",
        title="Elsewhere",
        space={"w": 600, "h": 800},
        marks=[{"type": "stamp", "stamp": "wave", "cx": 1, "cy": 2, "w": 3, "tier": 0.6}],
    )
    filtered = chalk_store.list_drawings(USER, conversation_id=CONVO)
    assert [d["id"] for d in filtered] == [mine["id"]]
    filtered_other = chalk_store.list_drawings(USER, conversation_id="jynx-scroll:task:t9")
    assert [d["id"] for d in filtered_other] == [other_convo["id"]]
    # Unfiltered is the whole archive, as before; a conversation
    # the caller does not own yields nothing.
    assert len(chalk_store.list_drawings(USER)) == 2
    assert chalk_store.list_drawings(OTHER_USER, conversation_id=CONVO) == []
    assert chalk_store.list_drawings(USER, conversation_id="no-such-conversation") == []


# ---------------------------------------------------------------------------
# Service seam (recorded generations, zero live model calls)
# ---------------------------------------------------------------------------


class RecordedGen:
    """Fake generate_fn in the Stage 1B pattern: replays recorded
    voice outputs; thread-summary calls get a fixed string."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, prompt, **kw):
        op = kw.get("operation")
        self.calls.append((op, prompt))
        if op == "conversation-thread-summary":
            return "Rolling summary of the thread."
        if self.outputs:
            return self.outputs.pop(0)
        return "Recorded reply with nothing left queued."

    def voice_prompts(self):
        return [p for op, p in self.calls if op == "voice-chat"]


@pytest.fixture()
def conv_store(tmp_path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


def make_service(store, gen, chalk_store):
    svc = ConversationService(store, generate_fn=gen)
    svc._chalk_store_instance = chalk_store
    return svc


@pytest.fixture()
def chalk_on(monkeypatch):
    monkeypatch.setenv("ZENAF_CHALK_CARRIAGE", "1")
    yield


SCROLL_CONTEXT = {
    "sheet_type": "jynx_scroll",
    "entity_type": "project",
    "entity_id": "p1",
}


def test_maverick_turn_stores_drawing_and_strips_markup(
    conv_store, chalk_store, chalk_on
):
    gen = RecordedGen([VALID_TAIL])
    svc = make_service(conv_store, gen, chalk_store)
    result = svc.turn(USER, MAVERICK, "Show me the workshop.", conversation_id=CONVO,
                      context=SCROLL_CONTEXT)
    # The visitor's reply carries no chalk markup, in the response…
    assert "[[chalk]]" not in result.reply.reply
    assert "stamp |" not in result.reply.reply
    assert result.reply.reply.startswith("A workshop, then")
    # …nor in the persisted record.
    bodies = [m["body"] for m in conv_store.history(USER, CONVO, limit=10)]
    assert all("[[chalk]]" not in b for b in bodies)
    # The drawing is stored, retrievable, marks in order, keyed to
    # the conversation and its selected subject.
    drawings = chalk_store.list_drawings(USER)
    assert len(drawings) == 1
    drawing = drawings[0]
    assert drawing["conversation_id"] == CONVO
    assert drawing["subject_type"] == "project"
    assert drawing["subject_id"] == "p1"
    assert [m["type"] for m in drawing["marks"]] == ["stamp", "stamp", "stroke"]
    assert drawing["marks"][0]["stamp"] == "ring"
    # The instruction block rode the prompt while the flag is on.
    assert any("[[chalk]]" in p for p in gen.voice_prompts())


def test_flag_off_strips_but_never_persists_and_sends_no_block(
    conv_store, chalk_store, monkeypatch
):
    monkeypatch.delenv("ZENAF_CHALK_CARRIAGE", raising=False)
    gen = RecordedGen([VALID_TAIL])
    svc = make_service(conv_store, gen, chalk_store)
    result = svc.turn(USER, MAVERICK, "Show me the workshop.", conversation_id=CONVO,
                      context=SCROLL_CONTEXT)
    # Strip-always hygiene holds with the flag off…
    assert "[[chalk]]" not in result.reply.reply
    # …but nothing is persisted and no instruction block was sent.
    assert chalk_store.list_drawings(USER) == []
    assert all("[[chalk]]" not in p for p in gen.voice_prompts())


def test_malformed_chalk_turn_succeeds_with_no_drawing(
    conv_store, chalk_store, chalk_on
):
    bad = (
        "A reply that stands on its own.\n\n[[chalk]]\n"
        "drawing |\n"
        "stamp | nosuchstamp | cx=1 | cy=1 | w=10"
    )
    gen = RecordedGen([bad])
    svc = make_service(conv_store, gen, chalk_store)
    result = svc.turn(USER, MAVERICK, "Draw something.", conversation_id=CONVO)
    assert result.reply.reply == "A reply that stands on its own."
    assert chalk_store.list_drawings(USER) == []


def test_non_maverick_seat_never_carries_chalk(conv_store, chalk_store, chalk_on):
    gen = RecordedGen([VALID_TAIL])
    svc = make_service(conv_store, gen, chalk_store)
    result = svc.turn(USER, "conductor", "Show me the workshop.", conversation_id="weaver-convo")
    # No drawing, and the other seat's reply is byte-identical to
    # the generation — the seam does not run for other seats.
    assert result.reply.reply == VALID_TAIL
    assert chalk_store.list_drawings(USER) == []


def test_tail_only_generation_is_malformed(conv_store, chalk_store, chalk_on):
    gen = RecordedGen(["[[chalk]]\ndrawing |\nstamp | ring | cx=1 | cy=1 | w=10"])
    svc = make_service(conv_store, gen, chalk_store)
    result = svc.turn(USER, MAVERICK, "Draw.", conversation_id=CONVO)
    assert result.reply.reply == ""
    assert chalk_store.list_drawings(USER) == []


# ---------------------------------------------------------------------------
# Read route (handler-level, the archetype-routes pattern)
# ---------------------------------------------------------------------------


def test_route_serves_owner_drawings_and_isolates(monkeypatch, chalk_store):
    from api.routes import conversation_routes

    _record(chalk_store)
    monkeypatch.setattr(conversation_routes, "_chalk_store", lambda: chalk_store)

    mine = conversation_routes.list_chalk_drawings(current_user={"id": USER})
    assert len(mine["drawings"]) == 1
    item = mine["drawings"][0]
    assert item["space"] == {"w": 600, "h": 800}
    assert item["marks"][0]["stamp"] == "ring"
    assert item["subject_id"] == "p1"

    theirs = conversation_routes.list_chalk_drawings(current_user={"id": OTHER_USER})
    assert theirs == {"drawings": []}

    with pytest.raises(HTTPException) as exc:
        conversation_routes.list_chalk_drawings(current_user={})
    assert exc.value.status_code == 401


def test_route_filter_by_conversation(monkeypatch, chalk_store):
    from api.routes import conversation_routes

    _record(chalk_store)
    chalk_store.record_drawing(
        user_id=USER,
        conversation_id="jynx-scroll:task:t9",
        title="Elsewhere",
        space={"w": 600, "h": 800},
        marks=[{"type": "stamp", "stamp": "wave", "cx": 1, "cy": 2, "w": 3, "tier": 0.6}],
    )
    monkeypatch.setattr(conversation_routes, "_chalk_store", lambda: chalk_store)

    filtered = conversation_routes.list_chalk_drawings(
        conversation_id=CONVO, current_user={"id": USER}
    )
    assert [d["title"] for d in filtered["drawings"]] == ["A drawing"]
    # The parameter absent, the feed is the whole archive.
    everything = conversation_routes.list_chalk_drawings(current_user={"id": USER})
    assert len(everything["drawings"]) == 2
