"""Tests for read-only provider default inspection (no execution)."""

from __future__ import annotations

from local_ai.execution_policy.provider_default_inspect import (
    IMPLICIT_DEFAULT_SOURCES,
    build_normalized_policy_payload,
    build_provider_policy_for_current_user,
    build_provider_resolution_for_run,
    inspect_usable_providers_for_principal,
)
from local_ai.llm.execution_principal import anonymous_account_principal, authenticated_account_principal


def test_implicit_sources_non_empty():
    assert len(IMPLICIT_DEFAULT_SOURCES) >= 3
    assert any(s.get("id") == "resolver_council" for s in IMPLICIT_DEFAULT_SOURCES)


def test_normalized_payload_has_planes():
    p = build_normalized_policy_payload()
    assert p["schema_version"] == 1
    assert "planes" in p
    assert "account_authenticated" in p["planes"]
    assert "account_anonymous" in p["planes"]
    assert "system" in p["planes"]
    assert "fallback_order_explanation" in p
    assert "example_routing_intent_workspace_council" in p


def test_usable_providers_shape():
    rows = inspect_usable_providers_for_principal(anonymous_account_principal())
    assert isinstance(rows, list)
    assert all("provider_id" in r and "usable_for_execution" in r for r in rows)


def test_build_provider_policy_includes_credential_visibility():
    pol = build_provider_policy_for_current_user("u-cred-vis")
    cv = (pol.get("current_session") or {}).get("credential_visibility")
    assert isinstance(cv, dict)
    assert cv.get("anonymous_openai_cloud_allowed") is False
    assert cv.get("system", {}).get("openai_env_var") == "ZENAF_SYSTEM_OPENAI_KEY"
    assert "openai_configured" in cv.get("system", {})
    aa = cv.get("account_authenticated") or {}
    assert aa.get("openai_effective_source") in ("env", "settings", "none")


def test_build_provider_resolution_minimal():
    pr = authenticated_account_principal("u-test-inspect")
    trace = build_provider_resolution_for_run(
        mode="council",
        params=None,
        principal=pr,
        exec_meta={},
        routing_context=None,
        teacher_meta=None,
    )
    assert trace["mode"] == "council"
    assert trace["routing_context_present"] is False
    assert trace["externalization_allowed"] is True
    assert trace.get("cloud_blocked_reason") is None
    assert trace["seam"] is not None
    assert trace["council"] is not None


def test_build_provider_resolution_externalization_default_denied_with_routing():
    from api.main import RunRoutingContext

    pr = authenticated_account_principal("u-test-inspect-2")
    rc = RunRoutingContext(
        surface="workspace_organizer",
        action_kind="structured_evaluation",
        action_intent="workspace_council",
    )
    trace = build_provider_resolution_for_run(
        mode="council",
        params=None,
        principal=pr,
        exec_meta={},
        routing_context=rc,
        teacher_meta={
            "council_native_attachment_trace": {
                "council_native_fallback_reason": "privacy_requires_local",
            },
            "teacher_skipped_reason": "privacy_requires_local",
        },
    )
    assert trace["routing_context_present"] is True
    assert trace["externalization_allowed"] is False
    assert trace["cloud_blocked_reason"] == "native_main_attachment:privacy_requires_local; teacher:privacy_requires_local"
