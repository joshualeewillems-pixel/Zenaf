"""
Vision Execution LLM calls: unified ``get_llm_adapter_for_principal`` (profile, credentials,
and any active ``run_context`` policy / Ollama model overrides from ``apply_seam_routing``).
"""

from __future__ import annotations

from typing import Any

from local_ai.llm.adapter import LLMRequest
from local_ai.llm.execution_principal import ExecutionPrincipal


def ve_eval_provider_shim(principal: ExecutionPrincipal, *, use_execution_seam: bool) -> Any:
    """
    Object with ``.generate(prompt, timeout=...) -> str``.

    ``use_execution_seam`` is retained for call-site compatibility; effective routing comes
    from whether the caller wrapped the run in ``apply_seam_routing`` (context overrides).
    """
    _ = use_execution_seam
    from local_ai.llm.resolver import get_llm_adapter_for_principal

    adapter = get_llm_adapter_for_principal(principal)

    class _Shim:
        def generate(self, prompt: str, *, timeout: int | None = 60) -> str:
            return adapter.generate_text(LLMRequest(task="ve_eval", prompt=prompt, timeout=timeout))

    return _Shim()
