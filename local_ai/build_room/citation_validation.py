"""Tool-access stage-1 increment C: ingestion-time citation validation.

Pure functions, no model calls, no I/O. A tool citation in claim
text has the form ``path@revision:lines`` (e.g.
``build_room/meeting.py@a1b2c3:1845-1870`` or a single line
``build_room/meeting.py@a1b2c3:42``).

Correction §5 (mark, never strip): a citation is GROUNDED if and
only if its path, revision, AND cited line range match a successful
runner-recorded read in the generation's tool-call log — same path
(after snapshot normalization), same revision, cited range SUBSET
of the recorded returned range. Anything else is marked
``unverified``. The claim text is NEVER altered: validation only
annotates. There is no grounding score — the rule is
marked-unverified + excluded from grounded counts.

Validation source: the transcript tool-call log (the entries the
runner recorded during the generation). Only entries with outcome
``"returned"`` can ground a citation; refused/capped entries ground
nothing, including a lines-citation to a path whose read was
refused.

Judgment call (flagged in the increment-C PR): a truncated read
grounds per its RECORDED ``lines`` range, and the entry's
``truncated`` flag travels with it for reviewer scrutiny. The log
does not record how many lines a truncated delivery covered, so a
finer delivered-range rule cannot be computed from the log alone;
over-grounding on truncated reads is bounded by the recorded range
and visible via the flag, never silent.
"""

from __future__ import annotations

import re
from typing import Any

from local_ai.build_room.tool_access import normalize_snapshot_path

# No "/" requirement on the path: a bare filename is a legitimate
# snapshot path, and missing it would leave a citation unvalidated
# (a gap). False positives are fail-closed, not fail-open: an
# accidental match can only ever be marked unverified, since
# grounding additionally requires a runner-recorded read with the
# same path, revision, and covering range. The revision group is
# alphanumeric-only, so dotted strings (e.g. email domains) do not
# match as revisions.
_TOOL_CITATION_RE = re.compile(
    r"(?P<path>[A-Za-z0-9_.\-/]+)"
    r"@(?P<revision>[A-Za-z0-9]+)"
    r":(?P<lines>\d+(?:-\d+)?)"
)


def find_tool_citations(text: str) -> list[dict[str, Any]]:
    """Extract tool citations from claim text, in order of appearance.

    Each result carries the verbatim matched string plus the parsed
    path, revision, and line range (single line N becomes N-N).
    Text is never modified here.
    """
    found: list[dict[str, Any]] = []
    for match in _TOOL_CITATION_RE.finditer(text or ""):
        lines = match.group("lines")
        if "-" in lines:
            start_s, end_s = lines.split("-", 1)
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(lines)
        found.append({
            "citation": match.group(0),
            "path": match.group("path"),
            "revision": match.group("revision"),
            "line_start": start,
            "line_end": end,
        })
    return found


def _parse_recorded_lines(lines: str | None) -> tuple[int, int] | None:
    """Parse a log entry's recorded ``lines`` field ("A-B") or None."""
    if not isinstance(lines, str) or "-" not in lines:
        return None
    try:
        start_s, end_s = lines.split("-", 1)
        return int(start_s), int(end_s)
    except ValueError:
        return None


def validate_tool_citations(
    text: str, tool_entries: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Validate every tool citation in ``text`` against the log.

    ``tool_entries`` are the runner-recorded entries for THIS
    generation (same participant, same phase). Returns one
    annotation per citation found: the verbatim citation, its
    parsed parts, ``status`` ("grounded" or "unverified"), and a
    ``reason`` (None when grounded, otherwise what failed to match).
    An empty tool log means every citation is unverified — a
    citation to a read that never happened cannot be grounded.
    """
    entries = tool_entries or []
    returned = [
        e for e in entries
        if isinstance(e, dict) and e.get("outcome") == "returned"
    ]
    annotations: list[dict[str, Any]] = []
    for citation in find_tool_citations(text):
        cited_path = normalize_snapshot_path(citation["path"])
        reason: str | None = None
        for entry in returned:
            resolved = entry.get("resolved_path")
            if resolved is None:
                continue
            if normalize_snapshot_path(str(resolved)) != cited_path:
                continue
            if entry.get("revision") != citation["revision"]:
                reason = "revision_mismatch"
                continue
            recorded = _parse_recorded_lines(entry.get("lines"))
            if recorded is None:
                reason = "unparseable_returned_range"
                continue
            rec_start, rec_end = recorded
            if (citation["line_start"] >= rec_start
                    and citation["line_end"] <= rec_end):
                reason = None
                break
            reason = "range_not_covered"
        else:
            if reason is None:
                reason = "no_matching_returned_read"
        annotations.append({
            "citation": citation["citation"],
            "path": citation["path"],
            "revision": citation["revision"],
            "line_start": citation["line_start"],
            "line_end": citation["line_end"],
            "status": "grounded" if reason is None else "unverified",
            "reason": reason,
        })
    return annotations
