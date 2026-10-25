"""Conversation-skeleton service: turns, history, and quiet thread continuity.

``ConversationService.turn`` is the whole Phase 1 loop: persist the user
turn, build the reply through the shared voice-reply builder (never a fork),
persist the reply, and touch the active seat's thread_state.

Thread summarization is deliberately cheap: a seat's rolling summary is
refreshed only after ~20 of its turns since the last pass, via the existing
LLM path. If that pass fails, the old summary stands and the counter resets —
the raw history is still in the store, so staleness is safe and honest.
No new summarizer service is built here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from local_ai.council import capabilities as CAP
from local_ai.council.archetypes import get_archetype
from local_ai.council.naming import get_display_name
from local_ai.fellowship import events as fellowship_events

from .reply import VoiceReply, generate_voice_reply
from .store import ConversationStore

logger = logging.getLogger(__name__)

GenerateFn = Callable[..., str]

#: The fellowship event sink: called with emit_event's keyword arguments
#: once a turn's reply is fully computed and persisted (the request
#: tail). The routes wire the real emitter; tests inject fakes.
EventSink = Callable[..., None]

SUMMARY_EVERY_N_TURNS = 20
_HISTORY_FOR_REPLY = 10


def context_hint_for(context: dict[str, Any] | None) -> str | None:
    """One factual line about what the user is doing right now. No inference."""
    if not context:
        return None
    sheet_type = str(context.get("sheet_type") or "").strip()
    entity_type = str(context.get("entity_type") or "").strip()
    entity_id = str(context.get("entity_id") or "").strip()
    if not sheet_type and not entity_type:
        return None
    parts = []
    if sheet_type:
        parts.append(f"the '{sheet_type}' sheet open")
    if entity_type:
        parts.append(f"focusing on {entity_type}" + (f" ({entity_id})" if entity_id else ""))
    if not parts:
        return None
    return "the user currently has " + " and ".join(parts) + "."


@dataclass
class TurnResult:
    user_message: dict[str, Any]
    assistant_message: dict[str, Any]
    reply: VoiceReply
    conversation_id: str


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        generate_fn: GenerateFn | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.store = store
        self._generate_fn = generate_fn
        self._event_sink = event_sink

    # -- the turn loop ----------------------------------------------------------

    def turn(
        self,
        user_id: str,
        archetype_id: str,
        message: str,
        conversation_id: str = "skeleton",
        mode: str = "trained",
        question: bool = False,
        context: dict[str, Any] | None = None,
    ) -> TurnResult:
        """One persistent-conversation turn. Raises ValueError on bad input."""
        arch_id = (archetype_id or "").strip().lower()
        if get_archetype(arch_id) is None:
            raise ValueError(f"Unknown voice: {archetype_id!r}")
        if not (message or "").strip() and not question:
            raise ValueError("Message is empty.")

        self.store.ensure_conversation(user_id, conversation_id)
        context = dict(context or {})

        user_msg = self.store.append_message(
            user_id, conversation_id, arch_id, "user", message,
            mode=mode, context=context,
        )

        recent = self.store.history(user_id, conversation_id, limit=_HISTORY_FOR_REPLY + 1)
        # recent includes the just-stored user turn; the reply builder appends
        # the new user message itself, so hand it everything before it.
        history_turns = [
            {"role": m["role"], "content": m["body"]} for m in recent[:-1]
        ][-_HISTORY_FOR_REPLY:]

        thread = self.store.get_thread_state(user_id, conversation_id, arch_id)
        thread_summary = thread["summary"] or None

        voice_reply = generate_voice_reply(
            user_id,
            arch_id,
            message,
            history_turns,
            mode=mode,
            question=question,
            context_hint=context_hint_for(context),
            thread_summary=thread_summary,
            generate_fn=self._generate_fn,
            # Continuation background knowledge (demonstration spec
            # §6): this seat's slice, resolved from the visitor's
            # actual state — no intention line, no offer instruction.
            capability_context=CAP.continuation_block(
                arch_id, CAP.resolve_visitor_state(user_id)),
        )

        assistant_msg = self.store.append_message(
            user_id,
            conversation_id,
            arch_id,
            "voice",
            voice_reply.reply,
            mode=voice_reply.mode_used,
            context=context,
        )

        self._touch_thread(user_id, conversation_id, arch_id, voice_reply.display_name)

        result = TurnResult(
            user_message=user_msg,
            assistant_message=assistant_msg,
            reply=voice_reply,
            conversation_id=conversation_id,
        )
        # Fellowship Runtime P1: the turn is a shared-reality event.
        # Emitted only now — reply computed and persisted — and the
        # sink itself only *schedules* the slow path (two-speed law),
        # so nothing here can delay or break the reply. Derivation
        # failures are the sink's problem, never the turn's.
        self._emit_turn_event(user_id, conversation_id, arch_id, message, user_msg)
        return result

    def _emit_turn_event(
        self,
        user_id: str,
        conversation_id: str,
        arch_id: str,
        message: str,
        user_msg: dict[str, Any],
    ) -> None:
        """Record this turn as a fellowship event via the wired sink.

        Fully guarded (a turn must succeed even if the event layer is
        down) and skipped for empty user messages (question-mode
        turns, where the seat speaks first — no user words, no event).
        """
        if self._event_sink is None or not (message or "").strip():
            return
        try:
            self._event_sink(
                kind=fellowship_events.CONVERSATION_TURN,
                user_id=user_id,
                entity_type="conversation",
                entity_id=conversation_id,
                evidence_text=message,
                summary=f"Conversation turn with the {arch_id} voice.",
                payload={
                    "archetype_id": arch_id,
                    "message_id": user_msg.get("id"),
                },
            )
        except Exception:
            logger.exception("fellowship: conversation-turn event failed")

    def history(
        self, user_id: str, conversation_id: str = "skeleton", limit: int = 50
    ) -> list[dict[str, Any]]:
        self.store.ensure_conversation(user_id, conversation_id)
        return self.store.history(user_id, conversation_id, limit=limit)

    def thread_state(
        self, user_id: str, conversation_id: str, archetype_id: str
    ) -> dict[str, Any]:
        return self.store.get_thread_state(user_id, conversation_id, archetype_id)

    # -- quiet continuity ---------------------------------------------------------

    def _touch_thread(
        self, user_id: str, conversation_id: str, archetype_id: str, display_name: str
    ) -> None:
        """Bump the seat's thread; refresh its rolling summary every N turns."""
        state = self.store.update_thread_state(
            user_id, conversation_id, archetype_id, increment=1
        )
        if state["messages_since_summary"] < SUMMARY_EVERY_N_TURNS:
            return
        self._refresh_thread_summary(user_id, conversation_id, archetype_id, display_name, state)

    def _refresh_thread_summary(
        self,
        user_id: str,
        conversation_id: str,
        archetype_id: str,
        display_name: str,
        state: dict[str, Any],
    ) -> None:
        """Best-effort rolling summary of this seat's recent turns."""
        try:
            recent = self.store.history(user_id, conversation_id, limit=60)
            seat_turns = [m for m in recent if m["archetype_id"] == archetype_id]
            seat_turns = seat_turns[-SUMMARY_EVERY_N_TURNS * 2:]
            if not seat_turns:
                self.store.update_thread_state(
                    user_id, conversation_id, archetype_id, reset_counter=True
                )
                return
            lines = []
            for m in seat_turns:
                who = "User" if m["role"] == "user" else display_name
                lines.append(f"{who}: {(m['body'] or '')[:600]}")
            prompt = (
                f"Summarize this ongoing one-on-one thread between the user and "
                f"{display_name} (a council voice). Previous summary, if any:\n"
                f"{(state['summary'] or '(none)')[:800]}\n\n"
                f"Recent turns:\n" + "\n".join(lines) + "\n\n"
                "Write a compact rolling summary (under 150 words): open threads, "
                "decisions made, the user's current stance, tone. Plain sentences, "
                "no bullet headers, no advice."
            )
            gen = self._generate_fn
            if gen is None:
                from local_ai.agent_intake.llm_keys import generate as _gen

                gen = _gen
            summary = gen(
                prompt, provider_id="meta", user_id=user_id,
                operation="conversation-thread-summary", timeout=60,
            ).strip()
            if summary:
                self.store.update_thread_state(
                    user_id, conversation_id, archetype_id,
                    summary=summary, reset_counter=True,
                )
            else:
                self.store.update_thread_state(
                    user_id, conversation_id, archetype_id, reset_counter=True
                )
        except Exception:
            # The raw history remains the source of truth; a stale (or empty)
            # summary is safe. Reset the counter so a broken LLM doesn't get
            # retried on every turn.
            try:
                self.store.update_thread_state(
                    user_id, conversation_id, archetype_id, reset_counter=True
                )
            except Exception:
                pass
