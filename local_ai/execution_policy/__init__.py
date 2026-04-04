"""
Execution policy resolver: routing metadata → provider/model plan; optional ``/run`` wiring
for Ollama model override and OpenAI primary (see ``api.main._begin_run_routing``).
"""

from .load import default_policy_path, load_execution_policy_config
from .privacy_apply import (
    DEFAULT_PRIVACY_POLICY_INPUT,
    ExecutionPolicyBlocked,
    ExecutionPolicyOutcome,
    PrivacyPolicyInput,
    PrivacyPolicyInputPartial,
    apply_privacy_to_execution_resolution,
    apply_trace_privacy_redaction,
    merge_privacy_policy_input,
    provider_execution_tier,
)
from .resolve import resolve_execution_policy_for_action
from .seam_routing import SUPPORTED_SEAM_PROVIDERS, apply_seam_routing
from .run_context import (
    RoutingTeardown,
    end_execution_routing,
    get_ollama_model_override,
    get_policy_provider_override,
    ollama_model_override,
    push_ollama_model_override,
    push_policy_provider_override,
    reset_ollama_model_override,
    reset_policy_provider_override,
)
from .types import (
    ActionRoutingContext,
    ExecutionPolicyResolution,
    PolicyConfig,
    ProviderModelRef,
)

__all__ = [
    "DEFAULT_PRIVACY_POLICY_INPUT",
    "ActionRoutingContext",
    "ExecutionPolicyBlocked",
    "ExecutionPolicyOutcome",
    "ExecutionPolicyResolution",
    "PolicyConfig",
    "PrivacyPolicyInput",
    "PrivacyPolicyInputPartial",
    "ProviderModelRef",
    "RoutingTeardown",
    "SUPPORTED_SEAM_PROVIDERS",
    "apply_privacy_to_execution_resolution",
    "apply_seam_routing",
    "apply_trace_privacy_redaction",
    "default_policy_path",
    "end_execution_routing",
    "merge_privacy_policy_input",
    "provider_execution_tier",
    "get_ollama_model_override",
    "get_policy_provider_override",
    "load_execution_policy_config",
    "ollama_model_override",
    "push_ollama_model_override",
    "push_policy_provider_override",
    "reset_ollama_model_override",
    "reset_policy_provider_override",
    "resolve_execution_policy_for_action",
]
