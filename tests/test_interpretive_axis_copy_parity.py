"""
Parity: Python _INTERPRETIVE_AXIS_COPY_FALLBACK must match canonical JSON on disk.

If they drift, runtime loads correct JSON in dev but broken deploys could serve stale copy.
No persistence or new modules — test-only safeguard.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_ai.developmental_guidance import _INTERPRETIVE_AXIS_COPY_FALLBACK


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _canonical_json_path() -> Path:
    return (
        _repo_root()
        / "frontend"
        / "src"
        / "developmentalGuidance"
        / "interpretive_axis_copy.json"
    )


def test_interpretive_axis_fallback_matches_canonical_json() -> None:
    path = _canonical_json_path()
    if not path.is_file():
        pytest.skip(f"Canonical JSON not at {path} (parity check skipped)")

    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    for key in ("axisNames", "tilts", "labels"):
        assert key in data, f"JSON missing required key {key!r}"
        assert key in _INTERPRETIVE_AXIS_COPY_FALLBACK, f"Fallback missing {key!r}"

    for key in ("axisNames", "tilts", "labels"):
        assert data[key] == _INTERPRETIVE_AXIS_COPY_FALLBACK[key], (
            f"interpretive_axis_copy.json[{key!r}] != _INTERPRETIVE_AXIS_COPY_FALLBACK[{key!r}]. "
            "Update the Python fallback in local_ai/developmental_guidance.py to match the JSON."
        )
