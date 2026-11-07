"""Manifest writer for the wash benchmark harness (design §2.2).

Every run records a manifest: runtime + version, model file + hash,
quantization, context cap, sampling parameters (temperature, seed or
``unsupported``), device/machine, semantic contract version, extraction
implementation version, fixture set version, harness version, and the
variant (model-on vs. skip-enabled). No result is comparable without its
manifest. Unsupported sampling controls and all runtime/model parameters are
recorded — nothing about a run is left implicit.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_ai.eval.wash import (
    EXTRACTION_VERSION,
    FIXTURE_SET_VERSION,
    GOLD_LABEL_VERSION,
    HARNESS_VERSION,
    MANIFEST_VERSION,
    SEMANTIC_VERSION,
    VALIDATOR_VERSION,
    VARIANT_MODEL_ON,
)


@dataclass
class Manifest:
    """One run's manifest (§2.2). All fields are plain JSON values."""

    manifest_version: str = MANIFEST_VERSION
    run_id: str = ""
    created_at: str = ""  # UTC ISO-8601
    semantic_contract_version: str = SEMANTIC_VERSION
    extraction_version: str = EXTRACTION_VERSION
    harness_version: str = HARNESS_VERSION
    validator_version: str = VALIDATOR_VERSION
    fixture_set_version: str = FIXTURE_SET_VERSION
    gold_label_version: str = GOLD_LABEL_VERSION
    variant: str = VARIANT_MODEL_ON  # model-on | skip-enabled (§4.3, §8)
    candidate: str | None = None  # model id, e.g. "qwen3:1.7b"; None for self-proof
    runtime: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def new_manifest(
    *,
    variant: str = VARIANT_MODEL_ON,
    candidate: str | None = None,
    runtime: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    notes: str = "",
) -> Manifest:
    """Build a manifest for a run, filling run id + timestamp."""
    return Manifest(
        run_id=f"wash-{uuid.uuid4().hex[:12]}",
        created_at=datetime.now(timezone.utc).isoformat(),
        variant=variant,
        candidate=candidate,
        runtime=runtime or {"name": "none — harness self-proof, no model present"},
        thresholds=thresholds or {},
        notes=notes,
    )


def write_manifest(path: str | Path, manifest: Manifest) -> Path:
    """Write a manifest as JSON. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.to_json() + "\n", encoding="utf-8")
    return path


def read_manifest(path: str | Path) -> dict[str, Any]:
    """Read a manifest file back as a plain dict."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = ["Manifest", "new_manifest", "write_manifest", "read_manifest"]
