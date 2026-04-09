"""
Append-only JSONL persistence for LearningRecord dicts.

- Same payload as ``LearningRecord.to_json_dict()`` (already redacted at capture).
- Optional rotation via ``ZENAF_LEARNING_PERSIST_MAX_MB``.
- Startup replay: last line per ``record_id`` wins (supports outcome-update re-append).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_FILE_LOCK = threading.Lock()

# Set by init; None = persistence disabled
_persist_path: Optional[str] = None
_persist_max_bytes: Optional[int] = None
_init_done = False


def _env_path() -> str:
    return (os.environ.get("ZENAF_LEARNING_PERSIST_PATH") or "").strip()


def _env_max_bytes() -> Optional[int]:
    raw = (os.environ.get("ZENAF_LEARNING_PERSIST_MAX_MB") or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw) * 1024 * 1024)
    except ValueError:
        logger.warning("learning_persist: invalid ZENAF_LEARNING_PERSIST_MAX_MB=%r; rotation disabled", raw)
        return None


def is_persistence_configured() -> bool:
    return bool(_persist_path)


def reset_persistence_for_tests() -> None:
    """Clear module state (tests only)."""
    global _persist_path, _persist_max_bytes, _init_done
    _persist_path = None
    _persist_max_bytes = None
    _init_done = False


def _is_learning_row(d: Any) -> bool:
    if not isinstance(d, dict):
        return False
    rid = d.get("record_id")
    ts = d.get("ts_ms")
    if not isinstance(rid, str) or not rid.strip():
        return False
    try:
        int(ts)
    except (TypeError, ValueError):
        return False
    return True


def _maybe_rotate(path: str) -> None:
    if _persist_max_bytes is None:
        return
    p = Path(path)
    try:
        if not p.is_file():
            return
        if p.stat().st_size < _persist_max_bytes:
            return
    except OSError as e:
        logger.warning("learning_persist: could not stat %s (%s); skip rotation", path, e)
        return

    stamp = time.strftime("%Y%m%d-%H%M%S")
    rotated = p.with_name(f"{p.name}.{stamp}.rotated")
    try:
        p.rename(rotated)
        logger.info(
            "learning_persist: rotated %s -> %s (max ~%s MB)",
            path,
            rotated.name,
            (_persist_max_bytes or 0) // (1024 * 1024),
        )
    except OSError as e:
        logger.warning("learning_persist: rotation failed for %s (%s); continuing with same file", path, e)


def append_record_dict(row: dict[str, Any]) -> None:
    """Append one UTF-8 JSON line. No-op if persistence not configured."""
    path = _persist_path
    if not path:
        return
    line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
    data = line.encode("utf-8")
    with _FILE_LOCK:
        try:
            parent = Path(path).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
            _maybe_rotate(path)
            with open(path, "ab") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            logger.warning("learning_persist: append failed (%s); record kept in memory only", e)


def replay_into_buffer(buffer: Any, path: str, *, buffer_maxlen: int) -> dict[str, int]:
    """
    Read JSONL; for duplicate record_id, **last line in file order** wins.
    Loads up to ``buffer_maxlen`` rows by chronological ``ts_ms``.

    Returns stats: ``lines_read``, ``lines_corrupt``, ``records_distinct``, ``records_loaded``.
    """
    latest_by_id: dict[str, dict[str, Any]] = {}
    lines_read = 0
    lines_corrupt = 0
    p = Path(path)
    if not p.is_file():
        return {
            "lines_read": 0,
            "lines_corrupt": 0,
            "records_distinct": 0,
            "records_loaded": 0,
        }
    try:
        with open(p, "rb") as f:
            for raw in f:
                lines_read += 1
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    d = json.loads(raw.decode("utf-8"))
                    if not _is_learning_row(d):
                        lines_corrupt += 1
                        continue
                    rid = str(d["record_id"])
                    latest_by_id[rid] = d
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, KeyError):
                    lines_corrupt += 1
                    logger.debug("learning_persist: skipping corrupt line %s", lines_read)
    except OSError as e:
        logger.warning("learning_persist: could not read %s (%s); starting with empty replay", path, e)
        return {
            "lines_read": lines_read,
            "lines_corrupt": lines_corrupt,
            "records_distinct": 0,
            "records_loaded": 0,
        }

    if lines_corrupt:
        logger.warning(
            "learning_persist: replay %s — %s corrupt / skipped lines (of %s read)",
            path,
            lines_corrupt,
            lines_read,
        )

    distinct = len(latest_by_id)
    ordered = sorted(latest_by_id.values(), key=lambda r: int(r.get("ts_ms") or 0))
    tail = ordered[-buffer_maxlen:] if buffer_maxlen > 0 else ordered

    for row in tail:
        buffer.append_dict(row)

    return {
        "lines_read": lines_read,
        "lines_corrupt": lines_corrupt,
        "records_distinct": distinct,
        "records_loaded": len(tail),
    }


def init_from_env(buffer: Any) -> Optional[dict[str, Any]]:
    """
    Read env, optionally replay file into ``buffer``. Safe if file missing or partially corrupt.

    Returns a small status dict if persistence is enabled, else None.
    """
    global _persist_path, _persist_max_bytes, _init_done
    if _init_done:
        return {"already_initialized": True, "path": _persist_path}
    _init_done = True

    path = _env_path()
    if not path:
        return None

    _persist_path = path
    _persist_max_bytes = _env_max_bytes()

    maxlen = getattr(buffer, "maxlen", 5000)
    try:
        maxlen = int(maxlen)
    except (TypeError, ValueError):
        maxlen = 5000

    stats = replay_into_buffer(buffer, path, buffer_maxlen=maxlen)
    logger.info(
        "learning_persist: path=%s rotation_max_bytes=%s replay=%s",
        path,
        _persist_max_bytes,
        stats,
    )
    return {"path": path, "max_bytes": _persist_max_bytes, **stats}
