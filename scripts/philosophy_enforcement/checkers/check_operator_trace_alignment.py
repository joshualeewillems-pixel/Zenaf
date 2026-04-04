"""
Operator / Studio LLM routes must emit a server trace OR declare exemption (Phase 4 / 4B, Philosophy #15).

Scans ``api/routes/studio_routes.py`` and admin-only routes in ``api/routes/auth_routes.py``.
For each route whose handler (plus same-module callees) touches LLM primitives, requires either:

- A server trace helper call (``emit_server_ai_action_trace``, ``trace_core_profile_llm_route``,
  ``trace_meeting_debug_extract_route``, ``_emit_ve_server_trace``), or
- A matching ``exempt_routes`` row in ``docs/01_TRUTH/ai_trace_exemptions.json`` whose ``reason``
  references ``studio_admin_surface`` (operator carve-out).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_CHECKER_ID = "check_operator_trace_alignment"
_EXEMPTIONS_REL = "docs/01_TRUTH/ai_trace_exemptions.json"
_OPERATOR_FILES: tuple[tuple[str, bool], ...] = (
    # (path relative to repo, restrict_to_admin_dep_blocks)
    ("api/routes/studio_routes.py", False),
    ("api/routes/auth_routes.py", True),
)

_ROUTE_DECO = re.compile(
    r"^@router\.(get|post|put|patch|delete)\(\s*[\"']([^\"']*)[\"']",
    re.MULTILINE,
)
_ROUTER_PREFIX = re.compile(
    r"APIRouter\s*\(\s*[^)]*prefix\s*=\s*[\"']([^\"']+)[\"']",
    re.MULTILINE | re.DOTALL,
)
_LLM_RES = [
    re.compile(r"get_council_llm_adapter_for_principal\s*\("),
    re.compile(r"\.generate_text\s*\("),
    re.compile(r"LLMRequest\s*\("),
]
_TRACE_RES = [
    re.compile(r"emit_server_ai_action_trace\s*\("),
    re.compile(r"trace_core_profile_llm_route\s*\("),
    re.compile(r"trace_meeting_debug_extract_route\s*\("),
    re.compile(r"_emit_ve_server_trace\s*\("),
]


class _CalleeVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.names.add(node.func.id)
        self.generic_visit(node)


def _router_prefix(text: str) -> str:
    m = _ROUTER_PREFIX.search(text)
    return m.group(1).strip() if m else ""


def _full_path(prefix: str, route_path: str) -> str:
    p = prefix.rstrip("/")
    r = (route_path or "").strip()
    if not r:
        return p or "/"
    return f"{p}/{r.lstrip('/')}" if p else f"/{r.lstrip('/')}"


def _module_functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    out: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
    return out


def _closure_source(
    text: str,
    tree: ast.Module,
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    entry: str,
) -> str:
    if entry not in funcs:
        return ""
    seen: set[str] = set()
    stack = [entry]
    parts: list[str] = []
    while stack:
        name = stack.pop()
        if name not in funcs or name in seen:
            continue
        seen.add(name)
        node = funcs[name]
        seg = ast.get_source_segment(text, node)
        if seg:
            parts.append(seg)
        vis = _CalleeVisitor()
        vis.visit(node)
        for callee in vis.names:
            if callee in funcs:
                stack.append(callee)
    return "\n".join(parts)


def _any_pattern(src: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(src) for p in patterns)


def _load_studio_admin_exemptions(repo: Path) -> tuple[list[dict], list[Finding]]:
    findings: list[Finding] = []
    fp = repo / _EXEMPTIONS_REL
    if not fp.is_file():
        findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="ai_trace_exemptions.json missing — cannot validate operator LLM exemptions",
                location=_EXEMPTIONS_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return [], findings
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=f"ai_trace_exemptions.json invalid JSON: {e}",
                location=_EXEMPTIONS_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return [], findings
    routes = data.get("exempt_routes")
    if not isinstance(routes, list):
        findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="ai_trace_exemptions.json missing exempt_routes array",
                location=_EXEMPTIONS_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return [], findings
    studio_rows: list[dict] = []
    for item in routes:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or "")
        if "studio_admin_surface" in reason.lower():
            studio_rows.append(item)
    if not studio_rows:
        findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="exempt_routes must include at least one entry whose reason cites studio_admin_surface (4B contract)",
                location=_EXEMPTIONS_REL,
                checker_id=_CHECKER_ID,
            )
        )
    return studio_rows, findings


def _exempt_covers(method: str, full_path: str, studio_rows: list[dict]) -> bool:
    m = method.upper()
    for item in studio_rows:
        methods = [str(x).upper() for x in (item.get("methods") or [])]
        if m not in methods:
            continue
        pc = str(item.get("path_contains") or "")
        if pc and pc in full_path:
            return True
    return False


def _route_entry_names(text: str) -> list[tuple[str, str, str, int]]:
    """(http_method, path, function_name, line_1based) per @router block."""
    out: list[tuple[str, str, str, int]] = []
    for m in _ROUTE_DECO.finditer(text):
        method = m.group(1).upper()
        path = m.group(2)
        start = m.start()
        line_no = text[:start].count("\n") + 1
        rest = text[m.end() :]
        next_at = rest.find("\n@router.")
        block = rest if next_at < 0 else rest[:next_at]
        dm = re.search(r"^def\s+(\w+)\s*\(", block, re.MULTILINE)
        if not dm:
            continue
        out.append((method, path, dm.group(1), line_no))
    return out


def _scan_file(
    repo: Path,
    rel: str,
    restrict_admin: bool,
    studio_rows: list[dict],
    out: CheckerRun,
) -> None:
    fp = repo / rel
    if not fp.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=f"Operator route file missing: {rel}",
                location=rel,
                checker_id=_CHECKER_ID,
            )
        )
        return
    text = fp.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=f"SyntaxError in {rel}: {e}",
                location=rel,
                checker_id=_CHECKER_ID,
            )
        )
        return
    funcs = _module_functions(tree)
    prefix = _router_prefix(text)

    for method, path, fname, line_no in _route_entry_names(text):
        block_start = text.find(f"def {fname}")
        block_end = text.find("\n@router.", block_start + 1)
        block = text[block_start:block_end] if block_start >= 0 else ""
        if restrict_admin and "get_current_admin_user" not in block:
            continue
        full = _full_path(prefix, path)
        combined = _closure_source(text, tree, funcs, fname)
        if not combined:
            continue
        if not _any_pattern(combined, _LLM_RES):
            continue
        if _any_pattern(combined, _TRACE_RES):
            continue
        if _exempt_covers(method, full, studio_rows):
            continue
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=(
                    f"Operator route {method} {full} ({fname}) invokes LLM but has no server trace "
                    "and no studio_admin_surface exempt_routes match in ai_trace_exemptions.json"
                ),
                location=f"{rel}:{line_no}",
                detail=f"handler={fname}",
                checker_id=_CHECKER_ID,
            )
        )


@register("check_operator_trace_alignment")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id=_CHECKER_ID)
    studio_rows, pre = _load_studio_admin_exemptions(repo)
    out.findings.extend(pre)
    for rel, restrict in _OPERATOR_FILES:
        _scan_file(repo, rel, restrict, studio_rows, out)
    return out


def run_exploratory(repo: Path) -> CheckerRun:
    return run(repo)
