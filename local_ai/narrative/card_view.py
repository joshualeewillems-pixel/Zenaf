"""The personal narrative card — a governed, read-only view (Phase 1A).

The card is NOT a store (design Rev 3 evaluation): it is an
assembly over existing records — one thread, its readings, its
change records, its evidence, and the visitor's endorsement
annotations — rendered through the shared currency derivation
(``currency.derive_currency``) so every surface sees the same
current field and the same history.

Read-only: this module writes nothing, calls no model, and
changes no standing. A card whose thread carries card sections
(``structure`` / ``distinctions`` / ``tags`` in a reading's
payload, a Phase 1B generation concern) surfaces them verbatim;
their absence is a normal state, not an error.
"""

from __future__ import annotations

from .currency import derive_currency
from .store import NarrativeStore

#: Reading-payload sections the card surfaces when present.
CARD_SECTIONS = ("structure", "distinctions", "tags")


def _reading_entry(store: NarrativeStore, user_id: str, reading, currency_entry):
    payload = reading.reading or {}
    entry = {
        "id": reading.id,
        "author": reading.author,
        "status": reading.status,
        "created_at": reading.created_at,
        "evidence_refs": list(reading.evidence_refs or []),
        "currency": currency_entry.to_dict(),
        "endorsements": store.card_endorsements_for(user_id, reading.id),
    }
    for key in CARD_SECTIONS:
        if key in payload:
            entry[key] = payload[key]
    return entry


def card_for(
    store: NarrativeStore, user_id: str, thread_id: str
) -> dict:
    """Assemble one personal narrative card as a plain dict.

    ``current_field`` holds the thread's live readings (derived
    currency, never stored status alone), each with its currency
    labels, its card sections when present, and the visitor's
    endorsement annotations for that exact version. ``history``
    holds the retired readings — organically superseded and
    verdict-closed alike — fully inspectable, never presented as
    equally current. ``has_competing`` is True when the current
    field holds readings in the derived ``competing`` condition.

    Raises ``ValueError`` for an unknown thread (or another
    user's), matching the store's ownership discipline.
    """
    thread = store.get_thread(user_id, thread_id)
    if thread is None:
        raise ValueError(f"unknown thread: {thread_id!r}")
    readings = store.readings_for(user_id, thread_id)
    changes = store.changes_for(user_id, thread_id)
    currency = derive_currency(thread, readings, changes)
    evidence_count = len(store.evidence_for(user_id, thread_id))

    current_field: list[dict] = []
    history: list[dict] = []
    for reading in readings:
        entry = _reading_entry(
            store, user_id, reading, currency[reading.id]
        )
        if currency[reading.id].placement == "current":
            current_field.append(entry)
        else:
            history.append(entry)

    return {
        "thread": {
            "id": thread.id,
            "title": thread.title,
            "status": thread.status,
        },
        "evidence_count": evidence_count,
        "current_field": current_field,
        "history": history,
        "has_competing": any(
            "competing" in entry["currency"]["labels"]
            for entry in current_field
        ),
    }
