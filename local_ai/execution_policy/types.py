"""Execution policy types (Phase 0 — resolver seam; no execution changes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Optional

LegacyProviderRoute = Literal["default", "council"]


@dataclass(frozen=True)
class ProviderModelRef:
    provider: str
    model: str


@dataclass(frozen=True)
class ActionRoutingContext:
    """Substrate-aligned routing input. None => legacy implicit behavior."""

    surface: str
    action_kind: str
    action_intent: Optional[str] = None
    streaming: Optional[bool] = None
    sensitivity: Optional[str] = None


@dataclass(frozen=True)
class ExecutionPolicyResolution:
    """Resolved provider/model plan. Fallback chain is not executed in Phase 0."""

    primary: ProviderModelRef
    fallback_chain: tuple[ProviderModelRef, ...] = ()
    allow_cloud: bool = True
    flags: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyConfig:
    """Loaded policy document (schema v1)."""

    schema_version: int
    global_priority: str
    defaults: Mapping[str, Any]
    priority_profiles: Mapping[str, Mapping[str, Any]]
    overrides_by_action_kind: Mapping[str, Mapping[str, Any]]
    overrides_by_action_intent: Mapping[str, Mapping[str, Any]]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PolicyConfig:
        return cls(
            schema_version=int(raw.get("schema_version", 1)),
            global_priority=str(raw.get("global_priority", "balanced")),
            defaults=dict(raw.get("defaults") or {}),
            priority_profiles={k: dict(v or {}) for k, v in (raw.get("priority_profiles") or {}).items()},
            overrides_by_action_kind={k: dict(v or {}) for k, v in (raw.get("overrides_by_action_kind") or {}).items()},
            overrides_by_action_intent={k: dict(v or {}) for k, v in (raw.get("overrides_by_action_intent") or {}).items()},
        )
