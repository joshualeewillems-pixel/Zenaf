"""Adapter registry: detection and lookup.

To add a new source: subclass SourceAdapter in a new module under
adapters/, then append an instance to ADAPTERS below. Detection is
first-match, so put more specific detectors before generic ones.
"""
from __future__ import annotations

from pathlib import Path

from .base import SourceAdapter
from .chatgpt import ChatGPTAdapter
from .claude import ClaudeAdapter
from .x_archive import XArchiveAdapter

ADAPTERS: list[SourceAdapter] = [
    ChatGPTAdapter(),
    ClaudeAdapter(),
    XArchiveAdapter(),
]


def detect_source(path: Path) -> SourceAdapter | None:
    """Return the first adapter that claims the file, or None if unknown."""
    for adapter in ADAPTERS:
        try:
            if adapter.detect(path):
                return adapter
        except Exception:
            # A broken detector must never block other adapters.
            continue
    return None


def get_adapter(source_id: str) -> SourceAdapter | None:
    """Look up an adapter by its source_id."""
    for adapter in ADAPTERS:
        if adapter.source_id == source_id:
            return adapter
    return None


def list_sources() -> list[dict[str, str]]:
    """Adapter catalog for UI display."""
    return [
        {"source_id": a.source_id, "display_name": a.display_name}
        for a in ADAPTERS
    ]
