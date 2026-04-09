"""
Port pre-rename filesystem state (`.atria` / `~/.atria`) into canonical `.zenaf` / `~/.zenaf` paths.

Idempotent: only copies or moves when the destination is missing or empty. Safe to run on every API startup.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from local_ai.env_legacy_aliases import is_legacy_atria_import_disabled

logger = logging.getLogger(__name__)


def _dir_has_files(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        next(path.iterdir())
        return True
    except StopIteration:
        return False


def migrate_home_dot_atria() -> None:
    """Copy settings encryption key and Soil data from ~/.atria into ~/.zenaf when targets absent."""
    home = Path.home()
    old_base = home / ".atria"
    new_base = home / ".zenaf"
    if not old_base.is_dir():
        return

    key_name = "settings_encryption.key"
    old_key = old_base / key_name
    new_key = new_base / key_name
    if old_key.is_file() and not new_key.is_file():
        try:
            new_base.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_key, new_key)
            logger.info("[legacy-migration] copied %s -> %s", old_key, new_key)
        except OSError as e:
            logger.warning("[legacy-migration] could not copy settings key: %s", e)

    old_soil = old_base / "soil" / "v1"
    new_soil = new_base / "soil" / "v1"
    if old_soil.is_dir() and _dir_has_files(old_soil) and not new_soil.exists():
        try:
            new_soil.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(old_soil, new_soil)
            logger.info("[legacy-migration] copied soil tree %s -> %s", old_soil, new_soil)
        except OSError as e:
            logger.warning("[legacy-migration] could not copy soil: %s", e)


def migrate_repo_dot_atria_workspace_identity(repo_root: Path | None = None) -> None:
    """
    Move `.atria/workspace-identity/v1` → `.zenaf/workspace-identity/v1` when the latter does not exist.
    Brand profile + translation template live here.
    """
    root = repo_root or Path(__file__).resolve().parents[1]
    old_v1 = root / ".atria" / "workspace-identity" / "v1"
    new_v1 = root / ".zenaf" / "workspace-identity" / "v1"
    if not old_v1.is_dir():
        return
    if new_v1.exists():
        return
    try:
        new_v1.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_v1), str(new_v1))
        logger.info("[legacy-migration] moved workspace-identity v1 %s -> %s", old_v1, new_v1)
        # Drop empty parents under .atria
        p = old_v1.parent
        while p.name and p != root:
            try:
                if p.is_dir() and not _dir_has_files(p):
                    p.rmdir()
                p = p.parent
            except OSError:
                break
    except OSError as e:
        logger.warning("[legacy-migration] could not move workspace-identity: %s", e)


def run_all_legacy_atria_migrations(repo_root: Path | None = None) -> None:
    if is_legacy_atria_import_disabled():
        logger.info(
            "[legacy-migration] skipped (ZENAF_DISABLE_LEGACY_ATRIA_IMPORT=%r)",
            (os.environ.get("ZENAF_DISABLE_LEGACY_ATRIA_IMPORT") or "").strip(),
        )
        return
    migrate_home_dot_atria()
    migrate_repo_dot_atria_workspace_identity(repo_root)
