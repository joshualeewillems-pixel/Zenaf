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
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_ai.build_room.claim_standing import compute_claim_standing
from local_ai.build_room.record_completeness import check_standing_invariants

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


def _meeting_id_from_filename(name: str) -> str:
    """Fallback meeting id from an artifact filename.

    ``meeting_<id>.draft_artifact.json`` → ``<id>``; anything else
    returns the bare stem.
    """
    stem = name
    if stem.startswith("meeting_"):
        stem = stem[len("meeting_"):]
    if stem.endswith(".draft_artifact.json"):
        stem = stem[: -len(".draft_artifact.json")]
    return stem


def inventory_store_dir(store_dir: Path | str) -> dict[str, Any]:
    """Read-only dry-run inventory of a store directory (design:
    migration dry-run, Joshua).

    For each stored artifact, runs the pure ``migrate_artifact_standing``
    in memory and reports what it *would* do — never what it does.
    This function has NO write code path and takes no ``dry_run``
    flag: there is nothing in it that opens a file for writing, so
    it cannot migrate by mistake. It deliberately does not share
    code with ``migrate_store_dir``'s write path; the read loop is
    small, and sharing it would put the write path one refactor
    away from the inventory.

    Response vocabulary mirrors the stage-4 reports: ``would_migrate``
    (migration reports ``migrated: true``), ``already_present``,
    ``unmigrated`` (standing "not computed"), ``failed`` (unreadable
    file). No claim texts, registries, or tables are returned — only
    counts and verdicts. A missing directory or unreadable file is
    reported, never raised.
    """
    store = Path(store_dir)
    report: dict[str, Any] = {
        "store_dir": str(store),
        "files": [],
        "totals": {
            "files": 0,
            "would_migrate": 0,
            "already_present": 0,
            "unmigrated": 0,
            "failed": 0,
        },
    }
    if not store.is_dir():
        report["error"] = "store directory does not exist"
        return report
    for path in sorted(store.glob(ARTIFACT_GLOB)):
        entry: dict[str, Any] = {"file": path.name}
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            entry.update({
                "meeting_id": _meeting_id_from_filename(path.name),
                "claims": 0,
                "has_claim_standing": False,
                "verdict": "failed",
                "reason": f"unreadable: {type(exc).__name__}",
            })
            report["files"].append(entry)
            report["totals"]["files"] += 1
            report["totals"]["failed"] += 1
            continue
        if not isinstance(artifact, dict):
            entry.update({
                "meeting_id": _meeting_id_from_filename(path.name),
                "claims": 0,
                "has_claim_standing": False,
                "verdict": "unmigrated",
                "reason": "artifact is not an object",
            })
        else:
            _, migration_report = migrate_artifact_standing(artifact)
            if migration_report["migrated"]:
                verdict = "would_migrate"
            elif migration_report["reason"] == "claim_standing already present":
                verdict = "already_present"
            else:
                verdict = "unmigrated"
            meeting_id = artifact.get("meeting_id")
            registry = artifact.get("claim_registry")
            entry.update({
                "meeting_id": meeting_id
                if isinstance(meeting_id, str) and meeting_id
                else _meeting_id_from_filename(path.name),
                "claims": len(registry) if isinstance(registry, list) else 0,
                "has_claim_standing": "claim_standing" in artifact,
                "verdict": verdict,
                "reason": migration_report["reason"],
            })
        report["files"].append(entry)
        report["totals"]["files"] += 1
        report["totals"][entry["verdict"]] += 1
    return report


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


# ---------------------------------------------------------------------------
# Migration execution (design v2, Joshua: Weaver corrections adopted)
# ---------------------------------------------------------------------------

LOCK_DIRNAME = ".migration.lock"
BACKUPS_DIRNAME = "backups"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _acquire_lock(store: Path) -> tuple[Path | None, str | None]:
    """Create the exclusive migration lock directory.

    Returns ``(lock_dir, error)``: on success ``(dir, None)``; when
    the lock is already held ``(None, "held")``; on any other OS
    failure ``(None, "os_error: ...")`` (distinguished so a
    permission problem is never misreported as a live lock).
    Atomic ``mkdir``: exactly one caller wins. The lock directory
    holds a ``lock.json`` with the run id and start timestamp so an
    operator can identify it. A stale lock from a crashed run is
    removed manually by the operator — never broken automatically,
    because breaking a live lock would reintroduce the
    interleaving the lock exists to prevent.
    """
    lock_dir = store / LOCK_DIRNAME
    try:
        lock_dir.mkdir(exist_ok=False)
    except FileExistsError:
        return None, "held"
    except OSError as exc:
        return None, f"os_error: {type(exc).__name__}: {exc}"
    try:
        run_id = uuid.uuid4().hex[:12]
        (lock_dir / "lock.json").write_text(
            json.dumps({
                "run_id": run_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        shutil.rmtree(lock_dir, ignore_errors=True)
        return None, f"os_error: {type(exc).__name__}: {exc}"
    return lock_dir, None


def _release_lock(lock_dir: Path) -> None:
    shutil.rmtree(lock_dir, ignore_errors=True)


def _run_id_from_lock(lock_dir: Path) -> str:
    try:
        info = json.loads((lock_dir / "lock.json").read_text(encoding="utf-8"))
        run_id = info.get("run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    except Exception:
        pass
    return uuid.uuid4().hex[:12]


def execute_migration(store_dir: Path | str) -> dict[str, Any]:
    """Execute the stage-4 migration against a store directory.

    Design v2 procedure: exclusive lock → backup-first with a
    verified SHA-256 manifest → per artifact, in-memory migration
    → pre-write invariant verification → atomic write → post-write
    verification (persisted table equals verified table, invariants
    re-run on the persisted form) → lock release. Collection-level
    fail-closed: the first verification, write, or post-write
    failure stops the run; already-migrated files stay migrated;
    remaining files report ``not_attempted``; nothing is ever
    automatically rolled back. Top-level ``status`` is
    ``completed``, ``aborted_before_writes``, or
    ``partially_completed`` (plus ``lock_held: true`` when the lock
    was already held, so the route can answer 409). The feature
    flag is never touched. Returns the full report; never raises
    for store problems (missing directory, unreadable file).
    """
    store = Path(store_dir)
    totals = {
        "files": 0,
        "migrated": 0,
        "already_present": 0,
        "unmigrated": 0,
        "verification_failed": 0,
        "write_failed": 0,
        "requires_recovery": 0,
        "not_attempted": 0,
    }
    report: dict[str, Any] = {
        "store_dir": str(store),
        "backup_dir": None,
        "run_id": None,
        "status": "aborted_before_writes",
        "files": [],
        "totals": totals,
        "feature_flag_changed": False,
    }
    if not store.is_dir():
        report["error"] = "store directory does not exist"
        return report
    lock_dir, lock_error = _acquire_lock(store)
    if lock_dir is None:
        if lock_error == "held":
            report["lock_held"] = True
            report["reason"] = "migration already running"
        else:
            report["reason"] = f"lock acquisition failed: {lock_error}"
        return report
    run_id = _run_id_from_lock(lock_dir)
    report["run_id"] = run_id
    try:
        paths = sorted(store.glob(ARTIFACT_GLOB))
        # -- Backup first, then verify backups before any write. --
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        backup_dir = store / BACKUPS_DIRNAME / f"{stamp}-{run_id}"
        report["backup_dir"] = str(backup_dir)
        manifest: dict[str, Any] = {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": {},
        }
        try:
            backup_dir.mkdir(parents=True, exist_ok=False)
            for path in paths:
                original = path.read_bytes()
                digest = _sha256_bytes(original)
                shutil.copyfile(path, backup_dir / path.name)
                manifest["files"][path.name] = digest
            (backup_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            # Verify: every backup present, byte-identical to its original.
            for path in paths:
                backup_path = backup_dir / path.name
                if not backup_path.is_file():
                    raise IOError(f"backup missing: {path.name}")
                if _sha256_bytes(backup_path.read_bytes()) != manifest["files"][path.name]:
                    raise IOError(f"backup digest mismatch: {path.name}")
                if _sha256_bytes(path.read_bytes()) != manifest["files"][path.name]:
                    raise IOError(f"original changed during backup: {path.name}")
        except Exception as exc:
            report["status"] = "aborted_before_writes"
            report["reason"] = f"backup failed: {type(exc).__name__}: {exc}"
            return report
        # -- Per artifact, collection-level fail-closed. --
        status = "completed"
        for index, path in enumerate(paths):
            entry: dict[str, Any] = {"file": path.name}
            try:
                artifact = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                # Unreadable files cannot migrate; they are reported,
                # not fatal — but per fail-closed semantics the run
                # still stops here rather than skipping silently.
                entry.update({
                    "meeting_id": _meeting_id_from_filename(path.name),
                    "claims": 0,
                    "verdict": "verification_failed",
                    "invariants_passed": False,
                    "post_write_verified": None,
                    "reason": f"unreadable: {type(exc).__name__}",
                })
                report["files"].append(entry)
                totals["files"] += 1
                totals["verification_failed"] += 1
                status = "partially_completed"
                _mark_not_attempted(report, totals, paths[index + 1:])
                break
            if not isinstance(artifact, dict):
                entry.update({
                    "meeting_id": _meeting_id_from_filename(path.name),
                    "claims": 0,
                    "verdict": "unmigrated",
                    "invariants_passed": None,
                    "post_write_verified": None,
                    "reason": "artifact is not an object",
                })
                report["files"].append(entry)
                totals["files"] += 1
                totals["unmigrated"] += 1
                continue
            meeting_id = artifact.get("meeting_id")
            registry = artifact.get("claim_registry")
            entry["meeting_id"] = (
                meeting_id
                if isinstance(meeting_id, str) and meeting_id
                else _meeting_id_from_filename(path.name)
            )
            entry["claims"] = len(registry) if isinstance(registry, list) else 0
            migrated, migration_report = migrate_artifact_standing(artifact)
            if not migration_report["migrated"]:
                verdict = (
                    "already_present"
                    if migration_report["reason"] == "claim_standing already present"
                    else "unmigrated"
                )
                entry.update({
                    "verdict": verdict,
                    "invariants_passed": None,
                    "post_write_verified": None,
                    "reason": migration_report["reason"],
                })
                report["files"].append(entry)
                totals["files"] += 1
                totals[verdict] += 1
                continue
            table = migrated["claim_standing"]
            passed, failures = check_standing_invariants(
                migrated["claim_registry"], migrated.get("interactions", []), table)
            if not passed:
                entry.update({
                    "verdict": "verification_failed",
                    "invariants_passed": False,
                    "post_write_verified": None,
                    "reason": "pre-write invariants failed: " + "; ".join(failures),
                })
                report["files"].append(entry)
                totals["files"] += 1
                totals["verification_failed"] += 1
                status = "partially_completed"
                _mark_not_attempted(report, totals, paths[index + 1:])
                break
            try:
                _atomic_write(path, migrated)
            except Exception as exc:
                entry.update({
                    "verdict": "write_failed",
                    "invariants_passed": True,
                    "post_write_verified": None,
                    "reason": f"write failed: {type(exc).__name__}",
                })
                report["files"].append(entry)
                totals["files"] += 1
                totals["write_failed"] += 1
                status = "partially_completed"
                _mark_not_attempted(report, totals, paths[index + 1:])
                break
            # Post-write verification: persisted state must equal
            # the verified in-memory result, invariants included.
            try:
                persisted = json.loads(path.read_text(encoding="utf-8"))
                persisted_ok = (
                    isinstance(persisted, dict)
                    and persisted.get("claim_standing") == table
                )
                if persisted_ok:
                    passed_after, failures_after = check_standing_invariants(
                        persisted["claim_registry"],
                        persisted.get("interactions", []),
                        persisted["claim_standing"],
                    )
                    persisted_ok = passed_after
                    post_failures = failures_after
                else:
                    post_failures = ["persisted claim_standing differs from verified table"]
            except Exception as exc:
                persisted_ok = False
                post_failures = [f"post-write read failed: {type(exc).__name__}"]
            if not persisted_ok:
                entry.update({
                    "verdict": "requires_recovery",
                    "invariants_passed": True,
                    "post_write_verified": False,
                    "reason": "post-write verification failed: " + "; ".join(post_failures),
                })
                report["files"].append(entry)
                totals["files"] += 1
                totals["requires_recovery"] += 1
                status = "partially_completed"
                _mark_not_attempted(report, totals, paths[index + 1:])
                break
            entry.update({
                "verdict": "migrated",
                "invariants_passed": True,
                "post_write_verified": True,
                "reason": migration_report["reason"],
            })
            report["files"].append(entry)
            totals["files"] += 1
            totals["migrated"] += 1
        report["status"] = status
        return report
    finally:
        _release_lock(lock_dir)


def _mark_not_attempted(
    report: dict[str, Any],
    totals: dict[str, int],
    remaining: list[Path],
) -> None:
    """Record files never reached after a fail-closed stop."""
    for path in remaining:
        report["files"].append({
            "file": path.name,
            "meeting_id": _meeting_id_from_filename(path.name),
            "claims": None,
            "verdict": "not_attempted",
            "invariants_passed": None,
            "post_write_verified": None,
            "reason": "run stopped before this file",
        })
        totals["files"] += 1
        totals["not_attempted"] += 1
