"""
Model provider layer for Zenaf.

Prefer ``local_ai.llm.resolver.get_llm_adapter_for_principal`` for execution. This module
retains ``get_default_provider`` for narrow legacy/testing use only.
"""

from .meta import MetaProvider

from local_ai.execution_policy.run_context import get_policy_provider_override

# Protocol: any provider must implement generate(prompt, **kwargs) -> str


def get_default_provider():
    """Return the active model provider (Meta by default).

    When execution policy sets a per-request override (e.g. OpenAI), that instance is returned.
    """
    policy = get_policy_provider_override()
    if policy is not None:
        return policy
    return MetaProvider()


def get_council_provider():
    """
    Return a provider with ``.generate`` for council runs (anonymous principal).

    Prefer ``get_council_provider_for_principal`` from ``local_ai.llm.resolver`` when identity matters.
    """
    from local_ai.llm.execution_principal import anonymous_account_principal
    from local_ai.llm.resolver import get_council_provider_for_principal

    return get_council_provider_for_principal(anonymous_account_principal())


def describe_default_execution_policy():
    """
    Phase 0: introspection only. Matches ``resolve_execution_policy_for_action(None)``
    (same effective primary as ``OllamaProvider()`` / ``OLLAMA_MODEL``). Does not affect
    ``generate()`` or ``/run`` behavior.
    """
    from local_ai.execution_policy import ExecutionPolicyBlocked, resolve_execution_policy_for_action

    r = resolve_execution_policy_for_action(None, legacy_route="default")
    if isinstance(r, ExecutionPolicyBlocked):
        raise RuntimeError("unexpected execution policy block for null context")
    return r


def describe_council_execution_policy():
    """Phase 0: same effective primary as ``get_council_provider()`` (env + council model)."""
    from local_ai.execution_policy import ExecutionPolicyBlocked, resolve_execution_policy_for_action

    r = resolve_execution_policy_for_action(None, legacy_route="council")
    if isinstance(r, ExecutionPolicyBlocked):
        raise RuntimeError("unexpected execution policy block for null context")
    return r
