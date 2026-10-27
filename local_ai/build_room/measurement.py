"""Server-side generation measurement for the Build-Council Room.

Two instruments, both testable without any model call:

- Latency (:func:`measure_generation`): a monotonic-clock bracket
  around exactly ONE participant call. The timer covers the generate
  call only — never prompt building, gating, or validation. The
  margin threshold is DERIVED (0.8 × timeout_seconds, 96s only as
  the instance at a 120s timeout) and the margin comparison uses
  the UNROUNDED duration; reported durations are rounded to
  milliseconds for readability, never for the verdict.
- Cost (:func:`compute_generation_cost`): provider-reported token
  usage is "measured"; exact tokenizer counts are a labeled
  "estimated" fallback in a separate computation, never blended.
  The dollar charge is ALWAYS calculated from a price table —
  provider usage carries tokens, never dollars — and no price is
  ever invented here: when no verified price table is supplied,
  the charge stays null with a stated reason (unassessable).

Single-call guarantee: :func:`measure_generation` issues exactly
one participant call on every path. A participant without
``generate_with_usage`` falls back to ``generate()`` once and the
cost is estimated from that call's returned text — never a second
generation to obtain usage. Likewise, a ``generate_with_usage``
result without a usage block falls back to estimating from the
same call's text.
"""

from __future__ import annotations

import time
from typing import Any

TRIPWIRE_USD = 0.05
MARGIN_FRACTION = 0.8


def _count_tokens_exact(text: str) -> int | None:
    """Exact o200k_base count, or None when tiktoken is unavailable."""
    try:
        from local_ai.llm.tokenizer import count_tokens
    except ImportError:
        return None
    try:
        return count_tokens(text)
    except RuntimeError:
        return None


def _is_timeout(exc: BaseException, duration: float, timeout: int) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    name = type(exc).__name__.lower()
    if "timeout" in name or "timed out" in str(exc).lower():
        return True
    return duration >= timeout


def measure_generation(participant: Any, prompt: str, *,
                       timeout: int = 120) -> dict[str, Any]:
    """Run exactly one generation and measure it server-side.

    Returns a dict with ``text`` (or None on failure), ``error``
    (or None), ``usage`` (provider-reported dict or None),
    ``used_generate_with_usage`` (bool), and ``generation`` — the
    latency object: duration_seconds (ms precision, reported),
    timeout_seconds, margin_threshold_seconds (derived, 0.8 ×
    timeout), margin_seconds, within_margin (from the UNROUNDED
    duration), timed_out. On refusal-style non-generation paths
    the caller must NOT call this function at all: no generation
    object exists for a call that never happened (design §E.3).
    """
    start = time.monotonic()
    used_with_usage = hasattr(participant, "generate_with_usage")
    try:
        if used_with_usage:
            result = participant.generate_with_usage(
                prompt, timeout=timeout)
            if isinstance(result, (tuple, list)) and len(result) == 2:
                text, usage = result
            else:  # mis-shaped parallel return: text only, usage absent
                text, usage = result, None
        else:
            text = participant.generate(prompt, timeout=timeout)
            usage = None
    except Exception as exc:  # failure is data, not a crash
        duration = time.monotonic() - start
        timed_out = _is_timeout(exc, duration, timeout)
        threshold = MARGIN_FRACTION * timeout
        return {
            "text": None,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "usage": None,
            "used_generate_with_usage": used_with_usage,
            "generation": {
                "duration_seconds": round(duration, 3),
                "timeout_seconds": timeout,
                "margin_threshold_seconds": threshold,
                "margin_seconds": round(timeout - duration, 3),
                "within_margin": (not timed_out) and duration < threshold,
                "timed_out": timed_out,
            },
        }
    duration = time.monotonic() - start
    threshold = MARGIN_FRACTION * timeout
    return {
        "text": text,
        "error": None,
        "error_type": None,
        "usage": usage if isinstance(usage, dict) else None,
        "used_generate_with_usage": used_with_usage,
        "generation": {
            "duration_seconds": round(duration, 3),
            "timeout_seconds": timeout,
            "margin_threshold_seconds": threshold,
            "margin_seconds": round(timeout - duration, 3),
            "within_margin": duration < threshold,
            "timed_out": False,
        },
    }


def compute_generation_cost(prompt_text: str, response_text: str | None,
                            usage: dict | None,
                            price_table: dict | None) -> dict[str, Any]:
    """Build the generation_cost object (design §F.4).

    ``usage`` is the provider-reported usage dict (or None).
    ``price_table`` is {model, per_1m_input_usd, per_1m_output_usd,
    provenance, retrieved_date} or None. With no verified price
    table, tokens are still reported but charge_usd stays null —
    a charge is never fabricated from an invented price, and a
    null charge makes the tripwire unassessable, never clear.
    """
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    source: str
    reason: str | None = None
    if isinstance(usage, dict) and isinstance(
            usage.get("prompt_tokens"), int) and isinstance(
            usage.get("completion_tokens"), int):
        source = "measured"
        prompt_tokens = usage["prompt_tokens"]
        completion_tokens = usage["completion_tokens"]
    else:
        prompt_tokens = _count_tokens_exact(prompt_text) if prompt_text else None
        completion_tokens = (_count_tokens_exact(response_text)
                             if response_text else None)
        if prompt_tokens is None or completion_tokens is None:
            return {
                "source": "unavailable",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "price_table": price_table,
                "charge_usd": None,
                "charge_basis": None,
                "reason": ("provider usage absent and exact tokenizer "
                           "count unavailable"),
            }
        source = "estimated"
        reason = ("provider usage absent; tokens counted exactly "
                  "with o200k_base (estimate, not provider-reported)")
    if price_table is None:
        return {
            "source": source,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "price_table": None,
            "charge_usd": None,
            "charge_basis": None,
            "reason": "no verified price table recorded; charge unassessable",
        }
    charge = round(
        (prompt_tokens / 1_000_000) * price_table["per_1m_input_usd"]
        + (completion_tokens / 1_000_000) * price_table["per_1m_output_usd"],
        6)
    basis = ("measured_tokens_x_stated_price" if source == "measured"
             else "estimated_tokens_x_stated_price")
    return {
        "source": source,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "price_table": price_table,
        "charge_usd": charge,
        "charge_basis": basis,
        "reason": reason,
    }


def evaluate_tripwire(cost: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate the $0.05 tripwire (S4) against a cost object.

    The tripwire is a REVIEW trigger only, never an automatic
    decision. The evaluation always states its source: measured
    (provider tokens × stated price), estimate-based, or
    unassessable (charge null — stated, never assumed clear).
    """
    if not cost or cost.get("charge_usd") is None:
        return {
            "tripped": None,
            "label": "unassessable",
            "charge_usd": None,
            "source": cost.get("source") if cost else None,
        }
    charge = cost["charge_usd"]
    label = ("measured" if cost.get("source") == "measured"
             else "estimate-based")
    return {
        "tripped": charge > TRIPWIRE_USD,
        "label": label,
        "charge_usd": charge,
        "source": cost.get("source"),
    }
