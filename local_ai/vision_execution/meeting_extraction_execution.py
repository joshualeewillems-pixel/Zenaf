"""
Meeting extraction: execution policy gate when ``routing_context`` is sent (privacy_mode, etc.).
When policy allows, ``apply_seam_routing`` pushes OpenAI/Ollama so ``get_llm_adapter_for_principal`` sees the same overrides.
Align with frontend intents in ``meetingExtractionTrace.ts``.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from local_ai.execution_policy import (
    ActionRoutingContext,
    ExecutionPolicyBlocked,
    resolve_execution_policy_for_action,
)
from local_ai.execution_policy.privacy_apply import privacy_mode_to_partial

SURFACE_DEFAULT = "meeting_extraction"
INTENT_SINGLE = "meeting_extract_single"
INTENT_CHUNKS = "meeting_extract_chunks"
INTENT_SYNTHESIS = "meeting_extract_synthesis"


@contextmanager
def meeting_execution_seam(
    routing_context: Optional[dict[str, Any]],
    *,
    mode: str,
    user_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    """
    When ``routing_context`` is set, apply the same seam as Vision Execution (OpenAI key check, overrides).

    Yields ``meta`` from ``apply_seam_routing`` (possibly ``execution_blocked``). Always tears down overrides.
    When ``routing_context`` is None, yields ``{}`` (no seam; principal resolver uses profile/env only).
    """
    if not routing_context:
        yield {}
        return
    from local_ai.execution_policy.run_context import end_execution_routing
    from local_ai.execution_policy.seam_routing import apply_seam_routing
    from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id, principal_for_vision_execution_user

    mp = (
        principal_for_vision_execution_user(user_id)
        if user_id
        else execution_principal_from_legacy_user_id(None)
    )
    teardown, meta = apply_seam_routing(mode=mode, routing_context=routing_context, principal=mp)
    try:
        yield meta
    finally:
        end_execution_routing(teardown)


def meeting_extraction_execution_blocked(
    *,
    action_intent: str,
    routing_context: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """
    If policy/privacy blocks execution, return user-facing error detail.
    If ``routing_context`` is missing or not a dict, returns None (legacy permissive path).
    """
    if routing_context is None or not isinstance(routing_context, dict):
        return None

    surface = str(routing_context.get("surface") or SURFACE_DEFAULT).strip() or SURFACE_DEFAULT
    action_kind = str(routing_context.get("action_kind") or "suggestion_batch").strip() or "suggestion_batch"
    intent = str(routing_context.get("action_intent") or action_intent).strip() or action_intent
    streaming = routing_context.get("streaming")
    stream_b = bool(streaming) if streaming is not None else False
    sens_raw = routing_context.get("sensitivity")
    sensitivity = str(sens_raw).strip() if sens_raw else None

    pm = routing_context.get("privacy_mode")
    partial = privacy_mode_to_partial(str(pm).strip() if pm is not None else None)

    ctx = ActionRoutingContext(
        surface=surface,
        action_kind=action_kind,
        action_intent=intent,
        streaming=stream_b,
        sensitivity=sensitivity,
    )
    outcome = resolve_execution_policy_for_action(ctx, legacy_route="default", privacy=partial)
    if isinstance(outcome, ExecutionPolicyBlocked):
        return outcome.detail or "Execution blocked by privacy policy"
    return None
