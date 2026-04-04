"""
Lane-based triage: derive operational lane from category, priority, suggested_action, and noise detection.
No heavy AI; rules only. Used by pipeline to set item.lane at ingest time only.

Lane placement is read-only and derived—there is no PATCH or client override of lane in this pass.
Noise items stay in the queue (Likely junk lane); we do not drop ingested messages.

Taxonomy note: lane ids and labels are a first-pass ontology; refine later without breaking mirror-only.
"""
from __future__ import annotations

import re
from typing import Literal

# Lane ids for UI and API
LANE_NEEDS_ATTENTION = "needs_attention"
LANE_INSURANCE = "insurance_medical"
LANE_ORDERING = "ordering_supplies"
LANE_WAITING_FYI = "waiting_fyi"
LANE_LIKELY_JUNK = "likely_junk"

LANES_ORDER: list[str] = [
    LANE_NEEDS_ATTENTION,
    LANE_INSURANCE,
    LANE_ORDERING,
    LANE_WAITING_FYI,
    LANE_LIKELY_JUNK,
]

# Human-readable labels for UI
LANE_LABELS: dict[str, str] = {
    LANE_NEEDS_ATTENTION: "Needs attention",
    LANE_INSURANCE: "Insurance / MediCal",
    LANE_ORDERING: "Ordering / Supplies",
    LANE_WAITING_FYI: "Waiting / FYI",
    LANE_LIKELY_JUNK: "Likely junk / noise",
}


def _is_noise(subject: str, summary: str, category: str, confidence: float) -> bool:
    """Rule-based noise/junk detection. Returns True if item should go to Likely junk lane."""
    subject = (subject or "").strip().lower()
    summary = (summary or "").strip().lower()
    combined = f"{subject} {summary}"

    # Subject patterns: promotional / newsletter / generic phishing
    subject_junk = re.search(
        r"\b(unsubscribe|opt[- ]?out|no longer wish|newsletter|promotion|promotional|"
        r"discount|limited time|act now|click here|verify your (?:account|email)|"
        r"free shipping|\d+% off|winner|congratulations(?!\s+(?:on|your))\b|"
        r"notification from)\b",
        subject,
        re.IGNORECASE,
    )
    if subject_junk:
        return True

    # Gmail-common: receipt, order confirmation, calendar invite, digest
    if re.search(
        r"\b(receipt|your order|order (?:confirm|shipped)|invite you to|"
        r"don'?t forget|your (?:weekly|daily) (?:digest|summary)|no reply|do not reply|noreply)\b",
        subject,
        re.IGNORECASE,
    ):
        return True
    # "Invitation:" (colon often followed by space; \b after : doesn't match)
    if re.search(r"\binvitation\s*:", subject, re.IGNORECASE):
        return True
    if re.search(r"\binvitation\s*:.*(?:calendar|event|meeting)\b", subject, re.IGNORECASE):
        return True

    # Body/summary: heavy unsubscribe / view in browser
    if re.search(r"\bunsubscribe\b", combined) and re.search(r"\bview in browser\b", combined):
        return True
    if re.search(r"image.?blocked|display images", combined):
        if len(combined) < 200:  # short and image-blocked = often marketing
            return True

    # Low-confidence other: likely noise
    if category == "other" and confidence < 0.4 and (subject or summary):
        if re.search(r"\b(sale|offer|deal|percent off|%\s*off)\b", combined):
            return True
    # Very short generic body with junk-tinged subject (avoid "Appointment reminder" etc.)
    if len(combined.strip()) < 60 and re.search(r"\b(digest|notification|your (?:weekly|daily))\b", subject, re.IGNORECASE):
        return True
    # "Reminder:" as in promo subject, not "Appointment reminder"
    if re.search(r"\breminder\s*:\s*(?:sale|offer|deal)\b", subject, re.IGNORECASE):
        return True

    return False


def derive_lane(
    category: str,
    priority: str,
    suggested_action: str,
    *,
    subject: str = "",
    summary: str = "",
    confidence: float = 0.0,
    signal_codes: list[str] | None = None,
    mailbox_context: str = "operational",
) -> str:
    """
    Derive a single lane from classification and optional noise detection.
    Returns one of LANE_* constants.
    signal_codes: optional list from classifier; signal_medical_marketing_mixed forces likely_junk.
    """
    subject = (subject or "").strip()
    summary = (summary or "").strip()
    suggested_action = (suggested_action or "").strip().lower()
    category = (category or "other").strip().lower()
    priority = (priority or "normal").strip().lower()
    mailbox_context = (mailbox_context or "operational").strip().lower()
    codes = signal_codes or []

    # Medical + marketing mixed, or referral subject + marketing body: Likely junk
    if "signal_medical_marketing_mixed" in codes or "signal_marketing_body_referral_subject" in codes:
        return LANE_LIKELY_JUNK

    # Clinical overrides junk subject: insurance/lab_result must not go to likely_junk on subject junk alone
    noise = _is_noise(subject, summary, category, confidence)
    if noise and category in ("insurance", "lab_result"):
        if category == "insurance":
            return LANE_INSURANCE
        return LANE_NEEDS_ATTENTION

    # Noise: if detected, Likely junk
    if noise:
        return LANE_LIKELY_JUNK

    # Top-level mailbox context gating
    if mailbox_context == "personal_account":
        return LANE_WAITING_FYI
    if mailbox_context == "newsletter_media":
        return LANE_WAITING_FYI
    if mailbox_context in ("marketing_promo", "advocacy_political"):
        return LANE_LIKELY_JUNK

    # Needs attention: urgent or immediate action, but only for operational context
    if mailbox_context == "operational":
        if priority == "urgent":
            return LANE_NEEDS_ATTENTION
        if "immediately" in suggested_action or "review immediately" in suggested_action:
            return LANE_NEEDS_ATTENTION
        # Referral, lab, prescription: clinical work that should be seen soon
        if category in ("referral", "lab_result", "prescription"):
            return LANE_NEEDS_ATTENTION

    # Insurance / MediCal (and records release)
    if category == "insurance":
        return LANE_INSURANCE
    if category == "records_request":
        return LANE_INSURANCE
    combined = f"{(subject or '').lower()} {(summary or '').lower()}"
    if re.search(r"\b(medical|medi.?cal|prior auth|prior authorization|eob|eligibility)\b", combined):
        return LANE_INSURANCE

    # Ordering / Supplies (don't override prescription/referral/lab)
    if category not in ("prescription", "referral", "lab_result") and re.search(
        r"\b(order|supply|supplies|shipment|reorder|formulary|inventory)\b",
        combined,
        re.IGNORECASE,
    ):
        return LANE_ORDERING
    if category not in ("prescription", "referral", "lab_result") and (
        "pharmacy" in suggested_action or "order" in suggested_action
    ):
        return LANE_ORDERING

    # Waiting / FYI: low priority, or general inquiry, or generic "review and triage"
    if priority == "low":
        return LANE_WAITING_FYI
    if category == "general_inquiry":
        return LANE_WAITING_FYI
    if "review and triage" in suggested_action and priority != "high":
        return LANE_WAITING_FYI

    # Default: high/urgent -> needs attention (operational only); else waiting/fyi
    if mailbox_context == "operational" and priority in ("high", "urgent"):
        return LANE_NEEDS_ATTENTION
    return LANE_WAITING_FYI
