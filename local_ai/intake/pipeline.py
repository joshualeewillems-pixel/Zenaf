"""
Unified intake pipeline: input (email or fax) → classification → PHI detection → optional redaction → structured output.
Raw content is kept internal; only sanitized text is used for summary and may be sent to external AI later.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from . import classifier as C
from . import redaction as R

SourceKind = Literal["email", "fax"]
QueueItemStatus = Literal["new", "reviewed", "done"]
ConfidenceDisplay = Literal["high", "medium", "low"]


def _confidence_display(confidence: float) -> ConfidenceDisplay:
    if confidence >= 0.7:
        return "high"
    if confidence >= 0.4:
        return "medium"
    return "low"


@dataclass
class IntakeItem:
    """Structured output for the queue; raw content is not included."""
    id: str
    category: str
    priority: str
    summary: str
    suggested_action: str
    source: SourceKind
    has_phi: bool = False
    created_at: str = ""
    status: QueueItemStatus = "new"
    notes: str = ""
    assigned_to: str = ""
    external_id: str = ""
    subject: str = ""
    source_label: str = ""
    sender: str = ""  # Tier A: e.g. From header; stored in mirror
    # lane + confidence are derived at ingest only (read-only after add); not editable via PATCH
    lane: str = ""
    confidence: float = 0.0  # classifier rule-match strength 0–1, not certainty
    confidence_display: ConfidenceDisplay = "low"  # bucketed for UI; maps from classifier only
    # Judgment layer: one reasoning event per item; optional override when staff corrects
    judgment_id: str = ""
    lane_override: str = ""  # when set, display this instead of lane; logged as correction
    # Tier B: sanitized body for mirror only; not in to_dict so in-memory queue stays Tier A
    sanitized_body: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "category": self.category,
            "priority": self.priority,
            "summary": self.summary,
            "suggested_action": self.suggested_action,
            "source": self.source,
            "has_phi": self.has_phi,
            "created_at": self.created_at,
            "status": self.status,
            "notes": self.notes,
            "assigned_to": self.assigned_to,
            "external_id": self.external_id,
            "subject": self.subject,
            "source_label": self.source_label,
            "sender": self.sender,
            "lane": self.lane,
            "confidence": self.confidence,
            "confidence_display": self.confidence_display,
            "judgment_id": self.judgment_id,
            "lane_override": self.lane_override,
        }
        return d


def _truncate_summary(sanitized: str, max_len: int = 200) -> str:
    s = (sanitized or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3].rstrip() + "..."


def _suggested_action_from_category(category: str, priority: str) -> str:
    """Placeholder suggested actions; no automation."""
    if priority == "urgent":
        return "Review immediately"
    if category == "referral":
        return "Route to referral coordinator"
    if category == "lab_result":
        return "Route to clinical review"
    if category == "prescription":
        return "Route to pharmacy or prescriber"
    if category == "appointment":
        return "Schedule or reschedule"
    if category == "insurance":
        return "Route to billing/authorization"
    if category == "records_request":
        return "Process records release"
    return "Review and triage"


def _interpretation_codes_for(category: str, priority: str) -> list[str]:
    """Reason codes for what classifier inferred."""
    return [
        f"interpretation_category_{category}",
        f"interpretation_priority_{priority}",
    ]


def _policy_codes_for_lane(
    lane: str,
    category: str,
    priority: str,
    confidence: float,
    signal_codes: list[str] | None = None,
) -> list[str]:
    """Reason codes for why this lane/action was chosen."""
    from . import lanes as L
    codes = signal_codes or []
    if lane == L.LANE_LIKELY_JUNK:
        if "signal_medical_marketing_mixed" in codes:
            return ["policy_medical_marketing_to_junk"]
        if "signal_marketing_body_referral_subject" in codes:
            return ["policy_marketing_body_referral_subject_to_junk"]
        return ["policy_low_confidence_to_noise"] if confidence < 0.4 else ["policy_noise_detected"]
    if lane == L.LANE_NEEDS_ATTENTION:
        if priority == "urgent":
            return ["policy_urgent_to_needs_attention"]
        if category in ("referral", "lab_result", "prescription"):
            return [f"policy_{category}_to_needs_attention"]
        return ["policy_immediate_action_to_needs_attention"]
    if lane == L.LANE_INSURANCE:
        if category == "insurance":
            return ["policy_insurance_to_insurance_lane"]
        if category == "records_request":
            return ["policy_records_to_insurance"]
        return ["policy_medical_keywords_to_insurance"]
    if lane == L.LANE_ORDERING:
        return ["policy_ordering_keywords_to_ordering"]
    if lane == L.LANE_WAITING_FYI:
        if priority == "low":
            return ["policy_low_priority_to_waiting_fyi"]
        if category == "general_inquiry":
            return ["policy_general_inquiry_to_waiting_fyi"]
        return ["policy_default_to_waiting_fyi"]
    return ["policy_default_to_waiting_fyi"]


def run_pipeline(
    raw_text: str,
    source: SourceKind,
    *,
    do_redact: bool = True,
    created_at: str | None = None,
    subject: str | None = None,
) -> IntakeItem:
    """
    Run the full pipeline on raw intake text. Raw text is never stored in the returned item.
    Optional subject is used for lane derivation (e.g. email).
    """
    from datetime import datetime, timezone
    from . import lanes as L

    ts = (created_at or datetime.now(timezone.utc).isoformat())
    item_id = str(uuid.uuid4())

    # Normalize HTML so summary/preview and classification never see raw tags
    if raw_text and isinstance(raw_text, str) and "<" in raw_text and ">" in raw_text:
        from .email_ingestion import _clean_html_to_text
        raw_text = _clean_html_to_text(raw_text) or raw_text

    if not raw_text or not isinstance(raw_text, str):
        from local_ai.judgment import create_intake_judgment
        judgment = create_intake_judgment(
            entity_id=item_id,
            interpretation={"category": "other", "priority": "normal"},
            proposed_action={"lane": L.LANE_WAITING_FYI},
            confidence=0.0,
            signal_codes=[],
            interpretation_codes=["interpretation_category_other", "interpretation_priority_normal"],
            policy_codes=["policy_default_to_waiting_fyi"],
            observation_ref={"subject_preview": "", "body_length": 0, "matched_signals": []},
        )
        return IntakeItem(
            id=item_id,
            category="other",
            priority="normal",
            summary="(No content)",
            suggested_action="Review and triage",
            source=source,
            has_phi=False,
            created_at=ts,
            status="new",
            lane=L.LANE_WAITING_FYI,
            confidence=0.0,
            confidence_display="low",
            judgment_id=judgment.id,
        )

    # 1. Classify (internal; rule-based only). Pass subject so junk subject caps confidence.
    classification = C.classify(raw_text, subject=subject)
    category = classification.get("category") or "other"
    priority = classification.get("priority") or "normal"
    confidence = float(classification.get("confidence") or 0.0)

    # 2. PHI detection
    phi_findings = R.detect_phi(raw_text)
    has_phi = len(phi_findings) > 0

    # 3. Optional redaction → sanitized text
    sanitized = R.redact(raw_text) if do_redact and has_phi else raw_text

    # 4. Summary and suggested action
    summary = _truncate_summary(sanitized)
    suggested_action = _suggested_action_from_category(category, priority)

    # 5. Lane from category, priority, suggested_action, and noise (subject/summary/confidence)
    signal_codes = classification.get("signal_codes") or []
    lane = L.derive_lane(
        category,
        priority,
        suggested_action,
        subject=(subject or ""),
        summary=summary,
        confidence=confidence,
        signal_codes=signal_codes,
        mailbox_context=(classification.get("mailbox_context") or "operational"),
    )

    # 6. Judgment layer: signal/interpretation/policy codes and observation_ref (no raw content)
    interpretation_codes = _interpretation_codes_for(category, priority)
    policy_codes = _policy_codes_for_lane(lane, category, priority, confidence, signal_codes=signal_codes)
    if category in ("insurance", "lab_result") and lane != L.LANE_LIKELY_JUNK and L._is_noise(
        subject or "", summary, category, confidence
    ):
        policy_codes = list(policy_codes) + ["policy_clinical_overrides_junk_subject"]
    observation_ref = {
        "subject_preview": (subject or "")[:80],
        "body_length": len((raw_text or "").strip()),
        "matched_signals": list(signal_codes),
    }
    from local_ai.judgment import create_intake_judgment
    judgment = create_intake_judgment(
        entity_id=item_id,
        interpretation={"category": category, "priority": priority},
        proposed_action={"lane": lane},
        confidence=confidence,
        signal_codes=signal_codes,
        interpretation_codes=interpretation_codes,
        policy_codes=policy_codes,
        observation_ref=observation_ref,
    )

    item = IntakeItem(
        id=item_id,
        category=category,
        priority=priority,
        summary=summary,
        suggested_action=suggested_action,
        source=source,
        has_phi=has_phi,
        created_at=ts,
        status="new",
        lane=lane,
        confidence=confidence,
        confidence_display=_confidence_display(confidence),
        judgment_id=judgment.id,
    )
    item.sanitized_body = sanitized  # Tier B: for mirror only; not in to_dict()
    return item
