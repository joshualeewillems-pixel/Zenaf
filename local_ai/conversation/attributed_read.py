"""The attributed subject read — one shared, read-only composition.

For a subject the caller owns (an initiative, project, task or idea),
this read answers three questions from the records that already exist,
attributing every item to the home it came from:

* **Boundary states** — what boundary material is attributable to the
  subject, each item labelled by its STATE (expressed / proposed /
  established / enforceable), composed from existing homes only:
  core-profile non-negotiables and strand topic boundaries (expressed —
  they exist, but neither is placed at the subject; no per-subject
  boundary record exists in any store), steward/seat interpretations
  naming the subject (proposed, pencil register, under the mirrored
  steward gates), VE decisions and follow-through commitments naming
  the subject (established), and the permission system plus consent
  flags (enforceable — enforcement is not expression).

* **Kintsugi material** — the subject's live readings' tensions and
  open questions, their derived currency, their standing
  reconsiderations, and whether the lineage shows an interpretation
  RECONSIDERED with its correction ACCEPTED (accepted supersession).
  The seam this earns marks a restoration of UNDERSTANDING — a
  corrected interpretation — never a restoration of the circumstances
  understood. A tension, however enduring, is an open question held;
  nothing in this read represents it as damage.

* **Attending seats** — the seats whose seat-authored readings name
  the subject (attribution is ``ThreadReading.author``, never lens
  affinity — bench_foliage's discipline) and the seats whose
  conversations attend the subject (context_preparation's scan).

This is NOT a second intelligence: it composes the existing narrative
architecture and record homes, writes nothing, and invents nothing.
Owner-scoped throughout; every failure mode reads as empty, never an
error, never a leak. The steward-gated parts (proposed interpretations,
the Kintsugi material, reading-based attendance) mirror the pencil
gate composition exactly — ``ZENAF_STEWARD_PENCIL`` on, then
:func:`local_ai.narrative.consent.coordination_allowed` (both consent
flags), fail-closed. The visitor's own records (expressed, established,
enforceable, conversation attendance) are not steward material and are
not gated.
"""

from __future__ import annotations

import logging
from typing import Any

from local_ai.conversation import bench_foliage as _bf
from local_ai.conversation import context_preparation as _cp
from local_ai.conversation import subject_context as _sc
from local_ai.conversation.store import ConversationStore
from local_ai.followthrough.store import FollowthroughStore
from local_ai.narrative import consent as _consent
from local_ai.narrative.context import CONTEXT_THREAD_STATUSES, pencil_context_enabled
from local_ai.narrative.currency import derive_currency
from local_ai.narrative.store import NarrativeStore
from local_ai.permissions.home import permission_home_state
from local_ai.strand_interviews.keys import DESIGN_STRAND_KEYS
from local_ai.vision_execution import storage as _ve

logger = logging.getLogger(__name__)

# Change kinds that record an interpretation being reconsidered. A
# seam is earned only when such a change's successor reading stands
# ACCEPTED — the correction itself was ruled on, not merely offered.
_RECONSIDERED_KINDS = ("contradicted", "reopened")

_THREAD_CAP = 8
_ITEMS_PER_READING = 5
_TEXT_CAP = 240


def _clean_items(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = _sc._clean(str(value or ""))[:_TEXT_CAP]
        if text:
            out.append(text)
        if len(out) >= _ITEMS_PER_READING:
            break
    return out


def _empty_read(entity_type: str, entity_id: str) -> dict[str, Any]:
    return {
        "resolved": False,
        "subject": None,
        "steward_gate_open": False,
        "boundaries": {
            "expressed": [],
            "proposed": [],
            "established": [],
            "enforceable": {
                "permission_home_enabled": False,
                "permission_consent_given": False,
                "steward_derivation": False,
                "steward_coordination": False,
            },
        },
        "kintsugi": None,
        "guests": {"attending": []},
    }


def _steward_gate_open(user_id: str, consent_connection: Any) -> bool:
    """The pencil gate composition, mirrored exactly (fail-closed)."""
    if not pencil_context_enabled():
        return False
    try:
        return bool(
            _consent.coordination_allowed(user_id, connection=consent_connection)
        )
    except Exception:  # noqa: BLE001 — fail closed, never raise
        logger.debug("attributed read: consent check failed", exc_info=True)
        return False


def _standing_threads_naming(
    store: NarrativeStore, user_id: str, subject_ref: str, entity_id: str
) -> list[Any]:
    """Standing threads whose evidence names the subject — the linkage
    is context_preparation's, reused, not re-derived."""
    out: list[Any] = []
    try:
        threads = [
            t
            for t in store.threads_for(user_id, limit=None)
            if t.status in CONTEXT_THREAD_STATUSES
        ]
    except Exception:  # noqa: BLE001
        return out
    for thread in threads:
        try:
            if _cp._thread_names_subject(
                store, user_id, thread, subject_ref, entity_id
            ):
                out.append(thread)
        except Exception:  # noqa: BLE001 — one bad thread never sinks the read
            continue
        if len(out) >= _THREAD_CAP:
            break
    return out


def _thread_record(
    store: NarrativeStore, user_id: str, thread: Any
) -> tuple[list[Any], list[Any], dict[str, Any]]:
    """(all readings, changes, currency by reading id) for one thread."""
    try:
        readings = list(store.readings_for(user_id, thread.id) or [])
        changes = list(store.changes_for(user_id, thread.id) or [])
    except Exception:  # noqa: BLE001
        return [], [], {}
    if not readings:
        return readings, changes, {}
    try:
        currency = derive_currency(thread, readings, changes)
    except Exception:  # noqa: BLE001
        currency = {}
    return readings, changes, currency


def _is_live(reading: Any, currency: dict[str, Any]) -> bool:
    """Live = accepted, or proposed and still placed current — the
    same rule bench_foliage applies for foliage authorship."""
    if reading.status == "accepted":
        return True
    if reading.status != "proposed":
        return False
    cur = currency.get(reading.id)
    return cur is not None and cur.placement == "current"


def _reading_view(reading: Any, currency: dict[str, Any]) -> dict[str, Any]:
    cur = currency.get(reading.id)
    body = reading.reading if isinstance(reading.reading, dict) else {}
    return {
        "reading_id": reading.id,
        "author": reading.author,
        "status": reading.status,
        "placement": cur.placement if cur is not None else None,
        "currency_labels": list(cur.labels) if cur is not None else [],
        "tensions": _clean_items(body.get("tensions")),
        "open_questions": _clean_items(body.get("open_questions")),
    }


def _restoration_of_understanding(
    readings: list[Any], changes: list[Any]
) -> bool:
    """True when a lineage shows an interpretation reconsidered and
    its correction accepted: a contradicted/reopened change whose
    successor reading stands ACCEPTED. A supersession whose successor
    was never accepted earns nothing — the correction was offered,
    not established."""
    by_id = {r.id: r for r in readings}
    for change in changes:
        if change.kind not in _RECONSIDERED_KINDS:
            continue
        successor = by_id.get(change.new_reading_id or "")
        if successor is not None and successor.status == "accepted":
            return True
    return False


def _expressed_boundaries(
    user_id: str, conversation_store: ConversationStore | None
) -> list[dict[str, Any]]:
    """The visitor's own declared boundaries. Both homes exist WITHOUT
    being placed at the subject — the read says so on every item,
    because no per-subject boundary record exists in any store."""
    items: list[dict[str, Any]] = []
    try:
        for profile in _ve.list_core_profiles(user_id) or []:
            text = _sc._clean(str(profile.get("non_negotiables") or ""))
            if text:
                items.append(
                    {
                        "source": "core_profile",
                        "text": text,
                        "placement": "exists — not placed at this subject",
                    }
                )
    except Exception:  # noqa: BLE001
        logger.debug("attributed read: core profiles failed", exc_info=True)
    if conversation_store is not None:
        for key in DESIGN_STRAND_KEYS:
            try:
                rows = conversation_store.list_topic_boundaries(user_id, key)
            except Exception:  # noqa: BLE001
                continue
            for row in rows or []:
                topic = _sc._clean(str(row.get("topic") or ""))
                if topic:
                    items.append(
                        {
                            "source": "strand_topic",
                            "strand_key": key,
                            "topic": topic,
                            "placement": "binds the strand, not this subject",
                        }
                    )
    return items


def _established_boundaries(
    user_id: str,
    entity_type: str,
    entity_id: str,
    followthrough_store: FollowthroughStore | None,
) -> list[dict[str, Any]]:
    """What the visitor has actually settled about this subject: VE
    decisions keyed to it, and — for tasks, the only entity
    commitments link to — its follow-through commitments."""
    items: list[dict[str, Any]] = []
    try:
        decisions = _ve.list_decisions(
            user_id, entity_type=entity_type, entity_id=entity_id
        )
        for decision in decisions or []:
            items.append(
                {
                    "source": "decision",
                    "decision_type": str(decision.get("decision_type") or ""),
                    "created_at": str(decision.get("created_at") or ""),
                }
            )
    except Exception:  # noqa: BLE001
        logger.debug("attributed read: decisions failed", exc_info=True)
    if entity_type == "task" and followthrough_store is not None:
        try:
            commitments = followthrough_store.list_commitments_for_task(
                user_id, entity_id, status=None
            )
            for commitment in commitments or []:
                items.append(
                    {
                        "source": "commitment",
                        "text": _sc._clean(str(commitment.get("text") or "")),
                        "status": str(commitment.get("status") or ""),
                        "created_at": str(commitment.get("created_at") or ""),
                    }
                )
        except Exception:  # noqa: BLE001
            logger.debug("attributed read: commitments failed", exc_info=True)
    return items


def _enforceable_state(user_id: str, consent_connection: Any) -> dict[str, Any]:
    """The enforcement layer's state, labelled as enforcement: the
    permission home and the steward consent flags. Enforcement is not
    expression — this section never claims a boundary was stated."""
    state = {
        "permission_home_enabled": False,
        "permission_consent_given": False,
        "steward_derivation": False,
        "steward_coordination": False,
    }
    try:
        home = permission_home_state(user_id, connection=consent_connection)
        state["permission_home_enabled"] = bool(home.get("enabled"))
        state["permission_consent_given"] = bool(
            (home.get("consent") or {}).get("given")
        )
    except Exception:  # noqa: BLE001
        logger.debug("attributed read: permission home failed", exc_info=True)
    try:
        state["steward_derivation"] = bool(
            _consent.steward_consent_allowed(
                user_id, connection=consent_connection
            )
        )
        state["steward_coordination"] = bool(
            _consent.steward_coordination_allowed(
                user_id, connection=consent_connection
            )
        )
    except Exception:  # noqa: BLE001
        logger.debug("attributed read: consent flags failed", exc_info=True)
    return state


def attributed_read_for_subject(
    user_id: str,
    entity_type: str,
    entity_id: str,
    *,
    narrative_store: NarrativeStore | None = None,
    conversation_store: ConversationStore | None = None,
    followthrough_store: FollowthroughStore | None = None,
    consent_connection: Any = None,
) -> dict[str, Any]:
    """The attributed read for one caller-owned subject. Never raises;
    an unresolvable or foreign subject reads as the empty shape."""
    read = _empty_read(entity_type, entity_id)
    if not user_id or entity_type not in _sc._SUBJECT_TYPES or not entity_id:
        return read
    try:
        subject_row = _sc._resolve_subject(user_id, entity_type, entity_id)
    except Exception:  # noqa: BLE001
        subject_row = None
    if subject_row is None:
        return read
    read["resolved"] = True
    read["subject"] = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "title": _sc._clean(str(subject_row.get("title") or "")),
    }
    subject_ref = f"{entity_type}:{entity_id}"

    if conversation_store is None:
        try:
            conversation_store = ConversationStore()
        except Exception:  # noqa: BLE001
            conversation_store = None
    if followthrough_store is None:
        try:
            followthrough_store = FollowthroughStore()
        except Exception:  # noqa: BLE001
            followthrough_store = None

    read["boundaries"]["expressed"] = _expressed_boundaries(
        user_id, conversation_store
    )
    read["boundaries"]["established"] = _established_boundaries(
        user_id, entity_type, entity_id, followthrough_store
    )
    read["boundaries"]["enforceable"] = _enforceable_state(
        user_id, consent_connection
    )

    gate_open = _steward_gate_open(user_id, consent_connection)
    read["steward_gate_open"] = gate_open

    attending: dict[str, set[str]] = {}
    seat_ids = set(_bf._seat_ids())

    # Attendance by conversation — the visitor's own records, ungated;
    # the scan and the attendance test are context_preparation's.
    if conversation_store is not None:
        try:
            family = _cp._subject_family(user_id, entity_type, subject_row)
            messages = _cp._scan_conversations(conversation_store, user_id, None)
            for message in messages:
                seat = str(message.get("archetype_id") or "")
                if seat in seat_ids and _cp._attends(message, family):
                    attending.setdefault(seat, set()).add("conversation")
        except Exception:  # noqa: BLE001
            logger.debug(
                "attributed read: conversation attendance failed", exc_info=True
            )

    # The steward-gated material: proposed interpretations, the
    # Kintsugi record, and attendance by reading.
    if gate_open:
        store = narrative_store
        if store is None:
            try:
                store = NarrativeStore()
            except Exception:  # noqa: BLE001
                store = None
        if store is not None:
            threads = _standing_threads_naming(
                store, user_id, subject_ref, entity_id
            )
            try:
                all_reconsiderations = list(
                    store.reconsiderations_for(user_id) or []
                )
            except Exception:  # noqa: BLE001
                all_reconsiderations = []
            proposed: list[dict[str, Any]] = []
            kintsugi_threads: list[dict[str, Any]] = []
            restoration = False
            for thread in threads:
                readings, changes, currency = _thread_record(
                    store, user_id, thread
                )
                if _restoration_of_understanding(readings, changes):
                    restoration = True
                live_views = [
                    _reading_view(r, currency)
                    for r in readings
                    if _is_live(r, currency)
                ]
                for view in live_views:
                    if view["author"] in seat_ids:
                        attending.setdefault(view["author"], set()).add(
                            "reading"
                        )
                    if view["tensions"] or view["open_questions"]:
                        proposed.append(
                            {
                                "thread_id": thread.id,
                                "thread_title": _sc._clean(
                                    str(getattr(thread, "title", "") or "")
                                ),
                                "author_name": (
                                    _cp._seat_name(user_id, view["author"])
                                    if view["author"] in seat_ids
                                    else "the Steward"
                                ),
                                **view,
                            }
                        )
                reading_ids = {r.id for r in readings}
                kintsugi_threads.append(
                    {
                        "thread_id": thread.id,
                        "thread_title": _sc._clean(
                            str(getattr(thread, "title", "") or "")
                        ),
                        "readings": live_views,
                        "reconsiderations": [
                            {
                                "reading_id": rec.reading_id,
                                "status": rec.status,
                                "reason": _sc._clean(
                                    str(rec.reason or "")
                                )[:_TEXT_CAP],
                            }
                            for rec in all_reconsiderations
                            if rec.reading_id in reading_ids
                        ],
                    }
                )
            read["boundaries"]["proposed"] = proposed
            read["kintsugi"] = {
                "threads": kintsugi_threads,
                # The seam marker: an interpretation was reconsidered
                # and its correction accepted. It marks restored
                # UNDERSTANDING only — never repaired circumstances.
                "restoration_of_understanding": restoration,
            }

    read["guests"] = {
        "attending": [
            {
                "seat": seat,
                "seat_name": _cp._seat_name(user_id, seat),
                "via": sorted(via),
            }
            for seat, via in sorted(attending.items())
        ]
    }
    return read
