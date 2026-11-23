"""Story-First Phase 1B — the card-section generation kind (Outlet D).

The kind produces, for a thread, a reading whose payload carries
the personal card's sections (``structure`` / ``distinctions`` /
``tags``) alongside the existing tensions, open questions, and
milestones. All generation is a recorded fake; the suite asserts
the fake's call counts, so a gate that generates when it should
abstain fails loudly. Covered:

- The deterministic pre-filter (S1 multiplicity, S2 detectable
  structural material, S3 dedup / durable rejection) runs with no
  model call, and its failure abstains before generation.
- Generation rides behind its OWN default-off switch
  (``ZENAF_RECOGNITION_CARD_SECTIONS_GEN``), on the correspondence
  precedent: switch off ⇒ pre-filter result recorded, nothing
  generated, nothing proposed.
- Validation is deterministic: citations outside the input set,
  an empty structure block, or unaddressed distinctions discard
  the whole candidate.
- The reading lands through ``propose_reading`` at ``proposed``
  standing — the verdict path is never touched (no standing
  pointer moves, no other reading's status changes), per the
  Rev 6 contract.
- The Phase 1A card view surfaces the sections verbatim.
- The pass budgets card generation per pass, independently of
  the other outlets.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from local_ai.narrative import NarrativeStore
from local_ai.narrative.card_view import card_for
from local_ai.narrative.recognition import (
    CARD_SECTIONS_READING_KIND,
    CardSectionCandidate,
    assess_card_sections,
    propose_all,
    run_recognition_pass,
)
from local_ai.narrative.refs import SourceRef

USER = "user-1"

_ROW_ID_RE = re.compile(r"\[([a-z]+-[0-9a-f]{24})\]")

SWITCH = "ZENAF_RECOGNITION_CARD_SECTIONS_GEN"


# ---------------------------------------------------------------------------
# Fakes and fixture helpers (the recognition suite's idiom)
# ---------------------------------------------------------------------------


class FakeGen:
    """A recorded generate_fn: logs every prompt, answers via a
    responder callable. Call counts are the suite's cost ledger."""

    def __init__(self, responder):
        self.prompts: list[str] = []
        self._responder = responder

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return self._responder(prompt)

    @property
    def calls(self) -> int:
        return len(self.prompts)


def _prompt_row_ids(prompt: str) -> list[str]:
    """Evidence row ids in the order the prompt renders them."""
    return _ROW_ID_RE.findall(prompt)


def _card_json(row_ids, *, distinctions=None, structure=None):
    """A valid card-section generation citing the given rows."""
    if structure is None:
        structure = {
            "roles": [
                {"text": "the one who moved", "evidence_refs": [row_ids[0]]}
            ],
            "relationships": [
                {
                    "text": "care pulling against work",
                    "evidence_refs": row_ids[:2],
                }
            ],
            "conflicts": [],
            "reversals": [],
            "sacrifices": [
                {
                    "text": "the old role, given up",
                    "evidence_refs": [row_ids[0]],
                }
            ],
            "consequences": [],
            "changes_over_time": [
                {
                    "text": "visits became the routine",
                    "evidence_refs": [row_ids[-1]],
                }
            ],
        }
    return json.dumps(
        {
            "structure": structure,
            "distinctions": (
                distinctions
                if distinctions is not None
                else ["not a story of recovery; the record shows none"]
            ),
            "tags": ["care", "displacement"],
            "tensions": ["care against work"],
            "open_questions": ["what happens when the visits end"],
            "milestones": [],
        }
    )


def _valid_card_responder(prompt):
    return _card_json(_prompt_row_ids(prompt))


def _thread(store, title, status="active"):
    thread = store.create_thread(USER, origin="user_declared", title=title)
    if status != "nascent":
        store.set_thread_status(USER, thread.id, status)
    return store.get_thread(USER, thread.id)


def _set_time(store, row_id, timestamp):
    conn = sqlite3.connect(str(store.db_path))
    conn.execute(
        "UPDATE thread_evidence SET created_at = ? WHERE id = ?",
        (timestamp, row_id),
    )
    conn.commit()
    conn.close()


def _row(store, thread_id, row_id):
    for row in store.evidence_for(USER, thread_id):
        if row.id == row_id:
            return row
    raise AssertionError(f"row {row_id} not on thread {thread_id}")


def _add(store, thread_id, kind, ref_id, *, note="", at=None, entity=None):
    row = store.add_evidence(
        USER,
        thread_id,
        SourceRef(kind=kind, ref_id=ref_id, evidence_kind="quote"),
        note=note,
    )
    if entity:
        store.annotate_evidence_entities(
            USER, thread_id, {(kind, ref_id): entity}
        )
    if at:
        _set_time(store, row.id, at)
    return _row(store, thread_id, row.id)


def _change(store, thread_id, kind, kind_ref, ref_id, *, at=None, entity=None):
    """Record a change whose cited evidence arrives WITH the change."""
    change = store.record_change(
        USER,
        thread_id,
        kind=kind,
        evidence_refs=[
            SourceRef(kind=kind_ref, ref_id=ref_id, evidence_kind="quote")
        ],
    )
    if entity:
        store.annotate_evidence_entities(
            USER, thread_id, {(kind_ref, ref_id): entity}
        )
    if at:
        rows = store.evidence_for(USER, thread_id)
        row = [r for r in rows if r.key == (kind_ref, ref_id)][0]
        _set_time(store, row.id, at)
    return change


def _structured_thread(store, title="Caring for Mum"):
    """Three points, three days, two subjects — S1 + S2 pass."""
    thread = _thread(store, title)
    _add(
        store, thread.id, "event", "evt-moved",
        note="I moved cities to be near her — left my old role to do it",
        at="2026-03-08T10:00:00+00:00", entity="person:mum",
    )
    _add(
        store, thread.id, "journal_entry", "journal-hospital",
        note="the hospital weeks: forms, rotas, sleeping in a chair",
        at="2026-05-08T10:00:00+00:00", entity="person:mum",
    )
    _add(
        store, thread.id, "event", "evt-deadline",
        note="the atlas deadline slipped again while I was away",
        at="2026-06-02T10:00:00+00:00", entity="project:atlas",
    )
    return store.get_thread(USER, thread.id)


def _card_readings(store, thread_id):
    return [
        r
        for r in store.readings_for(USER, thread_id)
        if isinstance(r.reading, dict)
        and r.reading.get("kind") == CARD_SECTIONS_READING_KIND
    ]


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


@pytest.fixture()
def gen_on(monkeypatch):
    monkeypatch.setenv(SWITCH, "1")


# ---------------------------------------------------------------------------
# The switch — pre-filter runs, generation waits (correspondence R7 shape)
# ---------------------------------------------------------------------------


def test_switch_off_prefilter_runs_nothing_generated(store, monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    thread = _structured_thread(store)
    fake = FakeGen(_valid_card_responder)
    result = assess_card_sections(store, USER, thread.id, generate_fn=fake)
    assert not [
        c for c in result.candidates if isinstance(c, CardSectionCandidate)
    ]
    assert fake.calls == 0
    assert any("generation switch off" in n for n in result.notes)
    assert store.readings_for(USER, thread.id) == []


def test_switch_on_but_no_generation_injected(store, gen_on):
    thread = _structured_thread(store)
    result = assess_card_sections(store, USER, thread.id, generate_fn=None)
    assert result.candidates == []
    assert any("no generation injected" in n for n in result.notes)


# ---------------------------------------------------------------------------
# Happy path — candidate, proposal, card surface, contract intact
# ---------------------------------------------------------------------------


def test_switch_on_proposes_card_reading_at_proposed(store, gen_on):
    thread = _structured_thread(store)
    fake = FakeGen(_valid_card_responder)
    result = assess_card_sections(store, USER, thread.id, generate_fn=fake)
    candidates = [
        c for c in result.candidates if isinstance(c, CardSectionCandidate)
    ]
    assert len(candidates) == 1
    assert fake.calls == 1
    # Assessment is pure: nothing written until propose_all.
    assert store.readings_for(USER, thread.id) == []

    written = propose_all(store, USER, result)
    assert len(written) == 1
    (reading,) = _card_readings(store, thread.id)
    assert reading.id == written[0]
    assert reading.author == "steward"
    assert reading.status == "proposed"
    payload = reading.reading
    assert payload["kind"] == CARD_SECTIONS_READING_KIND
    assert set(payload["structure"]) == {
        "roles",
        "relationships",
        "conflicts",
        "reversals",
        "sacrifices",
        "consequences",
        "changes_over_time",
    }
    assert payload["structure"]["roles"][0]["text"] == "the one who moved"
    assert payload["distinctions"] == [
        "not a story of recovery; the record shows none"
    ]
    assert payload["tags"] == ["care", "displacement"]
    assert payload["tensions"] == ["care against work"]
    assert payload["open_questions"] == ["what happens when the visits end"]
    assert payload["sections_signature"].startswith("card_sections:")
    assert payload["coverage"]["evidence_examined"] == 3
    window_ids = {r.id for r in store.evidence_for(USER, thread.id)}
    assert set(reading.evidence_refs) == window_ids
    # The verdict path was never touched: nothing became standing.
    assert store.get_thread(USER, thread.id).standing_reading_id is None


def test_card_view_surfaces_sections_verbatim(store, gen_on):
    thread = _structured_thread(store)
    result = assess_card_sections(
        store, USER, thread.id, generate_fn=FakeGen(_valid_card_responder)
    )
    propose_all(store, USER, result)
    card = card_for(store, USER, thread.id)
    assert len(card["current_field"]) == 1
    entry = card["current_field"][0]
    (reading,) = _card_readings(store, thread.id)
    assert entry["structure"] == reading.reading["structure"]
    assert entry["distinctions"] == reading.reading["distinctions"]
    assert entry["tags"] == reading.reading["tags"]
    assert entry["currency"]["placement"] == "current"


def test_existing_reading_and_standing_untouched(store, gen_on):
    """Rev 6 contract: the card kind writes through propose_reading
    only — a pre-existing reading's status and the thread's
    standing pointer are byte-identical after the proposal."""
    thread = _structured_thread(store)
    prior = store.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={"tensions": ["an older tension"], "open_questions": []},
        evidence_refs=[store.evidence_for(USER, thread.id)[0].id],
    )
    result = assess_card_sections(
        store, USER, thread.id, generate_fn=FakeGen(_valid_card_responder)
    )
    propose_all(store, USER, result)
    after = {r.id: r for r in store.readings_for(USER, thread.id)}
    assert after[prior.id].status == "proposed"
    assert after[prior.id].reading["tensions"] == ["an older tension"]
    assert store.get_thread(USER, thread.id).standing_reading_id is None


# ---------------------------------------------------------------------------
# S1 / S2 — the deterministic pre-filter
# ---------------------------------------------------------------------------


def test_s1_abstains_on_sparse_thread(store, gen_on):
    thread = _thread(store, "Two notes")
    _add(
        store, thread.id, "event", "evt-one",
        note="one thing happened", at="2026-03-03T10:00:00+00:00",
        entity="person:mum",
    )
    _add(
        store, thread.id, "event", "evt-two",
        note="another thing happened", at="2026-04-03T10:00:00+00:00",
        entity="project:atlas",
    )
    fake = FakeGen(_valid_card_responder)
    result = assess_card_sections(store, USER, thread.id, generate_fn=fake)
    assert result.candidates == []
    assert fake.calls == 0
    assert any("S1 abstain" in n for n in result.notes)


def test_s2_abstains_single_subject_no_movement(store, gen_on):
    thread = _thread(store, "Sleep")
    for i, month in enumerate(("03", "04", "06")):
        _add(
            store, thread.id, "journal_entry", f"journal-sleep-{i}",
            note="sleep was poor again; woke at three and stayed awake",
            at=f"2026-{month}-12T10:00:00+00:00", entity="topic:sleep",
        )
    fake = FakeGen(_valid_card_responder)
    result = assess_card_sections(store, USER, thread.id, generate_fn=fake)
    assert result.candidates == []
    assert fake.calls == 0
    assert any("S2 abstain" in n for n in result.notes)


def test_s2_passes_on_recorded_movement_alone(store, gen_on):
    """One subject, but the thread moved: the movement itself is
    structural material, so the pre-filter passes."""
    thread = _thread(store, "Presenting work")
    _add(
        store, thread.id, "event", "evt-dread",
        note="I dread presenting; my hands shake before every talk",
        at="2026-03-03T10:00:00+00:00", entity="task:presenting",
    )
    _change(
        store, thread.id, "milestone", "event", "evt-volunteer",
        at="2026-04-10T10:00:00+00:00", entity="task:presenting",
    )
    _add(
        store, thread.id, "event", "evt-presented",
        note="presented the results to the team",
        at="2026-06-15T10:00:00+00:00", entity="task:presenting",
    )
    fake = FakeGen(_valid_card_responder)
    result = assess_card_sections(store, USER, thread.id, generate_fn=fake)
    assert [
        c for c in result.candidates if isinstance(c, CardSectionCandidate)
    ]
    assert fake.calls == 1


# ---------------------------------------------------------------------------
# Validation — deterministic, whole-candidate discard
# ---------------------------------------------------------------------------


def test_validation_discards_citation_outside_window(store, gen_on):
    thread = _structured_thread(store)

    def bad_responder(prompt):
        row_ids = _prompt_row_ids(prompt)
        return _card_json(
            row_ids,
            structure={
                "roles": [
                    {
                        "text": "cites a record that was never shown",
                        "evidence_refs": ["evt-000000000000000000000000"],
                    }
                ],
            },
        )

    fake = FakeGen(bad_responder)
    result = assess_card_sections(store, USER, thread.id, generate_fn=fake)
    assert result.candidates == []
    assert fake.calls == 1
    assert any("failed validation" in n for n in result.notes)
    assert store.readings_for(USER, thread.id) == []


def test_validation_discards_empty_structure(store, gen_on):
    thread = _structured_thread(store)
    empty = {field: [] for field in (
        "roles", "relationships", "conflicts", "reversals",
        "sacrifices", "consequences", "changes_over_time",
    )}
    fake = FakeGen(
        lambda prompt: _card_json(_prompt_row_ids(prompt), structure=empty)
    )
    result = assess_card_sections(store, USER, thread.id, generate_fn=fake)
    assert result.candidates == []
    assert store.readings_for(USER, thread.id) == []


def test_validation_discards_unaddressed_distinctions(store, gen_on):
    thread = _structured_thread(store)
    fake = FakeGen(
        lambda prompt: _card_json(
            _prompt_row_ids(prompt), distinctions=[]
        )
    )
    result = assess_card_sections(store, USER, thread.id, generate_fn=fake)
    assert result.candidates == []
    assert store.readings_for(USER, thread.id) == []


def test_decline_and_failure_write_nothing(store, gen_on):
    thread = _structured_thread(store)
    declining = FakeGen(lambda prompt: "NONE")
    result = assess_card_sections(
        store, USER, thread.id, generate_fn=declining
    )
    assert result.candidates == []

    def boom(prompt):
        raise RuntimeError("provider down")

    failing = FakeGen(boom)
    result = assess_card_sections(store, USER, thread.id, generate_fn=failing)
    assert result.candidates == []
    assert any("generation failed" in n for n in result.notes)
    assert store.readings_for(USER, thread.id) == []


# ---------------------------------------------------------------------------
# S3 — dedup and durable rejection
# ---------------------------------------------------------------------------


def test_s3_dedup_same_evidence_then_reopens_on_new(store, gen_on):
    thread = _structured_thread(store)
    first = assess_card_sections(
        store, USER, thread.id, generate_fn=FakeGen(_valid_card_responder)
    )
    propose_all(store, USER, first)

    fake2 = FakeGen(_valid_card_responder)
    second = assess_card_sections(store, USER, thread.id, generate_fn=fake2)
    assert not [
        c for c in second.candidates if isinstance(c, CardSectionCandidate)
    ]
    assert fake2.calls == 0  # S3 abstains before generation
    assert any("S3 abstain" in n for n in second.notes)

    # New evidence changes the signature and re-opens eligibility.
    _add(
        store, thread.id, "journal_entry", "journal-later",
        note="she is home now; the visits are daily again",
        at="2026-08-01T10:00:00+00:00", entity="person:mum",
    )
    fake3 = FakeGen(_valid_card_responder)
    third = assess_card_sections(store, USER, thread.id, generate_fn=fake3)
    assert [
        c for c in third.candidates if isinstance(c, CardSectionCandidate)
    ]
    assert fake3.calls == 1


def test_s3_rejected_card_not_reproposed(store, gen_on):
    thread = _structured_thread(store)
    first = assess_card_sections(
        store, USER, thread.id, generate_fn=FakeGen(_valid_card_responder)
    )
    propose_all(store, USER, first)
    (reading,) = _card_readings(store, thread.id)
    store.reject_reading(USER, reading.id)

    fake2 = FakeGen(_valid_card_responder)
    second = assess_card_sections(store, USER, thread.id, generate_fn=fake2)
    assert not [
        c for c in second.candidates if isinstance(c, CardSectionCandidate)
    ]
    assert fake2.calls == 0
    assert any("rejected on this evidence" in n for n in second.notes)


# ---------------------------------------------------------------------------
# The pass — budget and outlet independence
# ---------------------------------------------------------------------------


def test_pass_budgets_card_generation_independently(store, monkeypatch):
    monkeypatch.setenv("ZENAF_RECOGNITION", "1")
    monkeypatch.setenv(SWITCH, "1")
    a = _structured_thread(store, "Caring for Mum")
    b = _structured_thread(store, "Caring for Dad")
    fake = FakeGen(_valid_card_responder)
    result = run_recognition_pass(store, USER, generate_fn=fake)
    cards = _card_readings(store, a.id) + _card_readings(store, b.id)
    assert len(cards) == 1  # MAX_CARD_SECTION_GENERATIONS_PER_PASS
    assert fake.calls == 1
    assert result.generation_calls == 1


def test_pass_card_switch_off_proposes_no_cards(store, monkeypatch):
    monkeypatch.setenv("ZENAF_RECOGNITION", "1")
    monkeypatch.delenv(SWITCH, raising=False)
    thread = _structured_thread(store)
    fake = FakeGen(_valid_card_responder)
    run_recognition_pass(store, USER, generate_fn=fake)
    assert _card_readings(store, thread.id) == []
    assert fake.calls == 0
