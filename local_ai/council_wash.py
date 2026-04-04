"""
Council-only deterministic wash (v0): redact obvious identifiers before cloud execution.
No LLM washing; no global classification.
"""

from __future__ import annotations

import re
from typing import Any

WASH_VERSION = "council_wash_v0"

_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.I,
)
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
)
# sk- / pk- style API key prefixes (short window to limit false positives)
_API_TOKEN_RE = re.compile(r"\b(?:sk|pk)-[A-Za-z0-9]{16,}\b", re.I)
_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
# assignment-style secrets (value redacted, key label kept loosely)
_KV_SECRET_RE = re.compile(
    r"(?i)(?P<prefix>\b(?:password|secret|api[_\- ]?key|token|bearer)\s*[:=]\s*)(?P<val>\S+)",
)

_PLACEHOLDER_UUID = "[REDACTED_UUID]"
_PLACEHOLDER_EMAIL = "[REDACTED_EMAIL]"
_PLACEHOLDER_TOKEN = "[REDACTED_TOKEN]"
def _redact_identifiers(text: str) -> tuple[str, list[str]]:
    summary: list[str] = []
    t = text
    n = len(_UUID_RE.findall(t))
    if n:
        t = _UUID_RE.sub(_PLACEHOLDER_UUID, t)
        summary.append(f"uuid:{n}")
    n = len(_EMAIL_RE.findall(t))
    if n:
        t = _EMAIL_RE.sub(_PLACEHOLDER_EMAIL, t)
        summary.append(f"email:{n}")
    n = len(_API_TOKEN_RE.findall(t))
    if n:
        t = _API_TOKEN_RE.sub(_PLACEHOLDER_TOKEN, t)
        summary.append(f"api_token:{n}")
    n = len(_AWS_KEY_RE.findall(t))
    if n:
        t = _AWS_KEY_RE.sub(_PLACEHOLDER_TOKEN, t)
        summary.append(f"aws_access_key:{n}")

    def _kv_sub(m: re.Match[str]) -> str:
        return f"{m.group('prefix')}{_PLACEHOLDER_TOKEN}"

    n_kv = len(_KV_SECRET_RE.findall(t))
    if n_kv:
        t = _KV_SECRET_RE.sub(_kv_sub, t)
        summary.append(f"kv_secret:{n_kv}")
    return t, summary


def _wash_safety_ok(washed: str) -> tuple[bool, list[str]]:
    """Fail closed if obvious patterns remain after redaction."""
    reasons: list[str] = []
    if _UUID_RE.search(washed):
        reasons.append("residual_uuid")
    if _EMAIL_RE.search(washed):
        reasons.append("residual_email")
    if _API_TOKEN_RE.search(washed) or _AWS_KEY_RE.search(washed):
        reasons.append("residual_token")
    if _KV_SECRET_RE.search(washed):
        reasons.append("residual_kv_secret")
    return (not reasons), reasons


def neutral_snapshot_from_text(text: str) -> dict[str, str]:
    """Lightweight heuristic fields appended to cloud context (post-redaction)."""
    problem = ""
    constraints_parts: list[str] = []
    outcome = ""
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        lo = raw.lower()
        if lo.startswith("outcome:") or "outcome:" in lo[:20]:
            outcome = raw.split(":", 1)[-1].strip()[:500]
        elif "constraint" in lo or lo.startswith("constraints:"):
            constraints_parts.append(raw[:300])
        elif lo.startswith("project:") or lo.startswith("goal:") or lo.startswith("problem:"):
            if not problem:
                problem = raw.split(":", 1)[-1].strip()[:500]
        elif lo.startswith("note:") and not outcome:
            outcome = raw.split(":", 1)[-1].strip()[:500]
    if not problem:
        flat = " ".join(text.split())[:400]
        problem = flat if flat else "(empty)"
    constraints = "; ".join(constraints_parts) if constraints_parts else "(none extracted)"
    if not outcome:
        outcome = "(none extracted)"
    return {
        "problem": problem,
        "constraints": constraints[:800],
        "outcome": outcome[:500],
    }


def _snapshot_appendix(snapshot: dict[str, str]) -> str:
    return (
        "\n\n--- NEUTRAL SNAPSHOT (wash v0; deterministic) ---\n"
        f"Problem: {snapshot['problem']}\n"
        f"Constraints: {snapshot['constraints']}\n"
        f"Outcome: {snapshot['outcome']}\n"
    )


def prepare_council_contexts(raw_enriched: str | None) -> tuple[str, str | None, dict[str, Any]]:
    """
    Build native (raw) context and optional cloud-safe washed context.

    Returns:
        native_context: verbatim raw (or empty string)
        cloud_context: washed + snapshot appendix if safety passes; else None (do not send to cloud)
        wash_trace: inspect-only dict (no raw payload echoes)
    """
    raw = (raw_enriched or "").strip()
    trace: dict[str, Any] = {
        "wash_version": WASH_VERSION,
        "wash_applied": False,
        "cloud_payload_source": "raw",
        "safety_allow_cloud_with_wash": True,
        "transform_summary": [],
        "safety_refusal_reasons": [],
    }
    if not raw:
        trace["cloud_payload_source"] = "raw"
        return "", None, trace

    washed, tsum = _redact_identifiers(raw)
    trace["wash_applied"] = bool(tsum)
    trace["transform_summary"] = tsum

    snap = neutral_snapshot_from_text(washed)
    cloud_body = washed + _snapshot_appendix(snap)

    ok, reasons = _wash_safety_ok(cloud_body)
    trace["safety_allow_cloud_with_wash"] = ok
    trace["safety_refusal_reasons"] = reasons
    if ok:
        trace["cloud_payload_source"] = "washed"
        return raw, cloud_body, trace

    trace["cloud_payload_source"] = "none_unsafe_wash"
    return raw, None, trace
