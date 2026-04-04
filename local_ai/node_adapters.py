"""
TOMBSTONED — do not use.

This module previously held pure adapters from VE / content / intake row dicts
to ``NodeSnapshot``. That experimental seam is retired; the codebase uses
``local_ai.node_substrate`` types directly where needed, plus VE persistence
(e.g. ``node_vitality``, ``council_stream_runs``) without this adapter layer.

Git history preserves the old implementations. New code must not import from here.
"""

from __future__ import annotations

from typing import Any

__all__: list[str] = []


def __getattr__(name: str) -> Any:
    raise AttributeError(
        f"local_ai.node_adapters.{name} was removed (tombstoned). See module docstring."
    )
