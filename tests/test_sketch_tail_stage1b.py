"""Bonsai Bench Stage 1B — integration fixtures (scope §2.2, design §10).

Every generation is a recorded output driven through the real
``ConversationService.turn`` with an injected ``generate_fn`` — zero
live model calls. Fixtures run in the scope's order: F9 first (it pins
Talk's current empty-body behaviour before any seam code is written
against it), then F2, F4, F5, F6, F7, F8, F10, F11, F12, F16, F19, F20.
"""

from __future__ import annotations

import pytest

from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore

USER = "u-sketch"
OTHER_USER = "u-other"
CONVO = "bench-convo"
OTHER_CONVO = "other-convo"
SKEPTIC = "skeptic"
CONDUCTOR = "conductor"


@pytest.fixture()
def conv_store(tmp_path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


class RecordedGen:
    """Fake generate_fn: replays recorded voice outputs in order and
    captures every prompt. Thread-summary calls (a different
    operation) are answered with a fixed string and never consume the
    recorded voice outputs."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []  # (operation, prompt)

    def __call__(self, prompt, **kw):
        op = kw.get("operation")
        self.calls.append((op, prompt))
        if op == "conversation-thread-summary":
            return "Rolling summary of the thread."
        if self.outputs:
            return self.outputs.pop(0)
        return "Recorded reply with nothing left queued."

    def voice_prompts(self):
        return [p for op, p in self.calls if op == "voice-chat"]

    def summary_prompts(self):
        return [p for op, p in self.calls if op == "conversation-thread-summary"]


def make_service(store, gen):
    return ConversationService(store, generate_fn=gen)


def stored_messages(store, user=USER, convo=CONVO):
    return store.history(user, convo, limit=200)


def assistant_bodies(store, user=USER, convo=CONVO):
    return [m["body"] for m in stored_messages(store, user, convo) if m["role"] == "voice"]


# ---------------------------------------------------------------------------
# F9 — degenerate generation (runs FIRST, per scope §2.2)
# ---------------------------------------------------------------------------


def test_f9_current_empty_body_behaviour_pinned(conv_store):
    """Pin, before any seam code exists: a wholly empty generation is
    stored as an empty assistant message and the turn returns normally.
    No emptiness check intervenes and no fallback line is invented.
    This is Talk's current behaviour at the 1B base; Stage 1 does not
    change it."""
    gen = RecordedGen([""])
    svc = make_service(conv_store, gen)
    result = svc.turn(
        USER, SKEPTIC, "I keep going back and forth on the contract.",
        conversation_id=CONVO,
    )
    assert result.reply.reply == ""
    assert result.assistant_message["body"] == ""
    assert assistant_bodies(conv_store) == [""]
