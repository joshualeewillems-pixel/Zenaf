"""
Intake observability (Philosophy #10).

The intake mirror schema defines ``mirror_sync`` (last poll / cursor) and ``mailbox_action`` (audit).
If those tables are part of the declared substrate, the **real poll path** should persist sync state,
and mailbox mutations should record audit rows when implemented.

This checker surfaces the gap documented in ``docs/01_TRUTH/BOOT_FLOW.md`` and
``docs/OPEN_QUESTIONS.md``: ``poll_ingest_emails`` does not call ``mirror.set_sync_state``, and
``record_mailbox_action`` has no call sites outside its definition (unless
``intake-observability-exempt:`` + ``mailbox mutations parked`` documents a v1-parked gap in ``mirror.py``).

Emits **confirmed violations** for Track B: wire writers, document exempt, or narrow TRUTH claims.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_CHECKER_ID = "check_intake_observability"
_MIRROR_REL = "local_ai/intake/mirror.py"
_INGEST_REL = "local_ai/intake/email_ingestion.py"
_ROUTES_REL = "api/routes/intake_routes.py"
_MIRROR_SYNC_DDL = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+mirror_sync",
    re.IGNORECASE | re.DOTALL,
)
_DEF_RECORD_MAILBOX = re.compile(r"^\s*def\s+record_mailbox_action\s*\(")
# TRUTH-acknowledged gap: mailbox_action table with no writers until mutations exist (Phase 5 Track B).
_MAILBOX_ACTION_EXEMPT = "intake-observability-exempt:"
_MAILBOX_ACTION_EXEMPT_HINT = "mailbox mutations parked"


def _repo_text(repo: Path, rel: str) -> str | None:
    p = repo / rel
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8")


def _record_mailbox_called_outside_def(repo: Path) -> bool:
    """True if any non-definition line contains a call-like ``record_mailbox_action(``."""
    roots = [repo / "local_ai", repo / "api"]
    skip_prefixes = ("tests/",)
    for base in roots:
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(repo).as_posix()
            if rel.startswith(skip_prefixes):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                if "record_mailbox_action(" not in line:
                    continue
                if _DEF_RECORD_MAILBOX.match(line):
                    continue
                return True
    return False


@register("check_intake_observability")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id=_CHECKER_ID)
    mirror_txt = _repo_text(repo, _MIRROR_REL)
    ingest_txt = _repo_text(repo, _INGEST_REL)
    routes_txt = _repo_text(repo, _ROUTES_REL)

    if mirror_txt is None:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="local_ai/intake/mirror.py missing — cannot verify intake observability",
                location=_MIRROR_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return out
    if not _MIRROR_SYNC_DDL.search(mirror_txt):
        return out
    if routes_txt is None or "/email/poll" not in routes_txt:
        out.findings.append(
            Finding(
                kind=FindingKind.HEURISTIC_SUSPICION,
                message="intake poll route not found — observability check skipped for poll path",
                location=_ROUTES_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return out

    if ingest_txt is None:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="email_ingestion.py missing — poll path absent",
                location=_INGEST_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return out

    if "set_sync_state" not in ingest_txt:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=(
                    "Intake poll path never persists mirror_sync: `poll_ingest_emails` / email_ingestion "
                    "does not call `set_sync_state` while mirror schema defines `mirror_sync` "
                    "(Philosophy #10; see BOOT_FLOW.md §4)"
                ),
                location=_INGEST_REL,
                detail="Wire set_sync_state after successful poll or document exempt in TRUTH + narrow schema claims.",
                checker_id=_CHECKER_ID,
            )
        )

    if (
        "def record_mailbox_action" in mirror_txt
        and not _record_mailbox_called_outside_def(repo)
        and (
            _MAILBOX_ACTION_EXEMPT not in mirror_txt
            or _MAILBOX_ACTION_EXEMPT_HINT not in mirror_txt.lower()
        )
    ):
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=(
                    "mailbox_action audit helper exists but has no production call sites "
                    "(Philosophy #10; PLATFORM_PRIMITIVES / OPEN_QUESTIONS §2)"
                ),
                location=_MIRROR_REL,
                detail="Call record_mailbox_action when implementing mailbox mutations, or document as unwired.",
                checker_id=_CHECKER_ID,
            )
        )

    return out


def run_exploratory(repo: Path) -> CheckerRun:
    return run(repo)
