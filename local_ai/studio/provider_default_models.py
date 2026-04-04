"""
Canonical default model IDs per execution provider for Studio / admin hints.

Uses ``local_ai.llm.provider_registry.default_model_hint`` so UI and bakeoffs stay aligned
with provider modules (google_genai.DEFAULT_MODEL, xai.DEFAULT_MODEL, etc.).
"""

from __future__ import annotations

from typing import Any

from local_ai.llm.provider_registry import EXECUTION_PROVIDER_IDS, default_model_hint


def build_provider_default_models_map() -> dict[str, str]:
    """Provider id -> recommended default model id string (non-empty for known providers)."""
    out: dict[str, str] = {}
    for pid in EXECUTION_PROVIDER_IDS:
        h = (default_model_hint(pid) or "").strip()
        if h:
            out[pid] = h
    return out


def default_models_response_payload() -> dict[str, Any]:
    """JSON-serializable payload for GET /studio/provider-default-models."""
    m = build_provider_default_models_map()
    return {
        **m,
        "source": "local_ai.llm.provider_registry.default_model_hint (per provider module DEFAULT_MODEL / config)",
    }
