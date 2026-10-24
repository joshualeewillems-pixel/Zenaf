"""Narrative Steward S1 — slow-path thread derivation.

Covers local_ai/narrative/derivation.py per the audit's Part IV S1
acceptance tests (4–6) and the S1 brief's pins:

- S1-4: a cluster on nobody's ground spends zero generations and
  proposes nothing.
- S1-5: a birth proposal cites real Tier-E evidence; a dismissed
  cluster is not re-proposed on re-analysis; new evidence re-opens
  a dismissed cluster (dismissal is content-addressed, not a ban).
- S1-6 (review-gate invariant): nothing from S1 accepts a thread,
  reading, or change, or writes a training signal — proposals land
  nascent/proposed and stay there until a user verdict.
- Part XI boundary 2: derivation with no lens anywhere — changes,
  milestones, and evidence are representable without a lens, and a
  reading's progression stays unknown unless a lens is fitted.
- Part XI boundary 1: derivation never walks containment links
  (AST-pinned) and never infers containment.
- Two-speed law: derivation adds zero generations to any turn path
  (measured chat counts + static separation from reply/service/
  encounter/meeting).
- Store invariants through the derivation path: evidence-required
  readings, change-requires-new-evidence, tier inadmissibility
  (a dramatization ref can never become derivation evidence).

All generations are fake/counting. Stores are tmp SQLite files.
No surface is touched: S1 writes proposed rows to the S0 store
only, installs no pipeline at app assembly, and proposes no lens
fittings.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from local_ai.fellowship.events import FellowshipEvent
from local_ai.narrative import NarrativeStore, SourceRef
from local_ai.narrative.derivation import (
    EvidenceItem,
    StewardPipeline,
    analyze_for_threads,
    birth_signature,
    cluster_items,
    derive_batch,
    dismiss_proposal,
    entry_to_item,
    event_to_item,
    extension_signature,
)

USER = "user-1"
OTHER = "user-2"

#: Focus-anchored wording: "cultivation" is a Gardener focus term, so
#: clusters using it clear the jurisdiction gate deterministically.
FOCUS_TEXT = "cultivation in the orchard, learning what ripens"
#: Nonsense wording: no focus term, no shared token with anything
#: else — the nobody's-ground fixture.
NONSENSE_A = "quuxor flibberty wobble"
NONSENSE_B = "zibblenaut morptastic dremmel"

BIRTH_JSON = json.dumps(
    {
        "title": "The orchard years",
        "tensions": ["roots vs. road"],
        "open_questions": ["what endures?"],
        "milestones": ["planted the first row"],
        "scales": ["personal"],
        "primary_scale": "personal",
    }
)

EXTENSION_JSON = json.dumps(
    {
        "tensions": ["roots vs. road, revisited"],
        "open_questions": ["what endures now?"],
        "milestones": ["pruned the old row"],
        "scales": ["personal"],
        "primary_scale": "personal",
        "change_kind": "extended",
    }
)


def _store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _event(event_id, text, entity="task:orchard-1"):
    entity_type, _, entity_id = entity.partition(":")
    return FellowshipEvent(
        id=event_id,
        kind="conversation_turn",
        user_id=USER,
        entity_type=entity_type,
        entity_id=entity_id,
        evidence_text=text,
        summary="orchard turn",
    )


def _counting_gen(payload, calls):
    def gen(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return payload

    return gen


# -- S1-4: nobody's ground -----------------------------------------------------


def test_cluster_on_nobodys_ground_spends_zero_calls(tmp_path):
    """Audit S1-4: no entity/strand/keyword overlap with any ground,
    no jurisdiction candidacy -> zero LLM calls, zero proposals."""
    store = _store(tmp_path)
    # Linked by a shared entity, but the wording hits no focus term
    # and no strand vector exists — cohesion without candidacy.
    items = [
        event_to_item(_event("evt-1", NONSENSE_A)),
        event_to_item(_event("evt-2", NONSENSE_B)),
    ]
    assert cluster_items(items)[0].items == items  # one cluster, linked
    calls: list = []
    result = derive_batch(USER, items, store, generate_fn=_counting_gen(BIRTH_JSON, calls))
    assert result.calls == 0
    assert result.births == [] and result.readings == [] and result.changes == []
    assert store.threads_for(USER) == []
    assert any("nobody's ground" in s for s in result.skipped)


def test_singleton_with_no_overlap_spends_zero_calls(tmp_path):
    store = _store(tmp_path)
    calls: list = []
    result = derive_batch(
        USER,
        [event_to_item(_event("evt-1", NONSENSE_A))],
        store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
    )
    assert result.calls == 0
    assert result.births == [] and store.threads_for(USER) == []


# -- S1-5: birth proposals -----------------------------------------------------


def test_birth_proposal_cites_real_evidence_and_stays_proposed(tmp_path):
    """Audit S1-5 (first half): a birth cites >= 1 real Tier-E ref
    and lands nascent/proposed — nothing accepted, nothing trained."""
    store = _store(tmp_path)
    items = [
        event_to_item(_event("evt-1", FOCUS_TEXT)),
        event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
    ]
    calls: list = []
    result = derive_batch(USER, items, store, generate_fn=_counting_gen(BIRTH_JSON, calls))
    assert result.calls == 1
    assert len(result.births) == 1 and len(result.readings) == 1
    thread = store.get_thread(USER, result.births[0])
    assert thread.origin == "steward_proposal"
    assert thread.status == "nascent"
    assert thread.title == "The orchard years"
    assert thread.standing_reading_id is None  # S1-6: nothing accepted
    evidence = store.evidence_for(USER, thread.id)
    assert len(evidence) == 2
    assert {row.ref_kind for row in evidence} == {"event"}
    reading = store.readings_for(USER, thread.id, status="proposed")[0]
    assert reading.author == "steward"
    assert reading.reading["tensions"] == ["roots vs. road"]
    assert reading.scales == ["personal"] and reading.primary_scale == "personal"
    assert reading.progression.state == "unknown"  # no lens anywhere (XI-2)
    assert thread.lens_fitting_id is None
    assert store.fittings_for(USER, thread.id) == []


def test_rerun_same_batch_produces_zero_new_rows(tmp_path):
    """Idempotency: re-analysis with no new evidence proposes
    nothing — births are covered by the threads they created."""
    store = _store(tmp_path)
    items = [
        event_to_item(_event("evt-1", FOCUS_TEXT)),
        event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
    ]
    calls: list = []
    gen = _counting_gen(BIRTH_JSON, calls)
    first = derive_batch(USER, items, store, generate_fn=gen)
    assert len(first.births) == 1
    second = derive_batch(USER, items, store, generate_fn=gen)
    assert second.calls == 0
    assert second.births == [] and second.readings == [] and second.changes == []
    assert len(store.threads_for(USER)) == 1


def test_evidence_in_resolved_thread_is_not_reproposed_as_birth(tmp_path):
    """Coverage checks every status: evidence already inside a
    resolved thread is not re-proposed as a brand-new story —
    a settled story is not quietly revived by re-proposal."""
    store = _store(tmp_path)
    thread = store.create_thread(
        USER,
        origin="user_declared",
        title="Settled orchard",
        evidence_refs=[
            SourceRef(kind="event", ref_id="evt-1", evidence_kind="quote"),
            SourceRef(kind="event", ref_id="evt-2", evidence_kind="quote"),
        ],
    )
    store.set_thread_status(USER, thread.id, "resolved")
    calls: list = []
    result = derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
    )
    assert result.calls == 0
    assert result.births == []
    assert any("covered" in s for s in result.skipped)


def test_dismissed_birth_cluster_not_reproposed(tmp_path):
    """Audit S1-5 (second half): a dismissed cluster is not
    re-proposed when the same evidence is re-analyzed."""
    store = _store(tmp_path)
    items = [
        event_to_item(_event("evt-1", FOCUS_TEXT)),
        event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
    ]
    dismiss_proposal(
        store, USER, kind="thread_birth", signature=birth_signature(items)
    )
    calls: list = []
    result = derive_batch(USER, items, store, generate_fn=_counting_gen(BIRTH_JSON, calls))
    assert result.calls == 0
    assert result.births == [] and store.threads_for(USER) == []
    assert any("dismissed" in s for s in result.skipped)


def test_new_evidence_reopens_dismissed_cluster(tmp_path):
    """Dismissal is content-addressed, not a ban: genuinely new
    evidence produces a new signature and may be proposed again."""
    store = _store(tmp_path)
    items = [
        event_to_item(_event("evt-1", FOCUS_TEXT)),
        event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
    ]
    dismiss_proposal(
        store, USER, kind="thread_birth", signature=birth_signature(items)
    )
    wider = items + [event_to_item(_event("evt-3", FOCUS_TEXT + " anew"))]
    calls: list = []
    result = derive_batch(USER, wider, store, generate_fn=_counting_gen(BIRTH_JSON, calls))
    assert result.calls == 1
    assert len(result.births) == 1


def test_dismissal_store_api_round_trip(tmp_path):
    store = _store(tmp_path)
    assert store.is_dismissed(USER, kind="thread_birth", signature="s") is False
    first = store.record_dismissal(USER, kind="thread_birth", signature="s")
    assert store.is_dismissed(USER, kind="thread_birth", signature="s") is True
    again = store.record_dismissal(USER, kind="thread_birth", signature="s")
    assert again.id == first.id  # idempotent re-record
    assert store.is_dismissed(OTHER, kind="thread_birth", signature="s") is False
    assert [d.signature for d in store.dismissals_for(USER)] == ["s"]
    with pytest.raises(ValueError):
        store.record_dismissal(USER, kind="vibe", signature="s")
    with pytest.raises(ValueError):
        store.record_dismissal(USER, kind="thread_birth", signature="  ")


# -- extension path ------------------------------------------------------------


def _seed_thread(store):
    """A live thread whose evidence derivation knows is about
    task:orchard-1 — seeded through the store + the annotation
    derivation itself would have written at attach time."""
    thread = store.create_thread(
        USER,
        origin="user_declared",
        title="The orchard",
        evidence_refs=[SourceRef(kind="event", ref_id="evt-1", evidence_kind="quote")],
    )
    store.annotate_evidence_entities(
        USER, thread.id, {("event", "evt-1"): "task:orchard-1"}
    )
    return thread


def test_extension_proposes_change_then_reading(tmp_path):
    """A new event overlapping a live thread: one generation, a
    proposed change (recorded while the evidence is still new) and
    a proposed reading — both unaccepted (S1-6)."""
    store = _store(tmp_path)
    _seed_thread(store)
    calls: list = []
    result = derive_batch(
        USER,
        [event_to_item(_event("evt-2", FOCUS_TEXT))],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert result.calls == 1
    assert len(result.changes) == 1 and len(result.readings) == 1
    assert result.births == []
    thread = store.threads_for(USER)[0]
    change = store.changes_for(USER, thread.id)[0]
    assert change.kind == "extended" and change.status == "proposed"
    reading = store.readings_for(USER, thread.id, status="proposed")[0]
    assert reading.reading["milestones"] == ["pruned the old row"]
    assert thread.standing_reading_id is None
    assert thread.lens_fitting_id is None


def test_extension_without_change_kind_proposes_reading_only(tmp_path):
    store = _store(tmp_path)
    _seed_thread(store)
    payload = json.dumps(
        {
            "tensions": ["still roots"],
            "open_questions": [],
            "milestones": [],
            "scales": [],
            "primary_scale": None,
            "change_kind": None,
        }
    )
    calls: list = []
    result = derive_batch(
        USER,
        [event_to_item(_event("evt-2", FOCUS_TEXT))],
        store,
        generate_fn=_counting_gen(payload, calls),
    )
    assert result.calls == 1
    assert result.changes == [] and len(result.readings) == 1


def test_extension_with_already_attached_evidence_spends_zero_calls(tmp_path):
    store = _store(tmp_path)
    _seed_thread(store)
    calls: list = []
    result = derive_batch(
        USER,
        [event_to_item(_event("evt-1", FOCUS_TEXT))],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert result.calls == 0
    assert result.readings == [] and result.changes == []


def test_extension_rerun_produces_zero_new_rows(tmp_path):
    store = _store(tmp_path)
    _seed_thread(store)
    gen = _counting_gen(EXTENSION_JSON, [])
    first = derive_batch(
        USER, [event_to_item(_event("evt-2", FOCUS_TEXT))], store, generate_fn=gen
    )
    assert len(first.readings) == 1
    calls: list = []
    second = derive_batch(
        USER,
        [event_to_item(_event("evt-2", FOCUS_TEXT))],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert second.calls == 0
    assert second.readings == [] and second.changes == []


def test_extension_overlapping_two_threads_spends_one_call_each(tmp_path):
    store = _store(tmp_path)
    first = _seed_thread(store)
    second = store.create_thread(
        USER,
        origin="user_declared",
        title="The second orchard",
        evidence_refs=[SourceRef(kind="event", ref_id="evt-1", evidence_kind="quote")],
    )
    store.annotate_evidence_entities(
        USER, second.id, {("event", "evt-1"): "task:orchard-1"}
    )
    assert first.id != second.id
    calls: list = []
    result = derive_batch(
        USER,
        [event_to_item(_event("evt-2", FOCUS_TEXT))],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert result.calls == 2
    assert len(result.readings) == 2


def test_milestone_change_needs_no_lens(tmp_path):
    """Part XI boundary 2, end to end: a milestone is proposed with
    no lens, no fitting, no progression position anywhere."""
    store = _store(tmp_path)
    _seed_thread(store)
    payload = json.dumps(
        {
            "tensions": [],
            "open_questions": [],
            "milestones": ["the orchard gate finished"],
            "scales": [],
            "primary_scale": None,
            "change_kind": "milestone",
        }
    )
    result = derive_batch(
        USER,
        [event_to_item(_event("evt-2", FOCUS_TEXT))],
        store,
        generate_fn=_counting_gen(payload, []),
    )
    assert len(result.changes) == 1
    thread = store.threads_for(USER)[0]
    change = store.changes_for(USER, thread.id)[0]
    assert change.kind == "milestone"
    assert thread.lens_fitting_id is None
    assert store.fittings_for(USER, thread.id) == []


# -- single-event entry point ---------------------------------------------------


def test_analyze_for_threads_extends_but_never_births(tmp_path):
    """Audit Part II §3: one event extends a live thread it overlaps
    and can never birth (birth needs >= 2 items)."""
    store = _store(tmp_path)
    _seed_thread(store)
    calls: list = []
    extended = analyze_for_threads(
        _event("evt-2", FOCUS_TEXT),
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert extended.calls == 1 and len(extended.readings) == 1
    alone = analyze_for_threads(
        _event("evt-9", FOCUS_TEXT),
        store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
    )
    # evt-9 shares the task entity with the live thread, so it also
    # extends (one more call) — it still births nothing.
    assert alone.births == []
    calls.clear()
    unrelated = analyze_for_threads(
        _event("evt-10", NONSENSE_A, entity="task:elsewhere-9"),
        store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
    )
    assert unrelated.calls == 0 and unrelated.births == []


# -- decline discipline ----------------------------------------------------------


def test_generation_decline_leaves_no_rows(tmp_path):
    store = _store(tmp_path)
    items = [
        event_to_item(_event("evt-1", FOCUS_TEXT)),
        event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
    ]
    calls: list = []
    result = derive_batch(
        USER, items, store, generate_fn=_counting_gen("NONE", calls)
    )
    assert result.calls == 1 and result.declines == 1
    assert result.births == [] and store.threads_for(USER) == []


def test_malformed_generation_leaves_no_rows(tmp_path):
    store = _store(tmp_path)
    items = [
        event_to_item(_event("evt-1", FOCUS_TEXT)),
        event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
    ]
    result = derive_batch(
        USER, items, store, generate_fn=_counting_gen("not json {{{", [])
    )
    assert result.declines == 1 and store.threads_for(USER) == []


def test_primary_scale_outside_scales_declines_without_stranding(tmp_path):
    """A primary scale outside scales is refused BEFORE any write,
    so no birth thread is stranded without its reading."""
    store = _store(tmp_path)
    items = [
        event_to_item(_event("evt-1", FOCUS_TEXT)),
        event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
    ]
    payload = json.dumps(
        {
            "title": "Bad scales",
            "tensions": [],
            "open_questions": [],
            "milestones": [],
            "scales": ["personal"],
            "primary_scale": "mythological",
        }
    )
    result = derive_batch(
        USER, items, store, generate_fn=_counting_gen(payload, [])
    )
    assert result.declines == 1
    assert store.threads_for(USER) == []


# -- tier inadmissibility through the derivation path ----------------------------


def test_dramatization_ref_never_becomes_derivation_evidence(tmp_path):
    """The prefilter refuses non-evidence tiers before any
    generation is spent; the store would refuse them anyway."""
    store = _store(tmp_path)
    items = [
        EvidenceItem(
            ref=SourceRef(kind="story_artifact", ref_id="story-1"),
            text=FOCUS_TEXT,
        ),
        EvidenceItem(
            ref=SourceRef(kind="story_artifact", ref_id="story-2"),
            text=FOCUS_TEXT + " again",
        ),
    ]
    calls: list = []
    result = derive_batch(USER, items, store, generate_fn=_counting_gen(BIRTH_JSON, calls))
    assert result.calls == 0
    assert result.births == [] and store.threads_for(USER) == []
    assert any("non-evidence-tier" in s for s in result.skipped)


def test_journal_entry_and_claim_adapters_produce_evidence_items(tmp_path):
    from types import SimpleNamespace

    from local_ai.narrative.derivation import claim_to_item

    claim = SimpleNamespace(
        id="agent-1:strand:self:m3", evidence="I kept the orchard",
        title="kept the orchard",
    )
    claim_item = claim_to_item(claim)
    assert claim_item.ref.kind == "claim"
    assert claim_item.ref.ref_id == "agent-1:strand:self:m3"
    assert claim_item.ref.evidence_kind == "quote"
    assert claim_item.text == "I kept the orchard"
    store = _store(tmp_path)
    items = [
        entry_to_item("entry-1", FOCUS_TEXT),
        entry_to_item("entry-2", FOCUS_TEXT + " again"),
    ]
    assert all(item.ref.kind == "journal_entry" for item in items)
    assert all(item.ref.evidence_kind == "quote" for item in items)
    result = derive_batch(
        USER, items, store, generate_fn=_counting_gen(BIRTH_JSON, [])
    )
    assert len(result.births) == 1
    thread = store.get_thread(USER, result.births[0])
    assert {row.ref_kind for row in store.evidence_for(USER, thread.id)} == {
        "journal_entry"
    }


# -- separation pins: no links, no turn path, no training ------------------------


def test_derivation_walks_no_links_and_touches_no_turn_path():
    """Part XI boundary 1, pinned mechanically: derivation.py never
    names the containment-link reads, never imports a conversation
    path or a training-signal writer; and no turn-path module
    imports the narrative package at all."""
    package_dir = Path(__file__).resolve().parent.parent / "local_ai" / "narrative"
    source = (package_dir / "derivation.py").read_text(encoding="utf-8")
    for forbidden in ("links_for", "links_as_parent", "links_as_child", "thread_links"):
        assert forbidden not in source
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    banned_prefixes = (
        "local_ai.conversation",
        "local_ai.llm",
        "local_ai.providers",
    )
    offenders = [name for name in imported if name.startswith(banned_prefixes)]
    assert offenders == []
    assert not any("signal" in name for name in imported)
    repo = package_dir.parent.parent
    for turn_path in (
        "local_ai/conversation/reply.py",
        "local_ai/conversation/service.py",
        "local_ai/conversation/encounter.py",
        "local_ai/conversation/meeting.py",
    ):
        assert "local_ai.narrative" not in (repo / turn_path).read_text(
            encoding="utf-8"
        )


def test_chat_turn_counts_unchanged_with_derivation_loaded(
    tmp_path, monkeypatch
):
    """Two-speed law, measured: with the derivation module loaded
    in-process, skeleton chat turns still spend exactly the audited
    counts (1/turn; 2 on the summary-refresh turn) and never spend
    a narrative-derivation call."""
    import local_ai.narrative.derivation  # noqa: F401 — loaded on purpose

    import local_ai.conversation.service as service_mod
    from local_ai.conversation.service import ConversationService
    from local_ai.conversation.store import ConversationStore

    calls: list = []

    def counting(prompt: str, **kwargs) -> str:
        calls.append((prompt, kwargs))
        if "ongoing one-on-one thread" in prompt:
            return "Rolling summary."
        return "Fake reply."

    store = ConversationStore(db_path=tmp_path / "conv.db")
    monkeypatch.setattr(service_mod, "SUMMARY_EVERY_N_TURNS", 2)
    svc = ConversationService(store, generate_fn=counting)
    svc.turn("u1", "mentor", "one")
    assert len(calls) == 1
    svc.turn("u1", "mentor", "two")
    assert len(calls) == 3  # turn 2: reply + summary refresh
    assert not any(
        kwargs.get("operation") == "narrative-derivation"
        for _, kwargs in calls
    )
    store.close()


# -- pipeline: defined, synchronous when asked, not installed ---------------------


def test_pipeline_runs_batch_synchronously_when_scheduled_so(tmp_path):
    store = _store(tmp_path)
    calls: list = []
    pipeline = StewardPipeline(
        store=store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
        scheduler=lambda fn: fn(),
    )
    pipeline.schedule_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
    )
    assert len(calls) == 1
    assert len(store.threads_for(USER)) == 1
