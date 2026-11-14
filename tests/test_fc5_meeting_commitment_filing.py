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


def _user_msg(msg_id: str, body: str) -> dict:
    return {
        "id": msg_id,
        "user_id": UID,
        "conversation_id": CID,
        "archetype_id": "conductor",
        "role": "user",
        "body": body,
        "mode": "base",
        "context": {"meeting": True},
        "created_at": "2026-11-12T00:00:00+00:00",
    }


class _Host:
    """Minimal host: records what the runtime asks of it."""

    def __init__(self, last_voice: dict | None = None,
                 history: list[dict] | None = None) -> None:
        self._last = last_voice
        self._history = list(history) if history is not None else []
        self.said: list[str] = []
        self.generated: list[str] = []
        self.closed: list[str] = []

    def last_voice_message(self) -> dict | None:
        return self._last

    def recent_history(self, limit: int = 8) -> list[dict]:
        """The bounded window the carried-offer resolver reads."""
        if limit <= 0:
            return []
        return self._history[-int(limit):]

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
    # A conversational turn after the read-back also breaks the
    # carry (founder ruling 2026-11-12): the offer is reachable
    # only across exactly one read-back turn, not across a
    # read-back PLUS a conversational turn.
    state.impression_text = "A held read of the visitor."
    intervened = _Host(
        _voice_msg("msg-reply-2", "A plain reply, no block."),
        history=[
            _voice_msg("msg-offer-1", _offer_body()),
            _voice_msg("msg-impression", "A held read of the visitor."),
            _user_msg("msg-u-readback", "Yes, that's right."),
            _voice_msg("msg-readback-reply", "Noted."),
            _user_msg("msg-u-conv", "Tell me more about that."),
            _voice_msg("msg-reply-2", "A plain reply, no block."),
            _user_msg("msg-u-now", "Yes"),
        ],
    )
    _file(intervened, state, "Yes", service)
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []
    # The offer in the immediately previous model turn files.
    _file(_Host(_voice_msg("msg-offer-1", _offer_body())),
          state, "Yes", service)
    assert len(service.list_commitments(UID)) == 1


# ---------------------------------------------------------------------------
# T-F5-6 — read-back lag
# ---------------------------------------------------------------------------


def test_f5_6_read_back_lag_files_without_re_offer(ft_ctx, tmp_path):
    """Founder ruling 2026-11-12 (read-back offer continuity): an
    offer accepted while answering the read-back files nothing on
    that turn (the hook does not run on the response turn); on the
    next conversational turn the same affirmation files the
    ORIGINAL offer — no re-offer required — because exactly one
    read-back turn intervened. The filing keeps the original
    offer's id, label, and provenance.

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
    # Next conversational turn: the seat did NOT re-offer. The last
    # voice message is its read-back response (no block); the
    # carried offer resolves from the bounded history window.
    response = _voice_msg("msg-readback-reply", "Got it — noted, and held.")
    host._last = response
    host._history = [
        offer,
        _voice_msg("msg-impression", "A held read of the visitor."),
        _user_msg("msg-u-readback", "Yes, lock it in"),
        response,
        _user_msg("msg-u-now", "Yes, lock it in"),
    ]
    runtime.handle_turn(host, state, "Yes, lock it in", 0)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    assert rows[0]["text"] == LABEL
    assert rows[0]["source_message_id"] == "msg-offer-1"
    assert rows[0]["source_quote"] == "Yes, lock it in"
    assert len(state.confirmed_writes) == 1
    assert state.confirmed_writes[0]["status"] == "recorded"
    assert state.confirmed_writes[0]["source_message_id"] == "msg-offer-1"


# ---------------------------------------------------------------------------
# T-F5-6b — read-back offer continuity (founder ruling 2026-11-12)
# ---------------------------------------------------------------------------

IMPRESSION = "A held read of the visitor."


def _pre_voices(*, offer_in="reply", offer_label=LABEL):
    """The pre-read-back model turn's voices, in order, plus the
    impression text the state must carry for the walk to identify
    the read-back turn. ``offer_in``: "reply" (block in the reply
    before the impression), "impression" (block in the impression
    itself), "both-same" (the same label in both), "both-different"
    (reply "first", impression "second"), or None (no block)."""
    if offer_in == "reply":
        return ([_voice_msg("msg-offer-1", _offer_body(offer_label)),
                 _voice_msg("msg-impression", IMPRESSION)], IMPRESSION)
    if offer_in == "impression":
        body = _offer_body(offer_label)
        return ([_voice_msg("msg-impression", body)], body)
    if offer_in == "both-same":
        body = _offer_body(offer_label)
        return ([_voice_msg("msg-offer-1", body),
                 _voice_msg("msg-impression", body)], body)
    if offer_in == "both-different":
        return ([_voice_msg("msg-offer-1", _offer_body("first")),
                 _voice_msg("msg-impression", _offer_body("second"))],
                _offer_body("second"))
    return ([_voice_msg("msg-impression", IMPRESSION)], IMPRESSION)


def _carried_host(*, pre_voices, readback_body="Yes, that's right.",
                  response_bodies=("Noted.",), current_body="Yes",
                  trailing_voices=(), impression_text=IMPRESSION):
    """(host, state) for the carry shape:
    [pre_voices...] U_readback [responses...] U_current [trailing...].
    ``trailing_voices`` are voices spoken in the current turn
    before the hook runs (the live introduction). The host's last
    voice message is the last voice in the assembled history, as
    production's last_voice_message would return it."""
    history = list(pre_voices)
    history.append(_user_msg("msg-u-readback", readback_body))
    for n, body in enumerate(response_bodies):
        history.append(_voice_msg(f"msg-response-{n}", body))
    history.append(_user_msg("msg-u-now", current_body))
    history.extend(trailing_voices)
    last_voice = next(
        (m for m in reversed(history) if m.get("role") == "voice"), None
    )
    state = EncounterState()
    state.impression_text = impression_text
    return _Host(last_voice, history=history), state


def test_f5_6b_immediate_acceptance_files(tmp_path):
    """The ruling's first case: the offer in the immediately
    previous model turn files on an explicit acceptance."""
    service = _ft_service(tmp_path)
    host = _Host(
        _voice_msg("msg-offer-1", _offer_body()),
        history=[
            _voice_msg("msg-offer-1", _offer_body()),
            _user_msg("msg-u-now", "Yes"),
        ],
    )
    _file(host, EncounterState(), "Yes", service)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    assert rows[0]["source_message_id"] == "msg-offer-1"


def test_f5_6b_carried_offer_in_reply_files(tmp_path):
    """Read-back acceptance: the offer in the reply before the
    impression files on the next turn's explicit acceptance,
    keeping the original offer's id, label, and provenance."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="reply")
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text)
    _file(host, state, "Yes", service)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    row = rows[0]
    assert row["text"] == LABEL
    assert row["source_message_id"] == "msg-offer-1"
    assert row["source_conversation_id"] == CID
    assert row["source_quote"] == "Yes"
    assert len(state.confirmed_writes) == 1
    assert state.confirmed_writes[0]["source_message_id"] == "msg-offer-1"


def test_f5_6b_carried_offer_in_impression_files(tmp_path):
    """The block in the impression voice itself is the carried
    offer — it files with the impression's own id."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="impression")
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text)
    _file(host, state, "Yes", service)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    assert rows[0]["text"] == LABEL
    assert rows[0]["source_message_id"] == "msg-impression"


def test_f5_6b_carried_same_label_twice_files_once(tmp_path):
    """The same label in both the reply and the impression is one
    offer, not two — it files once, carried by the newest voice
    (the impression)."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="both-same")
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text)
    _file(host, state, "Yes", service)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    assert rows[0]["source_message_id"] == "msg-impression"
    assert len(state.confirmed_writes) == 1


def test_f5_6b_carried_competing_offers_file_nothing(tmp_path):
    """Two different labels in the pre-read-back turn are competing
    offers — automatic filing is invalid and nothing files."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="both-different")
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text)
    _file(host, state, "Yes", service)
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []


def test_f5_6b_immediately_preceding_offer_wins(tmp_path):
    """When the last voice message carries its own block, that
    offer files — the carried one is not also filed."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="reply")
    host, state = _carried_host(
        pre_voices=pre_voices, impression_text=impression_text,
        response_bodies=(_offer_body("second"),),
    )
    _file(host, state, "Yes", service)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    assert rows[0]["text"] == "second"
    assert rows[0]["source_message_id"] == "msg-response-0"


def test_f5_6b_reoffer_in_readback_response_supersedes(tmp_path):
    """The seat re-offers in its read-back response (a different
    label), then speaks on without the block: the carried offer is
    superseded — the visitor's "Yes" is ambiguous between the two
    offers, so nothing files automatically."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="reply")
    host, state = _carried_host(
        pre_voices=pre_voices, impression_text=impression_text,
        response_bodies=(_offer_body("second"), "Anything else?"),
    )
    _file(host, state, "Yes", service)
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []


def test_f5_6b_carried_ambiguous_current_message_files_nothing(tmp_path):
    """The carried offer resolves, but an ambiguous current reply
    files nothing — the matcher gate still binds on this path."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="reply")
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text,
                                current_body="Hmm")
    _file(host, state, "Hmm", service)
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []


def test_f5_6b_carried_withdrawal_in_readback_files_nothing(tmp_path):
    """The read-back answer withdraws the offer ("No, don't file
    that") — a later "Yes" does not revive it automatically."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="reply")
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text,
                                readback_body="No, don't file that")
    _file(host, state, "Yes", service)
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []


def test_f5_6b_carried_correction_in_readback_files_nothing(tmp_path):
    """The read-back answer amends the record ("I meant Y") — a
    substantive change in the same exchange, so the carried offer
    does not file automatically even though the matcher alone
    would not deny it."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="reply")
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text,
                                readback_body="I meant Y. Yes, lock it in.")
    _file(host, state, "Yes", service)
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []


def test_f5_6b_carried_silent_readback_response_files_nothing(tmp_path):
    """The model said nothing in response to the read-back (a
    degraded turn) — the carry fails closed and nothing files."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="reply")
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text,
                                response_bodies=())
    _file(host, state, "Yes", service)
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []


def test_f5_6b_carried_offer_files_with_introduction_first(tmp_path):
    """The live introduction, spoken in the current turn before
    the hook runs, does not disturb the carry: the walk skips the
    current turn's own speech."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="reply")
    host, state = _carried_host(
        pre_voices=pre_voices, impression_text=impression_text,
        trailing_voices=[_voice_msg("msg-intro", "I am the Champion.")],
    )
    _file(host, state, "Yes", service)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    assert rows[0]["source_message_id"] == "msg-offer-1"


def test_f5_6b_carried_no_offer_files_nothing(tmp_path):
    """No block anywhere in the pre-read-back turn: the carry
    resolves nothing and a "Yes" files nothing."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in=None)
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text)
    _file(host, state, "Yes", service)
    assert service.list_commitments(UID) == []
    assert state.confirmed_writes == []


def test_f5_6b_carried_duplicate_retry_files_once(tmp_path):
    """A second "Yes" to the same carried offer files nothing
    further — the state dedup holds on the carried path."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="reply")
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text)
    _file(host, state, "Yes", service)
    assert len(service.list_commitments(UID)) == 1
    _file(host, state, "Yes", service)
    assert len(service.list_commitments(UID)) == 1
    assert len(state.confirmed_writes) == 1


def test_f5_6b_carried_storage_idempotency_survives_lost_confirmation(tmp_path):
    """Correction 2 on the carried path: the Confirmation is lost
    after the write commits; a retry returns the committed row —
    same id — not a second row."""
    service = _ft_service(tmp_path)
    pre_voices, impression_text = _pre_voices(offer_in="reply")
    host, state = _carried_host(pre_voices=pre_voices,
                                impression_text=impression_text)
    _file(host, state, "Yes", service)
    assert len(service.list_commitments(UID)) == 1
    first_id = state.confirmed_writes[0]["id"]
    state.confirmed_writes.clear()
    _file(host, state, "Yes", service)
    rows = service.list_commitments(UID)
    assert len(rows) == 1
    assert rows[0]["id"] == first_id
    assert len(state.confirmed_writes) == 1
    assert state.confirmed_writes[0]["id"] == first_id


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
    "commitment abc123def456, 'non-complicity at home' "
    "(recorded). You may say it is done."
)


def _context_state():
    """An encounter state carrying a commitment context: one
    confirmed write on the encounter — the FC5 scoped ruling's
    condition (founder, 2026-11-13). The entry's content does not
    affect frame assembly; only its presence gates the offer
    instruction (and, at the seam, the confirmation suffix)."""
    return EncounterState(confirmed_writes=[{
        "kind": "commitment",
        "id": "abc123def456",
        "label": "non-complicity at home",
        "status": "recorded",
        "turn": 1,
        "source_message_id": "msg-ctx",
    }])


def _frames(with_context=False):
    """(seat, variant, kind, frame) for every seat, fresh and
    all-met, engage and turn — the implemented assembly. By
    default the frames are built on a fresh encounter (no
    commitment context); with_context=True builds them on a
    state carrying a confirmed write."""
    out = []
    for arch, script, builder in _SEAT_BUILDERS:
        for variant, met in (("fresh", ()), ("all-met", _ALL_MET)):
            d = dataclasses.replace(builder(script), met_seats=met)
            rt = EncounterRuntime(d)
            st = _context_state() if with_context else None
            out.append((arch, variant, "engage", rt._engage_frame(st)))
            tf, _cue = rt._turn_frame(
                st if st is not None else EncounterState(),
                "What is worth fighting for?"
            )
            out.append((arch, variant, "turn", tf))
    return out


def test_f5_11_instruction_scoped_to_commitment_context():
    """FC5 scoped (founder ruling, 2026-11-13; this test replaces
    the unconditional-presence pin of the pre-scoping build): the
    offer instruction is not first-meeting boilerplate. On a
    fresh encounter — no commitment context — it appears in NO
    seat's frames, engage or turn, fresh or all-met: every
    no-context assembly is the pre-FC5 assembly. When the
    encounter carries a commitment context (a confirmed write on
    state), the instruction rides EVERY seat's frames under the
    same condition: the gate is the encounter's records, never
    the seat, and no seat is excluded."""
    for arch, variant, kind, frame in _frames():
        assert "```commitment-offer" not in frame, (arch, variant, kind)
        assert "Never say it is filed." not in frame, (arch, variant, kind)
    for arch, variant, kind, frame in _frames(with_context=True):
        assert "```commitment-offer" in frame, (arch, variant, kind)
        assert "label: <the thing in the visitor's words, short>" in frame, (
            arch, variant, kind,
        )


def test_f5_11b_context_adds_exactly_the_instruction():
    """The commitment-context assembly differs from the
    no-context assembly by exactly the instruction and its
    separator (157 + 2 = 159 chars), appended last — the scoping
    changes the instruction's presence, never its content,
    position, or anything else in the frame."""
    plain = {(a, v, k): f for a, v, k, f in _frames()}
    ctx = {(a, v, k): f for a, v, k, f in _frames(with_context=True)}
    assert plain.keys() == ctx.keys()
    for key, frame in plain.items():
        assert len(ctx[key]) - len(frame) == 159, key
        assert ctx[key].endswith(ENC._COMMITMENT_OFFER_INSTRUCTION), key


def test_f5_12_frame_budget_tightest_with_instruction_and_suffix():
    """Rendered frames, composed exactly as the seam composes
    them: the tightest frame — Mentor all-met engage — with the
    157-char Variant C instruction and one 85-char compact
    confirmation line is 8,645 chars, headroom 355, above the
    300 floor. (The pre-hybrid form — the 246-char instruction
    and the ~127-char full line — composed to 8,776 on the
    rebased branch, headroom 224: the failure that commissioned
    the hybrid correction.) If this ever fails, the instruction
    is shortened, never the block format.

    FC5 scoped (2026-11-13): the frames measured here are the
    commitment-context assembly (_frames(with_context=True)) —
    since the scoping, a frame carries the confirmation suffix
    in production only when the encounter carries records, which
    is exactly the state in which it also carries the
    instruction; the composed worst case is unchanged."""
    worst = 0
    worst_label = ""
    for arch, variant, kind, frame in _frames(with_context=True):
        total = len(frame) + 2 + len(_ONE_SUFFIX_LINE)
        if total > worst:
            worst = total
            worst_label = f"{arch} {variant} {kind}"
    assert worst < CAP, worst_label
    assert CAP - worst >= 300, worst_label
    # Pin the measured tightest frame so a future drift is visible.
    assert worst_label == "mentor all-met engage"
    assert worst == 8645


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


# ---------------------------------------------------------------------------
# T-F5-13 — hybrid confirmation rendering (founder rulings 2026-11-12)
# ---------------------------------------------------------------------------
#
# Context-relevant selection (S1–S4) with the compact line,
# corrected by (1) the all-or-nothing overflow marker, (2) the
# unshown-records framing line, (3) dismissal reconciliation.
# Design: your_files/zenaf-fc5-hybrid-correction-design-2026-11-12.md.
# Every figure below is rendered through the real seam against the
# real frame assembly — never hand-computed. Both gates are the
# standing ones (9,000 cap, 300 floor; a composed frame satisfies
# both iff it is at most 8,700).

L58 = "finish the proposal draft and send it to the client Friday"
FRAMING = "Unshown records are unconfirmed. Ask; do not assert."


def _conf(i, label, turn, status="recorded", kind="commitment"):
    return {
        "kind": kind,
        "id": f"{i:012d}"[-12:],
        "label": label,
        "status": status,
        "turn": turn,
        "source_message_id": f"msg-{i}",
    }


def _tightest_frame(kind):
    """The longest frame of a kind in the commitment-context
    assembly: the hybrid budget tests compose the confirmation
    suffix onto a base frame, and since the FC5 scoping
    (2026-11-13) the suffix renders only on frames whose
    encounter carries records — the same frames that carry the
    offer instruction — so the composed worst case is measured
    on the context assembly, exactly as production composes it."""
    return max(
        (f for _, _, k, f in _frames(with_context=True) if k == kind),
        key=len,
    )


def _block(state, frame, message):
    out = EncounterRuntime._with_confirmations(state, frame, message)
    assert out.startswith(frame + "\n\n")
    return out[len(frame) + 2:]


def test_hybrid_texts_pinned_verbatim():
    """The hybrid texts and Variant C are pinned verbatim (T2.2 +
    the instruction economy pin): any growth is a deliberate,
    visible change. The marker stays fixed-cost at every
    reachable count (T1.7)."""
    assert ENC._COMMITMENT_OFFER_INSTRUCTION == (
        "When you offer to lock something in, append a "
        "```commitment-offer block: one line, "
        "`label: <the thing in the visitor's words, short>`. "
        "Never say it is filed."
    )
    assert len(ENC._COMMITMENT_OFFER_INSTRUCTION) == 157
    assert ENC._CONFIRMATION_FRAMING_LINE == FRAMING
    assert len(FRAMING) == 52
    assert ENC._CONFIRMATION_OVERFLOW_MARKER.format(k=2) == (
        "System fact: recorded commitments (2) are not shown here "
        "(frame limit); this view is incomplete. Claim no status "
        "this turn."
    )
    for k in range(1, 100):
        assert len(ENC._CONFIRMATION_OVERFLOW_MARKER.format(k=k)) <= 140


def test_hybrid_compact_line_fields_and_lengths():
    """The D5 compact line keeps every field — kind, id, exact
    label, status, license phrase — at 85 chars for a 22-char
    label (121 at 58, 263 at 200)."""
    line = EncounterRuntime._confirmation_line(_conf(1, LABEL, 1))
    assert line == (
        "commitment 000000000001, 'non-complicity at home' "
        "(recorded). You may say it is done."
    )
    assert len(line) == 85
    assert len(EncounterRuntime._confirmation_line(_conf(1, L58, 1))) == 121
    assert len(
        EncounterRuntime._confirmation_line(_conf(1, "x" * 200, 1))
    ) == 263


def test_hybrid_selection_s1_s2_windows():
    """S1 selects this turn's filing and S2 last turn's; an older
    entry is not selected by an unrelated message, and the
    framing line leads because the rendered set is partial."""
    state = EncounterState(user_turns=5, confirmed_writes=[
        _conf(1, "the oldest record", 3),
        _conf(2, "last turns record", 4),
        _conf(3, "this turns record", 5),
    ])
    block = _block(state, "FRAME", "Tell me more about that.")
    assert block.split("\n")[0] == FRAMING
    assert "this turns record" in block
    assert "last turns record" in block
    assert "the oldest record" not in block


def test_hybrid_selection_s3_names_the_record():
    """T2.3: naming the label (or the id) verbatim in the current
    message selects that record for the next generation; a
    paraphrase selects nothing — the honest limit, pinned."""
    state = EncounterState(user_turns=6, confirmed_writes=[
        _conf(1, LABEL, 2),
        _conf(2, "water the plants", 3),
    ])
    by_label = _block(state, "FRAME", f"About {LABEL} — is that set?")
    assert LABEL in by_label
    assert "water the plants" not in by_label
    by_id = _block(state, "FRAME", "What about 000000000002?")
    assert "water the plants" in by_id
    assert LABEL not in by_id
    paraphrase = _block(state, "FRAME", "That home thing from before?")
    assert paraphrase == FRAMING


def test_hybrid_selection_s4_general_inquiry_renders_full_set():
    """S4: a general inquiry renders the full set for that
    generation — no framing line (R == N) — byte-identical to
    the full suffix rendering."""
    state = EncounterState(user_turns=6, confirmed_writes=[
        _conf(1, LABEL, 2),
        _conf(2, "water the plants", 3),
    ])
    block = _block(state, "FRAME", "What have I locked in so far?")
    assert FRAMING not in block
    assert block == EncounterRuntime._confirmation_suffix(state)


def test_hybrid_quiet_turn_and_empty_state():
    """T2.1 presence matrix: a quiet turn (R = 0, N ≥ 1) renders
    the framing line alone; empty state leaves the frame
    byte-identical and the suffix empty."""
    state = EncounterState(
        user_turns=6, confirmed_writes=[_conf(1, LABEL, 2)]
    )
    assert _block(state, "FRAME", "Tell me more about that.") == FRAMING
    empty = EncounterState()
    assert EncounterRuntime._with_confirmations(empty, "FRAME", "hi") == "FRAME"
    assert EncounterRuntime._confirmation_suffix(empty) == ""
    # No message context (message=None): selection is undefined,
    # so the seam renders the full set — the pre-hybrid contract
    # the firebrand p6 plumbing test pins. Every production
    # generation site passes its message.
    bare = EncounterRuntime._with_confirmations(state, "FRAME")
    assert "You may say it is done" in bare
    assert FRAMING not in bare


def test_hybrid_rendering_never_mutates_state_and_keeps_order():
    """T1.5: rendering is a pure view — repeat calls on identical
    (state, message, frame) are byte-identical, state is
    deep-equal after, and filing order is preserved."""
    state = EncounterState(user_turns=6, confirmed_writes=[
        _conf(1, LABEL, 2),
        _conf(2, "water the plants", 3),
    ])
    before = [dict(c) for c in state.confirmed_writes]
    first = _block(state, "FRAME", "What have I locked in so far?")
    second = _block(state, "FRAME", "What have I locked in so far?")
    assert first == second
    assert state.confirmed_writes == before
    assert first.index(LABEL) < first.index("water the plants")


def test_hybrid_worst_case_headroom_302():
    """The corrected design's binding case, rendered: a partial
    R = 1 selection with the framing line riding, ordinary label,
    on the tightest frame in the system composes to 8,698 —
    headroom 302, both gates hold. A quiet turn on the same frame
    renders the framing line alone at 8,612 (headroom 388)."""
    engage = _tightest_frame("engage")
    state = EncounterState(user_turns=5, confirmed_writes=[
        _conf(1, "an older record", 1),
        _conf(2, LABEL, 5),
    ])
    out = EncounterRuntime._with_confirmations(state, engage, "Go on.")
    assert len(out) == 8698
    assert CAP - len(out) == 302
    block = out[len(engage) + 2:]
    assert block.split("\n")[0] == FRAMING
    assert LABEL in block
    quiet = EncounterState(user_turns=9, confirmed_writes=[
        _conf(1, LABEL, 2),
        _conf(2, "water the plants", 3),
    ])
    out = EncounterRuntime._with_confirmations(quiet, engage, "Go on.")
    assert len(out) == 8612


def test_hybrid_overflow_boundary_is_exact():
    """T1.1/T1.2: at the fit limit the lines render (composed
    exactly 8,700); one char past it the whole block defers to
    the marker (8,683) — the marker names no record and carries
    the no-claim instruction."""
    engage = _tightest_frame("engage")
    older = _conf(1, "an older record", 1)
    fits = EncounterState(user_turns=5, confirmed_writes=[
        older, _conf(2, "x" * 24, 5),
    ])
    out = EncounterRuntime._with_confirmations(fits, engage, "Go on.")
    assert len(out) == 8700
    assert "Claim no status" not in out
    over = EncounterState(user_turns=5, confirmed_writes=[
        older, _conf(2, "x" * 25, 5),
    ])
    out = EncounterRuntime._with_confirmations(over, engage, "Go on.")
    assert len(out) == 8683
    block = out[len(engage) + 2:]
    assert block == ENC._CONFIRMATION_OVERFLOW_MARKER.format(k=2)
    assert "incomplete" in block
    assert "x" * 25 not in block
    assert "an older record" not in block


def test_hybrid_marker_cases_compose_8683_8684():
    """Every generation the uncorrected hybrid failed now
    composes at 8,683–8,684 via the marker: back-to-back filings
    (R = 2) on the tightest frame, and a general inquiry at the
    mechanical maximum (N = 11 — the count's second digit costs
    the marker one char)."""
    engage = _tightest_frame("engage")
    state = EncounterState(user_turns=5, confirmed_writes=[
        _conf(1, LABEL, 4),
        _conf(2, "water the plants", 5),
    ])
    out = EncounterRuntime._with_confirmations(state, engage, "Go on.")
    assert len(out) == 8683
    big = EncounterState(user_turns=12, confirmed_writes=[
        _conf(i, LABEL, i + 1) for i in range(1, 12)
    ])
    out = EncounterRuntime._with_confirmations(
        big, engage, "What did you record for me?"
    )
    assert len(out) == 8684
    assert out.endswith(ENC._CONFIRMATION_OVERFLOW_MARKER.format(k=11))


def test_hybrid_s4_full_set_renders_on_turn_frames():
    """T1.6, second half: the same N = 11 general inquiry on the
    tightest turn frame renders all 11 lines — composed 7,844,
    pinned."""
    turn = _tightest_frame("turn")
    big = EncounterState(user_turns=12, confirmed_writes=[
        _conf(i, LABEL, i + 1) for i in range(1, 12)
    ])
    out = EncounterRuntime._with_confirmations(
        big, turn, "What did you record for me?"
    )
    assert len(out) == 7844
    assert out.count("You may say it is done.") == 11


def test_hybrid_marker_preserves_state_and_defers_not_loses():
    """T1.3/T1.4: an overflow generation touches nothing durable
    — state deep-equal after, the full record still renders from
    the same state (the receipt reads state, never the block),
    and a later generation whose selection fits renders the same
    lines byte-identically."""
    engage = _tightest_frame("engage")
    turn = _tightest_frame("turn")
    state = EncounterState(user_turns=5, confirmed_writes=[
        _conf(1, LABEL, 4),
        _conf(2, "water the plants", 5),
    ])
    before = [dict(c) for c in state.confirmed_writes]
    EncounterRuntime._with_confirmations(state, engage, "Go on.")
    assert state.confirmed_writes == before
    assert EncounterRuntime._confirmation_suffix(state).count("\n") == 1
    later = EncounterRuntime._with_confirmations(state, turn, "Go on.")
    assert later == (
        turn + "\n\n" + EncounterRuntime._confirmation_suffix(state)
    )


class _StatusHost(_Host):
    """_Host plus the optional dismissal-reconciliation getter."""

    def __init__(self, statuses=None, raises=False, **kwargs):
        super().__init__(**kwargs)
        self._statuses = statuses or {}
        self._raises = raises
        self.asked: list[str] = []

    def commitment_statuses(self, ids):
        self.asked.extend(ids)
        if self._raises:
            raise RuntimeError("store is down")
        return {i: self._statuses.get(i) for i in ids}


def test_hybrid_reconciliation_table():
    """T3.1: store dismissed → flip; open → unchanged; done →
    unchanged (excluded by design — a fulfilled commitment stays
    an active record); row missing → flip; already dismissed →
    unchanged; reminder entries are never consulted; provenance
    is byte-identical after a flip; a second pass is idempotent."""
    state = EncounterState(user_turns=3, confirmed_writes=[
        _conf(1, "to dismiss", 2),
        _conf(2, "stays open", 2),
        _conf(3, "fulfilled", 2),
        _conf(4, "vanished", 2),
        _conf(5, "already gone", 2, status="dismissed"),
        _conf(6, "a reminder", 2, kind="reminder"),
    ])
    host = _StatusHost({
        "000000000001": "dismissed",
        "000000000002": "open",
        "000000000003": "done",
        # 000000000004 is absent from the map: no row → None.
    })
    _runtime()._reconcile_dismissed_confirmations(host, state)
    by_id = {c["id"]: c for c in state.confirmed_writes}
    assert by_id["000000000001"]["status"] == "dismissed"
    assert by_id["000000000002"]["status"] == "recorded"
    assert by_id["000000000003"]["status"] == "recorded"
    assert by_id["000000000004"]["status"] == "dismissed"
    assert by_id["000000000005"]["status"] == "dismissed"
    assert by_id["000000000006"]["status"] == "recorded"
    assert set(host.asked) == {
        "000000000001", "000000000002",
        "000000000003", "000000000004",
    }
    flipped = by_id["000000000001"]
    assert flipped["label"] == "to dismiss"
    assert flipped["turn"] == 2
    assert flipped["source_message_id"] == "msg-1"
    _runtime()._reconcile_dismissed_confirmations(host, state)
    assert [c["status"] for c in state.confirmed_writes] == [
        "dismissed", "recorded", "recorded",
        "dismissed", "dismissed", "recorded",
    ]


def test_hybrid_reconciliation_fails_soft():
    """T3.1 failure rows: a host without the getter, or a getter
    that raises, leaves every entry unchanged — reconciliation
    fails soft to the pre-correction behavior and never blocks
    the turn."""
    state = EncounterState(
        user_turns=3, confirmed_writes=[_conf(1, LABEL, 2)]
    )
    _runtime()._reconcile_dismissed_confirmations(_Host(), state)
    assert state.confirmed_writes[0]["status"] == "recorded"
    _runtime()._reconcile_dismissed_confirmations(
        _StatusHost(raises=True), state
    )
    assert state.confirmed_writes[0]["status"] == "recorded"


def test_hybrid_dismissed_rendering():
    """T3.2: a dismissed entry renders the was-recorded line —
    id and label verbatim, the license withdrawn in words — and
    never alongside an active license."""
    line = EncounterRuntime._confirmation_line(
        _conf(1, LABEL, 2, status="dismissed")
    )
    assert line == (
        "commitment 000000000001, 'non-complicity at home' "
        "(was recorded; dismissed — never say it is done)."
    )
    assert len(line) == 99
    state = EncounterState(
        user_turns=3,
        confirmed_writes=[_conf(1, LABEL, 2, status="dismissed")],
    )
    suffix = EncounterRuntime._confirmation_suffix(state)
    assert "never say it is done" in suffix
    assert "You may say it is done" not in suffix


def test_hybrid_dismissed_line_budgets():
    """Rendered pins from the design table: a lone dismissed
    confirmation in its S2 window composes to 8,659 (22-char
    label) and 8,695 (58-char) on the tightest frame — both
    gates hold."""
    engage = _tightest_frame("engage")
    for label, total in ((LABEL, 8659), (L58, 8695)):
        state = EncounterState(user_turns=3, confirmed_writes=[
            _conf(1, label, 2, status="dismissed"),
        ])
        out = EncounterRuntime._with_confirmations(
            state, engage, "Tell me more about that."
        )
        assert len(out) == total


def test_hybrid_dismissed_status_survives_round_trip():
    """T3.4: the reconciled status is one new VALUE in the
    existing field — it survives the to_json/from_json
    round-trip byte-equal. No schema change."""
    state = EncounterState(
        user_turns=3,
        confirmed_writes=[_conf(1, LABEL, 2, status="dismissed")],
    )
    back = EncounterState.from_json(state.to_json())
    assert back.confirmed_writes == state.confirmed_writes
    assert back.confirmed_writes[0]["status"] == "dismissed"


def test_hybrid_dismissal_end_to_end(ve_ctx, ft_ctx, tmp_path):
    """T3.3 (the f5_7 pattern): file through the real hook,
    dismiss the row in the store, and the next turn's persisted
    state carries the entry as dismissed, rendering the
    was-recorded form. The same flow without dismissal keeps
    the recorded form and its license."""
    svc, uid = _offered_meeting(tmp_path, with_block=True)
    svc.turn(uid, "conductor", "Yes, lock it in")
    service = _ft_service(ft_ctx)
    row = service.list_commitments(uid)[0]
    service.set_commitment_status(uid, row["id"], "dismissed")
    svc.turn(uid, "conductor", "Tell me more about that.")
    enc = EncounterState.from_json(
        svc.meetings.get(uid, "conductor", 1)["state_json"]
    )
    assert enc.confirmed_writes[0]["status"] == "dismissed"
    suffix = EncounterRuntime._confirmation_suffix(enc)
    assert "was recorded; dismissed" in suffix
    assert "You may say it is done" not in suffix
    service.store.close()


def test_hybrid_no_dismissal_keeps_recorded_form(ve_ctx, ft_ctx, tmp_path):
    """T3.3 control: the same two turns without a dismissal —
    the entry stays recorded and keeps its license."""
    svc, uid = _offered_meeting(tmp_path, with_block=True)
    svc.turn(uid, "conductor", "Yes, lock it in")
    svc.turn(uid, "conductor", "Tell me more about that.")
    enc = EncounterState.from_json(
        svc.meetings.get(uid, "conductor", 1)["state_json"]
    )
    assert enc.confirmed_writes[0]["status"] == "recorded"
    assert "You may say it is done" in EncounterRuntime._confirmation_suffix(
        enc
    )
