"""
Canonical core identity (Wave 2C / Track A): detect hardcoded first-profile peering and
risky .find() selection without is_primary / is_canonical or keyed lookup.

Scans frontend/src, api/, and local_ai/**/*.py. Does not modify product code.
Exemption: same-line or previous-line comment containing `canonical-identity-exempt`.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_EXEMPT_MARK = "canonical-identity-exempt"

# Whole-file allowlist: canonical resolver implementation may use profiles[0] as last-resort fallback.
_ALLOWLIST_FILE_SUBSTRINGS = (
    "canonicalCoreProfile.ts",
    "canonical_core_profile",
)

# Per-path skips (tests / generated).
_SKIP_PATH_SUBSTRINGS = (
    "/__tests__/",
    ".test.ts",
    ".test.tsx",
    ".spec.ts",
    ".spec.tsx",
)

# FE: alternate names for core profile lists (not `profiles[0]` on FE — canonical_identity_leaks).
_INDEX_PATTERN_FE = re.compile(
    r"\b(coreProfiles|core_profiles|workspaceCoreProfiles|coreProfileRows)\s*\[\s*0\s*\]",
    re.I,
)
# api/*.py and local_ai/**/*.py: `profiles` from list_core_profiles etc.
_INDEX_PATTERN_API_PROFILES = re.compile(r"\bprofiles\s*\[\s*0\s*\]", re.I)

# .find( on those collections — single-line heuristic; exempt if is_primary, is_canonical, or equality lookup.
_FIND_HEAD = re.compile(
    r"\b(profiles|coreProfiles|core_profiles)\s*\.find\s*\(",
    re.I,
)


def _skip_path(rel: str) -> bool:
    r = rel.replace("\\", "/")
    if any(s in r for s in _SKIP_PATH_SUBSTRINGS):
        return True
    return False


def _allowlist_file(rel: str) -> bool:
    r = rel.replace("\\", "/")
    return any(a in r for a in _ALLOWLIST_FILE_SUBSTRINGS)


def _line_exempt(line: str, prev: str) -> bool:
    low = (line + "\n" + prev).lower()
    return _EXEMPT_MARK in low


def _find_line_safe_predicate(line: str) -> bool:
    """True if .find line plausibly uses primary/canonical or keyed lookup (not arbitrary first match)."""
    if "is_primary" in line or "is_canonical" in line:
        return True
    if "===" in line or "==" in line:
        return True
    return False


def _scan_file(fp: Path, repo: Path, out: CheckerRun, *, use_profiles_index: bool) -> None:
    rel = fp.relative_to(repo).as_posix()
    if _skip_path(rel):
        return
    allow_file = _allowlist_file(rel)
    try:
        text = fp.read_text(encoding="utf-8")
    except OSError:
        return
    lines = text.splitlines()
    for i, line in enumerate(lines):
        prev = lines[i - 1] if i > 0 else ""
        if _line_exempt(line, prev):
            continue

        # Strip trailing Python comments; skip full-line comments (avoids matching mentions in `# ...` text).
        scan_line = line
        if fp.suffix == ".py":
            code, _, _cmt = line.partition("#")
            scan_line = code.rstrip()
            if not scan_line.strip():
                continue

        hit_index = _INDEX_PATTERN_FE.search(scan_line) or (
            use_profiles_index and _INDEX_PATTERN_API_PROFILES.search(scan_line)
        )
        if hit_index:
            if allow_file:
                continue
            out.findings.append(
                Finding(
                    kind=FindingKind.CONFIRMED_VIOLATION,
                    message="Hardcoded index [0] on core-profile list — use canonical resolver or exempt with canonical-identity-exempt",
                    location=f"{rel}:{i + 1}",
                    detail=line.strip()[:200],
                    checker_id="check_canonical_identity",
                )
            )

        if _FIND_HEAD.search(scan_line) and not _find_line_safe_predicate(scan_line):
            out.findings.append(
                Finding(
                    kind=FindingKind.CONFIRMED_VIOLATION,
                    message="profiles/coreProfiles .find without is_primary, is_canonical, or equality — risks non-canonical peering",
                    location=f"{rel}:{i + 1}",
                    detail=line.strip()[:200],
                    checker_id="check_canonical_identity",
                )
            )


@register("check_canonical_identity")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="check_canonical_identity")

    fe_root = repo / "frontend" / "src"
    if fe_root.is_dir():
        for pat in ("**/*.ts", "**/*.tsx"):
            for fp in fe_root.glob(pat):
                if fp.is_file():
                    _scan_file(fp, repo, out, use_profiles_index=False)

    api_root = repo / "api"
    if api_root.is_dir():
        for fp in api_root.rglob("*.py"):
            if fp.is_file():
                _scan_file(fp, repo, out, use_profiles_index=True)

    local_ai_root = repo / "local_ai"
    if local_ai_root.is_dir():
        for fp in local_ai_root.rglob("*.py"):
            if fp.is_file():
                _scan_file(fp, repo, out, use_profiles_index=True)

    return out
