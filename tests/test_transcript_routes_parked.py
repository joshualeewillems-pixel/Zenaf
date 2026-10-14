"""Transcript sorter router must stay importable when the parked backend is absent.

Regression (2026-10-14): the prod Docker image does not ship parked/, so
`from sorter import sort_transcript` raised ModuleNotFoundError there, the
/transcripts router died at import, and (after the PR #44 startup check) the
server refused to boot — staging crash-looped. The router must degrade to a
clear 503 on the deprecated endpoint, never die at import.
"""
from __future__ import annotations

import builtins
import importlib
import sys

import pytest
from fastapi import HTTPException

import api.routes.transcript_routes as tr


def test_module_imports_when_sorter_backend_missing(monkeypatch):
    """Simulate prod (no parked/): `import sorter` raises -> module still imports."""
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sorter":
            raise ImportError("No module named 'sorter' (simulated prod image)")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules.pop("api.routes.transcript_routes", None)
    try:
        mod = importlib.import_module("api.routes.transcript_routes")
    finally:
        # Evict again so later imports get the genuine module back.
        sys.modules.pop("api.routes.transcript_routes", None)
    assert mod.sort_transcript is None
    assert mod.router is not None
    assert len(mod.router.routes) > 0


def test_sort_endpoint_503_when_backend_parked(monkeypatch):
    monkeypatch.setattr(tr, "sort_transcript", None)
    body = tr.TranscriptSortBody(raw_transcript_text="hello world")
    with pytest.raises(HTTPException) as exc_info:
        tr.post_sort_transcript(body)
    assert exc_info.value.status_code == 503
    assert "parked" in exc_info.value.detail


def test_sort_endpoint_400_on_empty_text():
    body = tr.TranscriptSortBody(raw_transcript_text="   ")
    with pytest.raises(HTTPException) as exc_info:
        tr.post_sort_transcript(body)
    assert exc_info.value.status_code == 400
