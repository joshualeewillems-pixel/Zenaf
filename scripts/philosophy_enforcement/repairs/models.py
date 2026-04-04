from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RepairBatchResult:
    applied: bool
    touched_files: list[str] = field(default_factory=list)
    summary: str = ""
    error: str | None = None
