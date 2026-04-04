"""
Trace coverage (client): AI-touching api/routes endpoints should have a frontend caller
that emits AiActionTrace (or equivalent) unless exempt in ai_trace_exemptions.json.

Does not parse Markdown program state. Does not modify product code.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from ..models import CheckerRun, Finding, FindingKind
from . import register

_EXEMPT_JSON = Path("docs/01_TRUTH/ai_trace_exemptions.json")
_ROUTES_DIR = Path("api/routes")

# Server-side LLM / heavy-AI indicators (route handler body).
_LLM_MARKERS = (
    "_run_ve_llm_with_routing",
    "distill_content_source",
    "rewrite_focus_field",
    "generate_project_suggested_work",
    "emit_server_ai_action_trace",
    "trace_core_profile_llm_route",
    "trace_meeting_debug_extract_route",
    "_emit_ve_server_trace",
    "get_council_llm_adapter",
    "adapter.generate_text",
    "LLMRequest(",
    "infer_draft_value_from_context",
    "audio/transcriptions",
    "whisper-1",
)
_MEETING_FN = frozenset(
    {
        "extract_meeting",
        "extract_segment_summary",
        "extract_meeting_segments",
        "extract_meeting_synthesis",
    }
)

# Frontend: must appear in a file that references the route (same-file heuristic).
_CLIENT_TRACE_MARKERS = (
    "pushAiActionTrace",
    "createAiActionTrace",
    "workspaceRunWithTrace",
    "recordMeetingExtractionTraceOutcome",
    "recordCoreProfileTraceOutcome",
    "recordContentTraceOutcome",
)


def _load_exemptions(repo: Path) -> dict[str, Any]:
    p = repo / _EXEMPT_JSON
    if not p.is_file():
        return {"exempt_endpoints": [], "exempt_routes": [], "exempt_inline_llm": []}
    return json.loads(p.read_text(encoding="utf-8"))


def _endpoint_exempt(method: str, full_path: str, cfg: dict[str, Any]) -> str | None:
    m = method.upper()
    combined = list(cfg.get("exempt_endpoints", [])) + list(cfg.get("exempt_routes", []))
    for ex in combined:
        methods = [x.upper() for x in ex.get("methods", [])]
        if methods and m not in methods:
            continue
        sub = ex.get("path_contains", "")
        if sub and sub in full_path:
            return str(ex.get("reason", "exempt"))
    return None


def _body_exempt_inline(src: str, cfg: dict[str, Any]) -> str | None:
    """If handler only uses infer_draft_value_from_context and no other LLM markers, exempt per policy."""
    if "infer_draft_value_from_context" not in src:
        return None
    trimmed = src
    for entry in cfg.get("exempt_inline_llm", []):
        sym = entry.get("symbol", "")
        if sym and sym in trimmed:
            # Strip the exempt symbol line-ish and see if other LLM markers remain.
            remainder = trimmed.replace(sym, "")
            if not any(m in remainder for m in _LLM_MARKERS if m != "infer_draft_value_from_context"):
                return str(entry.get("reason", "inline exempt"))
    return None


def _router_prefix(tree: ast.Module, text: str) -> str:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "router":
                val = node.value
                if not isinstance(val, ast.Call):
                    continue
                if isinstance(val.func, ast.Name) and val.func.id == "APIRouter":
                    for kw in val.keywords:
                        if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                            p = kw.value.value
                            if isinstance(p, str):
                                return p.rstrip("/")
    return ""


def _iter_routes(
    tree: ast.Module, text: str, file_prefix: str
) -> list[tuple[str, str, str, int]]:
    """(method, full_path, function_name, lineno)"""
    router_prefix = _router_prefix(tree, text)
    base = (router_prefix + file_prefix).rstrip("/")
    out: list[tuple[str, str, str, int]] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        method: str | None = None
        path_piece: str | None = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if dec.func.attr not in ("get", "post", "put", "patch", "delete"):
                    continue
                method = dec.func.attr.upper()
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    raw = dec.args[0].value
                    if isinstance(raw, str):
                        path_piece = raw
                break
        if not method or path_piece is None:
            continue
        sub = path_piece if path_piece.startswith("/") else "/" + path_piece
        full = (base + sub).replace("//", "/")
        if not full.startswith("/"):
            full = "/" + full
        out.append((method, full, node.name, node.lineno))
    return out


def _uses_llm(name: str, src: str) -> bool:
    if name in _MEETING_FN:
        return True
    if any(m in src for m in _LLM_MARKERS):
        return True
    return False


def _function_src(text: str, node: ast.FunctionDef) -> str:
    seg = ast.get_source_segment(text, node)
    return seg or ""


def _literals_for_path(full_path: str) -> list[str]:
    """Path segments excluding {param} for 'all literals must appear' FE match."""
    parts = [
        p
        for p in full_path.split("/")
        if p and not (p.startswith("{") and p.endswith("}"))
    ]
    return [p for p in parts if len(p) >= 2]


def _frontend_files(repo: Path) -> dict[Path, str]:
    root = repo / "frontend" / "src"
    if not root.is_dir():
        return {}
    out: dict[Path, str] = {}
    for p in root.rglob("*.ts"):
        try:
            out[p] = p.read_text(encoding="utf-8")
        except OSError:
            continue
    for p in root.rglob("*.tsx"):
        try:
            out[p] = p.read_text(encoding="utf-8")
        except OSError:
            continue
    return out


def _fe_looks_like_http_caller(body: str) -> bool:
    return any(
        x in body
        for x in (
            "fetch(",
            "veApiPost",
            "veApiGet",
            "veApiPatch",
            "apiPost",
            "apiGet",
            "apiPatch",
            "axios.",
            "XMLHttpRequest",
        )
    )


def _is_core_profiles_conversation_route(full_path: str) -> bool:
    fp = full_path.rstrip("/")
    return "/core-profiles/" in fp and fp.endswith("/conversation")


# Template / string URL evidence for POST .../core-profiles/{id}/conversation (not bare word "conversation").
_CORE_PROFILE_CONVERSATION_URL_PATTERNS = (
    re.compile(r"/core-profiles/\$\{[^}]+\}/conversation'"),
    re.compile(r'/core-profiles/\$\{[^}]+\}/conversation"'),
    re.compile(r"/core-profiles/\$\{[^}]+\}/conversation`"),
    re.compile(r"`/core-profiles/\$\{[^}]+\}/conversation`"),
    re.compile(r"'/core-profiles/\$\{[^}]+\}/conversation'"),
    re.compile(r'"/core-profiles/\$\{[^}]+\}/conversation"'),
)


def _core_profiles_conversation_url_evidence(body: str) -> bool:
    return any(p.search(body) for p in _CORE_PROFILE_CONVERSATION_URL_PATTERNS)


def _path_literals_match_body(full_path: str, body: str) -> bool:
    """
    Match route path to FE source. Vision Execution callers often use relative paths
    (apiPost('/extract-meeting')) without the literal substring 'vision-execution'.
    """
    parts = _literals_for_path(full_path)
    if not parts:
        return False
    if full_path.startswith("/vision-execution"):
        rest = [p for p in parts if p != "vision-execution"]
        if not rest:
            return "VISION_EXECUTION_API" in body or "/vision-execution" in body
        return all(p in body for p in rest)
    return all(p in body for p in parts)


def _fe_matches_route(full_path: str, texts: dict[Path, str]) -> list[Path]:
    matched: list[Path] = []
    for path, body in texts.items():
        if _is_core_profiles_conversation_route(full_path):
            if not (_core_profiles_conversation_url_evidence(body) and _fe_looks_like_http_caller(body)):
                continue
        else:
            if not _path_literals_match_body(full_path, body):
                continue
            if not _fe_looks_like_http_caller(body):
                continue
        matched.append(path)
    return matched


def _file_traced(body: str) -> bool:
    return any(m in body for m in _CLIENT_TRACE_MARKERS)


@register("trace_coverage")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="trace_coverage")
    cfg = _load_exemptions(repo)
    routes_dir = repo / _ROUTES_DIR
    if not routes_dir.is_dir():
        out.error = f"Missing {_ROUTES_DIR}"
        return out

    fe_texts = _frontend_files(repo)
    if not fe_texts:
        out.findings.append(
            Finding(
                kind=FindingKind.HEURISTIC_SUSPICION,
                message="No frontend/src .ts/.tsx files found — client trace check skipped for coverage",
                location="frontend/src",
                checker_id="trace_coverage",
            )
        )

    # Per-file prefix when include_router(router, prefix="/settings") — only settings_routes uses it in main.
    FILE_PREFIX = {
        "settings_routes.py": "/settings",
    }

    for py_path in sorted(routes_dir.glob("*.py")):
        if py_path.name.startswith("_"):
            continue
        text = py_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            out.findings.append(
                Finding(
                    kind=FindingKind.HEURISTIC_SUSPICION,
                    message=f"SyntaxError in {py_path.name}: {e}",
                    location=str(py_path.relative_to(repo)),
                    checker_id="trace_coverage",
                )
            )
            continue

        fprefix = FILE_PREFIX.get(py_path.name, "")
        for method, full_path, fname, lineno in _iter_routes(tree, text, fprefix):
            node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fname), None)
            if node is None:
                continue
            src = _function_src(text, node)
            if not _uses_llm(fname, src):
                continue
            if method == "GET":
                if not any(m in src for m in _LLM_MARKERS):
                    continue
            elif method not in ("POST", "PUT", "PATCH"):
                continue

            ex = _endpoint_exempt(method, full_path, cfg)
            if ex:
                continue
            inline = _body_exempt_inline(src, cfg)
            if inline:
                continue

            rel = f"{py_path.relative_to(repo).as_posix()}:{fname}"
            loc = f"{method} {full_path} ({rel}:{lineno})"

            callers = _fe_matches_route(full_path, fe_texts)
            if not callers:
                out.findings.append(
                    Finding(
                        kind=FindingKind.HEURISTIC_SUSPICION,
                        message="AI route: no frontend/src reference matched by path literals — verify CLI/server-only or add client trace when UI calls this",
                        location=loc,
                        detail=f"path_literals={_literals_for_path(full_path)}",
                        checker_id="trace_coverage",
                    )
                )
                continue

            bad = [p for p in callers if not _file_traced(fe_texts[p])]
            if bad:
                preview = ", ".join(p.relative_to(repo).as_posix() for p in bad[:5])
                if len(bad) > 5:
                    preview += f", +{len(bad) - 5} more"
                out.findings.append(
                    Finding(
                        kind=FindingKind.CONFIRMED_VIOLATION,
                        message="AI route called from frontend without client AiActionTrace signals in same file (pushAiActionTrace / workspaceRunWithTrace / record*TraceOutcome / createAiActionTrace)",
                        location=loc,
                        detail=f"untraced_callers={preview}",
                        checker_id="trace_coverage",
                    )
                )

    return out
