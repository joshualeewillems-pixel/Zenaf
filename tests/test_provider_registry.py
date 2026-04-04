"""Provider registry: prefs, gating, status rows (no DB required for pure logic)."""
from __future__ import annotations

from unittest.mock import patch

from local_ai.llm.execution_principal import (
    anonymous_account_principal,
    authenticated_account_principal,
)


def test_pref_enabled_defaults_true() -> None:
    from local_ai.llm.provider_registry import pref_enabled

    assert pref_enabled({}, "openai") is True
    assert pref_enabled({"openai": {}}, "openai") is True
    assert pref_enabled({"openai": {"enabled": True}}, "openai") is True
    assert pref_enabled({"openai": {"enabled": False}}, "openai") is False


def test_execution_gate_blocks_when_disabled() -> None:
    from local_ai.llm.provider_registry import execution_provider_gate_for_principal

    profile = {"provider_prefs": {"openai": {"enabled": False}}}
    msg = execution_provider_gate_for_principal(authenticated_account_principal("user-1"), "openai", profile)
    assert msg
    assert "disabled" in msg.lower()


def test_execution_gate_skips_when_no_user() -> None:
    from local_ai.llm.provider_registry import execution_provider_gate_for_principal

    profile = {"provider_prefs": {"openai": {"enabled": False}}}
    assert execution_provider_gate_for_principal(anonymous_account_principal(), "openai", profile) is None


def test_adapter_gate_requires_key_when_enabled() -> None:
    from local_ai.llm.provider_registry import user_llm_adapter_gate_for_principal

    profile = {"provider_prefs": {}}
    with patch("local_ai.vision_execution.storage.get_decrypted_llm_api_key", return_value=None):
        msg = user_llm_adapter_gate_for_principal(authenticated_account_principal("u1"), "anthropic", profile)
    assert msg
    assert "key" in msg.lower()


def test_build_rows_includes_all_execution_providers() -> None:
    from local_ai.llm.provider_registry import EXECUTION_PROVIDER_IDS, build_provider_status_rows_for_principal

    profile = {"provider_prefs": {}, "default_provider": "ollama", "default_model": None, "ollama_model": None}
    creds = {p: False for p in ("openai", "anthropic", "google", "xai")}
    rows = build_provider_status_rows_for_principal(authenticated_account_principal("u1"), profile, creds)
    assert [r["id"] for r in rows] == list(EXECUTION_PROVIDER_IDS)
