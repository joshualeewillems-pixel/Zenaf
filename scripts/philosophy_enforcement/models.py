from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FindingKind(str, Enum):
    CONFIRMED_VIOLATION = "confirmed_violation"
    HEURISTIC_SUSPICION = "heuristic_suspicion"


class RowStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    NOT_YET_AUTOMATED = "not-yet-automated"


@dataclass
class Finding:
    kind: FindingKind
    message: str
    location: str
    detail: str = ""
    checker_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "location": self.location,
            "detail": self.detail,
            "checker_id": self.checker_id,
        }


@dataclass
class CheckerRun:
    checker_id: str
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "checker_id": self.checker_id,
            "findings": [f.to_dict() for f in self.findings],
            "error": self.error,
        }


@dataclass
class PhilosophyRow:
    philosophy_id: int
    name: str
    slug: str
    status: RowStatus
    findings: list[Finding]
    suggested_next_action: str
    checker_runs: list[CheckerRun] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "philosophy_id": self.philosophy_id,
            "name": self.name,
            "slug": self.slug,
            "status": self.status.value,
            "findings": [f.to_dict() for f in self.findings],
            "suggested_next_action": self.suggested_next_action,
            "checker_runs": [c.to_dict() for c in self.checker_runs],
        }


def aggregate_status(findings: list[Finding]) -> RowStatus:
    if any(f.kind == FindingKind.CONFIRMED_VIOLATION for f in findings):
        return RowStatus.FAIL
    if any(f.kind == FindingKind.HEURISTIC_SUSPICION for f in findings):
        return RowStatus.PARTIAL
    return RowStatus.PASS
