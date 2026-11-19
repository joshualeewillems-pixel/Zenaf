"""Bonsai Bench Stage 1B — integration fixtures (scope §2.2, design §10).

Every generation is a recorded output driven through the real
``ConversationService.turn`` with an injected ``generate_fn`` — zero
live model calls. Fixtures run in the scope's order: F9 first (it pins
Talk's current empty-body behaviour before any seam code is written
against it), then F2, F4, F5, F6, F7, F8, F10, F11, F12, F16, F19, F20.
"""

from __future__ import annotations

import pytest

import local_ai.conversation.service as service_mod
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore

USER = "u-sketch"
OTHER_USER = "u-other"
CONVO = "bench-convo"
OTHER_CONVO = "other-convo"
SKEPTIC = "skeptic"
CONDUCTOR = "conductor"


@pytest.fixture()
def conv_store(tmp_path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


class RecordedGen:
    """Fake generate_fn: replays recorded voice outputs in order and
    captures every prompt. Thread-summary calls (a different
    operation) are answered with a fixed string and never consume the
    recorded voice outputs."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []  # (operation, prompt)

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

    def summary_prompts(self):
        return [p for op, p in self.calls if op == "conversation-thread-summary"]


def make_service(store, gen):
    return ConversationService(store, generate_fn=gen)


def stored_messages(store, user=USER, convo=CONVO):
    return store.history(user, convo, limit=200)


def assistant_bodies(store, user=USER, convo=CONVO):
    return [m["body"] for m in stored_messages(store, user, convo) if m["role"] == "voice"]


@pytest.fixture()
def sketch_on(monkeypatch):
    monkeypatch.setenv("ZENAF_SKETCH_SHAPING", "1")
    yield


def tail(body, *lines):
    return body + "\n\n[[sketch]]\n" + "\n".join(lines)


def table_census(store):
    """Row counts for every table in the conversation store's DB."""
    conn = store._conn
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {
        t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables
    }


# ---------------------------------------------------------------------------
# F9 — degenerate generation (runs FIRST, per scope §2.2)
# ---------------------------------------------------------------------------


def test_f9_current_empty_body_behaviour_pinned(conv_store):
    """Pin, before any seam code exists: a wholly empty generation is
    stored as an empty assistant message and the turn returns normally.
    No emptiness check intervenes and no fallback line is invented.
    This is Talk's current behaviour at the 1B base; Stage 1 does not
    change it."""
    gen = RecordedGen([""])
    svc = make_service(conv_store, gen)
    result = svc.turn(
        USER, SKEPTIC, "I keep going back and forth on the contract.",
        conversation_id=CONVO,
    )
    assert result.reply.reply == ""
    assert result.assistant_message["body"] == ""
    assert assistant_bodies(conv_store) == [""]


def test_f9_tail_only_generation(conv_store, sketch_on):
    """A tail-only generation: the tail is dropped whole (the §4.3
    degenerate rule), zero instructions are returned, and the pinned
    empty-body behaviour above governs what remains — an empty
    assistant message, a normal return, no fallback invented."""
    gen = RecordedGen(
        ["[[sketch]]\nbranch | the shape of the thing | ground=assumed | src=turn"]
    )
    svc = make_service(conv_store, gen)
    result = svc.turn(
        USER, SKEPTIC, "I keep going back and forth on the contract.",
        conversation_id=CONVO,
    )
    assert result.reply.reply == ""
    assert result.assistant_message["body"] == ""
    assert assistant_bodies(conv_store) == [""]
    carriage = result.sketch_instructions
    assert carriage is None or carriage["instructions"] == []


def test_f9_tail_only_generation_flag_off(conv_store, monkeypatch):
    """The degenerate strip is hygiene, not a feature: with the flag
    off the tail still never persists, and nothing is carried."""
    monkeypatch.delenv("ZENAF_SKETCH_SHAPING", raising=False)
    gen = RecordedGen(
        ["[[sketch]]\nbranch | the shape of the thing | ground=assumed | src=turn"]
    )
    svc = make_service(conv_store, gen)
    result = svc.turn(
        USER, SKEPTIC, "I keep going back and forth on the contract.",
        conversation_id=CONVO,
    )
    assert result.assistant_message["body"] == ""
    assert result.sketch_instructions is None


# ---------------------------------------------------------------------------
# F2 — absent tail (A3: absence is free)
# ---------------------------------------------------------------------------


def test_f2_absent_tail_byte_identical(conv_store, sketch_on):
    reply_text = "That tension is real, and it is worth looking at slowly."
    gen = RecordedGen([reply_text])
    svc = make_service(conv_store, gen)
    result = svc.turn(
        USER, SKEPTIC, "I keep going back and forth on the contract.",
        conversation_id=CONVO,
    )
    assert result.reply.reply == reply_text
    assert result.assistant_message["body"] == reply_text
    assert assistant_bodies(conv_store) == [reply_text]
    assert result.sketch_instructions is None


# ---------------------------------------------------------------------------
# F4 — reply protection at the seam (A2)
# ---------------------------------------------------------------------------


def test_f4_reply_protection_at_the_seam(conv_store, sketch_on):
    body = "Here is the reply, complete in itself."
    gen = RecordedGen([tail(body, "wobble | e1 | hard")])
    svc = make_service(conv_store, gen)
    result = svc.turn(
        USER, SKEPTIC, "I keep going back and forth on the contract.",
        conversation_id=CONVO,
    )
    # The persisted and returned text is the body exactly; the garbage
    # tail yields zero instructions; no retry was issued (A6).
    assert result.reply.reply == body
    assert result.assistant_message["body"] == body
    assert assistant_bodies(conv_store) == [body]
    carriage = result.sketch_instructions
    assert carriage is not None and carriage["instructions"] == []
    assert len(gen.voice_prompts()) == 1


# ---------------------------------------------------------------------------
# F5 — citation validation set (§5.1–5.2)
# ---------------------------------------------------------------------------


def test_f5_citation_validation_set(conv_store, sketch_on):
    gen = RecordedGen(
        [
            "A plain opening reply.",
            "An other-conversation reply.",
            "Someone else's reply.",
        ]
    )
    svc = make_service(conv_store, gen)
    seed = svc.turn(USER, SKEPTIC, "The money side is the part I keep circling.", conversation_id=CONVO)
    user_msg_id = seed.user_message["id"]
    voice_msg_id = seed.assistant_message["id"]
    other_convo = svc.turn(USER, SKEPTIC, "A different conversation entirely.", conversation_id=OTHER_CONVO)
    other_convo_user_id = other_convo.user_message["id"]
    foreign = svc.turn(OTHER_USER, SKEPTIC, "Not your conversation.", conversation_id=CONVO)
    foreign_user_id = foreign.user_message["id"]

    # The case outputs cite the seeded ids, so they are queued only
    # now that those ids exist (the fake consumes strictly in order).
    gen.outputs.extend(
        [
            tail("Case one.", "branch | said here today | ground=reported | src=turn"),
            tail("Case two.", f"branch | said earlier | ground=reported | src=msg:{user_msg_id}"),
            tail("Case three.", f"branch | my own words | ground=reported | src=msg:{voice_msg_id}"),
            tail("Case four.", f"branch | documented in chat | ground=documented | src=msg:{user_msg_id}"),
            tail("Case five.", "branch | a phantom record | ground=assumed | src=rec:missing-record"),
            tail("Case six.", "branch | a documented claim | ground=documented | src=rec:foreign-record-1"),
            tail("Case seven.", f"branch | from another thread | ground=assumed | src=msg:{other_convo_user_id}"),
            tail("Case eight.", f"branch | from another person | ground=assumed | src=msg:{foreign_user_id}"),
        ]
    )

    def run_case(message):
        result = svc.turn(USER, SKEPTIC, message, conversation_id=CONVO)
        carriage = result.sketch_instructions
        assert carriage is not None
        return carriage["instructions"]

    # 1. src=turn grounding "reported" validates.
    kept = run_case("Go on.")
    assert [i["src"] for i in kept] == ["turn"]
    # 2. src=msg: of a user message in this conversation validates.
    kept = run_case("Go on.")
    assert [i["src"] for i in kept] == [f"msg:{user_msg_id}"]
    # 3. src=msg: of a voice message cannot ground "reported".
    assert run_case("Go on.") == []
    # 4. ground=documented with a conversation source drops.
    assert run_case("Go on.") == []
    # 5. src=rec: unknown drops (no supply channel in v1).
    assert run_case("Go on.") == []
    # 6. src=rec: of another user's record drops identically — the
    # failure is indistinguishable from a typo; nothing leaks.
    assert run_case("Go on.") == []
    # 7. src=msg: of a message in another conversation drops.
    assert run_case("Go on.") == []
    # 8. src=msg: of another user's message drops.
    assert run_case("Go on.") == []
    # Every case's body persisted stripped and intact.
    bodies = assistant_bodies(conv_store)
    assert bodies[1:] == [f"Case {n}." for n in
                          ["one", "two", "three", "four", "five", "six", "seven", "eight"]]


# ---------------------------------------------------------------------------
# F6 — per-element isolation (A5)
# ---------------------------------------------------------------------------


def test_f6_per_element_isolation(conv_store, sketch_on):
    gen = RecordedGen(
        [
            tail(
                "Two of these three stand.",
                "branch | the money side | ground=assumed | src=turn",
                "branch | a phantom record | ground=assumed | src=rec:not-there",
                "gap | what would change my mind | basis=turn",
            )
        ]
    )
    svc = make_service(conv_store, gen)
    result = svc.turn(
        USER, SKEPTIC, "The money side is the part I keep circling.",
        conversation_id=CONVO,
    )
    instructions = result.sketch_instructions["instructions"]
    assert [i["verb"] for i in instructions] == ["branch", "gap"]
    assert instructions[0]["label"] == "the money side"
    assert instructions[1]["label"] == "what would change my mind"


# ---------------------------------------------------------------------------
# F7 — correction sequence (Guarantee 2 as a test)
# ---------------------------------------------------------------------------


def test_f7_correction_sequence(conv_store, sketch_on):
    gen = RecordedGen(
        [
            "An ordinary opening.",
            tail(
                "Let us look at the shape of it.",
                "branch | the money side | ground=reported | src=turn",
                "branch | what would change my mind | ground=assumed | src=turn",
            ),
            tail(
                "You are right to push on that.",
                "revise | e1 | label=the money side, in your words",
                "remove | e2",
            ),
        ]
    )
    svc = make_service(conv_store, gen)
    # Warm-up turn: ordinary Talk bookkeeping (thread_state row, the
    # subject snapshot) establishes itself here, so the census below
    # measures the shaping sequence alone.
    svc.turn(USER, SKEPTIC, "I keep going back and forth on the contract.", conversation_id=CONVO)
    census_before = table_census(conv_store)

    r1 = svc.turn(
        USER, SKEPTIC, "The money side is what I actually said.",
        conversation_id=CONVO,
    )
    ins1 = r1.sketch_instructions["instructions"]
    assert [i["verb"] for i in ins1] == ["branch", "branch"]

    # Simulated client application, on the §1A.1 application's
    # semantics: handles are assigned in creation order.
    sketch = {}
    for n, ins in enumerate(ins1, start=1):
        sketch[f"e{n}"] = {"label": ins["label"], "ground": ins["ground"]}
    assert list(sketch) == ["e1", "e2"]

    summary = (
        'e1 branch "the money side" (reported) · '
        'e2 branch "what would change my mind" (assumed)'
    )
    r2 = svc.turn(
        USER, SKEPTIC, "That branch is wrong — it is not fear, it is grief.",
        conversation_id=CONVO, context={"sketch_summary": summary},
    )
    # The client-derived summary reached the prompt: the continuity
    # channel the correction addresses through.
    assert summary in gen.voice_prompts()[-1]
    ins2 = r2.sketch_instructions["instructions"]
    assert [i["verb"] for i in ins2] == ["revise", "remove"]

    # The client applies the correction exactly.
    for ins in ins2:
        if ins["verb"] == "revise":
            sketch[ins["handle"]]["label"] = ins["label"]
        elif ins["verb"] == "remove":
            del sketch[ins["handle"]]
    assert sketch == {
        "e1": {"label": "the money side, in your words", "ground": "reported"}
    }

    # Guarantee 2, as numbers: across the whole create → correct
    # sequence, no table in the store gained or lost a row except
    # messages, which grew by exactly the two turns' four rows.
    census_after = table_census(conv_store)
    assert set(census_after) == set(census_before)
    for table, count in census_before.items():
        expected = count + 4 if table == "messages" else count
        assert census_after[table] == expected, (
            f"{table}: {count} before, {census_after[table]} after"
        )


# ---------------------------------------------------------------------------
# F8 — strip on all paths (A1)
# ---------------------------------------------------------------------------


def test_f8_strip_on_all_paths(conv_store, sketch_on, monkeypatch):
    monkeypatch.setattr(service_mod, "SUMMARY_EVERY_N_TURNS", 1)
    body = "The reply that must survive everywhere."
    tail_line = "branch | the money side | ground=reported | src=turn"
    gen = RecordedGen([tail(body, tail_line), "A follow-up reply."])
    svc = make_service(conv_store, gen)
    r1 = svc.turn(USER, SKEPTIC, "First message.", conversation_id=CONVO)
    # Persisted body and response body are tail-free.
    assert r1.assistant_message["body"] == body
    assert r1.reply.reply == body
    # The summary-refresh input (forced to run this turn) is built
    # from stored bodies and is tail-free.
    summaries = gen.summary_prompts()
    assert summaries, "the summary refresh should have run"
    for prompt in summaries:
        assert "[[sketch]]" not in prompt
        assert tail_line not in prompt
    # The next turn's rendered history carries the body, not the tail.
    svc.turn(USER, SKEPTIC, "Second message.", conversation_id=CONVO)
    prompt2 = gen.voice_prompts()[-1]
    assert body in prompt2
    assert tail_line not in prompt2


# ---------------------------------------------------------------------------
# F10 — summary channel (§2.6)
# ---------------------------------------------------------------------------


def test_f10_summary_channel_valid(conv_store, sketch_on):
    summary = 'e1 branch "the money side" (reported)'
    gen = RecordedGen(["A reply."])
    svc = make_service(conv_store, gen)
    svc.turn(
        USER, SKEPTIC, "Go on.", conversation_id=CONVO,
        context={"sheet_type": "tree", "sketch_summary": summary},
    )
    prompt = gen.voice_prompts()[-1]
    assert "Live context:" in prompt
    assert "the 'tree' sheet open" in prompt
    assert "Current sketch (provisional, from the bench" in prompt
    assert summary in prompt
    # The field is absent from every persisted context_json.
    for m in stored_messages(conv_store):
        assert "sketch_summary" not in (m.get("context") or {})


def test_f10_summary_clipped_factual_line_prioritized(conv_store, sketch_on):
    summary = 'e1 branch "' + "x" * 260 + '" (reported)'
    gen = RecordedGen(["A reply."])
    svc = make_service(conv_store, gen)
    svc.turn(
        USER, SKEPTIC, "Go on.", conversation_id=CONVO,
        context={"sheet_type": "tree", "sketch_summary": summary},
    )
    prompt = gen.voice_prompts()[-1]
    line = [l for l in prompt.split("\n") if l.startswith("Live context:")][0]
    # The factual line leads and survives whole; the combined hint is
    # clipped at the 300-char cap, so the summary enters but is cut.
    assert line.startswith(
        "Live context: the user currently has the 'tree' sheet open."
    )
    assert len(line) <= len("Live context: ") + 300
    assert "Current sketch (provisional" in line
    assert summary not in line


@pytest.mark.parametrize(
    "bad",
    [
        "line one\nline two",
        "has a [[ marker in it",
        "x" * 301,
    ],
)
def test_f10_invalid_summaries_ignored(conv_store, sketch_on, bad):
    gen = RecordedGen(["A reply."])
    svc = make_service(conv_store, gen)
    result = svc.turn(
        USER, SKEPTIC, "Go on.", conversation_id=CONVO,
        context={"sketch_summary": bad},
    )
    # The turn succeeds; the invalid summary is simply not hinted.
    assert result.reply.reply == "A reply."
    prompt = gen.voice_prompts()[-1]
    assert "Current sketch (provisional" not in prompt
    for m in stored_messages(conv_store):
        assert "sketch_summary" not in (m.get("context") or {})


def test_f10_summary_scrubbed_for_non_skeptic(conv_store, sketch_on):
    summary = 'e1 branch "the money side" (reported)'
    gen = RecordedGen(["A reply."])
    svc = make_service(conv_store, gen)
    svc.turn(
        USER, CONDUCTOR, "Go on.", conversation_id=CONVO,
        context={"sketch_summary": summary},
    )
    prompt = gen.voice_prompts()[-1]
    assert summary not in prompt
    assert "Current sketch (provisional" not in prompt
    for m in stored_messages(conv_store):
        assert "sketch_summary" not in (m.get("context") or {})


# ---------------------------------------------------------------------------
# F11 — non-skeptic inertness
# ---------------------------------------------------------------------------


def test_f11_non_skeptic_inertness(conv_store, sketch_on):
    text = tail(
        "A conductor reply, complete in itself.",
        "branch | not a bench | ground=assumed | src=turn",
    )
    gen = RecordedGen([text])
    svc = make_service(conv_store, gen)
    result = svc.turn(USER, CONDUCTOR, "Go on.", conversation_id=CONVO)
    # No parse, no strip, no carriage: behaviour identical to today,
    # the block standing in the reply exactly as generated.
    assert result.reply.reply == text
    assert result.assistant_message["body"] == text
    assert result.sketch_instructions is None


# ---------------------------------------------------------------------------
# F12 — established untouched
# ---------------------------------------------------------------------------


def test_f12_established_untouched(conv_store, sketch_on, tmp_path):
    import hashlib
    import sqlite3

    from local_ai.narrative import NarrativeStore, SourceRef

    npath = tmp_path / "narrative.db"
    nstore = NarrativeStore(db_path=npath)
    nstore.create_thread(
        USER,
        title="The winter contract",
        evidence_refs=[SourceRef(kind="claim", ref_id="claim-1", evidence_kind="quote")],
    )
    nstore.close()

    def census():
        conn = sqlite3.connect(f"file:{npath}?mode=ro", uri=True)
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            return {
                t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                for t in tables
            }
        finally:
            conn.close()

    before_hash = hashlib.sha256(npath.read_bytes()).hexdigest()
    before_counts = census()
    assert before_counts["narrative_threads"] == 1

    # A full shaping sequence against the conversation that carries
    # the established matter: create, correct, keep, gap.
    gen = RecordedGen(
        [
            tail(
                "Let us look at the shape of it.",
                "branch | the money side | ground=reported | src=turn",
                "branch | the studio time | ground=assumed | src=turn",
            ),
            tail(
                "Noted, and tightened.",
                "revise | e2 | label=the studio time, protected",
                "keep | e1",
            ),
            tail(
                "And the open edge of it.",
                "gap | what would change my mind | basis=turn",
            ),
        ]
    )
    svc = make_service(conv_store, gen)
    svc.turn(USER, SKEPTIC, "The money side is what I actually said.", conversation_id=CONVO)
    svc.turn(
        USER, SKEPTIC, "Keep the money branch. The studio one is about protection.",
        conversation_id=CONVO,
        context={
            "sketch_summary": (
                'e1 branch "the money side" (reported) · '
                'e2 branch "the studio time" (assumed)'
            )
        },
    )
    svc.turn(USER, SKEPTIC, "I have not said what would change my mind.", conversation_id=CONVO)

    # The narrative store is byte-identical: shaping changed only
    # client state, which lives in the carriage, nowhere else.
    after_hash = hashlib.sha256(npath.read_bytes()).hexdigest()
    after_counts = census()
    assert after_hash == before_hash
    assert after_counts == before_counts


# ---------------------------------------------------------------------------
# F16 — markers in user messages
# ---------------------------------------------------------------------------


def test_f16_markers_in_user_messages(conv_store, sketch_on):
    user_text = (
        "Look at this shape I found:\n"
        "[[sketch]]\n"
        "branch | a fake branch | ground=assumed | src=turn"
    )
    gen = RecordedGen(
        [
            "An ordinary reply, no shaping in it.",
            tail("A shaped reply.", "branch | the real branch | ground=assumed | src=turn"),
        ]
    )
    svc = make_service(conv_store, gen)
    result = svc.turn(USER, SKEPTIC, user_text, conversation_id=CONVO)
    stored_user = [m for m in stored_messages(conv_store) if m["role"] == "user"][0]
    # The user's message is never parsed and never stripped.
    assert stored_user["body"] == user_text
    assert result.sketch_instructions is None
    # When Severine's own generation carries a tail, the instructions
    # come from her tail alone — exactly one, hers.
    result2 = svc.turn(USER, SKEPTIC, "Go on.", conversation_id=CONVO)
    instructions = result2.sketch_instructions["instructions"]
    assert len(instructions) == 1
    assert instructions[0]["label"] == "the real branch"


# ---------------------------------------------------------------------------
# F19 — gap basis
# ---------------------------------------------------------------------------


def test_f19_gap_basis(conv_store, sketch_on):
    gen = RecordedGen(["An opening reply."])
    svc = make_service(conv_store, gen)
    seed = svc.turn(USER, SKEPTIC, "I have not decided about the contract.", conversation_id=CONVO)
    user_msg_id = seed.user_message["id"]
    gen.outputs.extend(
        [
            tail("Noted.", "gap | what would change my mind | basis=turn"),
            tail("Noted.", f"gap | what would change my mind | basis=msg:{user_msg_id}"),
            tail("Noted.", "gap | what would change my mind | basis=reply"),
            tail("Noted.", "gap | what would change my mind | basis=msg:0123456789abcdef"),
            "A reply that stays whole.\n\n[[sketch]]\ngap | what would change my mind",
        ]
    )

    def run_gap(message):
        result = svc.turn(USER, SKEPTIC, message, conversation_id=CONVO)
        return result.sketch_instructions["instructions"]

    # basis=turn renders.
    gaps = run_gap("Go on.")
    assert [g["basis"] for g in gaps] == ["turn"]
    # basis=msg: of an existing message renders.
    gaps = run_gap("Go on.")
    assert [g["basis"] for g in gaps] == [f"msg:{user_msg_id}"]
    # basis=reply renders (its binding is F20's subject).
    gaps = run_gap("Go on.")
    assert [g["basis"] for g in gaps] == ["reply"]
    # basis=msg: of a nonexistent message drops at validation.
    assert run_gap("Go on.") == []
    # A gap with no basis at all: the tail fails whole, the body is
    # intact, and the gap never renders.
    result = svc.turn(USER, SKEPTIC, "Go on.", conversation_id=CONVO)
    assert result.assistant_message["body"] == "A reply that stays whole."
    assert result.sketch_instructions["instructions"] == []


# ---------------------------------------------------------------------------
# F20 — reply-reference timing (scope §3)
# ---------------------------------------------------------------------------


def test_f20_reply_reference_timing(conv_store, sketch_on):
    gen = RecordedGen(
        [
            tail(
                "I notice you have not said what would change your mind.",
                "gap | what would change my mind | basis=reply",
            ),
            tail(
                "Another reply.",
                "branch | a forward claim | ground=assumed | src=msg:0123456789abcdef",
            ),
        ]
    )
    svc = make_service(conv_store, gen)
    r1 = svc.turn(USER, SKEPTIC, "I have not decided.", conversation_id=CONVO)
    carriage = r1.sketch_instructions
    assert carriage is not None
    # basis=reply validated at the seam, where no reply identifier
    # existed: the element stands, its basis still symbolic.
    gaps = [i for i in carriage["instructions"] if i["verb"] == "gap"]
    assert len(gaps) == 1 and gaps[0]["basis"] == "reply"
    # The binding is deferred to carriage time: the turn pair names
    # the persisted messages, the reply's real id among them.
    assert carriage["turn_pair"]["user_message_id"] == r1.user_message["id"]
    assert carriage["turn_pair"]["reply_message_id"] == r1.assistant_message["id"]
    # Inspection resolution through the pair lands on the persisted
    # reply itself.
    found = conv_store.get_message(
        USER, CONVO, carriage["turn_pair"]["reply_message_id"]
    )
    assert found is not None and found["body"] == r1.assistant_message["body"]
    # A literal forward reference — citing an identifier that does
    # not exist when the seam validates — fails and drops its
    # element. No forward reference is possible.
    r2 = svc.turn(USER, SKEPTIC, "Go on.", conversation_id=CONVO)
    assert r2.sketch_instructions["instructions"] == []


# ---------------------------------------------------------------------------
# Rollout flag and instruction block (scope §2.3)
# ---------------------------------------------------------------------------


def test_flag_defaults_off_in_every_environment(monkeypatch):
    monkeypatch.delenv("ZENAF_SKETCH_SHAPING", raising=False)
    assert service_mod.sketch_shaping_enabled() is False
    # The verdict reversal: even a staging-shaped environment does
    # not default the flag on.
    monkeypatch.setenv("FLY_APP_NAME", "zenaf-staging")
    monkeypatch.setenv("ZENAF_PROD", "1")
    assert service_mod.sketch_shaping_enabled() is False
    monkeypatch.setenv("ZENAF_SKETCH_SHAPING", "1")
    assert service_mod.sketch_shaping_enabled() is True
    monkeypatch.setenv("ZENAF_SKETCH_SHAPING", "off")
    assert service_mod.sketch_shaping_enabled() is False


def test_strip_always_with_flag_off(conv_store, monkeypatch):
    monkeypatch.delenv("ZENAF_SKETCH_SHAPING", raising=False)
    body = "A reply that must still be protected."
    gen = RecordedGen(
        [tail(body, "branch | the money side | ground=reported | src=turn")]
    )
    svc = make_service(conv_store, gen)
    result = svc.turn(USER, SKEPTIC, "Go on.", conversation_id=CONVO)
    # Hygiene holds with the flag off; nothing is returned for
    # application; the instruction block was never sent.
    assert result.assistant_message["body"] == body
    assert result.sketch_instructions is None
    assert "bookkeeping tail" not in gen.voice_prompts()[-1]


def test_instruction_block_sent_only_when_on_and_skeptic(conv_store, sketch_on):
    gen = RecordedGen(["Reply one.", "Reply two."])
    svc = make_service(conv_store, gen)
    svc.turn(USER, SKEPTIC, "Go on.", conversation_id=CONVO)
    assert "bookkeeping tail" in gen.voice_prompts()[-1]
    svc.turn(USER, CONDUCTOR, "Go on.", conversation_id=CONVO)
    assert "bookkeeping tail" not in gen.voice_prompts()[-1]


def test_instruction_block_size_bound():
    # The design's scale is ~700 chars for the complete block; the
    # full nine-verb grammar lands at 798 (recorded in the results
    # note). This bound keeps the block from growing silently.
    assert len(service_mod._SKETCH_SHAPING_BLOCK) <= 800


# ---------------------------------------------------------------------------
# Route carriage (scope §2.1 S5): the field reaches the HTTP response
# ---------------------------------------------------------------------------


def test_route_carriage_and_summary_schema(conv_store, sketch_on, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.routes.conversation_routes as conv_routes
    from api.routes.auth_routes import get_current_user

    gen = RecordedGen(
        [tail("A shaped reply.", "branch | the money side | ground=reported | src=turn")]
    )
    svc = make_service(conv_store, gen)
    monkeypatch.setattr(conv_routes, "_service", lambda: svc)
    app = FastAPI()
    app.include_router(conv_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": USER}
    client = TestClient(app)
    # A 301-char summary rides along: it must be ignored by the
    # service's form validation, never a 422 (F10 at the route).
    r = client.post(
        "/conversation/turn",
        json={
            "archetype_id": "skeptic",
            "message": "Go on.",
            "conversation_id": CONVO,
            "context": {"sketch_summary": "x" * 301},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "A shaped reply."
    carriage = body["sketch_instructions"]
    assert carriage["instructions"][0]["label"] == "the money side"
    assert carriage["turn_pair"]["reply_message_id"] == body["message_id"]
    assert carriage["turn_pair"]["user_message_id"]
