"""Steward Recognition (Gate B) — the missing caller, gated.

Covers the Gate B brief §4 test specification: each founder
requirement as a named gate (R1–R7), plus the carried validation /
shape / bridge tests from the scoping proposal §10. All generation
is a recorded fake; the suite asserts the fake's call counts, so a
gate that generates when it should abstain fails loudly. Fixtures
follow the proposal's example cases 1–9.

- R1: nothing becomes standing without a user verdict.
- R2: competing narrative forms, proposed together, unranked.
- R3: durable rejection (fittings via the store's Phase 4 T2 rule;
  progressions via G4 dismissal/coverage).
- R4: metaphors never become evidence.
- R5: abstention amid suffering and change (cases 9, 2, 4).
- R6: consent, switches, erasure barrier, provenance.
- R7: correspondence generation's own switch and call boundary.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from local_ai.narrative import NarrativeStore
from local_ai.narrative.context import WEAVER_BRANCH_ID, narrative_context_for
from local_ai.narrative.lenses import get_lens
from local_ai.narrative.recognition import (
    FittingCandidate,
    ProgressionCandidate,
    RecognitionResult,
    assess_pairs,
    assess_thread,
    propose_all,
    run_recognition_pass,
)
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.review import apply_verdict, pending_review_items

USER = "user-1"
OTHER = "user-2"

_ROW_ID_RE = re.compile(r"\[([a-z]+-[0-9a-f]{24})\]")


# ---------------------------------------------------------------------------
# Fakes and fixture helpers
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


def _progression_json(row_ids, *, claim="a development", contradiction=None):
    """A valid progression generation citing the given rows in order."""
    return json.dumps(
        {
            "steps": [
                {"evidence_refs": [row_id], "observation": f"point {i + 1}"}
                for i, row_id in enumerate(row_ids)
            ],
            "development_claim": claim,
            "rivals": {
                "recurrence": "the theme could merely be returning",
                "coincidence": "the points could be unrelated",
            },
            "contradiction": contradiction,
        }
    )


def _valid_progression_responder(prompt):
    return _progression_json(_prompt_row_ids(prompt))


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


def _row(store, thread_id, row_id):
    for row in store.evidence_for(USER, thread_id):
        if row.id == row_id:
            return row
    raise AssertionError(f"row {row_id} not on thread {thread_id}")


def _change(store, thread_id, kind, kind_ref, ref_id, *, at=None, entity=None):
    """Record a change whose cited evidence arrives WITH the change
    (invariant 2: the cited ref must be new to the thread)."""
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


def _rows(store, thread_id):
    return store.evidence_for(USER, thread_id)


# ---------------------------------------------------------------------------
# Case fixtures (proposal §11 / Rev 2 §21)
# ---------------------------------------------------------------------------


def _case1(store):
    """Case 1 — genuine progression: presenting, Mar → Sep."""
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
    _add(
        store, thread.id, "journal_entry", "journal-sept",
        note="presented again today; it was fine, mostly",
        at="2026-09-08T10:00:00+00:00", entity="task:presenting",
    )
    return store.get_thread(USER, thread.id)


def _case2(store):
    """Case 2 — recurring theme, no movement: sleep, five months."""
    thread = _thread(store, "Sleep")
    for i, month in enumerate(("03", "04", "06", "08")):
        _add(
            store, thread.id, "journal_entry", f"journal-sleep-{i}",
            note="sleep was poor again; woke at three and stayed awake",
            at=f"2026-{month}-12T10:00:00+00:00",
        )
    return store.get_thread(USER, thread.id)


def _case7(store):
    """Case 7 — one progression, two forms: leaving the job."""
    thread = _thread(store, "Leaving the job")
    _add(
        store, thread.id, "event", "evt-left",
        note="I am leaving — I exited my role at the firm in March",
        at="2026-03-05T10:00:00+00:00",
    )
    _change(
        store, thread.id, "milestone", "event", "evt-freelance",
        at="2026-04-12T10:00:00+00:00",
    )
    # The milestone's evidence row carries the ordeal language.
    rows = _rows(store, thread.id)
    milestone_row = [r for r in rows if r.ref_id == "evt-freelance"][0]
    conn = sqlite3.connect(str(store.db_path))
    conn.execute(
        "UPDATE thread_evidence SET note = ? WHERE id = ?",
        (
            "I decided to freelance — the ordeal of it: a central "
            "difficulty, stakes I named myself",
            milestone_row.id,
        ),
    )
    conn.commit()
    conn.close()
    _add(
        store, thread.id, "journal_entry", "journal-seasons",
        note="work comes in seasons and cycles, never one single arc",
        at="2026-06-10T10:00:00+00:00",
    )
    _add(
        store, thread.id, "journal_entry", "journal-fallow",
        note="rest is part of the work; this winter I am fallow, not failing",
        at="2026-08-10T10:00:00+00:00",
    )
    _add(
        store, thread.id, "journal_entry", "journal-return",
        note=(
            "going back to the same work but mine now — bringing it "
            "home, received differently"
        ),
        at="2026-09-10T10:00:00+00:00",
    )
    return store.get_thread(USER, thread.id)


def _case8(store):
    """Case 8 — the misleading metaphor: caring for a parent."""
    thread = _thread(store, "Caring for Mum")
    _add(
        store, thread.id, "event", "evt-moved",
        note="I moved cities to be near her — I exited my old role to do this",
        at="2026-03-08T10:00:00+00:00",
    )
    _add(
        store, thread.id, "journal_entry", "journal-hospital",
        note=(
            "the ordeal of the hospital weeks: a central difficulty "
            "with stakes I named myself"
        ),
        at="2026-05-08T10:00:00+00:00",
    )
    return store.get_thread(USER, thread.id)


def _pair(store):
    """Two threads sharing an entity, movements in opposition.

    Thread A also carries a full progression path (for R4); thread
    B is sparse. Returns (thread_a, thread_b).
    """
    a = _thread(store, "Atlas project")
    _add(
        store, a.id, "event", "evt-a1",
        note="the client project extended through spring",
        at="2026-03-04T10:00:00+00:00", entity="project:atlas",
    )
    _change(
        store, a.id, "extended", "event", "evt-a2",
        at="2026-04-06T10:00:00+00:00", entity="project:atlas",
    )
    _add(
        store, a.id, "journal_entry", "journal-a3",
        note="the atlas work settled into a rhythm",
        at="2026-05-06T10:00:00+00:00", entity="project:atlas",
    )
    b = _thread(store, "Atlas doubts")
    _add(
        store, b.id, "event", "evt-b1",
        note="worried the atlas timeline was slipping",
        at="2026-03-20T10:00:00+00:00", entity="project:atlas",
    )
    _change(
        store, b.id, "contradicted", "event", "evt-b2",
        at="2026-04-22T10:00:00+00:00", entity="project:atlas",
    )
    return store.get_thread(USER, a.id), store.get_thread(USER, b.id)


_CORRESPONDENCE_JSON = json.dumps(
    {
        "structural_tension": "one story grows while the other is contradicted",
        "proposed_relationship": "the same project, read as progress in one thread and as failure in the other",
        "candidate_metaphor": "a bridge inspected from both ends",
        "mapping": {"thread a": "the extension", "thread b": "the contradiction"},
        "limitations": (
            "the two threads may simply record different weeks; "
            "the opposition is in the record's shape, not proof "
            "that anyone disagreed"
        ),
    }
)


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


# ---------------------------------------------------------------------------
# R1 — nothing becomes standing without a user verdict
# ---------------------------------------------------------------------------


def test_t1_1_recognition_proposes_nothing_becomes_standing(store):
    """Case 1 + 7 pass: readings and fittings land as proposals only."""
    thread = _case7(store)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    propose_all(store, USER, result)

    readings = store.readings_for(USER, thread.id)
    progression = [
        r for r in readings
        if isinstance(r.reading, dict)
        and r.reading.get("kind") == "progression_candidate"
    ]
    assert len(progression) == 1
    assert progression[0].status == "proposed"
    assert progression[0].author == "steward"

    fittings = store.fittings_for(USER, thread.id)
    assert len(fittings) == 2
    assert all(f.status == "proposed" for f in fittings)

    thread_now = store.get_thread(USER, thread.id)
    assert thread_now.lens_fitting_id is None
    assert thread_now.standing_reading_id is None
    snapshot = store.snapshot_for_read(USER)
    assert all(r.status == "proposed" for r in snapshot["readings"])


def _perm_conn(*, derivation=True, coordination=True):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
        (
            USER,
            json.dumps(
                {
                    "steward_derivation": derivation,
                    "steward_coordination": coordination,
                }
            ),
            "2026-11-19T00:00:00+00:00",
        ),
    )
    conn.commit()
    return conn


def _context(store, branch_id=WEAVER_BRANCH_ID, attended="atlas"):
    return narrative_context_for(
        store,
        USER,
        branch_id,
        attended_text=attended,
        connection=_perm_conn(),
        aspiration_reader=lambda uid: None,
        aspiration_permission_check=lambda uid: False,
    )


def test_t1_2_proposed_frames_never_render_in_context(store):
    """A proposed fitting/correspondence produces NO context line."""
    a, _b = _pair(store)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, a.id, generate_fn=fake)
    propose_all(store, USER, result)
    # Even with a proposed fitting placed directly, nothing renders.
    rows = _rows(store, a.id)
    store.set_fitting(
        USER,
        a.id,
        lens_id="departure_initiation_return",
        evidence_refs=[rows[0].id, rows[1].id],
        status="proposed",
        proposed_by="steward",
    )
    prepared = _context(store, attended="atlas")
    assert prepared.available
    assert "fitting:" not in prepared.block
    assert "correspondence" not in prepared.block


def test_t1_3_verdict_moves_proposal_to_standing(store):
    """Acceptance is the only road to standing; state reads standing."""
    thread = _case1(store)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    propose_all(store, USER, result)
    reading = [
        r for r in store.readings_for(USER, thread.id)
        if isinstance(r.reading, dict)
        and r.reading.get("kind") == "progression_candidate"
    ][0]
    apply_verdict(store, USER, f"reading:{reading.id}", "accepted")
    thread_now = store.get_thread(USER, thread.id)
    assert thread_now.standing_reading_id == reading.id
    standing = store.readings_for(USER, thread.id, status="accepted")
    assert [r.id for r in standing] == [reading.id]


# ---------------------------------------------------------------------------
# R2 — competing narrative forms, proposed together, unranked
# ---------------------------------------------------------------------------


def test_t2_1_two_forms_proposed_together_unranked(store):
    """Case 7: monomyth + seasonal both proposed; no score anywhere."""
    thread = _case7(store)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    fittings = [
        c for c in result.candidates if isinstance(c, FittingCandidate)
    ]
    assert {c.lens_id for c in fittings} == {
        "departure_initiation_return",
        "sowing_growth_harvest_fallow",
    }
    # Candidates carry no ordering surface at all.
    for candidate in fittings:
        assert not hasattr(candidate, "score")
        assert not hasattr(candidate, "rank")
        lens = get_lens(candidate.lens_id)
        assert candidate.cautions == lens.cautions
    propose_all(store, USER, result)
    items = [
        i for i in pending_review_items(store, USER)
        if i.item_kind == "fitting"
    ]
    assert len(items) == 2
    for item in items:
        assert set(item.payload) == {"lens_id", "proposed_by", "evidence_refs"}


def test_t2_2_one_live_frame_at_a_time(store):
    """Accepting one leaves the other proposed; a second live frame
    is refused until the first retires (the store's rule, untouched)."""
    thread = _case7(store)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    propose_all(store, USER, result)
    first, second = store.fittings_for(USER, thread.id)
    store.set_fitting_status(USER, first.id, "accepted")
    assert store.get_thread(USER, thread.id).lens_fitting_id == first.id
    assert store.fittings_for(USER, thread.id, status="proposed")[0].id == second.id
    with pytest.raises(ValueError):
        store.set_fitting_status(USER, second.id, "accepted")
    store.set_fitting_status(USER, first.id, "retired")
    store.set_fitting_status(USER, second.id, "accepted")
    assert store.get_thread(USER, thread.id).lens_fitting_id == second.id


# ---------------------------------------------------------------------------
# R3 — durable rejection
# ---------------------------------------------------------------------------


def test_t3_1_rejected_fitting_not_reproposed_on_same_evidence(store):
    """Case 8: monomyth proposed, rejected; same evidence → silence."""
    thread = _case8(store)
    result = assess_thread(store, USER, thread.id, generate_fn=None)
    propose_all(store, USER, result)
    fittings = store.fittings_for(USER, thread.id)
    assert len(fittings) == 1
    assert fittings[0].lens_id == "departure_initiation_return"
    store.set_fitting_status(USER, fittings[0].id, "rejected")

    result2 = assess_thread(store, USER, thread.id, generate_fn=None)
    propose_all(store, USER, result2)
    fittings_after = store.fittings_for(USER, thread.id)
    assert len(fittings_after) == 1
    assert fittings_after[0].status == "rejected"
    assert any("rejected" in note for note in result2.notes)


def test_t3_2_new_evidence_reopens_fitting(store):
    """One new point matching the lens → the fitting may return."""
    thread = _case8(store)
    result = assess_thread(store, USER, thread.id, generate_fn=None)
    propose_all(store, USER, result)
    fitting = store.fittings_for(USER, thread.id)[0]
    store.set_fitting_status(USER, fitting.id, "rejected")

    _add(
        store, thread.id, "journal_entry", "journal-home",
        note="bringing her home from hospital, going back to our old house",
        at="2026-07-08T10:00:00+00:00",
    )
    result2 = assess_thread(store, USER, thread.id, generate_fn=None)
    propose_all(store, USER, result2)
    fittings = store.fittings_for(USER, thread.id)
    assert len(fittings) == 2
    by_status = {f.status: f for f in fittings}
    assert by_status["rejected"].id == fitting.id
    assert by_status["proposed"].lens_id == "departure_initiation_return"


def test_t3_3_rejected_progression_not_reproposed(store):
    """Case 5: rejected sequence stays rejected until new evidence
    AND an intervening change re-open the thread."""
    thread = _case1(store)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    propose_all(store, USER, result)
    reading = [
        r for r in store.readings_for(USER, thread.id)
        if isinstance(r.reading, dict)
        and r.reading.get("kind") == "progression_candidate"
    ][0]
    store.reject_reading(USER, reading.id)

    fake2 = FakeGen(_valid_progression_responder)
    result2 = assess_thread(store, USER, thread.id, generate_fn=fake2)
    assert not [
        c for c in result2.candidates if isinstance(c, ProgressionCandidate)
    ]
    assert fake2.calls == 0  # G4 abstains before generation

    # New evidence alone is not enough: still no intervening change
    # after the rejected window's last point... add both.
    _add(
        store, thread.id, "journal_entry", "journal-oct",
        note="presented to the whole company; hands steady",
        at="2026-10-08T10:00:00+00:00", entity="task:presenting",
    )
    _change(
        store, thread.id, "milestone", "event", "evt-keynote",
        at="2026-10-20T10:00:00+00:00", entity="task:presenting",
    )
    fake3 = FakeGen(_valid_progression_responder)
    result3 = assess_thread(store, USER, thread.id, generate_fn=fake3)
    assert [
        c for c in result3.candidates if isinstance(c, ProgressionCandidate)
    ]
    assert fake3.calls == 1


# ---------------------------------------------------------------------------
# R4 — metaphors never become evidence
# ---------------------------------------------------------------------------


def test_t4_1_interpretation_citation_discards_candidate(store, monkeypatch):
    """A generation citing an accepted correspondence's id is discarded."""
    monkeypatch.setenv("ZENAF_RECOGNITION_CORRESPONDENCE_GEN", "1")
    a, _b = _pair(store)
    corr_fake = FakeGen(lambda prompt: _CORRESPONDENCE_JSON)
    pair_result = assess_pairs(store, USER, generate_fn=corr_fake)
    propose_all(store, USER, pair_result)
    correspondence = store.correspondences_for(USER)[0]
    store.set_correspondence_status(USER, correspondence.id, "user_accepted")

    def citing_responder(prompt):
        row_ids = _prompt_row_ids(prompt)
        return _progression_json([correspondence.id, *row_ids[1:]])

    fake = FakeGen(citing_responder)
    result = assess_thread(store, USER, a.id, generate_fn=fake)
    assert not [
        c for c in result.candidates if isinstance(c, ProgressionCandidate)
    ]
    assert any("validation" in note for note in result.notes)


def test_t4_2_no_proposal_cites_an_interpretation(store, monkeypatch):
    """Across a full pass, no proposal row's refs name a corr-/fit- id."""
    monkeypatch.setenv("ZENAF_RECOGNITION", "1")
    monkeypatch.setenv("ZENAF_RECOGNITION_CORRESPONDENCE_GEN", "1")

    def responder(prompt):
        if "correspondence analyst" in prompt:
            return _CORRESPONDENCE_JSON
        return _valid_progression_responder(prompt)

    _case1(store)
    _pair(store)
    fake = FakeGen(responder)
    result = run_recognition_pass(store, USER, generate_fn=fake)
    propose_all(store, USER, result)

    cited: list[str] = []
    for thread in store.threads_for(USER):
        for reading in store.readings_for(USER, thread.id):
            cited.extend(reading.evidence_refs)
        for fitting in store.fittings_for(USER, thread.id):
            cited.extend(fitting.evidence_refs)
    for correspondence in store.correspondences_for(USER):
        cited.extend(correspondence.evidence_refs)
    assert cited  # the pass did propose things
    assert all(
        not ref.startswith(("corr-", "fit-", "rdg-")) for ref in cited
    )


# ---------------------------------------------------------------------------
# R5 — abstention amid suffering and change
# ---------------------------------------------------------------------------


def _case9(store):
    """Case 9 — a hard year: much happened, no arc is honest."""
    a = _thread(store, "The hard year")
    _add(
        store, a.id, "journal_entry", "journal-flood",
        note="the flood took the ground floor in February",
        at="2026-02-10T10:00:00+00:00", entity="house:home",
    )
    _add(
        store, a.id, "journal_entry", "journal-job",
        note="still at the warehouse job, same shifts as before",
        at="2026-04-10T10:00:00+00:00",
    )
    _add(
        store, a.id, "journal_entry", "journal-dad",
        note="dad's illness worsened through June",
        at="2026-06-10T10:00:00+00:00",
    )
    _add(
        store, a.id, "journal_entry", "journal-school",
        note="Mina changed schools in September",
        at="2026-09-10T10:00:00+00:00",
    )
    _change(store, a.id, "contradicted", "event", "evt-a9x",
            at="2026-10-10T10:00:00+00:00")
    b = _thread(store, "Home rota")
    _add(
        store, b.id, "journal_entry", "journal-rota",
        note="the home rota board by the door",
        at="2026-03-10T10:00:00+00:00", entity="house:home",
    )
    _change(store, b.id, "extended", "event", "evt-b9x",
            at="2026-05-10T10:00:00+00:00")
    return a, b


def test_t5_1_hard_year_no_proposals_anywhere(store, monkeypatch):
    """Case 9: zero proposals at all three outlets; the one reached
    generation (the strongest pair) declines and leaves no row."""
    monkeypatch.setenv("ZENAF_RECOGNITION_CORRESPONDENCE_GEN", "1")
    a, b = _case9(store)
    fake = FakeGen(lambda prompt: "NONE")
    for thread in (a, b):
        result = assess_thread(store, USER, thread.id, generate_fn=fake)
        assert result.candidates == []
        propose_all(store, USER, result)
    pair_result = assess_pairs(store, USER, generate_fn=fake)
    assert pair_result.detections  # the pair WAS seen
    assert pair_result.candidates == []
    propose_all(store, USER, pair_result)
    assert fake.calls == 1  # exactly one generation, on the pair
    assert store.readings_for(USER, a.id) == []
    assert store.fittings_for(USER, a.id) == []
    assert store.correspondences_for(USER) == []


def test_t5_2_recurrence_without_movement_abstains(store):
    """Case 2 (sleep): G2 — recurrence is not a progression."""
    thread = _case2(store)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    assert not [
        c for c in result.candidates if isinstance(c, ProgressionCandidate)
    ]
    assert fake.calls == 0
    assert any("G2" in note for note in result.notes)


def test_t5_3_sparse_thread_abstains_store_unchanged(store, tmp_path):
    """Case 4: two points — G1 abstains; assessment writes nothing."""
    thread = _thread(store, "A passing worry")
    _add(
        store, thread.id, "journal_entry", "journal-w1",
        note="a passing worry about the presentation",
        at="2026-05-01T10:00:00+00:00",
    )
    _add(
        store, thread.id, "journal_entry", "journal-w2",
        note="the worry again, unchanged",
        at="2026-06-01T10:00:00+00:00",
    )
    db_bytes_before = (tmp_path / "narrative.db").read_bytes()
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    propose_all(store, USER, result)
    assert result.candidates == []
    assert fake.calls == 0
    assert (tmp_path / "narrative.db").read_bytes() == db_bytes_before


# ---------------------------------------------------------------------------
# R6 — consent, switches, erasure, provenance
# ---------------------------------------------------------------------------


def test_t6_1_sweep_skips_recognition_without_consent(store, tmp_path, monkeypatch):
    from local_ai.narrative import sweep as sweep_module

    monkeypatch.setenv("ZENAF_RECOGNITION", "1")
    calls = []

    def spy(store_, user_id, generate_fn=None):
        calls.append(user_id)
        return RecognitionResult()

    monkeypatch.setattr(sweep_module, "run_recognition_pass", spy)
    log_path = tmp_path / "activity.log"
    log_path.write_text("")
    result = sweep_module.run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=None,
        consent_reader=lambda uid: False,
    )
    assert calls == []
    assert result.recognition is None


def test_t6_2_sweep_skips_recognition_when_switch_off(store, tmp_path, monkeypatch):
    from local_ai.narrative import sweep as sweep_module

    monkeypatch.delenv("ZENAF_RECOGNITION", raising=False)
    calls = []

    def spy(store_, user_id, generate_fn=None):
        calls.append(user_id)
        return RecognitionResult()

    monkeypatch.setattr(sweep_module, "run_recognition_pass", spy)
    log_path = tmp_path / "activity.log"
    log_path.write_text("")
    result = sweep_module.run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=None,
        consent_reader=lambda uid: True,
    )
    assert calls == []
    assert result.recognition is None

    # Positive control: switch on + consent on → the pass runs once.
    monkeypatch.setenv("ZENAF_RECOGNITION", "1")
    result2 = sweep_module.run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=None,
        consent_reader=lambda uid: True,
    )
    assert calls == [USER]
    assert result2.recognition is not None
    assert result2.recognition["generation_calls"] == 0


def test_t6_3_erasure_boundary_evidence_never_reaches_generation(store):
    """Case-adjacent (D2): pre-boundary evidence is invisible to the
    assessment; the funnel refuses any write without a manifest."""
    thread = _thread(store, "Presenting, again")
    pre1 = _add(
        store, thread.id, "event", "evt-pre1",
        note="an old dread, before the boundary",
        at="2026-01-05T10:00:00+00:00", entity="task:presenting",
    )
    pre2 = _add(
        store, thread.id, "event", "evt-pre2",
        note="another old note, before the boundary",
        at="2026-01-20T10:00:00+00:00", entity="task:presenting",
    )
    _add(
        store, thread.id, "event", "evt-post1",
        note="presented in March and it held",
        at="2026-03-03T10:00:00+00:00", entity="task:presenting",
    )
    _change(
        store, thread.id, "milestone", "event", "evt-post2",
        at="2026-04-10T10:00:00+00:00", entity="task:presenting",
    )
    _add(
        store, thread.id, "journal_entry", "journal-post3",
        note="presented again in June, steady",
        at="2026-06-15T10:00:00+00:00", entity="task:presenting",
    )
    store.write_erasure_tombstone(
        USER, erased_at="2026-02-01T00:00:00+00:00", operation_id="op-test"
    )
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    assert fake.calls == 1
    prompt_ids = _prompt_row_ids(fake.prompts[0])
    assert pre1.id not in prompt_ids
    assert pre2.id not in prompt_ids
    candidates = [
        c for c in result.candidates if isinstance(c, ProgressionCandidate)
    ]
    assert candidates
    assert pre1.id not in candidates[0].evidence_refs
    assert pre2.id not in candidates[0].evidence_refs
    # The funnel backstop: with a tombstone standing and no
    # eligibility manifest, the write itself is refused (D2) — no
    # reading lands at all, and certainly none citing barred rows.
    propose_all(store, USER, result)
    assert store.readings_for(USER, thread.id) == []


def test_t6_4_proposals_cite_only_owned_tier_e_evidence(store):
    """Every proposal ref resolves to a thread_evidence row of the user."""
    thread = _case1(store)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    propose_all(store, USER, result)
    snapshot = store.snapshot_for_read(USER)
    owned = {row.id for row in snapshot["evidence"]}
    for reading in store.readings_for(USER, thread.id):
        assert set(reading.evidence_refs) <= owned
    for fitting in store.fittings_for(USER, thread.id):
        assert set(fitting.evidence_refs) <= owned


# ---------------------------------------------------------------------------
# R7 — correspondence generation's own boundary
# ---------------------------------------------------------------------------


def test_t7_1_detection_without_generation_when_switch_off(store, monkeypatch):
    """Off: the pair is detected and reported; nothing is generated
    or proposed. The internal detection is the observable surface."""
    monkeypatch.delenv("ZENAF_RECOGNITION_CORRESPONDENCE_GEN", raising=False)
    _pair(store)
    fake = FakeGen(lambda prompt: _CORRESPONDENCE_JSON)
    result = assess_pairs(store, USER, generate_fn=fake)
    assert len(result.detections) == 1
    detection = result.detections[0]
    assert sorted(detection.opposed_kinds) == ["contradicted", "extended"]
    assert result.candidates == []
    assert fake.calls == 0
    propose_all(store, USER, result)
    assert store.correspondences_for(USER) == []


def test_t7_2_switch_on_one_call_limitations_enforced(store, monkeypatch):
    monkeypatch.setenv("ZENAF_RECOGNITION_CORRESPONDENCE_GEN", "1")
    _pair(store)
    # Thin limitations → the candidate is discarded before proposing.
    thin = FakeGen(
        lambda prompt: _CORRESPONDENCE_JSON.replace(
            "the two threads may simply record different weeks; "
            "the opposition is in the record's shape, not proof "
            "that anyone disagreed",
            "none",
        )
    )
    result = assess_pairs(store, USER, generate_fn=thin)
    assert thin.calls == 1
    assert result.candidates == []
    propose_all(store, USER, result)
    assert store.correspondences_for(USER) == []

    # Substantive limitations → exactly one proposed correspondence.
    fake = FakeGen(lambda prompt: _CORRESPONDENCE_JSON)
    result2 = assess_pairs(store, USER, generate_fn=fake)
    assert fake.calls == 1
    propose_all(store, USER, result2)
    correspondences = store.correspondences_for(USER)
    assert len(correspondences) == 1
    assert correspondences[0].status == "proposed"
    # Correspondences are steward-proposed by construction (the
    # model carries no other proposer); the limitations rode along.
    assert "different weeks" in correspondences[0].limitations


def test_t7_3_switches_are_independent(store, monkeypatch):
    """Outlet A generating never enables correspondence generation."""
    monkeypatch.delenv("ZENAF_RECOGNITION_CORRESPONDENCE_GEN", raising=False)
    thread = _case1(store)
    _pair(store)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    assert [
        c for c in result.candidates if isinstance(c, ProgressionCandidate)
    ]
    pair_result = assess_pairs(store, USER, generate_fn=fake)
    assert pair_result.detections
    assert pair_result.candidates == []
    assert fake.calls == 1  # only the progression generation happened


# ---------------------------------------------------------------------------
# Carried validation / shape tests (proposal §10) + case 3 (G3) + case 6
# ---------------------------------------------------------------------------


def _case3(store):
    """Case 3 — a development contradicted later (Dana)."""
    thread = _thread(store, "Working with Dana")
    _add(
        store, thread.id, "journal_entry", "journal-mar",
        note="Dana delivered the draft early; I trust her with the client work",
        at="2026-03-05T10:00:00+00:00",
    )
    _add(
        store, thread.id, "journal_entry", "journal-may",
        note="Dana handled the client call alone and it went well",
        at="2026-05-12T10:00:00+00:00",
    )
    # A typed movement (the delegation decision) so G2 can pass and
    # the G3 behavior — not abstention — is what the test exercises.
    _change(
        store, thread.id, "milestone", "event", "evt-delegate",
        at="2026-05-20T10:00:00+00:00",
    )
    standing = store.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={"tensions": [], "milestones": ["growing trust in Dana"]},
        evidence_refs=[
            SourceRef(kind="journal_entry", ref_id="journal-mar",
                      evidence_kind="quote"),
            SourceRef(kind="journal_entry", ref_id="journal-may",
                      evidence_kind="quote"),
        ],
    )
    store.accept_reading(USER, standing.id)
    change = _change(
        store, thread.id, "contradicted", "event", "evt-verdict",
        at="2026-07-20T10:00:00+00:00",
    )
    store.set_change_status(USER, change.id, "confirmed")
    return store.get_thread(USER, thread.id)


def test_case3_contradiction_must_be_carried(store):
    """G3: a reading that omits the confirmed contradiction is
    discarded; one that carries it is a valid candidate."""
    thread = _case3(store)
    rows = _rows(store, thread.id)
    verdict_row = [r for r in rows if r.ref_id == "evt-verdict"][0]

    omitting = FakeGen(
        lambda prompt: _progression_json(_prompt_row_ids(prompt))
    )
    result = assess_thread(store, USER, thread.id, generate_fn=omitting)
    assert not [
        c for c in result.candidates if isinstance(c, ProgressionCandidate)
    ]

    def carrying(prompt):
        return _progression_json(
            _prompt_row_ids(prompt),
            contradiction={
                "evidence_refs": [verdict_row.id],
                "note": "the July verdict reversed the trust arc",
            },
        )

    fake = FakeGen(carrying)
    result2 = assess_thread(store, USER, thread.id, generate_fn=fake)
    candidates = [
        c for c in result2.candidates if isinstance(c, ProgressionCandidate)
    ]
    assert len(candidates) == 1
    assert candidates[0].reading["contradiction"]["evidence_refs"] == [
        verdict_row.id
    ]


def test_validation_out_of_set_citation_discarded(store):
    thread = _case1(store)

    def responder(prompt):
        row_ids = _prompt_row_ids(prompt)
        row_ids[1] = "tev-000000000000000000000000"
        return _progression_json(row_ids)

    fake = FakeGen(responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    assert not [
        c for c in result.candidates if isinstance(c, ProgressionCandidate)
    ]
    propose_all(store, USER, result)
    assert store.readings_for(USER, thread.id) == []


def test_validation_out_of_order_steps_discarded(store):
    thread = _case1(store)

    def responder(prompt):
        row_ids = _prompt_row_ids(prompt)
        row_ids.reverse()
        return _progression_json(row_ids)

    fake = FakeGen(responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    assert not [
        c for c in result.candidates if isinstance(c, ProgressionCandidate)
    ]


def test_validation_none_declines_without_a_row(store):
    thread = _case1(store)
    fake = FakeGen(lambda prompt: "NONE")
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    assert result.candidates == []
    assert fake.calls == 1
    propose_all(store, USER, result)
    assert store.readings_for(USER, thread.id) == []


def test_proposal_shape(store):
    """The written proposal: steward-authored, proposed, progression
    unknown, evidence ordered as the steps, coverage attached."""
    thread = _case1(store)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(store, USER, thread.id, generate_fn=fake)
    propose_all(store, USER, result)
    reading = [
        r for r in store.readings_for(USER, thread.id)
        if isinstance(r.reading, dict)
        and r.reading.get("kind") == "progression_candidate"
    ][0]
    assert reading.author == "steward"
    assert reading.status == "proposed"
    payload = reading.reading
    assert reading.progression.state == "unknown"
    step_refs = [
        ref for step in payload["steps"] for ref in step["evidence_refs"]
    ]
    assert reading.evidence_refs == step_refs
    assert payload["coverage"]["evidence_examined"] == 4
    assert payload["rivals"]["recurrence"]
    assert payload["rivals"]["coincidence"]


def test_verdict_flow_supersede_and_unresolved(store):
    """Accepting a newer reading supersedes the standing one;
    unresolved leaves the row exactly as it was."""
    thread = _case1(store)
    rows = _rows(store, thread.id)
    refs = [SourceRef(kind=r.ref_kind, ref_id=r.ref_id,
                      evidence_kind="quote") for r in rows[:2]]
    first = store.propose_reading(
        USER, thread.id, author="steward",
        reading={"tensions": ["a"], "milestones": []}, evidence_refs=refs,
    )
    second = store.propose_reading(
        USER, thread.id, author="steward",
        reading={"tensions": ["b"], "milestones": []}, evidence_refs=refs,
    )
    apply_verdict(store, USER, f"reading:{first.id}", "accepted")
    apply_verdict(store, USER, f"reading:{second.id}", "accepted")
    by_id = {r.id: r for r in store.readings_for(USER, thread.id)}
    assert by_id[first.id].status == "superseded"
    assert by_id[second.id].status == "accepted"

    third = store.propose_reading(
        USER, thread.id, author="steward",
        reading={"tensions": ["c"], "milestones": []}, evidence_refs=refs,
    )
    apply_verdict(store, USER, f"reading:{third.id}", "unresolved")
    assert store.readings_for(USER, thread.id, status="proposed")[0].id == third.id


def test_recognition_imports_no_conversation_or_generation():
    """The separation is structural: no conversation path, no
    generation machinery, no signals store, no review filing."""
    import ast
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "local_ai" / "narrative" / "recognition.py"
    )
    tree = ast.parse(path.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_fragments = (
        "conversation", "agent_intake", "signals", "encounter",
        "meeting", "reply", "llm_keys", "review",
    )
    for module in imported:
        for fragment in forbidden_fragments:
            assert fragment not in module, f"forbidden import: {module}"


# ---------------------------------------------------------------------------
# §6.2 positive twin — the standing frame reaches every seat identically
# ---------------------------------------------------------------------------


def test_accepted_frame_renders_for_all_seven_seats(store):
    a, _b = _pair(store)
    rows = _rows(store, a.id)
    fitting = store.set_fitting(
        USER,
        a.id,
        lens_id="departure_initiation_return",
        evidence_refs=[rows[0].id, rows[1].id],
        status="proposed",
        proposed_by="steward",
    )
    store.set_fitting_status(USER, fitting.id, "accepted")
    branches = [
        "seat:mentor", "seat:champion", "seat:guardian",
        "seat:ambassador", "seat:conductor", "seat:skeptic",
        "seat:maverick",
    ]
    lines = []
    for branch in branches:
        prepared = _context(store, branch_id=branch, attended="atlas")
        assert prepared.available, branch
        fitting_lines = [
            line for line in prepared.block.splitlines() if "fitting:" in line
        ]
        assert len(fitting_lines) == 1, branch
        lines.append(fitting_lines[0])
    assert len(set(lines)) == 1
    assert "Departure, Initiation, Return — the Hero's Journey" in lines[0]
    assert "(accepted)" in lines[0]


# ---------------------------------------------------------------------------
# Case 6 — Explore with Aria (the one conversational bridge)
# ---------------------------------------------------------------------------


def test_explore_with_aria_bridge(tmp_path, monkeypatch):
    """The user carries a proposal into a strand thread as a source;
    the proposal's own state does not move."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes import steward_review_routes as routes
    from api.routes.auth_routes import get_current_user
    from local_ai.conversation.store import ConversationStore
    from local_ai.strand_interviews.guidance import strand_guidance_block

    nstore = NarrativeStore(db_path=tmp_path / "narrative.db")
    thread = _case1(nstore)
    fake = FakeGen(_valid_progression_responder)
    result = assess_thread(nstore, USER, thread.id, generate_fn=fake)
    propose_all(nstore, USER, result)
    reading = [
        r for r in nstore.readings_for(USER, thread.id)
        if isinstance(r.reading, dict)
        and r.reading.get("kind") == "progression_candidate"
    ][0]

    monkeypatch.setattr(
        routes, "get_narrative_store",
        lambda: NarrativeStore(db_path=tmp_path / "narrative.db"),
    )
    monkeypatch.setattr(
        routes, "get_conversation_store",
        lambda: ConversationStore(db_path=tmp_path / "conv.db"),
    )
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": USER}
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        f"/steward/review/reading/{reading.id}/explore",
        json={"strand_key": "voice"},
    )
    assert resp.status_code == 200, resp.text
    # The route closes the stores it was handed (open-query-close);
    # re-open on the same files to inspect what landed.
    nstore = NarrativeStore(db_path=tmp_path / "narrative.db")
    cstore = ConversationStore(db_path=tmp_path / "conv.db")
    sources = cstore.list_strand_sources(USER, "voice")
    assert len(sources) == 1
    assert sources[0]["ref"] == f"steward:reading:{reading.id}"
    assert "a development" in sources[0]["excerpt_redacted"]
    block = strand_guidance_block(
        "voice",
        sources=[
            {
                "kind": s["kind"],
                "label": s["label"],
                "excerpt": s["excerpt_redacted"],
            }
            for s in sources
        ],
    )
    assert "a development" in block
    # Exploration is not a verdict: the proposal is untouched.
    assert nstore.readings_for(USER, thread.id)[0].status == "proposed"
    # Unknown ids stay indistinguishable; bad kinds are refused.
    resp404 = client.post(
        "/steward/review/reading/rdg-000000000000000000000000/explore",
        json={"strand_key": "voice"},
    )
    assert resp404.status_code == 404
    resp400 = client.post(
        f"/steward/review/change/{reading.id}/explore",
        json={"strand_key": "voice"},
    )
    assert resp400.status_code == 400
