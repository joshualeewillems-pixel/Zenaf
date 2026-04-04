"""
Offline dedupe + summary for persisted LearningRecord JSONL (active + rotated).

Privacy: only reads stored fields; no prompt rehydration or external joins.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal, Mapping, Sequence


def is_learning_record_row(d: Any) -> bool:
    """Same acceptance rule as persistence replay (record_id + ts_ms)."""
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


SortFiles = Literal["none", "path", "mtime"]


def resolve_input_paths(
    patterns: Sequence[str],
    *,
    sort: SortFiles = "none",
) -> list[Path]:
    """
    Expand shell globs and ensure paths exist.

    ``sort``:
    - ``none``: preserve expanded order within each pattern, patterns in CLI order.
    - ``path``: lexicographic by resolved path string.
    - ``mtime``: ascending modification time (oldest first; good for last-line-wins + newest data last).
    """
    import glob as glob_mod

    seen: set[str] = set()
    out: list[Path] = []
    for pat in patterns:
        matches = glob_mod.glob(pat)
        if not matches:
            p = Path(pat)
            if p.is_file():
                matches = [str(p)]
            else:
                raise FileNotFoundError(f"No files matched pattern: {pat!r}")
        for m in matches:
            if m not in seen:
                seen.add(m)
                out.append(Path(m))
    if sort == "path":
        out.sort(key=lambda x: str(x.resolve()))
    elif sort == "mtime":
        out.sort(key=lambda p: p.stat().st_mtime)
    return out


@dataclass
class DedupeStats:
    files_read: int
    lines_read: int
    lines_blank: int
    lines_corrupt: int
    record_rows_accepted: int
    distinct_record_ids: int
    record_ids_with_multiple_lines: int


def iter_jsonl_lines(paths: Iterable[Path]) -> Iterator[tuple[Path, int, bytes]]:
    """Yield (path, line_index_1based, raw_line_bytes) including blank lines for counting."""
    for path in paths:
        with open(path, "rb") as f:
            for i, raw in enumerate(f, start=1):
                yield path, i, raw


def dedupe_last_line_wins(paths: Sequence[Path]) -> tuple[dict[str, dict[str, Any]], DedupeStats]:
    """
    Stream all files in order; for each ``record_id``, the last valid row wins.
    """
    latest: dict[str, dict[str, Any]] = {}
    id_seen_count: Counter[str] = Counter()

    lines_read = 0
    lines_blank = 0
    lines_corrupt = 0
    accepted = 0

    for _path, _ln, raw in iter_jsonl_lines(paths):
        lines_read += 1
        stripped = raw.strip()
        if not stripped:
            lines_blank += 1
            continue
        try:
            d = json.loads(stripped.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            lines_corrupt += 1
            continue
        if not is_learning_record_row(d):
            lines_corrupt += 1
            continue
        rid = str(d["record_id"])
        id_seen_count[rid] += 1
        latest[rid] = d
        accepted += 1

    multi = sum(1 for c in id_seen_count.values() if c > 1)
    stats = DedupeStats(
        files_read=len(paths),
        lines_read=lines_read,
        lines_blank=lines_blank,
        lines_corrupt=lines_corrupt,
        record_rows_accepted=accepted,
        distinct_record_ids=len(latest),
        record_ids_with_multiple_lines=multi,
    )
    return latest, stats


def build_summary(deduped: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate counts from deduped rows only (already-redacted fields as stored)."""
    rows = list(deduped.values())
    action_intent = Counter(str(r.get("action_intent") or "unknown") for r in rows)
    surface = Counter(str(r.get("surface") or "unknown") for r in rows)
    tier = Counter(str(r.get("delegation_tier") or "unknown") for r in rows)
    provider = Counter(
        (None if r.get("provider_used") in (None, "") else str(r.get("provider_used"))) for r in rows
    )
    model = Counter((None if r.get("model_used") in (None, "") else str(r.get("model_used"))) for r in rows)
    val_pass = sum(1 for r in rows if r.get("validation_passed") is True)
    val_fail = sum(1 for r in rows if r.get("validation_passed") is False)
    val_other = len(rows) - val_pass - val_fail
    def _outcome_label(r: Mapping[str, Any]) -> str:
        u = r.get("user_outcome")
        if u is None or u == "":
            return "none"
        return str(u).strip().lower()

    outcome = Counter(_outcome_label(r) for r in rows)
    capture = Counter(str(r.get("capture_mode") or "unknown") for r in rows)

    # Normalize keys for JSON (None -> "null" string for provider/model)
    def counter_with_null_key(c: Counter) -> dict[str, int]:
        out: dict[str, int] = {}
        for k, v in c.items():
            key = "null" if k is None else str(k)
            out[key] = v
        return dict(sorted(out.items()))

    return {
        "total_distinct_records": len(rows),
        "action_intent_counts": dict(sorted(action_intent.items(), key=lambda kv: (-kv[1], kv[0]))),
        "surface_counts": dict(sorted(surface.items(), key=lambda kv: (-kv[1], kv[0]))),
        "delegation_tier_counts": dict(sorted(tier.items(), key=lambda kv: (-kv[1], kv[0]))),
        "provider_used_counts": counter_with_null_key(provider),
        "model_used_counts": counter_with_null_key(model),
        "validation": {
            "passed_true": val_pass,
            "passed_false": val_fail,
            "passed_other_or_missing": val_other,
        },
        "user_outcome_counts": dict(sorted(outcome.items(), key=lambda kv: (-kv[1], kv[0]))),
        "capture_mode_counts": dict(sorted(capture.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def write_cleaned_jsonl(deduped: Mapping[str, Any], out_path: Path) -> None:
    """Write one JSON object per line, UTF-8, sorted by ts_ms then record_id."""
    rows = sorted(
        deduped.values(),
        key=lambda r: (int(r.get("ts_ms") or 0), str(r.get("record_id") or "")),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def format_summary_text(
    dedupe_stats: DedupeStats,
    summary: Mapping[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("=== LearningRecord JSONL prep ===")
    lines.append(
        f"Files: {dedupe_stats.files_read} | Lines read: {dedupe_stats.lines_read} "
        f"(blank: {dedupe_stats.lines_blank}, corrupt/skipped: {dedupe_stats.lines_corrupt})"
    )
    lines.append(
        f"Accepted record rows: {dedupe_stats.record_rows_accepted} | "
        f"Distinct record_id: {dedupe_stats.distinct_record_ids} | "
        f"Ids with multiple lines (deduped): {dedupe_stats.record_ids_with_multiple_lines}"
    )
    lines.append("")
    lines.append(f"Distinct records (deduped): {summary['total_distinct_records']}")
    lines.append("")
    for title, key in (
        ("action_intent", "action_intent_counts"),
        ("surface", "surface_counts"),
        ("delegation_tier", "delegation_tier_counts"),
        ("provider_used", "provider_used_counts"),
        ("model_used", "model_used_counts"),
        ("user_outcome", "user_outcome_counts"),
        ("capture_mode", "capture_mode_counts"),
    ):
        lines.append(f"-- {title} --")
        sub = summary.get(key) or {}
        for k, v in sub.items():
            lines.append(f"  {k}: {v}")
        lines.append("")
    v = summary.get("validation") or {}
    lines.append("-- validation --")
    lines.append(f"  passed_true: {v.get('passed_true', 0)}")
    lines.append(f"  passed_false: {v.get('passed_false', 0)}")
    lines.append(f"  passed_other_or_missing: {v.get('passed_other_or_missing', 0)}")
    return "\n".join(lines) + "\n"


def run_prep(
    patterns: Sequence[str],
    *,
    sort_files: SortFiles = "none",
    out_jsonl: Path | None = None,
    summary_json: Path | None = None,
) -> tuple[dict[str, dict[str, Any]], DedupeStats, dict[str, Any]]:
    paths = resolve_input_paths(patterns, sort=sort_files)
    deduped, dstats = dedupe_last_line_wins(paths)
    summary = build_summary(deduped)
    summary_full: dict[str, Any] = {
        "dedupe": asdict(dstats),
        "summary": summary,
    }
    if out_jsonl is not None:
        write_cleaned_jsonl(deduped, out_jsonl)
    if summary_json is not None:
        summary_json.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_json, "w", encoding="utf-8") as f:
            json.dump(summary_full, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return deduped, dstats, summary_full
