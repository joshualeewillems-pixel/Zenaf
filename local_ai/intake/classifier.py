"""
Internal classification for intake items. Rule-based only; no external AI.
Maps raw (or sanitized) text to category and priority for queue display.
Subject can be passed to cap confidence when subject looks like junk (Gmail receipts, newsletters, etc.).
"""
from __future__ import annotations

import re
from typing import Any

# Categories for clinic intake (extend as needed)
CATEGORIES = [
    "referral",
    "lab_result",
    "prescription",
    "appointment",
    "insurance",
    "records_request",
    "general_inquiry",
    "other",
]

# Priority levels for queue
PRIORITY_LEVELS = ["low", "normal", "high", "urgent"]

# Subject patterns that suggest junk/noise: cap category confidence so lane can send to Likely junk
_SUBJECT_JUNK = re.compile(
    r"\b(receipt|your order|order (?:confirm|shipped)|invitation\s*:|\binvite you to\b|"
    r"don'?t forget|reminder\s*:.*(?:sale|offer)|verify (?:your )?email|"
    r"confirm (?:your )?subscription|you have (?:a )?notification|"
    r"your (?:weekly|daily) (?:digest|summary)|no reply|do not reply|noreply@|"
    r"unsubscribe|newsletter|promotion|%\s*off|winner|congratulations\b|"
    r"limited time|act now|click here)\b",
    re.IGNORECASE,
)


def _subject_looks_junk(subject: str | None) -> bool:
    """True if subject matches common Gmail junk/receipt/newsletter patterns."""
    if not subject or not isinstance(subject, str):
        return False
    return bool(_SUBJECT_JUNK.search(subject.strip()))


def _classify_mailbox_context(subject: str, body: str) -> tuple[str, list[str]]:
    """
    Classify high-level mailbox context for gating lanes before detailed routing.
    Returns (context, signals) where context is one of:
    - 'operational'
    - 'personal_account'
    - 'newsletter_media'
    - 'marketing_promo'
    - 'advocacy_political'
    """
    subject = (subject or "").strip().lower()
    body = (body or "").strip().lower()
    combined = f"{subject} {body}"
    signals: list[str] = []

    # Newsletter / content platform
    if re.search(r"\bview (this|the) (post|email) (on the web|in your browser)\b", combined):
        signals.append("mailbox_newsletter_view_on_web")
        return "newsletter_media", signals
    if "substack.com" in combined or "via substack" in combined:
        signals.append("mailbox_newsletter_substack")
        return "newsletter_media", signals
    if re.search(r"\bnewsletter\b|\bdigest\b|\bnew episode\b|\bpodcast\b|\bsubscribe\b", combined):
        signals.append("mailbox_newsletter_generic")
        return "newsletter_media", signals

    # Personal finance / consumer account notifications
    if re.search(
        r"\b(fico|credit score|your score|statement is ready|statement available|"
        r"1099\b|w-2\b|tax form|k-1\b|bill is due|payment due|auto[- ]pay|"
        r"your account (?:has been|was) (?:debited|credited)|investment update|portfolio update)\b",
        combined,
    ):
        signals.append("mailbox_personal_finance")
        return "personal_account", signals

    # Marketing / promo / advocacy / political
    if re.search(
        r"\b(unsubscribe\b.*\bupdate preferences\b|limited time offer|flash sale|"
        r"%\s*off\b|today only\b|act now\b|campaign update\b|chip in\b|donate now\b|"
        r"sign the petition|watch the (?:forbidden|shocking) video)\b",
        combined,
    ):
        signals.append("mailbox_marketing_or_advocacy")
        # Distinguish advocacy-ish emails
        if re.search(r"\bpetition\b|campaign\b|our movement\b|pac\b", combined):
            return "advocacy_political", signals
        return "marketing_promo", signals

    return "operational", signals

def classify(text: str, *, subject: str | None = None) -> dict[str, Any]:
    """
    Classify intake text into category and priority. Uses keyword/pattern rules only.
    Returns dict with: category, priority, confidence (float 0-1), signal_codes (list of observed signals).
    """
    signal_codes: list[str] = []
    if not text or not isinstance(text, str):
        return {"category": "other", "priority": "normal", "confidence": 0.0, "signal_codes": signal_codes}

    t = text.lower().strip()
    subject_lower = (subject or "").strip().lower()
    combined = f"{subject_lower} {t}"
    mailbox_context, mailbox_signals = _classify_mailbox_context(subject_lower, t)
    signal_codes.extend(mailbox_signals)
    category = "other"
    priority = "normal"
    confidence = 0.0

    # Records-request negation: suppress classification when user explicitly denies
    records_negation = re.search(
        r"\bnot\s+(?:a\s+)?(?:medical\s+)?records?\s+request\b|"
        r"\bnot\s+requesting\s+(?:my\s+)?records?\b",
        combined,
        re.IGNORECASE,
    )
    if not records_negation and re.search(
        r"\b(record(s)?|release|chart|roi|release of information)\b.*\b(request|release)\b|"
        r"\b(request|release)\b.*\b(record(s)?|release|chart|roi|medical record)\b|"
        r"\bfax\s+record\b",
        combined,
        re.IGNORECASE,
    ):
        category = "records_request"
        confidence = 0.6
        signal_codes.append("signal_records_release_context")
    elif records_negation:
        signal_codes.append("signal_records_request_negated")
    # Category keywords (order matters: more specific first)
    if category == "other" and re.search(r"\breferral\b|refer(?:ring|red)\b|refer to\b", combined):
        category = "referral"
        confidence = 0.7
    elif category == "other" and re.search(r"\blab\b|result(s)?\b|specimen\b|cbc\b|panel\b", t):
        category = "lab_result"
        confidence = 0.7
        signal_codes.append("signal_lab_result_detected")
    elif category == "other" and re.search(r"\bprescription\b|rx\b|medication\b|refill\b", t):
        category = "prescription"
        confidence = 0.7
    elif category == "other" and re.search(r"\bappointment\b|schedule\b|reschedule\b|cancel\b", t):
        if re.search(r"\b(demo|webinar|limited time)\b", subject_lower):
            confidence = 0.3
            category = "other"
            signal_codes.append("signal_marketing_term_demo")
        else:
            category = "appointment"
            confidence = 0.7
    elif category == "other" and re.search(r"\binsurance\b|authorization\b|prior auth\b|eob\b", t):
        category = "insurance"
        confidence = 0.7
    elif category == "other" and re.search(r"\binquir(y|ies)\b|question\b|contact\b", t):
        category = "general_inquiry"
        confidence = 0.5

    # Priority: urgency keywords
    if re.search(r"\burgent\b|asap\b|stat\b|emergency\b|critical\b", t):
        priority = "urgent"
    elif re.search(r"\bpriority\b|soon\b|timely\b|important\b", t):
        priority = "high"
    elif re.search(r"\broutine\b|when convenient\b", t):
        priority = "low"

    # Medical + marketing mixed: treat as noise, not clinical prescription
    if category == "prescription" and re.search(
        r"\b(unsubscribe|save\s*\d+\s*%|sale|offer)\b",
        combined,
        re.IGNORECASE,
    ):
        category = "other"
        confidence = 0.35
        signal_codes.append("signal_medical_marketing_mixed")

    # Referral subject + marketing body only: treat as noise, not referral
    if category == "referral" and re.search(
        r"\b(act now|unsubscribe|congratulations|you've been selected|selected\s*!)\b",
        t,
        re.IGNORECASE,
    ) and len(t) < 200:
        category = "other"
        confidence = 0.35
        signal_codes.append("signal_marketing_body_referral_subject")

    if confidence == 0.0 and category == "other":
        confidence = 0.3

    # Cap confidence when subject looks like junk
    if _subject_looks_junk(subject):
        confidence = min(confidence, 0.35)
        signal_codes.append("signal_subject_junk_hint")
    # Very short body with no strong clinical signal
    if len(t) < 40 and category == "other" and confidence < 0.5:
        confidence = min(confidence, 0.35)
        signal_codes.append("signal_short_body")

    return {
        "category": category,
        "priority": priority,
        "confidence": min(1.0, confidence),
        "signal_codes": signal_codes,
        "mailbox_context": mailbox_context,
    }
