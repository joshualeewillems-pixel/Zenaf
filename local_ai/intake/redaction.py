"""
PHI detection and optional redaction. Keeps raw content internal; only sanitized text
should be sent to external AI. Pattern-based for now.
"""
from __future__ import annotations

import re
from typing import Any

# Patterns that may indicate PHI (simplified; extend per HIPAA guidance)
PHI_PATTERNS = [
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL]"),
    (r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", "[PHONE]"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]"),
    (r"\b(?:DOB|dob|date of birth)\s*:?\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", "[DOB]"),
    (r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", "[DATE]"),
    (r"\b(?:MRN|mrn|medical record)\s*:?\s*#?\s*\d{4,}\b", "[MRN]"),
    (r"\b(?:patient|pt)\s*:?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", "[NAME]"),
]


def detect_phi(text: str) -> list[dict[str, Any]]:
    """
    Detect potential PHI spans in text. Returns list of {start, end, label, matched}.
    Does not modify text; for display or audit only.
    """
    if not text or not isinstance(text, str):
        return []
    findings = []
    for pattern, label in PHI_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            findings.append({
                "start": m.start(),
                "end": m.end(),
                "label": label,
                "matched": text[m.start() : m.end()],
            })
    return findings


def redact(text: str, replacement: str = "[REDACTED]") -> str:
    """
    Return a copy of text with PHI patterns replaced by replacement.
    Use the result for any external AI or logging; keep original internal only.
    """
    if not text or not isinstance(text, str):
        return text
    out = text
    for pattern, _ in PHI_PATTERNS:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out
