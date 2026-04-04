"""
Compiled / structured cloud delegation — types only.

The internal system owns task definition, contract, synthesis, validation, and distribution;
the remote model is a bounded inference step (JSON in / JSON out).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Public label for traces / API (no new AiActionKind)
STRUCTURED_CLOUD_DELEGATION_V1: Literal["structured_cloud_v1"] = "structured_cloud_v1"

WORKSPACE_NEXT_STEP_DELEGATION_SCHEMA_ID = "workspace_next_step_structured_json_v1"

INITIATIVE_EVALUATE_DELEGATION_SCHEMA_ID = "initiative_evaluate_structured_json_v1"

INITIATIVE_EVALUATE_INTENT = "initiative_evaluate"

CORE_PROFILE_RECONCILE_DELEGATION_SCHEMA_ID = "core_profile_reconcile_structured_json_v1"

# Must match ``local_ai.vision_execution.core_profile_execution.INTENT_RECONCILE``
# and ``local_ai.execution_policy.externalization.CORE_PROFILE_RECONCILE_INTENT``.
CORE_PROFILE_RECONCILE_INTENT = "core_profile_reconcile"


@dataclass(frozen=True)
class WorkspaceNextStepDelegationContract:
    """Pre-execution contract for one workspace next-step delegation call."""

    task_intent: str
    """Substrate intent, e.g. ``workspace_next_step``."""

    bounded_context: str
    """User/workspace context only; length-capped before synthesis."""

    question_goal: str | None
    """Optional user goal line."""

    output_schema_id: str
    """Identifier for the expected JSON shape (prompt + validator must match)."""

    destination_api_shape: str
    """Human-readable mapping hint for maintainers (prompt footer)."""

    subject_id_hint: str | None
    """Optional id for externalization / audit; may appear inside ``bounded_context``."""


@dataclass(frozen=True)
class InitiativeEvaluateDelegationContract:
    """Pre-execution contract for one structured-cloud initiative evaluation call."""

    task_intent: str
    """``initiative_evaluate``."""

    title: str
    brief: str
    core_profile_block: str | None
    """Bounded core profile text section, or ``None``."""

    output_schema_id: str
    destination_api_shape: str


@dataclass(frozen=True)
class CoreProfileReconcileDelegationContract:
    """Pre-execution contract for one structured-cloud core profile reconcile call."""

    task_intent: str
    """``core_profile_reconcile``."""

    current_profile_block: str
    """Bounded ``- key: value`` lines for current structured fields."""

    raw_notes: str
    conversation_text: str
    output_schema_id: str
    destination_api_shape: str
