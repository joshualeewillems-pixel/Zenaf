"""
Manual arc-detection runner (lab / observation only).

Implements heuristic ``v0.1_friction_to_done`` per docs/01_TRUTH/FRUIT_MINT_POLICY.md:
friction-negative anchor → engagement pivot → terminal-done (VE status) → stability window.

Does not mint, accrue value, or touch vitality scores. Writes ``arc_detection_candidates`` rows
with status=proposed only.

Usage (repo root)::

    python -m local_ai.vision_execution.detect_arcs --user <user_id> --heuristic v0.1_friction_to_done
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.coordination_signals import summarize_execution_flow_trunk

# Terminal status: same word list as node_vitality_scores._is_done (not imported — Philosophy #16 firewall).
_DONE_STATUS_RE = re.compile(
    r"\b(done|complete|completed|shipped|closed|won)\b",
    re.IGNORECASE,
)


def _is_terminal_ve_status(status: str | None) -> bool:
    return bool(_DONE_STATUS_RE.search(status or ""))

# -----------------------------------------------------------------------------
# Heuristic v0.1 constants (tune only with FRUIT_MINT_POLICY / matrix review)
# -----------------------------------------------------------------------------

HEURISTIC_V01 = "v0.1_friction_to_done"
C_FRICTION = 0.4
C_PIVOT = 0.35
MIN_SPAN_AVOID_TO_COMPLETE = timedelta(hours=48)
STABILITY_AFTER_COMPLETE = timedelta(days=3)

SkipReason = Literal[
    "no_execution_flow_readings",
    "missing_friction_anchor",
    "missing_pivot",
    "not_terminal",
    "bad_timeline",
    "insufficient_span",
    "unstable_after_completion",
    "insufficient_stability_window",
]


@dataclass(frozen=True)
class FlowReading:
    id: str
    created_at: str
    impact: str
    dimension: str
    confidence: float


def _parse_iso(dt: str | None) -> datetime | None:
    if not dt or not str(dt).strip():
        return None
    s = str(dt).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(s)
        if out.tzinfo is None:
            out = out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_avoidance_anchor(r: FlowReading) -> bool:
    return (
        r.dimension == "friction"
        and r.impact == "negative"
        and r.confidence >= C_FRICTION
    )


def _is_engagement_pivot(r: FlowReading) -> bool:
    if r.impact == "positive":
        return True
    if r.dimension == "friction" and r.impact in ("neutral", "positive"):
        return True
    if r.dimension in ("clarity", "capacity") and r.impact != "negative" and r.confidence >= C_PIVOT:
        return True
    return False


def _is_strong_friction_negative(r: FlowReading) -> bool:
    return r.dimension == "friction" and r.impact == "negative" and r.confidence >= C_FRICTION


def collect_flow_readings_from_judgment_rows(rows: list[dict[str, Any]]) -> list[FlowReading]:
    out: list[FlowReading] = []
    for r in rows:
        if (r.get("verdict_kind") or "") != "execution_flow_reading":
            continue
        trunk = r.get("trunk") if isinstance(r.get("trunk"), dict) else {}
        summ = summarize_execution_flow_trunk(trunk)
        if not summ:
            continue
        rid = str(r.get("id") or "").strip()
        cat = str(r.get("created_at") or "").strip()
        if not rid or not cat:
            continue
        try:
            conf = float(summ["confidence"])
        except (TypeError, ValueError):
            conf = 0.0
        out.append(
            FlowReading(
                id=rid,
                created_at=cat,
                impact=str(summ.get("impact") or ""),
                dimension=str(summ.get("dimension") or ""),
                confidence=conf,
            )
        )
    return out


def try_v01_friction_to_done(
    *,
    readings: list[FlowReading],
    row_status: str | None,
    row_updated_at: str | None,
) -> tuple[SkipReason | None, dict[str, Any] | None]:
    """
    Returns (skip_reason, None) or (None, payload) with keys for DB + notes.
    """
    if not readings:
        return "no_execution_flow_readings", None

    avoid: FlowReading | None = None
    for r in readings:
        if _is_avoidance_anchor(r):
            avoid = r
            break
    if avoid is None:
        return "missing_friction_anchor", None

    t_avoid = _parse_iso(avoid.created_at)
    if t_avoid is None:
        return "missing_friction_anchor", None

    pivot: FlowReading | None = None
    for r in readings:
        tr = _parse_iso(r.created_at)
        if tr is None or tr <= t_avoid:
            continue
        if _is_engagement_pivot(r):
            pivot = r
            break
    if pivot is None:
        return "missing_pivot", None

    t_eng = _parse_iso(pivot.created_at)
    if t_eng is None or t_eng <= t_avoid:
        return "missing_pivot", None

    if not _is_terminal_ve_status(row_status):
        return "not_terminal", None

    t_complete = _parse_iso(row_updated_at)
    if t_complete is None or t_complete <= t_eng:
        return "bad_timeline", None

    if t_complete - t_avoid < MIN_SPAN_AVOID_TO_COMPLETE:
        return "insufficient_span", None

    for r in readings:
        tr = _parse_iso(r.created_at)
        if tr is None or tr <= t_complete:
            continue
        if _is_strong_friction_negative(r):
            return "unstable_after_completion", None

    now = _now_utc()
    if now - t_complete < STABILITY_AFTER_COMPLETE:
        return "insufficient_stability_window", None

    det_conf = max(0.0, min(1.0, (avoid.confidence + pivot.confidence) / 2.0))

    notes: dict[str, Any] = {
        "heuristic": HEURISTIC_V01,
        "interpretation": "coordination-shaped arc candidate only; not inner transformation",
        "policy_ref": "docs/01_TRUTH/FRUIT_MINT_POLICY.md",
        "limitations": [
            "t_complete uses entity updated_at as proxy for completion time",
            "t_avoid not verified against historical non-terminal status",
        ],
        "t_avoid_at": avoid.created_at,
        "t_eng_at": pivot.created_at,
        "t_complete_at": row_updated_at,
        "reading_count": len(readings),
    }
    payload = {
        "t_avoid_reading_id": avoid.id,
        "t_eng_reading_id": pivot.id,
        "t_complete_at": (row_updated_at or "").strip(),
        "detector_confidence": det_conf,
        "notes": notes,
    }
    return None, payload


def _iter_subject_rows(user_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Pairs (entity_type, row_dict) for ideas, initiatives, projects, tasks."""
    out: list[tuple[str, dict[str, Any]]] = []
    for row in ve_storage.list_ideas(user_id):
        out.append(("idea", row))
    for row in ve_storage.list_initiatives(user_id):
        out.append(("initiative", row))
    for row in ve_storage.list_projects(user_id):
        out.append(("project", row))
    for row in ve_storage.list_tasks(user_id):
        out.append(("task", row))
    return out


def run_detection(
    *,
    user_id: str,
    heuristic: str,
    debug_jsonl: Path | None,
) -> int:
    user = ve_storage.get_user_by_id(user_id.strip())
    if not user:
        print(f"error: no user with id {user_id!r}", file=sys.stderr)
        return 2

    if heuristic != HEURISTIC_V01:
        print(f"error: unknown heuristic {heuristic!r} (supported: {HEURISTIC_V01!r})", file=sys.stderr)
        return 2

    ve_storage.get_connection()

    skips: Counter[str] = Counter()
    proposed = 0
    scanned = 0
    if debug_jsonl:
        debug_jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl_f = debug_jsonl.open("w", encoding="utf-8") if debug_jsonl else None

    def _log(obj: dict[str, Any]) -> None:
        if jsonl_f:
            jsonl_f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    try:
        for entity_type, row in _iter_subject_rows(user_id.strip()):
            eid = str(row.get("id") or "").strip()
            if not eid:
                continue
            scanned += 1
            jrows = ve_storage.list_node_judgments_chronological(user_id.strip(), entity_type, eid, limit=2000)
            readings = collect_flow_readings_from_judgment_rows(jrows)
            skip, payload = try_v01_friction_to_done(
                readings=readings,
                row_status=str(row.get("status") or ""),
                row_updated_at=str(row.get("updated_at") or "") or None,
            )
            base_ev = {
                "event": "scan_entity",
                "entity_type": entity_type,
                "entity_id": eid,
                "execution_flow_readings": len(readings),
            }
            _log(base_ev)
            if skip:
                skips[skip] += 1
                _log({**base_ev, "event": "skip", "reason": skip})
                continue

            assert payload is not None
            notes_obj = payload["notes"]
            new_id = ve_storage.try_insert_arc_detection_candidate(
                user_id=user_id.strip(),
                source_entity_type=entity_type,
                source_entity_id=eid,
                heuristic_version=heuristic,
                t_avoid_reading_id=payload["t_avoid_reading_id"],
                t_eng_reading_id=payload["t_eng_reading_id"],
                t_complete_at=payload["t_complete_at"],
                detector_confidence=float(payload["detector_confidence"]),
                notes_json=json.dumps(notes_obj, ensure_ascii=False),
            )
            if new_id:
                proposed += 1
                _log(
                    {
                        **base_ev,
                        "event": "proposed",
                        "candidate_id": new_id,
                        "detector_confidence": payload["detector_confidence"],
                    }
                )
            else:
                skips["duplicate_candidate"] += 1
                _log({**base_ev, "event": "skip", "reason": "duplicate_candidate"})
    finally:
        if jsonl_f:
            jsonl_f.close()

    print(f"arc_detection run heuristic={heuristic} user={user_id.strip()}")
    print(f"entities_scanned: {scanned}")
    print(f"candidates_proposed: {proposed}")
    print("skipped:")
    for k, v in sorted(skips.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {k}: {v}")
    if debug_jsonl:
        print(f"debug_jsonl: {debug_jsonl.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Arc detection lab - proposed rows only (no mint).")
    p.add_argument("--user", required=True, help="Vision Execution user id (users.id)")
    p.add_argument(
        "--heuristic",
        default=HEURISTIC_V01,
        help=f"Heuristic id (default: {HEURISTIC_V01})",
    )
    p.add_argument(
        "--debug-jsonl",
        default="",
        help="Write one JSON object per line (default: reports/arc_detection/arc_detect_<ts>.jsonl under repo)",
    )
    args = p.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    if args.debug_jsonl.strip():
        debug_path = Path(args.debug_jsonl).expanduser()
        if not debug_path.is_absolute():
            debug_path = repo_root / debug_path
    else:
        rep = repo_root / "reports" / "arc_detection"
        rep.mkdir(parents=True, exist_ok=True)
        ts = _now_utc().strftime("%Y%m%d_%H%M%S")
        debug_path = rep / f"arc_detect_{ts}.jsonl"

    return run_detection(user_id=args.user, heuristic=args.heuristic.strip(), debug_jsonl=debug_path)


if __name__ == "__main__":
    raise SystemExit(main())
