"""Shared provenance resolver (W2 + W3) — one hierarchy, one source of strings.

Extracted mechanically from ``local_ai/vision_execution/execution_context.py``
(W3's first commit); no wording change. W2's ``execution_context.py``
re-exports the moved names so its tests keep passing against the same
names. W3's feed render imports ``resolve_origin`` from here.

Authority, in order: the W3 reconciled implementation brief §4 (which
specifies the hierarchy field-by-field) and the W2 reconciled brief +
final gate verdict. The explanation strings live here and nowhere
else — a wording change is one edit here, and it changes both surfaces
at once, which is why the change needs a gate decision (the strings
are fixed copy, as W2's module header states). "You decided this"
appears nowhere in this module's system-authored text.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixed copy (W2 reconciled brief §2 — fixed copy, not model output.
# Wording changes need a gate decision).
# ---------------------------------------------------------------------------

QUOTE_LABEL = "Quote from the original proposal:"
QUOTE_MAX_CHARS = 200

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Small pure helpers (moved verbatim from execution_context.py)
# ---------------------------------------------------------------------------

def _parse_date(value: Any) -> date | None:
    """Strict %Y-%m-%d after strip. Anything else is undated, not an error."""
    s = value.strip() if isinstance(value, str) else ""
    if not _DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _safe_line(text: Any) -> str:
    """Collapse ALL whitespace (including newlines) to single spaces.

    Task text is untrusted data even when formatting the prompt: a
    title containing newlines or section markers must not visually
    escape the task-data section. (Same discipline as
    ``obligations._safe_line``.)
    """
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_title(title: Any) -> str:
    """Display title: whitespace-collapsed, at most 80 chars.

    Verdict ruling 6: deterministic ellipsis when cut; the stored
    title is unchanged. A hostile or very long title cannot make a
    task unrenderable.
    """
    text = _safe_line(title)
    if len(text) > 80:
        return text[:79] + "…"
    return text


def date_part(raw: Any) -> str | None:
    """YYYY-MM-DD part of a stored ISO timestamp, or None if not a date."""
    s = str(raw or "").strip()
    if len(s) < 10:
        return None
    return s[:10] if _parse_date(s[:10]) is not None else None


def seat_display(user_id: str, origin_seat: Any) -> str | None:
    """Resolvable seat display name, or None.

    The same naming authority the prompt builder uses for history
    turns (stock role name, e.g. "Champion", or the visitor's chosen
    name) — never the current seat's name. Unknown seat ids are
    unresolvable. Never raises.
    """
    seat = (origin_seat or "").strip().lower() if isinstance(origin_seat, str) else ""
    if not seat:
        return None
    try:
        from local_ai.council.archetypes import get_archetype
        from local_ai.council.naming import get_display_name

        if get_archetype(seat) is None:
            return None
        return get_display_name(user_id, seat)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Provenance hierarchy (W2, moved verbatim; W3 §4.1 specifies it
# field-by-field)
# ---------------------------------------------------------------------------

def _resolve(user_id: str, task: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str | None]:
    """One lookup, one level determination.

    Returns (clause, matched_proposal_or_None, seat_or_None). The
    matched proposal is set only on row 1 (exactly one QUALIFYING
    approved proposal — ``state == 'approved'`` AND ``decided_at``
    non-null — with a valid decision date and a resolvable seat).
    "Multiple" means multiple QUALIFYING approved proposals, not
    multiple rows total: one approved + one declined proposal is
    exactly one qualifying row — row 1, not a degrade.

    A lookup failure must NEVER become permission to infer a stronger
    origin relationship: an exception sets ``proposals = None``, which
    can only fall through to rows 2–5 on the task's own fields — it
    can never produce row 1, because row 1 requires the lookup to
    have succeeded and returned exactly one qualifying row.
    """
    seat = seat_display(user_id, task.get("origin_seat"))
    has_origin = bool((task.get("origin_conversation_id") or "").strip())
    created_date = date_part(task.get("created_at"))

    proposals: list[dict[str, Any]] | None = None
    try:
        from local_ai.vision_execution import storage as _storage

        proposals = _storage.get_proposals_by_created_task(user_id, task.get("id") or "")
    except Exception:
        # Provenance lookup failure degrades; it never takes the block down.
        logger.exception("execution context: proposal lookup failed; degrading provenance")
        proposals = None

    if proposals:
        approved = [
            p
            for p in proposals
            if (p.get("state") or "") == "approved" and p.get("decided_at")
        ]
        if len(approved) == 1:
            decided_date = date_part(approved[0].get("decided_at"))
            if decided_date and seat:
                return (
                    f"Created from a proposal you approved on {decided_date} "
                    f"in your conversation with {seat}.",
                    approved[0],
                    seat,
                )
    if has_origin and seat and created_date:
        return (
            f"Task created on {created_date}, originating from your "
            f"conversation with {seat}.",
            None,
            seat,
        )
    if has_origin and seat:
        return f"Originating from your conversation with {seat}.", None, seat
    if created_date:
        return f"Task created on {created_date}.", None, seat
    return "", None, seat


def provenance_clause(user_id: str, task: dict[str, Any]) -> str:
    """Weakest verified wording, in order. Never raises, never errors.

    Row 1 needs exactly one APPROVED proposal for this task (owner
    scoped, by ``created_task_id``) with a valid decision date —
    ``decided_at`` is set by ``_now()`` in the same UPDATE that flips
    the proposal to 'approved', inside the same transaction that
    creates the task, so it IS the approval instant — and a resolvable
    seat. Lookup failure, zero rows, or multiple QUALIFYING matches
    degrade to row 2; the block is never suppressed for a provenance
    failure.
    """
    clause, _matched, _seat = _resolve(user_id, task)
    return clause


# ---------------------------------------------------------------------------
# W3 additions (shared module, one truncation rule, one entry point)
# ---------------------------------------------------------------------------

def truncate_quote(text: Any, max_chars: int = QUOTE_MAX_CHARS) -> str:
    """Deterministic quote truncation (W3 §2.8): whitespace-collapse,
    then the first ``max_chars - 1`` characters + "…" when over the
    cap. The same quote always truncates the same way. Truncation is
    by length only — it never treats any phrase as a reason to cut
    or alter text (W3 §4.3, correction 5: a verified quote is
    rendered verbatim apart from this length cut)."""
    collapsed = _safe_line(text)
    if len(collapsed) > max_chars:
        return collapsed[: max_chars - 1] + "…"
    return collapsed


def resolve_origin(user_id: str, task: dict[str, Any]) -> dict[str, Any] | None:
    """W3 entry point: the six-field ``origin`` object, or None.

    Present ONLY when the task carries deliberation provenance
    (non-null ``origin_conversation_id`` and a resolvable seat or
    date — W3 §4.3). A legacy/manual task carries no origin at all.
    The quote is present only when the hierarchy's row 1 matched
    (exactly one QUALIFYING approved proposal with a valid decision
    date): the quote is that proposal's ``evidence_quote``,
    truncated to 200 chars. On rows 2–5 the quote is ABSENT — no
    approved proposal means no proposal quote, and no quote is ever
    inferred from the task's ``original_*`` snapshot or any other
    task field (U-D7 RULED). ``proposal_id`` is the matched proposal
    row's id — the decision reference, never a decisions-table id.
    The kill switch is NOT checked here: the render path gates the
    call (W3 §3 step 5d), so this stays a pure function of
    (user_id, task).
    """
    has_origin = bool((task.get("origin_conversation_id") or "").strip())
    if not has_origin:
        return None
    clause, matched, seat = _resolve(user_id, task)
    if not clause:
        return None
    quote: str | None = None
    proposal_id: str | None = None
    if matched is not None:
        quote = truncate_quote(matched.get("evidence_quote") or "")
        proposal_id = matched.get("id")
    return {
        "seat": seat,
        "conversation_id": task.get("origin_conversation_id"),
        "quote": quote,
        "quote_label": QUOTE_LABEL,
        "proposal_id": proposal_id,
        "explanation": clause,
    }
