"""
Privacy constraints after base execution policy merge.
Deterministic; no silent fallback to disallowed providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional, Union

from .types import ExecutionPolicyResolution, ProviderModelRef

ExecutionPolicyOutcome = Union[ExecutionPolicyResolution, "ExecutionPolicyBlocked"]


def provider_execution_tier(provider: str) -> Literal["local", "cloud"]:
    p = str(provider or "").strip().lower().replace("-", "_")
    if p in ("ollama", "llamacpp", "lm_studio", "local"):
        return "local"
    return "cloud"


@dataclass(frozen=True)
class PrivacyPolicyInput:
    require_local: bool = False
    allow_cloud_fallback: bool = True
    approved_providers: Optional[tuple[str, ...]] = None
    approved_models: Optional[Mapping[str, tuple[str, ...]]] = None


DEFAULT_PRIVACY_POLICY_INPUT = PrivacyPolicyInput()


@dataclass(frozen=True)
class ExecutionPolicyBlocked:
    execution_blocked: Literal[True] = field(default=True, init=False)
    reason: Literal["privacy_constraints"] = "privacy_constraints"
    detail: str = ""


@dataclass(frozen=True)
class PrivacyPolicyInputPartial:
    """Explicit overrides for merge (field None = use profile default for that axis)."""

    require_local: Optional[bool] = None
    allow_cloud_fallback: Optional[bool] = None
    approved_providers: Optional[tuple[str, ...]] = None
    approved_models: Optional[Mapping[str, tuple[str, ...]]] = None


def merge_privacy_policy_input(
    profile_require_local: bool,
    explicit: Optional[PrivacyPolicyInputPartial] = None,
) -> PrivacyPolicyInput:
    e = explicit or PrivacyPolicyInputPartial()
    return PrivacyPolicyInput(
        require_local=e.require_local if e.require_local is not None else profile_require_local,
        allow_cloud_fallback=e.allow_cloud_fallback
        if e.allow_cloud_fallback is not None
        else DEFAULT_PRIVACY_POLICY_INPUT.allow_cloud_fallback,
        approved_providers=e.approved_providers
        if e.approved_providers is not None
        else DEFAULT_PRIVACY_POLICY_INPUT.approved_providers,
        approved_models=e.approved_models if e.approved_models is not None else DEFAULT_PRIVACY_POLICY_INPUT.approved_models,
    )


def _ref_passes_allowlists(ref: ProviderModelRef, privacy: PrivacyPolicyInput) -> bool:
    if privacy.require_local and provider_execution_tier(ref.provider) != "local":
        return False
    ap = privacy.approved_providers
    if ap is not None and len(ap) > 0 and ref.provider not in ap:
        return False
    am = privacy.approved_models
    if am is not None and len(am) > 0:
        lst = am.get(ref.provider)
        if lst is not None and len(lst) > 0 and ref.model not in lst:
            return False
    return True


def apply_privacy_to_execution_resolution(
    res: ExecutionPolicyResolution,
    privacy: PrivacyPolicyInput,
) -> ExecutionPolicyOutcome:
    ordered = (res.primary, *res.fallback_chain)
    allowlisted = tuple(r for r in ordered if _ref_passes_allowlists(r, privacy))

    after_cloud: list[ProviderModelRef] = []
    for i, r in enumerate(allowlisted):
        if i > 0 and not privacy.allow_cloud_fallback and provider_execution_tier(r.provider) == "cloud":
            continue
        after_cloud.append(r)

    if not after_cloud:
        return ExecutionPolicyBlocked(
            detail="No provider/model remains after privacy filtering (require_local, allowlists, or allow_cloud_fallback)."
        )

    primary = after_cloud[0]
    fallback_chain = tuple(after_cloud[1:])
    allow_cloud_out = bool(res.allow_cloud and privacy.allow_cloud_fallback)
    if privacy.require_local:
        allow_cloud_out = False

    flags = dict(res.flags)
    flags["privacy_applied"] = True
    flags["privacy_require_local"] = privacy.require_local
    flags["privacy_allow_cloud_fallback"] = privacy.allow_cloud_fallback

    return ExecutionPolicyResolution(
        primary=primary,
        fallback_chain=fallback_chain,
        allow_cloud=allow_cloud_out,
        flags=flags,
    )


def privacy_mode_to_partial(mode: Optional[str]) -> Optional[PrivacyPolicyInputPartial]:
    """
    Map client routing_context.privacy_mode to execution-policy partials.
    Align with frontend `privacyModeToPartialPrivacyPolicy`.
    Unknown / empty values => None (legacy / normal behavior).
    """
    m = (mode or "").strip().lower()
    if not m or m == "normal":
        return None
    if m == "protected":
        return PrivacyPolicyInputPartial(approved_providers=("ollama", "openai", "anthropic"))
    if m == "restricted":
        return PrivacyPolicyInputPartial(
            allow_cloud_fallback=False,
            approved_providers=("ollama", "openai"),
        )
    if m == "local_only":
        return PrivacyPolicyInputPartial(require_local=True, allow_cloud_fallback=False)
    return None


def apply_trace_privacy_redaction(
    *,
    input_snapshot: str,
    output: str,
    redact_trace_snapshot: bool,
    suppress_trace_output: bool,
) -> tuple[str, str]:
    snap = input_snapshot
    out = output
    if redact_trace_snapshot:
        t = str(snap or "").strip()
        snap = "[redacted]" if len(t) <= 80 else f"[redacted] len={len(t)}"
    if suppress_trace_output:
        out = '{"suppressed": true}'
    return snap, out
