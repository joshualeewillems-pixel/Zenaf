"""
Core profile AI (reconcile / conversation): substrate-aligned execution policy gate.

Privacy and provider/model filtering apply only when the client sends ``routing_context``
(see docs/02_ACTIVE_DESIGN/PRIVACY_EXECUTION_COVERAGE.md).
"""
from __future__ import annotations

from typing import Any, Optional

from local_ai.execution_policy import (
    ActionRoutingContext,
    ExecutionPolicyBlocked,
    resolve_execution_policy_for_action,
)
from local_ai.execution_policy.privacy_apply import privacy_mode_to_partial

SURFACE_DEFAULT = "core_profile"
INTENT_RECONCILE = "core_profile_reconcile"
INTENT_CONVERSATION = "core_profile_conversation"


def core_profile_execution_blocked(
    *,
    action_intent: str,
    routing_context: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """
    If policy/privacy blocks execution, return a user-facing error string.
    If ``routing_context`` is missing or not a dict, returns None (legacy permissive path).
    """
    if routing_context is None or not isinstance(routing_context, dict):
        return None

    surface = str(routing_context.get("surface") or SURFACE_DEFAULT).strip() or SURFACE_DEFAULT
    action_kind = str(routing_context.get("action_kind") or "structured_evaluation").strip() or "structured_evaluation"
    intent = str(routing_context.get("action_intent") or action_intent).strip() or action_intent
    streaming = routing_context.get("streaming")
    stream_b = bool(streaming) if streaming is not None else False
    sens_raw = routing_context.get("sensitivity")
    sensitivity = str(sens_raw).strip() if sens_raw else None

    partial = privacy_mode_to_partial(
        str(routing_context["privacy_mode"]).strip()
        if routing_context.get("privacy_mode") is not None
        else None
    )

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
