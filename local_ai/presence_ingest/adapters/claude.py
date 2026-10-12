"""Claude export adapter.

Parses the official Claude data export: a `conversations.json` file holding a
list of conversations. Each conversation has a `name` and a `chat_messages`
list of {"sender": "human"|"assistant", "text": ..., "created_at": ...}.
Tolerates the `conversation_messages` key variant seen in some exports.

sender "human" maps to actor "user". Malformed messages are skipped and
counted, never fatal.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from ..redact import redact_text
from ..schema import PresenceEvent
from .base import SourceAdapter, cap_text

ADAPTER_VERSION = "1.0.0"
_SENDER_TO_ACTOR = {"human": "user", "assistant": "assistant"}
_MESSAGE_KEYS = ("chat_messages", "conversation_messages")


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    try:
        # Python 3.11+ fromisoformat handles "Z"; normalize for safety.
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class ClaudeAdapter(SourceAdapter):
    source_id = "claude"
    display_name = "Claude"

    def detect(self, path: Path) -> bool:
        if path.suffix.lower() != ".json":
            return False
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False
        if not isinstance(data, list) or not data:
            return False
        first = data[0]
        if not isinstance(first, dict):
            return False
        # Distinguish from ChatGPT exports: Claude conversations carry message
        # lists, not a node mapping.
        if isinstance(first.get("mapping"), dict):
            return False
        return any(isinstance(first.get(k), list) for k in _MESSAGE_KEYS)

    def iter_events(self, path: Path) -> Iterator[PresenceEvent]:
        self.last_skipped = 0
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        if not isinstance(data, list):
            return
        for conv in data:
            if not isinstance(conv, dict):
                self.last_skipped += 1
                continue
            name = conv.get("name") if isinstance(conv.get("name"), str) else ""
            conv_id = conv.get("uuid") if isinstance(conv.get("uuid"), str) else ""
            messages: list = []
            for key in _MESSAGE_KEYS:
                msgs = conv.get(key)
                if isinstance(msgs, list):
                    messages = msgs
                    break
            if not messages:
                self.last_skipped += 1
                continue
            for position, msg in enumerate(messages):
                event = self._msg_to_event(msg, path, name, conv_id, position)
                if event is None:
                    self.last_skipped += 1
                    continue
                yield event

    def _msg_to_event(
        self,
        msg: object,
        path: Path,
        name: str,
        conv_id: str,
        position: int,
    ) -> PresenceEvent | None:
        if not isinstance(msg, dict):
            return None
        actor = _SENDER_TO_ACTOR.get(msg.get("sender"))
        if actor is None:
            return None
        raw_text = msg.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            return None
        text = cap_text(redact_text(raw_text.strip()))
        if not text:
            return None
        return PresenceEvent(
            event_id=f"claude-{uuid4().hex[:12]}",
            source=self.source_id,
            ts=_parse_iso(msg.get("created_at")),
            actor=actor,
            kind="message",
            text=text,
            context={
                "conversation_title": name,
                "conversation_id": conv_id,
                "position": position,
            },
            provenance={
                "file_name": path.name,
                "adapter": self.source_id,
                "adapter_version": ADAPTER_VERSION,
            },
        )
