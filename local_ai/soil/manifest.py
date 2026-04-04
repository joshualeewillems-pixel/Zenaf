"""Create node tree and node.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_ai.soil.paths import SOIL_CATEGORIES, node_dir, sanitize_entity_type


def default_node_id(entity_type: str, entity_id: str | None) -> str:
    et = sanitize_entity_type(entity_type)
    if et == "_root":
        return "_root"
    eid = (entity_id or "").strip()
    if not eid:
        raise ValueError("entity_id required for node_id")
    return f"{et}:{eid}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_node(
    root: Path,
    entity_type: str,
    entity_id: str | None,
    *,
    title: str = "",
    parent_id: str | None = None,
    inherits_from: list[str] | None = None,
    promotion_targets: list[str] | None = None,
    related_nodes: list[str] | None = None,
) -> Path:
    nd = node_dir(root, entity_type, entity_id)
    nd.mkdir(parents=True, exist_ok=True)
    (nd / "canonical").mkdir(exist_ok=True)
    soil = nd / "soil"
    soil.mkdir(exist_ok=True)
    for cat in SOIL_CATEGORIES:
        (soil / cat).mkdir(exist_ok=True)

    node_path = nd / "node.json"
    node_id = default_node_id(entity_type, entity_id)
    et = sanitize_entity_type(entity_type)

    if node_path.is_file():
        existing = json.loads(node_path.read_text(encoding="utf-8"))
        if existing.get("node_id") != node_id:
            raise ValueError(
                f"node.json node_id mismatch: disk={existing.get('node_id')!r} expected={node_id!r}"
            )
        if existing.get("node_type") != et:
            raise ValueError("node.json node_type mismatch")
        return nd

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "node_id": node_id,
        "node_type": et,
        "title": title or node_id,
        "parent_id": parent_id,
        "inherits_from": list(inherits_from or []),
        "promotion_targets": list(promotion_targets or []),
        "related_nodes": list(related_nodes or []),
        "ve_entity_id": None if et == "_root" else (entity_id or "").strip() or None,
        "updated_at": _utc_now_iso(),
    }
    node_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return nd


def read_manifest(node_dir_path: Path) -> dict[str, Any]:
    p = node_dir_path / "node.json"
    if not p.is_file():
        raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding="utf-8"))
