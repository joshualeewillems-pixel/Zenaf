"""V4 — the obligation-block gate for champion (I5, partial).

Governing direction §10: capability awareness is persistent;
contextual relevance is circumstantial. The capability awareness
slice (``continuation_block``) renders always and is never touched
here. The obligation *apparatus* — ``obligation_context``, including
its record list and ``PROPOSAL_INSTRUCTION`` — renders only when a
composed per-turn relevance determination fires.

The determination (§10.1, composed, all deterministic, no model):

1. **Arc attendance** — the active encounter arc's carried subjects
   (its current readings' tensions / open questions / recognitions
   and its held notes), when capture is live for champion. Arc
   attendance alone NEVER fires the apparatus (§10.2, the Priya
   case): it establishes what the conversation is about, and a
   deliberation about capacity is not a call for task operations.
2. **Steward relevance** — ``assess_relevance`` (reused unchanged)
   over the durable candidate set: the visitor's VE tasks (the
   obligation builder's own record set), open proposals (standing
   threads carrying a proposed reading), standing threads, and
   attended subjects — the current message entering through
   ``attended_refs_for_text``.
3. **Bounded recency** — subjects attended in the last
   ``RECENCY_TURNS`` visitor turns, for follow-ups ("yes, do it")
   whose current message names nothing.

A candidate fires the apparatus when it is *taken up* in the
exchange: a live proposal awaiting the visitor; a candidate whose
entity refs are attended now or within the recency bound; or a
candidate ``assess_relevance`` finds relevant through an attended
shared ref / attended thread. With no active arc the same gate runs
over the durable records alone — binary, and recorded either way.

Every determination — firing or not — is recorded through the
existing assessment path (``store.record_relevance_assessment``,
as ``coordination.prepare_context`` uses it), so "not relevant" is
a recorded result, not an absence.

The gate governs *rendering only*, never authorization (§10,
§12.4). The ``ve_entity`` citation writer and reference-following
candidate derivation (EO-7) are deferred by design: gate candidates
from VE records are the obligation builder's own record set, read
directly — a read of existing data, not a derivation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .context import attended_refs_for_text
from .relevance import assess_relevance

#: The gate toggle (V4's independent switch; V1's capture switch and
#: V3's carriage switch are separate flags and neither lives here).
#: Default OFF everywhere, read per call, in the house flag idiom
#: (cf. ``pencil_context_enabled``): with the toggle off the
#: apparatus renders unconditionally, exactly as before the gate.
GATE_ENV = "ZENAF_OBLIGATION_GATE"

#: The branch the determination is recorded under.
CHAMPION_BRANCH_ID = "seat:champion"

#: Bounded recency (signal 3): visitor turns, counting back from the
#: current message, whose attended subjects still count as taken up.
RECENCY_TURNS = 3


def obligation_gate_enabled() -> bool:
    """Is the obligation-block gate live right now? Default OFF."""
    raw = os.environ.get(GATE_ENV)
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return False


@dataclass(frozen=True)
class GateCandidate:
    """One durable candidate the determination composes over."""

    kind: str  # "ve_task" | "proposal" | "thread"
    text: str = ""
    entity_refs: tuple[str, ...] = ()
    thread_id: str | None = None
    strand_weights: dict | None = None
    awaiting: bool = False  # a live proposal awaiting the visitor


@dataclass(frozen=True)
class ObligationDetermination:
    """The composed per-turn determination (unstored form)."""

    fires: bool
    reasons: tuple[str, ...] = ()
    arc_attended: bool = False
    arc_thread_id: str | None = None
    arc_subjects: tuple[str, ...] = ()
    attended_refs: tuple[str, ...] = ()
    recent_refs: tuple[str, ...] = ()
    candidate_inputs: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def assessment_inputs(self) -> dict:
        return {
            "gate": "obligation_block",
            "arc_attended": self.arc_attended,
            "arc_thread_id": self.arc_thread_id,
            "arc_subjects": list(self.arc_subjects),
            "attended_refs": list(self.attended_refs),
            "recent_refs": list(self.recent_refs),
            "candidates": [dict(c) for c in self.candidate_inputs],
        }


def _tokens(text: str) -> set[str]:
    from .relevance import _tokens as relevance_tokens

    return set(relevance_tokens(text or ""))


def compose_determination(
    *,
    message: str,
    history_texts: tuple[str, ...] | list[str] = (),
    arc_subjects: tuple[str, ...] | list[str] = (),
    arc_thread_id: str | None = None,
    arc_entity_refs: tuple[str, ...] | list[str] = (),
    candidates: tuple[GateCandidate, ...] | list[GateCandidate] = (),
) -> ObligationDetermination:
    """Compose the §10.1 determination from explicit inputs (pure)."""
    candidates = list(candidates)
    all_refs: list[str] = list(arc_entity_refs)
    for cand in candidates:
        all_refs.extend(cand.entity_refs)
    attended = attended_refs_for_text(all_refs, message or "")
    recent_texts = list(history_texts)[-RECENCY_TURNS:]
    recent: set[str] = set()
    for text in recent_texts:
        recent |= attended_refs_for_text(all_refs, text or "")
    taken_up_refs = set(attended) | recent

    # Signal 1 — arc attendance: the arc's carried subjects are
    # attended by the current/recent exchange (refs or >=2 tokens).
    arc_attended = False
    if arc_thread_id is not None or arc_subjects:
        arc_text = " ".join(arc_subjects)
        arc_tokens = _tokens(arc_text)
        msg_tokens = _tokens(message or "")
        recent_tokens: set[str] = set()
        for text in recent_texts:
            recent_tokens |= _tokens(text)
        arc_attended = bool(
            (set(arc_entity_refs) & taken_up_refs)
            or len(arc_tokens & msg_tokens) >= 2
            or len(arc_tokens & recent_tokens) >= 2
        )

    reasons: list[str] = []
    candidate_inputs: list[dict] = []
    fires = False
    for cand in candidates:
        result = assess_relevance(
            CHAMPION_BRANCH_ID,
            candidate_text=cand.text,
            candidate_entity_refs=cand.entity_refs,
            candidate_strand_weights=cand.strand_weights,
            candidate_thread_id=cand.thread_id,
            attended_entity_refs=tuple(taken_up_refs) + tuple(arc_entity_refs),
            attended_thread_ids=(arc_thread_id,) if arc_thread_id else (),
        )
        cand_refs_taken_up = bool(set(cand.entity_refs) & taken_up_refs)
        cand_reasons: list[str] = []
        if cand.awaiting:
            cand_reasons.append("live_proposal_awaiting")
        if cand_refs_taken_up and set(cand.entity_refs) & set(attended):
            cand_reasons.append("attended_subject")
        elif cand_refs_taken_up:
            cand_reasons.append("bounded_recency")
        if result.relevant and cand_refs_taken_up:
            cand_reasons.append("assess_relevance:" + ",".join(result.reasons))
        if cand.awaiting and arc_attended and cand.kind == "proposal":
            cand_reasons.append("arc_attendance")
        cand_fires = bool(cand_reasons)
        fires = fires or cand_fires
        for reason in cand_reasons:
            if reason not in reasons:
                reasons.append(reason)
        candidate_inputs.append(
            {
                "kind": cand.kind,
                "thread_id": cand.thread_id,
                "entity_refs": list(cand.entity_refs),
                "awaiting": cand.awaiting,
                "assess_relevant": result.relevant,
                "assess_reasons": list(result.reasons),
                "fires": cand_fires,
                "fire_reasons": cand_reasons,
            }
        )
    if not fires:
        reasons = ["not_relevant"]
    return ObligationDetermination(
        fires=fires,
        reasons=tuple(reasons),
        arc_attended=arc_attended,
        arc_thread_id=arc_thread_id,
        arc_subjects=tuple(arc_subjects),
        attended_refs=tuple(sorted(attended)),
        recent_refs=tuple(sorted(recent)),
        candidate_inputs=tuple(candidate_inputs),
    )


# -- gathering over the live stores ---------------------------------------------


def _reading_subjects(reading: dict | None) -> list[str]:
    subjects: list[str] = []
    for key in ("tensions", "open_questions"):
        for item in (reading or {}).get(key) or []:
            if isinstance(item, str):
                subjects.append(item)
            elif isinstance(item, dict):
                for value in item.values():
                    if isinstance(value, str) and value:
                        subjects.append(value)
    recognition = (reading or {}).get("recognition")
    if isinstance(recognition, str) and recognition:
        subjects.append(recognition)
    return subjects


def gather_candidates(
    store: Any,
    user_id: str,
    *,
    conversation_id: str,
    archetype_id: str = "champion",
) -> tuple[tuple[str, ...], str | None, tuple[str, ...], list[GateCandidate]]:
    """Read the durable candidate set + the live encounter arc.

    Returns (arc_subjects, arc_thread_id, arc_entity_refs, candidates).
    Every read is of existing data; any individual read failing
    degrades that candidate class to empty, never raises here —
    the caller guards the whole determination.
    """
    arc_subjects: list[str] = []
    arc_thread_id: str | None = None
    arc_refs: list[str] = []
    candidates: list[GateCandidate] = []

    scope = None
    try:
        scope = store.open_encounter_for(user_id, conversation_id, archetype_id)
    except Exception:
        scope = None
    if scope:
        arc_thread_id = scope.get("thread_id")
    if arc_thread_id:
        try:
            for reading in store.readings_for(user_id, arc_thread_id):
                arc_subjects.extend(_reading_subjects(reading.reading or {}))
        except Exception:
            pass
        try:
            for note in store.held_notes_for(user_id, arc_thread_id):
                statement = note.get("statement")
                if statement:
                    arc_subjects.append(str(statement))
        except Exception:
            pass
        try:
            for row in store.evidence_for(user_id, arc_thread_id):
                arc_refs.append(f"{row.ref_kind}:{row.ref_id}")
        except Exception:
            pass

    # Standing threads + open proposals (durable, not the arc itself).
    try:
        threads = store.threads_for(user_id, limit=None)
    except Exception:
        threads = []
    for thread in threads:
        if thread.id == arc_thread_id:
            continue
        if thread.status not in ("active", "dormant", "nascent"):
            continue
        text_parts = [thread.title or "", thread.scope or ""]
        awaiting = False
        try:
            for reading in store.readings_for(user_id, thread.id):
                text_parts.extend(_reading_subjects(reading.reading or {}))
                if reading.status == "proposed":
                    awaiting = True
        except Exception:
            pass
        candidates.append(
            GateCandidate(
                kind="proposal" if awaiting else "thread",
                text=" ".join(p for p in text_parts if p),
                thread_id=thread.id,
                strand_weights=thread.strand_weights,
                awaiting=awaiting,
            )
        )

    # VE tasks — the obligation builder's own record set.
    try:
        from local_ai.vision_execution import storage as ve_storage
        from local_ai.vision_execution.obligations import _is_open

        for task in ve_storage.list_tasks(user_id):
            if not _is_open(task):
                continue
            task_id = str(task.get("id") or "")
            candidates.append(
                GateCandidate(
                    kind="ve_task",
                    text=" ".join(
                        str(task.get(k) or "")
                        for k in ("title", "notes", "description")
                    ),
                    entity_refs=(f"ve_entity:{task_id}",) if task_id else (),
                )
            )
    except Exception:
        pass
    return tuple(arc_subjects), arc_thread_id, tuple(arc_refs), candidates


def determine_and_record(
    store: Any,
    user_id: str,
    *,
    conversation_id: str,
    archetype_id: str = "champion",
    message: str,
    history_texts: tuple[str, ...] | list[str] = (),
) -> ObligationDetermination:
    """Gather, compose, and record one turn's determination.

    The recording lands through the existing assessment path
    (``record_relevance_assessment``) for BOTH outcomes.
    """
    arc_subjects, arc_thread_id, arc_refs, candidates = gather_candidates(
        store, user_id, conversation_id=conversation_id, archetype_id=archetype_id
    )
    determination = compose_determination(
        message=message,
        history_texts=history_texts,
        arc_subjects=arc_subjects,
        arc_thread_id=arc_thread_id,
        arc_entity_refs=arc_refs,
        candidates=candidates,
    )
    evidence_refs: list[str] = list(arc_refs)
    for cand in candidates:
        evidence_refs.extend(cand.entity_refs)
    store.record_relevance_assessment(
        user_id,
        CHAMPION_BRANCH_ID,
        thread_id=arc_thread_id,
        evidence_refs=evidence_refs,
        relevant=determination.fires,
        reasons=determination.reasons,
        inputs=determination.assessment_inputs,
    )
    return determination


class _LazyGateStore:
    """Lazily-built NarrativeStore (the noting writer's pattern):
    constructing the service never touches the narrative DB."""

    def __init__(self) -> None:
        self._store: Any = None

    def get(self) -> Any:
        if self._store is None:
            from .store import NarrativeStore

            self._store = NarrativeStore()
        return self._store


def default_gate_store_provider() -> _LazyGateStore:
    return _LazyGateStore()


class ObligationGate:
    """The injectable gate the conversation service consults.

    The service never imports this package (the Part XI turn-path
    pin: the turn path may import only the narrative consent leaf) —
    the routes wire this object in, exactly as V1's noting writer is
    wired. ``store`` is a NarrativeStore; when omitted, one is built
    lazily on first determination.
    """

    def __init__(self, store: Any | None = None) -> None:
        self._store = store
        self._lazy: _LazyGateStore | None = None if store is not None else _LazyGateStore()

    def enabled(self) -> bool:
        return obligation_gate_enabled()

    def determine_and_record(
        self,
        user_id: str,
        *,
        conversation_id: str,
        archetype_id: str = "champion",
        message: str,
        history_texts: tuple[str, ...] | list[str] = (),
    ) -> ObligationDetermination:
        store = self._store if self._store is not None else self._lazy.get()
        return determine_and_record(
            store,
            user_id,
            conversation_id=conversation_id,
            archetype_id=archetype_id,
            message=message,
            history_texts=history_texts,
        )


def default_obligation_gate() -> ObligationGate:
    """The production gate: lazily-built NarrativeStore (the noting
    writer's pattern — constructing it touches no DB)."""
    return ObligationGate()


__all__ = [
    "CHAMPION_BRANCH_ID",
    "GATE_ENV",
    "RECENCY_TURNS",
    "GateCandidate",
    "ObligationDetermination",
    "ObligationGate",
    "compose_determination",
    "default_gate_store_provider",
    "default_obligation_gate",
    "determine_and_record",
    "gather_candidates",
    "obligation_gate_enabled",
]
