"""Meeting extract profile guidance: canonical user core vs templates."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.vision_execution.meeting_extract import _resolve_profile_guidance


def test_resolve_profile_guidance_explicit_template():
    g = _resolve_profile_guidance("clinic_operations", None)
    assert isinstance(g, dict)
    assert "initiative" in g


def test_resolve_profile_guidance_canonical_user(monkeypatch):
    def fake_canonical(uid: str):
        assert uid == "u1"
        return {
            "id": "cp1",
            "core_definition": "Ship fast",
            "current_goals": "Close the loop",
        }

    monkeypatch.setattr(
        "local_ai.vision_execution.service.canonical_core_profile_for_user",
        fake_canonical,
    )
    g = _resolve_profile_guidance(None, "u1")
    assert "Ship fast" in str(g.get("initiative") or "")


def test_resolve_profile_guidance_no_user_falls_back_template():
    g = _resolve_profile_guidance(None, None)
    assert isinstance(g, dict)
    assert g
