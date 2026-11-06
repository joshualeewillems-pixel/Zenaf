"""Follow-through engine: watchers, nudge computation, commitments, growth.

Computation is on-demand and idempotent: ``compute_nudges`` derives candidates
from current state, persists only genuinely new nudges (nudge-once dedup), and
auto-resolves nudges whose condition cleared. No scheduler in v1.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any

from local_ai.followthrough import growth as G
from local_ai.followthrough.store import FollowthroughStore
from local_ai.vision_execution.provenance import resolve_origin

logger = logging.getLogger(__name__)

# W3 §5.1: the status allowlists (nudge-scoped). One place, next to
# where _is_done used to live; the candidate builders and the
# render-time kind validation (§6.3) call the same predicates — the
# same predicate, not two copies. Matching:
# str(status or "").strip().lower() against the sets.
# The regex "done" interpretation (_DONE_RE / _is_done, which also
# matched completed/closed/archived/shipped/won) is RETIRED for
# nudges: it silently suppressed tasks whose status meaning was
# unknown. TASKS ONLY for the task sets:
_TASK_OPEN_STATUSES = {"todo", "in progress", "blocked"}
_TASK_TERMINAL_STATUSES = {"done", "dropped"}
# U-D10 RULED (founder, 2026-11-06): the project allowlist is a
# SEPARATE predicate with its own sets — projects do not share the
# task status vocabulary (Draft is the default; only Blocked
# normalizes into the task set). Applying the task allowlist to
# projects would silently suppress every Draft and Active project
# nudge.
_PROJECT_OPEN_STATUSES = {"draft", "evaluating", "ready", "active", "blocked"}
_PROJECT_TERMINAL_STATUSES = {"complete", "killed"}


def _normalize_status(status: str | None) -> str:
    return str(status or "").strip().lower()


def _task_status_class(status: str | None) -> str:
    """W3 §5.1: 'open' | 'terminal' | 'unknown' for a TASK status."""
    n = _normalize_status(status)
    if n in _TASK_OPEN_STATUSES:
        return "open"
    if n in _TASK_TERMINAL_STATUSES:
        return "terminal"
    return "unknown"


def _project_status_class(status: str | None) -> str:
    """W3 §5.1 + U-D10: 'open' | 'terminal' | 'unknown' for a PROJECT status."""
    n = _normalize_status(status)
    if n in _PROJECT_OPEN_STATUSES:
        return "open"
    if n in _PROJECT_TERMINAL_STATUSES:
        return "terminal"
    return "unknown"


def _is_tentative(timeframe_commitment: str | None) -> bool:
    """A tentative timeframe is a timeframe dimension, not a status —
    and a tentative date never generates a deadline nudge (§2.5)."""
    return _normalize_status(timeframe_commitment) == "tentative"


def w3_provenance_enabled() -> bool:
    """W3 §2.9 kill switch: gates provenance PRESENTATION only.

    Mirrors W2's ``execution_context_enabled``: an explicit
    ``ZENAF_W3_PROVENANCE`` value wins ("1"/"true"/"yes"/"on" = on;
    anything else = off). Otherwise the default is ON in staging and
    OFF in production, discriminated by ``FLY_APP_NAME``
    (``zenaf-staging``) — ``ZENAF_PROD=1`` cannot discriminate
    because ``fly.toml`` sets it on staging too. Local dev (no app
    name) defaults ON. Flipping is a restart, not a code deploy.
    Read per call so tests can flip it with ``monkeypatch.setenv``.
    Correctness fixes stay active regardless of the switch.
    """
    raw = os.environ.get("ZENAF_W3_PROVENANCE")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    app = (os.environ.get("FLY_APP_NAME") or "").strip().lower()
    if app and app != "zenaf-staging":
        return False
    return True

# Nudge kinds (stable — the today-aggregate consumes these).
KIND_DATE_OVERDUE = "date_overdue"
KIND_DATE_APPROACHING = "date_approaching"
KIND_STALLED = "stalled"
KIND_GROWTH_STALL = "growth_stall"
KIND_COMMITMENT_OPEN = "commitment_open"


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    try:
        dt = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_day(raw: str | None) -> date | None:
    dt = _parse_dt(raw)
    return dt.date() if dt else None


def _idle_days(updated_at: str | None, now: datetime) -> int | None:
    dt = _parse_dt(updated_at)
    if dt is None:
        return None
    return max(0, (now - dt).days)


def _human_days(n: int) -> str:
    if n <= 0:
        return "less than a day"
    if n == 1:
        return "1 day"
    if n < 14:
        return f"{n} days"
    weeks = n // 7
    return f"{weeks} week" if weeks == 1 else f"{weeks} weeks"


def _kind_applies(kind: str, entity_type: str, status: str | None) -> bool:
    """W3 §6.3 (status leg): does the stored kind still apply to the
    CURRENT entity state? The candidate builders use the same
    allowlist predicates — one predicate, not two copies.
    Commitments are validated separately (§8.1: existence + open +
    unlinked), not by status, so no kind returns True for them here.
    """
    if kind in (KIND_DATE_OVERDUE, KIND_DATE_APPROACHING):
        return entity_type == "task" and _task_status_class(status) == "open"
    if kind in (KIND_STALLED, KIND_GROWTH_STALL):
        if entity_type == "task":
            return _task_status_class(status) == "open"
        if entity_type == "project":
            return _project_status_class(status) == "open"
        return False
    return False


# -- shared condition wording (§6.2 exact copy, fixed) -----------------------
# The candidate builders AND the render-time recompute call these —
# one wording function per kind, so the stored why_text and the
# rendered why can never drift apart.

def _overdue_line(title: str, delta_days: int, due_iso: str) -> str:
    """The existing shape is kept — already honest; only the delta
    was stale. The colon became an em dash (§6.2)."""
    return f"Overdue by {_human_days(delta_days)} — “{title}” was due {due_iso}."


def _approaching_line(title: str, delta_days: int, due_iso: str) -> str:
    if delta_days == 0:
        when = "today"
    elif delta_days == 1:
        when = "tomorrow"
    else:
        when = f"in {delta_days} days"
    return f"“{title}” is due {when} ({due_iso})."


def _stalled_line(title: str, idle_days: int) -> str:
    """The W2 honest wording (D3 fix). The idle count is the raw day
    count, always 'days' (idle is >= 7 here)."""
    return (
        f"No recorded update in {idle_days} days "
        f"(idle beyond the 7-day follow-through threshold) — “{title}”."
    )


def _growth_stall_line(title: str, state: str, stalled_for: int) -> str:
    """The metaphor wording is kept (brief D3, carried)."""
    return (
        f"“{title}” is still a {state} after "
        f"{_human_days(stalled_for)} — water it, or let it rest?"
    )


class FollowthroughService:
    """The engine. ``ve`` is the VE service module (injectable for tests)."""

    def __init__(self, store: FollowthroughStore | None = None, ve: Any = None) -> None:
        self.store = store or FollowthroughStore()
        if ve is None:
            from local_ai.vision_execution import service as ve_service
            ve = ve_service
        self.ve = ve

    # -- public API -----------------------------------------------------------
    def compute_nudges(self, user_id: str) -> list[dict[str, Any]]:
        """Run watchers, persist genuinely new nudges, auto-resolve cleared ones,
        return the live feed ordered must → should → could (then oldest first).
        The return path re-reads each live row's entity and recomputes the
        condition wording from current state (W3 §3 step 5) — the feed is
        never the stored text verbatim.

        GET is not entirely read-only (W3 §2.1, U-D1 RULED): the create
        step above persists genuinely new nudges and the auto-resolve
        step resolves cleared ones. The RENDER step (_render_rows)
        performs no writes.
        """
        now = datetime.now(timezone.utc)
        candidates = []
        unknown_task_ids: set[str] = set()
        unknown_project_ids: set[str] = set()
        date_cands, date_unknown = self._date_candidates(user_id, now)
        candidates.extend(date_cands)
        unknown_task_ids |= date_unknown
        stalled_cands, stalled_task_unknown, stalled_project_unknown = (
            self._stalled_candidates(user_id, now)
        )
        candidates.extend(stalled_cands)
        unknown_task_ids |= stalled_task_unknown
        unknown_project_ids |= stalled_project_unknown
        candidates.extend(self._commitment_candidates(user_id))

        # W3 §5.3 diagnostic: task and project unknown counts separately;
        # counts only, server logs only — never in the feed, never in the
        # briefing response. Logged only when either count is nonzero.
        if unknown_task_ids or unknown_project_ids:
            logger.info(
                "nudge_status_unknown task_count=%d project_count=%d",
                len(unknown_task_ids), len(unknown_project_ids),
            )

        wanted = {(c["kind"], c["entity_type"], c["entity_id"]) for c in candidates}

        for c in candidates:
            if self.store.active_nudge(user_id, c["kind"], c["entity_type"],
                                       c["entity_id"]):
                continue  # already surfaced and live — nudge once
            if self.store.recently_acked(user_id, c["kind"], c["entity_type"],
                                         c["entity_id"], G.RE_NUDGE_COOLDOWN_DAYS):
                continue  # acked recently — stay quiet
            if self.store.snoozed(user_id, c["kind"], c["entity_type"],
                                  c["entity_id"]):
                continue  # snoozed — stay quiet
            nudge = self.store.create_nudge(user_id, **c)
            self.store.log_event(user_id, "nudge_created", nudge_id=nudge["id"],
                                 detail=f"{c['kind']}:{c['entity_type']}:{c['entity_id']}")

        # Auto-resolve live nudges whose condition no longer holds.
        for (kind, etype, eid) in self.store.list_active_keys(user_id) - wanted:
            nudge = self.store.active_nudge(user_id, kind, etype, eid)
            if nudge:
                self.store.resolve_nudge(nudge["id"], user_id)
                self.store.log_event(user_id, "nudge_resolved",
                                     nudge_id=nudge["id"],
                                     detail=f"{kind}:{etype}:{eid}")

        feed = self.store.list_feed_nudges(user_id)
        feed.sort(key=lambda n: (G.SEVERITY_ORDER.get(n["severity"], 9),
                                 n["created_at"]))
        return self._render_rows(user_id, feed, now)

    # -- render-time recompute + validation (W3 §3 step 5, §6, §8.1) --------
    def _render_rows(
        self, user_id: str, feed: list[dict[str, Any]], now: datetime
    ) -> list[dict[str, Any]]:
        """Render the live feed (W3 §3 step 5). Pure: no writes.

        For each live nudge row, in order:
          a. Re-read the entity via the authority-aware getter
             (owner-scoped; for commitment_open, the store's own
             `get_commitment`). None → EXCLUDE. A raise propagates
             (500), never a silent exclusion and never a silent False.
          b. Validate the stored kind still applies (§6.3) against
             the CURRENT entity state. Fails → EXCLUDE.
          c. Recompute the condition wording (§6.2) from the current
             row. The stored why_text is never updated.
          d/e. Resolve origin for task kinds (shared resolver, §4);
             truncate the quote to 200 chars (§2.8). Skipped entirely
             when the kill switch is OFF.
          f. Set the public suggested_seat (§7): null when the TASK
             carries stored origin columns (whether the switch is ON
             or OFF); the stored kind hint otherwise.
        The order of the feed is preserved (severity → created_at,
        step 5g — the sort happened before this call).
        """
        out: list[dict[str, Any]] = []
        provenance_on = w3_provenance_enabled()
        for n in feed:
            kind = n["kind"]
            entity_type = n["entity_type"]
            entity_id = n["entity_id"]
            if entity_type == "commitment":
                # §6.3 (corrected): existence + open + unlinked, read
                # through the authoritative getter at render time.
                c = self.store.get_commitment(entity_id, user_id)
                if (
                    c is None
                    or c.get("status") != "open"
                    or c.get("linked_task_id")
                ):
                    continue
                out.append(self._public_nudge(n))
                continue
            getter = (
                self.ve.get_task if entity_type == "task"
                else self.ve.get_project
            )
            entity = getter(entity_id, user_id)
            if entity is None:
                continue
            if not _kind_applies(kind, entity_type, entity.get("status")):
                continue
            why = self._recomputed_why(user_id, kind, entity, entity_type, now)
            if why is None:
                continue
            row = self._public_nudge(n)
            row["why"] = why
            row["entity_title"] = entity.get("title") or n.get("entity_title", "")
            carries_origin = bool(
                entity_type == "task"
                and (entity.get("origin_conversation_id") or "").strip()
            )
            if carries_origin and provenance_on:
                # §4.3: the origin key is present ONLY when the task
                # carries deliberation provenance (a resolvable seat
                # or date — resolve_origin returns None otherwise)
                # AND the switch is ON. A legacy/manual task carries
                # no origin key at all.
                origin = resolve_origin(user_id, entity)
                if origin is not None:
                    row["origin"] = origin
            # §7 / step 5f: a task carrying stored origin columns
            # renders with a null public seat in BOTH switch states —
            # OFF does not revert it to the kind hint. A legacy/manual
            # task (no origin columns) keeps the kind hint.
            if carries_origin:
                row["suggested_seat"] = None
            out.append(row)
        return out

    def _recomputed_why(
        self, user_id: str, kind: str, entity: dict[str, Any],
        entity_type: str, now: datetime,
    ) -> str | None:
        """§6.2 recompute + §6.3 full condition validation, from the
        current row. Returns None when the kind's condition no longer
        holds — the caller excludes the card. An unrecognized kind has
        no validation rule, so it is excluded (fail-closed)."""
        title = entity.get("title") or f"Untitled {entity_type}"
        if kind in (KIND_DATE_OVERDUE, KIND_DATE_APPROACHING):
            if _is_tentative(entity.get("timeframe_commitment")):
                return None
            due = _parse_day(entity.get("due_date"))
            if due is None:
                return None
            delta = (due - now.date()).days
            if kind == KIND_DATE_OVERDUE:
                if delta >= 0:
                    return None
                return _overdue_line(title, -delta, due.isoformat())
            if delta < 0 or delta > G.APPROACH_DAYS:
                return None
            return _approaching_line(title, delta, due.isoformat())
        if kind == KIND_STALLED:
            # Growth-state entities speak growth, not staleness (§6.3).
            if self.store.get_growth(entity_type, entity["id"], user_id) is not None:
                return None
            idle = _idle_days(entity.get("updated_at"), now)
            if idle is None or idle < G.STALL_DAYS:
                return None
            return _stalled_line(title, idle)
        if kind == KIND_GROWTH_STALL:
            g = self.store.get_growth(entity_type, entity["id"], user_id)
            if g is None:
                return None
            stalled_for = _idle_days(g.get("transitioned_at"), now)
            if stalled_for is None or stalled_for < G.GROWTH_STALL_DAYS:
                return None
            return _growth_stall_line(title, g["state"], stalled_for)
        return None

    def ack_nudge(self, user_id: str, nudge_id: str) -> dict[str, Any]:
        nudge = self.store.ack_nudge(nudge_id, user_id)
        if nudge is None:
            raise KeyError(nudge_id)
        return self._public_nudge(nudge)

    def snooze_nudge(
        self, user_id: str, nudge_id: str, until_iso: str
    ) -> dict[str, Any]:
        until = _parse_dt(until_iso)
        if until is None:
            raise ValueError(f"cannot parse snooze time {until_iso!r}")
        if until <= datetime.now(timezone.utc):
            raise ValueError("snooze time must be in the future")
        nudge = self.store.snooze_nudge(nudge_id, user_id, until.isoformat())
        if nudge is None:
            raise KeyError(nudge_id)
        return self._public_nudge(nudge)

    # -- commitments ----------------------------------------------------------
    def create_commitment(
        self, user_id: str, text: str, source_quote: str | None = None
    ) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("commitment text is required")
        return self.store.create_commitment(user_id, text, source_quote)

    def list_commitments(
        self, user_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        return self.store.list_commitments(user_id, status)

    def list_commitments_for_task(
        self, user_id: str, task_id: str, status: str | None = "open"
    ) -> list[dict[str, Any]]:
        """Commitments directly linked to one task (S3). Passthrough to
        the store read of the same name; ``user_id`` required."""
        return self.store.list_commitments_for_task(user_id, task_id, status)

    def link_commitment(
        self, user_id: str, commitment_id: str, task_id: str
    ) -> dict[str, Any]:
        task = self.ve.get_task(task_id, user_id)
        if task is None:
            # Distinguish "someone else's" from "doesn't exist".
            if self.ve.get_task(task_id) is not None:
                raise PermissionError(task_id)
            raise KeyError(task_id)
        out = self.store.link_commitment(commitment_id, user_id, task_id)
        if out is None:
            raise KeyError(commitment_id)
        return out

    def set_commitment_status(
        self, user_id: str, commitment_id: str, status: str
    ) -> dict[str, Any]:
        out = self.store.set_commitment_status(commitment_id, user_id, status)
        if out is None:
            raise KeyError(commitment_id)
        return out

    # -- growth states --------------------------------------------------------
    def set_growth_state(
        self, user_id: str, entity_type: str, entity_id: str, state: str | None
    ) -> dict[str, Any]:
        if entity_type not in G.GROWTH_ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of {list(G.GROWTH_ENTITY_TYPES)}")
        self._require_owned_entity(user_id, entity_type, entity_id)
        current_row = self.store.get_growth(entity_type, entity_id, user_id)
        current = current_row["state"] if current_row else None
        G.check_transition(current, state)
        if state is None:
            self.store.clear_growth(entity_type, entity_id, user_id)
            self.store.log_event(user_id, "growth_cleared",
                                 detail=f"{entity_type}:{entity_id}")
            return {"entity_type": entity_type, "entity_id": entity_id, "state": None}
        row = self.store.set_growth(entity_type, entity_id, user_id, state)
        self.store.log_event(user_id, "growth_transition",
                             detail=f"{entity_type}:{entity_id}:{current}->{state}")
        return {"entity_type": entity_type, "entity_id": entity_id,
                "state": row["state"], "transitioned_at": row["transitioned_at"]}

    def get_growth_state(
        self, user_id: str, entity_type: str, entity_id: str
    ) -> dict[str, Any]:
        if entity_type not in G.GROWTH_ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of {list(G.GROWTH_ENTITY_TYPES)}")
        self._require_owned_entity(user_id, entity_type, entity_id)
        row = self.store.get_growth(entity_type, entity_id, user_id)
        return {"entity_type": entity_type, "entity_id": entity_id,
                "state": row["state"] if row else None,
                "transitioned_at": row["transitioned_at"] if row else None}

    def _require_owned_entity(
        self, user_id: str, entity_type: str, entity_id: str
    ) -> dict[str, Any]:
        getter = self.ve.get_task if entity_type == "task" else self.ve.get_project
        entity = getter(entity_id, user_id)
        if entity is None:
            if getter(entity_id) is not None:
                raise PermissionError(entity_id)
            raise KeyError(entity_id)
        return entity

    # -- watchers -------------------------------------------------------------
    def _date_candidates(
        self, user_id: str, now: datetime
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """Deadline candidates (W3 §3 step 1, §5.2): TASKS ONLY, status
        in the task OPEN set, due date parses, NOT tentative.
        Unknown-status tasks generate no candidate and are counted
        (returned ids)."""
        out: list[dict[str, Any]] = []
        unknown_task_ids: set[str] = set()
        today = now.date()
        for task in self.ve.list_tasks(user_id) or []:
            status_class = _task_status_class(task.get("status"))
            if status_class != "open":
                if status_class == "unknown":
                    unknown_task_ids.add(task["id"])
                continue
            if _is_tentative(task.get("timeframe_commitment")):
                continue
            due = _parse_day(task.get("due_date"))
            if due is None:
                continue  # dates are optional — no date, no date nudge
            title = task.get("title") or "Untitled task"
            delta = (due - today).days
            if delta < 0:
                out.append({
                    "kind": KIND_DATE_OVERDUE, "entity_type": "task",
                    "entity_id": task["id"], "severity": "must",
                    "why_text": _overdue_line(title, -delta, due.isoformat()),
                    "entity_title": title, "suggested_seat": "Conductor",
                })
            elif delta <= G.APPROACH_DAYS:
                out.append({
                    "kind": KIND_DATE_APPROACHING, "entity_type": "task",
                    "entity_id": task["id"], "severity": "should",
                    "why_text": _approaching_line(title, delta, due.isoformat()),
                    "entity_title": title, "suggested_seat": "Conductor",
                })
        return out, unknown_task_ids

    def _stalled_candidates(
        self, user_id: str, now: datetime
    ) -> tuple[list[dict[str, Any]], set[str], set[str]]:
        """Stall candidates (W3 §3 step 1, §5.2, §6.3): tasks under the
        task allowlist, projects under the U-D10 project allowlist.
        Unknown-status entities generate no candidate and are counted
        (returned ids, per entity type). Growth-state entities speak
        growth, not staleness: only the gentle growth-stall nudge
        applies."""
        out: list[dict[str, Any]] = []
        unknown_task_ids: set[str] = set()
        unknown_project_ids: set[str] = set()
        growth = self.store.growth_user_ids(user_id)
        entities: list[tuple[str, dict[str, Any]]] = [
            ("task", t) for t in (self.ve.list_tasks(user_id) or [])
        ] + [
            ("project", p) for p in (self.ve.list_projects(user_id) or [])
        ]
        for entity_type, e in entities:
            if entity_type == "task":
                status_class = _task_status_class(e.get("status"))
            else:
                status_class = _project_status_class(e.get("status"))
            if status_class != "open":
                if status_class == "unknown":
                    if entity_type == "task":
                        unknown_task_ids.add(e["id"])
                    else:
                        unknown_project_ids.add(e["id"])
                continue
            title = e.get("title") or f"Untitled {entity_type}"
            g = growth.get((entity_type, e["id"]))
            if g is not None:
                stalled_for = _idle_days(g.get("transitioned_at"), now)
                if stalled_for is not None and stalled_for >= G.GROWTH_STALL_DAYS:
                    out.append({
                        "kind": KIND_GROWTH_STALL, "entity_type": entity_type,
                        "entity_id": e["id"], "severity": "could",
                        "why_text": _growth_stall_line(
                            title, g["state"], stalled_for),
                        "entity_title": title, "suggested_seat": "Gardener",
                    })
                continue
            idle = _idle_days(e.get("updated_at"), now)
            if idle is not None and idle >= G.STALL_DAYS:
                out.append({
                    "kind": KIND_STALLED, "entity_type": entity_type,
                    "entity_id": e["id"], "severity": "should",
                    "why_text": _stalled_line(title, idle),
                    "entity_title": title, "suggested_seat": "Guardian",
                })
        return out, unknown_task_ids, unknown_project_ids

    def _commitment_candidates(self, user_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for c in self.store.list_commitments(user_id, status="open"):
            linked = c.get("linked_task_id")
            if linked:
                task = self.ve.get_task(linked, user_id)
                # W3 §5.2: the promise is fulfilled when the linked task
                # reaches a TASK-terminal state (Done/Dropped). An
                # unknown-status task is NOT terminal — its meaning is
                # unknown, so the commitment is left open, not
                # auto-closed on that basis alone.
                if task is not None and _task_status_class(
                    task.get("status")
                ) == "terminal":
                    self.store.set_commitment_status(c["id"], user_id, "done")
                    self.store.log_event(user_id, "commitment_fulfilled",
                                         detail=c["id"])
                continue
            out.append({
                "kind": KIND_COMMITMENT_OPEN, "entity_type": "commitment",
                "entity_id": c["id"], "severity": "should",
                "why_text": (
                    f"You said you’d do this — “{c['text']}” — "
                    f"but it isn’t a task yet. Make it one?"
                ),
                "entity_title": c["text"][:80], "suggested_seat": "Guardian",
            })
        return out

    # -- response shaping (stable contract for the today-aggregate) ------------
    @staticmethod
    def _public_nudge(n: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": n["id"],
            "kind": n["kind"],
            "entity_type": n["entity_type"],
            "entity_id": n["entity_id"],
            "entity_title": n.get("entity_title", ""),
            "severity": n["severity"],
            "why": n.get("why_text", ""),
            "suggested_seat": n.get("suggested_seat"),
            "created_at": n["created_at"],
        }
