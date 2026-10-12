"""Write soil/promoted/*.json audit records."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_ai.soil.manifest import ensure_node
from local_ai.soil.paths import node_dir


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_promotion_record(
    root: Path,
    entity_type: str,
    entity_id: str | None,
    *,
    from_soil_id: str,
    from_path_rel: str,
    from_node_id: str,
    to_canonical_ref: dict[str, Any],
    reason: str,
    accepted_by: str,
    supporting_soil_ids: list[str] | None = None,
    to_node_id: str | None = None,
    canonical_write_result: dict[str, Any] | None = None,
    promotion_id: str | None = None,
) -> Path:
    ensure_node(root, entity_type, entity_id)
    nd = node_dir(root, entity_type, entity_id)
    promo_dir = nd / "soil" / "promoted"
    promo_dir.mkdir(parents=True, exist_ok=True)

    pid = promotion_id or (
        f"promo_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
    )
    record: dict[str, Any] = {
        "promotion_id": pid,
        "created_at": _utc_now_iso(),
        "from_soil_id": from_soil_id,
        "from_path": from_path_rel.replace("\\", "/"),
        "from_node_id": from_node_id,
        "to_canonical_ref": dict(to_canonical_ref),
        "reason": reason,
        "accepted_by": accepted_by,
        "supporting_soil_ids": list(supporting_soil_ids or []),
    }
    if to_node_id is not None:
        record["to_node_id"] = to_node_id
    if canonical_write_result is not None:
        record["canonical_write_result"] = dict(canonical_write_result)

    out = promo_dir / f"{pid}.json"
    if out.exists():
        out = promo_dir / f"{pid}_{secrets.token_hex(2)}.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return out.resolve()
