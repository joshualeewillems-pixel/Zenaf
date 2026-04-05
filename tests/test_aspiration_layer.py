"""Aspiration layer: derivation, policy, and storage helpers."""

from __future__ import annotations

from datetime import timedelta

import pytest

from local_ai.council_preflight import CouncilPreflight, parse_preflight_from_request


def test_parse_preflight_explicit_guidance_request():
    ctx = {"council_preflight": {"explicit_guidance_request": True}}
    p = parse_preflight_from_request(ctx, "help me reflect")
    assert p.explicit_guidance_request is True


def test_derive_aspiration_signal_sparse(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai import aspiration_layer as AL

    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_aspiration_profile",
        lambda uid: None,
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_resonance_pattern",
        lambda uid, **kw: {"escalation_signal": {"confidence": 0.2, "current_level": 1}},
    )
    sig = AL.derive_aspiration_signal("user-1")
    assert sig["confidence"] <= 0.95
    assert isinstance(sig["basis"], list)
    assert "dominant_aspiration_vector" in sig


def test_should_invoke_requires_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai import aspiration_layer as AL

    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: True)
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.user_permission_enabled",
        lambda uid, key: False,
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_aspiration_profile",
        lambda uid: {
            "core_aim": "Build calm systems",
            "use_in_guidance": True,
            "growth_domains": [],
        },
    )
    invoke, reasons, conf = AL.should_invoke_aspirational_guidance(
        user_id="u1",
        preflight=CouncilPreflight(active_surface="core_profile"),
    )
    assert invoke is False
    assert "permission_aspiration_use_denied" in reasons


def test_should_invoke_when_gates_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai import aspiration_layer as AL

    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: True)
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.user_permission_enabled",
        lambda uid, key: key == "aspiration_use_in_guidance",
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_aspiration_profile",
        lambda uid: {
            "core_aim": "Ship useful tools",
            "use_in_guidance": True,
            "growth_domains": ["craft"],
            "guidance_preferences": {},
        },
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_resonance_pattern",
        lambda uid, **kw: {"escalation_signal": {"confidence": 0.3, "current_level": 2}},
    )
    invoke, reasons, _conf = AL.should_invoke_aspirational_guidance(
        user_id="u1",
        preflight=CouncilPreflight(
            active_surface="core_profile",
            developmental_guidance={
                "as_of": "2026-01-01T00:00:00Z",
                "evidence_refs": [],
                "signals_summary": {"test": 1},
                "hypotheses": [
                    {
                        "kind": "friction",
                        "statement": "Test hypothesis line",
                        "confidence": "low",
                        "basis": [],
                    }
                ],
                "suggested_guidance_style": "neutral",
            },
        ),
    )
    assert invoke is True
    assert "aspiration_present" in reasons


def test_format_block_omitted_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai import aspiration_layer as AL

    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: False)
    text, exp = AL.format_aspiration_augmentation_block(
        "u1",
        preflight=CouncilPreflight(active_surface="core_profile"),
    )
    assert text is None
    assert "aspiration_guidance_feature_off" in exp.get("reason_codes", [])


def test_prompt_contract_uses_smart_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai import aspiration_layer as AL

    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: True)
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.user_permission_enabled",
        lambda uid, key: key == "aspiration_use_in_guidance",
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_aspiration_profile",
        lambda uid: {
            "core_aim": "A" * 2000,
            "current_edge": "B" * 2000,
            "current_obstacles": "C" * 2000,
            "use_in_guidance": True,
            "growth_domains": ["craft"],
            "guidance_preferences": {"style": "socratic"},
        },
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_resonance_pattern",
        lambda uid, **kw: {"average_score": 0.8, "total_ratings": 20, "high_resonance_count": 16, "low_resonance_count": 1},
    )
    text, exp = AL.format_aspiration_augmentation_block("u1", preflight=CouncilPreflight(active_surface="core_profile"))
    assert isinstance(text, str)
    assert len(text) <= 780
    assert "Socratic questioning" in text
    assert exp.get("augmentation_chars", 0) <= 780


def test_inference_proposals_require_significant_interaction_and_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai import aspiration_layer as AL

    logs: list[dict] = []
    monkeypatch.setattr(AL, "aspiration_inference_enabled", lambda: True)
    monkeypatch.setattr("local_ai.vision_execution.storage.user_permission_enabled", lambda uid, key: True)
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_aspiration_profile",
        lambda uid: {"allow_inference": True, "core_aim": "", "growth_domains": []},
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.list_aspiration_proposals",
        lambda uid, status=None: [],
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.append_aspiration_inference_log",
        lambda uid, snapshot: logs.append(snapshot),
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_resonance_pattern",
        lambda uid, **kw: {"total_ratings": 3, "high_resonance_count": 1, "average_score": 0.6},
    )
    out = AL.get_aspiration_inference_proposals("u1")
    assert out == []
    assert any(x.get("event") == "proposal_scan_skipped" for x in logs)


def test_action_directive_injected_for_decisiveness_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai import aspiration_layer as AL

    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: True)
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.user_permission_enabled",
        lambda uid, key: key == "aspiration_use_in_guidance",
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_aspiration_profile",
        lambda uid: {
            "core_aim": "Be more decisive",
            "use_in_guidance": True,
            "growth_domains": ["execution"],
            "current_edge": "Decisiveness under ambiguity",
            "current_obstacles": "Option sprawl",
            "guidance_preferences": {"style": "challenge"},
            "updated_at": "2026-03-30T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_resonance_pattern",
        lambda uid, **kw: {
            "average_score": 0.3,
            "low_resonance_count": 8,
            "high_resonance_count": 1,
            "total_ratings": 10,
            "escalation_signal": {"current_level": 4, "confidence": 0.82, "recommended_approach": "challenge"},
        },
    )
    text, exp = AL.format_aspiration_augmentation_block(
        "u1",
        preflight=CouncilPreflight(active_surface="core_profile"),
    )
    assert isinstance(text, str)
    assert "[STRATEGIC ADAPTATION:" in text
    assert "Limit to 2 options and require a selection before proceeding." in text
    assert "directive" in exp


def test_action_directive_soft_exit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai import aspiration_layer as AL

    monkeypatch.setattr(AL, "aspiration_guidance_injection_enabled", lambda: True)
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.user_permission_enabled",
        lambda uid, key: key == "aspiration_use_in_guidance",
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_aspiration_profile",
        lambda uid: {
            "core_aim": "Be more decisive",
            "use_in_guidance": True,
            "growth_domains": ["execution"],
            "current_edge": "Decisiveness",
            "current_obstacles": "Overthinking",
            "guidance_preferences": {"style": "challenge"},
            "updated_at": "2026-03-30T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_resonance_pattern",
        lambda uid, **kw: {
            "average_score": 0.3,
            "low_resonance_count": 7,
            "high_resonance_count": 1,
            "total_ratings": 9,
            "escalation_signal": {"current_level": 4, "confidence": 0.85, "recommended_approach": "challenge"},
        },
    )
    text, _exp = AL.format_aspiration_augmentation_block(
        "u1",
        preflight=CouncilPreflight(
            active_surface="core_profile",
            user_question="Stop forcing me to choose, I need to brainstorm first.",
        ),
    )
    assert isinstance(text, str)
    assert "Suspend forced-choice directives temporarily" in text


def test_time_decay_reduces_stale_signal_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai import aspiration_layer as AL

    fixed_now = AL.datetime(2026, 3, 30, 0, 0, 0, tzinfo=AL.timezone.utc)
    monkeypatch.setattr(AL, "_now_utc", lambda: fixed_now)

    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_resonance_pattern",
        lambda uid, **kw: {"average_score": 0.8, "high_resonance_count": 8, "low_resonance_count": 1, "total_ratings": 10},
    )

    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_aspiration_profile",
        lambda uid: {
            "core_aim": "Grow clarity",
            "growth_domains": ["clarity"],
            "current_edge": "Choose faster",
            "current_obstacles": "",
            "near_term_aspirations": "",
            "anti_goals": "",
            "updated_at": (fixed_now - timedelta(days=21)).isoformat(),
        },
    )
    stale = AL.derive_aspiration_signal("u1")

    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_aspiration_profile",
        lambda uid: {
            "core_aim": "Grow clarity",
            "growth_domains": ["clarity"],
            "current_edge": "Choose faster",
            "current_obstacles": "",
            "near_term_aspirations": "",
            "anti_goals": "",
            "updated_at": fixed_now.isoformat(),
        },
    )
    fresh = AL.derive_aspiration_signal("u1")

    assert stale["confidence"] < fresh["confidence"]
    assert stale["time_decay_factor"] < fresh["time_decay_factor"]


def test_upsert_aspiration_profile_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai.vision_execution import models as M
    from local_ai.vision_execution import storage as St

    monkeypatch.setattr(St, "_DB_PATH", tmp_path / "ve.db")
    uid = M.new_id()
    conn = St.get_connection()
    now = St._now()
    conn.execute(
        "INSERT INTO users (id, email, password_hash, display_name, is_admin, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, ?, ?)",
        (uid, f"{uid}@t.local", "x", "T", now, now),
    )
    conn.commit()
    row = St.upsert_aspiration_profile(
        uid,
        {
            "core_aim": "Test aim",
            "growth_domains": ["a", "b"],
            "use_in_guidance": True,
            "allow_inference": False,
        },
    )
    assert row["core_aim"] == "Test aim"
    assert row["growth_domains"] == ["a", "b"]
    assert row["use_in_guidance"] is True
    patched = St.patch_aspiration_profile(uid, {"current_edge": "Edge"})
    assert patched and patched.get("current_edge") == "Edge"
