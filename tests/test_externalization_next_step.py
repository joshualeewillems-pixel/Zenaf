"""
Externalization v1: structured placeholders for workspace_next_step + OpenAI + subject_id.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient

from api.main import app
from local_ai.execution_policy.externalization import (
    apply_subject_id_mapping,
    make_placeholder_token,
    maybe_externalize_for_cloud,
    rebind_after_cloud_response,
    redact_externalization_for_privacy,
)
from local_ai.execution_policy.types import PolicyConfig
from local_ai.providers.ollama import OllamaProvider


def _policy_base(**kwargs) -> PolicyConfig:
    base = {
        "schema_version": 1,
        "global_priority": "balanced",
        "defaults": {
            "local": {"provider": "ollama", "model": None},
            "cloud": {"provider": "openai", "model": "gpt-4.1-mini"},
            "allow_cloud_fallback": True,
            "max_fallback_steps": 3,
        },
        "priority_profiles": {
            "balanced": {},
            "privacy": {"allow_cloud": False, "require_local": True},
        },
        "overrides_by_action_kind": {},
        "overrides_by_action_intent": {},
    }
    base.update(kwargs)
    return PolicyConfig.from_dict(base)


@pytest.fixture
def client():
    return TestClient(app)


def test_maybe_externalize_noop_local():
    r = maybe_externalize_for_cloud(
        mode="next_step",
        routing_context={"action_intent": "workspace_next_step"},
        exec_meta={"provider_used": "ollama"},
        internal_prompt="Context:\nhello\n\nResponse:",
        subject_id="x1",
    )
    assert r.strategy == "none"
    assert r.external_prompt == "Context:\nhello\n\nResponse:"


def test_apply_subject_id_mapping_and_roundtrip():
    sid = "proj-secret-99"
    internal = f"Context:\nTrack {sid} for Q2.\n\nResponse:"
    ext, pm = apply_subject_id_mapping(internal, sid)
    assert sid not in ext
    tok = make_placeholder_token("subject_id", sid)
    assert tok in ext
    raw_out = f"Recommendation: sync on {tok}\nRationale: test\n"
    rb = rebind_after_cloud_response(raw_out, pm)
    assert rb.integrity_ok
    assert rb.unresolved_tokens == ()
    assert rb.invalid_tokens_in_output == ()
    assert sid in rb.text
    assert tok not in rb.text


def test_rebind_mutated_checksum_fails():
    sid = "id-a"
    _, pm = apply_subject_id_mapping(f"x {sid} y", sid)
    tok = next(iter(pm.by_token.keys()))
    bad = re.sub(r":[a-f0-9]{8}\]\]$", ":ffffffff]]", tok)
    rb = rebind_after_cloud_response(f"Recommendation: {bad}\n", pm)
    assert not rb.integrity_ok
    assert bad in rb.invalid_tokens_in_output


def test_rebind_extra_unknown_token_fails():
    sid = "id-b"
    _, pm = apply_subject_id_mapping(f"context {sid} here", sid)
    other = make_placeholder_token("subject_id", "other-id")
    rb = rebind_after_cloud_response(f"Recommendation: {other}\n", pm)
    assert not rb.integrity_ok
    assert other in rb.invalid_tokens_in_output


def test_rebind_missing_echo_fails_unresolved():
    sid = "id-c"
    internal, pm = apply_subject_id_mapping(f"Goal {sid} end", sid)
    assert pm.tokens_sent
    rb = rebind_after_cloud_response("Recommendation: no placeholder here\nRationale: x\n", pm)
    assert len(rb.unresolved_tokens) == 1
    fully_ok = rb.integrity_ok and len(rb.unresolved_tokens) == 0
    assert not fully_ok


def test_redact_restricted_omits_token_strings():
    d = redact_externalization_for_privacy(
        privacy_mode="restricted",
        integrity_ok=False,
        unresolved_tokens=("[[ZENAF_REF:subject_id:xx:abcd1234]]",),
        invalid_tokens=("[[ZENAF_REF:subject_id:yy:deadbeef]]",),
    )
    assert d["externalization_integrity_ok"] is False
    assert d["externalization_unresolved_count"] == 1
    assert d["externalization_invalid_count"] == 1
    assert "externalization_unresolved_tokens" not in d
    assert "externalization_invalid_tokens" not in d


def test_redact_normal_includes_lists():
    d = redact_externalization_for_privacy(
        privacy_mode="normal",
        integrity_ok=True,
        unresolved_tokens=(),
        invalid_tokens=(),
    )
    assert d["externalization_unresolved_tokens"] == []
    assert d["externalization_invalid_tokens"] == []


def test_post_run_next_step_externalization_e2e(client, monkeypatch):
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "local-m", raising=False)
    monkeypatch.setattr(
        "local_ai.execution_policy.seam_routing._ollama_reachable_for_seam_fallback",
        lambda: True,
    )

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_next_step": {"primary": {"provider": "openai", "model": "gpt-4o-mini"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    sid = "initiative-uuid-7f2a"
    tok = make_placeholder_token("subject_id", sid)

    def fake_generate(self, prompt, *, timeout=None):
        import json

        assert sid not in prompt
        assert tok in prompt
        return json.dumps(
            {
                "recommendation": f"Follow up on {tok}",
                "rationale": "ok",
                "alternatives": [],
                "caution": None,
            }
        )

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)
    r = client.post(
        "/run",
        json={
            "mode": "next_step",
            "params": {"question": "What next?"},
            "context": {
                "context_block": f"Active initiative {sid} needs a decision.",
                "subject_id": sid,
            },
            "routing_context": {
                "surface": "workspace_organizer",
                "action_kind": "structured_evaluation",
                "action_intent": "workspace_next_step",
            },
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    rec = data["result"]["recommendation"]
    assert sid in rec
    assert tok not in rec
    assert data.get("externalization_integrity_ok") is True
    assert data.get("delegation_path") == "structured_cloud_v1"


@pytest.mark.parametrize(
    "mode,intent,prov,expect",
    [
        ("analyze", "workspace_next_step", "openai", "none"),
        ("next_step", "workspace_analyze", "openai", "none"),
    ],
)
def test_maybe_externalize_only_next_step_intent(mode, intent, prov, expect):
    r = maybe_externalize_for_cloud(
        mode=mode,
        routing_context={"action_intent": intent},
        exec_meta={"provider_used": prov},
        internal_prompt=f"Context:\nx y\n\nResponse:",
        subject_id="x",
    )
    assert r.strategy == expect
