"""W2 factual execution backflow — the ``execution_context`` block.

One bounded, factual block per ordinary Talk turn: the tasks belonging
to the current conversation (seeds: ``origin_conversation_id`` equals
the conversation, plus tasks reachable by verified references under
the lifecycle addendum §5(c) ownership-safe traversal rule), rendered
in three strictly separated tiers — recorded state by exact status,
computed conditions with their thresholds named, never an
interpretation. No task from another conversation enters the turn
unless explicitly linked. No new model call, no scheduler, no
lifecycle machinery, no decisions-table change.

Authority, in order: rev2 §3.3 and §6 (W2 slice); the lifecycle
addendum §2.7 and §5(c); the W2 design brief (2026-11-06); the
reconciled implementation brief + GPT final gate verdict (2026-11-06,
same file); the founder's six rulings and three binding corrections
therein. Where the reconciled brief and the verdict disagree, THE
VERDICT GOVERNS. Two such conflicts are implemented here, not in the
brief: (a) a traversal read raising an exception gets the
retrieval-incomplete notice, NEVER the partiality footer (verdict
correction 2 — the brief's §7/§8 said footer); (b) the ten-task
selection cap is reconciled with the single ownership-verified
overflow candidate (verdict correction 1 — the brief's §4 "selection
stops at 10" vs §7 "eleventh read").

D3 (open architectural discrepancy, documented — NOT normalized in
W2): five interpretations of "done" live in one tree — rev2 §3.3
exact ``== "Done"`` / ``== "Dropped"``; storage
``_ve_task_status_done`` (regex done|complete|completed|shipped|
closed|won); W1 ``_is_terminal_parent_status`` (that regex OR
normalized "dropped"); obligations ``_CLOSED = {"done", "dropped"}``
(lowered exact match); followthrough ``_is_done`` (regex including
"archived"). W2 renders the stored status verbatim and uses W1's
helper ONLY to suppress outstanding-condition language on terminal
tasks (verdict Q4). It does not pick one rule for the tree.

Prompt-budget finding (verdict §5 gate, verified at 8761278): there
is NO enforced overall character cap on the assembled Talk prompt.
``build_voice_prompt`` appends sections in fixed order with
per-section caps only (``extra_instructions`` [:8000],
``thread_summary`` [:1200], ``context_hint`` [:300], history 10 turns
x [:2000]); ``generate_voice_reply`` passes the joined prompt to the
provider with no truncation; no ``MIN_HEADROOM`` / ``HEADROOM``
constant exists in ``local_ai/``. The 8,000-char figure belongs to
the first-meeting steward-frame records (pre-generated, capped at
generation time), not to Talk assembly. The execution block therefore
cannot silently displace required character instructions or the
``[-10:]`` history window: sections append in fixed order, and the
block is bounded at 2,000 chars by its own whole-block cap. The
8,000-char budget is nevertheless applied as a POLICY threshold in
``reply.build_voice_prompt`` (the block yields — budget notice, then
omission with a log line — rather than displacing required
sections), because the verdict orders the budget mechanism and the
PR #324 lesson is that an uncapped frame truncates silently. The
budget notice fires on prompt length, not on a runtime truncation
that exists nowhere in this path.

The assembler never raises: a failed seed read yields the
retrieval-failure notice; an empty seed set yields no block; a
traversal exception yields the verified records plus the
retrieval-incomplete notice.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixed block text (reconciled brief §2 — fixed copy, not model output.
# Wording changes need a gate decision). "You decided this" appears
# nowhere in this module.
# ---------------------------------------------------------------------------

HEADER = (
    "Execution state — tasks from this conversation. Recorded execution "
    "state and deterministic conditions only. These records may be "
    "incomplete or stale. Do not treat computed conditions as evidence "
    "of motive, commitment, or failure."
)

PARTIALITY_FOOTER = "Execution context is partial; additional tasks were not included."

RETRIEVAL_FAILURE_NOTICE = (
    "Execution records could not be retrieved for this turn. Their absence "
    "from this context does not indicate that no tasks exist."
)

BUDGET_NOTICE = (
    "Execution records were omitted from this turn for length. Their absence "
    "from this context does not indicate that no tasks exist."
)

RETRIEVAL_INCOMPLETE_NOTICE = (
    "Some linked execution records could not be checked. This view may be incomplete."
)

# ---------------------------------------------------------------------------
# Caps (addendum §5(c) + reconciled brief §6)
# ---------------------------------------------------------------------------

_BLOCK_CHAR_CAP = 2000
_MAX_TASKS = 10
_MAX_DEPTH = 3
_MAX_READS = 20
_TITLE_MAX_CHARS = 80
# Policy budget for the assembled Talk prompt (see the module docstring:
# no enforced runtime cap exists on this path; 8,000 is the
# steward-frame budget adopted as the threshold the block yields to).
_VOICE_PROMPT_BUDGET = 8000
_STALL_DAYS = 7

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_FORBIDDEN_WORDS = ("stuck", "avoiding", "losing momentum")


# ---------------------------------------------------------------------------
# Kill switch (verdict ruling 4)
# ---------------------------------------------------------------------------

def execution_context_enabled() -> bool:
    """Single server-side flag omitting the block entirely.

    An explicit ``ZENAF_EXECUTION_CONTEXT`` value wins ("1"/"true"/
    "yes"/"on" = on; anything else = off). Otherwise the default is ON
    in staging and OFF in production. ``ZENAF_PROD=1`` cannot
    discriminate — ``fly.toml`` sets it on the staging app too — so
    the app name is the discriminator: the staging Fly app is
    ``zenaf-staging`` (``FLY_APP_NAME`` is set by Fly at runtime); a
    future production deployment runs under a different app name.
    Local dev (no app name) defaults ON. Flipping is a restart, not
    a code deploy (same procedure as the steward's
    ``ZENAF_WEAVER_STEWARD=0`` rollback). Read per call so tests can
    flip it with ``monkeypatch.setenv``.
    """
    raw = os.environ.get("ZENAF_EXECUTION_CONTEXT")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    app = (os.environ.get("FLY_APP_NAME") or "").strip().lower()
    if app and app != "zenaf-staging":
        return False
    return True


# ---------------------------------------------------------------------------
# Small pure helpers
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


def _parse_dt(raw: Any) -> datetime | None:
    """ISO timestamp to aware datetime; naive reads as UTC. None on garbage."""
    if not raw or not str(raw).strip():
        return None
    try:
        dt = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _date_part(raw: Any) -> str | None:
    """YYYY-MM-DD part of a stored ISO timestamp, or None if not a date."""
    s = str(raw or "").strip()
    if len(s) < 10:
        return None
    return s[:10] if _parse_date(s[:10]) is not None else None


def _safe_line(text: Any) -> str:
    """Collapse ALL whitespace (including newlines) to single spaces.

    Task text is untrusted data even when formatting the prompt: a
    title containing newlines or section markers must not visually
    escape the task-data section. (Same discipline as
    ``obligations._safe_line``.)
    """
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _normalize_title(title: Any) -> str:
    """Display title: whitespace-collapsed, at most 80 chars.

    Verdict ruling 6: deterministic ellipsis when cut; the stored
    title is unchanged. A hostile or very long title cannot make a
    task unrenderable.
    """
    text = _safe_line(title)
    if len(text) > _TITLE_MAX_CHARS:
        return text[: _TITLE_MAX_CHARS - 1] + "…"
    return text


def _seat_display(user_id: str, origin_seat: Any) -> str | None:
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


def _is_terminal(status: Any) -> bool:
    """W1's terminal helper: done-set regex OR normalized "dropped"."""
    from local_ai.vision_execution import storage as _storage

    return bool(_storage._is_terminal_parent_status(status))


def _idle_days(updated_at: Any, now: datetime) -> int | None:
    """Days since last write, via the followthrough computation."""
    from local_ai.followthrough.service import _idle_days as _ft_idle_days

    return _ft_idle_days(updated_at, now)


# ---------------------------------------------------------------------------
# Provenance (verdict correction 3: optional enrichment, never a gate)
# ---------------------------------------------------------------------------

def _provenance_clause(user_id: str, task: dict[str, Any]) -> str:
    """Weakest verified wording, in order. Never raises, never errors.

    Row 1 needs exactly one APPROVED proposal for this task (owner
    scoped, by ``created_task_id``) with a valid decision date —
    ``decided_at`` is set by ``_now()`` in the same UPDATE that flips
    the proposal to 'approved', inside the same transaction that
    creates the task, so it IS the approval instant (verified at
    8761278: ``storage.py:5655``, ``:5733``) — and a resolvable seat.
    Lookup failure, zero rows, or multiple matches degrade to row 2;
    the block is never suppressed for a provenance failure.
    """
    seat = _seat_display(user_id, task.get("origin_seat"))
    has_origin = bool((task.get("origin_conversation_id") or "").strip())
    created_date = _date_part(task.get("created_at"))

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
            decided_date = _date_part(approved[0].get("decided_at"))
            if decided_date and seat:
                return (
                    f"Created from a proposal you approved on {decided_date} "
                    f"in your conversation with {seat}."
                )
    if has_origin and seat and created_date:
        return (
            f"Task created on {created_date}, originating from your "
            f"conversation with {seat}."
        )
    if has_origin and seat:
        return f"Originating from your conversation with {seat}."
    if created_date:
        return f"Task created on {created_date}."
    return ""


# ---------------------------------------------------------------------------
# Record rendering (reconciled brief §3 + §5, as ruled)
# ---------------------------------------------------------------------------

def _render_record(
    user_id: str, task: dict[str, Any], today: date, now: datetime
) -> str:
    """One single-line record. Atomic clauses, included whole or not
    at all; never cut mid-clause. Forbidden words (stuck / avoiding /
    losing momentum) never appear in the block's own language — a
    hostile TITLE may contain them as user data, quoted as the title,
    which is not an interpretation."""
    title = _normalize_title(task.get("title") or "")
    status = str(task.get("status") or "")
    normalized = status.strip().lower()
    terminal = _is_terminal(status)
    tentative = (task.get("timeframe_commitment") or None) == "tentative"

    parts = [f"{title} — Status {status}"]
    if normalized == "dropped":
        parts[0] += " (recorded)"
    elif terminal:
        updated = _date_part(task.get("updated_at"))
        if updated:
            parts[0] += f" (last updated {updated})"
    parts[0] += "."

    if not terminal:
        if tentative:
            # Ruling 3: tentative tasks receive NEITHER idle NOR overdue
            # language. The date renders as a recorded fact only.
            due = _parse_date(task.get("due_date"))
            if due is not None:
                parts.append(f"Due date {due.isoformat()} (tentative).")
        else:
            idle = _idle_days(task.get("updated_at"), now)
            if idle is not None and idle >= _STALL_DAYS:
                parts.append(
                    f"No recorded update in {idle} days (idle beyond the "
                    f"{_STALL_DAYS}-day follow-through threshold)."
                )
            due = _parse_date(task.get("due_date"))
            if due is not None:
                if due < today:
                    parts.append(f"Due date {due.isoformat()} has passed.")
                else:
                    parts.append(f"Due date {due.isoformat()}.")

    provenance = _provenance_clause(user_id, task)
    if provenance:
        parts.append(provenance)
    return _safe_line(" ".join(parts))


# ---------------------------------------------------------------------------
# Selection: bounded breadth-first traversal (verdict correction 1)
# ---------------------------------------------------------------------------

def _edges(task: dict[str, Any]) -> list[str]:
    """Edges in expansion order: parent_task_id, then dependency_ids
    in stored order. Non-string / blank ids are not edges."""
    out: list[str] = []
    parent = task.get("parent_task_id")
    if isinstance(parent, str) and parent.strip():
        out.append(parent.strip())
    deps = task.get("dependency_ids") or []
    if isinstance(deps, list):
        for dep in deps:
            if isinstance(dep, str) and dep.strip():
                out.append(dep.strip())
    return out


def _select(
    user_id: str, seeds: list[dict[str, Any]], seed_overflow: bool
) -> tuple[list[dict[str, Any]], bool, bool, int]:
    """Bounded BFS from the seeds.

    Returns (selected, overflow_verified, incomplete, reads).
    All seeds enter first, in seed order, before any linked record;
    then depth 1 across all seeds, then 2, then 3. A task reachable
    by several paths is counted once, at its minimum depth (BFS level
    order guarantees it). Selection stops at 10 verified tasks; the
    traversal then continues ONLY as far as necessary to verify ONE
    additional eligible owned task, within the total 20-read budget —
    never rendered, never beyond depth 3, never inferred from an
    unreadable edge; it stops immediately once owned overflow is
    established. A read returning None excludes that task and prunes
    its subtree (no footer, no placeholder). A read raising stops
    traversal and marks the block incomplete (never the footer).
    """
    from local_ai.vision_execution import storage as _storage

    selected: list[dict[str, Any]] = list(seeds[:_MAX_TASKS])
    visited = {t.get("id") for t in seeds if t.get("id")}
    overflow = bool(seed_overflow)
    incomplete = False
    reads = 0

    current: list[tuple[dict[str, Any], int]] = [(t, 0) for t in selected]
    while current and not overflow and not incomplete:
        depth = current[0][1] + 1
        if depth > _MAX_DEPTH:
            break
        next_level: list[tuple[dict[str, Any], int]] = []
        for task, _d in current:
            if overflow or incomplete:
                break
            for edge_id in _edges(task):
                if overflow or incomplete:
                    break
                if edge_id in visited:
                    continue
                visited.add(edge_id)
                reads += 1
                if reads > _MAX_READS:
                    # Budget exhausted without establishing overflow.
                    return selected, overflow, incomplete, reads
                try:
                    nxt = _storage.get_task(edge_id, user_id)
                except Exception:
                    # The read path is unreliable; keep verified records.
                    logger.exception(
                        "execution context: traversal read failed; keeping verified records"
                    )
                    incomplete = True
                    break
                if nxt is None:
                    # Foreign / missing / unresolvable: exclude + prune.
                    continue
                if len(selected) >= _MAX_TASKS:
                    # Selection full: this verified owned task IS the
                    # overflow candidate. Never rendered; stop at once.
                    overflow = True
                    break
                selected.append(nxt)
                next_level.append((nxt, depth))
        current = next_level
    return selected, overflow, incomplete, reads


# ---------------------------------------------------------------------------
# Block assembly
# ---------------------------------------------------------------------------

def _fit_records(records: list[str], incomplete: bool) -> list[str]:
    """Fit whole records into the 2,000-char whole-block cap.

    The header is always intact; the footer's length is always
    reserved up front (reconciled brief §6), as is the incomplete
    notice's when an exception occurred. Records are added in
    selection order; the first record that does not fit whole is
    omitted along with everything after it — later shorter records
    never jump ahead. Returns the record lines that fit.
    """
    reserved = len(PARTIALITY_FOOTER) + 1
    if incomplete:
        reserved += len(RETRIEVAL_INCOMPLETE_NOTICE) + 1
    capacity = _BLOCK_CHAR_CAP - len(HEADER) - reserved
    kept: list[str] = []
    used = 0
    for record in records:
        if used + 1 + len(record) <= capacity:
            kept.append(record)
            used += 1 + len(record)
        else:
            break
    return kept


def build_execution_context(
    user_id: str, conversation_id: str, *, today: date | None = None, now: datetime | None = None
) -> tuple[str | None, str]:
    """Build the W2 block for one Talk turn. Never raises.

    Returns (block, status). Status is "ok" (block rendered, possibly
    with footer / incomplete notice), "empty" (no in-scope tasks —
    block None), "failed" (seed query raised — block is the
    retrieval-failure notice), or "incomplete" (a traversal read
    raised — block is the verified records plus the
    retrieval-incomplete notice). ``today`` / ``now`` are test seams
    (live defaults: VE storage-clock UTC date, ``datetime.now(timezone.utc)``).
    """
    from local_ai.vision_execution import obligations as _obligations
    from local_ai.vision_execution import storage as _storage

    if not user_id or not str(user_id).strip():
        return None, "empty"
    today = today or _obligations.storage_clock_today()
    now = now or datetime.now(timezone.utc)

    try:
        seeds = _storage.list_tasks_by_origin_conversation(user_id, conversation_id)
    except Exception:
        logger.exception("execution context: seed query failed; returning failure notice")
        return RETRIEVAL_FAILURE_NOTICE, "failed"
    if not seeds:
        return None, "empty"

    seed_overflow = len(seeds) > _MAX_TASKS
    selected, overflow, incomplete, _reads = _select(user_id, seeds, seed_overflow)

    records: list[str] = []
    render_failed = False
    for task in selected:
        try:
            records.append(_render_record(user_id, task, today, now))
        except Exception:
            # A record that cannot be rendered is dropped; the block
            # reports the uncertainty rather than inventing the line.
            logger.exception("execution context: record render failed; dropping record")
            render_failed = True
    if render_failed:
        incomplete = True

    # Length overflow is established here: a selected owned record
    # dropped by the character cap is a verified omission.
    kept = _fit_records(records, incomplete)
    length_dropped = len(kept) < len(records)
    footer_fired = bool(seed_overflow or overflow or length_dropped)

    lines = [HEADER] + kept
    if incomplete:
        lines.append(RETRIEVAL_INCOMPLETE_NOTICE)
    if footer_fired:
        lines.append(PARTIALITY_FOOTER)
    block = "\n".join(lines)
    assert len(block) <= _BLOCK_CHAR_CAP, "execution block exceeded its cap"
    return block, ("incomplete" if incomplete else "ok")
