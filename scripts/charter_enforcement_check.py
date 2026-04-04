#!/usr/bin/env python3
"""
Charter enforcement — minimal mechanical checks (v0).

Maps to docs/01_TRUTH/ATRIA_SYSTEM_CHARTER.md:
  §4 Traceability  — server trace or declared exempt marker on VE LLM routes
  §2 Save/commit   — infer_draft_value_from_context + heuristic scan
  §5 Product honesty — stub UI affordance (Clarify with AI)

Output: stdout report aligned with ATRIA_CHARTER_VIOLATION_LEDGER.md categories.
Exit code: 0 always (report-only). Set CHARTER_ENFORCE_STRICT=1 to exit 1 on any §4 finding.

Limitations: AST scan is vision_execution router only; POST /run is summarized, not deep-routed.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_VE_ROUTES = _REPO / "api" / "routes" / "vision_execution.py"
_MAIN = _REPO / "api" / "main.py"
_EXEMPT_TS = _REPO / "frontend" / "src" / "ai-actions" / "aiTraceExemptRegistry.ts"
_CLARIFY_UI = _REPO / "frontend" / "src" / "vision-execution" / "VisionExecutionView.tsx"
_INTEGRATION_COMMIT = _REPO / "local_ai" / "integration_commit.py"

TRACE_MARKERS = (
    "trace_core_profile_llm_route",
    "trace_meeting_debug_extract_route",
    "emit_server_ai_action_trace",
    # Shared helper in api/routes/vision_execution.py (wraps emit_server_ai_action_trace).
    "_emit_ve_server_trace",
)
# Bodies that call LLM without necessarily using _run_ve_llm_with_routing
LLM_MARKERS = (
    "_run_ve_llm_with_routing",
    "distill_content_source",
    "rewrite_focus_field",
    "generate_project_suggested_work",
)
# Meeting extract calls local extract (LLM inside module)
MEETING_ROUTE_NAMES = frozenset(
    {
        "extract_meeting",
        "extract_segment_summary",
        "extract_meeting_segments",
        "extract_meeting_synthesis",
    }
)

EXEMPT_COMMENT_RE = re.compile(r"#\s*charter-trace-exempt:\s*([a-z0-9_]+)", re.I)


def _load_exempt_ids() -> set[str]:
    if not _EXEMPT_TS.is_file():
        return set()
    text = _EXEMPT_TS.read_text(encoding="utf-8")
    return set(re.findall(r"id:\s*'([^']+)'", text))


def _iter_router_functions(py_file: Path) -> list[tuple[str, str]]:
    text = py_file.read_text(encoding="utf-8")
    tree = ast.parse(text)
    out: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        routed = False
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if dec.func.attr in ("get", "post", "put", "patch", "delete"):
                    routed = True
                    break
        if not routed:
            continue
        seg = ast.get_source_segment(text, node)
        if seg:
            out.append((node.name, seg))
    return out


def _function_uses_llm(name: str, src: str) -> bool:
    if any(m in src for m in LLM_MARKERS):
        return True
    if name in MEETING_ROUTE_NAMES:
        return True
    return False


def _function_has_server_trace(src: str) -> bool:
    return any(m in src for m in TRACE_MARKERS)


def _function_exempt_comment(src: str) -> str | None:
    m = EXEMPT_COMMENT_RE.search(src)
    return m.group(1).strip().lower() if m else None


def check_trace_ve_routes(exempt_ids: set[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for fname, src in _iter_router_functions(_VE_ROUTES):
        if not _function_uses_llm(fname, src):
            continue
        ex = _function_exempt_comment(src)
        if ex:
            if ex not in exempt_ids:
                findings.append(
                    {
                        "ledger": "Trace / charter 4 (exempt id mismatch)",
                        "severity": "minor",
                        "rule": "Charter 4.1 trace or exempt",
                        "where": f"api/routes/vision_execution.py::{fname}",
                        "detail": f"charter-trace-exempt:{ex} not in aiTraceExemptRegistry.ts",
                    }
                )
            continue
        if _function_has_server_trace(src):
            continue
        findings.append(
            {
                "ledger": "Trace / charter 4 (server trace gap)",
                "severity": "misleading",
                "rule": "Charter 4.3 server trace authority",
                "where": f"api/routes/vision_execution.py::{fname}",
                "detail": "LLM/heavy path: no trace_core_profile_llm_route, trace_meeting_debug_extract_route, or emit_server_ai_action_trace in route body",
            }
        )
    return findings


def check_run_gateway() -> list[dict[str, str]]:
    """POST /run and /run/stream: client workspace traces; not server_emit — informational."""
    if not _MAIN.is_file():
        return []
    t = _MAIN.read_text(encoding="utf-8")
    if "def run" not in t and "/run" not in t:
        return []
    return [
        {
            "ledger": "Trace / charter 4 (client-primary gateway)",
            "severity": "minor",
            "rule": "Charter 4.1 / 4.3",
            "where": "api/main.py POST /run, /run/stream",
            "detail": "LLM gateway: primary trace is client AiActionTrace (workspaceRunWithTrace). Server council persists artifacts separately; not evaluated per-mode here.",
        }
    ]


def check_commit_determinism() -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if _INTEGRATION_COMMIT.is_file() and "infer_draft_value_from_context" in _INTEGRATION_COMMIT.read_text(
        encoding="utf-8"
    ):
        findings.append(
            {
                "ledger": "Commit / charter 2 (review call sites)",
                "severity": "misleading",
                "rule": "Charter 2.3 payload integrity",
                "where": "local_ai/integration_commit.py",
                "detail": "infer_draft_value_from_context defined — fallback when [DRAFT_VALUE] missing; must stay narrow and visible.",
            }
        )
    atools = _REPO / "local_ai" / "atria_tools.py"
    if atools.is_file() and "infer_draft_value_from_context" in atools.read_text(encoding="utf-8"):
        findings.append(
            {
                "ledger": "Commit / charter 2 (review call sites)",
                "severity": "minor",
                "rule": "Charter 2.3",
                "where": "local_ai/atria_tools.py",
                "detail": "Invokes infer_draft_value_from_context — confirm only on conversational integration path with empty task text.",
            }
        )
    return findings


def check_phantom_clarify() -> list[dict[str, str]]:
    if not _CLARIFY_UI.is_file():
        return []
    t = _CLARIFY_UI.read_text(encoding="utf-8")
    if "Clarify with AI" not in t:
        return []
    if "handleClarifyWithAI" not in t:
        return []
    # Stub: setTimeout local fill, no fetch to evaluate API
    block_start = t.find("const handleClarifyWithAI")
    if block_start < 0:
        return []
    block = t[block_start : block_start + 800]
    if "apiPost" in block or "fetch(" in block:
        return []
    return [
        {
            "ledger": "Product honesty / charter 5 (violation candidate)",
            "severity": "misleading",
            "rule": "Charter 5.3 UI language",
            "where": "frontend/src/vision-execution/VisionExecutionView.tsx (Idea Lab)",
            "detail": 'Button "Clarify with AI" uses timed local placeholder text — no LLM/API; label implies AI (see ACTIVE_VS_PLANNED.md matrix).',
        }
    ]


def main() -> int:
    exempt_ids = _load_exempt_ids()
    sections: list[tuple[str, list[dict[str, str]]]] = [
        ("Charter 4 — vision_execution LLM routes (server trace or # charter-trace-exempt: <id>)", check_trace_ve_routes(exempt_ids)),
        ("Charter 4 — /run gateway note", check_run_gateway()),
        ("Charter 2 — commit / payload (integration_commit)", check_commit_determinism()),
        ("Charter 5 — phantom / overpromise (Clarify with AI stub)", check_phantom_clarify()),
    ]

    print("Atria charter enforcement check (v0)")
    print(f"Repo: {_REPO}")
    print(f"Loaded exempt ids from aiTraceExemptRegistry.ts: {sorted(exempt_ids)}")
    print()

    all_findings: list[dict[str, str]] = []
    for title, findings in sections:
        print(f"=== {title} ===")
        if not findings:
            print("  (no findings)")
        for f in findings:
            print(f"  [{f['severity']}] {f['rule']}")
            print(f"    Ledger bucket: {f['ledger']}")
            print(f"    Where: {f['where']}")
            print(f"    {f['detail']}")
            all_findings.append(f)
        print()

    if os.environ.get("CHARTER_ENFORCE_STRICT") == "1":
        misleading = [f for f in all_findings if f["severity"] == "misleading"]
        if misleading:
            print(f"CHARTER_ENFORCE_STRICT: failing on {len(misleading)} misleading finding(s).", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
