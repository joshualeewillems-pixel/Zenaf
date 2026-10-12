"""Redaction at capture: PII never enters the event store.

Fast, dependency-free regex replacements applied by adapters *before* events
are stored. This is a backstop, not a guarantee — adapters should still avoid
persisting obviously sensitive fields — but it ensures the common cases
(emails, phone numbers, long digit runs like account/ID numbers) cannot leak
into the signal store in plain text.

Tokens are stable and human-readable so distilled signals stay legible:
[EMAIL], [PHONE], [ID], [NUMBER].
"""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# US-style phone numbers with common separators, optional country code.
_PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
# US social-security-style 3-2-4.
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Any remaining long digit run (account numbers, order ids, tokens, ...).
_LONG_DIGITS_RE = re.compile(r"\d{7,}")


def redact_text(text: str | None) -> str:
    """Return text with emails, phones, SSNs, and long digit runs tokenized."""
    if not text:
        return ""
    redacted = _EMAIL_RE.sub("[EMAIL]", text)
    redacted = _PHONE_RE.sub("[PHONE]", redacted)
    redacted = _SSN_RE.sub("[ID]", redacted)
    redacted = _LONG_DIGITS_RE.sub("[NUMBER]", redacted)
    return redacted
