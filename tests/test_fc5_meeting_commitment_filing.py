"""FC5 meeting commitment filing (2026-11-12).

The hook's real body (design §2.4) + the three founder integrity
corrections (Nov 11 ruling): bounded deterministic affirmation
matching, storage-level idempotency on the offer's stable id, and
provenance from authenticated server-side context.

No model calls anywhere here: the hook is deterministic parse +
matcher, and the meeting-path tests run against a stubbed
generate_fn. The follow-through database is isolated per test
(monkeypatched DEFAULT_DB_PATH for the turn-path tests; an explicit
temp-DB service for the direct-hook tests).
"""

from __future__ import annotations

import dataclasses
import sqlite3
import threading

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.encounter import (
    EncounterRuntime,
    EncounterState,
    build_ambassador_k1_definition,
    build_champion_k1_definition,
    build_guardian_k1_definition,
    build_maverick_k1_definition,
    build_mentor_k1_definition,
    build_skeptic_k1_definition,
    build_weaver_k1_definition,
    match_affirmation,
    parse_commitment_offer,
)
from local_ai.conversation.meeting import (
    MeetingService,
    MeetingStore,
)
from local_ai.conversation.reply import _EXTRA_INSTRUCTIONS_CAP as CAP
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT
from local_ai.followthrough.service import FollowthroughService
from local_ai.followthrough.store import FollowthroughStore
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve

UID = "fc5-test-user"
CID = "meeting-conductor-1"
LABEL = "non-complicity at home"


def _offer_body(label: str = LABEL) -> str:
    return (
        "Want me to lock that in as a commitment here?\n\n"
        "```commitment-offer\n"
        f"label: {label}\n"
        "```\n"
    )


def _voice_msg(msg_id: str, body: str) -> dict:
    return {
        "id": msg_id,
        "user_id": UID,
        "conversation_id": CID,
        "archetype_id": "conductor",
        "role": "voice",
        "body": body,
        "mode": "base",
        "context": {"meeting": True},
        "created_at": "2026-11-12T00:00:00+00:00",
    }


class _Host:
    """Minimal host: records what the runtime asks of it."""

    def __init__(self, last_voice: dict | None = None) -> None:
        self._last = last_voice
        self.said: list[str] = []
        self.generated: list[str] = []
        self.closed: list[str] = []

    def last_voice_message(self) -> dict | None:
        return self._last

    def generate(self, frame: str) -> str:
        self.generated.append(frame)
        return ""

    def say(self, body: str) -> None:
        self.said.append(body)

    def store_impression(self, claim: str, strands) -> None:
        pass

    def store_response(self, text: str) -> None:
        pass

    def store_dimensions(self, a: str, b: str) -> None:
        pass

    def close(self, wrap_line: str) -> None:
        self.closed.append(wrap_line)


def _runtime() -> EncounterRuntime:
    return EncounterRuntime(
        build_champion_k1_definition(MT.CHAMPION_FIRST_MEETING)
    )


def _ft_service(tmp_path, name: str = "ft.db") -> FollowthroughService:
    return FollowthroughService(FollowthroughStore(tmp_path / name))


def _file(host, state, message, service) -> None:
    _runtime()._file_accepted_offer(host, state, message, service=service)


# ---------------------------------------------------------------------------
# T-F5-1 — affirmation matcher table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message, expected",
    [
        ("yes", "affirm"),
        ("Yes", "affirm"),
        ("yes please", "affirm"),
        ("Yes, please do", "affirm"),
        ("please do", "affirm"),
        ("lock it in", "affirm"),
        ("Lock it in.", "affirm"),
        ("file it", "affirm"),
        ("record it", "affirm"),
        ("do it", "affirm"),
        ("go ahead", "affirm"),
        ("sounds good", "affirm"),
        ("let's do it", "affirm"),
        ("lets do it", "affirm"),
        ("yes, non-complicity at home", "affirm"),
        ("Yes, lock it in", "affirm"),
        ("no", "deny"),
        ("No.", "deny"),
        ("not yet", "deny"),
        ("yes, but not yet", "deny"),
        ("don't file", "deny"),
        ("dont file", "deny"),
        ("don't", "deny"),
        ("wait", "deny"),
        ("hold on", "deny"),
        ("later", "deny"),
        ("maybe", "deny"),
        ("not now", "deny"),
        ("no thanks", "deny"),
        ("not that", "deny"),
        ("hmm", "ambiguous"),
        ("I guess", "ambiguous"),
        ("we'll see", "ambiguous"),
        ("what do you mean?", "ambiguous"),
        ("", "ambiguous"),
        ("   ", "ambiguous"),
        ("I know what you mean", "ambiguous"),
        ("Yesterday I decided to quit", "ambiguous"),
        ("nothing to add", "ambiguous"),
    ],
)
def test_f5_1_affirmation_matcher_table(message, expected):
    """Denylist first, allowlist exact/starts-with on the listed
    forms only, everything else ambiguous. Token boundaries, not
    substrings: "know" does not contain "no", "yesterday" does not
    start with "yes", "nothing" does not contain "not"."""
    assert match_affirmation(message) == expected


# ---------------------------------------------------------------------------
# T-F5-2 — block parser
# ---------------------------------------------------------------------------


def test_f5_2_block_parser():
    assert parse_commitment_offer(_offer_body()) == LABEL
    assert parse_commitment_offer("Want me to lock that in?") is None
    assert parse_commitment_offer("```commitment-offer\nlabel: \n```") is None
    assert parse_commitment_offer("```commitment-offer\nno label here\n```") is None
    assert parse_commitment_offer(
        "```commitment-offer\nlabel: " + "x" * 201 + "\n```"
    ) is None
    assert parse_commitment_offer(
        "```commitment-offer\nlabel: " + "x" * 200 + "\n```"
    ) == "x" * 200
    # Two blocks: the first wins; the second is ignored, not a
    # second filing.
    two = _offer_body("first") + "\n" + _offer_body("second")
    assert parse_commitment_offer(two) == "first"
    # The label key is the field name; surrounding prose is fine.
    assert parse_commitment_offer(
        "Sure —\n```commitment-offer\nlabel: walk the dog\n```\nAnything else?"
    ) == "walk the dog"


# ---------------------------------------------------------------------------
# T-F5-3 — dedup (state + storage)
# ---------------------------------------------------------------------------


def test_f5_3_dedup_same_offer_files_once(tmp_path):
    service = _ft_service(tmp_path)
    host = _Host(_voice_msg("msg-offer-1", _offer_body()))
    state = EncounterState()
    _file(host, state, "Yes, lock it in", service)
    _file(host, state, "Yes, lock it in", service)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    assert len(state.confirmed_writes) == 1
    assert state.confirmed_writes[0]["id"] == rows[0]["id"]
    assert state.confirmed_writes[0]["status"] == "recorded"


def test_f5_3_dedup_different_offers_file_each(tmp_path):
    service = _ft_service(tmp_path)
    state = EncounterState()
    _file(_Host(_voice_msg("msg-offer-1", _offer_body("first"))),
          state, "Yes", service)
    _file(_Host(_voice_msg("msg-offer-2", _offer_body("second"))),
          state, "Yes", service)
    rows = service.list_commitments(UID)
    assert len(rows) == 2
    assert {r["text"] for r in rows} == {"first", "second"}
    assert len(state.confirmed_writes) == 2


def test_f5_3_storage_idempotency_survives_lost_confirmation(tmp_path):
    """Correction 2: the encounter-state persistence fails after the
    commitments write commits (the Confirmation never reaches
    state_json). A retry must return the already-committed row —
    same id — not file a second row."""
    service = _ft_service(tmp_path)
    host = _Host(_voice_msg("msg-offer-1", _offer_body()))
    state = EncounterState()
    _file(host, state, "Yes, lock it in", service)
    assert len(service.list_commitments(UID)) == 1
    first_id = state.confirmed_writes[0]["id"]
    # Simulate the lost persistence: the row exists, the state
    # has no record of it.
    state.confirmed_writes.clear()
    _file(host, state, "Yes, lock it in", service)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    assert rows[0]["id"] == first_id
    assert len(state.confirmed_writes) == 1
    assert state.confirmed_writes[0]["id"] == first_id


def test_f5_3_storage_idempotency_second_writer_same_offer(tmp_path):
    """A second store handle (another process/connection) filing
    the same offer also returns the existing row — the UNIQUE
    index, not the in-memory state, is the backstop."""
    service_a = _ft_service(tmp_path)
    service_b = FollowthroughService(FollowthroughStore(tmp_path / "ft.db"))
    host = _Host(_voice_msg("msg-offer-1", _offer_body()))
    state = EncounterState()
    _file(host, state, "Yes", service_a)
    # The state record is lost (a second process would never see it
    # anyway) — only the store's UNIQUE index stands between the
    # retry and a duplicate row.
    state.confirmed_writes.clear()
    _file(host, state, "Yes", service_b)
    assert len(service_a.list_commitments(UID)) == 1
    assert len(state.confirmed_writes) == 1
    service_b.store.close()


# ---------------------------------------------------------------------------
# T-F5-4 — write failure files nothing
# ---------------------------------------------------------------------------


class _FailingService:
    def create_commitment(self, *args, **kwargs):
        raise RuntimeError("database is down")


def test_f5_4_write_failure_files_nothing(tmp_path):
    host = _Host(_voice_msg("msg-offer-1", _offer_body()))
    state = EncounterState()
    _runtime()._file_accepted_offer(
        host, state, "Yes, lock it in", service=_FailingService()
    )
    assert state.confirmed_writes == []
    assert EncounterRuntime._confirmation_suffix(state) == ""


# ---------------------------------------------------------------------------
# T-F5-5 — recency
# ---------------------------------------------------------------------------


def test_f5_5_recency_offer_must_be_last_voice_turn(tmp_path):
    service = _ft_service(tmp_path)
    state = EncounterState()
    # An intervening reply with no block: "yes" now files nothing.
    _file(_Host(_voice_msg("msg-later", "A plain reply, no block.")),
          state, "Yes", service)
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []
    # The offer in the immediately previous model turn files.
    _file(_Host(_voice_msg("msg-offer-1", _offer_body())),
          state, "Yes", service)
    assert len(service.list_commitments(UID)) == 1


# ---------------------------------------------------------------------------
# T-F5-6 — read-back lag
# ---------------------------------------------------------------------------


def test_f5_6_read_back_lag_no_filing_then_next_turn_files(ft_ctx, tmp_path):
    """An offer accepted while answering the read-back files nothing
    on that turn (the hook does not run on the response turn); on
    the next conversational turn — the seat having re-offered with
    the block, per the prohibition + block-emission instruction —
    the same affirmation files.

    The hook constructs its default service on the filing path, so
    the default store is pointed at an isolated database (ft_ctx)
    and the rows are read back from there.
    """
    service = _ft_service(ft_ctx)
    offer = _voice_msg("msg-offer-1", _offer_body())
    host = _Host(offer)
    state = EncounterState(
        impression_offered=True,
        impression_answered=False,
        impression_text="A held read of the visitor.",
        impression_strands=[],
    )
    runtime = _runtime()
    runtime.handle_turn(host, state, "Yes, lock it in", 0)
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []
    assert state.impression_answered is True
    # Next conversational turn: the seat re-offered (block in the
    # immediately previous model turn) and the visitor affirms.
    host._last = _voice_msg("msg-offer-2", _offer_body())
    runtime.handle_turn(host, state, "Yes, lock it in", 0)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    assert len(state.confirmed_writes) == 1
    assert state.confirmed_writes[0]["status"] == "recorded"


# ---------------------------------------------------------------------------
# T-F5-7 / T-F5-8 — end-to-end through the meeting turn path
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (test_meetings
    pattern)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


@pytest.fixture()
def ft_ctx(tmp_path, monkeypatch):
    """Point the hook's default follow-through store at an isolated
    database for the turn-path tests (the hook constructs its
    service lazily; the module attribute is read at construction)."""
    import local_ai.followthrough.store as ft_store

    monkeypatch.setattr(ft_store, "DEFAULT_DB_PATH", tmp_path / "ft.db")
    return tmp_path


def _seeded_user(email="fc5@example.com"):
    user = ve.create_user_account(email, "pw", "FC5")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _meeting_svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
    )


def _offered_meeting(tmp_path, with_block: bool):
    """A started Conductor meeting whose last voice message is the
    seat's offer (with or without the block). Returns (svc, uid)."""
    svc = _meeting_svc(tmp_path)
    uid = _seeded_user()
    svc.start(uid, "conductor")
    body = _offer_body() if with_block else (
        "Want me to lock that in as a commitment here?"
    )
    svc.conversations.append_message(
        uid, CID, "conductor", "voice", body, mode="base",
        context={"meeting": True},
    )
    return svc, uid


def test_f5_7_end_to_end_meeting_turn_files(ve_ctx, ft_ctx, tmp_path):
    svc, uid = _offered_meeting(tmp_path, with_block=True)
    result = svc.turn(uid, "conductor", "Yes, lock it in")
    store = FollowthroughStore(ft_ctx / "ft.db")
    rows = store.list_commitments(uid)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "open"
    assert row["text"] == LABEL
    assert row["source_quote"] == "Yes, lock it in"
    assert row["source_conversation_id"] == CID
    assert row["source_message_id"]
    confirmations = result["confirmations"]
    assert len(confirmations) == 1
    conf = confirmations[0]
    assert conf["kind"] == "commitment"
    assert conf["status"] == "recorded"
    assert conf["id"] == row["id"]
    assert conf["label"] == LABEL
    # The persisted state renders the suffix: the seat may say Done.
    enc = EncounterState.from_json(
        svc.meetings.get(uid, "conductor", 1)["state_json"]
    )
    suffix = EncounterRuntime._confirmation_suffix(enc)
    assert row["id"] in suffix
    assert LABEL in suffix
    assert "You may say it is done" in suffix
    store.close()


def test_f5_8_no_offer_control_files_nothing(ve_ctx, ft_ctx, tmp_path):
    svc, uid = _offered_meeting(tmp_path, with_block=False)
    result = svc.turn(uid, "conductor", "Yes, lock it in")
    store = FollowthroughStore(ft_ctx / "ft.db")
    assert store.list_commitments(uid) == []
    assert result["confirmations"] == []
    enc = EncounterState.from_json(
        svc.meetings.get(uid, "conductor", 1)["state_json"]
    )
    assert EncounterRuntime._confirmation_suffix(enc) == ""
    store.close()


def test_f5_7_second_yes_files_nothing_more(ve_ctx, ft_ctx, tmp_path):
    """A second affirmation of the same offer — on the next turn,
    with the seat's reply in between carrying no new block — files
    nothing further (recency + dedup)."""
    svc, uid = _offered_meeting(tmp_path, with_block=True)
    svc.turn(uid, "conductor", "Yes, lock it in")
    svc.turn(uid, "conductor", "Yes, definitely")
    store = FollowthroughStore(ft_ctx / "ft.db")
    assert len(store.list_commitments(uid)) == 1
    store.close()


# ---------------------------------------------------------------------------
# T-F5-9 — hook scope
# ---------------------------------------------------------------------------


def _scoped_no_filing(state, message, ft_path):
    """Drive one handle_turn that must not file, asserting against
    the isolated default store the hook constructs (ft_ctx)."""
    host = _Host(_voice_msg("msg-offer-1", _offer_body()))
    _runtime().handle_turn(host, state, message, 0)
    store = FollowthroughStore(ft_path / "ft.db")
    try:
        assert store.list_commitments(UID) == []
    finally:
        store.close()
    assert state.confirmed_writes == []


def test_f5_9_hook_scope_response_completion_wrap(ft_ctx, tmp_path):
    # Impression-response turn: an affirmed offer files nothing.
    _scoped_no_filing(
        EncounterState(
            impression_offered=True,
            impression_answered=False,
            impression_text="A held read of the visitor.",
            impression_strands=[],
        ),
        "Yes, lock it in",
        ft_ctx,
    )
    # Completion turn: the offered path + affirmation closes the
    # meeting; no filing.
    state = EncounterState(completion_offered=True)
    _scoped_no_filing(state, "Yes", ft_ctx)
    assert state.closed is True
    # Wrap turn: past the turn ceiling, no filing.
    _scoped_no_filing(
        EncounterState(user_turns=13),
        "Yes, lock it in",
        ft_ctx,
    )


# ---------------------------------------------------------------------------
# T-F5-10 — reminder non-interference
# ---------------------------------------------------------------------------


def test_f5_10_reminder_ask_files_nothing(tmp_path):
    service = _ft_service(tmp_path)
    state = EncounterState()
    # A reminder ask with no commitment-offer block: FC6's branch
    # owns it; FC5 files nothing.
    _file(
        _Host(_voice_msg("msg-1", "I can remind you daily at 4pm if you like.")),
        state, "remind me daily at 4pm", service,
    )
    # A commitment-offer block + a reminder ask (not an affirmation):
    # ambiguous, files nothing.
    _file(
        _Host(_voice_msg("msg-offer-1", _offer_body())),
        state, "remind me daily at 4pm", service,
    )
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []


# ---------------------------------------------------------------------------
# T-F5-11 / T-F5-12 — render: instruction present, frame budget
# ---------------------------------------------------------------------------

_SEAT_BUILDERS = (
    ("conductor", MT.CONDUCTOR_FIRST_MEETING, build_weaver_k1_definition),
    ("mentor", MT.MENTOR_FIRST_MEETING, build_mentor_k1_definition),
    ("champion", MT.CHAMPION_FIRST_MEETING, build_champion_k1_definition),
    ("guardian", MT.GUARDIAN_FIRST_MEETING, build_guardian_k1_definition),
    ("maverick", MT.MAVERICK_FIRST_MEETING, build_maverick_k1_definition),
    ("ambassador", MT.AMBASSADOR_FIRST_MEETING, build_ambassador_k1_definition),
    ("skeptic", MT.SKEPTIC_FIRST_MEETING, build_skeptic_k1_definition),
)
_ALL_MET = (
    "mentor", "champion", "guardian", "maverick",
    "ambassador", "conductor", "skeptic",
)
_ONE_SUFFIX_LINE = (
    "Recorded this meeting (system fact, not your claim): "
    "commitment abc123def456, 'non-complicity at home'. "
    "You may say it is done."
)


def _frames():
    """(seat, variant, kind, frame) for every seat, fresh and
    all-met, engage and turn — the implemented assembly."""
    out = []
    for arch, script, builder in _SEAT_BUILDERS:
        for variant, met in (("fresh", ()), ("all-met", _ALL_MET)):
            d = dataclasses.replace(builder(script), met_seats=met)
            rt = EncounterRuntime(d)
            out.append((arch, variant, "engage", rt._engage_frame()))
            tf, _cue = rt._turn_frame(
                EncounterState(), "What is worth fighting for?"
            )
            out.append((arch, variant, "turn", tf))
    return out


def test_f5_11_instruction_in_all_seven_seats_prompts():
    for arch, variant, kind, frame in _frames():
        assert "```commitment-offer" in frame, (arch, variant, kind)
        assert "label: <the thing in the visitor's words, short>" in frame, (
            arch, variant, kind,
        )


def test_f5_12_frame_budget_tightest_with_instruction_and_suffix():
    """Measured from post-L1 renders at current main (not
    arithmetic): the tightest frame — Mentor all-met engage — with
    the ~246-char instruction and one ~127-char suffix line is
    8,534 chars, headroom 466, above the 300 floor. If this ever
    fails, the instruction is shortened, never the block format."""
    worst = 0
    worst_label = ""
    for arch, variant, kind, frame in _frames():
        total = len(frame) + 2 + len(_ONE_SUFFIX_LINE)
        if total > worst:
            worst = total
            worst_label = f"{arch} {variant} {kind}"
    assert worst < CAP, worst_label
    assert CAP - worst >= 300, worst_label
    # Pin the measured tightest frame so a future drift is visible.
    assert worst_label == "mentor all-met engage"
    assert worst == 8534


# ---------------------------------------------------------------------------
# Store migration (correction 2 support)
# ---------------------------------------------------------------------------


def test_migration_adds_columns_and_index_to_legacy_db(tmp_path):
    """A commitments table created by the old schema (no provenance
    columns) gains both columns + the unique index on open, and the
    idempotent path works against it."""
    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(legacy))
    conn.execute(
        "CREATE TABLE commitments ("
        "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, text TEXT NOT NULL,"
        " source_quote TEXT, linked_task_id TEXT,"
        " status TEXT NOT NULL DEFAULT 'open',"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO commitments (id, user_id, text, status, created_at,"
        " updated_at) VALUES ('old-1', ?, 'walk the dog', 'open', 'x', 'x')",
        (UID,),
    )
    conn.commit()
    conn.close()
    store = FollowthroughStore(legacy)
    cols = [
        r[1]  # PRAGMA table_info rows are plain tuples: (cid, name, ...)
        for r in sqlite3.connect(str(legacy)).execute(
            "PRAGMA table_info(commitments)"
        ).fetchall()
    ]
    assert "source_conversation_id" in cols
    assert "source_message_id" in cols
    assert store.list_commitments(UID)[0]["id"] == "old-1"
    row = store.create_commitment(
        UID, "walk the dog", "Yes",
        source_conversation_id=CID, source_message_id="msg-old",
    )
    assert row["source_conversation_id"] == CID
    again = store.create_commitment(
        UID, "walk the dog", "Yes",
        source_conversation_id=CID, source_message_id="msg-old",
    )
    assert again["id"] == row["id"]
    assert len(store.list_commitments(UID)) == 2
    store.close()
