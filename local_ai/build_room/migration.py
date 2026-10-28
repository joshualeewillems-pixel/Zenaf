"""Registry standing stage 4 (design v2): derivation-only migration.

Older stored artifacts predate the ``claim_standing`` section (stage 1
added it to newly built artifacts). This module derives that section
for them from the record they already carry — nothing else changes.

Rules, all fail-closed:

- The input artifact is never mutated; migration returns a copy.
- Only the additive ``claim_standing`` section is appended. Claim
  records and every other stored field are copied untouched — the
  migration is a derivation, never a rewrite.
- An artifact that already carries ``claim_standing`` is left
  exactly as it was (the pass is idempotent).
- An artifact without a usable claim registry, or any artifact
  whose derivation raises, is left exactly as it was and reported
  unmigrated. Unmigrated artifacts report "standing not computed" —
  never an assumed standing.
- The store-dir pass writes back only migrated files, via an
  atomic replace, so a failed write leaves the original intact.

This module computes tables; it never changes acceptance rules,
prompt wording, budgets, or the feature flag. Applying the pass to a
live store (e.g. staging's data volume) is a separate step from
building it — nothing here runs on its own.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from local_ai.build_room.claim_standing import compute_claim_standing

STANDING_NOT_COMPUTED = "standing not computed"
ARTIFACT_GLOB = "meeting_*.draft_artifact.json"


def _unmigrated(reason: str) -> dict[str, Any]:
    return {
        "migrated": False,
        "standing": STANDING_NOT_COMPUTED,
        "reason": reason,
    }


def _validate_registry(artifact: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None, str | None]:
    """Return (claims, interactions, error). Error is None when usable."""
    registry = artifact.get("claim_registry")
    if not isinstance(registry, list) or not registry:
        return [], None, "no claim registry"
    seen: set[str] = set()
    for entry in registry:
        if not isinstance(entry, dict):
            return [], None, "claim registry entry is not an object"
        cid = entry.get("id")
        if not isinstance(cid, str) or not cid:
            return [], None, "claim registry entry without an id"
        if cid in seen:
            return [], None, f"duplicate claim id: {cid}"
        seen.add(cid)
    interactions = artifact.get("interactions", [])
    if interactions is None:
        interactions = []
    if not isinstance(interactions, list):
        return [], None, "interactions is not a list"
    return registry, interactions, None


def migrate_artifact_standing(
    artifact: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive ``claim_standing`` for one stored artifact.

    Returns ``(artifact_dict, report)``. ``artifact_dict`` is a copy
    of the input with the section appended on success, and an
    unchanged copy otherwise. The input is never mutated. ``report``
    carries ``migrated``, ``standing`` (``"computed"`` or
    ``"standing not computed"``), and a ``reason``.
    """
    if not isinstance(artifact, dict):
        return {}, _unmigrated("artifact is not an object")
    if "claim_standing" in artifact:
        return copy.deepcopy(artifact), {
            "migrated": False,
            "standing": "computed",
            "reason": "claim_standing already present",
        }
    claims, interactions, error = _validate_registry(artifact)
    if error is not None:
        return copy.deepcopy(artifact), _unmigrated(error)
    try:
        table = compute_claim_standing(claims, interactions)
    except Exception as exc:  # fail closed: leave it exactly as it was
        return copy.deepcopy(artifact), _unmigrated(
            f"derivation failed: {type(exc).__name__}: {exc}")
    migrated = copy.deepcopy(artifact)
    migrated["claim_standing"] = table
    return migrated, {
        "migrated": True,
        "standing": "computed",
        "reason": "derived from stored claim registry",
        "claims": len(claims),
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON the way the runner does, via temp file + replace."""
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def migrate_store_dir(
    store_dir: Path | str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Migrate every stored artifact in a directory (the stage-4 pass).

    Only files matching ``meeting_*.draft_artifact.json`` are
    considered. Migrated files are written back (unless ``dry_run``);
    every other file is left byte-identical. Returns a report with
    per-file outcomes and totals; a missing directory or unreadable
    file is reported, never raised.
    """
    store = Path(store_dir)
    report: dict[str, Any] = {
        "store_dir": str(store),
        "dry_run": dry_run,
        "files": [],
        "migrated": 0,
        "already_present": 0,
        "unmigrated": 0,
        "failed": 0,
    }
    if not store.is_dir():
        report["error"] = "store directory does not exist"
        return report
    for path in sorted(store.glob(ARTIFACT_GLOB)):
        entry: dict[str, Any] = {"file": path.name}
        try:
            raw = path.read_text(encoding="utf-8")
            artifact = json.loads(raw)
        except Exception as exc:
            entry.update({
                "migrated": False,
                "standing": STANDING_NOT_COMPUTED,
                "reason": f"unreadable: {type(exc).__name__}",
            })
            report["files"].append(entry)
            report["failed"] += 1
            continue
        migrated, migration_report = migrate_artifact_standing(artifact)
        entry.update(migration_report)
        if migration_report["migrated"]:
            if dry_run:
                report["migrated"] += 1
            else:
                try:
                    _atomic_write(path, migrated)
                except Exception as exc:
                    entry.update({
                        "migrated": False,
                        "standing": STANDING_NOT_COMPUTED,
                        "reason": f"write failed: {type(exc).__name__}",
                    })
                    report["files"].append(entry)
                    report["failed"] += 1
                    continue
                report["migrated"] += 1
        elif migration_report["reason"] == "claim_standing already present":
            report["already_present"] += 1
        else:
            report["unmigrated"] += 1
        report["files"].append(entry)
    return report
