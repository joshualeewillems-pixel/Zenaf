"""Steward increment B — decline records for offers (proposal §10).

Covers the proposal's acceptance tests for increment B only:
semantic offer identities (invitation / subject / class) with
exact-equality matching, scoped refusal, the ambiguity contract,
consultation before proposing (derive_batch birth + extension
paths, deferred worker, post-generation class check), the two
dismissal regimes kept distinct, prune exemption, per-user
scoping, gate interaction, the deletion distinction + warn-first
preview content, and class-as-offer-boundary (no processing-ban
claim). Storage + consultation only: no surfacing, no dialogue
change, no UI. All generations are fake/counting/raising. Stores
are tmp SQLite files. No production writer exists for declines
yet (E/H own the first writers); tests call the record/clear
functions directly and say so (test 15).
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from local_ai.narrative import NarrativeStore
from local_ai.narrative.derivation import (
    EvidenceItem,
    StewardPipeline,
    birth_signature,
    class_key,
    clear_offer_decline,
    derive_batch,
    dismiss_proposal,
    extension_signature,
    invitation_key,
    is_offer_declined,
    record_offer_decline,
    subject_key_for_cluster,
    subject_key_for_thread,
    work_deferred_prose,
)
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.sweep import prune_ignored_threads

USER = "user-1"
OTHER = "user-2"
FOCUS_TEXT = "cultivation in the orchard, learning what ripens"
BOSS = "person:boss"
OTHER_ENTITY = "person:gardener"

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
        "title": "The orchard years, revisited",
        "tensions": ["roots vs. road, revisited"],
        "open_questions": ["what endures now?"],
        "milestones": ["pruned the old row"],
        "scales": ["personal"],
        "primary_scale": "personal",
        "change_kind": "extended",
    }
)

REOPENED_JSON = json.dumps(
    {
        "title": "The orchard years, reopened",
        "tensions": ["roots vs. road, reopened"],
        "open_questions": ["what endures now?"],
        "milestones": ["walked the old row again"],
        "scales": ["personal"],
        "primary_scale": "personal",
        "change_kind": "reopened",
    }
)


def _store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _item(ref_id, text, entity=None):
    return EvidenceItem(
        ref=SourceRef(kind="event", ref_id=ref_id, evidence_kind="quote"),
        text=text,
        entity_ref=entity,
    )


def _pair(tag, entity, text=FOCUS_TEXT):
    """Two items that cluster (shared entity, or shared tokens
    when entity is None) — a birth candidate."""
    return [
        _item(f"evt-{tag}-1", text, entity),
        _item(f"evt-{tag}-2", text + " again", entity),
    ]


def _counting_gen(payload, calls):
    def gen(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return payload

    return gen


def _raising_gen(prompt, **kwargs):
    raise RuntimeError("backend down")


def _threads(store, user):
    return store.threads_for(user)


def _readings(store, user, thread_id):
    return store.readings_for(user, thread_id)


def _changes(store, user, thread_id):
    return store.changes_for(user, thread_id)


def _deferred(store, user, status=None):
    return store.deferred_prose_for(user, status=status)


def _birth(store, user, tag, entity, gen_payload=BIRTH_JSON):
    """Derive one birth; returns the thread (asserts it landed)."""
    calls: list = []
    result = derive_batch(
        user,
        _pair(tag, entity),
        store,
        generate_fn=_counting_gen(gen_payload, calls),
    )
    assert result.calls == 1, result.skipped
    assert len(result.births) == 1
    return store.get_thread(user, result.births[0])


# ---------------------------------------------------------------------------
# §10.12 key-grammar pins + §10.13 record/clear semantics
# ---------------------------------------------------------------------------


def test_key_grammars_and_precision_order(tmp_path):
    """§10.12: invitation/subject/class key construction, entity
    tie-break determinism, entity-beats-scope order, precision
    tags, and the ambiguity matrix at the function level."""
    # Invitation grammar: inv:<thread|birth>:<kind>:<slot>:<keys>.
    assert invitation_key("birth", "birth", "birth", ["b:2", "a:1"]) == (
        "inv:birth:birth:birth:a:1|b:2"
    )
    assert invitation_key("t1", "extension", "reading", ["x:1"]) == (
        "inv:t1:extension:reading:x:1"
    )
    assert class_key("extension:reopened") == "class:extension:reopened"

    store = _store(tmp_path)
    # Subject from a cluster: dominant entity, ties lexicographic.
    cluster_items = _pair("g", BOSS)
    # A true 1-1 tie: one BOSS item, one apple item — the
    # lexicographically first entity wins, deterministically.
    tied = [
        _item("evt-g-1", FOCUS_TEXT, BOSS),
        _item("evt-g-3", FOCUS_TEXT, "person:apple"),
    ]
    from local_ai.narrative.derivation import Cluster

    key, prec = subject_key_for_cluster(Cluster(items=tied))
    assert (key, prec) == ("person:apple", "precise")
    key, prec = subject_key_for_cluster(Cluster(items=cluster_items))
    assert (key, prec) == (BOSS, "precise")
    key, prec = subject_key_for_cluster(
        Cluster(items=_pair("h", None))
    )
    assert (key, prec) == (None, "unknown")

    # Subject from a thread: entity beats scope; scope is coarse;
    # neither is unknown. Threads built directly (no derivation)
    # so their evidence carries no entity annotations.
    scoped = store.create_thread(
        USER, origin="user_declared", title="work notes", scope="work"
    )
    key, prec = subject_key_for_thread(store, USER, scoped)
    assert (key, prec) == ("work", "coarse")
    bare = store.create_thread(USER, origin="user_declared", title="bare")
    key, prec = subject_key_for_thread(store, USER, bare)
    assert (key, prec) == (None, "unknown")
    # Entity beats scope: a derived birth annotates its evidence,
    # so its thread's subject is the precise entity even when a
    # scope label is also present on the thread object.
    born = _birth(store, USER, "e", BOSS)
    key, prec = subject_key_for_thread(store, USER, born)
    assert (key, prec) == (BOSS, "precise")

    # Ambiguity matrix at the function level.
    record_offer_decline(store, USER, scope="subject", key=BOSS)
    # Precise mismatch proceeds.
    assert (
        is_offer_declined(
            store, USER, subject_key="person:other",
            subject_precision="precise",
        )
        is None
    )
    # Unknown + declines standing -> ambiguous.
    assert (
        is_offer_declined(
            store, USER, subject_key=None, subject_precision="unknown"
        )
        == "ambiguous"
    )
    # Unknown + NO declines standing -> proceeds.
    assert (
        is_offer_declined(
            store, OTHER, subject_key=None, subject_precision="unknown"
        )
        is None
    )
    # Coarse key literally equal to a declined coarse label ->
    # MATCHED (the visitor declined that broad label itself).
    record_offer_decline(store, OTHER, scope="subject", key="work")
    assert (
        is_offer_declined(
            store, OTHER, subject_key="work", subject_precision="coarse"
        )
        == "subject"
    )
    # Coarse non-equal + declines standing -> ambiguous.
    assert (
        is_offer_declined(
            store, USER, subject_key="work", subject_precision="coarse"
        )
        == "ambiguous"
    )
    # No subject key AND no precision skips the subject check
    # (invitation/class still evaluated: class match wins here).
    record_offer_decline(store, OTHER, scope="class", key="birth")
    assert (
        is_offer_declined(store, OTHER, class_label="birth") == "class"
    )
    assert is_offer_declined(store, OTHER) is None


def test_record_clear_idempotent_and_scoped(tmp_path):
    """§10.13: re-declining returns the existing row; clearing a
    nonexistent decline returns False and changes nothing;
    clearing deletes exactly one row."""
    store = _store(tmp_path)
    first = record_offer_decline(store, USER, scope="subject", key=BOSS)
    again = record_offer_decline(store, USER, scope="subject", key=BOSS)
    assert again.id == first.id
    assert len(store.dismissals_for(USER)) == 1
    assert (
        clear_offer_decline(store, USER, scope="subject", key="person:nope")
        is False
    )
    assert len(store.dismissals_for(USER)) == 1
    record_offer_decline(store, USER, scope="subject", key="person:other")
    assert len(store.dismissals_for(USER)) == 2
    assert (
        clear_offer_decline(store, USER, scope="subject", key=BOSS)
        is True
    )
    remaining = [d.signature for d in store.dismissals_for(USER)]
    assert remaining == ["subj:person:other"]
    with pytest.raises(ValueError):
        record_offer_decline(store, USER, scope="mood", key="x")
    with pytest.raises(ValueError):
        record_offer_decline(store, USER, scope="subject", key="  ")
    with pytest.raises(ValueError):
        record_offer_decline(store, USER, scope="class", key="nope")
    with pytest.raises(ValueError):
        record_offer_decline(store, USER, scope="invitation", key="no-prefix")


# ---------------------------------------------------------------------------
# §10.1–10.4 derive_batch behavior
# ---------------------------------------------------------------------------


def test_declined_invitation_never_reproposed(tmp_path):
    """§10.1: a declined offer is never re-proposed on re-analysis
    of the same evidence (invitation scope; 0 generations; the
    skip reason names the decline)."""
    store = _store(tmp_path)
    items = _pair("a", BOSS)
    keys = sorted(i.evidence_key() for i in items)
    record_offer_decline(
        store, USER, scope="invitation",
        key=invitation_key("birth", "birth", "birth", keys),
    )
    calls: list = []
    result = derive_batch(
        USER, items, store, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert calls == []
    assert result.births == [] and _threads(store, USER) == []
    assert any("offer declined (invitation)" in s for s in result.skipped)


def test_new_evidence_never_reopens_subject(tmp_path):
    """§10.2: new evidence about a declined subject does NOT reopen
    the offer — birth path (no thread yet) and extension path
    (live thread, new evidence) alike, 0 generations each."""
    store = _store(tmp_path)
    # Birth path: decline first, then a birth cluster on the subject.
    record_offer_decline(store, USER, scope="subject", key=BOSS)
    calls: list = []
    result = derive_batch(
        USER, _pair("b", BOSS), store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
    )
    assert calls == [] and result.births == []
    assert any("offer declined (subject)" in s for s in result.skipped)
    # Extension path: clear, birth the thread, decline again, then
    # new evidence on the same subject.
    assert clear_offer_decline(store, USER, scope="subject", key=BOSS)
    thread = _birth(store, USER, "c", BOSS)
    record_offer_decline(store, USER, scope="subject", key=BOSS)
    calls.clear()
    result = derive_batch(
        USER,
        [
            _item("evt-d-1", FOCUS_TEXT + " once more", BOSS),
            _item("evt-d-2", FOCUS_TEXT + " once more again", BOSS),
        ],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert calls == []
    assert len(_readings(store, USER, thread.id)) == 1


def test_rewording_never_evades_invitation(tmp_path):
    """§10.3: rewording the same offer does not evade the decline
    (same evidence, a generation that would return different prose
    — still blocked, because consultation precedes generation and
    identity is evidence-keyed, not prose-keyed)."""
    store = _store(tmp_path)
    items = _pair("w", BOSS)
    keys = sorted(i.evidence_key() for i in items)
    record_offer_decline(
        store, USER, scope="invitation",
        key=invitation_key("birth", "birth", "birth", keys),
    )
    calls: list = []
    other_prose = BIRTH_JSON.replace("orchard years", "garden seasons")
    result = derive_batch(
        USER, items, store, generate_fn=_counting_gen(other_prose, calls)
    )
    assert calls == []
    assert result.births == [] and _threads(store, USER) == []


def _scoped_thread(store, user, tag, scope):
    """A directly-created thread with a scope label and one
    unannotated evidence row — the coarse/unknown subject setup.
    Its evidence carries no entity_refs, so its subject key is
    the scope (coarse) or unknown (no scope)."""
    base = _item(f"evt-{tag}-base", FOCUS_TEXT)
    thread = store.create_thread(
        user, origin="user_declared", title=f"thread {tag}",
        scope=scope, evidence_refs=[base.ref],
    )
    return thread, base


def _extension_batch(tag):
    """A cluster overlapping a directly-created thread: the base
    ref (already attached) plus one new ref, sharing tokens."""
    return [
        _item(f"evt-{tag}-base", FOCUS_TEXT),
        _item(f"evt-{tag}-new", FOCUS_TEXT + " more"),
    ]


def test_subject_blocks_all_invitation_blocks_one(tmp_path):
    """§10.4: a subject-scope decline blocks all offers in that
    subject (two threads sharing the coarse subject key), while a
    specific-invitation decline blocks only that invitation (the
    other thread's offer still proposes)."""
    store = _store(tmp_path)
    thread_a, _ = _scoped_thread(store, USER, "a", "work")
    thread_b, _ = _scoped_thread(store, USER, "b", "work")
    # Subject half: one decline blocks both threads' extensions.
    record_offer_decline(store, USER, scope="subject", key="work")
    calls: list = []
    for tag in ("a", "b"):
        result = derive_batch(
            USER, _extension_batch(tag), store,
            generate_fn=_counting_gen(EXTENSION_JSON, calls),
        )
        assert any("offer declined (subject)" in s for s in result.skipped)
    assert calls == []
    assert _readings(store, USER, thread_a.id) == []
    assert _readings(store, USER, thread_b.id) == []
    # Invitation half: clear the subject, decline only A's
    # extension invitation; B's extension still proposes.
    assert clear_offer_decline(store, USER, scope="subject", key="work")
    record_offer_decline(
        store, USER, scope="invitation",
        key=invitation_key(
            thread_a.id, "extension", "reading", ["event:evt-a-new"]
        ),
    )
    calls.clear()
    result = derive_batch(
        USER, _extension_batch("a"), store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert any("offer declined (invitation)" in s for s in result.skipped)
    assert _readings(store, USER, thread_a.id) == []
    result = derive_batch(
        USER, _extension_batch("b"), store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert len(calls) == 1
    assert len(_readings(store, USER, thread_b.id)) == 1


def test_dismissal_never_deletes(tmp_path):
    """§10.5: a dismissal never deletes the thread, reading, or
    change it dismissed (all three rows unchanged, same ids)."""
    store = _store(tmp_path)
    thread = _birth(store, USER, "d", BOSS)
    calls: list = []
    derive_batch(
        USER,
        [
            _item("evt-e-1", FOCUS_TEXT + " once more", BOSS),
            _item("evt-e-2", FOCUS_TEXT + " once more again", BOSS),
        ],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert len(calls) == 1
    readings_before = [r.id for r in _readings(store, USER, thread.id)]
    changes_before = [c.id for c in _changes(store, USER, thread.id)]
    assert len(readings_before) == 2 and len(changes_before) == 1
    record_offer_decline(store, USER, scope="subject", key=BOSS)
    record_offer_decline(store, USER, scope="class", key="birth")
    dismiss_proposal(
        store, USER, kind="thread_birth",
        signature=birth_signature(_pair("d", BOSS)),
    )
    assert store.get_thread(USER, thread.id) is not None
    assert [r.id for r in _readings(store, USER, thread.id)] == readings_before
    assert [c.id for c in _changes(store, USER, thread.id)] == changes_before


def test_reopening_scoped_and_initiative_without_clear(tmp_path):
    """§10.6: clearing a decline clears that offer/scope only
    (others still block); and derivation re-analysis never
    clears anything — initiative-without-clear at B's level:
    nothing in derivation removes a decline row, so a stored
    refusal stands across re-analysis until an explicit lift.
    (Discussion recognition itself is H's work; B provides no
    discussion-clearing path, and this test pins that no
    derivation call clears.)"""
    store = _store(tmp_path)
    thread = _birth(store, USER, "r", BOSS)
    ext_items = [
        _item("evt-rn-1", FOCUS_TEXT + " once more", BOSS),
        _item("evt-rn-2", FOCUS_TEXT + " once more again", BOSS),
    ]
    ext_keys = sorted(i.evidence_key() for i in ext_items)
    record_offer_decline(store, USER, scope="subject", key=BOSS)
    record_offer_decline(
        store, USER, scope="invitation",
        key=invitation_key(thread.id, "extension", "reading", ext_keys),
    )
    record_offer_decline(store, USER, scope="class", key="extension:reading")
    calls: list = []
    gen = _counting_gen(EXTENSION_JSON, calls)
    # Clear invitation -> subject still blocks.
    assert clear_offer_decline(
        store, USER, scope="invitation",
        key=invitation_key(thread.id, "extension", "reading", ext_keys),
    )
    result = derive_batch(USER, ext_items, store, generate_fn=gen)
    assert calls == []
    assert any("offer declined (subject)" in s for s in result.skipped)
    # Clear subject -> class still blocks.
    assert clear_offer_decline(store, USER, scope="subject", key=BOSS)
    result = derive_batch(USER, ext_items, store, generate_fn=gen)
    assert calls == []
    assert any("offer declined (class)" in s for s in result.skipped)
    # Clear class -> proposes.
    assert clear_offer_decline(
        store, USER, scope="class", key="extension:reading"
    )
    result = derive_batch(USER, ext_items, store, generate_fn=gen)
    assert len(calls) == 1
    # Initiative-without-clear: re-decline the subject, then
    # analyze NEW evidence on the topic repeatedly — the row
    # stands, the offer stays blocked, and no derivation call
    # removed anything. (The earlier extension evidence is
    # attached by now, so fresh refs are needed for a live
    # extension path at all.)
    record_offer_decline(store, USER, scope="subject", key=BOSS)
    new_items = [
        _item("evt-rn-3", FOCUS_TEXT + " a third time", BOSS),
        _item("evt-rn-4", FOCUS_TEXT + " a third time again", BOSS),
    ]
    for _ in range(2):
        result = derive_batch(USER, new_items, store, generate_fn=gen)
        assert len(calls) == 1
        assert any("offer declined (subject)" in s for s in result.skipped)
    assert [d.signature for d in store.dismissals_for(USER)] == [
        "subj:" + BOSS
    ]
    # Only an explicit lift clears it.
    assert clear_offer_decline(store, USER, scope="subject", key=BOSS)
    assert store.dismissals_for(USER) == []


def test_two_regimes_distinct(tmp_path):
    """§10.7: the SAME new evidence that reopens a thread-candidate
    dismissal (S1 behavior: new signature -> proposed) does NOT
    reopen an offer decline at subject scope (blocked)."""
    # Candidate regime: dismissed cluster, wider evidence proposes.
    store_c = _store(tmp_path / "c")
    items = _pair("x", BOSS)
    dismiss_proposal(
        store_c, USER, kind="thread_birth",
        signature=birth_signature(items),
    )
    wider = items + [_item("evt-x-3", FOCUS_TEXT + " anew", BOSS)]
    calls: list = []
    result = derive_batch(
        USER, wider, store_c, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert len(calls) == 1 and len(result.births) == 1
    # Offer regime: same wider evidence, subject declined -> blocked.
    store_o = _store(tmp_path / "o")
    record_offer_decline(store_o, USER, scope="subject", key=BOSS)
    calls.clear()
    result = derive_batch(
        USER, wider, store_o, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert calls == [] and result.births == []
    assert any("offer declined (subject)" in s for s in result.skipped)


def test_class_scope_and_post_generation_check(tmp_path):
    """§10.11: a class decline blocks all offers of that class
    across subjects; clearing it re-enables them. A kind-level
    class blocks pre-generation; a change-kind class is caught by
    the post-generation check (discarded, generation spent)."""
    store = _store(tmp_path)
    record_offer_decline(store, USER, scope="class", key="birth")
    calls: list = []
    gen = _counting_gen(BIRTH_JSON, calls)
    for tag, entity in (("cb", BOSS), ("cg", OTHER_ENTITY)):
        result = derive_batch(
            USER, _pair(tag, entity), store, generate_fn=gen
        )
        assert any("offer declined (class)" in s for s in result.skipped)
    assert calls == [] and _threads(store, USER) == []
    assert clear_offer_decline(store, USER, scope="class", key="birth")
    thread = _birth(store, USER, "cb", BOSS)
    # Kind-level class blocks the extension pre-generation.
    record_offer_decline(store, USER, scope="class", key="extension:reading")
    calls.clear()
    result = derive_batch(
        USER,
        [
            _item("evt-k-1", FOCUS_TEXT + " once more", BOSS),
            _item("evt-k-2", FOCUS_TEXT + " once more again", BOSS),
        ],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert calls == []
    assert len(_readings(store, USER, thread.id)) == 1
    assert clear_offer_decline(
        store, USER, scope="class", key="extension:reading"
    )
    # Change-kind class: caught post-generation, discarded whole.
    record_offer_decline(
        store, USER, scope="class", key="extension:reopened"
    )
    calls.clear()
    result = derive_batch(
        USER,
        [
            _item("evt-k-3", FOCUS_TEXT + " a third time", BOSS),
            _item("evt-k-4", FOCUS_TEXT + " a third time again", BOSS),
        ],
        store,
        generate_fn=_counting_gen(REOPENED_JSON, calls),
    )
    assert len(calls) == 1  # generation spent, proposal discarded
    assert len(_readings(store, USER, thread.id)) == 1
    assert _changes(store, USER, thread.id) == []
    assert any("offer declined (class)" in s for s in result.skipped)
    n_changes = 0
    # Negative control: an extended change under the same
    # reopened-decline stores normally.
    result = derive_batch(
        USER,
        [
            _item("evt-k-5", FOCUS_TEXT + " a fourth time", BOSS),
            _item("evt-k-6", FOCUS_TEXT + " a fourth time again", BOSS),
        ],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert len(_changes(store, USER, thread.id)) == n_changes + 1
    assert len(_readings(store, USER, thread.id)) == 2


def test_ambiguity_contract_derive_level(tmp_path):
    """§10.16: an unknown-subject offer with a subject decline
    standing is WITHHELD (skip reason, 0 generations, no rows) —
    not allowed through and not recorded as a match. A coarsely
    keyed offer against a precise decline is likewise withheld.
    The consultation API returns "ambiguous" distinctly, is a
    pure query (no rows created by calling it), and visitor
    discussion is never routed through consultation: no B path
    consults for what the visitor brings up — consultation runs
    only inside steward-initiated derivation (H consults only
    for unsolicited offers; that seam contract is tested here at
    the function level, H's use is H's test)."""
    # Birth-path unknown subject + declines standing -> withheld.
    store = _store(tmp_path)
    record_offer_decline(store, USER, scope="subject", key=BOSS)
    calls: list = []
    result = derive_batch(
        USER, _pair("u", None), store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
    )
    assert calls == [] and result.births == []
    assert any("offer ambiguous (subject)" in s for s in result.skipped)
    # Same, no declines standing -> proceeds.
    store2 = _store(tmp_path / "u2")
    result = derive_batch(
        USER, _pair("u", None), store2,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
    )
    assert len(calls) == 1 and len(result.births) == 1
    # Extension-path coarse offer vs precise decline -> withheld,
    # and the new evidence is NOT attached by the withheld path.
    store3 = _store(tmp_path / "u3")
    thread, _ = _scoped_thread(store3, USER, "w", "work")
    record_offer_decline(store3, USER, scope="subject", key=BOSS)
    calls.clear()
    before_keys = {
        row.ref_kind + ":" + row.ref_id
        for row in store3.evidence_for(USER, thread.id)
    }
    result = derive_batch(
        USER, _extension_batch("w"), store3,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert calls == []
    assert any("offer ambiguous (subject)" in s for s in result.skipped)
    after_keys = {
        row.ref_kind + ":" + row.ref_id
        for row in store3.evidence_for(USER, thread.id)
    }
    assert after_keys == before_keys
    # API distinctness + purity.
    assert (
        is_offer_declined(
            store3, USER, subject_key=None, subject_precision="unknown"
        )
        == "ambiguous"
    )
    assert (
        is_offer_declined(
            store3, USER, subject_key=None, subject_precision="unknown"
        )
        != "subject"
    )
    n_before = len(store3.dismissals_for(USER))
    is_offer_declined(
        store3, USER, subject_key=None, subject_precision="unknown"
    )
    assert len(store3.dismissals_for(USER)) == n_before


# ---------------------------------------------------------------------------
# §10.8 deferred-worker consultation + §10.9 prune exemption
# ---------------------------------------------------------------------------


def _records_first_birth(store, user, tag, entity):
    """A birth with the backend down: thread + deferred row, no
    reading. Returns (thread, deferred row)."""
    result = derive_batch(
        user, _pair(tag, entity), store, generate_fn=_raising_gen
    )
    assert result.deferred, "records-first should owe prose"
    thread = store.get_thread(user, result.deferred[0])
    rows = [
        r
        for r in _deferred(store, user, status="pending")
        if r["thread_id"] == thread.id
    ]
    assert len(rows) == 1
    return thread, rows[0]


def test_deferred_worker_consultation_and_suppression(tmp_path):
    """§10.8: a deferred row whose offer is declined (invitation,
    subject, or per-signature case) settles as suppressed_by_decline
    — NOT done, NOT deleted: status value, matched scope + key
    retained in the suppression columns, texts cleared, refs
    retained, result records the suppression, 0 generations spent,
    thread + evidence still present. A second worker pass never
    re-claims the suppressed row; re-analysis of the same offer
    while the decline stands is still blocked; the exact suppressed
    proposal is never re-created (unique slot occupied).
    Ambiguous deferred rows stay pending and are re-checked each
    pass (not settled, not rendered)."""
    # Invitation case.
    store = _store(tmp_path / "inv")
    thread, row = _records_first_birth(store, USER, "s", BOSS)
    keys = sorted(i.evidence_key() for i in _pair("s", BOSS))
    inv = invitation_key("birth", "birth", "birth", keys)
    record_offer_decline(store, USER, scope="invitation", key=inv)
    calls: list = []
    result = work_deferred_prose(
        store, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert calls == []
    assert len(result.suppressed) == 1
    assert result.suppressed[0]["scope"] == "invitation"
    assert result.suppressed[0]["key"] == inv
    settled = _deferred(store, USER, status="suppressed_by_decline")
    assert len(settled) == 1 and settled[0]["id"] == row["id"]
    assert settled[0]["suppressed_scope"] == "invitation"
    assert settled[0]["suppressed_key"] == inv
    assert settled[0]["evidence_texts_json"] == "[]"
    assert settled[0]["evidence_refs_json"] != "[]"
    assert store.get_thread(USER, thread.id) is not None
    # Second pass never re-claims; re-analysis stays blocked and
    # creates no new deferred row.
    result = work_deferred_prose(
        store, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert calls == [] and result.suppressed == []
    assert len(_readings(store, USER, thread.id)) == 0
    result = derive_batch(
        USER, _pair("s", BOSS), store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
    )
    assert calls == [] and len(_deferred(store, USER)) == 1

    # Subject case.
    store2 = _store(tmp_path / "subj")
    thread2, row2 = _records_first_birth(store2, USER, "s", BOSS)
    record_offer_decline(store2, USER, scope="subject", key=BOSS)
    calls.clear()
    result = work_deferred_prose(
        store2, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert calls == []
    settled = _deferred(store2, USER, status="suppressed_by_decline")
    assert len(settled) == 1
    assert settled[0]["suppressed_scope"] == "subject"
    assert settled[0]["suppressed_key"] == "subj:" + BOSS

    # Per-signature case: the row's own birth signature dismissed.
    store3 = _store(tmp_path / "sig")
    thread3, row3 = _records_first_birth(store3, USER, "s", BOSS)
    dismiss_proposal(
        store3, USER, kind="thread_birth",
        signature=birth_signature(_pair("s", BOSS)),
    )
    calls.clear()
    result = work_deferred_prose(
        store3, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert calls == []
    settled = _deferred(store3, USER, status="suppressed_by_decline")
    assert len(settled) == 1
    assert settled[0]["suppressed_scope"] == "thread_birth"
    assert settled[0]["suppressed_key"].startswith("birth:")

    # Ambiguous case: unknown-subject row + subject decline
    # standing -> stays pending, re-checked each pass, never
    # rendered, and its thread is pinned from pruning (owed prose).
    store4 = _store(tmp_path / "amb")
    thread4, row4 = _records_first_birth(store4, USER, "s", None)
    record_offer_decline(store4, USER, scope="subject", key=BOSS)
    calls.clear()
    for _ in range(2):
        result = work_deferred_prose(
            store4, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
        )
        assert calls == []
        pending = _deferred(store4, USER, status="pending")
        assert len(pending) == 1 and pending[0]["id"] == row4["id"]
        assert _deferred(store4, USER, status="suppressed_by_decline") == []
    assert prune_ignored_threads(store4, USER) == []
    assert store4.get_thread(USER, thread4.id) is not None


def test_prune_exemption_pinned(tmp_path):
    """§10.9: pruning a stale steward-proposal thread leaves its
    decline rows intact (declines are not thread-owned and are
    never pruned — the asymmetry is intentional: expiry removes
    unasked-for material, never the visitor's explicit no)."""
    from datetime import datetime, timedelta, timezone

    store = _store(tmp_path)
    thread, _row = _records_first_birth(store, USER, "p", BOSS)
    calls: list = []
    work_deferred_prose(
        store, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert _deferred(store, USER, status="done")
    record_offer_decline(store, USER, scope="subject", key=BOSS)
    record_offer_decline(store, USER, scope="class", key="birth")
    dismiss_proposal(
        store, USER, kind="thread_birth",
        signature=birth_signature(_pair("p", BOSS)),
    )
    assert len(store.dismissals_for(USER)) == 3
    conn = sqlite3.connect(str(tmp_path / "narrative.db"))
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    conn.execute(
        "UPDATE narrative_threads SET updated_at = ? WHERE id = ?",
        (old, thread.id),
    )
    conn.commit()
    conn.close()
    assert prune_ignored_threads(store, USER) == [thread.id]
    assert store.get_thread(USER, thread.id) is None
    assert len(store.dismissals_for(USER)) == 3


# ---------------------------------------------------------------------------
# §10.10 per-user scoping + §10.14 gate interaction
# ---------------------------------------------------------------------------


def test_per_user_scoping(tmp_path):
    """§10.10: user A's declines do not block user B's identical
    offers (all three scopes, birth and extension paths)."""
    store = _store(tmp_path)
    items = _pair("sc", BOSS)
    keys = sorted(i.evidence_key() for i in items)
    record_offer_decline(
        store, USER, scope="invitation",
        key=invitation_key("birth", "birth", "birth", keys),
    )
    record_offer_decline(store, USER, scope="subject", key=BOSS)
    record_offer_decline(store, USER, scope="class", key="birth")
    calls: list = []
    gen = _counting_gen(BIRTH_JSON, calls)
    result = derive_batch(OTHER, items, store, generate_fn=gen)
    assert len(calls) == 1 and len(result.births) == 1
    other_thread = store.get_thread(OTHER, result.births[0])
    result = derive_batch(
        OTHER,
        [
            _item("evt-sc-3", FOCUS_TEXT + " once more", BOSS),
            _item("evt-sc-4", FOCUS_TEXT + " once more again", BOSS),
        ],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert len(calls) == 2
    assert len(_readings(store, OTHER, other_thread.id)) == 2
    # And USER's own identical birth is still blocked.
    result = derive_batch(USER, items, store, generate_fn=gen)
    assert len(calls) == 2 and result.births == []
    assert _threads(store, USER) == []


def test_gate_interaction(tmp_path):
    """§10.14: gate-closed batches consume-skip as in A (no
    consultation runs, no rows); on re-enablement, pre-existing
    declines apply to the first derived batch."""
    from local_ai.fellowship.events import FellowshipEvent

    def _event(event_id, text, user=USER):
        return FellowshipEvent(
            id=event_id,
            kind="meeting_completed",
            user_id=user,
            entity_type="meeting",
            entity_id="mentor-k1",
            evidence_text=text,
            summary="meeting turn",
            payload={"archetype_id": "mentor", "keystone_index": 1},
        )

    store = _store(tmp_path)
    thread = _birth(store, USER, "gt", "meeting:mentor-k1")
    flag = [False]
    calls: list = []
    pipe = StewardPipeline(
        store=store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
        scheduler=lambda fn: fn(),
        consent_reader=lambda user_id: flag[0],
    )
    # Gate closed: nothing derives, nothing is consulted.
    pipe.schedule_event(_event("evt-g1", FOCUS_TEXT + " once more"))
    assert calls == [] and len(_readings(store, USER, thread.id)) == 1
    # Declines recorded while closed persist; on re-enablement
    # the first derived batch respects them.
    record_offer_decline(store, USER, scope="subject", key="meeting:mentor-k1")
    flag[0] = True
    pipe.schedule_event(_event("evt-g2", FOCUS_TEXT + " once more again"))
    assert calls == [] and len(_readings(store, USER, thread.id)) == 1
    # Control: same flow with no declines extends normally.
    store2 = _store(tmp_path / "ctl")
    thread2 = _birth(store2, USER, "gt", "meeting:mentor-k1")
    calls2: list = []
    pipe2 = StewardPipeline(
        store=store2,
        generate_fn=_counting_gen(EXTENSION_JSON, calls2),
        scheduler=lambda fn: fn(),
        consent_reader=lambda user_id: True,
    )
    pipe2.schedule_event(_event("evt-g3", FOCUS_TEXT + " once more"))
    assert len(calls2) == 1
    assert len(_readings(store2, USER, thread2.id)) == 2


# ---------------------------------------------------------------------------
# §10.15 no-production-writer honesty + §10.17–10.20 deletion
# ---------------------------------------------------------------------------


def test_no_production_writer_claimed():
    """§10.15: B's record/clear functions are called by tests (and,
    later, E/H) — no test fakes a production writer that does not
    exist. This test guards it structurally: no module under
    local_ai/ calls the decline-writer functions. (The read-only
    consultation query is derivation's own machinery, not a
    writer, and is not restricted here.)"""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "local_ai"
    writers = {"record_offer_decline", "clear_offer_decline"}
    offenders = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in writers:
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert offenders == [], offenders


def _deletion_fixture(store, user):
    """Two steward threads (one with a reading, one with a
    deferred row), linked, plus one user-declared thread and
    decline rows in all scopes/regimes. Returns (t1, t2, user_t)."""
    t1 = _birth(store, user, "m1", BOSS)
    # Different entity for the second thread, or its pair would
    # overlap t1 and extend it instead of birthing a new thread.
    t2, _row = _records_first_birth(store, user, "m2", OTHER_ENTITY)
    store.link_threads(user, t1.id, t2.id)
    user_t = store.create_thread(user, origin="user_declared", title="mine")
    record_offer_decline(store, user, scope="subject", key=BOSS)
    record_offer_decline(store, user, scope="class", key="birth")
    record_offer_decline(
        store, user, scope="invitation",
        key=invitation_key("birth", "birth", "birth", ["event:evt-z-1"]),
    )
    dismiss_proposal(
        store, user, kind="thread_birth", signature="birth:event:evt-z-9"
    )
    return t1, t2, user_t


def test_deletion_distinction(tmp_path):
    """§10.17: routine clear of a user's steward-proposal material
    leaves ALL of their decline rows intact; full deletion of the
    same material removes their decline rows too (both regimes).
    A routine clear never deletes a decline row; a full deletion
    never preserves one secretly. User-declared threads are
    untouched by routine clear (they are not steward material)."""
    store = _store(tmp_path / "routine")
    t1, t2, user_t = _deletion_fixture(store, USER)
    report = store.clear_user_material(USER, operation="routine_clear")
    assert set(report["deleted_thread_ids"]) == {t1.id, t2.id}
    assert report["deleted_decline_count"] == 0
    assert store.get_thread(USER, t1.id) is None
    assert store.get_thread(USER, t2.id) is None
    assert store.get_thread(USER, user_t.id) is not None
    assert len(store.dismissals_for(USER)) == 4
    assert _deferred(store, USER) == []

    store2 = _store(tmp_path / "full")
    t1, t2, user_t = _deletion_fixture(store2, USER)
    report = store2.clear_user_material(USER, operation="full_delete")
    assert set(report["deleted_thread_ids"]) == {t1.id, t2.id}
    assert report["deleted_decline_count"] == 4
    assert store2.dismissals_for(USER) == []
    assert store2.get_thread(USER, user_t.id) is not None
    with pytest.raises(ValueError):
        store2.deletion_preview(USER, operation="nuke")
    with pytest.raises(ValueError):
        store2.clear_user_material(USER, operation="nuke")


def test_class_is_offer_boundary_not_processing_ban(tmp_path):
    """§10.18: the post-generation check blocks SURFACING (no
    change stored) — and the suite asserts nothing about
    pre-processing enforcement, which B does not implement. Proof
    the boundary is offer-only: the generation WAS invoked with
    the material (the prompt contains the evidence text), so
    analysis happened; only the storing/surfacing was blocked."""
    store = _store(tmp_path)
    thread = _birth(store, USER, "cb", BOSS)
    record_offer_decline(
        store, USER, scope="class", key="extension:reopened"
    )
    calls: list = []
    result = derive_batch(
        USER,
        [
            _item("evt-cbx-1", FOCUS_TEXT + " once more", BOSS),
            _item("evt-cbx-2", FOCUS_TEXT + " once more again", BOSS),
        ],
        store,
        generate_fn=_counting_gen(REOPENED_JSON, calls),
    )
    assert len(calls) == 1
    assert FOCUS_TEXT in calls[0][0]  # the material WAS analyzed
    assert len(_readings(store, USER, thread.id)) == 1
    assert _changes(store, USER, thread.id) == []
    assert any("offer declined (class)" in s for s in result.skipped)


def test_warn_first_previews(tmp_path):
    """§10.19–10.20: the deletion_preview for a routine clear
    names the affected material (thread ids + titles,
    reading/change/deferred counts, containment links touched)
    and states explicitly that decline rows are PRESERVED. The
    full-deletion preview names the same material AND the decline
    records that go too (count + scopes), so the visitor knows
    declined offers may be proposed again. No generic
    confirmation without content passes: previews name specific
    ids and titles. UI rendering of both previews is E's surface
    work and is not tested here — only the preview content."""
    store = _store(tmp_path)
    t1, t2, _user_t = _deletion_fixture(store, USER)
    link_id = store.links_for(USER, t1.id)[0].id
    routine = store.deletion_preview(USER, operation="routine_clear")
    assert routine["operation"] == "routine_clear"
    assert set(routine["thread_ids"]) == {t1.id, t2.id}
    assert {t["id"] for t in routine["threads"]} == {t1.id, t2.id}
    assert all(t["title"] for t in routine["threads"])
    assert routine["reading_count"] == 1
    assert routine["deferred_count"] == 1
    assert [l["id"] for l in routine["links_touched"]] == [link_id]
    assert routine["declines"]["preserved"] is True
    assert routine["declines"]["total"] == 4
    full = store.deletion_preview(USER, operation="full_delete")
    assert full["operation"] == "full_delete"
    assert set(full["thread_ids"]) == {t1.id, t2.id}
    assert full["declines"]["preserved"] is False
    assert full["declines"]["total"] == 4
    assert full["declines"]["by_kind"] == {
        "offer_subject": 1,
        "offer_class": 1,
        "offer_invitation": 1,
        "thread_birth": 1,
    }
    # Previews are read-only: nothing was deleted by computing them.
    assert store.get_thread(USER, t1.id) is not None
    assert len(store.dismissals_for(USER)) == 4
