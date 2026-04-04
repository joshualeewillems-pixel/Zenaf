"""Minimal soil filesystem kernel (spec: docs/02_ACTIVE_DESIGN/SOIL_LAYER_FILESYSTEM_SPEC.md)."""

from local_ai.soil.append import append_soil_item, logical_node_id
from local_ai.soil.manifest import ensure_node, read_manifest
from local_ai.soil.named_capture_allowlist import (
    NAMED_SYSTEM_CAPTURE_ALLOWLIST,
    validate_named_capture_name,
)
from local_ai.soil.paths import (
    ALLOWED_ENTITY_TYPES,
    SOIL_CATEGORIES,
    node_dir,
    relative_path_posix,
    resolve_soil_root,
    safe_entity_id_segment,
    sanitize_entity_type,
)
from local_ai.soil.promotion import write_promotion_record

__all__ = [
    "ALLOWED_ENTITY_TYPES",
    "NAMED_SYSTEM_CAPTURE_ALLOWLIST",
    "SOIL_CATEGORIES",
    "append_soil_item",
    "ensure_node",
    "logical_node_id",
    "node_dir",
    "read_manifest",
    "relative_path_posix",
    "resolve_soil_root",
    "safe_entity_id_segment",
    "sanitize_entity_type",
    "validate_named_capture_name",
    "write_promotion_record",
]
