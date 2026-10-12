"""
Resolve LLM adapters from ExecutionPrincipal: credential namespace, profile, then provider.
"""

from __future__ import annotations

import contextvars
from typing import Any

from local_ai.llm.adapter import BlockedLLMAdapter, LLMRequest, LLMAdapter
from local_ai.llm.credentials import resolve_cloud_api_key
from local_ai.llm.execution_principal import ExecutionPrincipal
from local_ai.llm.provider_registry import user_llm_adapter_gate_for_principal
from local_ai.hosted_config import default_llm_provider as _hosted_default_provider
from local_ai.providers.ollama import OllamaProvider

# Last council native attachment resolution (per asyncio context / request). For provider_resolution only.
_council_native_attachment_trace: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "council_native_attachment_trace",
    default=None,
)


def peek_council_native_attachment_trace() -> dict[str, Any] | None:
    """Read-only copy of attachment trace for council native (None if no council adapter run in this context)."""
    t = _council_native_attachment_trace.get()
    return dict(t) if t else None


def _set_council_native_attachment_trace(updates: dict[str, Any]) -> None:
    cur = _council_native_attachment_trace.get()
    base: dict[str, Any] = {} if cur is None else dict(cur)
    base.update(updates)
    _council_native_attachment_trace.set(base)


class _ProviderInstanceAdapter:
    """Seam-pushed provider (e.g. OpenAI with routed model/key)."""

    __slots__ = ("_inner",)

    def __init__(self, provider: Any):
        self._inner = provider

    def generate_text(self, request: LLMRequest) -> str:
        return self._inner.generate(request.prompt, timeout=request.timeout)


def get_provider_shim_for_legacy_generate(principal: ExecutionPrincipal) -> Any:
    """Object with .generate(prompt, timeout=60) for legacy evaluate paths."""
    adapter = get_llm_adapter_for_principal(principal)

    class _Shim:
        def generate(self, prompt: str, *, timeout: int | None = 60) -> str:
            return adapter.generate_text(
                LLMRequest(task="legacy", prompt=prompt, timeout=timeout),
            )

    return _Shim()


class _OllamaLLMAdapter:
    def __init__(self, base_url: str | None, model: str | None):
        self._inner = OllamaProvider(base_url=base_url, model=model)

    def generate_text(self, request: LLMRequest) -> str:
        return self._inner.generate(request.prompt, timeout=request.timeout)


class _CloudLLMAdapter:
    def __init__(self, provider: str, api_key: str, model: str | None):
        self._provider = provider
        self._api_key = api_key
        self._model = model

    def generate_text(self, request: LLMRequest) -> str:
        to = request.timeout if request.timeout is not None else 120
        if self._provider == "openai":
            from local_ai.providers import openai as p

            return p.generate(self._api_key, request.prompt, model=self._model, timeout=to)
        if self._provider == "anthropic":
            from local_ai.providers import anthropic as p

            return p.generate(self._api_key, request.prompt, model=self._model, timeout=to)
        if self._provider == "google":
            from local_ai.providers import google_genai as p

            return p.generate(self._api_key, request.prompt, model=self._model, timeout=to)
        if self._provider == "xai":
            from local_ai.providers import xai as p

            return p.generate(self._api_key, request.prompt, model=self._model, timeout=to)
        raise RuntimeError(f"Unknown provider {self._provider}")


def _profile_for_principal(principal: ExecutionPrincipal) -> dict:
    from local_ai.vision_execution import storage

    if principal.account_user_id:
        return storage.get_user_llm_profile(principal.account_user_id)
    return {}


def get_llm_adapter_for_principal(principal: ExecutionPrincipal) -> LLMAdapter:
    from local_ai.execution_policy.run_context import get_ollama_model_override, get_policy_provider_override

    policy = get_policy_provider_override()
    if policy is not None:
        return _ProviderInstanceAdapter(policy)

    profile = _profile_for_principal(principal)

    routed_om = get_ollama_model_override()
    if routed_om and str(routed_om).strip():
        msg = user_llm_adapter_gate_for_principal(principal, "ollama", profile)
        if msg:
            return BlockedLLMAdapter(msg)
        base = (profile.get("ollama_base_url") or "").strip() or None
        return _OllamaLLMAdapter(base_url=base, model=str(routed_om).strip())

    dp = (profile.get("default_provider") or _hosted_default_provider() or "ollama").strip().lower()
    model = profile.get("default_model") or None

    if dp == "ollama":
        msg = user_llm_adapter_gate_for_principal(principal, "ollama", profile)
        if msg:
            return BlockedLLMAdapter(msg)
        base = (profile.get("ollama_base_url") or "").strip() or None
        om = (profile.get("ollama_model") or "").strip() or None
        return _OllamaLLMAdapter(base_url=base, model=om)

    msg = user_llm_adapter_gate_for_principal(principal, dp, profile)
    if msg:
        return BlockedLLMAdapter(msg)

    key, _src = resolve_cloud_api_key(principal, dp)
    if not key:
        return BlockedLLMAdapter(
            f"No API key available for {dp} in namespace {principal.credential_namespace!r} "
            "(configure system env keys or account Settings)."
        )
    return _CloudLLMAdapter(dp, key, model)


def _urlparse_host(url: str) -> str | None:
    if not url:
        return None
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        if p.netloc:
            return p.netloc[:240]
        return url[:120]
    except Exception:
        return url[:120]


def describe_llm_adapter_routing(adapter: LLMAdapter) -> dict[str, Any]:
    """Introspect resolved adapter for diagnostics (no side effects beyond adapter construction)."""
    if isinstance(adapter, BlockedLLMAdapter):
        return {
            "adapter_kind": "BlockedLLMAdapter",
            "effective_provider": "blocked",
            "effective_model": None,
            "blocked_reason_preview": (adapter.reason or "")[:200],
        }
    if isinstance(adapter, _OllamaLLMAdapter):
        inner = adapter._inner
        bu = getattr(inner, "base_url", None) or ""
        return {
            "adapter_kind": "Ollama",
            "effective_provider": "ollama",
            "effective_model": getattr(inner, "model", None),
            "ollama_base_url_host": _urlparse_host(str(bu)),
        }
    if isinstance(adapter, _CloudLLMAdapter):
        return {
            "adapter_kind": "Cloud",
            "effective_provider": (adapter._provider or "").strip().lower(),
            "effective_model": adapter._model,
        }
    if isinstance(adapter, _ProviderInstanceAdapter):
        inner = adapter._inner
        return {
            "adapter_kind": "PolicyProviderInstance",
            "effective_provider": _council_adapter_provider_id(adapter),
            "effective_model": getattr(inner, "model", None),
            "policy_instance_class": type(inner).__name__,
        }
    return {
        "adapter_kind": type(adapter).__name__,
        "effective_provider": "unknown",
        "effective_model": None,
    }


def describe_meeting_evidence_llm_routing(
    principal: ExecutionPrincipal,
    *,
    seam_routing_active: bool,
) -> dict[str, Any]:
    """
    Snapshot of provider/model resolution for meeting segment extraction (same path as get_llm_adapter_for_principal).
    ``seam_routing_active`` should be True when the caller had a non-empty routing_context / execution seam.
    """
    from local_ai.execution_policy.run_context import get_ollama_model_override, get_policy_provider_override

    policy = get_policy_provider_override()
    om_override = get_ollama_model_override()
    profile = _profile_for_principal(principal)
    adapter = get_llm_adapter_for_principal(principal)
    eff = describe_llm_adapter_routing(adapter)

    policy_active = policy is not None
    om_act = bool(om_override and str(om_override).strip())
    if policy_active:
        routing_resolution_source = "execution_policy_provider_override"
    elif om_act:
        routing_resolution_source = "ollama_model_override"
    else:
        routing_resolution_source = "profile_default"

    return {
        "routing_context_seam_active": bool(seam_routing_active),
        "execution_policy_override_active": policy_active,
        "ollama_model_override_active": om_act,
        "ollama_model_override": str(om_override).strip() if om_act else None,
        "profile_default_provider": (profile.get("default_provider") or "ollama"),
        "profile_ollama_model": ((profile.get("ollama_model") or "").strip() or None),
        "profile_default_model": profile.get("default_model"),
        "profile_ollama_base_url_set": bool((profile.get("ollama_base_url") or "").strip()),
        "routing_resolution_source": routing_resolution_source,
        "seam_execution_policy_route_active": bool(seam_routing_active and policy_active),
        **eff,
    }


def _try_main_attachment_adapter_for_council_native(
    principal: ExecutionPrincipal,
    profile: dict,
) -> tuple[LLMAdapter | None, str | None]:
    """
    ``main`` attachment: same substrate as ``get_llm_adapter_for_principal`` after policy + routed Ollama
    (profile ``default_provider`` / ``default_model``, gates + keys). Gated by ``allows_externalization``.
    """
    dp = (profile.get("default_provider") or _hosted_default_provider() or "ollama").strip().lower()
    model = profile.get("default_model") or None
    if dp == "ollama":
        msg = user_llm_adapter_gate_for_principal(principal, "ollama", profile)
        if msg:
            return None, f"ollama_prefs_gate:{msg[:240]}"
        base = (profile.get("ollama_base_url") or "").strip() or None
        om = (profile.get("ollama_model") or "").strip() or None
        return _OllamaLLMAdapter(base_url=base, model=om), None
    msg = user_llm_adapter_gate_for_principal(principal, dp, profile)
    if msg:
        return None, f"cloud_prefs_gate:{dp}:{msg[:200]}"
    key, _src = resolve_cloud_api_key(principal, dp)
    if not key:
        return None, f"no_api_key_for_{dp}"
    return _CloudLLMAdapter(dp, key, model), None


def get_council_llm_adapter_for_principal(
    principal: ExecutionPrincipal,
    *,
    force_provider: str | None = None,
    force_model: str | None = None,
    allows_externalization: bool = True,
) -> LLMAdapter:
    """
    Default council seats (no per-seat override): policy provider, routed Ollama model,
    authenticated ``main`` attachment (profile default_provider path),
    then ``ZENAF_COUNCIL_MODEL`` / ``OLLAMA_COUNCIL_MODEL`` / profile ollama (local council stack).
    """
    import os

    from local_ai.execution_policy.run_context import get_ollama_model_override, get_policy_provider_override

    _council_native_attachment_trace.set({})

    fp = (force_provider or "").strip().lower()
    fm = (force_model or "").strip() or None

    policy = get_policy_provider_override()
    if policy is not None:
        _set_council_native_attachment_trace(
            {
                "council_native_attachment_requested": None,
                "council_native_attachment_resolved": "policy_provider_override",
                "council_native_fallback_reason": None,
                "council_native_stack_lane": None,
            }
        )
        return _ProviderInstanceAdapter(policy)

    profile = _profile_for_principal(principal)

    if fp:
        _set_council_native_attachment_trace(
            {
                "council_native_attachment_requested": None,
                "council_native_attachment_resolved": "explicit_native_provider",
                "council_native_fallback_reason": None,
                "council_native_stack_lane": None,
            }
        )
        if fp == "ollama":
            msg = user_llm_adapter_gate_for_principal(principal, "ollama", profile)
            if msg:
                return BlockedLLMAdapter(msg)
            base = (profile.get("ollama_base_url") or "").strip() or None
            forced_om = fm or (profile.get("ollama_model") or "").strip() or None
            return _OllamaLLMAdapter(base_url=base, model=forced_om)
        msg = user_llm_adapter_gate_for_principal(principal, fp, profile)
        if msg:
            return BlockedLLMAdapter(msg)
        key, _src = resolve_cloud_api_key(principal, fp)
        if not key:
            return BlockedLLMAdapter(
                f"No API key available for {fp} in namespace {principal.credential_namespace!r} "
                "(configure system env keys or account Settings)."
            )
        return _CloudLLMAdapter(fp, key, fm)

    routed_om = get_ollama_model_override()
    if routed_om and str(routed_om).strip():
        _set_council_native_attachment_trace(
            {
                "council_native_attachment_requested": None,
                "council_native_attachment_resolved": "routed_ollama_override",
                "council_native_fallback_reason": None,
                "council_native_stack_lane": None,
            }
        )
        msg = user_llm_adapter_gate_for_principal(principal, "ollama", profile)
        if msg:
            return BlockedLLMAdapter(msg)
        base = (profile.get("ollama_base_url") or "").strip() or None
        return _OllamaLLMAdapter(base_url=base, model=str(routed_om).strip())

    if principal.account_user_id:
        if not allows_externalization:
            _set_council_native_attachment_trace(
                {
                    "council_native_attachment_requested": "main",
                    "council_native_attachment_resolved": "local",
                    "council_native_fallback_reason": "privacy_requires_local",
                    "council_native_stack_lane": None,
                }
            )
        else:
            _set_council_native_attachment_trace(
                {
                    "council_native_attachment_requested": "main",
                    "council_native_attachment_resolved": None,
                    "council_native_fallback_reason": None,
                    "council_native_stack_lane": None,
                }
            )
            main_ad, main_err = _try_main_attachment_adapter_for_council_native(principal, profile)
            if main_ad is not None:
                _set_council_native_attachment_trace(
                    {
                        "council_native_attachment_requested": "main",
                        "council_native_attachment_resolved": "main",
                        "council_native_fallback_reason": None,
                        "council_native_stack_lane": None,
                    }
                )
                return main_ad
            _set_council_native_attachment_trace(
                {
                    "council_native_attachment_requested": "main",
                    "council_native_attachment_resolved": "local_fallback",
                    "council_native_fallback_reason": main_err or "main_attachment_unusable",
                    "council_native_stack_lane": None,
                }
            )
    else:
        _set_council_native_attachment_trace(
            {
                "council_native_attachment_requested": None,
                "council_native_attachment_resolved": "council_local_stack",
                "council_native_fallback_reason": None,
                "council_native_stack_lane": None,
            }
        )

    try:
        from local_ai import config as _config
    except Exception:
        _config = None
    council_model = os.environ.get("ZENAF_COUNCIL_MODEL", "").strip()
    if not council_model and _config and getattr(_config, "OLLAMA_COUNCIL_MODEL", None):
        council_model = str(_config.OLLAMA_COUNCIL_MODEL).strip()
    if council_model:
        _set_council_native_attachment_trace({"council_native_stack_lane": "env_council_model"})
        msg = user_llm_adapter_gate_for_principal(principal, "ollama", profile)
        if msg:
            return BlockedLLMAdapter(msg)
        base = (profile.get("ollama_base_url") or "").strip() or None
        return _OllamaLLMAdapter(base_url=base, model=council_model)

    msg = user_llm_adapter_gate_for_principal(principal, "ollama", profile)
    if msg:
        return BlockedLLMAdapter(msg)
    _set_council_native_attachment_trace({"council_native_stack_lane": "profile_ollama_model"})
    base = (profile.get("ollama_base_url") or "").strip() or None
    om = (profile.get("ollama_model") or "").strip() or None
    return _OllamaLLMAdapter(base_url=base, model=om)


def _adapter_model_hint(adapter: LLMAdapter) -> Any:
    if isinstance(adapter, _OllamaLLMAdapter):
        return adapter._inner.model
    if isinstance(adapter, _CloudLLMAdapter):
        return adapter._model
    inner = getattr(adapter, "_inner", None)
    return getattr(inner, "model", None) if inner is not None else None


def _council_adapter_provider_id(adapter: LLMAdapter) -> str:
    if isinstance(adapter, _OllamaLLMAdapter):
        return "ollama"
    if isinstance(adapter, _CloudLLMAdapter):
        return (adapter._provider or "").strip().lower() or "cloud"
    if isinstance(adapter, BlockedLLMAdapter):
        return "blocked"
    if isinstance(adapter, _ProviderInstanceAdapter):
        inner = adapter._inner
        name = type(inner).__name__
        if name == "OpenAIProvider":
            return "openai"
        mod = (getattr(type(inner), "__module__", "") or "").lower()
        if "anthropic" in mod:
            return "anthropic"
        if "google" in mod or "genai" in mod:
            return "google"
        return name.replace("Provider", "").lower() or "policy"
    return "unknown"


def get_council_provider_for_principal(
    principal: ExecutionPrincipal,
    *,
    force_provider: str | None = None,
    force_model: str | None = None,
    allows_externalization: bool = True,
) -> Any:
    """Object with ``.generate(prompt, timeout=…)`` and ``.model`` (for logging), principal-aware."""
    fp = (force_provider or "").strip().lower()
    adapter = get_council_llm_adapter_for_principal(
        principal,
        force_provider=force_provider,
        force_model=force_model,
        allows_externalization=allows_externalization,
    )

    class _CouncilShim:
        def __init__(self) -> None:
            self._adapter = adapter
            self.model = _adapter_model_hint(adapter)
            self.council_provider_id = fp or _council_adapter_provider_id(adapter)

        def generate(self, prompt: str, *, timeout: int | None = 120) -> str:
            return self._adapter.generate_text(LLMRequest(task="council", prompt=prompt, timeout=timeout))

    return _CouncilShim()
