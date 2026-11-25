"""Bench foliage evidence from steward readings (rapid fire item 5,
founder-authorized 2026-11-25).

The Bench's §7 foliage has two honest sources. The first shipped
with the Bench itself (PR #415): a task's origin provenance — the
seat whose approved proposal created the task. The second is this
module: the seats whose STEWARD READINGS touch the task. The
design fixture foliated twigs from Maeve's steward readings (a
per-task discussion map); until now that source had no product
endpoint. This module is the read behind
``GET /vision-execution/bench-foliage/by-parent/{type}/{id}``.

Linkage — REUSED, not reinvented: a thread touches a task exactly
when context preparation (PR #425) says a thread touches a
subject — its evidence names the record, through either recorded
naming channel (the derivation index ``entity_ref ==
"<type>:<id>"``, or a ``ve_entity`` evidence row for the record's
id). The test itself is imported from context_preparation.

Attribution — from the reading record itself: ``ThreadReading.
author`` is the field that attributes a reading. It is a seat
archetype id for seat-authored readings (V1 noting writes
``author = archetype_id``), ``"steward"`` for the Steward's own
derivation readings, ``"user"`` for the visitor's. Only a seat
archetype foliates, and never the skeptic: §7 is Bench law —
discussion with Severine alone never foliates her own tree, and
her colour is deliberately absent from the foliage palette. Two
candidate attributions were considered and rejected:

* ``"steward"`` → Maeve. The fixture's foliage seat was Maeve
  because the fixture's discussion map was drawn as hers. The
  product record does not support the mapping: the Steward is
  not one of the seven seats and is not Maeve (she is the
  guardian seat; the Steward is chief of staff). Steward-authored
  readings therefore contribute NO foliage here — an honest
  absence, reported as such, rather than a borrowed colour.
* Lens ``seat_affinity``. Affinity is a routing hint (lenses.py
  says so in as many words: "routing hint, NOT a permission"),
  and a reading is bound to a lens only through an optional
  progression position. A hint about where material leans is not
  an attribution of who wrote it.

Which readings count: the thread's live readings — ACCEPTED
readings (the standing record) plus PROPOSED readings that are
currency-current (the pencil channel's own filter, mirrored from
context_preparation's steward item: a proposed reading displaced
through change lineage is history, not living material).
Superseded and rejected readings never foliate.

Gate — mirrored from context_preparation's steward source,
fail-closed: the ``ZENAF_STEWARD_PENCIL`` master switch first,
then BOTH steward consent flags (``coordination_allowed``), then
standing threads only (active/dormant — nascent threads are
invisible, exactly as in the pencil channel). Gate closed or
consent absent ⇒ empty foliage, never an error, never a leak.
One pencil mechanism is deliberately NOT mirrored:
``prepare_context`` relevance re-validation WRITES relevance
assessment rows. This read writes nothing, anywhere — so, exactly
as in context preparation, subject relevance here is the stricter
direct test (evidence naming this record) and no assessment is
recorded.

Owner isolation is structural: the parent resolves through the
subject block's owner-scoped resolver (a foreign id resolves to
nothing), tasks are listed through the owner-scoped VE getters,
and every narrative read is scoped by the caller's user_id.

The assembler never raises: any failure degrades to empty
foliage, so an unreadable narrative store can never take the
Bench down.
"""

from __future__ import annotations

import logging
from typing import Any

from local_ai.conversation import context_preparation as _cp
from local_ai.conversation import subject_context as _sc

logger = logging.getLogger(__name__)

#: Parent kinds the Bench grows trees from and a task can hang
#: under. ``task`` scopes to the task itself plus its subtasks
#: (the subject block's children definition).
_PARENT_TYPES = frozenset({"initiative", "project", "task"})


def _seat_ids() -> frozenset[str]:
    """The seven seat archetype ids — the council registry's own
    list, so a seat renamed or added there is honoured here."""
    from local_ai.council.jurisdictions import jurisdiction_ids

    return frozenset(jurisdiction_ids())


def _tasks_in_scope(
    user_id: str, parent_type: str, parent_id: str
) -> list[dict[str, Any]] | None:
    """The caller's tasks under the parent, or None when the
    parent does not resolve as the caller's own (foreign, deleted,
    legacy — nothing, never a guess)."""
    from local_ai.vision_execution import storage as ve

    row = _sc._resolve_subject(user_id, parent_type, parent_id)
    if not row:
        return None
    if parent_type == "task":
        tasks = [row]
        _label, subtasks, _noun = _sc._children(user_id, row, "task")
        tasks.extend(subtasks)
        return tasks
    if parent_type == "project":
        return ve.list_tasks(user_id, project_id=str(row["id"]))
    # initiative: its projects (the subject block's children),
    # then each project's tasks.
    _label, projects, _noun = _sc._children(user_id, row, "initiative")
    tasks: list[dict[str, Any]] = []
    for project in projects:
        tasks.extend(ve.list_tasks(user_id, project_id=str(project["id"])))
    return tasks


def _reading_authors_current(
    store: Any, user_id: str, thread: Any
) -> set[str]:
    """The authors of one thread's live readings: accepted
    readings as they stand, plus proposed readings filtered to
    currency-current exactly as the pencil channel filters them
    (a proposed reading displaced through change lineage is
    history and authors nothing here)."""
    from local_ai.narrative.currency import derive_currency

    authors: set[str] = set()
    for reading in store.readings_for(user_id, thread.id, status="accepted"):
        if reading.author:
            authors.add(reading.author)
    proposed = store.readings_for(user_id, thread.id, status="proposed")
    if proposed:
        currency = derive_currency(
            thread, proposed, store.changes_for(user_id, thread.id)
        )
        for reading in proposed:
            if currency[reading.id].placement == "current" and reading.author:
                authors.add(reading.author)
    return authors


def foliage_for_parent(
    user_id: str,
    parent_type: str,
    parent_id: str,
    *,
    narrative_store: Any | None = None,
    consent_connection: Any | None = None,
) -> dict[str, list[str]]:
    """Foliage evidence for the Bench: ``{task_id: [seat, ...]}``
    for the caller's tasks under one parent — the seats whose
    steward readings touch each task, sorted, skeptic excluded.

    Read-only and fail-closed: the pencil gates mirrored from
    context preparation; any failure, closed gate, absent
    consent, unresolvable parent, or absent store yields ``{}``
    (or the partial map computed before the failure). Never
    raises, never writes.
    """
    try:
        if not user_id or not parent_id:
            return {}
        parent_type = str(parent_type or "").strip().lower()
        if parent_type not in _PARENT_TYPES:
            return {}
        tasks = _tasks_in_scope(user_id, parent_type, str(parent_id))
        if not tasks:
            return {}
    except Exception:
        logger.exception("bench foliage: parent resolution failed")
        return {}

    try:
        from local_ai.narrative.consent import coordination_allowed
        from local_ai.narrative.context import (
            CONTEXT_THREAD_STATUSES,
            pencil_context_enabled,
        )

        if not pencil_context_enabled():
            return {}
        if not coordination_allowed(user_id, connection=consent_connection):
            return {}
        store = narrative_store
        if store is None:
            from local_ai.narrative.store import NarrativeStore

            store = NarrativeStore()
        standing = [
            t
            for t in store.threads_for(user_id, limit=None)
            if t.status in CONTEXT_THREAD_STATUSES
        ]
        seats = _seat_ids()
    except Exception:
        logger.exception("bench foliage: steward gate failed")
        return {}

    foliage: dict[str, set[str]] = {}
    for task in tasks:
        task_id = str(task.get("id") or "")
        if not task_id:
            continue
        subject_ref = f"task:{task_id}"
        try:
            for thread in standing:
                if not _cp._thread_names_subject(
                    store, user_id, thread, subject_ref, task_id
                ):
                    continue
                for author in _reading_authors_current(store, user_id, thread):
                    if author in seats and author != "skeptic":
                        foliage.setdefault(task_id, set()).add(author)
        except Exception:
            logger.exception("bench foliage: thread scan failed for a task")
            continue
    return {task_id: sorted(found) for task_id, found in foliage.items() if found}
