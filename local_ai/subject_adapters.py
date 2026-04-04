"""
TOMBSTONED — do not use.

This module previously held pure adapters from VE / content / intake row dicts
to ``SubjectSnapshot``. Use ``local_ai.judgment_substrate`` (``SubjectRef``,
``normalize_subject_ref``, ``JudgmentTrunk``, etc.) and VE row dicts directly;
there is no separate adapter package.

Git history preserves the old implementations. New code must not import from here.
"""

from __future__ import annotations

from typing import Any

__all__: list[str] = []


def __getattr__(name: str) -> Any:
    raise AttributeError(
        f"local_ai.subject_adapters.{name} was removed (tombstoned). See module docstring."
    )
