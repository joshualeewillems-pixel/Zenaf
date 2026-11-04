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
from local_ai.vision_execution import obligations as _obligations

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


#: Capability C S5 — join-context caps. The block is bounded to the
#: justifying exchange by construction (the stored evidence), and
#: these caps keep a hostile or oversized stored record from
#: expanding the prompt: same 2000-char line cap as history lines,
#: at most 10 stored context entries.
_JOIN_LINE_CAP = 2000
_JOIN_CONTEXT_ENTRIES_CAP = 10


def build_invitation_context(invitation: dict[str, Any] | None) -> str | None:
    """Render one pending invitation as a first-joining-turn block.

    Verdict Q5: verbatim evidence plus explicitly attributed
    interpretation. The reason is labeled as the inviting selection's
    reading — an interpretation, never an established fact — and the
    exchange lines are the stored verbatim record. Returns None for
    a missing invitation or an empty reason (the store requires a
    reason, so None here means "nothing to join on").

    The responding seat is labeled by its stock display name (the
    S0 history convention for seats without a visitor-chosen name
    in this path); the label never comes from the current seat.
    Stored context entries, when present, render verbatim and
    bounded; non-string entries without a readable content field
    are skipped rather than stringified.
    """
    if not invitation:
        return None
    reason = (invitation.get("reason") or "").strip()
    if not reason:
        return None
    evidence = invitation.get("evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    lines = [
        "Invitation context — this turn joins you to a conversation "
        "you were invited into.",
        "The inviting selection's reading (an interpretation, not an "
        f"established fact): {reason}",
    ]
    user_message = (evidence.get("user_message") or "").strip()
    assistant_reply = (evidence.get("assistant_reply") or "").strip()
    responding_seat = (evidence.get("responding_seat") or "").strip().lower()
    context_entries = evidence.get("context") or []
    if user_message or assistant_reply or context_entries:
        lines.append("The exchange that justified the invitation (verbatim):")
        if user_message:
            lines.append(f"User: {user_message[:_JOIN_LINE_CAP]}")
        if assistant_reply:
            arch = get_archetype(responding_seat) if responding_seat else None
            label = arch.display_name if arch is not None else (responding_seat or "Voice")
            lines.append(f"{label}: {assistant_reply[:_JOIN_LINE_CAP]}")
        if isinstance(context_entries, list):
            for entry in context_entries[:_JOIN_CONTEXT_ENTRIES_CAP]:
                if isinstance(entry, str) and entry.strip():
                    lines.append(entry.strip()[:_JOIN_LINE_CAP])
                elif isinstance(entry, dict):
                    content = (entry.get("content") or "").strip()
                    if content:
                        role = (entry.get("role") or "Context").strip() or "Context"
                        lines.append(f"{role}: {content[:_JOIN_LINE_CAP]}")
    else:
        lines.append("No justifying exchange was stored with this invitation.")
    return "\n".join(lines)


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
        steward_context_provider: Callable[..., str | None] | None = None,
    ) -> None:
        self.store = store
        self._generate_fn = generate_fn
        self._event_sink = event_sink
        # Phase 2 (Narrative Steward, Weaver-first): an optional
        # provider of prepared steward context, called ONLY for the
        # Weaver (archetype "conductor"). Every other seat's path is
        # byte-identical with or without it: the provider is never
        # consulted, and extra_instructions stays None. The block
        # itself is advisory — the Weaver's existing generation
        # responds to it or sets it aside; availability adds zero
        # generations. Any provider failure degrades to no context,
        # never a broken turn.
        self._steward_context_provider = steward_context_provider

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
        # Capability C S0: history_turns carry archetype_id so the reply
        # builder can label voice turns by their ACTUAL speaker. The
        # window is unchanged (last 10) — attribution, not more context.
        history_turns = [
            {"role": m["role"], "content": m["body"], "archetype_id": m.get("archetype_id")}
            for m in recent[:-1]
        ][-_HISTORY_FOR_REPLY:]

        thread = self.store.get_thread_state(user_id, conversation_id, arch_id)
        thread_summary = thread["summary"] or None

        steward_block = None
        if arch_id == "conductor" and self._steward_context_provider is not None:
            try:
                steward_block = self._steward_context_provider(
                    user_id, message, history_turns
                )
            except Exception:
                logger.exception(
                    "steward: prepared context failed; continuing without it"
                )
                steward_block = None

        # Firebrand task context (trial, champion-only): server-side,
        # from the caller's own scoped tasks — the client cannot inject
        # or forge obligations. A failed read yields the failure notice
        # block, never an empty list; other seats get no block.
        obligation_context = None
        if arch_id == "champion":
            obligation_context, _obligation_status = (
                _obligations.build_obligation_context(user_id)
            )

        # Capability C S5: first joining turn only. If a pending,
        # unexpired invitation exists for this (user, conversation,
        # seat) at turn start, the turn carries its evidence +
        # attributed reason as a bounded context block (same pattern
        # as obligation_context: a delimited section, absent
        # otherwise). The S1 accept wiring below consumes the
        # invitation when the turn completes, so later turns use
        # normal continuity and never see the block again. Guarded:
        # a failed lookup must never break the turn.
        invitation_context = None
        try:
            pending = self.store.list_pending_invitations(user_id, conversation_id)
            joined = [
                inv
                for inv in pending
                if (inv.get("seat") or "").strip().lower() == arch_id
            ]
            if joined:
                invitation_context = build_invitation_context(joined[0])
        except Exception:
            logger.exception("invitations: join context lookup failed")
            invitation_context = None

        voice_reply = generate_voice_reply(
            user_id,
            arch_id,
            message,
            history_turns,
            mode=mode,
            question=question,
            context_hint=context_hint_for(context),
            obligation_context=obligation_context,
            invitation_context=invitation_context,
            thread_summary=thread_summary,
            generate_fn=self._generate_fn,
            # Phase 2 steward context (Weaver only): prepared
            # context travels as extra_instructions inside the
            # existing prompt budget — no new generation, no
            # second call. Other seats never receive it.
            extra_instructions=steward_block,
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

        # Capability C S1: joining is a sent turn, never a tap. A
        # completed turn addressed to an invited seat accepts that
        # seat's pending invitation(s) for this conversation, recorded
        # against the user message. Bookkeeping only — a failure here
        # must never break the turn, and with no invitation pending
        # this is a no-op, so one-on-one flows are unaffected.
        # Question-mode turns count: the user sent a turn to the seat.
        try:
            self.store.accept_pending_for_seat(
                user_id, conversation_id, arch_id, user_msg["id"]
            )
        except Exception:
            logger.exception("invitations: accept-on-turn failed")

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

    def history_before(
        self,
        user_id: str,
        conversation_id: str = "skeleton",
        before_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        # No ensure_conversation here: a cursor page is only meaningful
        # for an existing thread, and an unknown cursor must stay an
        # empty page (fail-closed) rather than creating a row.
        return self.store.history_before(
            user_id, conversation_id, before_id=before_id, limit=limit
        )

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
