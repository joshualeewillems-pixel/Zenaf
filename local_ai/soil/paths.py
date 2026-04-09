"""Soil root resolution and safe node paths."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

SOIL_VERSION_DIR = "v1"

SOIL_CATEGORIES: tuple[str, ...] = (
    "inbox",
    "recurring_patterns",
    "tensions",
    "hypotheses",
    "excerpts",
    "mediations",
    "entity_shadows",
    "route_observations",
    "candidate_truth",
    "promoted",
)

ALLOWED_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "task",
        "project",
        "initiative",
        "idea",
        "perspective_agent",
        "core_profile",
        "_root",
    }
)

_BAD_SEGMENT_CHARS = re.compile(r'[\\/:*?"<>|\r\n\x00-\x1f]')


def resolve_soil_root() -> Path:
    env = os.environ.get("ZENAF_SOIL_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".zenaf" / "soil" / SOIL_VERSION_DIR


def sanitize_entity_type(entity_type: str) -> str:
    raw = (entity_type or "").strip().lower()
    if not raw or raw == ".." or "/" in raw or "\\" in raw:
        raise ValueError("invalid entity_type")
    if raw not in ALLOWED_ENTITY_TYPES:
        raise ValueError(f"entity_type not allowed for soil kernel: {raw!r}")
    return raw


def safe_entity_id_segment(entity_type: str, entity_id: str | None) -> str:
    et = sanitize_entity_type(entity_type)
    if et == "_root":
        rid = (entity_id or "").strip() or "root"
    else:
        rid = (entity_id or "").strip()
        if not rid:
            raise ValueError("entity_id is required for non-_root nodes")

    cleaned = _BAD_SEGMENT_CHARS.sub("_", rid).strip("._")
    cleaned = cleaned[:120] if len(cleaned) > 120 else cleaned
    if cleaned:
        return cleaned
    digest = hashlib.sha256(rid.encode("utf-8")).hexdigest()[:16]
    return f"id_{digest}"


def node_dir(root: Path, entity_type: str, entity_id: str | None) -> Path:
    et = sanitize_entity_type(entity_type)
    seg = safe_entity_id_segment(et, entity_id)
    return root / "nodes" / et / seg


def relative_path_posix(path: Path, root: Path) -> str:
    """
    Path of `path` relative to soil `root`, always with forward slashes.
    Use for API/CLI JSON and stdout so clients are consistent across OS.
    """
    return path.resolve().relative_to(root.resolve()).as_posix()
