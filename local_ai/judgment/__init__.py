"""
Judgment Layer — shared, neutral protocol for reasoning events.

Design intent:
- Atria Core = orchestration / system coordination
- Judgment Layer = shared protocol: observations, interpretation, proposed action,
  confidence, reason codes, review/correction
- Modules (intake, vision→execution, council, etc.) use the judgment layer
- Future PersonalityProfile / JudgmentProfile = pluggable lenses that influence judgment;
  they are not the same thing as judgment itself

This module defines:
- JudgmentRecord = one structured reasoning event (minimal shape)
- Minimal in-memory store for intake domain only; no generic framework yet.

Do not fuse into Atria Core. This is infrastructure used by modules.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DOMAIN_INTAKE = "intake"


@dataclass
class JudgmentRecord:
    """
    One structured reasoning event. Canonical source of current interpretation/action:
    the latest non-superseded record for an entity is the truth; lane_override on
    IntakeItem is a convenience mirror for UI/filtering only.
    """
    id: str
    domain: str
    entity_id: str
    interpretation: dict[str, Any]   # e.g. {"category": "referral", "priority": "normal"}
    proposed_action: dict[str, Any]  # e.g. {"lane": "needs_attention"}
    confidence: float
    # Reason codes in 3 groups for trust/debugging (not raw content)
    signal_codes: list[str]       # what was observed, e.g. signal_subject_junk_hint, signal_short_body
    interpretation_codes: list[str]  # what classifier inferred, e.g. interpretation_category_referral
    policy_codes: list[str]       # why final lane/action was chosen, e.g. policy_referral_to_needs_attention
    created_at: str
    observation_ref: dict[str, Any] | None = None  # subject_preview, body_length, matched_signals; no raw content
    superseded_by: str | None = None  # id of JudgmentRecord that supersedes this one
    correction_note: str | None = None  # set when this record is a human correction override

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "domain": self.domain,
            "entity_id": self.entity_id,
            "interpretation": self.interpretation,
            "proposed_action": self.proposed_action,
            "confidence": self.confidence,
            "signal_codes": self.signal_codes,
            "interpretation_codes": self.interpretation_codes,
            "policy_codes": self.policy_codes,
            "reason_codes": self.signal_codes + self.interpretation_codes + self.policy_codes,
            "created_at": self.created_at,
            "observation_ref": self.observation_ref,
            "superseded_by": self.superseded_by,
            "correction_note": self.correction_note,
        }


# --- Minimal store (intake domain only; in-memory) ---
_records: list[JudgmentRecord] = []
_by_id: dict[str, JudgmentRecord] = {}


def add_record(record: JudgmentRecord) -> None:
    _records.append(record)
    _by_id[record.id] = record


def clear_records() -> None:
    """Clear in-memory store (e.g. before loading from persistent mirror)."""
    _records.clear()
    _by_id.clear()


def get_record(judgment_id: str) -> JudgmentRecord | None:
    return _by_id.get(judgment_id)


def get_for_entity(domain: str, entity_id: str) -> list[JudgmentRecord]:
    """All records for this entity, created_at ascending (oldest first)."""
    out = [r for r in _records if r.domain == domain and r.entity_id == entity_id]
    out.sort(key=lambda r: r.created_at)
    return out


def get_supersession_chain(judgment_id: str) -> list[JudgmentRecord]:
    """All records for the same entity as this judgment, in created_at order (original first, then corrections)."""
    current = _by_id.get(judgment_id)
    if not current:
        return []
    return get_for_entity(current.domain, current.entity_id)


def create_intake_judgment(
    entity_id: str,
    interpretation: dict[str, Any],
    proposed_action: dict[str, Any],
    confidence: float,
    *,
    signal_codes: list[str],
    interpretation_codes: list[str],
    policy_codes: list[str],
    observation_ref: dict[str, Any] | None = None,
) -> JudgmentRecord:
    """Create and store one intake judgment record. Returns the record (caller can set item.judgment_id = record.id)."""
    record = JudgmentRecord(
        id=str(uuid.uuid4()),
        domain=DOMAIN_INTAKE,
        entity_id=entity_id,
        interpretation=interpretation,
        proposed_action=proposed_action,
        confidence=confidence,
        signal_codes=signal_codes or [],
        interpretation_codes=interpretation_codes or [],
        policy_codes=policy_codes or [],
        created_at=datetime.now(timezone.utc).isoformat(),
        observation_ref=observation_ref,
    )
    add_record(record)
    return record


def create_correction_record(
    entity_id: str,
    supersedes_judgment_id: str,
    proposed_action_override: dict[str, Any],
    correction_note: str,
) -> JudgmentRecord:
    """
    Record a human correction: new JudgmentRecord that supersedes the original.
    Canonical state becomes this new record; item.judgment_id and item.lane_override are updated as a mirror.
    """
    original = _by_id.get(supersedes_judgment_id)
    interpretation = original.interpretation.copy() if original else {}
    obs_ref = dict(original.observation_ref) if original and original.observation_ref else None
    record = JudgmentRecord(
        id=str(uuid.uuid4()),
        domain=DOMAIN_INTAKE,
        entity_id=entity_id,
        interpretation=interpretation,
        proposed_action=proposed_action_override,
        confidence=1.0,  # human override
        signal_codes=[],
        interpretation_codes=["interpretation_correction"],
        policy_codes=["policy_correction_lane_override"],
        created_at=datetime.now(timezone.utc).isoformat(),
        observation_ref=obs_ref,
        superseded_by=None,
        correction_note=correction_note,
    )
    add_record(record)
    if original:
        original.superseded_by = record.id
    return record


__all__ = [
    "JudgmentRecord",
    "DOMAIN_INTAKE",
    "add_record",
    "clear_records",
    "get_record",
    "get_for_entity",
    "get_supersession_chain",
    "create_intake_judgment",
    "create_correction_record",
]
