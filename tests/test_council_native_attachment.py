"""Council native main attachment default for authenticated principals."""
from __future__ import annotations

from unittest.mock import patch

from local_ai.llm.execution_principal import anonymous_account_principal, authenticated_account_principal
from local_ai.llm import resolver as R


def test_council_authenticated_main_cloud_when_profile_default_openai():
    pr = authenticated_account_principal("u-main-1")
    prof = {"default_provider": "openai", "default_model": "gpt-4o-mini"}

    with patch.object(R, "_profile_for_principal", return_value=prof):
        with patch.object(R, "user_llm_adapter_gate_for_principal", return_value=None):
            with patch.object(R, "resolve_cloud_api_key", return_value=("sk-x", "env")):
                with patch("local_ai.execution_policy.run_context.get_policy_provider_override", return_value=None):
                    with patch("local_ai.execution_policy.run_context.get_ollama_model_override", return_value=None):
                        ad = R.get_council_llm_adapter_for_principal(pr)
    assert isinstance(ad, R._CloudLLMAdapter)
    assert ad._provider == "openai"
    tr = R.peek_council_native_attachment_trace()
    assert tr is not None
    assert tr["council_native_attachment_requested"] == "main"
    assert tr["council_native_attachment_resolved"] == "main"
    assert tr.get("council_native_fallback_reason") is None


def test_council_authenticated_fallback_local_when_no_cloud_key():
    pr = authenticated_account_principal("u-main-2")
    prof = {"default_provider": "openai", "default_model": "gpt-4o-mini"}

    with patch.object(R, "_profile_for_principal", return_value=prof):
        with patch.object(R, "user_llm_adapter_gate_for_principal", return_value=None):
            with patch.object(R, "resolve_cloud_api_key", return_value=(None, "none")):
                with patch("local_ai.execution_policy.run_context.get_policy_provider_override", return_value=None):
                    with patch("local_ai.execution_policy.run_context.get_ollama_model_override", return_value=None):
                        with patch.dict("os.environ", {"ZENAF_COUNCIL_MODEL": "mycouncil"}, clear=False):
                            ad = R.get_council_llm_adapter_for_principal(pr)
    assert isinstance(ad, R._OllamaLLMAdapter)
    assert ad._inner.model == "mycouncil"
    tr = R.peek_council_native_attachment_trace()
    assert tr["council_native_attachment_resolved"] == "local_fallback"
    assert tr.get("council_native_fallback_reason")
    assert tr.get("council_native_stack_lane") == "env_council_model"


def test_council_anonymous_skips_main_attachment_branch():
    pr = anonymous_account_principal()
    prof = {"default_provider": "openai", "default_model": "gpt-4o-mini"}

    with patch.object(R, "_profile_for_principal", return_value=prof):
        with patch.object(R, "user_llm_adapter_gate_for_principal", return_value=None):
            with patch("local_ai.execution_policy.run_context.get_policy_provider_override", return_value=None):
                with patch("local_ai.execution_policy.run_context.get_ollama_model_override", return_value=None):
                    with patch.dict("os.environ", {"ZENAF_COUNCIL_MODEL": "anonmodel"}, clear=False):
                        ad = R.get_council_llm_adapter_for_principal(pr)
    assert isinstance(ad, R._OllamaLLMAdapter)
    tr = R.peek_council_native_attachment_trace()
    assert tr["council_native_attachment_requested"] is None
    assert tr["council_native_attachment_resolved"] == "council_local_stack"


def test_privacy_gate_skips_main_attachment():
    pr = authenticated_account_principal("u-main-privacy")
    prof = {"default_provider": "openai", "default_model": "gpt-4o-mini"}

    with patch.object(R, "_profile_for_principal", return_value=prof):
        with patch.object(R, "user_llm_adapter_gate_for_principal", return_value=None):
            with patch.object(R, "resolve_cloud_api_key", return_value=("sk-x", "env")):
                with patch("local_ai.execution_policy.run_context.get_policy_provider_override", return_value=None):
                    with patch("local_ai.execution_policy.run_context.get_ollama_model_override", return_value=None):
                        with patch.dict("os.environ", {"ZENAF_COUNCIL_MODEL": "priv-local"}, clear=False):
                            ad = R.get_council_llm_adapter_for_principal(
                                pr, allows_externalization=False
                            )
    assert isinstance(ad, R._OllamaLLMAdapter)
    assert ad._inner.model == "priv-local"
    tr = R.peek_council_native_attachment_trace()
    assert tr["council_native_attachment_requested"] == "main"
    assert tr["council_native_attachment_resolved"] == "local"
    assert tr["council_native_fallback_reason"] == "privacy_requires_local"


def test_explicit_native_provider_skips_attachment_trace_main():
    pr = authenticated_account_principal("u-main-3")
    prof = {"default_provider": "openai", "default_model": "gpt-4o-mini"}

    with patch.object(R, "_profile_for_principal", return_value=prof):
        with patch.object(R, "user_llm_adapter_gate_for_principal", return_value=None):
            with patch("local_ai.execution_policy.run_context.get_policy_provider_override", return_value=None):
                with patch("local_ai.execution_policy.run_context.get_ollama_model_override", return_value=None):
                    with patch.object(R, "resolve_cloud_api_key", return_value=("k", "env")):
                        ad = R.get_council_llm_adapter_for_principal(
                            pr, force_provider="openai", force_model="gpt-4.1-mini"
                        )
    assert isinstance(ad, R._CloudLLMAdapter)
    tr = R.peek_council_native_attachment_trace()
    assert tr["council_native_attachment_resolved"] == "explicit_native_provider"
