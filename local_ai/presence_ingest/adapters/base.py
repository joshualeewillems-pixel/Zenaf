"""Source adapter contract for presence ingestion.

A SourceAdapter parses one export format (ChatGPT conversations.json, a
Claude export, an X archive, ...) into redacted PresenceEvents.

Contract:
- detect(path) -> bool: cheap, side-effect-free probe. Must not raise.
- iter_events(path) -> Iterator[PresenceEvent]: defensive parse. Real exports
  are messy; a malformed record is skipped, never fatal. Skips are counted in
  `self.last_skipped` (reset at the start of each iter_events call).
- Every emitted event's text must already be redacted (see redact.py) and
  capped at MAX_EVENT_TEXT_CHARS.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from ..schema import PresenceEvent

MAX_EVENT_TEXT_CHARS = 8000


def cap_text(text: str, limit: int = MAX_EVENT_TEXT_CHARS) -> str:
    """Truncate over-long event text with a visible marker."""
    if len(text) > limit:
        return text[:limit] + f"\n…[truncated {len(text) - limit} chars]"
    return text


class SourceAdapter(ABC):
    """Parses one export format into PresenceEvents."""

    source_id: str = ""
    display_name: str = ""

    def __init__(self) -> None:
        self.last_skipped: int = 0

    @abstractmethod
    def detect(self, path: Path) -> bool:
        """Return True if this adapter can parse the file at path."""

    @abstractmethod
    def iter_events(self, path: Path) -> Iterator["PresenceEvent"]:
        """Yield redacted PresenceEvents. Never raise on malformed records."""
