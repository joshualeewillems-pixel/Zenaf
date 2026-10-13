"""Data model for Agent Intake & Sorting ("The Sorting").

See docs/01_TRUTH/AGENT_INTAKE_AND_SORTING.md for the full design.

Privacy contract: ConnectedAgent.description / instructions / examples are
ALWAYS already redacted at capture (see pipeline.py). Raw user content never
enters the store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AgentKind = Literal["skill", "talent", "project", "undecided"]
AgentStatus = Literal["pending_review", "active", "archived"]

KINDS: tuple[str, ...] = ("skill", "talent", "project", "undecided")
STATUSES: tuple[str, ...] = ("pending_review", "active", "archived")


@dataclass
class StrandClaim:
    """One strand agent's case for owning the connected agent."""

    strand: str  # StrandKey from local_ai.strands
    score: float  # 0.0–1.0
    reasoning: str  # why, in plain language

    def to_dict(self) -> dict[str, Any]:
        return {"strand": self.strand, "score": self.score, "reasoning": self.reasoning}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StrandClaim":
        return cls(
            strand=str(d.get("strand", "")),
            score=float(d.get("score", 0.0)),
            reasoning=str(d.get("reasoning", "")),
        )


@dataclass
class SortResult:
    """The sorter's verdict on where a connected agent belongs.

    Training influence is multi-frame: strand_weights maps EVERY strand with a
    claim above threshold to its weight, and the agent's material routes to
    all of them. primary_strand (the max) is only the display anchor for the
    Living Tree branch — it does not gate training.
    """

    primary_strand: str  # StrandKey; display anchor (max weight), not a gate
    claims: list[StrandClaim]  # all seven, sorted by score desc
    strand_weights: dict[str, float] = field(default_factory=dict)  # strand -> 0.0-1.0, thresholded
    kind: AgentKind = "undecided"
    kind_reasoning: str = ""
    linked_projects: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0–1.0; low confidence triggers probing
    needs_probing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_strand": self.primary_strand,
            "claims": [c.to_dict() for c in self.claims],
            "strand_weights": dict(self.strand_weights),
            "kind": self.kind,
            "kind_reasoning": self.kind_reasoning,
            "linked_projects": list(self.linked_projects),
            "confidence": self.confidence,
            "needs_probing": self.needs_probing,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SortResult":
        return cls(
            primary_strand=str(d.get("primary_strand", "")),
            claims=[StrandClaim.from_dict(c) for c in (d.get("claims") or [])],
            strand_weights=dict(d.get("strand_weights") or {}),
            kind=d.get("kind", "undecided"),
            kind_reasoning=str(d.get("kind_reasoning", "")),
            linked_projects=list(d.get("linked_projects") or []),
            confidence=float(d.get("confidence", 0.0)),
            needs_probing=bool(d.get("needs_probing", False)),
        )


@dataclass
class ConnectedAgent:
    """An external AI agent the user has connected to Zenaf."""

    id: str
    name: str
    source_platform: str  # "chatgpt" | "claude" | "manual" | ...
    description: str  # redacted
    instructions: str | None  # redacted system prompt, if pasted
    examples: list[str]  # redacted
    sort: SortResult | None
    status: AgentStatus
    created_at: str  # ISO-8601
    user_id: str = ""  # owner; "" = pre-multi-user row, claimed on migration

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_platform": self.source_platform,
            "description": self.description,
            "instructions": self.instructions,
            "examples": list(self.examples),
            "sort": self.sort.to_dict() if self.sort else None,
            "status": self.status,
            "created_at": self.created_at,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConnectedAgent":
        sort_raw = d.get("sort")
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            source_platform=str(d.get("source_platform", "")),
            description=str(d.get("description", "")),
            instructions=d.get("instructions"),
            examples=list(d.get("examples") or []),
            sort=SortResult.from_dict(sort_raw) if sort_raw else None,
            status=d.get("status", "pending_review"),
            created_at=str(d.get("created_at", "")),
        )
