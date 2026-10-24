"""Narrative Steward S0 — narrative state foundation.

Covers local_ai/narrative/ (store, refs, lenses, models) per the
audit's Part IV S0 acceptance tests and Part IX's ratified schema
refinement:

- a user-declared thread keeps its founding evidence; archiving
  preserves evidence and readings (no cascade delete);
- lens library integrity (phases, fit signals, non-empty cautions)
  and fittings referencing real lenses and threads;
- INVARIANT 1: a reading with no evidence refs cannot be stored;
- INVARIANT 2: a thread change cannot be recorded without at least
  one NEW evidence ref (the anti-manufacture rule);
- tier inadmissibility: Dramatization and Interpretation refs are
  refused as evidence by type, at every evidence-citing write;
- Part IX representation round-trips: multi-scale readings with a
  primary scale; progression positioned (bound to its lens) /
  unknown / inapplicable; threads with and without scope; the
  involvement ledger record;
- the no-LLM rule: the narrative package imports no model,
  provider, or generation machinery (AST-checked, not by trust).

Stores are tmp SQLite files. No surface is touched: S0 has no
routes, no analysis, and no consumers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from local_ai.narrative import (
    InadmissibleEvidenceError,
    NarrativeStore,
    ProgressionPosition,
    SourceRef,
)
from local_ai.narrative.lenses import LENSES, get_lens

USER = "user-1"
OTHER = "user-2"

CLAIM_REF = SourceRef(kind="claim", ref_id="claim-9", evidence_kind="quote")
EVENT_REF = SourceRef(kind="event", ref_id="evt-7", evidence_kind="entity_ref")
ENTRY_REF = SourceRef(kind="journal_entry", ref_id="entry-3", evidence_kind="quote")
DRAMA_REF = SourceRef(kind="story_artifact", ref_id="story-1")
SCENE_REF = SourceRef(kind="scene_render", ref_id="scene-1")
READING_REF = SourceRef(kind="reading", ref_id="rdg-elsewhere")


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _thread(store, **kwargs):
    kwargs.setdefault("title", "The orchard years")
    return store.create_thread(USER, **kwargs)


# -- threads: creation, scope, founding evidence (audit S0 test 1) -------------


def test_user_declared_thread_keeps_claim_evidence(store):
    thread = store.create_thread(
        USER,
        origin="claim",
        title="From a claim",
        evidence_refs=[CLAIM_REF],
    )
    evidence = store.evidence_for(USER, thread.id)
    assert len(evidence) == 1
    assert evidence[0].ref_kind == "claim"
    assert evidence[0].ref_id == "claim-9"
    # the claim's anchor kind rides through untouched
    assert evidence[0].evidence_kind == "quote"


def test_thread_scope_is_optional(store):
    bare = _thread(store)
    assert bare.scope is None
    assert store.get_thread(USER, bare.id).scope is None

    scoped = _thread(store, scope="work")
    assert scoped.scope == "work"
    assert store.get_thread(USER, scoped.id).scope == "work"


def test_thread_creation_validates_vocabulary(store):
    with pytest.raises(ValueError):
        store.create_thread(USER, origin=" vibes")
    with pytest.raises(ValueError):
        store.create_thread(USER, strand_weights={"destiny": 1.0})
    with pytest.raises(ValueError):
        store.create_thread(USER, cast=[{"seat": "wizard", "role": "x"}])
    ok = store.create_thread(
        USER,
        strand_weights={"people": 0.7, "self": 0.3},
        cast=[{"seat": "conductor", "role": "integrator"}],
        aspiration_refs=["core_aim"],
    )
    assert ok.strand_weights == {"people": 0.7, "self": 0.3}
    assert ok.cast == [{"seat": "conductor", "role": "integrator"}]
    assert ok.aspiration_refs == ["core_aim"]


def test_threads_for_filters_and_user_isolation(store):
    mine = _thread(store, cast=[{"seat": "mentor", "role": "witness"}])
    _thread(store)
    store.create_thread(OTHER, title="not mine")

    assert mine.id in {t.id for t in store.threads_for(USER)}
    assert all(t.user_id == USER for t in store.threads_for(USER))
    assert store.threads_for(USER, seat="mentor")[0].id == mine.id
    assert store.threads_for(USER, seat="skeptic") == []
    assert store.get_thread(OTHER, mine.id) is None
    with pytest.raises(ValueError):
        store.propose_reading(
            OTHER, mine.id, author="user", evidence_refs=[CLAIM_REF]
        )


def test_archive_preserves_evidence_and_readings(store):
    thread = _thread(store, evidence_refs=[CLAIM_REF])
    reading = store.propose_reading(
        USER, thread.id, author="user",
        reading={"tensions": ["roots vs. road"]},
        evidence_refs=[CLAIM_REF],
    )
    store.accept_reading(USER, reading.id)
    store.set_thread_status(USER, thread.id, "active")
    archived = store.set_thread_status(USER, thread.id, "archived")
    assert archived.status == "archived"
    # no cascade delete: the record of the story survives its closing
    assert len(store.evidence_for(USER, thread.id)) == 1
    readings = store.readings_for(USER, thread.id)
    assert len(readings) == 1 and readings[0].status == "accepted"


# -- evidence attach: dedupe + the tier gate ------------------------------------


def test_add_evidence_dedupes(store):
    thread = _thread(store)
    first = store.add_evidence(USER, thread.id, CLAIM_REF, note="why")
    again = store.add_evidence(USER, thread.id, CLAIM_REF)
    assert first.id == again.id
    assert len(store.evidence_for(USER, thread.id)) == 1


@pytest.mark.parametrize("bad_ref", [DRAMA_REF, SCENE_REF, READING_REF])
def test_non_evidence_tiers_are_inadmissible_as_evidence(store, bad_ref):
    """Tier D (dramatization) and Tier I (interpretation) refs are
    refused by type at the attach choke point — not by convention."""
    thread = _thread(store)
    with pytest.raises(InadmissibleEvidenceError):
        store.add_evidence(USER, thread.id, bad_ref)
    with pytest.raises(InadmissibleEvidenceError):
        store.propose_reading(
            USER, thread.id, author="steward",
            reading={"tensions": []}, evidence_refs=[bad_ref],
        )
    with pytest.raises(InadmissibleEvidenceError):
        store.set_fitting(
            USER, thread.id, lens_id="descent_and_return",
            evidence_refs=[bad_ref],
        )
    assert store.evidence_for(USER, thread.id) == []


def test_unknown_ref_kind_is_a_programming_error(store):
    with pytest.raises(ValueError):
        SourceRef(kind="horoscope", ref_id="x")


# -- readings: invariant 1, scales, progression (Part IX round-trips) ----------


def test_reading_without_evidence_cannot_be_stored(store):
    thread = _thread(store)
    with pytest.raises(ValueError):
        store.propose_reading(
            USER, thread.id, author="steward",
            reading={"tensions": ["x"]}, evidence_refs=[],
        )
    with pytest.raises(ValueError):
        store.propose_reading(USER, thread.id, author="user")
    assert store.readings_for(USER, thread.id) == []


def test_reading_multi_scale_round_trip(store):
    thread = _thread(store, evidence_refs=[ENTRY_REF])
    reading = store.propose_reading(
        USER, thread.id, author="conductor",
        reading={
            "tensions": ["freedom vs. responsibility"],
            "open_questions": ["what does dependable mean here?"],
            "milestones": [],
            "cast_notes": {"conductor": "holds the whole"},
        },
        evidence_refs=[ENTRY_REF],
        scales=["existential", "institutional", "personal"],
        primary_scale="personal",
    )
    back = store.readings_for(USER, thread.id)[0]
    assert back.id == reading.id
    # several scales coexist; none is resolved into the others
    assert back.scales == ["existential", "institutional", "personal"]
    assert back.primary_scale == "personal"
    assert back.reading["tensions"] == ["freedom vs. responsibility"]
    assert len(back.evidence_refs) == 1


def test_primary_scale_must_be_among_scales(store):
    thread = _thread(store, evidence_refs=[ENTRY_REF])
    with pytest.raises(ValueError):
        store.propose_reading(
            USER, thread.id, author="user",
            evidence_refs=[ENTRY_REF],
            scales=["personal"], primary_scale="mythological",
        )
    # and a reading may carry no scale at all
    plain = store.propose_reading(
        USER, thread.id, author="user", evidence_refs=[ENTRY_REF]
    )
    assert plain.scales == [] and plain.primary_scale is None


def test_progression_positioned_is_bound_to_its_lens(store):
    thread = _thread(store, evidence_refs=[ENTRY_REF])
    reading = store.propose_reading(
        USER, thread.id, author="steward",
        evidence_refs=[ENTRY_REF],
        progression=ProgressionPosition.positioned(
            "departure_initiation_return", "initiation"
        ),
    )
    back = store.readings_for(USER, thread.id)[0]
    assert back.progression.state == "positioned"
    assert back.progression.lens_id == "departure_initiation_return"
    assert back.progression.phase == "initiation"
    assert reading.progression == back.progression


def test_progression_position_rejects_foreign_phases_and_lenses(store):
    thread = _thread(store, evidence_refs=[ENTRY_REF])
    # "fallow" belongs to the seasonal lens, not the monomyth — a
    # position is bound to ITS lens's template, not a shared ladder
    with pytest.raises(ValueError):
        store.propose_reading(
            USER, thread.id, author="steward",
            evidence_refs=[ENTRY_REF],
            progression=ProgressionPosition.positioned(
                "departure_initiation_return", "fallow"
            ),
        )
    with pytest.raises(ValueError):
        store.propose_reading(
            USER, thread.id, author="steward",
            evidence_refs=[ENTRY_REF],
            progression=ProgressionPosition.positioned(
                "no_such_lens", "departure"
            ),
        )


def test_progression_unknown_and_inapplicable_are_distinct_states(store):
    thread = _thread(store, evidence_refs=[ENTRY_REF])
    unknown = store.propose_reading(
        USER, thread.id, author="user", evidence_refs=[ENTRY_REF]
    )
    assert unknown.progression.state == "unknown"
    assert unknown.progression.lens_id is None

    inapplicable = store.propose_reading(
        USER, thread.id, author="user",
        evidence_refs=[ENTRY_REF],
        progression=ProgressionPosition.inapplicable(),
    )
    assert inapplicable.progression.state == "inapplicable"

    by_id = {r.id: r for r in store.readings_for(USER, thread.id)}
    assert by_id[unknown.id].progression.state == "unknown"
    assert by_id[inapplicable.id].progression.state == "inapplicable"
    # a non-positioned state may not smuggle a lens in sideways
    with pytest.raises(ValueError):
        store.propose_reading(
            USER, thread.id, author="user",
            evidence_refs=[ENTRY_REF],
            progression=ProgressionPosition(
                state="unknown", lens_id="descent_and_return"
            ),
        )


def test_accepted_reading_supersedes_the_prior_standing(store):
    thread = _thread(store, evidence_refs=[CLAIM_REF])
    first = store.propose_reading(
        USER, thread.id, author="mentor", evidence_refs=[CLAIM_REF]
    )
    attached = store.add_evidence(USER, thread.id, EVENT_REF)
    second = store.propose_reading(
        USER, thread.id, author="mentor",
        evidence_refs=[attached.id],
    )
    store.accept_reading(USER, first.id)
    assert store.get_thread(USER, thread.id).standing_reading_id == first.id
    store.accept_reading(USER, second.id)
    thread_now = store.get_thread(USER, thread.id)
    assert thread_now.standing_reading_id == second.id
    statuses = {r.id: r.status for r in store.readings_for(USER, thread.id)}
    assert statuses[first.id] == "superseded"
    assert statuses[second.id] == "accepted"
    with pytest.raises(ValueError):
        store.accept_reading(USER, second.id)  # no longer proposed


def test_reading_cannot_cite_another_threads_evidence(store):
    mine = _thread(store, evidence_refs=[CLAIM_REF])
    other = _thread(store)
    foreign_id = store.evidence_for(USER, mine.id)[0].id
    with pytest.raises(ValueError):
        store.propose_reading(
            USER, other.id, author="user", evidence_refs=[foreign_id]
        )


# -- changes: invariant 2 (no change without NEW evidence) ----------------------


def test_change_requires_new_evidence(store):
    thread = _thread(store, evidence_refs=[CLAIM_REF])
    existing_id = store.evidence_for(USER, thread.id)[0].id

    # no refs at all
    with pytest.raises(ValueError):
        store.record_change(USER, thread.id, kind="extended")
    # only the already-attached ref, by value
    with pytest.raises(ValueError):
        store.record_change(
            USER, thread.id, kind="extended", evidence_refs=[CLAIM_REF]
        )
    # only the already-attached row, by id
    with pytest.raises(ValueError):
        store.record_change(
            USER, thread.id, kind="extended", evidence_refs=[existing_id]
        )
    assert store.changes_for(USER, thread.id) == []
    assert store.get_thread(USER, thread.id).last_change_at is None


def test_change_with_new_evidence_is_recorded(store):
    thread = _thread(store, evidence_refs=[CLAIM_REF])
    existing_id = store.evidence_for(USER, thread.id)[0].id
    change = store.record_change(
        USER, thread.id, kind="extended",
        evidence_refs=[existing_id, EVENT_REF],  # old context + NEW ref
    )
    assert change.status == "proposed"
    assert len(change.evidence_refs) == 2
    assert len(store.evidence_for(USER, thread.id)) == 2
    updated = store.get_thread(USER, thread.id)
    assert updated.last_change_at is not None

    confirmed = store.set_change_status(USER, change.id, "confirmed")
    assert confirmed.status == "confirmed"
    with pytest.raises(ValueError):
        store.set_change_status(USER, change.id, "dismissed")


# -- retirement: first-class, with successor (audit Part II §5) -----------------


def test_retirement_requires_reason_and_successor(store):
    thread = _thread(store)
    with pytest.raises(ValueError):
        store.set_thread_status(USER, thread.id, "retired")
    with pytest.raises(ValueError):
        store.set_thread_status(
            USER, thread.id, "retired", retirement_reason="reinterpreted"
        )
    with pytest.raises(ValueError):
        store.set_thread_status(
            USER, thread.id, "retired",
            retirement_reason="reinterpreted",
            successor_thread_id=thread.id,
        )
    successor = _thread(store, title="The same ground, another story")
    retired = store.set_thread_status(
        USER, thread.id, "retired",
        retirement_reason="reinterpreted",
        successor_thread_id=successor.id,
    )
    assert retired.status == "retired"
    assert retired.retirement_reason == "reinterpreted"
    assert retired.successor_thread_id == successor.id
    with pytest.raises(ValueError):
        store.set_thread_status(USER, thread.id, "active")  # no quiet revival


# -- lens library + fittings (audit S0 test 2) -----------------------------------


def test_lens_library_integrity():
    assert len(LENSES) >= 3
    for lens in LENSES:
        assert lens.phases, lens.id
        assert lens.fit_signals, lens.id
        assert lens.cautions, lens.id  # non-empty cautions, always
        assert lens.source_note, lens.id  # attribution is data
        for phase in lens.phases:
            assert phase.name and phase.what_it_looks_for


def test_fitting_references_real_lens_and_thread(store):
    thread = _thread(store, evidence_refs=[CLAIM_REF])
    with pytest.raises(ValueError):
        store.set_fitting(
            USER, thread.id, lens_id="astrology",
            evidence_refs=[CLAIM_REF],
        )
    with pytest.raises(ValueError):
        store.set_fitting(
            USER, "thr-missing", lens_id="descent_and_return",
            evidence_refs=[CLAIM_REF],
        )
    with pytest.raises(ValueError):
        store.set_fitting(USER, thread.id, lens_id="descent_and_return")
    fitting = store.set_fitting(
        USER, thread.id, lens_id="descent_and_return",
        evidence_refs=[CLAIM_REF], proposed_by="user",
    )
    assert fitting.status == "proposed"
    assert get_lens(fitting.lens_id) is not None


def test_one_live_fitting_per_thread(store):
    thread = _thread(store, evidence_refs=[CLAIM_REF])
    first = store.set_fitting(
        USER, thread.id, lens_id="descent_and_return",
        evidence_refs=[CLAIM_REF],
    )
    store.set_fitting_status(USER, first.id, "offered")
    accepted = store.set_fitting_status(USER, first.id, "accepted")
    assert accepted.decided_at is not None
    assert store.get_thread(USER, thread.id).lens_fitting_id == first.id

    second = store.set_fitting(
        USER, thread.id, lens_id="ordeal_and_tempering",
        evidence_refs=[CLAIM_REF],
    )
    with pytest.raises(ValueError):
        store.set_fitting_status(USER, second.id, "accepted")
    # retire the live one — a recorded act — then the second may live
    store.set_fitting_status(USER, first.id, "retired")
    assert store.get_thread(USER, thread.id).lens_fitting_id is None
    store.set_fitting_status(USER, second.id, "accepted")
    assert store.get_thread(USER, thread.id).lens_fitting_id == second.id


def test_fitting_rejection_is_recorded_with_its_verdict_time(store):
    thread = _thread(store, evidence_refs=[CLAIM_REF])
    fitting = store.set_fitting(
        USER, thread.id, lens_id="sowing_growth_harvest_fallow",
        evidence_refs=[CLAIM_REF],
    )
    rejected = store.set_fitting_status(USER, fitting.id, "rejected")
    assert rejected.status == "rejected"
    assert rejected.decided_at is not None
    with pytest.raises(ValueError):
        store.set_fitting_status(USER, fitting.id, "accepted")


# -- involvement ledger (Part VII) -------------------------------------------------


def test_involvement_measure_round_trip(store):
    measure = store.record_involvement(
        USER, subject_kind="artifact", subject_id="story-1",
        user_authored_units=30, user_edited_units=10,
        synthesized_units=60, note="words",
    )
    assert measure.total_units == 100
    assert measure.user_share == pytest.approx(0.4)  # edits count as the user's

    back = store.involvement_for(USER, "artifact", "story-1")
    assert back.id == measure.id
    assert back.user_authored_units == 30
    assert back.user_share == pytest.approx(0.4)

    # upsert: one current measure per subject, replaced not stacked
    updated = store.record_involvement(
        USER, subject_kind="artifact", subject_id="story-1",
        user_authored_units=50, user_edited_units=10,
        synthesized_units=40, note="words, after the user's pass",
    )
    assert updated.id == measure.id
    assert len(store.involvements_for(USER)) == 1
    assert updated.user_share == pytest.approx(0.6)

    profile = store.record_involvement(
        USER, subject_kind="trained_profile", subject_id="conductor-you",
    )
    assert profile.user_share is None  # unmeasured, not zero-measured
    assert len(store.involvements_for(USER)) == 2
    assert store.involvement_for(OTHER, "artifact", "story-1") is None


def test_involvement_measure_validates(store):
    with pytest.raises(ValueError):
        store.record_involvement(
            USER, subject_kind="artifact", subject_id="x",
            synthesized_units=-1,
        )
    with pytest.raises(ValueError):
        store.record_involvement(
            USER, subject_kind="vibe", subject_id="x"
        )


# -- the no-LLM rule, checked mechanically -----------------------------------------


def test_narrative_package_imports_no_llm_machinery():
    package_dir = Path(__file__).resolve().parent.parent / "local_ai" / "narrative"
    banned_modules = {"openai", "anthropic", "ollama", "httpx", "requests"}
    banned_prefixes = (
        "local_ai.llm",
        "local_ai.providers",
        "local_ai.conversation",  # the reply assembler / surfaces
    )
    offenders: list[str] = []
    for path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                root = name.split(".")[0]
                if root in banned_modules or name.startswith(banned_prefixes):
                    offenders.append(f"{path.name}: {name}")
    assert offenders == []
