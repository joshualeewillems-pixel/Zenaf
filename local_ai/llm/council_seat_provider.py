"""
Resolve the LLM provider instance for a single council seat (explicit provider vs policy default).

Council seats call ``provider.generate(prompt, timeout=...)``. Cloud modules that only expose
``generate(api_key, prompt, ...)`` are wrapped in a small shim.

All seats resolve credentials and gating through ``ExecutionPrincipal`` (scope → namespace → keys).
"""

from __future__ import annotations

from typing import Any

from local_ai.llm.credentials import resolve_cloud_api_key
from local_ai.llm.execution_principal import ExecutionPrincipal
from local_ai.llm.provider_registry import (
    default_model_hint,
    effective_default_model_for_profile,
    normalize_provider_id,
    user_llm_adapter_gate_for_principal,
)
from local_ai.providers.ollama import OllamaProvider


class _AnthropicShim:
    def __init__(self, api_key: str, model: str | None):
        self._key = api_key
        self._model = model
        self.model = model

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        from local_ai.providers import anthropic as pa

        return pa.generate(self._key, prompt, model=self._model, timeout=timeout)


class _GoogleShim:
    def __init__(self, api_key: str, model: str | None):
        self._key = api_key
        self._model = model
        self.model = model

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        from local_ai.providers import google_genai as pg

        return pg.generate(self._key, prompt, model=self._model, timeout=timeout)


class _XaiShim:
    def __init__(self, api_key: str, model: str | None):
        self._key = api_key
        self._model = model
        self.model = model

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        from local_ai.providers import xai as px

        return px.generate(self._key, prompt, model=self._model, timeout=timeout)


class _OpenRouterShim:
    def __init__(self, api_key: str, model: str | None):
        self._key = api_key
        self._model = model
        self.model = model

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        from local_ai.providers import openrouter as por

        return por.generate(self._key, prompt, model=self._model, timeout=timeout)


class _MetaShim:
    def __init__(self, api_key: str, model: str | None):
        self._key = api_key
        self._model = model
        self.model = model

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        from local_ai.providers import meta as pm

        return pm.generate(self._key, prompt, model=self._model, timeout=timeout)


def _normalize_seat_provider(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or s in ("auto", "default"):
        return None
    return normalize_provider_id(s)


def _effective_provider_label(p: Any) -> str:
    name = type(p).__name__
    mid = getattr(p, "model", None)
    if mid:
        return f"{name}(model={mid!r})"
    return name


def _credential_source_literal(src: object) -> str:
    return src if isinstance(src, str) else "none"


def _seat_fallback_note(
    *,
    requested_provider: str,
    default_provider: Any,
    reason_code: str,
    principal: ExecutionPrincipal,
    credential_source: str | None = None,
    detail: str | None = None,
) -> str:
    """Human- and log-friendly; encodes requested vs effective and namespace (no silent mismatch)."""
    parts = [
        "seat_provider_fallback",
        f"requested={requested_provider!r}",
        f"effective={_effective_provider_label(default_provider)!r}",
        f"reason={reason_code}",
        f"execution_scope={principal.scope!r}",
        f"principal_ref={principal.principal_ref!r}",
        f"credential_namespace={principal.credential_namespace!r}",
    ]
    if credential_source is not None:
        parts.append(f"credential_source={credential_source!r}")
    if detail:
        parts.append(f"detail={detail}")
    return "; ".join(parts)


def build_council_seat_provider(
    seat_llm_provider: str | None,
    *,
    principal: ExecutionPrincipal,
    default_provider: Any,
    profile: dict[str, Any] | None = None,
    allows_externalization: bool = True,
) -> tuple[Any, str | None]:
    """
    Return ``(provider, fallback_note)`` where ``fallback_note`` is set when the requested
    provider could not be used and ``default_provider`` was used instead.
    """
    want = _normalize_seat_provider(seat_llm_provider)
    if want is None:
        return default_provider, None

    if not allows_externalization and want != "ollama":
        return default_provider, _seat_fallback_note(
            requested_provider=want,
            default_provider=default_provider,
            reason_code="privacy_requires_local",
            principal=principal,
            detail="Seat cloud provider blocked: externalization not allowed for this run.",
        )

    from local_ai.vision_execution import storage as St

    prof: dict[str, Any]
    if profile is not None:
        prof = profile
    elif principal.account_user_id:
        prof = St.get_user_llm_profile(principal.account_user_id)
    else:
        prof = {}

    gate = user_llm_adapter_gate_for_principal(principal, want, prof)
    if gate:
        return default_provider, _seat_fallback_note(
            requested_provider=want,
            default_provider=default_provider,
            reason_code="adapter_gate",
            principal=principal,
            detail=gate,
        )

    model = effective_default_model_for_profile(prof, want)

    if want == "ollama":
        base = (prof.get("ollama_base_url") or "").strip() or None
        om = (prof.get("ollama_model") or "").strip() or None
        return OllamaProvider(base_url=base, model=om), None

    if want == "openai":
        from local_ai.providers.openai import OpenAIProvider

        key, src = resolve_cloud_api_key(principal, "openai")
        if not key:
            return default_provider, _seat_fallback_note(
                requested_provider=want,
                default_provider=default_provider,
                reason_code="missing_api_key",
                principal=principal,
                credential_source=_credential_source_literal(src),
            )
        m = (model or "").strip() or default_model_hint("openai")
        return OpenAIProvider(model=m, api_key=key), None

    key, src = resolve_cloud_api_key(principal, want)
    if not key:
        return default_provider, _seat_fallback_note(
            requested_provider=want,
            default_provider=default_provider,
            reason_code="missing_api_key",
            principal=principal,
            credential_source=_credential_source_literal(src),
        )

    if want == "anthropic":
        return _AnthropicShim(key, model or None), None
    if want == "google":
        return _GoogleShim(key, model or None), None
    if want == "xai":
        return _XaiShim(key, model or None), None
    if want == "openrouter":
        return _OpenRouterShim(key, model or None), None
    if want == "meta":
        return _MetaShim(key, model or None), None

    return default_provider, _seat_fallback_note(
        requested_provider=want,
        default_provider=default_provider,
        reason_code="unknown_provider",
        principal=principal,
        detail=f"Provider {want!r} is not wired for council seats.",
    )
