"""
Resolve provider/model from routing context + policy (Phase 0 — no execution wiring).

``context is None`` reproduces implicit legacy behavior (default or council route).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Mapping, Optional

from .load import load_execution_policy_config
from .privacy_apply import (
    ExecutionPolicyOutcome,
    PrivacyPolicyInputPartial,
    apply_privacy_to_execution_resolution,
    merge_privacy_policy_input,
)
from .types import (
    ActionRoutingContext,
    ExecutionPolicyResolution,
    LegacyProviderRoute,
    PolicyConfig,
    ProviderModelRef,
)


def _import_config():
    import local_ai.config as cfg

    return cfg


def _effective_default_model() -> str:
    return _import_config().OLLAMA_MODEL


def _effective_council_model() -> str:
    env = os.environ.get("ATRIA_COUNCIL_MODEL", "").strip()
    if env:
        return env
    cfg = _import_config()
    return getattr(cfg, "OLLAMA_COUNCIL_MODEL", None) or cfg.OLLAMA_MODEL


def _resolve_null_model(
    model: Optional[str],
    *,
    legacy_route: LegacyProviderRoute,
    context_present: bool,
) -> str:
    _ = context_present  # legacy param; null-model choice is driven by legacy_route (council vs default).
    if model is not None and model != "":
        return str(model)
    # Council HTTP/stream path: unspecified model follows council stack even when routing_context is set.
    if legacy_route == "council":
        return _effective_council_model()
    return _effective_default_model()


def _coerce_provider_ref(
    d: Mapping[str, Any] | None,
    *,
    legacy_route: LegacyProviderRoute,
    context_present: bool,
    default_provider: str,
) -> ProviderModelRef:
    if not d:
        return ProviderModelRef(default_provider, _resolve_null_model(None, legacy_route=legacy_route, context_present=context_present))
    prov = str(d.get("provider") or default_provider)
    mod = d.get("model")
    mod_s = str(mod) if mod is not None and mod != "" else None
    return ProviderModelRef(prov, _resolve_null_model(mod_s, legacy_route=legacy_route, context_present=context_present))


def _parse_fallback_chain(
    raw: Any,
    *,
    legacy_route: LegacyProviderRoute,
    context_present: bool,
) -> list[ProviderModelRef]:
    out: list[ProviderModelRef] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, Mapping):
            out.append(_coerce_provider_ref(item, legacy_route=legacy_route, context_present=context_present, default_provider="ollama"))
    return out


def _apply_profile_flags(builder: dict[str, Any], prof: Mapping[str, Any]) -> None:
    if not prof:
        return
    if "allow_cloud" in prof:
        builder["allow_cloud"] = bool(prof["allow_cloud"])
    if prof.get("require_local"):
        builder["require_local"] = True
    if prof.get("prefer_cloud") is False:
        builder["allow_cloud"] = builder.get("allow_cloud", True) and False
    # prefer_cloud True does not force cloud in Phase 0 (no behavior change)


def _apply_override_block(
    block: Mapping[str, Any],
    builder: dict[str, Any],
    defaults: Mapping[str, Any],
    *,
    legacy_route: LegacyProviderRoute,
    context_present: bool,
) -> None:
    if "allow_cloud_fallback" in block:
        builder["allow_cloud"] = bool(block["allow_cloud_fallback"])
    if "primary" in block and isinstance(block["primary"], Mapping):
        builder["primary"] = _coerce_provider_ref(
            block["primary"],
            legacy_route=legacy_route,
            context_present=context_present,
            default_provider=str((defaults.get("local") or {}).get("provider") or "ollama"),
        )
    if "fallback_chain" in block:
        builder["fallback"] = _parse_fallback_chain(
            block["fallback_chain"],
            legacy_route=legacy_route,
            context_present=context_present,
        )


def resolve_execution_policy_for_action(
    context: Optional[ActionRoutingContext],
    *,
    legacy_route: LegacyProviderRoute = "default",
    policy_config: Optional[PolicyConfig] = None,
    policy_path: Optional[Path] = None,
    privacy: Optional[PrivacyPolicyInputPartial] = None,
    policy_namespace: Optional[str] = None,
) -> ExecutionPolicyOutcome:
    """
    Resolve execution policy. Does not call providers.

    - ``context is None``: legacy implicit path — same effective model as
      ``OllamaProvider()`` (``legacy_route='default'``) or council stack
      (``legacy_route='council'``).
    - ``context`` set: merge defaults → global profile → kind override → intent override;
      intent wins over kind for primary/fallback/allow_cloud.
    """
    cfg = policy_config or load_execution_policy_config(policy_path)
    defaults = cfg.defaults
    local_defaults = defaults.get("local") or {}
    default_provider = str(local_defaults.get("provider") or "ollama")
    allow_cloud_default = bool(defaults.get("allow_cloud_fallback", True))

    if context is None:
        primary = _coerce_provider_ref(
            local_defaults if isinstance(local_defaults, Mapping) else {},
            legacy_route=legacy_route,
            context_present=False,
            default_provider=default_provider,
        )
        flags_none: dict[str, Any] = {"legacy_route": legacy_route, "routing_context_absent": True}
        if policy_namespace:
            flags_none["policy_namespace"] = policy_namespace
        raw = ExecutionPolicyResolution(
            primary=primary,
            fallback_chain=(),
            allow_cloud=allow_cloud_default,
            flags=flags_none,
        )
        privacy_merged = merge_privacy_policy_input(False, privacy)
        return apply_privacy_to_execution_resolution(raw, privacy_merged)

    # Mutable builder for context-aware merge
    builder: dict[str, Any] = {
        "primary": _coerce_provider_ref(
            local_defaults if isinstance(local_defaults, Mapping) else {},
            legacy_route=legacy_route,
            context_present=True,
            default_provider=default_provider,
        ),
        "fallback": [],
        "allow_cloud": allow_cloud_default,
        "require_local": False,
    }

    profiles = cfg.priority_profiles
    _apply_profile_flags(builder, profiles.get(cfg.global_priority, {}))

    _ko = cfg.overrides_by_action_kind.get(context.action_kind)
    kind_ov = dict(_ko) if _ko else {}
    intent_key = (context.action_intent or "").strip()
    _ir = cfg.overrides_by_action_intent.get(intent_key) if intent_key else None
    intent_ov = dict(_ir) if _ir else {}

    if kind_ov:
        inh = kind_ov.get("inherit_priority")
        if inh and isinstance(inh, str) and inh in profiles:
            _apply_profile_flags(builder, profiles[inh])
        _apply_override_block(kind_ov, builder, defaults, legacy_route=legacy_route, context_present=True)

    if intent_ov:
        inh = intent_ov.get("inherit_priority")
        if inh and isinstance(inh, str) and inh in profiles:
            _apply_profile_flags(builder, profiles[inh])
        _apply_override_block(intent_ov, builder, defaults, legacy_route=legacy_route, context_present=True)

    primary = builder["primary"] if isinstance(builder["primary"], ProviderModelRef) else _coerce_provider_ref(
        local_defaults if isinstance(local_defaults, Mapping) else {},
        legacy_route=legacy_route,
        context_present=True,
        default_provider=default_provider,
    )
    fallback = builder.get("fallback") or []
    if not isinstance(fallback, list):
        fallback = []
    fb_tuple = tuple(fallback)

    flags: dict[str, Any] = {
        "routing_context_absent": False,
        "surface": context.surface,
        "action_kind": context.action_kind,
        "action_intent": context.action_intent,
    }
    if policy_namespace:
        flags["policy_namespace"] = policy_namespace
    if context.streaming is not None:
        flags["streaming"] = context.streaming
    if context.sensitivity:
        flags["sensitivity"] = context.sensitivity

    res = ExecutionPolicyResolution(
        primary=primary,
        fallback_chain=fb_tuple,
        allow_cloud=bool(builder.get("allow_cloud", allow_cloud_default)),
        flags=flags,
    )

    privacy_merged = merge_privacy_policy_input(bool(builder.get("require_local")), privacy)
    return apply_privacy_to_execution_resolution(res, privacy_merged)
