"""V1 — the noting capture writer: encounter scope, held material,
seat-authored readings (narrative architecture governing §§2, 4, 6).

The ConversationService seam hands this writer the validated notes
parsed from a capture-enabled seat's reply (citations already
validated against the conversation's own messages by the service).
The writer is seat-general Fellowship infrastructure: it serves any
archetype id it is handed and contains no seat-specific logic.

What a capture turn writes, in order:

- **Encounter scope.** The encounter arc is an ordinary narrative
  thread (origin ``steward_proposal`` — the closed THREAD_ORIGINS
  vocabulary gains no new member), marked as encounter scope in
  ``encounter_scopes`` with the Talk keying of governing §4: the
  container key (user, conversation, seat) plus the message span.
  An encounter opens at the feed's first write for its container key
  when no open encounter exists; its span start is that turn's user
  message. ``close_encounter`` fixes the span end (production
  close-out is a later increment).
- **Verbatim capture by reference.** The visitor's turn is cited as
  Tier E evidence on the encounter thread via the existing evidence
  machinery: the turn's ``conversation_turn`` fellowship event —
  whose evidence text is the visitor's verbatim message and whose
  payload carries the message id — addressed as
  ``SourceRef(kind="event", evidence_kind="quote")``, exactly as
  derivation and candidate capture already cite it. The closed
  ref-kind tables in refs.py are untouched: no kind addresses a raw
  conversation message, and the conversation-turn event is the
  record that does.
- **Held material.** Every note lands as a proposal in
  ``held_notes`` — encounter-scope, held pending comparison,
  hard-bounded by :data:`HELD_NOTE_BOUND_DAYS`. Reads exclude
  past-bound rows and the store's expiry function flips them to
  expired; expiry is not behind a flag.
- **Seat-authored readings.** A recognition note additionally writes
  a ThreadReading on the encounter thread, author = the seat's
  archetype id, standing ``proposed``, content = the seat's
  recognition statement in its own words. A later recognition
  supersedes an earlier one through the existing change machinery
  (a ``ThreadChange`` in the derivation-canonical order — change
  first, because the anti-manufacture invariant requires the change
  to carry newly attached evidence; then the new reading). Readings
  are never edited.
- **Objections.** The cited visitor message's conversation-turn
  event is attached to the thread as Tier E evidence, able to
  ground changes per the existing rules.

Fail-closed throughout: an unresolvable event citation drops that
note's evidence attach (the held record still names the cited
message id); a recognition with no evidence available on the thread
lands as held material only — no reading is ever fabricated without
evidence (store Invariant 1). Every failure is the caller's to
guard: this writer may raise on store errors, and the service seam
treats any failure as "no capture this turn", never a broken turn.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from local_ai.narrative.refs import SourceRef
from local_ai.narrative.store import NarrativeStore

logger = logging.getLogger(__name__)

#: The §6 holding bound: held material is compared at the first
#: comparison opportunity and in no case held past this bound;
#: material that reaches it unexamined expires unexamined. Seven
#: days matches the slice's encounter-scale cadence (a sitting's
#: material is either taken up within the week or honestly gone);
#: the value is an implementation detail — its existence in the
#: data path is the design point.
HELD_NOTE_BOUND_DAYS = 7

#: How the writer resolves a cited visitor message to the id of its
#: conversation_turn fellowship event. Signature:
#: (user_id, conversation_id, message_id) -> event id | None.
EventResolver = Callable[[str, str, str], str | None]


def resolve_turn_event_id(
    user_id: str, conversation_id: str, message_id: str
) -> str | None:
    """Find a visitor message's conversation_turn event id.

    Scans the activity log (newest first) for the fellowship
    ``conversation_turn`` event whose payload names this message —
    the event the conversation service emitted for that turn, whose
    evidence text is the message verbatim. Fail-closed: any read
    failure or non-match returns None and the caller drops the
    evidence attach for that citation only.
    """
    if not (user_id and conversation_id and message_id):
        return None
    try:
        from local_ai import activity as _activity

        events = _activity.get_recent_activity(limit=100_000)
    except Exception:
        logger.exception("noting: activity log scan failed")
        return None
    for event in events:
        if getattr(event, "source", "") != "fellowship":
            continue
        if getattr(event, "type", "") != "conversation_turn":
            continue
        if getattr(event, "actor", "") != user_id:
            continue
        if getattr(event, "entity_id", "") != conversation_id:
            continue
        try:
            detail = json.loads(getattr(event, "detail", "") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        payload = detail.get("payload") or {}
        if payload.get("message_id") == message_id:
            return getattr(event, "id", "") or None
    return None


class NotingCaptureWriter:
    """Writes one capture-enabled turn's notes into the steward store."""

    def __init__(
        self,
        store: NarrativeStore | None = None,
        *,
        event_resolver: EventResolver | None = None,
    ) -> None:
        self._store = store
        self._event_resolver = event_resolver or resolve_turn_event_id

    def _narrative_store(self) -> NarrativeStore:
        if self._store is None:
            self._store = NarrativeStore()
        return self._store

    # -- the per-turn capture ---------------------------------------------------

    def capture_turn(
        self,
        *,
        user_id: str,
        conversation_id: str,
        archetype_id: str,
        notes: list[dict[str, Any]],
        user_message_id: str,
        reply_message_id: str,
        turn_event_id: str | None,
    ) -> dict[str, Any]:
        """Land one turn's validated notes. ``notes`` are plain dicts
        ({"kind", "statement", "message_id"}) — citation validity was
        established by the service against the conversation store;
        event resolution and all steward writes happen here."""
        store = self._narrative_store()
        summary: dict[str, Any] = {
            "encounter_thread_id": None,
            "held_note_ids": [],
            "reading_ids": [],
            "change_ids": [],
            "evidence_attached": 0,
        }
        turn_ref = (
            SourceRef(kind="event", ref_id=turn_event_id, evidence_kind="quote")
            if turn_event_id
            else None
        )
        if not notes and turn_ref is None:
            return summary

        scope = store.open_encounter_for(user_id, conversation_id, archetype_id)
        if scope is None:
            thread = store.create_thread(
                user_id,
                origin="steward_proposal",
                title=f"Encounter — {archetype_id} — {conversation_id}",
                evidence_refs=[turn_ref] if turn_ref is not None else (),
            )
            scope = store.open_encounter_scope(
                user_id,
                thread.id,
                conversation_id=conversation_id,
                archetype_id=archetype_id,
                span_start_message_id=user_message_id,
            )
        thread_id = scope["thread_id"]
        summary["encounter_thread_id"] = thread_id

        attached: set[tuple[str, str]] = {
            (row.ref_kind, row.ref_id)
            for row in store.evidence_for(user_id, thread_id)
        }

        def attach(ref: SourceRef) -> bool:
            key = (ref.kind, ref.ref_id)
            if key in attached:
                return False
            store.add_evidence(user_id, thread_id, ref)
            attached.add(key)
            summary["evidence_attached"] += 1
            return True

        def latest_ref() -> SourceRef | None:
            rows = store.evidence_for(user_id, thread_id)
            if not rows:
                return None
            row = rows[-1]
            return SourceRef(
                kind=row.ref_kind,
                ref_id=row.ref_id,
                evidence_kind=row.evidence_kind or "quote",
            )

        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=HELD_NOTE_BOUND_DAYS)
        ).isoformat()

        for note in notes:
            kind = note.get("kind")
            if kind == "objection":
                cited = str(note.get("message_id") or "")
                event_id = self._event_resolver(
                    user_id, conversation_id, cited
                )
                ref = (
                    SourceRef(
                        kind="event", ref_id=event_id, evidence_kind="quote"
                    )
                    if event_id
                    else None
                )
                if ref is not None:
                    attach(ref)
                held = store.add_held_note(
                    user_id,
                    thread_id,
                    conversation_id=conversation_id,
                    archetype_id=archetype_id,
                    kind="objection",
                    cited_message_id=cited or None,
                    evidence_ref=ref,
                    source_user_message_id=user_message_id,
                    source_reply_message_id=reply_message_id,
                    author=archetype_id,
                    expires_at=expires_at,
                )
                summary["held_note_ids"].append(held["id"])
            elif kind == "recognition":
                statement = str(note.get("statement") or "")
                evidence = turn_ref or latest_ref()
                prior = self._latest_recognition_reading(
                    store, user_id, thread_id, archetype_id
                )
                # Supersession through the change machinery, in the
                # derivation-canonical order: the change lands first
                # because its anti-manufacture invariant requires a
                # ref newly attached by the change itself — this
                # turn's visitor-turn event, when it is new here.
                if (
                    prior is not None
                    and turn_ref is not None
                    and (turn_ref.kind, turn_ref.ref_id) not in attached
                ):
                    change = store.record_change(
                        user_id,
                        thread_id,
                        kind="extended",
                        evidence_refs=[turn_ref],
                        prior_reading_id=prior.id,
                    )
                    attached.add((turn_ref.kind, turn_ref.ref_id))
                    summary["change_ids"].append(change.id)
                    evidence = turn_ref
                reading_id = None
                if evidence is not None:
                    reading = store.propose_reading(
                        user_id,
                        thread_id,
                        author=archetype_id,
                        reading={"recognition": statement},
                        evidence_refs=[evidence],
                    )
                    reading_id = reading.id
                    summary["reading_ids"].append(reading.id)
                    attached.add((evidence.kind, evidence.ref_id))
                held = store.add_held_note(
                    user_id,
                    thread_id,
                    conversation_id=conversation_id,
                    archetype_id=archetype_id,
                    kind="recognition",
                    statement=statement,
                    evidence_ref=evidence,
                    source_user_message_id=user_message_id,
                    source_reply_message_id=reply_message_id,
                    author=archetype_id,
                    reading_id=reading_id,
                    expires_at=expires_at,
                )
                summary["held_note_ids"].append(held["id"])

        # Verbatim capture by reference: this turn's visitor message
        # is encounter evidence whether or not the seat noted
        # anything — the arc's evidence layer is the encounter's own
        # words, cited, never copied.
        if turn_ref is not None:
            attach(turn_ref)
        return summary

    @staticmethod
    def _latest_recognition_reading(store, user_id, thread_id, archetype_id):
        prior = None
        for reading in store.readings_for(user_id, thread_id):
            if reading.author != archetype_id:
                continue
            if reading.status not in ("proposed", "accepted"):
                continue
            if "recognition" in (reading.reading or {}):
                prior = reading
        return prior

    # -- encounter close (explicit; production close-out is V2) -----------------

    def close_encounter(
        self,
        *,
        user_id: str,
        conversation_id: str,
        archetype_id: str,
        span_end_message_id: str,
    ) -> dict[str, Any] | None:
        """Fix the open encounter's span end for a container key."""
        store = self._narrative_store()
        scope = store.open_encounter_for(user_id, conversation_id, archetype_id)
        if scope is None:
            return None
        return store.close_encounter_scope(
            user_id, scope["thread_id"], span_end_message_id=span_end_message_id
        )


def default_noting_writer() -> NotingCaptureWriter:
    """The production writer: a lazily-built NarrativeStore (the
    weaver_context_provider pattern — constructing the service never
    touches the narrative DB; the store opens on first capture)."""
    return NotingCaptureWriter()


__all__ = [
    "HELD_NOTE_BOUND_DAYS",
    "NotingCaptureWriter",
    "default_noting_writer",
    "resolve_turn_event_id",
]
