"""Narrative Steward Phase 3 — emergent narrative discovery.

Discovery asks "what might we have overlooked entirely?" — a
relationship not explicitly present in any individual conversation.
It is distinct from revision ("what might we have misunderstood?",
Phase 6) and distinct from correspondence (a metaphor illuminating
a tension, Phase 7): a discovery proposes a structural relationship
between threads, with no metaphor, no generated prose, and no
automatic chaining to anything else.

Deterministic and generation-free: candidates are thread PAIRS
whose evidence shares entity refs, scored by rarity — a ref that
appears in few threads is distinctive; a ref that appears
everywhere is generic. Precision gating, not generation:

- Single-thread candidates never surface (a pair is required).
- Low-overlap pairs never surface: the rarity-weighted score
  must reach ``min_score`` (default 1.0 — one ref unique to the
  pair, or equivalent weight).
- A pair already covered by an existing thread's evidence never
  surfaces (the relationship is already inside one story).
- Examining evidence and finding no defensible relationship is
  ABSTENTION, and abstention writes nothing: ``discover``
  returns a result object, not a row. Only ``propose`` writes,
  and only as nascent ``steward_proposal`` threads — reviewable
  births, never auto-activations, never training input.

A discovery proposal thread cites the shared evidence refs from
both threads, states the shared refs and the two alternative
explanations (shared underlying pattern vs coincidence) in its
scope note, and stays provisional until the user verdicts it.
Discovery never cites itself as evidence, never becomes evidence
for a later discovery (proposal threads are nascent, and nascent
threads are excluded from pairing), and never triggers a
correspondence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import NarrativeThread
from .refs import SourceRef
from .store import NarrativeStore

#: Thread statuses eligible for discovery pairing. Nascent threads
#: are proposals themselves (including prior discovery proposals);
#: resolved/retired/archived threads are finished business.
_PAIRABLE_STATUSES = ("active", "dormant")

#: Default gate: one ref unique to the pair scores exactly 1.0.
DEFAULT_MIN_SCORE = 1.0


@dataclass(frozen=True)
class DiscoveryCandidate:
    """One candidate relationship between two threads."""

    thread_a_id: str
    thread_b_id: str
    shared_entity_refs: tuple[str, ...]
    score: float
    #: Evidence rows (one per shared ref, from either thread) that
    #: the proposal thread will cite. Row ids are thread-agnostic
    #: only as (kind, id) pairs — rebuilt as SourceRefs at propose
    #: time from the source rows.
    evidence_keys: tuple[tuple[str, str, str], ...] = ()
    #: The two alternatives, always stated together. A discovery
    #: never asserts which is true — that is the user's verdict.
    alternatives: tuple[str, ...] = (
        "a shared underlying pattern across both stories",
        "coincidence — the shared refs do not indicate a pattern",
    )


@dataclass
class DiscoveryResult:
    """The outcome of one discovery pass. Never a stored row."""

    candidates: list[DiscoveryCandidate] = field(default_factory=list)
    pairs_examined: int = 0
    #: True when pairs were examined and none passed the gate.
    #: Abstention is a complete result, not a failure — and it
    #: writes nothing.
    abstained: bool = False


def _live_threads(
    store: NarrativeStore, user_id: str
) -> list[NarrativeThread]:
    return [
        thread
        for thread in store.threads_for(user_id, limit=None)
        if thread.status in _PAIRABLE_STATUSES
    ]


def _thread_ref_map(
    store: NarrativeStore, user_id: str, thread_id: str
) -> dict[str, list]:
    """entity_ref -> evidence rows carrying it, for one thread."""
    by_ref: dict[str, list] = {}
    for row in store.evidence_for(user_id, thread_id):
        if row.entity_ref:
            by_ref.setdefault(row.entity_ref, []).append(row)
    return by_ref


def discover(
    store: NarrativeStore,
    user_id: str,
    *,
    min_score: float = DEFAULT_MIN_SCORE,
) -> DiscoveryResult:
    """Find candidate cross-thread relationships. Writes nothing.

    Rarity weight for a shared ref is 2 / (number of pairable
    threads carrying it): a ref carried by exactly the pair scores
    1.0; a ref carried by ten threads scores 0.2. Pairs are
    skipped when an existing thread's evidence already covers all
    their shared refs (any status — a settled story is not
    re-proposed as a discovery).
    """
    threads = _live_threads(store, user_id)
    ref_maps = {
        thread.id: _thread_ref_map(store, user_id, thread.id)
        for thread in threads
    }
    ref_thread_count: dict[str, int] = {}
    for mapping in ref_maps.values():
        for ref in mapping:
            ref_thread_count[ref] = ref_thread_count.get(ref, 0) + 1
    # Evidence keys per thread, for coverage dedupe: a pair is
    # skipped when a THIRD thread's evidence already covers all
    # their shared refs — the relationship already lives inside
    # one story. The pair's own threads never count (their own
    # evidence trivially covers their own refs).
    key_sets: dict[str, set[tuple[str, str]]] = {}
    for thread in store.threads_for(user_id, limit=None):
        key_sets[thread.id] = {
            (row.ref_kind, row.ref_id)
            for row in store.evidence_for(user_id, thread.id)
        }
    candidates: list[DiscoveryCandidate] = []
    pairs_examined = 0
    for i, thread_a in enumerate(threads):
        for thread_b in threads[i + 1 :]:
            pairs_examined += 1
            shared = sorted(
                set(ref_maps[thread_a.id]) & set(ref_maps[thread_b.id])
            )
            if not shared:
                continue
            score = sum(
                2.0 / ref_thread_count[ref] for ref in shared
            )
            if score < min_score:
                continue
            evidence_keys: list[tuple[str, str, str]] = []
            for ref in shared:
                row = ref_maps[thread_a.id][ref][0]
                evidence_keys.append(
                    (row.ref_kind, row.ref_id, row.evidence_kind)
                )
            key_set = {(kind, ref_id) for kind, ref_id, _ in evidence_keys}
            covered_elsewhere = any(
                key_set <= key_sets[other.id]
                for other in store.threads_for(user_id, limit=None)
                if other.id not in (thread_a.id, thread_b.id)
            )
            if covered_elsewhere:
                continue
            candidates.append(
                DiscoveryCandidate(
                    thread_a_id=thread_a.id,
                    thread_b_id=thread_b.id,
                    shared_entity_refs=tuple(shared),
                    score=score,
                    evidence_keys=tuple(evidence_keys),
                )
            )
    return DiscoveryResult(
        candidates=candidates,
        pairs_examined=pairs_examined,
        abstained=pairs_examined > 0 and not candidates,
    )


def propose(
    store: NarrativeStore,
    user_id: str,
    candidates: list[DiscoveryCandidate],
) -> list[NarrativeThread]:
    """Write discovery candidates as reviewable birth proposals.

    Each proposal is a nascent ``steward_proposal`` thread citing
    the shared evidence. Nothing activates without a user verdict;
    a rejected proposal archives (the review wiring's birth
    verdict), and the coverage dedupe in :func:`discover` keeps a
    rejected discovery from being re-proposed on the same refs.
    """
    threads: list[NarrativeThread] = []
    for candidate in candidates:
        refs = [
            SourceRef(
                kind=kind, ref_id=ref_id, evidence_kind=evidence_kind
            )
            for kind, ref_id, evidence_kind in candidate.evidence_keys
        ]
        title_a = store.get_thread(user_id, candidate.thread_a_id)
        title_b = store.get_thread(user_id, candidate.thread_b_id)
        name_a = title_a.title if title_a else candidate.thread_a_id
        name_b = title_b.title if title_b else candidate.thread_b_id
        thread = store.create_thread(
            user_id,
            origin="steward_proposal",
            title=f"Shared pattern: {name_a} × {name_b}",
            scope=(
                "discovery: threads share "
                + ", ".join(candidate.shared_entity_refs)
                + "; either a shared underlying pattern or "
                "coincidence — provisional until verdict"
            ),
            evidence_refs=refs,
        )
        threads.append(thread)
    return threads
