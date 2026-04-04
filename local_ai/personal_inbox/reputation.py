"""
Sender/domain reputation tracking for personal inbox cleanup.

Data model (kept intentionally simple, JSON-backed by default):
- email_reputation: per-sender_email counters.
- domain_reputation: per-domain counters (treated as stronger long-term signal).
- trusted_senders / trusted_domains: counterweight to suppression and noise.
- suppressed_senders / suppressed_domains: high-junk sources.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REPUTATION_PATH = ROOT / "personal_inbox_reputation.json"


@dataclass
class SenderStats:
    total: int = 0
    junk_promo: int = 0
    newsletter_media: int = 0
    account_fyi: int = 0
    transactional_action: int = 0
    important_personal: int = 0
    review_manually: int = 0
    last_seen: str = ""


@dataclass
class Reputation:
    email_reputation: Dict[str, SenderStats] = field(default_factory=dict)
    domain_reputation: Dict[str, SenderStats] = field(default_factory=dict)
    trusted_senders: Dict[str, bool] = field(default_factory=dict)
    trusted_domains: Dict[str, bool] = field(default_factory=dict)
    suppressed_senders: Dict[str, bool] = field(default_factory=dict)
    suppressed_domains: Dict[str, bool] = field(default_factory=dict)


def _stats_for(bucket: Dict[str, SenderStats], key: str) -> SenderStats:
    if key not in bucket:
        bucket[key] = SenderStats()
    return bucket[key]


def load_reputation(path: Path | None = None) -> Reputation:
    p = path or DEFAULT_REPUTATION_PATH
    if not p.is_file():
        return Reputation()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return Reputation()
    rep = Reputation()
    for col, dest in (
        ("email_reputation", rep.email_reputation),
        ("domain_reputation", rep.domain_reputation),
    ):
        src = raw.get(col) or {}
        for k, v in src.items():
            dest[k] = SenderStats(**v)
    rep.trusted_senders = {k: True for k in (raw.get("trusted_senders") or [])}
    rep.trusted_domains = {k: True for k in (raw.get("trusted_domains") or [])}
    rep.suppressed_senders = {k: True for k in (raw.get("suppressed_senders") or [])}
    rep.suppressed_domains = {k: True for k in (raw.get("suppressed_domains") or [])}
    return rep


def save_reputation(rep: Reputation, path: Path | None = None) -> None:
    p = path or DEFAULT_REPUTATION_PATH
    payload = {
        "email_reputation": {k: asdict(v) for k, v in rep.email_reputation.items()},
        "domain_reputation": {k: asdict(v) for k, v in rep.domain_reputation.items()},
        "trusted_senders": sorted(rep.trusted_senders.keys()),
        "trusted_domains": sorted(rep.trusted_domains.keys()),
        "suppressed_senders": sorted(rep.suppressed_senders.keys()),
        "suppressed_domains": sorted(rep.suppressed_domains.keys()),
    }
    p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _inc(stats: SenderStats, context: str, timestamp: str) -> None:
    stats.total += 1
    stats.last_seen = timestamp or stats.last_seen
    if context in {"junk_promo", "newsletter_media", "account_fyi", "transactional_action", "important_personal", "review_manually"}:
        setattr(stats, context, getattr(stats, context) + 1)


def update_reputation(
    rep: Reputation,
    *,
    sender_email: str,
    context: str,
    timestamp: str,
) -> None:
    """Update both email-level and domain-level stats for a single message."""
    sender_email = (sender_email or "").strip().lower()
    if not sender_email or "@" not in sender_email:
        return
    local, domain = sender_email.split("@", 1)
    domain = domain.strip().lower()
    email_stats = _stats_for(rep.email_reputation, sender_email)
    domain_stats = _stats_for(rep.domain_reputation, domain)
    _inc(email_stats, context, timestamp)
    _inc(domain_stats, context, timestamp)


def is_trusted(sender_email: str, rep: Reputation) -> bool:
    sender_email = (sender_email or "").strip().lower()
    if not sender_email or "@" not in sender_email:
        return False
    local, domain = sender_email.split("@", 1)
    domain = domain.strip().lower()
    if sender_email in rep.suppressed_senders or domain in rep.suppressed_domains:
        # Trusted senders/domains override suppression.
        if sender_email in rep.trusted_senders or domain in rep.trusted_domains:
            return True
        return False
    if sender_email in rep.trusted_senders or domain in rep.trusted_domains:
        return True
    return False

