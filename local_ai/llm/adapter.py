from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from local_ai.llm.execution_principal import ExecutionPrincipal, anonymous_account_principal


class LLMAdapter(Protocol):
    def generate_text(self, request: "LLMRequest") -> str:
        ...


@dataclass(frozen=True)
class LLMRequest:
    task: str
    prompt: str
    timeout: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PrincipalTaggedResolverAdapter:
    """
    Content / seam-tagged calls: resolve via ``get_llm_adapter_for_principal`` (policy overrides,
    routed Ollama model, profile + credentials). Merges principal fields into request metadata.
    """

    principal: ExecutionPrincipal
    _inner: LLMAdapter | None = field(default=None, init=False, repr=False)

    def generate_text(self, request: LLMRequest) -> str:
        if not isinstance(self.principal, ExecutionPrincipal):
            raise TypeError("principal must be ExecutionPrincipal")
        if self._inner is None:
            from local_ai.llm.resolver import get_llm_adapter_for_principal

            self._inner = get_llm_adapter_for_principal(self.principal)
        meta = {
            **request.metadata,
            "execution_principal_ref": self.principal.principal_ref,
            "execution_scope": self.principal.scope,
            "credential_namespace": self.principal.credential_namespace,
            "policy_namespace": self.principal.policy_namespace,
        }
        return self._inner.generate_text(
            LLMRequest(task=request.task, prompt=request.prompt, timeout=request.timeout, metadata=meta)
        )


@dataclass(frozen=True)
class BlockedLLMAdapter:
    """User-facing block (e.g. provider disabled or missing key when adapter was requested)."""

    reason: str

    def generate_text(self, request: LLMRequest) -> str:
        raise RuntimeError(self.reason)


def get_llm_adapter(execution_principal: ExecutionPrincipal | None = None) -> LLMAdapter:
    p: ExecutionPrincipal = execution_principal if execution_principal is not None else anonymous_account_principal()
    if not isinstance(p, ExecutionPrincipal):
        raise TypeError("execution_principal must be ExecutionPrincipal or None")
    return PrincipalTaggedResolverAdapter(principal=p)


# Profile-scoped execution: `get_llm_adapter_for_principal` in `local_ai.llm.resolver`.
