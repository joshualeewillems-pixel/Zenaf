from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import PhilosophyRow, RowStatus
from .program_state import load_program_state


def render_markdown(
    rows: list[PhilosophyRow],
    repo: Path,
    program_state: dict[str, Any] | None = None,
) -> str:
    lines = [
        "# Philosophy enforcement report",
        "",
        f"- Generated: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Repo: `{repo}`",
        "",
    ]
    if program_state is not None:
        src = "docs/01_TRUTH/convergence_program_state.json"
        phase = program_state.get("active_phase", "")
        label = program_state.get("active_phase_label") or ""
        phase_line = f"**{phase}**"
        if label:
            phase_line += f" — {label}"
        lines.extend(
            [
                "## Program state (from JSON only)",
                "",
                f"- Source: `{src}`",
                f"- Active phase: {phase_line}",
                f"- Operating loop: {program_state.get('operating_loop', '')}",
                "",
                "| Objective ID | Title | Track |",
                "|--------------|-------|-------|",
            ]
        )
        for obj in program_state.get("active_objectives", []):
            oid = str(obj.get("id", "")).replace("|", "\\|")
            title = str(obj.get("title", "")).replace("|", "\\|")
            track = str(obj.get("track", "")).replace("|", "\\|")
            lines.append(f"| {oid} | {title} | {track} |")
        blocked = program_state.get("blocked") or []
        if blocked:
            lines.extend(["", "**Blocked:**", ""])
            lines.extend(f"- {b}" for b in blocked)
        else:
            lines.extend(["", "**Blocked:** *(none)*", ""])
        notes = str(program_state.get("notes", "")).replace("|", "\\|")
        lines.extend(["", f"**Notes:** {notes}", ""])
    lines.extend(
        [
            "| Philosophy | Status | Findings | Suggested next action |",
            "|------------|--------|----------|------------------------|",
        ]
    )
    for r in rows:
        find_parts = []
        for f in r.findings:
            tag = "**confirmed**" if f.kind.value == "confirmed_violation" else "*heuristic*"
            loc = f.location.replace("|", "\\|")
            find_parts.append(f"{tag}: {f.message} — `{loc}`")
        findings_cell = "<br>".join(find_parts) if find_parts else "—"
        action = r.suggested_next_action.replace("|", "\\|")
        lines.append(
            f"| {r.name} ({r.philosophy_id}) | `{r.status.value}` | {findings_cell} | {action} |"
        )
    lines.extend(
        [
            "",
            "## Legend",
            "",
            "- **confirmed**: static rule hit (treat as violation).",
            "- *heuristic*: needs human review.",
            "- `not-yet-automated`: no checker wired for this philosophy in the registry.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_reports(
    rows: list[PhilosophyRow],
    repo: Path,
    out_dir: Path | None = None,
    program_state: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    if program_state is None:
        program_state = load_program_state(repo)
    out = out_dir or (repo / "reports" / "philosophy_enforcement")
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / "latest.md"
    json_path = out / "latest.json"
    payload: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "program_state_source": "docs/01_TRUTH/convergence_program_state.json",
        "program_state": program_state,
        "rows": [r.to_dict() for r in rows],
        "summary": {
            "pass": sum(1 for r in rows if r.status == RowStatus.PASS),
            "fail": sum(1 for r in rows if r.status == RowStatus.FAIL),
            "partial": sum(1 for r in rows if r.status == RowStatus.PARTIAL),
            "not_yet_automated": sum(1 for r in rows if r.status == RowStatus.NOT_YET_AUTOMATED),
        },
    }
    md_path.write_text(render_markdown(rows, repo, program_state=program_state), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return md_path, json_path
