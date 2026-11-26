"""Per-subject seat-interaction counts — the Living Palace's ivy read.

Scene 1 of the Palace (founder, 2026-11-26) grows ivy on a building
according to the seat interaction recorded about its subject: how
much the visitor has talked about the record, and with which seats.
This module is the read side of that record. It invents nothing and
writes nothing: it counts what the conversation store already holds,
through the same linkage ``context_preparation.py`` documents —

* every message row carries a live-context snapshot
  (``messages.context_json``): the exact LiveContext the turn was
  sent with, sheet_type + entity_type + entity_id included;
* a USER message's own words were said ABOUT a subject when that
  message's own snapshot names it (entity_type + entity_id), and
  the seat it was said to is the message's own ``archetype_id``.

So an "interaction" here is one visitor turn, sent with a subject
selected, to one seat. Assistant replies are not counted (their
snapshots echo the turn's context; counting them would double every
exchange), and neither are messages whose snapshot names no subject
or a type outside the subject vocabulary.

Owner isolation is structural, inherited from the store: the scan
is ``ConversationStore.messages_across_conversations``, whose
ownership predicate is the query's first condition — another user's
rows can never match, by construction (the PR #409 pattern).

The scan is bounded (the store's own cap): interactions older than
the newest ``SCAN_LIMIT`` messages are simply not counted. The
bound is named here rather than hidden, exactly as the context
preparation's 500-message bound is named there.
"""

from __future__ import annotations

from typing import Any

from local_ai.conversation.subject_context import _SUBJECT_TYPES

#: The store scan's bound for this aggregate read. The store caps
#: ``messages_across_conversations`` at 2000; this read takes the
#: fullest count that bounded scan allows (the context
#: preparation's tighter 500 bound serves per-turn excerpts, a
#: different purpose).
SCAN_LIMIT = 2000


def aggregate_subject_interactions(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Count visitor turns per subject from scanned message rows.

    ``messages`` are the dicts ``messages_across_conversations``
    returns (parsed ``context``, ``archetype_id``, ``role``). The
    result is deterministic: subjects sorted by (entity_type,
    entity_id), per-seat counts sorted by seat id.
    """
    counts: dict[tuple[str, str], dict[str, Any]] = {}
    for message in messages:
        if message.get("role") != "user":
            continue
        context = message.get("context") or {}
        if not isinstance(context, dict):
            continue
        entity_type = str(context.get("entity_type") or "").strip().lower()
        entity_id = str(context.get("entity_id") or "").strip()
        if entity_type not in _SUBJECT_TYPES or not entity_id:
            continue
        entry = counts.setdefault(
            (entity_type, entity_id),
            {"entity_type": entity_type, "entity_id": entity_id, "total": 0, "per_seat": {}},
        )
        entry["total"] += 1
        seat = str(message.get("archetype_id") or "").strip()
        if seat:
            entry["per_seat"][seat] = entry["per_seat"].get(seat, 0) + 1
    subjects = []
    for key in sorted(counts):
        entry = counts[key]
        entry["per_seat"] = dict(sorted(entry["per_seat"].items()))
        subjects.append(entry)
    return {"subjects": subjects}


def subject_interactions_for_user(store: Any, user_id: str) -> dict[str, Any]:
    """The caller's per-subject interaction counts, from their own
    conversation store rows only. Raises nothing the caller must
    handle beyond its own failure isolation: the route degrades to
    an empty result when this read fails."""
    messages = store.messages_across_conversations(user_id, limit=SCAN_LIMIT)
    return aggregate_subject_interactions(messages)
