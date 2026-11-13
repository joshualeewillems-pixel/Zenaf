"""Read-back correction + impression retention — deterministic tests.

No model calls, no live meetings, no paid generations. Covers the
founder-authorized change set (2026-11-06):

- the strict-ack positive allowlist (routing),
- the marker parser (fail-closed) and the response-turn parse
  (--- separation, Strands: handling, missing-Strands-keeps-original),
- persistence (three columns on both tables, set-if-empty original,
  fail-safe signature, archive carry-through),
- filing/review (dimensions + original in the claim, ceiling label),
- the training boundary (accept on disputed/unresolved gates the
  affirmative signal; the accept itself still succeeds),
- the stored corpus (13 archived replies + the Fox reply, classifier
  and routing only — no model judgment).

The marker's visitor dimension follows the founder's tie-break
(change 2): hedged/uncertain agreement is unresolved, affirmed only
for unambiguous agreement. Revised x affirmed is VALID (founder
ruling 2026-11-06 ~00:47 PT): agreement does not forbid revision.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from local_ai.agent_intake.pipeline import log_claim_feedback
from local_ai.agent_intake.review_claims import build_meeting_impression_claim
from local_ai.agent_intake.store import AgentStore
from local_ai.conversation.encounter import (
    _classify_readback_reply,
    _is_acknowledgment,
    _is_strict_readback_ack,
    parse_impression_response,
    split_impression_marker,
)
from local_ai.conversation.meeting import MeetingService, MeetingStore, _is_ceiling_filed
from local_ai.conversation.store import ConversationStore
from local_ai.presence_ingest.store import PresenceStore
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


# --------------------------------------------------------------------------
# Strict-ack positive allowlist
# --------------------------------------------------------------------------

#: Every pattern the fast path admits (audit §D + the verdict's complete
#: patterns). Each must classify "ack" and pass the strict check.
STRICT_ACK_PATTERNS = [
    "Ok sounds good",
    "Yeah, that's right",
    "Yes — that's exactly right.",
    "Yeah, that's about right",
    "Yeah, spot on",
    "Yes",
    "Yeah",
    "no problem",
    "no worries",
    "no complaints",
    "Yeah, that's exactly right",
    "Yes, that's right",
]

#: Near-misses: each must FAIL the strict check (and therefore enter the
#: merged correction-capable frame, never the fast path).
STRICT_ACK_NEAR_MISSES = [
    # The demonstrated hole: qualified agreement swallowed as affirmation.
    "That's relatively true generally yes",
    # The review's hand-traced holes.
    "Yeah, mostly right",
    "Yeah, not exactly",
    "Great, let's talk about the garden",
    "Cool, tell me about the garden.",
    # Long agreements (the 6-word cap is load-bearing).
    "Ya, that's pretty on the nose what I just said",
    "I definitely think you're understanding what I'm saying",
    # Questions and topic changes.
    "What about the garden?",
    "That's true! You got all that from our short conversation huh?",
    # Qualified in every direction (audit §D qualifier set).
    "Yeah, kind of",
    "Yeah, sort of",
    "Yeah, pretty much",
    "Yeah, more or less",
    "Yeah, for the most part",
    "Yeah, in a way",
    "Yeah, not quite",
    "Yeah, not really",
    "Yeah, I guess",
    "Yeah, I suppose",
    "Yeah, partly right",
    "Yeah, almost right",
    "Yeah, largely right",
    "Yeah, somewhat right",
    "Yeah, probably right",
    # Ack-prefixed other business.
    "Yeah, that's right — but what about the garden?",
    "Yeah, that's right, except I protect mornings first",
    # No ack phrase at all — the shared matcher itself returns False
    # for these, so they enter the frame (which judges them affirmed),
    # exactly as under the audit's wrapper design.
    "Hmm.",
    "Interesting.",
    "Close enough.",
    "That's fair.",
    "That's right",
    "That's true",
    "That's correct",
    # Bare residue words with no ack phrase ("right", "true",
    # "nailed it"): the shared matcher itself returns False for
    # these, so they enter the frame — exactly as under the audit's
    # wrapper design.
    "right",
    "true",
    "nailed it",
    "Mostly right — except I protect mornings first.",
    # Pass tokens and empty input: none of these may take the ack-only
    # reply frame ("The user has agreed with your first impression" —
    # founder review 2026-11-06). The turn function routes them to
    # the no-generation pass branch instead. "not sure" is the sharp
    # case: "sure" is an ack phrase, but "not" is not a residue word,
    # so the positive-composition check rejects it.
    "",
    "pass",
    "skip",
    "next",
    "next question",
    "another question",
    "different question",
    "idk",
    "i don't know",
    "not sure",
    "nope",
]


@pytest.mark.parametrize("reply", STRICT_ACK_PATTERNS)
def test_strict_ack_allowlist_passes(reply):
    assert _is_strict_readback_ack(reply) is True
    assert _classify_readback_reply(reply) == "ack"


@pytest.mark.parametrize("reply", STRICT_ACK_NEAR_MISSES)
def test_strict_ack_near_miss_fails(reply):
    assert _is_strict_readback_ack(reply) is False
    assert _classify_readback_reply(reply) != "ack"


def test_shared_acknowledgment_unchanged():
    """The shared matcher was NOT tightened: it still reads the loose
    ack its other callers (detect_move, completion-confirmation) rely
    on. The strictness lives only in the read-back allowlist."""
    assert _is_acknowledgment("Yeah, mostly right") is True
    assert _is_acknowledgment("That's relatively true generally yes") is True
    assert _is_acknowledgment("Yeah, that's right") is True
    assert _is_acknowledgment("Hmm.") is False
    assert _is_acknowledgment("Honestly? I don't buy that reading of me at all.") is False


def test_existing_classifier_assertions_still_hold():
    """The test_weaver_rewrite.py:234-243 classifier assertions, pinned
    here too so a classifier change cannot silently move them."""
    assert _classify_readback_reply("Ok sounds good") == "ack"
    assert _classify_readback_reply("Yeah, that's right") == "ack"
    assert _classify_readback_reply("Yes — that's exactly right.") == "ack"
    assert _classify_readback_reply("Actually, it's the opposite for me.") == "correction"
    assert _classify_readback_reply("Mostly right — except I protect mornings first.") == "correction"
    assert _classify_readback_reply("No — I plan everything first.") == "correction"
    assert _classify_readback_reply("Not quite — more like I follow whoever's calmest.") == "correction"
    assert _classify_readback_reply("Hmm.") == "other"
    assert _classify_readback_reply("Interesting.") == "other"
    assert _classify_readback_reply("Close enough.") == "other"


# --------------------------------------------------------------------------
# Marker parser (fail-closed)
# --------------------------------------------------------------------------

def test_marker_valid_all_six_combinations():
    """Every well-formed combination is valid — including revised x
    affirmed (founder ruling 2026-11-06 ~00:47 PT: agreement does not
    forbid revision)."""
    for seat in ("retained", "revised"):
        for visitor in ("affirmed", "disputed", "unresolved"):
            body, out_seat, out_visitor, failed = split_impression_marker(
                f"Some reply.\n[[impression:{seat}:{visitor}]]\n"
            )
            assert failed is False, f"{seat} x {visitor} failed"
            assert (out_seat, out_visitor) == (seat, visitor)
            assert body == "Some reply."
            assert "[[impression:" not in body


def test_marker_duplicate_fails_closed():
    body, seat, visitor, failed = split_impression_marker(
        "A reply.\n[[impression:retained:affirmed]]\n[[impression:revised:disputed]]\n"
    )
    assert failed is True
    assert seat is None and visitor is None
    assert "[[impression:" not in body
    assert body == "A reply."


def test_marker_missing_fails_closed():
    body, seat, visitor, failed = split_impression_marker("A plain reply.\n")
    assert failed is True
    assert seat is None and visitor is None
    assert body == "A plain reply."


@pytest.mark.parametrize("bad", [
    "[[impression:kept:affirmed]]",       # bad seat value
    "[[impression:retained:agreed]]",     # bad visitor value
    "[[impression: retained:affirmed]]",  # space after the colon
    "[[impression:retained: affirmed]]",  # space before the visitor
    "[[impression:Retained:affirmed]]",   # uppercase seat
    "[[impression:retained:Affirmed]]",   # uppercase visitor
    "[[impression:retained:affirmed]",    # missing closing bracket
    "[impression:retained:affirmed]]",    # single bracket
    "[[impression:retained]]",            # missing dimension
    "[[impression:retained:affirmed:extra]]",  # extra dimension
])
def test_marker_malformed_fails_closed(bad):
    body, seat, visitor, failed = split_impression_marker(f"A reply.\n{bad}\n")
    assert failed is True, bad
    assert seat is None and visitor is None
    assert "[[impression:" not in body


def test_marker_glued_to_spoken_line_fails_closed():
    """A marker glued to a spoken line does NOT count (malformed) —
    and its text is stripped from the line, keeping the spoken words."""
    body, seat, visitor, failed = split_impression_marker(
        "That's right. [[impression:retained:affirmed]]\n"
    )
    assert failed is True
    assert seat is None and visitor is None
    assert body == "That's right."
    assert "[[impression:" not in body


def test_marker_like_lines_stripped_from_spoken_body():
    body, seat, visitor, failed = split_impression_marker(
        "First line.\n[[impression:retained:affirmed]]\n"
        "[[impression: something half-formed\n"
        "Last line.\n"
    )
    assert failed is True
    assert "[[impression:" not in body
    assert body == "First line.\nLast line."


# --------------------------------------------------------------------------
# Response-turn parse (--- separation, Strands: handling)
# --------------------------------------------------------------------------

ORIGINAL_STRANDS = ["Compass", "Logic"]


def test_parse_revision():
    parsed = parse_impression_response(
        "Fair catch — you're right, the split was too clean.\n"
        "---\n"
        "A revised read: you hold both exhaustion and play at once.\n"
        "Strands: Compass, Logic\n"
        "[[impression:revised:disputed]]\n"
        "[[thread:settled]]\n",
        ORIGINAL_STRANDS,
    )
    assert parsed.failed is False
    assert parsed.spoken_reply == "Fair catch — you're right, the split was too clean."
    assert parsed.revised_claim == "A revised read: you hold both exhaustion and play at once."
    assert parsed.strands == ["Compass", "Logic"]
    assert parsed.seat_outcome == "revised"
    assert parsed.visitor_response == "disputed"
    assert parsed.thread_verdict == "settled"


def test_parse_revision_on_agreeing_new_information():
    """Revised x affirmed is VALID: an agreeing reply may volunteer
    new information that materially changes the interpretation."""
    parsed = parse_impression_response(
        "Yes, that's right — and one more thing: I protect mornings first.\n"
        "---\n"
        "A revised read: mornings are guarded, not avoided.\n"
        "Strands: Compass\n"
        "[[impression:revised:affirmed]]\n"
        "[[thread:settled]]\n",
        ORIGINAL_STRANDS,
    )
    assert parsed.failed is False
    assert parsed.seat_outcome == "revised"
    assert parsed.visitor_response == "affirmed"
    assert parsed.revised_claim == "A revised read: mornings are guarded, not avoided."
    assert parsed.strands == ["Compass"]


def test_parse_retain_without_delimiter():
    parsed = parse_impression_response(
        "That's fair — I stand by the read.\n"
        "[[impression:retained:disputed]]\n"
        "[[thread:open]]\n",
        ORIGINAL_STRANDS,
    )
    assert parsed.failed is False
    assert parsed.spoken_reply == "That's fair — I stand by the read."
    assert parsed.revised_claim == ""
    assert parsed.strands == ORIGINAL_STRANDS
    assert parsed.seat_outcome == "retained"
    assert parsed.visitor_response == "disputed"
    assert parsed.thread_verdict == "open"


def test_parse_retain_with_delimiter_block_ignored():
    """A retained marker with a --- block: the block is not stored —
    the stored text and strands stand."""
    parsed = parse_impression_response(
        "I hear you, and I stand by the read.\n"
        "---\n"
        "The same read, repeated.\n"
        "Strands: Compass, Logic\n"
        "[[impression:retained:disputed]]\n"
        "[[thread:open]]\n",
        ORIGINAL_STRANDS,
    )
    assert parsed.failed is False
    assert parsed.revised_claim == ""
    assert parsed.strands == ORIGINAL_STRANDS
    assert parsed.seat_outcome == "retained"


def test_parse_revised_without_delimiter_fails_closed():
    """A revised marker with no --- separator: the revised impression
    cannot be identified separately from the reply, so the revision
    cannot be stored honestly."""
    parsed = parse_impression_response(
        "You're right, it should read differently.\n"
        "[[impression:revised:disputed]]\n"
        "[[thread:settled]]\n",
        ORIGINAL_STRANDS,
    )
    assert parsed.failed is True
    assert parsed.seat_outcome == "unjudged"
    assert parsed.visitor_response == "unresolved"
    assert parsed.revised_claim == ""
    assert parsed.strands == ORIGINAL_STRANDS
    assert parsed.spoken_reply == "You're right, it should read differently."


def test_parse_revision_missing_strands_keeps_original():
    """Missing Strands: on a revision keeps the ORIGINAL strands —
    never an empty set (which would file a 'none' claim id)."""
    parsed = parse_impression_response(
        "Fair point.\n"
        "---\n"
        "A revised read with no strands line.\n"
        "[[impression:revised:disputed]]\n"
        "[[thread:settled]]\n",
        ORIGINAL_STRANDS,
    )
    assert parsed.failed is False
    assert parsed.seat_outcome == "revised"
    assert parsed.strands == ORIGINAL_STRANDS
    assert parsed.revised_claim == "A revised read with no strands line."


def test_parse_empty_revised_block_fails_closed():
    parsed = parse_impression_response(
        "Fair point.\n"
        "---\n"
        "Strands: Compass\n"
        "[[impression:revised:disputed]]\n"
        "[[thread:settled]]\n",
        ORIGINAL_STRANDS,
    )
    assert parsed.failed is True
    assert parsed.seat_outcome == "unjudged"
    assert parsed.visitor_response == "unresolved"
    assert parsed.revised_claim == ""


def test_parse_marker_in_reply_portion_is_misplaced():
    parsed = parse_impression_response(
        "I agree. [[impression:retained:affirmed]]\n"
        "---\n"
        "Some revised text.\n"
        "[[impression:revised:disputed]]\n"
        "[[thread:settled]]\n",
        ORIGINAL_STRANDS,
    )
    assert parsed.failed is True
    assert parsed.seat_outcome == "unjudged"
    assert parsed.visitor_response == "unresolved"


def test_parse_empty_generation_fails_closed():
    parsed = parse_impression_response("", ORIGINAL_STRANDS)
    assert parsed.failed is True
    assert parsed.seat_outcome == "unjudged"
    assert parsed.visitor_response == "unresolved"
    assert parsed.spoken_reply == ""
    assert parsed.revised_claim == ""


def test_parse_spoken_reply_never_reaches_the_claim():
    """The spoken reply is the reply portion only; the revised block
    is the only text that can become the impression."""
    parsed = parse_impression_response(
        "Conversational acknowledgment, warm and brief.\n"
        "---\n"
        "The revised impression, in the seat's own words.\n"
        "Strands: Compass\n"
        "[[impression:revised:affirmed]]\n"
        "[[thread:settled]]\n",
        ORIGINAL_STRANDS,
    )
    assert "Conversational acknowledgment" in parsed.spoken_reply
    assert "Conversational acknowledgment" not in parsed.revised_claim
    assert parsed.revised_claim == "The revised impression, in the seat's own words."


# --------------------------------------------------------------------------
# Prompt-cap guard (the 8000 -> 9000 consequence)
# --------------------------------------------------------------------------

def test_engage_frames_fit_the_prompt_cap():
    """The read-back frames lengthened the engage frame (which embeds
    the full readback frame as prepared context). The Weaver frame hit
    8375 chars — past the old 8000 cap, which silently truncated the
    capability block's intention line and honesty guard off every
    Weaver engage turn. The cap is _EXTRA_INSTRUCTIONS_CAP; every
    seat's engage frame must fit it. Level 1 (2026-11-10): the
    intention line and honesty guard no longer ride the frame — they
    ride the canonical tier, an uncapped section immediately before
    the frame, so frame-cap truncation can never touch them
    (asserted in the tier by T-L1-1, tests/test_canonical_tier.py)."""
    from local_ai.conversation import encounter as ENC
    from local_ai.conversation.reply import _EXTRA_INSTRUCTIONS_CAP as cap
    from local_ai.council import capabilities as CAP
    from local_ai.council import meetings as MT

    for arch in ("conductor", "mentor", "champion", "ambassador", "skeptic", "maverick", "guardian"):
        definition = ENC.get_definition(MT.get_script(arch, 1))
        frame = ENC.EncounterRuntime(definition)._engage_frame()
        assert len(frame) <= cap, f"{arch}: engage frame {len(frame)} chars exceeds {cap}"
        capped = frame[:cap]
        assert CAP.INTENTION_LINE not in capped, f"{arch}: intention line in frame"
        assert CAP.HONESTY_GUARD not in capped, f"{arch}: honesty guard in frame"


def test_truncated_section_logs_loudly(caplog):
    """Founder review (2026-11-06): silently truncating a section was
    the worse finding; raising the cap treats the symptom. Any slice
    that actually cuts content now emits one warning log line naming
    the section, the archetype, the original length, and the cap —
    and the turn still runs with the sliced section (a log, not an
    assertion: a truncated section degrades the turn but must never
    crash it). Under-cap prompts log nothing."""
    import logging

    from local_ai.conversation import reply as R

    with caplog.at_level(logging.WARNING, logger="local_ai.conversation.reply"):
        prompt, _ = R.build_voice_prompt(
            "u1", "champion", "hello", [],
            extra_instructions="x" * (R._EXTRA_INSTRUCTIONS_CAP + 500),
        )
    lines = prompt
    assert any(len(line) == R._EXTRA_INSTRUCTIONS_CAP for line in lines)
    warnings = [
        rec for rec in caplog.records
        if "prompt section truncated" in rec.getMessage()
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "section=extra_instructions" in msg
    assert "archetype=champion" in msg
    assert f"original_chars={R._EXTRA_INSTRUCTIONS_CAP + 500}" in msg
    assert f"cap={R._EXTRA_INSTRUCTIONS_CAP}" in msg

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="local_ai.conversation.reply"):
        prompt, _ = R.build_voice_prompt(
            "u1", "champion", "hello", [],
            extra_instructions="short frame",
            thread_summary="s" * (R._THREAD_SUMMARY_CAP + 100),
            context_hint="c" * (R._CONTEXT_HINT_CAP + 50),
        )
    joined = "\n".join(prompt)
    assert "short frame" in joined
    truncated = [
        rec.getMessage() for rec in caplog.records
        if "prompt section truncated" in rec.getMessage()
    ]
    assert any("section=thread_summary" in m for m in truncated)
    assert any("section=context_hint" in m for m in truncated)
    assert not any("section=extra_instructions" in m for m in truncated)


# --------------------------------------------------------------------------
# Stored corpus (audit §I + Fox reply) — classifier and routing only
# --------------------------------------------------------------------------

#: (number, reply verbatim, old-kind, new-kind) — the 13 archived Weaver
#: replies plus the live Fox reply. Routing: every one enters the merged
#: correction-capable frame (none is a strict ack); the frame judges.
CORPUS = [
    (1, "Other than the fact that you phrased it like an ad lib, ya that's right", "other"),
    (2, "Ya, that's pretty on the nose what I just said", "other"),
    (3, "Well, I don't know you that well nor the specifics of what you're contending with but, yes, it does seem like you're more actionably \"itinerary\" based than is my natural proclivity", "other"),
    (4, "I can understand your perspective also. \"Optimal\" is often a moving target with these things and I'll be the first to admit that I can be so adamant about listening that I never actually follow through. Adapting towards oblivion until nothing of the original proposition even remains", "correction"),
    (5, "I definitely think you're understanding what I'm saying", "other"),
    (6, "This does feel like extraordinary circumstances but I do like to be helpful", "correction"),
    (7, "I parse it as a scope thing. \"We are all one\" is not an acceptable answer to \"rent is due\"", "other"),
    (8, "That's relatively true generally yes", "other"),
    (9, "Oh, you are definitely right! It has cost me much! I just prefer an honest \"nothing\" to a dishonest \"everything\" (if you catch what I mean)", "other"),
    (10, "I'm not sure I know what you mean exactly and I feel like we're talking in circles a bit but… can you tell me about this ap a little bit?", "other"),
    (11, "Oh, no, not too far at all. Very perceptive of you! And that IS a good line. \"The job shifts to holding a form where different lines can pass through\" I think that's right! And we'll said", "other"),
    (12, "It depends on the day but i'm a big fan of a well-made, peanut butter and jelly sandwich", "correction"),
    (13, "That's true! You got all that from our short conversation huh?", "other"),
    ("fox", "Another false dichotomy… or can someone not still play in their exhaustion?", "other"),
]


@pytest.mark.parametrize("number,reply,kind", CORPUS)
def test_corpus_reply_routes_to_the_frame(number, reply, kind):
    """No stored reply takes the ack fast path — including #8, the one
    qualified agreement the old matcher swallowed as an affirmation.
    The classifier kind is pinned; the route is the merged frame for
    all of them, where the character judges."""
    assert _classify_readback_reply(reply) == kind
    assert _is_strict_readback_ack(reply) is False


def test_corpus_negative_controls_do_not_auto_revise():
    """#4, #6, #12 were keyword misfires under the old classifier: the
    old correction route REVISED the stored impression on agreements.
    Under the new routing, the route itself never revises — a markerless
    generation is the fail-safe, and the original stands."""
    for number in (4, 6, 12):
        reply = next(r for n, r, _ in CORPUS if n == number)
        assert _is_strict_readback_ack(reply) is False
        parsed = parse_impression_response("A plain reply.\n", ORIGINAL_STRANDS)
        assert parsed.failed is True
        assert parsed.revised_claim == ""


def test_corpus_genuine_corrections_route_to_the_frame():
    """#7 (substantive reframe) and the Fox reply (framing challenge)
    both routed to "other" under the old classifier — the correction
    frame never fired. Under the new routing they enter the merged
    correction-capable frame."""
    for number in (7, "fox"):
        reply = next(r for n, r, _ in CORPUS if n == number)
        assert _classify_readback_reply(reply) == "other"
        assert _is_strict_readback_ack(reply) is False


# --------------------------------------------------------------------------
# Persistence (MeetingStore + service)
# --------------------------------------------------------------------------

def test_meeting_columns_exist_on_both_tables(tmp_path):
    store = MeetingStore(tmp_path / "meetings.db")
    meetings_cols = {r[1] for r in store._conn.execute("PRAGMA table_info(meetings)")}
    archive_cols = {r[1] for r in store._conn.execute("PRAGMA table_info(meeting_archives)")}
    for col in ("readback_original_claim", "readback_seat_outcome", "readback_visitor_response"):
        assert col in meetings_cols, col
        assert col in archive_cols, col


def test_meeting_update_allowlist_accepts_new_columns(tmp_path):
    store = MeetingStore(tmp_path / "meetings.db")
    store.create("u1", "conductor", 1)
    row = store.update(
        "u1", "conductor", 1,
        readback_original_claim="original",
        readback_seat_outcome="revised",
        readback_visitor_response="disputed",
    )
    assert row["readback_original_claim"] == "original"
    assert row["readback_seat_outcome"] == "revised"
    assert row["readback_visitor_response"] == "disputed"


def test_store_impression_set_if_empty_original(tmp_path):
    store = MeetingStore(tmp_path / "meetings.db")
    store.create("u1", "conductor", 1)
    store.store_impression("u1", "conductor", 1, "First read.", ["Compass"])
    row = store.get("u1", "conductor", 1)
    assert row["readback_claim"] == "First read."
    assert row["readback_original_claim"] == "First read."
    # A revision replaces the claim and strands but never the original.
    store.store_impression("u1", "conductor", 1, "Revised read.", ["Logic"])
    row = store.get("u1", "conductor", 1)
    assert row["readback_claim"] == "Revised read."
    assert row["readback_strands"] == '["Logic"]'
    assert row["readback_original_claim"] == "First read."


def test_meeting_migration_adds_columns_to_existing_db(tmp_path):
    """A store created before the columns landed gets them via the
    ALTER TABLE migration (no backfill — existing rows keep '')."""
    path = tmp_path / "meetings.db"
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE meetings (user_id TEXT NOT NULL, archetype_id TEXT NOT NULL, "
        "keystone_index INTEGER NOT NULL, readback_claim TEXT NOT NULL DEFAULT '', "
        "PRIMARY KEY (user_id, archetype_id, keystone_index));"
        "CREATE TABLE meeting_archives (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "user_id TEXT NOT NULL, archetype_id TEXT NOT NULL, keystone_index INTEGER NOT NULL, "
        "transcript_json TEXT NOT NULL DEFAULT '[]', readback_claim TEXT NOT NULL DEFAULT '');"
    )
    conn.execute(
        "INSERT INTO meetings (user_id, archetype_id, keystone_index, readback_claim) "
        "VALUES ('u1', 'conductor', 1, 'old read')"
    )
    conn.commit()
    conn.close()
    store = MeetingStore(path)
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(meetings)")}
    archive_cols = {r[1] for r in store._conn.execute("PRAGMA table_info(meeting_archives)")}
    for col in ("readback_original_claim", "readback_seat_outcome", "readback_visitor_response"):
        assert col in cols and col in archive_cols
    row = store.get("u1", "conductor", 1)
    assert row["readback_claim"] == "old read"
    assert row["readback_original_claim"] == ""


# --------------------------------------------------------------------------
# Service-level response turns (MarkerGen: the merged frame's generation
# is canned per test; the ack frame's is a brief reply)
# --------------------------------------------------------------------------

class MarkerGen:
    """Fake generation: the read-back offers the canned impression; the
    merged correction-capable frame returns the configured reply; the
    ack-only frame returns a brief reply. No model calls."""

    def __init__(self, merged_reply: str):
        self.merged_reply = merged_reply
        self.prompts: list[str] = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "The user has replied to your first impression" in prompt:
            return self.merged_reply
        if "The user has agreed with your first impression" in prompt:
            return "Heard, thank you.\n[[thread:settled]]"
        if "READ-BACK" in prompt:
            return (
                "A first impression, anchored in your words — correct me."
                "\nStrands: Compass, Logic"
            )
        if "ENCOUNTER" in prompt:
            return "An engaged reply that hears two tensions together."
        return "A plain reply."


def _svc(tmp_path, gen):
    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=gen,
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _seeded_user(email="readback@example.com"):
    user = ve.create_user_account(email, "pw", "Meet")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _mark_entry_done(uid):
    """Entry-gate setup (Guardian-first): mark the entry seat's
    keystone 1 Done via the task-update path so the Conductor's
    meeting (the readback vehicle) may begin."""
    from local_ai.conversation.meeting import _seat_keystone_tasks
    from local_ai.vision_execution import models as ve_models

    entry = keystone_seeding.ENTRY_SEAT_REF
    tasks = _seat_keystone_tasks(uid, entry)
    assert tasks, "seeded user has no entry-seat keystone tasks"
    if tasks[0]["status"] != "Done":
        ve.update_task(tasks[0]["id"], ve_models.TaskUpdate(status="Done"), uid)


def _to_readback(svc, uid):
    _mark_entry_done(uid)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I triage by what breaks first if I ignore it.")
    svc.turn(
        uid, "conductor",
        "And in my own work it's the same — what breaks first gets my hands first.",
    )
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"].startswith("A first impression")
    assert row["readback_original_claim"] == row["readback_claim"]
    return row


def _bodies(state):
    return [m.get("body", "") for m in state.get("messages", [])]


def test_service_revision_stores_only_the_revised_block(ve_ctx, tmp_path):
    gen = MarkerGen(
        "Fair catch — you're right, the split was too clean.\n"
        "---\n"
        "A revised read: you hold both exhaustion and play at once.\n"
        "Strands: Compass, Logic\n"
        "[[impression:revised:disputed]]\n"
        "[[thread:settled]]\n"
    )
    svc = _svc(tmp_path, gen)
    uid = _seeded_user()
    original = _to_readback(svc, uid)["readback_claim"]
    state = svc.turn(uid, "conductor", "Another false dichotomy — I can play in my exhaustion.")
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == "A revised read: you hold both exhaustion and play at once."
    assert row["readback_original_claim"] == original
    assert row["readback_seat_outcome"] == "revised"
    assert row["readback_visitor_response"] == "disputed"
    bodies = _bodies(state)
    assert any("Fair catch" in b for b in bodies)
    assert any("A revised read" in b for b in bodies)
    assert not any("[[impression:" in b for b in bodies)


def test_service_revised_affirmed_is_valid(ve_ctx, tmp_path):
    gen = MarkerGen(
        "Yes — and one more thing: mornings are guarded.\n"
        "---\n"
        "A revised read: mornings are guarded, not avoided.\n"
        "Strands: Compass\n"
        "[[impression:revised:affirmed]]\n"
        "[[thread:settled]]\n"
    )
    svc = _svc(tmp_path, gen)
    uid = _seeded_user()
    _to_readback(svc, uid)
    svc.turn(uid, "conductor", "Yes, that's right — and I protect mornings first.")
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_seat_outcome"] == "revised"
    assert row["readback_visitor_response"] == "affirmed"
    assert row["readback_claim"].startswith("A revised read:")


def test_service_archived_agreement_with_new_information_revises_affirmed(ve_ctx, tmp_path):
    """End-to-end fixture for the founder's revised x affirmed check
    (review item 1): archived reply #6 agrees AND volunteers new
    substantive information ("I do like to be helpful"), and the live
    fixture run produced [[impression:revised:affirmed]] through the
    real correction frame. The deterministic half pins the path: the
    real frame reaches the generator, the marker parses, and the row
    stores revised/affirmed with the original preserved."""
    gen = MarkerGen(
        "That tracks — a standing habit of pitching in makes holding a single line more sustainable.\n"
        "---\n"
        "A revised read: you have wider range than the single spot you're holding now, narrowed here by pressure rather than preference. Liking to be helpful reads as a steady part of you, not just cover for the moment.\n"
        "Strands: Heart, Compass\n"
        "[[impression:revised:affirmed]]\n"
        "[[thread:settled]]\n"
    )
    svc = _svc(tmp_path, gen)
    uid = _seeded_user()
    original = _to_readback(svc, uid)["readback_claim"]
    state = svc.turn(
        uid, "conductor",
        "This does feel like extraordinary circumstances but I do like to be helpful",
    )
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_seat_outcome"] == "revised"
    assert row["readback_visitor_response"] == "affirmed"
    assert row["readback_claim"].startswith("A revised read:")
    assert row["readback_original_claim"] == original
    assert row["readback_strands"] == '["Heart", "Compass"]'
    # The generation went through the REAL correction frame, not just
    # any prompt: the frame's revise-on-agreement sentence is in the
    # prompt the generator received.
    assert any(
        "If their agreement volunteers additional substantive information "
        "that materially changes the interpretation, revise the impression "
        "on that new information: agreement does not forbid revision." in p
        for p in gen.prompts
    )
    bodies = _bodies(state)
    assert not any("[[impression:" in b for b in bodies)


def test_service_fail_safe_writes_unjudged_unresolved(ve_ctx, tmp_path):
    gen = MarkerGen("A plain reply with no marker at all.\n[[thread:settled]]\n")
    svc = _svc(tmp_path, gen)
    uid = _seeded_user()
    original = _to_readback(svc, uid)["readback_claim"]
    state = svc.turn(uid, "conductor", "Mostly right — except I protect mornings first.")
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == original
    assert row["readback_original_claim"] == original
    assert row["readback_seat_outcome"] == "unjudged"
    assert row["readback_visitor_response"] == "unresolved"
    assert not any("[[impression:" in b for b in _bodies(state))


def test_service_strict_ack_writes_retained_affirmed(ve_ctx, tmp_path):
    gen = MarkerGen("UNUSED — the ack path never calls the merged frame.")
    svc = _svc(tmp_path, gen)
    uid = _seeded_user()
    original = _to_readback(svc, uid)["readback_claim"]
    svc.turn(uid, "conductor", "Yeah, that's right.")
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == original
    assert row["readback_seat_outcome"] == "retained"
    assert row["readback_visitor_response"] == "affirmed"
    assert not any(
        "The user has replied to your first impression" in p for p in gen.prompts
    )


def test_service_pass_writes_retained_unresolved(ve_ctx, tmp_path):
    gen = MarkerGen("UNUSED — a pass never generates.")
    svc = _svc(tmp_path, gen)
    uid = _seeded_user()
    original = _to_readback(svc, uid)["readback_claim"]
    svc.turn(uid, "conductor", "not sure")
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == original
    assert row["readback_seat_outcome"] == "retained"
    assert row["readback_visitor_response"] == "unresolved"
    assert not any(
        "The user has replied to your first impression" in p for p in gen.prompts
    )
    assert not any(
        "The user has agreed with your first impression" in p for p in gen.prompts
    )


def test_service_fox_pass_speaks_fallback(ve_ctx, tmp_path):
    """Fox fallback line (founder review 2026-11-06): the Maverick
    had no fallback line — the generic base sets fallback_line=""
    and the k1 builder copied it, so an empty/pass reply spoke
    nothing this turn. A pass on Fox now speaks the Fox fallback
    line and records retained x unresolved — and never reaches the
    ack-only frame (the strict-ack allowlist cannot match "pass")."""
    gen = MarkerGen("UNUSED — a pass never generates.")
    svc = _svc(tmp_path, gen)
    uid = _seeded_user()
    # The Guardian opens the council: her keystone 1 is Done (the
    # _to_readback setup), the Weaver's meeting completes, then the
    # Fox's opens.
    _to_readback(svc, uid)
    svc.turn(uid, "conductor", "Yeah, that's right.")
    svc.complete(uid, "conductor")
    svc.start(uid, "maverick")
    # Drive the Fox meeting until the read-back is offered.
    for _ in range(6):
        row = svc.meetings.get(uid, "maverick", 1)
        if row and row["readback_claim"]:
            break
        svc.turn(uid, "maverick", "I triage by what breaks first if I ignore it.")
    row = svc.meetings.get(uid, "maverick", 1)
    assert row["readback_claim"].startswith("A first impression")
    prompts_before_fox_pass = len(gen.prompts)
    state = svc.turn(uid, "maverick", "pass")
    row = svc.meetings.get(uid, "maverick", 1)
    assert row["readback_seat_outcome"] == "retained"
    assert row["readback_visitor_response"] == "unresolved"
    assert any("slipped through the hedge" in b for b in _bodies(state))
    # The conductor's own ack turn earlier in this test legitimately
    # used the ack-only frame; the assertion covers only the Fox pass.
    assert not any(
        "The user has agreed with your first impression" in p
        for p in gen.prompts[prompts_before_fox_pass:]
    )


def test_service_archive_carries_the_three_columns(ve_ctx, tmp_path):
    gen = MarkerGen(
        "Fair catch.\n"
        "---\n"
        "A revised read.\n"
        "Strands: Compass, Logic\n"
        "[[impression:revised:disputed]]\n"
        "[[thread:settled]]\n"
    )
    svc = _svc(tmp_path, gen)
    uid = _seeded_user()
    _to_readback(svc, uid)
    svc.turn(uid, "conductor", "Another false dichotomy.")
    svc.complete(uid, "conductor")
    svc.restart(uid, "conductor")
    archives = svc.meetings.list_archives(uid, "conductor", 1)
    assert len(archives) == 1
    archived = archives[0]
    assert archived["readback_seat_outcome"] == "revised"
    assert archived["readback_visitor_response"] == "disputed"
    assert archived["readback_claim"] == "A revised read."
    assert archived["readback_original_claim"].startswith("A first impression")


# --------------------------------------------------------------------------
# Filing / review (builder + service filing)
# --------------------------------------------------------------------------

def test_builder_carries_dimensions_and_original():
    claim = build_meeting_impression_claim(
        agent_id="meeting-conductor-1",
        seat_name="Weaver",
        readback_claim="Revised read.",
        readback_response="Another false dichotomy.",
        strand_keys=["self", "number"],
        run_key="run123",
        readback_original_claim="First read.",
        readback_seat_outcome="revised",
        readback_visitor_response="disputed",
    )
    assert claim.id == "meeting-conductor-1:impression:self+number:run123"
    assert claim.inference == "Revised read."
    assert claim.readback_visitor_response == "disputed"
    assert claim.readback_seat_outcome == "revised"
    assert claim.readback_original_claim == "First read."
    assert "First read." in claim.detail
    assert "revised" in claim.detail and "disputed" in claim.detail
    assert "Read-back outcome:" in claim.detail


def test_builder_retain_with_dispute():
    claim = build_meeting_impression_claim(
        agent_id="meeting-conductor-1",
        seat_name="Weaver",
        readback_claim="First read.",
        readback_response="I don't buy that reading of me at all.",
        strand_keys=["self"],
        run_key="run123",
        readback_original_claim="First read.",
        readback_seat_outcome="retained",
        readback_visitor_response="disputed",
    )
    assert claim.inference == "First read."
    assert "retained" in claim.detail and "disputed" in claim.detail
    # The original is the inference here — it is not repeated in the detail.
    assert claim.detail.count("First read.") == 1


def test_builder_fail_safe_notation():
    claim = build_meeting_impression_claim(
        agent_id="meeting-conductor-1",
        seat_name="Weaver",
        readback_claim="First read.",
        readback_response="Mostly right.",
        strand_keys=["self"],
        run_key="run123",
        readback_original_claim="First read.",
        readback_seat_outcome="unjudged",
        readback_visitor_response="unresolved",
    )
    assert "not recorded" in claim.detail
    assert "marker failed to parse" in claim.detail
    assert claim.readback_seat_outcome == "unjudged"
    assert claim.readback_visitor_response == "unresolved"


def test_builder_ceiling_label_corrected():
    """Amendment 5: a ceiling filing never mislabels the longest turn
    as the visitor's answer to the impression."""
    claim = build_meeting_impression_claim(
        agent_id="meeting-conductor-1",
        seat_name="Weaver",
        readback_claim="First read.",
        readback_response="The longest user turn of the meeting.",
        strand_keys=["self"],
        run_key="run123",
        readback_original_claim="First read.",
        readback_seat_outcome="",
        readback_visitor_response="",
        ceiling_filed=True,
    )
    assert "Your answer, word for word" not in claim.detail
    assert "not an answer to it" in claim.detail
    assert "never answered" in claim.detail
    assert claim.readback_visitor_response == "unresolved"
    assert claim.readback_seat_outcome == ""


def test_builder_legacy_dimensions_not_recorded():
    claim = build_meeting_impression_claim(
        agent_id="meeting-conductor-1",
        seat_name="Weaver",
        readback_claim="First read.",
        readback_response="Yes.",
        strand_keys=["self"],
        run_key="run123",
    )
    assert claim.readback_visitor_response == ""
    assert claim.readback_seat_outcome == ""
    assert "not recorded" in claim.detail
    assert "retained" not in claim.detail


def test_ceiling_filed_distinguisher():
    assert _is_ceiling_filed({"state_json": json.dumps({"impression_answered": False})}) is True
    assert _is_ceiling_filed({"state_json": json.dumps({"impression_answered": True})}) is False
    assert _is_ceiling_filed({"state_json": ""}) is False
    assert _is_ceiling_filed({"state_json": "not json"}) is False
    assert _is_ceiling_filed({}) is False


def test_service_filing_carries_dimensions_and_original(ve_ctx, tmp_path):
    gen = MarkerGen(
        "Fair catch.\n"
        "---\n"
        "A revised read.\n"
        "Strands: Compass, Logic\n"
        "[[impression:revised:disputed]]\n"
        "[[thread:settled]]\n"
    )
    svc = _svc(tmp_path, gen)
    uid = _seeded_user()
    _to_readback(svc, uid)
    svc.turn(uid, "conductor", "Another false dichotomy.")
    svc.complete(uid, "conductor")
    store = AgentStore(tmp_path / "agents.db", user_id=uid)
    claims = store.get_claims("meeting-conductor-1")
    assert len(claims) == 1
    claim = claims[0]
    assert claim.inference == "A revised read."
    assert claim.readback_visitor_response == "disputed"
    assert claim.readback_seat_outcome == "revised"
    assert claim.readback_original_claim.startswith("A first impression")
    assert "A first impression" in claim.detail
    assert "revised" in claim.detail and "disputed" in claim.detail
    assert claim.to_dict()["readback_visitor_response"] == "disputed"


# --------------------------------------------------------------------------
# Training boundary (verdict amendment 4)
# --------------------------------------------------------------------------

def _feedback_signals(tmp_path, claim_id, claim_type, action, visitor_response):
    # A fresh signals DB per call: the store accumulates, and a shared
    # DB would count earlier calls' signals.
    import uuid

    presence = PresenceStore(tmp_path / f"signals-{uuid.uuid4().hex}.db")
    log_claim_feedback(
        agent_id="meeting-conductor-1",
        claim_id=claim_id,
        claim_type=claim_type,
        claim_title="First impression — Weaver",
        action=action,
        user_id="u1",
        evidence="Some answer.",
        inference="Some read.",
        presence_store=presence,
        readback_visitor_response=visitor_response,
    )
    return presence.list_signals_by_kind("claim_feedback")


def test_training_gate_blocks_disputed_accept(tmp_path):
    signals = _feedback_signals(
        tmp_path,
        "meeting-conductor-1:impression:self+number:run1",
        "meeting_impression", "accepted", "disputed",
    )
    assert len(signals) == 2
    for s in signals:
        # Recorded, but NOT an affirmative characterization signal.
        assert s.valence == "observed"
        assert s.layer == "guidance"
        assert s.provenance["action"] == "accepted"
        assert s.provenance["readback_visitor_response"] == "disputed"
        assert "disputed" in (s.correction_diff or "")


def test_training_gate_blocks_unresolved_accept(tmp_path):
    signals = _feedback_signals(
        tmp_path,
        "meeting-conductor-1:impression:self+number:run1",
        "meeting_impression", "accepted", "unresolved",
    )
    assert len(signals) == 2
    for s in signals:
        assert s.valence == "observed"
        assert s.layer == "guidance"
        assert s.provenance["action"] == "accepted"


def test_training_gate_affirmed_accept_behaves_as_before(tmp_path):
    signals = _feedback_signals(
        tmp_path,
        "meeting-conductor-1:impression:self+number:run1",
        "meeting_impression", "accepted", "affirmed",
    )
    assert len(signals) == 2
    for s in signals:
        assert s.valence == "endorsed"
        assert s.layer == "behavior"
        assert s.provenance["action"] == "accepted"


def test_training_gate_legacy_empty_response_does_not_fire(tmp_path):
    signals = _feedback_signals(
        tmp_path,
        "meeting-conductor-1:impression:self+number:run1",
        "meeting_impression", "accepted", "",
    )
    assert len(signals) == 2
    for s in signals:
        assert s.valence == "endorsed"
        assert s.layer == "behavior"


def test_training_gate_only_applies_to_meeting_impressions(tmp_path):
    signals = _feedback_signals(
        tmp_path,
        "agent-1:strand:self:m1",
        "strand", "accepted", "disputed",
    )
    for s in signals:
        assert s.valence == "endorsed"
        assert s.layer == "behavior"


def test_training_gate_other_actions_unchanged(tmp_path):
    for action, valence, layer in (
        ("rejected", "rejected", "behavior"),
        ("corrected", "corrected", "guidance"),
        ("explained", "corrected", "guidance"),
        ("unresolved", "observed", "guidance"),
    ):
        signals = _feedback_signals(
            tmp_path,
            "meeting-conductor-1:impression:self+number:run1",
            "meeting_impression", action, "disputed",
        )
        assert len(signals) == 2
        for s in signals:
            assert s.valence == valence
            assert s.layer == layer
