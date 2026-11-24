"""V1 noting capture — parser, flag, and the ConversationService seam.

Every generation is a recorded output driven through the real
``ConversationService.turn`` with an injected ``generate_fn`` — zero
live model calls (the sketch-tail Stage 1B test discipline).

Pins:
- the trailer grammar (compliance, malformed, glued, foreign);
- strip-always while capture is live: no trailer text ever reaches
  the returned or persisted reply;
- capture OFF = byte-identical prompts, untouched replies, and zero
  store writes (the feed's absence is indistinguishable from feb2c9e);
- objection citations validated against the conversation's own
  messages: foreign / cross-conversation / non-visitor citations
  drop that note only.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai.conversation.noting import (
    NOTING_INSTRUCTION,
    capture_enabled,
    parse_noting_trailer,
)
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.narrative.noting import NotingCaptureWriter
from local_ai.narrative.store import NarrativeStore

USER = "u-noting"
CONVO = "noting-convo"
OTHER_CONVO = "other-convo"
CHAMPION = "champion"


# -- parser ---------------------------------------------------------------------


def test_parser_recognition_and_objection():
    text = (
        "A real reply.\n\n"
        "[[note:recognition|The visitor keeps agreeing while objecting]]\n"
        "[[note:objection|msg-123]]"
    )
    result = parse_noting_trailer(text)
    assert result.status == "ok"
    assert result.body == "A real reply."
    assert [(n.kind, n.statement, n.message_id) for n in result.notes] == [
        ("recognition", "The visitor keeps agreeing while objecting", ""),
        ("objection", "", "msg-123"),
    ]


def test_parser_no_marker_is_byte_identical():
    text = "Nothing to note.\n\nSecond paragraph [[not a note]].\n"
    result = parse_noting_trailer(text)
    assert result.status == "absent"
    assert result.body == text
    assert result.notes == []


def test_parser_glued_span_is_stripped_and_taken():
    text = "The answer stands. [[note:recognition|I notice the pattern]]"
    result = parse_noting_trailer(text)
    assert result.body == "The answer stands."
    assert [n.statement for n in result.notes] == ["I notice the pattern"]


def test_parser_statement_may_contain_pipes():
    result = parse_noting_trailer(
        "Reply.\n[[note:recognition|capacity | obligation — one tension]]"
    )
    assert [n.statement for n in result.notes] == [
        "capacity | obligation — one tension"
    ]
    assert result.body == "Reply."


@pytest.mark.parametrize(
    "tail",
    [
        "[[note:banana|whatever]]",  # foreign kind
        "[[note:recognition|]]",  # empty statement
        "[[note:recognition|   ]]",  # blank statement
        "[[note:objection|]]",  # empty citation
        "[[note:objection|not a msg id]]",  # bad citation shape
        "[[note:objection|msg id with spaces]]",
        "[[note:recognition|unterminated",
        "[[note:|x]]",
        "[[note:recognition]]",
    ],
)
def test_parser_malformed_degrades_to_no_note_and_never_leaks(tail):
    result = parse_noting_trailer(f"Visible reply.\n{tail}")
    assert result.notes == []
    assert result.body == "Visible reply."
    assert "[[note:" not in result.body


def test_parser_overlong_statement_drops():
    result = parse_noting_trailer(
        "Reply.\n[[note:recognition|" + "x" * 501 + "]]"
    )
    assert result.notes == []
    assert result.body == "Reply."


def test_parser_note_cap_strips_extras():
    lines = "\n".join(
        f"[[note:recognition|recognition {i}]]" for i in range(6)
    )
    result = parse_noting_trailer(f"Reply.\n{lines}")
    assert len(result.notes) == 4
    assert result.body == "Reply."


def test_parser_foreign_trailers_untouched():
    text = "Reply body.\n\n[[sketch]]\nbranch|Bench state|ground=reported|src=turn"
    result = parse_noting_trailer(text)
    assert result.status == "absent"
    assert result.body == text


def test_parser_note_only_reply_leaves_empty_body():
    result = parse_noting_trailer("[[note:recognition|Only a note]]")
    assert result.body == ""
    assert len(result.notes) == 1


# -- flag ------------------------------------------------------------------------


def test_capture_enabled_default_off_and_per_seat(monkeypatch):
    monkeypatch.delenv("ZENAF_NOTING_CAPTURE_SEATS", raising=False)
    assert capture_enabled(CHAMPION) is False
    monkeypatch.setenv("ZENAF_NOTING_CAPTURE_SEATS", "")
    assert capture_enabled(CHAMPION) is False
    monkeypatch.setenv("ZENAF_NOTING_CAPTURE_SEATS", "champion")
    assert capture_enabled(CHAMPION) is True
    assert capture_enabled("conductor") is False
    monkeypatch.setenv("ZENAF_NOTING_CAPTURE_SEATS", " champion , conductor ")
    assert capture_enabled(CHAMPION) is True
    assert capture_enabled("conductor") is True
    assert capture_enabled("guardian") is False


# -- service seam -----------------------------------------------------------------

class RecordedGen:
    """Fake generate_fn in the Stage 1B shape: replays recorded
    voice outputs, captures every voice prompt."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def __call__(self, prompt, **kw):
        if kw.get("operation") == "conversation-thread-summary":
            return "Rolling summary of the thread."
        self.prompts.append(prompt)
        if self.outputs:
            return self.outputs.pop(0)
        return "Recorded reply with nothing left queued."


class FakeSink:
    """Fellowship event sink double: returns an event object whose
    id is keyed by the turn's message id, as the real emitter's
    return is."""

    def __init__(self):
        self.event_ids: dict[str, str] = {}

    def __call__(self, **kw):
        message_id = kw["payload"]["message_id"]
        event_id = f"evt-{message_id}"
        self.event_ids[message_id] = event_id
        return SimpleNamespace(id=event_id)


@pytest.fixture()
def conv_store(tmp_path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


@pytest.fixture()
def narrative_store(tmp_path):
    return NarrativeStore(tmp_path / "narrative.db")


@pytest.fixture()
def sink():
    return FakeSink()


def make_writer(narrative_store, sink):
    return NotingCaptureWriter(
        narrative_store,
        event_resolver=lambda u, c, m: sink.event_ids.get(m),
    )


def make_service(conv_store, gen, sink, writer):
    return ConversationService(
        conv_store, generate_fn=gen, event_sink=sink, noting_writer=writer
    )


@pytest.fixture()
def capture_on(monkeypatch):
    monkeypatch.setenv("ZENAF_NOTING_CAPTURE_SEATS", "champion")


def test_capture_off_byte_identical_prompt_and_zero_writes(
    tmp_path, narrative_store, sink, monkeypatch
):
    """Flag absent vs flag naming another seat: identical prompts,
    identical replies, and the writer is never called — a recording
    double stands in for the store writer so 'zero writes' is
    observed, not assumed."""
    calls = []

    class RecordingWriter:
        def capture_turn(self, **kw):
            calls.append(kw)

    outputs = ["An answer with a trailer.\n\n[[note:recognition|Noted]]"]
    monkeypatch.delenv("ZENAF_NOTING_CAPTURE_SEATS", raising=False)
    gen_off = RecordedGen(outputs)
    svc_off = ConversationService(
        ConversationStore(db_path=tmp_path / "conv-off.db"),
        generate_fn=gen_off, event_sink=sink,
        noting_writer=RecordingWriter(),
    )
    result_off = svc_off.turn(USER, CHAMPION, "Hello.", conversation_id=CONVO)

    conv_store2 = ConversationStore(db_path=tmp_path / "conv-other.db")
    monkeypatch.setenv("ZENAF_NOTING_CAPTURE_SEATS", "guardian")
    gen_other = RecordedGen(outputs)
    svc_other = ConversationService(
        conv_store2, generate_fn=gen_other, event_sink=sink,
        noting_writer=RecordingWriter(),
    )
    result_other = svc_other.turn(
        USER, CHAMPION, "Hello.", conversation_id=OTHER_CONVO
    )

    assert gen_off.prompts == gen_other.prompts
    assert NOTING_INSTRUCTION not in gen_off.prompts[0]
    # Capture off: the parser never runs — a trailer-shaped tail is
    # the model's text and passes through untouched, exactly as at
    # feb2c9e (the feed does not exist on this path).
    assert result_off.reply.reply == outputs[0]
    assert result_other.reply.reply == outputs[0]
    assert calls == []
    assert narrative_store.held_notes_for(USER, include_expired=True) == []
    assert narrative_store.open_encounter_for(USER, CONVO, CHAMPION) is None


def test_capture_on_prompt_delta_is_exactly_the_instruction(
    conv_store, narrative_store, sink, capture_on, monkeypatch
):
    gen_on = RecordedGen(["Plain."])
    svc_on = make_service(
        conv_store, gen_on, sink, make_writer(narrative_store, sink)
    )
    svc_on.turn(USER, CHAMPION, "Hello.", conversation_id=CONVO)

    monkeypatch.delenv("ZENAF_NOTING_CAPTURE_SEATS", raising=False)
    gen_off = RecordedGen(["Plain."])
    svc_off = make_service(
        conv_store, gen_off, sink, make_writer(narrative_store, sink)
    )
    svc_off.turn(USER, CHAMPION, "Hello.", conversation_id=OTHER_CONVO)

    prompt_on, prompt_off = gen_on.prompts[0], gen_off.prompts[0]
    assert prompt_on.count(NOTING_INSTRUCTION) == 1
    assert prompt_on.replace("\n\n" + NOTING_INSTRUCTION, "", 1) == prompt_off


def test_capture_on_strips_trailer_everywhere(
    conv_store, narrative_store, sink, capture_on
):
    gen = RecordedGen(
        ["The real answer.\n\n[[note:recognition|A recognition formed]]"]
    )
    svc = make_service(conv_store, gen, sink, make_writer(narrative_store, sink))
    result = svc.turn(USER, CHAMPION, "Tell me.", conversation_id=CONVO)
    assert result.reply.reply == "The real answer."
    assert result.assistant_message["body"] == "The real answer."
    bodies = [
        m["body"] for m in conv_store.history(USER, CONVO) if m["role"] == "voice"
    ]
    assert bodies == ["The real answer."]
    held = narrative_store.held_notes_for(USER)
    assert [h["statement"] for h in held] == ["A recognition formed"]


def test_capture_on_malformed_trailer_stripped_no_note(
    conv_store, narrative_store, sink, capture_on
):
    gen = RecordedGen(["Answer.\n[[note:recognition|unterminated"])
    svc = make_service(conv_store, gen, sink, make_writer(narrative_store, sink))
    result = svc.turn(USER, CHAMPION, "Tell me.", conversation_id=CONVO)
    assert result.reply.reply == "Answer."
    assert "[[note:" not in result.assistant_message["body"]
    assert narrative_store.held_notes_for(USER, include_expired=True) == []


def test_capture_on_no_trailer_still_captures_verbatim_turn(
    conv_store, narrative_store, sink, capture_on
):
    """The arc exists where capture is live (§3.1): a note-free turn
    still opens the encounter and cites the visitor's turn as
    evidence — reference only, no note records."""
    gen = RecordedGen(["No notes this turn."])
    svc = make_service(conv_store, gen, sink, make_writer(narrative_store, sink))
    result = svc.turn(USER, CHAMPION, "Just talking.", conversation_id=CONVO)
    scope = narrative_store.open_encounter_for(USER, CONVO, CHAMPION)
    assert scope is not None
    assert scope["span_start_message_id"] == result.user_message["id"]
    evidence = narrative_store.evidence_for(USER, scope["thread_id"])
    assert [(e.ref_kind, e.evidence_kind) for e in evidence] == [
        ("event", "quote")
    ]
    assert narrative_store.held_notes_for(USER, include_expired=True) == []


def test_objection_citation_foreign_conversation_dropped(
    conv_store, narrative_store, sink, capture_on
):
    """A citation to another conversation's message — even the same
    user's — drops that note only; the recognition beside it lands."""
    gen = RecordedGen(["First.", "Second."])
    svc = make_service(conv_store, gen, sink, make_writer(narrative_store, sink))
    first = svc.turn(USER, CHAMPION, "Foreign message.", conversation_id=OTHER_CONVO)
    foreign_id = first.user_message["id"]

    gen2 = RecordedGen(
        [
            "Answer.\n"
            f"[[note:objection|{foreign_id}]]\n"
            "[[note:recognition|Still landed]]"
        ]
    )
    svc2 = make_service(conv_store, gen2, sink, make_writer(narrative_store, sink))
    svc2.turn(USER, CHAMPION, "I object to that framing.", conversation_id=CONVO)

    held = narrative_store.held_notes_for(USER)
    assert [h["kind"] for h in held] == ["recognition"]


def test_objection_citation_non_visitor_message_dropped(
    conv_store, narrative_store, sink, capture_on
):
    gen = RecordedGen(["A voice reply."])
    svc = make_service(conv_store, gen, sink, make_writer(narrative_store, sink))
    first = svc.turn(USER, CHAMPION, "Hello.", conversation_id=CONVO)
    voice_id = first.assistant_message["id"]

    gen2 = RecordedGen([f"Answer.\n[[note:objection|{voice_id}]]"])
    svc2 = make_service(conv_store, gen2, sink, make_writer(narrative_store, sink))
    svc2.turn(USER, CHAMPION, "That is not what I said.", conversation_id=CONVO)
    assert narrative_store.held_notes_for(USER, include_expired=True) == []


def test_objection_valid_citation_becomes_thread_evidence(
    conv_store, narrative_store, sink, capture_on
):
    gen = RecordedGen(["First answer.", "Second answer."])
    svc = make_service(conv_store, gen, sink, make_writer(narrative_store, sink))
    first = svc.turn(USER, CHAMPION, "I never agreed to that.", conversation_id=CONVO)
    cited_id = first.user_message["id"]

    gen2 = RecordedGen([f"Answer.\n[[note:objection|{cited_id}]]"])
    svc2 = make_service(conv_store, gen2, sink, make_writer(narrative_store, sink))
    svc2.turn(USER, CHAMPION, "You are putting words in my mouth.", conversation_id=CONVO)

    scope = narrative_store.open_encounter_for(USER, CONVO, CHAMPION)
    held = narrative_store.held_notes_for(USER)
    objections = [h for h in held if h["kind"] == "objection"]
    assert len(objections) == 1
    assert objections[0]["cited_message_id"] == cited_id
    assert objections[0]["evidence_ref_kind"] == "event"
    assert objections[0]["evidence_ref_id"] == f"evt-{cited_id}"
    evidence_ids = {
        e.ref_id for e in narrative_store.evidence_for(USER, scope["thread_id"])
    }
    assert f"evt-{cited_id}" in evidence_ids
