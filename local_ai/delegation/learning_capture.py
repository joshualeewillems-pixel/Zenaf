"""
Non-blocking learning artifacts for delegated (especially cloud) model calls.

v1: in-memory bounded ring buffer plus **optional** append-only JSONL persistence
(``ZENAF_LEARNING_PERSIST_PATH``). No training; dataset building for future prompt tuning,
heuristics, and local model improvement.

**Privacy:** ``restricted`` / ``local_only`` → minimal records (no raw input/output text).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping, Optional

from local_ai.delegation import learning_persist as _learning_persist

logger = logging.getLogger(__name__)


def exec_meta_provider_model(exec_meta: Mapping[str, Any] | None) -> tuple[Optional[str], Optional[str]]:
    """Best-effort provider / model labels for learning (no UI coupling)."""
    e = exec_meta or {}
    p = e.get("provider_used")
    m = e.get("model_used") or e.get("model")
    ps = str(p).strip() if p is not None else ""
    ms = str(m).strip() if m is not None else ""
    return (ps or None, ms or None)

DelegationTier = Literal["general", "structured", "strict_secure"]

_MAX_BUFFER = 5_000
_MAX_SNAPSHOT_NORMAL = 6_000
_MAX_OUTPUT_NORMAL = 12_000
_MAX_EXPORT_PER_REQUEST = 500


def _privacy_restrictive(privacy_mode: Optional[str]) -> bool:
    m = (privacy_mode or "").strip().lower()
    return m in ("restricted", "local_only")


def _prompt_ref(compiled_prompt: str) -> tuple[str, int]:
    """Reference only (hash prefix + length); never store full prompt in learning buffer by default."""
    n = len(compiled_prompt or "")
    if not compiled_prompt:
        return ("", 0)
    h = hashlib.sha256(compiled_prompt.encode("utf-8", errors="replace")).hexdigest()[:16]
    return (h, n)


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 20] + "\n… [truncated]"


@dataclass
class LearningRecord:
    """
    Stable shape for cross-surface export (JSON lines, future DB, training pipelines).

    ``user_outcome`` / ``outcome_diff_summary`` are reserved for async client follow-up
    (applied / edited / dismissed / copied); v1 usually leaves them null at capture time.
    """

    record_id: str
    ts_ms: int
    action_intent: str
    surface: str
    delegation_tier: DelegationTier
    provider_used: Optional[str]
    model_used: Optional[str]
    validation_passed: bool
    validation_error: Optional[str]
    input_snapshot_redacted: str
    compiled_prompt_sha256_prefix: str
    compiled_prompt_char_len: int
    model_output_redacted: str
    delegation_path: Optional[str]
    externalization_mapping_active: bool
    user_outcome: Optional[str] = None
    outcome_diff_summary: Optional[str] = None
    capture_mode: str = "full"  # "full" | "minimal"

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


class LearningBuffer:
    """Thread-safe FIFO-ish ring (newest at end via append + maxlen)."""

    def __init__(self, maxlen: int = _MAX_BUFFER) -> None:
        self._maxlen = int(maxlen)
        self._dq: deque[dict[str, Any]] = deque(maxlen=self._maxlen)
        self._lock = threading.Lock()

    @property
    def maxlen(self) -> int:
        return self._maxlen

    def append(self, record: LearningRecord) -> None:
        with self._lock:
            self._dq.append(record.to_json_dict())

    def append_dict(self, row: Mapping[str, Any]) -> None:
        """Append a row already in ``to_json_dict()`` shape (e.g. persistence replay)."""
        with self._lock:
            self._dq.append(dict(row))

    def recent(self, n: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._dq)[-n:]

    def slice_records(
        self,
        *,
        offset: int,
        limit: int,
        order: Literal["asc", "desc"] = "asc",
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Paginated read (oldest → newest in deque).

        ``order=asc``: slice is chronological (oldest first in page).
        ``order=desc``: page is reverse chronological (newest first).
        Returns ``(rows, total_len)``.
        """
        off = max(0, int(offset))
        lim = max(0, min(int(limit), _MAX_EXPORT_PER_REQUEST))
        with self._lock:
            all_rows = list(self._dq)
        total = len(all_rows)
        page = all_rows[off : off + lim]
        if order == "desc":
            page = list(reversed(page))
        return page, total

    def copy_all_records(self) -> list[dict[str, Any]]:
        """Snapshot for aggregate stats (bounded by maxlen)."""
        with self._lock:
            return list(self._dq)

    def size(self) -> int:
        with self._lock:
            return len(self._dq)

    def clear(self) -> None:
        """Clear all records (tests or admin tooling only)."""
        with self._lock:
            self._dq.clear()

    def update_user_outcome(
        self,
        record_id: str,
        user_outcome: str,
        *,
        outcome_diff_summary: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Mutate the first matching in-buffer record (in-place).

        Returns a **copy** of the updated row for persistence, or None if not found / invalid outcome.
        """
        rid = (record_id or "").strip()
        if not rid:
            return None
        o = (user_outcome or "").strip().lower()
        if o not in _ALLOWED_USER_OUTCOMES:
            return None
        diff = outcome_diff_summary
        if diff is not None:
            diff = _truncate(diff, 2_000)
        with self._lock:
            for d in self._dq:
                if d.get("record_id") == rid:
                    d["user_outcome"] = o
                    if diff is not None:
                        d["outcome_diff_summary"] = diff
                    return dict(d)
        return None


_ALLOWED_USER_OUTCOMES = frozenset({"applied", "edited", "dismissed", "copied"})

_global_buffer = LearningBuffer()


def get_learning_buffer() -> LearningBuffer:
    return _global_buffer


def learning_export_enabled() -> bool:
    """Opt-in so authenticated users cannot dump the buffer unless the operator enables export."""
    v = (os.environ.get("ZENAF_LEARNING_EXPORT_ENABLED") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def export_learning_records_jsonl(
    *,
    offset: int = 0,
    limit: int = _MAX_EXPORT_PER_REQUEST,
    order: Literal["asc", "desc"] = "asc",
) -> tuple[str, int]:
    """
    One JSON object per line (UTF-8). Rows are **as stored** (already privacy-redacted at capture).

    Returns ``(body, total_in_buffer)``.
    """
    rows, total = _global_buffer.slice_records(offset=offset, limit=limit, order=order)
    lines = [json.dumps(r, ensure_ascii=False, default=str) for r in rows]
    return "\n".join(lines) + ("\n" if lines else ""), total


def inspect_learning_buffer(
    *,
    offset: int = 0,
    limit: int = 100,
    order: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    """JSON-serializable summary + page of records (same redaction as buffer)."""
    lim = max(0, min(int(limit), _MAX_EXPORT_PER_REQUEST))
    rows, total = _global_buffer.slice_records(offset=offset, limit=lim, order=order)
    tier_counts: dict[str, int] = dict(Counter(r.get("delegation_tier") or "unknown" for r in rows))
    capture_counts: dict[str, int] = dict(Counter(r.get("capture_mode") or "unknown" for r in rows))
    return {
        "total_in_buffer": total,
        "offset": max(0, offset),
        "limit": len(rows),
        "order": order,
        "page_tier_counts": tier_counts,
        "page_capture_mode_counts": capture_counts,
        "records": rows,
    }


def learning_buffer_aggregate_stats() -> dict[str, Any]:
    """Lightweight stats over the full buffer (no payload bodies duplicated in a second structure beyond tier counts)."""
    all_rows = _global_buffer.copy_all_records()
    tiers = Counter(r.get("delegation_tier") or "unknown" for r in all_rows)
    modes = Counter(r.get("capture_mode") or "unknown" for r in all_rows)
    outcomes = Counter((r.get("user_outcome") or "none") for r in all_rows)
    val_ok = sum(1 for r in all_rows if r.get("validation_passed") is True)
    val_fail = sum(1 for r in all_rows if r.get("validation_passed") is False)
    return {
        "total_in_buffer": len(all_rows),
        "delegation_tier_counts": dict(tiers),
        "capture_mode_counts": dict(modes),
        "user_outcome_counts": dict(outcomes),
        "validation_passed_true": val_ok,
        "validation_passed_false": val_fail,
    }


def update_learning_record_user_outcome(
    record_id: str,
    user_outcome: str,
    *,
    outcome_diff_summary: Optional[str] = None,
    privacy_mode: Optional[str] = None,
) -> bool:
    """
    Server-side correlate: attach how the user treated the model output after the fact.

    Under restrictive privacy, optional ``outcome_diff_summary`` is dropped (may contain PII).
    """
    if _privacy_restrictive(privacy_mode):
        outcome_diff_summary = None
    updated = _global_buffer.update_user_outcome(
        record_id,
        user_outcome,
        outcome_diff_summary=outcome_diff_summary,
    )
    if updated is None:
        return False
    _learning_persist.append_record_dict(updated)
    return True


def init_learning_persistence_from_env() -> Optional[dict[str, Any]]:
    """
    Call once at API startup if durable learning is desired.

    Reads ``ZENAF_LEARNING_PERSIST_PATH``; replays JSONL into the in-memory buffer (last line per
    ``record_id`` wins). Missing file is OK; corrupt lines are skipped.
    """
    return _learning_persist.init_from_env(_global_buffer)


def reset_learning_persistence_for_tests() -> None:
    """Test helper: clear persistence module state so init can run again."""
    _learning_persist.reset_persistence_for_tests()


def capture_structured_delegation_outcome(
    *,
    surface: str,
    action_intent: str,
    privacy_mode: Optional[str],
    provider_used: Optional[str],
    model_used: Optional[str],
    delegation_tier: Literal["structured", "strict_secure"],
    input_snapshot: str,
    compiled_prompt: str,
    validation_passed: bool,
    validation_error: Optional[str],
    output_payload: Optional[Mapping[str, Any]],
    delegation_path: Optional[str] = None,
    externalization_mapping_active: bool = False,
) -> Optional[str]:
    """
    Fire-and-forget: never raises to callers; O(1) append under a short lock.

    Call **after** validation + distribution (or failure) on structured / strict-secure paths.
    Returns ``record_id`` for client correlation (same contract as general lane).
    """
    try:
        restrictive = _privacy_restrictive(privacy_mode)
        pref, plen = _prompt_ref(compiled_prompt)
        if restrictive:
            inp = ""
            out_s = json.dumps({k: "[redacted]" for k in (output_payload or {}).keys()}) if output_payload else ""
            mode = "minimal"
            verr = validation_error if validation_error else None
        else:
            inp = _truncate(input_snapshot or "", _MAX_SNAPSHOT_NORMAL)
            if output_payload is not None:
                out_s = _truncate(json.dumps(output_payload, ensure_ascii=False, default=str), _MAX_OUTPUT_NORMAL)
            else:
                out_s = ""
            mode = "full"
            verr = validation_error

        rec = LearningRecord(
            record_id=uuid.uuid4().hex[:12],
            ts_ms=int(time.time() * 1000),
            action_intent=(action_intent or "").strip() or "unknown",
            surface=(surface or "").strip() or "unknown",
            delegation_tier=delegation_tier,
            provider_used=provider_used,
            model_used=model_used,
            validation_passed=validation_passed,
            validation_error=verr,
            input_snapshot_redacted=inp,
            compiled_prompt_sha256_prefix=pref,
            compiled_prompt_char_len=plen,
            model_output_redacted=out_s,
            delegation_path=delegation_path,
            externalization_mapping_active=externalization_mapping_active,
            capture_mode=mode,
        )
        _global_buffer.append(rec)
        _learning_persist.append_record_dict(rec.to_json_dict())
        return rec.record_id
    except Exception as e:
        logger.debug("learning_capture: skipped (%s)", e, exc_info=True)
        return None


def capture_general_delegation_outcome(
    *,
    surface: str,
    action_intent: str,
    privacy_mode: Optional[str],
    provider_used: Optional[str],
    model_used: Optional[str],
    input_snapshot: str,
    compiled_prompt: str,
    validation_passed: bool,
    validation_error: Optional[str],
    raw_or_parsed_output: str,
) -> Optional[str]:
    """Tier ``general`` — lightweight text/JSON slice; same privacy rules. Returns ``record_id`` for client correlation."""
    try:
        restrictive = _privacy_restrictive(privacy_mode)
        pref, plen = _prompt_ref(compiled_prompt)
        if restrictive:
            inp = ""
            out_s = "[redacted]"
            mode = "minimal"
        else:
            inp = _truncate(input_snapshot or "", _MAX_SNAPSHOT_NORMAL)
            out_s = _truncate(raw_or_parsed_output or "", _MAX_OUTPUT_NORMAL)
            mode = "full"
        rec = LearningRecord(
            record_id=uuid.uuid4().hex[:12],
            ts_ms=int(time.time() * 1000),
            action_intent=(action_intent or "").strip() or "unknown",
            surface=(surface or "").strip() or "unknown",
            delegation_tier="general",
            provider_used=provider_used,
            model_used=model_used,
            validation_passed=validation_passed,
            validation_error=validation_error,
            input_snapshot_redacted=inp,
            compiled_prompt_sha256_prefix=pref,
            compiled_prompt_char_len=plen,
            model_output_redacted=out_s,
            delegation_path="general_lane_v1",
            externalization_mapping_active=False,
            capture_mode=mode,
        )
        _global_buffer.append(rec)
        _learning_persist.append_record_dict(rec.to_json_dict())
        return rec.record_id
    except Exception as e:
        logger.debug("learning_capture general: skipped (%s)", e, exc_info=True)
        return None