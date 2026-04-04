"""
Shared mechanics for compiled delegation: strict rebind after cloud ``generate``, before JSON parse.

Path-specific pieces stay in each delegation module:

- Which ``ExternalizeResult`` producer runs (``maybe_externalize_for_cloud`` vs initiative helper).
- How the prompt is synthesized and how model output is validated / distributed.

This module only centralizes: mapping-active detection, ``rebind_after_cloud_response``,
fail-closed integrity gate, and privacy redaction for externalization diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from local_ai.execution_policy.externalization import (
    ExternalizeResult,
    rebind_after_cloud_response,
    redact_externalization_for_privacy,
)

INTEGRITY_FAILURE_MESSAGE = (
    "Externalized response failed integrity validation (placeholder mismatch or missing echo)."
)


def mapping_active_for_externalize(ex: ExternalizeResult) -> bool:
    """True when structured placeholder mapping was applied (tokens were sent to the model)."""
    return ex.strategy != "none" and bool(ex.placeholder_map.by_token)


def redact_when_mapping_ok(
    *,
    privacy_mode: Optional[str],
    mapping_active: bool,
) -> dict:
    """
    After successful strict rebind (or when mapping was off), attach OK externalization
    trace fields only if placeholders were in play.
    """
    if not mapping_active:
        return {}
    return redact_externalization_for_privacy(
        privacy_mode=privacy_mode,
        integrity_ok=True,
        unresolved_tokens=(),
        invalid_tokens=(),
    )


@dataclass(frozen=True)
class StrictRebindOk:
    """Model output passed strict rebind; ``text`` is safe to parse (JSON, lines, etc.)."""

    text: str
    mapping_active: bool


@dataclass(frozen=True)
class StrictRebindIntegrityFailure:
    """Sent tokens missing, invalid, or mismatched — do not parse model output as contract."""

    redaction_extras: dict


StrictRebindResult = StrictRebindOk | StrictRebindIntegrityFailure


def strict_rebind_cloud_output(
    model_raw: str,
    ex: ExternalizeResult,
    *,
    privacy_mode: Optional[str],
) -> StrictRebindResult:
    """Run ``rebind_after_cloud_response`` and enforce fail-closed integrity when mapping was active."""
    mapping_on = mapping_active_for_externalize(ex)
    rb = rebind_after_cloud_response(model_raw, ex.placeholder_map)
    if mapping_on:
        fully_ok = rb.integrity_ok and len(rb.unresolved_tokens) == 0
        if not fully_ok:
            return StrictRebindIntegrityFailure(
                redaction_extras=redact_externalization_for_privacy(
                    privacy_mode=privacy_mode,
                    integrity_ok=False,
                    unresolved_tokens=rb.unresolved_tokens,
                    invalid_tokens=rb.invalid_tokens_in_output,
                )
            )
    return StrictRebindOk(text=rb.text, mapping_active=mapping_on)
