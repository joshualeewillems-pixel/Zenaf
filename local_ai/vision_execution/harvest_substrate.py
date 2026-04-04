"""
Pre-ontology harvest substrate for meeting / transcript ingestion.

HarvestItems are the loss-minimizing ledger (recall-first). Downstream mapping
into ideas/initiatives/projects/tasks/etc. must treat this ledger as authoritative
for recall; consolidation happens later (canonization / user review).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

HarvestCategory = Literal[
    "deliverable",
    "research",
    "workflow",
    "content",
    "media",
    "integration",
    "monetization",
    "scheduling",
    "dependency",
    "speculative_product",
    "other",
]

VALID_HARVEST_CATEGORIES: frozenset[str] = frozenset(
    (
        "deliverable",
        "research",
        "workflow",
        "content",
        "media",
        "integration",
        "monetization",
        "scheduling",
        "dependency",
        "speculative_product",
        "other",
    )
)


@dataclass
class HarvestItem:
    id: str
    ordinal: int
    label: str
    raw_text: str
    speaker: str | None = None
    source_segment_id: str | None = None
    source_turn_index: int | None = None
    category_hint: str | None = None
    speculative: bool = False
    confidence: float | None = None
    normalized_from: str | None = None
    mapped_entity_ids: list[str] = field(default_factory=list)
    notes: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_json_dict(d: dict[str, Any]) -> HarvestItem:
        cat = d.get("category_hint")
        if cat is not None and str(cat).strip() and str(cat).strip() not in VALID_HARVEST_CATEGORIES:
            cat = "other"
        mids = d.get("mapped_entity_ids")
        if not isinstance(mids, list):
            mids = []
        return HarvestItem(
            id=str(d.get("id") or uuid.uuid4().hex[:12]),
            ordinal=int(d.get("ordinal") or 0),
            label=str(d.get("label") or "").strip(),
            raw_text=str(d.get("raw_text") or "").strip(),
            speaker=_opt_str(d.get("speaker")),
            source_segment_id=_opt_str(d.get("source_segment_id")),
            source_turn_index=_opt_int(d.get("source_turn_index")),
            category_hint=_opt_str(cat) if cat else None,
            speculative=bool(d.get("speculative")),
            confidence=_opt_float(d.get("confidence")),
            normalized_from=_opt_str(d.get("normalized_from")),
            mapped_entity_ids=[str(x) for x in mids if x is not None and str(x).strip()],
            notes=_opt_str(d.get("notes")),
        )


@dataclass
class HarvestLedger:
    transcript_id: str
    created_at: str  # ISO-8601 preferred; ms since epoch string ok for internal
    items: list[HarvestItem]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "transcript_id": self.transcript_id,
            "created_at": self.created_at,
            "items": [i.to_json_dict() for i in self.items],
        }

    @staticmethod
    def from_json_dict(d: dict[str, Any]) -> HarvestLedger:
        raw_items = d.get("items")
        items: list[HarvestItem] = []
        if isinstance(raw_items, list):
            for it in raw_items:
                if isinstance(it, dict):
                    items.append(HarvestItem.from_json_dict(it))
        return HarvestLedger(
            transcript_id=str(d.get("transcript_id") or ""),
            created_at=str(d.get("created_at") or ""),
            items=items,
        )

    @staticmethod
    def empty(transcript_id: str) -> HarvestLedger:
        return HarvestLedger(
            transcript_id=transcript_id,
            created_at=str(int(time.time() * 1000)),
            items=[],
        )


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _opt_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
