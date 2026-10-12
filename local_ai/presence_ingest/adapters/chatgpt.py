"""ChatGPT export adapter.

Parses the official ChatGPT data export: a `conversations.json` file holding a
list of conversations. Each conversation has a `mapping` of nodes; each node
with a `message` carries `author.role` and `content.parts` (a list whose
string entries are the message text — non-string parts such as image payloads
are ignored).

Emits one PresenceEvent per user/assistant/system message. Malformed nodes
are skipped and counted, never fatal.
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
_KNOWN_ROLES = ("user", "assistant", "system", "tool")


def _to_dt(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        ts = float(str(value))
    except (TypeError, ValueError):
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


class ChatGPTAdapter(SourceAdapter):
    source_id = "chatgpt"
    display_name = "ChatGPT"

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
        return isinstance(first, dict) and isinstance(first.get("mapping"), dict)

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
            title = conv.get("title") if isinstance(conv.get("title"), str) else ""
            conv_id = conv.get("id") if isinstance(conv.get("id"), str) else ""
            mapping = conv.get("mapping")
            if not isinstance(mapping, dict):
                self.last_skipped += 1
                continue
            position = 0
            for node in mapping.values():
                event = self._node_to_event(node, path, title, conv_id, position)
                if event is None:
                    self.last_skipped += 1
                    continue
                position += 1
                yield event

    def _node_to_event(
        self,
        node: object,
        path: Path,
        title: str,
        conv_id: str,
        position: int,
    ) -> PresenceEvent | None:
        if not isinstance(node, dict):
            return None
        message = node.get("message")
        if not isinstance(message, dict):
            return None
        author = message.get("author")
        role = author.get("role") if isinstance(author, dict) else None
        if role not in _KNOWN_ROLES:
            return None
        content = message.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            return None
        texts = [p for p in parts if isinstance(p, str) and p.strip()]
        if not texts:
            return None
        text = cap_text(redact_text("\n".join(texts).strip()))
        if not text:
            return None
        return PresenceEvent(
            event_id=f"chatgpt-{uuid4().hex[:12]}",
            source=self.source_id,
            ts=_to_dt(message.get("create_time")),
            actor=str(role),
            kind="message",
            text=text,
            context={
                "conversation_title": title,
                "conversation_id": conv_id,
                "position": position,
            },
            provenance={
                "file_name": path.name,
                "adapter": self.source_id,
                "adapter_version": ADAPTER_VERSION,
            },
        )
