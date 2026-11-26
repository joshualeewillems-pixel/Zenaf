"""Review verdicts -> derivation dismissal memory (the later-phase
wiring, 2026-11-25).

The gap these tests close: ``review.apply_verdict`` never wrote
dismissal memory, so a rejected steward proposal's evidence could
be re-proposed as an equivalent birth/extension when derivation
re-analyzed it after the proposal's own rows were gone (the
terminal status stops the PROPOSAL returning; it says nothing to
derivation). The founder's standard (2026-11-25): durable
rejection prevents repetition on UNCHANGED grounds — new
evidence, changed circumstances, and explicit visitor initiation
remain unbarred.

Pins:

- A rejected birth writes a ``thread_birth`` dismissal over the
  founding evidence fingerprint (derivation's own signature).
- A rejected change writes an ``extension`` dismissal over
  exactly the evidence the change cites.
- After the rejected proposal's rows are gone, re-analysis of the
  same evidence is suppressed BY THE DISMISSAL (zero generation
  calls, the dismissal skip reason), not merely by coverage.
- Genuinely new evidence after a rejection is NOT barred: a new
  signature is proposed normally.
- Non-rejection verdicts (accepted / unresolved) write no
  dismissal, and neither do rejections of kinds that have no
  dismissal kind in DISMISSAL_KINDS (a reading, here) — that
  coverage question is deliberately not settled by this wiring.

All generations are fake/counting. Stores are tmp SQLite files.
"""

from __future__ import annotations

import json

from local_ai.fellowship.events import FellowshipEvent
from local_ai.narrative import NarrativeStore, SourceRef
from local_ai.narrative.derivation import (
    birth_signature,
    derive_batch,
    event_to_item,
    extension_signature,
)
from local_ai.narrative.review import apply_verdict, pending_review_items

USER = "user-1"

#: Focus-anchored wording: "cultivation" is a Gardener focus term,
#: so clusters using it clear the jurisdiction gate (as in the S1
#: suite this fixture mirrors).
FOCUS_TEXT = "cultivation in the orchard, learning what ripens"

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


def _birth_items():
    return [
        event_to_item(_event("evt-1", FOCUS_TEXT)),
        event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
    ]


def _derive_birth(store, gen_payload=BIRTH_JSON):
    items = _birth_items()
    calls: list = []
    result = derive_batch(
        USER, items, store, generate_fn=_counting_gen(gen_payload, calls)
    )
    assert len(result.births) == 1
    return items, result.births[0]


def _pending(store, kind):
    return [i for i in pending_review_items(store, USER) if i.item_kind == kind]


def _seed_thread(store):
    """A live thread whose evidence derivation knows is about
    task:orchard-1 (mirrors the S1 suite's seed)."""
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


# -- Gate 1: a rejected proposal writes dismissal memory -----------------------


def test_rejected_birth_writes_dismissal_memory(tmp_path):
    store = _store(tmp_path)
    items, thread_id = _derive_birth(store)
    assert store.dismissals_for(USER) == []

    result = apply_verdict(store, USER, f"birth:{thread_id}", "rejected")

    assert result.status == "archived"
    rows = store.dismissals_for(USER)
    assert len(rows) == 1
    assert rows[0].kind == "thread_birth"
    assert rows[0].signature == birth_signature(items)
    assert store.is_dismissed(
        USER, kind="thread_birth", signature=birth_signature(items)
    )


def test_rejected_change_writes_extension_dismissal(tmp_path):
    store = _store(tmp_path)
    thread = _seed_thread(store)
    item = event_to_item(_event("evt-2", FOCUS_TEXT))
    calls: list = []
    result = derive_batch(
        USER, [item], store, generate_fn=_counting_gen(EXTENSION_JSON, calls)
    )
    assert len(result.changes) == 1
    change_id = result.changes[0]
    assert store.dismissals_for(USER) == []

    verdict = apply_verdict(store, USER, f"change:{change_id}", "rejected")

    assert verdict.status == "dismissed"
    rows = store.dismissals_for(USER)
    assert len(rows) == 1
    assert rows[0].kind == "extension"
    assert rows[0].signature == extension_signature(thread.id, [item])
    assert store.is_dismissed(
        USER,
        kind="extension",
        signature=extension_signature(thread.id, [item]),
    )


def test_records_first_birth_rejection_writes_the_stored_signature(tmp_path):
    """Records-first births store derivation's exact fingerprint
    on the deferred-prose row; the rejection's dismissal must be
    that signature, not a reconstruction."""
    store = _store(tmp_path)
    items = _birth_items()
    result = derive_batch(USER, items, store, generate_fn=None)
    assert len(result.births) == 1
    thread_id = result.births[0]
    deferred = [
        row
        for row in store.deferred_prose_for_thread(USER, thread_id)
        if row.get("kind") == "birth"
    ]
    assert len(deferred) == 1
    stored_signature = deferred[0]["evidence_signature"]
    assert stored_signature == birth_signature(items)

    apply_verdict(store, USER, f"birth:{thread_id}", "rejected")

    rows = store.dismissals_for(USER)
    assert len(rows) == 1
    assert rows[0].kind == "thread_birth"
    assert rows[0].signature == stored_signature


# -- Gate 2: derivation does not re-propose on the same evidence ---------------


def test_rejected_birth_not_reproposed_after_thread_deleted(tmp_path):
    """The dismissal — not coverage — is the operative guard once
    the rejected proposal's rows are gone: delete the archived
    thread (its evidence cascades with it; dismissal rows are
    user-keyed and survive), then re-analyze the same evidence.
    Derivation must spend zero calls and skip on the dismissal."""
    store = _store(tmp_path)
    items, thread_id = _derive_birth(store)
    apply_verdict(store, USER, f"birth:{thread_id}", "rejected")
    assert store.delete_thread(USER, thread_id) is True
    assert store.threads_for(USER) == []
    assert len(store.dismissals_for(USER)) == 1  # survived deletion

    calls: list = []
    result = derive_batch(
        USER, items, store, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert result.calls == 0
    assert result.births == []
    assert store.threads_for(USER) == []
    assert any("birth dismissed" in s for s in result.skipped)


def test_rejected_change_not_reproposed_when_evidence_detaches(tmp_path):
    """Extension form of the same gate. While the rejected
    change's evidence stays attached, re-analysis is idempotent
    for the ordinary reason (nothing is new). The dismissal is
    what guards the state where the evidence row is gone but the
    thread survives — e.g. source erasure removing the derived
    row. Simulate that state by removing the one evidence row,
    then re-analyze: the extension must be skipped on the
    dismissal, with zero generation calls."""
    store = _store(tmp_path)
    thread = _seed_thread(store)
    item = event_to_item(_event("evt-2", FOCUS_TEXT))
    calls: list = []
    result = derive_batch(
        USER, [item], store, generate_fn=_counting_gen(EXTENSION_JSON, calls)
    )
    assert len(result.changes) == 1
    apply_verdict(store, USER, f"change:{result.changes[0]}", "rejected")
    assert len(store.dismissals_for(USER)) == 1

    # Simulate source erasure: the evt-2 evidence row is removed
    # while the thread (and the dismissal) survive.
    with store._lock:
        store._conn.execute(
            "DELETE FROM thread_evidence WHERE thread_id = ? "
            "AND ref_kind = 'event' AND ref_id = 'evt-2'",
            (thread.id,),
        )
        store._conn.commit()
    assert {
        f"{r.ref_kind}:{r.ref_id}" for r in store.evidence_for(USER, thread.id)
    } == {"event:evt-1"}

    calls = []
    result = derive_batch(
        USER, [item], store, generate_fn=_counting_gen(EXTENSION_JSON, calls)
    )
    assert result.calls == 0
    assert result.changes == [] and result.readings == []
    assert any("extension dismissed" in s for s in result.skipped)


# -- Gate 3: genuinely new evidence is NOT barred -------------------------------


def test_new_evidence_after_rejected_birth_is_proposed(tmp_path):
    """Dismissal is evidence-keyed, not a ban: the same evidence
    plus genuinely new evidence forms a new signature and may be
    proposed again."""
    store = _store(tmp_path)
    items, thread_id = _derive_birth(store)
    apply_verdict(store, USER, f"birth:{thread_id}", "rejected")
    assert len(store.dismissals_for(USER)) == 1

    wider = items + [event_to_item(_event("evt-3", FOCUS_TEXT + " anew"))]
    calls: list = []
    result = derive_batch(
        USER, wider, store, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert result.calls == 1
    assert len(result.births) == 1


def test_new_evidence_after_rejected_change_is_proposed(tmp_path):
    store = _store(tmp_path)
    thread = _seed_thread(store)
    item = event_to_item(_event("evt-2", FOCUS_TEXT))
    result = derive_batch(
        USER,
        [item],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, []),
    )
    assert len(result.changes) == 1
    apply_verdict(store, USER, f"change:{result.changes[0]}", "rejected")

    fresh = event_to_item(_event("evt-3", FOCUS_TEXT + " anew"))
    calls: list = []
    result = derive_batch(
        USER, [fresh], store, generate_fn=_counting_gen(EXTENSION_JSON, calls)
    )
    assert result.calls == 1
    assert len(result.changes) == 1 and len(result.readings) == 1


# -- Gate 4: non-rejection verdicts write no dismissal --------------------------


def test_accepted_and_unresolved_verdicts_write_no_dismissal(tmp_path):
    store = _store(tmp_path)
    _, thread_id = _derive_birth(store)
    apply_verdict(store, USER, f"birth:{thread_id}", "unresolved")
    assert store.dismissals_for(USER) == []
    apply_verdict(store, USER, f"birth:{thread_id}", "accepted")
    assert store.dismissals_for(USER) == []


def test_accepted_change_writes_no_dismissal(tmp_path):
    store = _store(tmp_path)
    _seed_thread(store)
    item = event_to_item(_event("evt-2", FOCUS_TEXT))
    result = derive_batch(
        USER,
        [item],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, []),
    )
    assert len(result.changes) == 1
    apply_verdict(store, USER, f"change:{result.changes[0]}", "accepted")
    assert store.dismissals_for(USER) == []


def test_rejected_reading_writes_no_dismissal(tmp_path):
    """Readings have no dismissal kind in DISMISSAL_KINDS; a
    rejected reading writes nothing. This pins the boundary the
    wiring deliberately does not cross — the coverage question
    for readings belongs to a separate decision."""
    store = _store(tmp_path)
    thread = _seed_thread(store)
    item = event_to_item(_event("evt-2", FOCUS_TEXT))
    result = derive_batch(
        USER,
        [item],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, []),
    )
    assert len(result.readings) == 1
    readings = _pending(store, "reading")
    assert len(readings) == 1

    apply_verdict(store, USER, readings[0].item_id, "rejected")

    assert store.dismissals_for(USER) == []
    # The change from the same extension proposal is untouched by
    # the reading's rejection and remains pending.
    assert len(_pending(store, "change")) == 1
    _ = thread
