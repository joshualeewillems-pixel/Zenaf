"""Append a soil Markdown item with YAML frontmatter (stdlib only)."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_ai.soil.manifest import default_node_id, ensure_node, read_manifest
from local_ai.soil.models import CAPTURE_SOURCES, MATURATION_STATUSES, category_for_soil_type
from local_ai.soil.named_capture_allowlist import validate_named_capture_name
from local_ai.soil.paths import resolve_soil_root

# Align with API `SoilAppendRequest.title` max_length; keeps node.json titles bounded.
_MANIFEST_TITLE_MAX = 512


def _soil_markdown_basename(soil_id: str) -> str:
    """
    Single stable .md filename segment from soil_id (no directories).
    Strips awkward edges; never returns empty or hidden-dot-only names.
    """
    sid = (soil_id or "").strip()
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", sid)[:80]
    slug = slug.strip("._")
    if not slug:
        slug = f"soil_{secrets.token_hex(4)}"
    if slug.startswith("."):
        slug = f"n{slug}"
    return f"{slug}.md"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_soil_id() -> str:
    return f"soil_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"


def _yaml_dq(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _frontmatter_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = ["---"]
    for k, v in data.items():
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, int):
            lines.append(f"{k}: {v}")
        elif isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {_yaml_dq(str(item))}")
        elif v is None:
            lines.append(f"{k}: null")
        else:
            lines.append(f"{k}: {_yaml_dq(str(v))}")
    lines.append("---")
    return lines


def append_soil_item(
    entity_type: str,
    entity_id: str | None,
    *,
    soil_type: str,
    body: str,
    capture_source: str,
    root: Path | None = None,
    status: str = "seed",
    source_refs: list[str] | None = None,
    tags: list[str] | None = None,
    promotion_score: int = 0,
    capture_name: str | None = None,
    soil_id: str | None = None,
    title: str = "",
    parent_id: str | None = None,
    inherits_from: list[str] | None = None,
    promotion_targets: list[str] | None = None,
    related_nodes: list[str] | None = None,
) -> tuple[Path, str]:
    if capture_source not in CAPTURE_SOURCES:
        raise ValueError(f"invalid capture_source: {capture_source!r}")
    if capture_source == "named_system_capture":
        capture_name = validate_named_capture_name(capture_name or "")
    if status not in MATURATION_STATUSES:
        raise ValueError(f"invalid status: {status!r}")

    category = category_for_soil_type(soil_type)
    if category == "promoted":
        raise ValueError("cannot append interpretive soil items under promoted/")

    base = root if root is not None else resolve_soil_root()
    title_safe = (title or "")[:_MANIFEST_TITLE_MAX]
    nd = ensure_node(
        base,
        entity_type,
        entity_id,
        title=title_safe,
        parent_id=parent_id,
        inherits_from=inherits_from,
        promotion_targets=promotion_targets,
        related_nodes=related_nodes,
    )
    manifest = read_manifest(nd)
    node_id = str(manifest["node_id"])
    sid = soil_id or _new_soil_id()

    fm: dict[str, Any] = {
        "soil_id": sid,
        "node_id": node_id,
        "soil_type": soil_type.strip(),
        "status": status,
        "created_at": _utc_now_iso(),
        "capture_source": capture_source,
        "promotion_score": int(promotion_score),
    }
    if source_refs is not None:
        fm["source_refs"] = list(source_refs)
    if tags is not None:
        fm["tags"] = list(tags)
    if capture_name:
        fm["capture_name"] = capture_name.strip()

    header = "\n".join(_frontmatter_lines(fm)) + "\n"
    content = header + (body or "").lstrip("\n")

    base_name = _soil_markdown_basename(sid)
    stem = Path(base_name).stem
    out_dir = nd / "soil" / category
    out_path = out_dir / base_name
    if out_path.exists():
        out_path = out_dir / f"{stem}_{secrets.token_hex(2)}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path.resolve(), sid


def logical_node_id(entity_type: str, entity_id: str | None) -> str:
    return default_node_id(entity_type, entity_id)
