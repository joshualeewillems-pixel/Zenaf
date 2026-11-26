"""Dismissal-kind coverage: correspondences + fittings
(Consultation 1 disposition, 2026-11-25).

PR #440 wired dismissal memory for the two pre-existing kinds
(thread_birth, extension). This increment extends coverage to
the two kinds the disposition assigns, under its rule: after a
formal rejection, the steward must not autonomously re-propose
the same substantive commitment on unchanged grounds. The key
captures the rejected INTERPRETATION on its grounds — never the
grounds alone, never the bare subject (thread pair / thread).

Pins:

- A rejected correspondence writes a ``correspondence``
  dismissal keyed on the relation between the threads (the
  record's own proposed_relationship + mapping — direction
  lives there, the stored thread pair is sorted) over the cited
  evidence keys; recognition's write path consults it.
- A rejected fitting writes a ``fitting`` dismissal keyed on
  the lens placement (thread + lens) over the cited evidence
  keys; recognition's write path consults it.
- Specificity: a different relation over the same pair, the
  reverse relation, a different lens on the same thread, and
  the same lens on a different thread are all NOT dismissed.
- Fingerprint churn: reordered citations, rebuilt evidence
  rows (new row ids, same refs), and an irrelevant excerpt
  attached to a thread do not make the same commitment look
  new. Genuinely new cited evidence reopens (the dismissal is
  evidence-keyed, not a ban).
- Race: the check sits at the final proposal-write, so a
  rejection recorded after a result's candidates were selected
  still gates that result's writes.
- Visitor initiation: the shared writers consult no dismissal
  state — a dismissed commitment can still be created at the
  visitor's own initiation.
- Absence: readings (deferred by the disposition) and
  oversight items (no interpretive kind) write no dismissal
  rows on rejection; accepted/unresolved verdicts write none
  for the new kinds either.

Stores are tmp SQLite files. No generation: candidates are
constructed directly, as a completed assessment would return
them.
"""

from __future__ import annotations

from local_ai.narrative import NarrativeStore
from local_ai.narrative.correspondence import propose_correspondence
from local_ai.narrative.derivation import (
    correspondence_signature_from_fields,
    fitting_signature_from_keys,
)
from local_ai.narrative.models import DISMISSAL_KINDS
from local_ai.narrative.recognition import (
    CorrespondenceCandidate,
    FittingCandidate,
    RecognitionResult,
    propose_all,
)
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.review import apply_verdict, pending_review_items

USER = "user-1"

LENS_A = "departure_initiation_return"
LENS_B = "sowing_growth_harvest_fallow"

RELATIONSHIP = "the orchard thread's planting causes the harvest thread's yield"
RELATIONSHIP_OTHER = "the two threads share a constraint neither can lift alone"
RELATIONSHIP_REVERSED = "the harvest thread's yield causes the orchard thread's planting"
MAPPING = {"thread a": "the planting", "thread b": "the yield"}
MAPPING_REVERSED = {"thread a": "the yield", "thread b": "the planting"}
TENSION = "one story advances while the other stalls"
LIMITATIONS = "the two threads may simply record different seasons"


def _store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _thread(store, title):
    thread = store.create_thread(USER, origin="user_declared", title=title)
    store.set_thread_status(USER, thread.id, "active")
    return store.get_thread(USER, thread.id)


def _add(store, thread_id, kind, ref_id, note=""):
    return store.add_evidence(
        USER,
        thread_id,
        SourceRef(kind=kind, ref_id=ref_id, evidence_kind="quote"),
        note=note,
    )


def _pair(store):
    """Two active threads, one evidence row each."""
    a = _thread(store, "The orchard")
    b = _thread(store, "The harvest")
    row_a = _add(store, a.id, "event", "evt-a1", note="planted the first row")
    row_b = _add(store, b.id, "event", "evt-b1", note="the yield came in")
    return a, b, row_a, row_b


def _corr_candidate(a, b, refs, *, relationship=RELATIONSHIP, mapping=None):
    return CorrespondenceCandidate(
        thread_ids=(a.id, b.id),
        evidence_refs=tuple(refs),
        structural_tension=TENSION,
        proposed_relationship=relationship,
        limitations=LIMITATIONS,
        candidate_metaphor=None,
        mapping=dict(MAPPING if mapping is None else mapping),
    )


def _fitting_candidate(thread, lens_id, refs):
    return FittingCandidate(
        thread_id=thread.id,
        lens_id=lens_id,
        evidence_refs=tuple(refs),
        matched_signals=(),
    )


def _propose(store, *candidates):
    return propose_all(store, USER, RecognitionResult(candidates=list(candidates)))


def _pending(store, kind):
    return [i for i in pending_review_items(store, USER) if i.item_kind == kind]


def _keys(store, thread_id, row_ids):
    by_id = {r.id: f"{r.ref_kind}:{r.ref_id}" for r in store.evidence_for(USER, thread_id)}
    return [by_id[r] for r in row_ids]


def _delete_evidence_rows(store, row_ids):
    with store._lock:
        for row_id in row_ids:
            store._conn.execute(
                "DELETE FROM thread_evidence WHERE id = ?", (row_id,)
            )
        store._conn.commit()


def _delete_fitting_row(store, fitting_id):
    with store._lock:
        store._conn.execute(
            "DELETE FROM lens_fittings WHERE id = ?", (fitting_id,)
        )
        store._conn.commit()


# -- Registration ---------------------------------------------------------------


def test_new_kinds_registered_and_roundtrip(tmp_path):
    assert "correspondence" in DISMISSAL_KINDS
    assert "fitting" in DISMISSAL_KINDS
    store = _store(tmp_path)
    for kind in ("correspondence", "fitting"):
        store.record_dismissal(USER, kind=kind, signature=f"{kind}:probe")
        assert store.is_dismissed(USER, kind=kind, signature=f"{kind}:probe")


def test_signature_specificity_units():
    keys = ["event:e1", "event:e2"]
    base = fitting_signature_from_keys("thr-1", LENS_A, keys)
    assert base == fitting_signature_from_keys("thr-1", LENS_A, list(reversed(keys)))
    assert base != fitting_signature_from_keys("thr-1", LENS_B, keys)
    assert base != fitting_signature_from_keys("thr-2", LENS_A, keys)

    corr = correspondence_signature_from_fields(
        ["thr-b", "thr-a"], RELATIONSHIP, MAPPING, keys
    )
    # Thread order and mapping key order are not identity.
    assert corr == correspondence_signature_from_fields(
        ["thr-a", "thr-b"],
        RELATIONSHIP,
        dict(reversed(list(MAPPING.items()))),
        list(reversed(keys)),
    )
    # A different relation over the same pair is a different key.
    assert corr != correspondence_signature_from_fields(
        ["thr-a", "thr-b"], RELATIONSHIP_OTHER, MAPPING, keys
    )
    # The reverse relation is a different key.
    assert corr != correspondence_signature_from_fields(
        ["thr-a", "thr-b"], RELATIONSHIP_REVERSED, MAPPING_REVERSED, keys
    )


# -- Correspondence: rejection writes, write path consults ----------------------


def test_rejected_correspondence_writes_dismissal(tmp_path):
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    written = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    assert len(written) == 1
    corr_id = written[0]
    assert store.dismissals_for(USER) == []

    result = apply_verdict(store, USER, f"correspondence:{corr_id}", "rejected")

    assert result.status == "rejected"
    rows = store.dismissals_for(USER)
    assert len(rows) == 1
    assert rows[0].kind == "correspondence"
    expected = correspondence_signature_from_fields(
        [a.id, b.id],
        RELATIONSHIP,
        MAPPING,
        _keys(store, a.id, [row_a.id]) + _keys(store, b.id, [row_b.id]),
    )
    assert rows[0].signature == expected
    assert store.is_dismissed(USER, kind="correspondence", signature=expected)


def test_rejected_correspondence_not_reproposed(tmp_path):
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    written = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    apply_verdict(store, USER, f"correspondence:{written[0]}", "rejected")

    again = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))

    assert again == []
    corrs = store.correspondences_for(USER)
    assert len(corrs) == 1
    assert corrs[0].status == "rejected"


def test_different_relation_over_same_pair_not_dismissed(tmp_path):
    """The thread pair alone keys nothing: another relation
    between the same threads is a different commitment."""
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    written = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    apply_verdict(store, USER, f"correspondence:{written[0]}", "rejected")

    other = _propose(
        store,
        _corr_candidate(
            a, b, [row_a.id, row_b.id], relationship=RELATIONSHIP_OTHER
        ),
    )

    assert len(other) == 1
    assert len(store.correspondences_for(USER)) == 2


def test_reverse_relation_not_dismissed(tmp_path):
    """Direction matters where the relation is directional: the
    reverse relation (relationship + mapping carrying the
    direction) is not the rejected commitment."""
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    written = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    apply_verdict(store, USER, f"correspondence:{written[0]}", "rejected")

    reversed_written = _propose(
        store,
        _corr_candidate(
            a,
            b,
            [row_a.id, row_b.id],
            relationship=RELATIONSHIP_REVERSED,
            mapping=MAPPING_REVERSED,
        ),
    )

    assert len(reversed_written) == 1
    assert len(store.correspondences_for(USER)) == 2


# -- Correspondence: fingerprint churn ------------------------------------------


def test_churn_reordered_citations_still_dismissed(tmp_path):
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    written = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    apply_verdict(store, USER, f"correspondence:{written[0]}", "rejected")

    again = _propose(store, _corr_candidate(a, b, [row_b.id, row_a.id]))

    assert again == []
    assert len(store.correspondences_for(USER)) == 1


def test_churn_rebuilt_evidence_rows_still_dismissed(tmp_path):
    """Rebuilt rows carry new row ids but the same refs; the
    dismissal keys on refs, so the commitment does not look new."""
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    written = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    apply_verdict(store, USER, f"correspondence:{written[0]}", "rejected")

    _delete_evidence_rows(store, [row_a.id, row_b.id])
    new_a = _add(store, a.id, "event", "evt-a1", note="planted the first row")
    new_b = _add(store, b.id, "event", "evt-b1", note="the yield came in")
    assert new_a.id != row_a.id and new_b.id != row_b.id

    again = _propose(store, _corr_candidate(a, b, [new_a.id, new_b.id]))

    assert again == []
    assert len(store.correspondences_for(USER)) == 1


def test_churn_irrelevant_excerpt_attached_still_dismissed(tmp_path):
    """An excerpt that attaches to a thread without being cited
    by the proposal is not part of its grounds."""
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    written = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    apply_verdict(store, USER, f"correspondence:{written[0]}", "rejected")

    _add(store, a.id, "event", "evt-a2", note="an unrelated note on the orchard")

    again = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))

    assert again == []
    assert len(store.correspondences_for(USER)) == 1


def test_new_cited_evidence_reopens_correspondence(tmp_path):
    """Evidence-keyed, not a ban: the same relation citing
    genuinely different evidence is a proposal on new grounds."""
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    written = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    apply_verdict(store, USER, f"correspondence:{written[0]}", "rejected")

    row_a2 = _add(store, a.id, "event", "evt-a9", note="replanted after the storm")
    row_b2 = _add(store, b.id, "event", "evt-b9", note="a second, larger yield")
    reopened = _propose(store, _corr_candidate(a, b, [row_a2.id, row_b2.id]))

    assert len(reopened) == 1
    assert len(store.correspondences_for(USER)) == 2


# -- Correspondence: race + visitor initiation -----------------------------------


def test_race_rejection_after_selection_gates_the_write(tmp_path):
    """The candidate list is built first (an in-flight run's
    selection); the rejection lands after; the write must still
    be gated — the check sits at the proposal-write, not at
    selection."""
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    in_flight = RecognitionResult(
        candidates=[_corr_candidate(a, b, [row_a.id, row_b.id])]
    )

    twin = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    apply_verdict(store, USER, f"correspondence:{twin[0]}", "rejected")

    written = propose_all(store, USER, in_flight)

    assert written == []
    assert len(store.correspondences_for(USER)) == 1


def test_visitor_initiated_correspondence_consults_no_dismissal(tmp_path):
    """The shared proposal function writes at the visitor's own
    initiation even while a dismissal stands — dismissal gates
    autonomous proposals only."""
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    written = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    apply_verdict(store, USER, f"correspondence:{written[0]}", "rejected")
    assert len(store.dismissals_for(USER)) == 1

    outcome = propose_correspondence(
        store,
        USER,
        evidence_refs=[row_a.id, row_b.id],
        structural_tension=TENSION,
        proposed_relationship=RELATIONSHIP,
        candidate_metaphor=None,
        mapping=dict(MAPPING),
        limitations=LIMITATIONS,
    )

    assert outcome.correspondence is not None
    assert len(store.correspondences_for(USER)) == 2


def test_accepted_and_unresolved_correspondence_write_no_dismissal(tmp_path):
    store = _store(tmp_path)
    a, b, row_a, row_b = _pair(store)
    written = _propose(store, _corr_candidate(a, b, [row_a.id, row_b.id]))
    apply_verdict(store, USER, f"correspondence:{written[0]}", "unresolved")
    assert store.dismissals_for(USER) == []
    apply_verdict(store, USER, f"correspondence:{written[0]}", "accepted")
    assert store.dismissals_for(USER) == []


# -- Fitting: rejection writes, write path consults -------------------------------


def _fitting_setup(store):
    thread = _thread(store, "The orchard")
    row_1 = _add(store, thread.id, "event", "evt-f1", note="leaving the valley")
    row_2 = _add(store, thread.id, "event", "evt-f2", note="returning home")
    return thread, row_1, row_2


def test_rejected_fitting_writes_dismissal(tmp_path):
    store = _store(tmp_path)
    thread, row_1, row_2 = _fitting_setup(store)
    written = _propose(store, _fitting_candidate(thread, LENS_A, [row_1.id, row_2.id]))
    assert len(written) == 1
    assert store.dismissals_for(USER) == []

    result = apply_verdict(store, USER, f"fitting:{written[0]}", "rejected")

    assert result.status == "rejected"
    rows = store.dismissals_for(USER)
    assert len(rows) == 1
    assert rows[0].kind == "fitting"
    expected = fitting_signature_from_keys(
        thread.id, LENS_A, _keys(store, thread.id, [row_1.id, row_2.id])
    )
    assert rows[0].signature == expected
    assert store.is_dismissed(USER, kind="fitting", signature=expected)


def test_rejected_fitting_not_reproposed_dismissal_is_the_guard(tmp_path):
    """With the rejected fitting's row deleted, the store's own
    Phase 4 T2 row check has nothing left to match — only the
    dismissal can gate the re-proposal, and it does."""
    store = _store(tmp_path)
    thread, row_1, row_2 = _fitting_setup(store)
    written = _propose(store, _fitting_candidate(thread, LENS_A, [row_1.id, row_2.id]))
    apply_verdict(store, USER, f"fitting:{written[0]}", "rejected")
    _delete_fitting_row(store, written[0])
    assert store.fittings_for(USER, thread.id) == []

    again = _propose(store, _fitting_candidate(thread, LENS_A, [row_1.id, row_2.id]))

    assert again == []
    assert store.fittings_for(USER, thread.id) == []


def test_fitting_churn_rebuilt_rows_still_dismissed(tmp_path):
    """Rebuilt evidence rows defeat the store's row-id set
    comparison (Phase 4 T2) but not the ref-keyed dismissal."""
    store = _store(tmp_path)
    thread, row_1, row_2 = _fitting_setup(store)
    written = _propose(store, _fitting_candidate(thread, LENS_A, [row_1.id, row_2.id]))
    apply_verdict(store, USER, f"fitting:{written[0]}", "rejected")

    _delete_evidence_rows(store, [row_1.id, row_2.id])
    new_1 = _add(store, thread.id, "event", "evt-f1", note="leaving the valley")
    new_2 = _add(store, thread.id, "event", "evt-f2", note="returning home")
    assert new_1.id != row_1.id and new_2.id != row_2.id

    again = _propose(store, _fitting_candidate(thread, LENS_A, [new_1.id, new_2.id]))

    assert again == []
    assert len(store.fittings_for(USER, thread.id)) == 1  # the rejected row only


def test_different_lens_on_same_thread_not_dismissed(tmp_path):
    store = _store(tmp_path)
    thread, row_1, row_2 = _fitting_setup(store)
    written = _propose(store, _fitting_candidate(thread, LENS_A, [row_1.id, row_2.id]))
    apply_verdict(store, USER, f"fitting:{written[0]}", "rejected")
    _delete_fitting_row(store, written[0])

    other = _propose(store, _fitting_candidate(thread, LENS_B, [row_1.id, row_2.id]))

    assert len(other) == 1
    fittings = store.fittings_for(USER, thread.id)
    assert len(fittings) == 1
    assert fittings[0].lens_id == LENS_B
    assert fittings[0].status == "proposed"


def test_same_lens_on_different_thread_not_dismissed(tmp_path):
    store = _store(tmp_path)
    thread, row_1, row_2 = _fitting_setup(store)
    written = _propose(store, _fitting_candidate(thread, LENS_A, [row_1.id, row_2.id]))
    apply_verdict(store, USER, f"fitting:{written[0]}", "rejected")

    other_thread = _thread(store, "The valley")
    row_3 = _add(store, other_thread.id, "event", "evt-f3", note="leaving again")
    row_4 = _add(store, other_thread.id, "event", "evt-f4", note="coming back")
    other = _propose(
        store, _fitting_candidate(other_thread, LENS_A, [row_3.id, row_4.id])
    )

    assert len(other) == 1
    assert len(store.fittings_for(USER, other_thread.id)) == 1


def test_fitting_race_rejection_after_selection_gates_the_write(tmp_path):
    store = _store(tmp_path)
    thread, row_1, row_2 = _fitting_setup(store)
    in_flight = RecognitionResult(
        candidates=[_fitting_candidate(thread, LENS_A, [row_1.id, row_2.id])]
    )

    twin = _propose(store, _fitting_candidate(thread, LENS_A, [row_1.id, row_2.id]))
    apply_verdict(store, USER, f"fitting:{twin[0]}", "rejected")
    # Remove the rejected row so only the dismissal can gate.
    _delete_fitting_row(store, twin[0])

    written = propose_all(store, USER, in_flight)

    assert written == []
    assert store.fittings_for(USER, thread.id) == []


def test_visitor_initiated_fitting_consults_no_dismissal(tmp_path):
    """The store writer itself consults no dismissal state: a
    fitting written directly (proposed_by user) stands even
    while a dismissal over the same placement stands. (The
    rejected row is removed first so the store's separate
    Phase 4 T2 row rule is not what decides this.)"""
    store = _store(tmp_path)
    thread, row_1, row_2 = _fitting_setup(store)
    written = _propose(store, _fitting_candidate(thread, LENS_A, [row_1.id, row_2.id]))
    apply_verdict(store, USER, f"fitting:{written[0]}", "rejected")
    assert len(store.dismissals_for(USER)) == 1
    _delete_fitting_row(store, written[0])

    fitting = store.set_fitting(
        USER,
        thread.id,
        lens_id=LENS_A,
        evidence_refs=[row_1.id, row_2.id],
        proposed_by="user",
        status="proposed",
    )

    assert fitting.id
    assert len(store.fittings_for(USER, thread.id)) == 1


def test_accepted_fitting_writes_no_dismissal(tmp_path):
    store = _store(tmp_path)
    thread, row_1, row_2 = _fitting_setup(store)
    written = _propose(store, _fitting_candidate(thread, LENS_A, [row_1.id, row_2.id]))
    apply_verdict(store, USER, f"fitting:{written[0]}", "accepted")
    assert store.dismissals_for(USER) == []


# -- Absence pins: readings deferred, oversight has no kind -----------------------


def test_rejected_reading_writes_no_dismissal(tmp_path):
    """Readings are DEFERRED by the disposition: automatic
    suppression only where interpretation-equivalence is
    reliable, which the current representation cannot promise.
    A rejected reading therefore writes no dismissal row."""
    store = _store(tmp_path)
    thread, row_1, row_2 = _fitting_setup(store)
    reading = store.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={"title": "A reading", "tensions": ["roots vs. road"]},
        evidence_refs=[row_1.id, row_2.id],
    )
    items = _pending(store, "reading")
    assert len(items) == 1

    apply_verdict(store, USER, f"reading:{reading.id}", "rejected")

    assert store.dismissals_for(USER) == []


def test_rejected_oversight_writes_no_dismissal(tmp_path):
    """Oversight items get NO interpretive dismissal kind: an
    oversight proposal is a system condition that warrants
    attention, not an interpretation the visitor is asked to
    adopt. Rejecting one writes no dismissal row."""
    store = _store(tmp_path)
    thread, _, _ = _fitting_setup(store)
    proposal = store.create_oversight_proposal(
        USER, thread.id, "stall", reason="no evidence in 30 days"
    )
    items = _pending(store, "oversight")
    assert len(items) == 1

    result = apply_verdict(store, USER, f"oversight:{proposal.id}", "rejected")

    assert result.status == "dismissed"
    assert store.dismissals_for(USER) == []
