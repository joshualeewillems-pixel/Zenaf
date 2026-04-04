"""Load execution policy JSON from disk with embedded fallback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

from .types import PolicyConfig

_EMBEDDED_FALLBACK: dict[str, Any] = {
    "schema_version": 1,
    "global_priority": "balanced",
    "defaults": {
        "local": {"provider": "ollama", "model": None},
        "cloud": {"provider": "ollama", "model": None},
        "allow_cloud_fallback": True,
        "max_fallback_steps": 3,
    },
    "priority_profiles": {
        "balanced": {},
        "quality": {"prefer_cloud": True},
        "speed": {"prefer_cloud": False},
        "cost": {"prefer_cloud": False, "prefer_smaller_model": True},
        "privacy": {"allow_cloud": False, "require_local": True},
    },
    "overrides_by_action_kind": {},
    "overrides_by_action_intent": {
        "idea_evaluate": {"primary": {"provider": "ollama", "model": None}},
        "initiative_evaluate": {"primary": {"provider": "ollama", "model": None}},
        "workspace_council": {"primary": {"provider": "ollama", "model": None}},
        "workspace_next_step": {"primary": {"provider": "ollama", "model": None}},
        "workspace_web_research": {"primary": {"provider": "ollama", "model": None}},
        "workspace_reassess": {"primary": {"provider": "ollama", "model": None}},
        "workspace_folder_advisor": {"primary": {"provider": "ollama", "model": None}},
        "meeting_extract_single": {"primary": {"provider": "ollama", "model": None}},
        "meeting_extract_chunks": {"primary": {"provider": "ollama", "model": None}},
        "meeting_extract_synthesis": {"primary": {"provider": "ollama", "model": None}},
        "candidate_placement_suggest": {"primary": {"provider": "ollama", "model": None}},
        "candidate_presort_triage": {"primary": {"provider": "ollama", "model": None}},
        "node_transform_suggest": {"primary": {"provider": "ollama", "model": None}},
        "meeting_harvest": {"primary": {"provider": "ollama", "model": None}},
        "meeting_harvest_normalize": {"primary": {"provider": "ollama", "model": None}},
    },
}


def default_policy_path() -> Path:
    """Repo root config path: ``config/ai_execution_policy.json``."""
    return Path(__file__).resolve().parents[2] / "config" / "ai_execution_policy.json"


def load_execution_policy_config(path: Optional[Path] = None) -> PolicyConfig:
    """
    Load policy from ``path`` or ``default_policy_path()``; on missing/unreadable file,
    use embedded defaults (same shape as shipped JSON).
    """
    p = path if path is not None else default_policy_path()
    raw: Mapping[str, Any]
    try:
        if p.is_file():
            raw = json.loads(p.read_text(encoding="utf-8"))
        else:
            raw = _EMBEDDED_FALLBACK
    except (OSError, json.JSONDecodeError):
        raw = _EMBEDDED_FALLBACK
    return PolicyConfig.from_dict(raw)
