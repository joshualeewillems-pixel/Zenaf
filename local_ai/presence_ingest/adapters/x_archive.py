"""X (Twitter) archive adapter — proves the "any digital presence" extensibility.

Parses the official X data archive `tweets.js`, which is JavaScript, not pure
JSON:
    window.YTD.tweets.part0 = [ {"tweet": {"id_str": ..., "full_text": ...,
                                 "created_at": ...}}, ... ]

The account owner is always the author, so every event has actor "user" and
kind "post". Malformed entries are skipped and counted, never fatal.
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


def _extract_array(text: str) -> list | None:
    """Pull the JSON array out of the `window.YTD.tweets.part0 = [...]` wrapper."""
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except Exception:
        return None
    return data if isinstance(data, list) else None


def _parse_tweet_time(value: object) -> datetime | None:
    # e.g. "Wed Oct 11 20:19:24 +0000 2023"
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.strptime(value.strip(), "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


class XArchiveAdapter(SourceAdapter):
    source_id = "x"
    display_name = "X (Twitter)"

    def detect(self, path: Path) -> bool:
        if path.suffix.lower() != ".js":
            return False
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:300]
        except Exception:
            return False
        return "window.YTD.tweets" in head

    def iter_events(self, path: Path) -> Iterator[PresenceEvent]:
        self.last_skipped = 0
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        entries = _extract_array(raw)
        if not entries:
            return
        for entry in entries:
            event = self._entry_to_event(entry, path)
            if event is None:
                self.last_skipped += 1
                continue
            yield event

    def _entry_to_event(self, entry: object, path: Path) -> PresenceEvent | None:
        if not isinstance(entry, dict):
            return None
        tweet = entry.get("tweet")
        if not isinstance(tweet, dict):
            return None
        full_text = tweet.get("full_text")
        if not isinstance(full_text, str) or not full_text.strip():
            return None
        text = cap_text(redact_text(full_text.strip()))
        if not text:
            return None
        tweet_id = tweet.get("id_str") if isinstance(tweet.get("id_str"), str) else ""
        return PresenceEvent(
            event_id=f"x-{tweet_id}" if tweet_id else f"x-{uuid4().hex[:12]}",
            source=self.source_id,
            ts=_parse_tweet_time(tweet.get("created_at")),
            actor="user",  # the archive owner is always the author
            kind="post",
            text=text,
            context={"tweet_id": tweet_id},
            provenance={
                "file_name": path.name,
                "adapter": self.source_id,
                "adapter_version": ADAPTER_VERSION,
            },
        )
