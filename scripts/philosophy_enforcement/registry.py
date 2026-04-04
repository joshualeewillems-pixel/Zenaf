from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def load_matrix_registry(repo: Path) -> dict[str, Any]:
    path = repo / "docs" / "01_TRUTH" / "global_philosophy_integration_matrix.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing philosophy registry: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def philosophy_checker_map(registry: dict[str, Any]) -> dict[int, list[str]]:
    """philosophy id -> ordered checker_ids."""
    out: dict[int, list[str]] = {}
    for row in registry.get("philosophies", []):
        pid = int(row["id"])
        auto = row.get("automation") or {}
        ids = auto.get("checker_ids") or []
        if ids:
            out[pid] = list(ids)
    return out
