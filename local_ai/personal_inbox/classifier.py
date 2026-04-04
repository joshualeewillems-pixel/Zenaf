"""
Personal inbox classifier: coarse mailbox-context categories for cleanup.

Categories:
- junk_promo
- newsletter_media
- account_fyi
- transactional_action
- important_personal
- review_manually
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


PersonalContext = str


def classify_personal_message(
    subject: str,
    body: str,
    *,
    sender: str | None = None,
) -> Dict[str, Any]:
    """
    Classify a personal-inbox message into a coarse context category.
    Returns {context, signals}.
    """
    subj = (subject or "").strip().lower()
    txt = (body or "").strip().lower()
    combined = f"{subj} {txt}"
    signals: List[str] = []

    # 1. Newsletter / media
    if re.search(r"\bview (this|the) (post|email) (on the web|in your browser)\b", combined):
        signals.append("pi_newsletter_view_on_web")
        return {"context": "newsletter_media", "signals": signals}
    if "substack.com" in combined or "via substack" in combined:
        signals.append("pi_newsletter_substack")
        return {"context": "newsletter_media", "signals": signals}
    if re.search(r"\bnewsletter\b|\bdigest\b|\bnew episode\b|\bpodcast\b", combined):
        signals.append("pi_newsletter_generic")
        return {"context": "newsletter_media", "signals": signals}

    # 2. Marketing / promo / advocacy (likely junk)
    if re.search(
        r"\b(unsubscribe\b.*\bupdate preferences\b|"
        r"limited time offer|flash sale|today only|act now\b|"
        r"%\s*off\b|coupon\b|promo code\b|"
        r"campaign update\b|chip in\b|donate now\b|"
        r"sign the petition|watch the (?:forbidden|shocking) video)\b",
        combined,
    ):
        signals.append("pi_marketing_or_advocacy")
        if re.search(r"\bpetition\b|campaign\b|our movement\b|pac\b", combined):
            return {"context": "junk_promo", "signals": signals}
        return {"context": "junk_promo", "signals": signals}

    # 3. Account FYI vs transactional action (personal finance / services)
    account_keywords = re.search(
        r"\b(fico|credit score|statement(?: is)? ready|statement available|"
        r"account update|portfolio update|investment update|we updated your terms)\b",
        combined,
    )
    transactional_keywords = re.search(
        r"\b(payment due|bill is due|payment failed|past due|overdue|"
        r"verify your (?:account|email|phone)|"
        r"tax form\b|1099\b|w-2\b|k-1\b|"
        r"renewal problem|subscription will expire|update your payment method)\b",
        combined,
    )
    if transactional_keywords:
        signals.append("pi_transactional_action")
        return {"context": "transactional_action", "signals": signals}
    if account_keywords:
        signals.append("pi_account_fyi")
        return {"context": "account_fyi", "signals": signals}

    # 4. Default heuristics for important vs manual-review
    # Simple heuristic: short, low-template messages with no bulk signals look important_personal.
    looks_template = bool(re.search(r"\bunsubscribe\b|privacy policy|view in browser", combined))
    if not looks_template and len(txt) < 600 and "@" not in (sender or ""):
        signals.append("pi_important_personal_heuristic")
        return {"context": "important_personal", "signals": signals}

    return {"context": "review_manually", "signals": signals}

