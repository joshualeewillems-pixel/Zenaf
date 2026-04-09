"""Optional operator brief env gate (ZENAF_OPERATOR_BRIEF_ENABLED)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_operator_brief_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENAF_OPERATOR_BRIEF_ENABLED", "0")
    import local_ai.context.phil_context as pc

    importlib.reload(pc)
    try:
        assert pc.load_operator_priority() == ""
        assert pc.load_philosophical_orientation() == ""
    finally:
        monkeypatch.delenv("ZENAF_OPERATOR_BRIEF_ENABLED", raising=False)
        importlib.reload(pc)


def test_operator_brief_false_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENAF_OPERATOR_BRIEF_ENABLED", "false")
    import local_ai.context.phil_context as pc

    importlib.reload(pc)
    try:
        assert pc.load_operator_priority() == ""
    finally:
        monkeypatch.delenv("ZENAF_OPERATOR_BRIEF_ENABLED", raising=False)
        importlib.reload(pc)
