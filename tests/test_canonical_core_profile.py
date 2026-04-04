"""Canonical core profile resolver (Phase 2 convergence)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.vision_execution import service as VeService


def test_canonical_core_profile_first_of_list_order(monkeypatch):
    """Resolver must match ordered ``list_core_profiles`` head (primary first, then newest)."""

    def fake_list(uid: str):
        assert uid == "u1"
        return [{"id": "winner"}, {"id": "other"}]

    monkeypatch.setattr("local_ai.vision_execution.service.S.list_core_profiles", fake_list)
    row = VeService.canonical_core_profile_for_user("u1")
    assert row == {"id": "winner"}


def test_canonical_core_profile_empty(monkeypatch):
    monkeypatch.setattr("local_ai.vision_execution.service.S.list_core_profiles", lambda _uid: [])
    assert VeService.canonical_core_profile_for_user("u-empty") is None
