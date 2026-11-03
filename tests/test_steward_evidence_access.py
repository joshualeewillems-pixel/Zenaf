"""Narrowed Phase 1 tests: provenance envelope, durability
determination, ownership guard (rev2 section 3, E1-E4).

No database, no store, no model: the determination's live re-fetch
and carrier lookup are caller-supplied callables, so fixtures are
in-memory fakes. That is the point — Phase 1 has no consumers and
no read invocation, and these tests prove the rules the future
callers must satisfy, not any store's behavior.

E5 (existing suite unmodified apart from this file, separation AST
tests passing) is covered by running the suites, not by a test here.
"""

import ast
from dataclasses import fields
from pathlib import Path

import pytest

from local_ai.narrative.evidence_access import (
    CarrierRef,
    DurabilityOutcome,
    EvidenceEnvelope,
    OwnershipRefusal,
    determine_durability,
    guard_row,
    guard_rows,
)

# Field names that must never appear on the envelope. These strings
# appear here ONLY as the forbidden list for the negative test — not
# as fields, assignments, or values produced by the module.
FORBIDDEN_ENVELOPE_FIELDS = {
    "act_kind",
    "act-kind",
    "significance",
    "recognition",
    "interpretation",
    "kind",
}

EXPECTED_ENVELOPE_FIELDS = (
    "source_system",
    "source_ids",
    "speaker_or_author",
    "timestamp",
    "form",
    "durability",
    "content",
    "stored_type_text",
    "about_target",
)


# -- E1: envelope field-for-field contents, one per source kind --------


def test_envelope_live_message():
    env = EvidenceEnvelope(
        source_system="conversation",
        source_ids=("conv-1", "msg-7"),
        speaker_or_author="user",
        timestamp="2026-11-03T10:00:00",
        form="verbatim",
        durability="RETRIEVABLE",
        content="I spent most of yesterday helping Sarah with the website.",
        stored_type_text=None,
        about_target="conv-1",
    )
    assert env.source_system == "conversation"
    assert env.source_ids == ("conv-1", "msg-7")
    assert env.speaker_or_author == "user"
    assert env.timestamp == "2026-11-03T10:00:00"
    assert env.form == "verbatim"
    assert env.durability == "RETRIEVABLE"
    assert env.content == "I spent most of yesterday helping Sarah with the website."
    assert env.stored_type_text is None
    assert env.about_target == "conv-1"


def test_envelope_live_decision_record():
    env = EvidenceEnvelope(
        source_system="ve_decisions",
        source_ids=("dec-9",),
        speaker_or_author="user",
        timestamp="2026-11-03T10:05:00",
        form="verbatim",
        durability="RETRIEVABLE",
        content="Adopt the morning routine.",
        stored_type_text="decision",
        about_target="initiative:morning-routine",
    )
    assert env.source_system == "ve_decisions"
    assert env.source_ids == ("dec-9",)
    assert env.stored_type_text == "decision"
    assert env.about_target == "initiative:morning-routine"


def test_envelope_evidence_note_quote():
    env = EvidenceEnvelope(
        source_system="conversation",
        source_ids=("conv-1", "msg-7"),
        speaker_or_author="user",
        timestamp="2026-11-03T10:00:00",
        form="quoted",
        durability="QUOTED",
        content="I spent most of yesterday helping Sarah with the website.",
        stored_type_text=None,
        about_target="conv-1",
    )
    assert env.form == "quoted"
    assert env.durability == "QUOTED"
    assert env.content == "I spent most of yesterday helping Sarah with the website."


def test_envelope_unavailable_citation():
    env = EvidenceEnvelope(
        source_system="conversation",
        source_ids=("conv-1", "msg-7"),
        speaker_or_author="user",
        timestamp="2026-11-03T10:00:00",
        form="verbatim",
        durability="UNAVAILABLE",
        content=None,
        stored_type_text=None,
        about_target="conv-1",
    )
    assert env.durability == "UNAVAILABLE"
    assert env.content is None
    # The ids and the loss fact are all an UNAVAILABLE envelope may
    # present; the ids themselves are still carried.
    assert env.source_ids == ("conv-1", "msg-7")


def test_envelope_source_ids_list_normalized():
    env = EvidenceEnvelope(
        source_system="conversation",
        source_ids=["conv-1", "msg-7"],
        speaker_or_author="user",
        timestamp="2026-11-03T10:00:00",
        form="verbatim",
        durability="RETRIEVABLE",
        content="hi",
        stored_type_text=None,
        about_target="conv-1",
    )
    assert env.source_ids == ("conv-1", "msg-7")


# -- E2: negative tests -------------------------------------------------


def test_envelope_has_exactly_the_contract_fields():
    names = tuple(f.name for f in fields(EvidenceEnvelope))
    assert names == EXPECTED_ENVELOPE_FIELDS
    assert not (set(names) & FORBIDDEN_ENVELOPE_FIELDS)


def test_stored_type_text_is_quoted_data_not_a_category():
    # The stored type string passes through verbatim, unmapped: a
    # generic stored string stays generic. The read path never
    # upgrades it into a semantic kind.
    env = EvidenceEnvelope(
        source_system="ve_decisions",
        source_ids=("dec-9",),
        speaker_or_author="user",
        timestamp="2026-11-03T10:05:00",
        form="verbatim",
        durability="RETRIEVABLE",
        content="Something happened.",
        stored_type_text="note",
        about_target="initiative:x",
    )
    assert env.stored_type_text == "note"


def test_unavailable_envelope_cannot_carry_content():
    with pytest.raises(ValueError):
        EvidenceEnvelope(
            source_system="conversation",
            source_ids=("conv-1", "msg-7"),
            speaker_or_author="user",
            timestamp="2026-11-03T10:00:00",
            form="verbatim",
            durability="UNAVAILABLE",
            content="reconstructed from memory",
            stored_type_text=None,
            about_target="conv-1",
        )


def test_envelope_rejects_unknown_form_and_durability():
    base = dict(
        source_system="conversation",
        source_ids=("conv-1", "msg-7"),
        speaker_or_author="user",
        timestamp="2026-11-03T10:00:00",
        content="hi",
        stored_type_text=None,
        about_target="conv-1",
    )
    with pytest.raises(ValueError):
        EvidenceEnvelope(form="paraphrase", durability="RETRIEVABLE", **base)
    with pytest.raises(ValueError):
        EvidenceEnvelope(form="verbatim", durability="MAYBE", **base)


def test_module_imports_nothing_but_stdlib():
    """Phase 1 adds no coupling: no store, narrative, model, or
    provider imports. This also keeps the separation AST tests
    mechanical: nothing here can trip them."""
    source = (
        Path(__file__).resolve().parent.parent
        / "local_ai"
        / "narrative"
        / "evidence_access.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported <= {"__future__", "collections.abc", "dataclasses"}


# -- E3: durability determination ---------------------------------------


class _RecordingLookup:
    """Carrier lookup fake that records exactly what it was asked."""

    def __init__(self, quotes):
        self.quotes = quotes
        self.calls = []

    def __call__(self, ref):
        self.calls.append(ref)
        return self.quotes.get((ref.kind, ref.ref_id))


def test_determination_retrievable_and_carrier_not_consulted():
    lookup = _RecordingLookup({("evidence_note", "note-1"): "quoted text"})
    out = determine_durability(
        source_ids=["conv-1", "msg-7"],
        live_fetch=lambda: "live row text",
        carrier_lookup=lookup,
        carrier_ref=CarrierRef(kind="evidence_note", ref_id="note-1"),
    )
    assert out.durability == "RETRIEVABLE"
    assert out.content == "live row text"
    assert out.carrier is None
    assert lookup.calls == [], "live hit must not consult any carrier"


def test_determination_quoted_from_named_evidence_note_only():
    lookup = _RecordingLookup({("evidence_note", "note-1"): "frozen quote"})
    out = determine_durability(
        source_ids=["conv-1", "msg-7"],
        live_fetch=lambda: None,
        carrier_lookup=lookup,
        carrier_ref=CarrierRef(kind="evidence_note", ref_id="note-1"),
    )
    assert out.durability == "QUOTED"
    assert out.content == "frozen quote"
    assert out.carrier == CarrierRef(kind="evidence_note", ref_id="note-1")
    assert lookup.calls == [CarrierRef(kind="evidence_note", ref_id="note-1")]


def test_determination_unavailable_when_neither_exists():
    lookup = _RecordingLookup({})
    out = determine_durability(
        source_ids=["conv-1", "msg-7"],
        live_fetch=lambda: None,
        carrier_lookup=lookup,
        carrier_ref=CarrierRef(kind="evidence_note", ref_id="note-1"),
    )
    assert out.durability == "UNAVAILABLE"
    assert out.content is None
    assert out.carrier is None
    assert isinstance(out, DurabilityOutcome)


def test_determination_consults_only_the_carrier_it_was_given():
    # A quote exists under note-2, but the caller named note-1 only.
    # The determination must not find it: no scanning beyond the
    # given carrier, even when another carrier holds the text.
    lookup = _RecordingLookup({("evidence_note", "note-2"): "other quote"})
    out = determine_durability(
        source_ids=["conv-1", "msg-7"],
        live_fetch=lambda: None,
        carrier_lookup=lookup,
        carrier_ref=CarrierRef(kind="evidence_note", ref_id="note-1"),
    )
    assert out.durability == "UNAVAILABLE"
    assert out.content is None
    assert lookup.calls == [CarrierRef(kind="evidence_note", ref_id="note-1")]


def test_determination_half_supplied_carrier_is_not_consulted():
    lookup = _RecordingLookup({("evidence_note", "note-1"): "frozen quote"})
    out = determine_durability(
        source_ids=["conv-1", "msg-7"],
        live_fetch=lambda: None,
        carrier_lookup=lookup,
        carrier_ref=None,
    )
    assert out.durability == "UNAVAILABLE"
    assert lookup.calls == []
    out2 = determine_durability(
        source_ids=["conv-1", "msg-7"],
        live_fetch=lambda: None,
        carrier_lookup=None,
        carrier_ref=CarrierRef(kind="evidence_note", ref_id="note-1"),
    )
    assert out2.durability == "UNAVAILABLE"


def test_determination_live_to_cleared_transition():
    state = {"row": "live row text"}

    def live_fetch():
        return state["row"]

    out1 = determine_durability(
        source_ids=["conv-1", "msg-7"], live_fetch=live_fetch
    )
    assert out1.durability == "RETRIEVABLE"
    state["row"] = None  # the conversation was cleared
    out2 = determine_durability(
        source_ids=["conv-1", "msg-7"], live_fetch=live_fetch
    )
    assert out2.durability == "UNAVAILABLE"
    assert out2.content is None


def test_determination_quoted_requires_carrier_identified():
    with pytest.raises(ValueError):
        DurabilityOutcome(
            durability="QUOTED",
            source_ids=("conv-1", "msg-7"),
            carrier=None,
            content="a quote with no carrier",
        )
    with pytest.raises(ValueError):
        DurabilityOutcome(
            durability="UNAVAILABLE",
            source_ids=("conv-1", "msg-7"),
            carrier=None,
            content="must not exist",
        )


# -- E4: ownership guard -------------------------------------------------


def test_guard_passes_same_user_row_unchanged():
    row = {
        "id": "dec-9",
        "user_id": "user-1",
        "entity_type": "initiative",
        "entity_id": "morning-routine",
        "decision_type": "decision",
        "content": "Adopt the morning routine.",
    }
    result = guard_row(row, "user-1")
    assert result is row


def test_guard_refuses_cross_user_row_with_zero_content():
    row = {
        "id": "dec-9",
        "user_id": "user-2",
        "entity_type": "initiative",
        "entity_id": "morning-routine",
        "decision_type": "decision",
        "content": "Adopt the morning routine.",
    }
    result = guard_row(row, "user-1")
    assert isinstance(result, OwnershipRefusal)
    assert fields(OwnershipRefusal) == (), "refusal must be fieldless"
    leaked = repr(result) + str(vars(result)) if hasattr(result, "__dict__") else repr(result)
    for secret in ("dec-9", "user-2", "morning-routine", "Adopt the morning"):
        assert secret not in leaked


def test_guard_refuses_missing_owner_and_empty_requester():
    row_no_owner = {"id": "dec-9", "content": "something"}
    assert isinstance(guard_row(row_no_owner, "user-1"), OwnershipRefusal)
    row = {"id": "dec-9", "user_id": "user-1", "content": "something"}
    assert isinstance(guard_row(row, ""), OwnershipRefusal)
    assert isinstance(guard_row(row, None), OwnershipRefusal)


def test_guard_rows_applies_per_row_no_emit_then_filter():
    # The flagged list_decisions enumeration hazard: every row is
    # guarded, not just a single get. Positions are preserved;
    # refused rows become content-free refusals in place.
    rows = [
        {"id": "dec-1", "user_id": "user-1", "content": "mine one"},
        {"id": "dec-2", "user_id": "user-2", "content": "theirs secret"},
        {"id": "dec-3", "user_id": "user-1", "content": "mine two"},
        {"id": "dec-4", "user_id": "user-3", "content": "theirs too"},
    ]
    out = guard_rows(rows, "user-1")
    assert out[0] is rows[0]
    assert out[2] is rows[2]
    assert isinstance(out[1], OwnershipRefusal)
    assert isinstance(out[3], OwnershipRefusal)
    rendered = repr(out)
    assert "theirs secret" not in rendered
    assert "theirs too" not in rendered
    assert "dec-2" not in rendered
    assert "dec-4" not in rendered
    assert "mine one" in rendered and "mine two" in rendered
