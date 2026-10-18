"""Follow-through engine: watchers, nudge computation, commitments, growth.

Computation is on-demand and idempotent: ``compute_nudges`` derives candidates
from current state, persists only genuinely new nudges (nudge-once dedup), and
auto-resolves nudges whose condition cleared. No scheduler in v1.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from local_ai.followthrough import growth as G
from local_ai.followthrough.store import FollowthroughStore

# Mirrors local_ai.vision_execution.storage._VE_TASK_DONE_STATUS_RE (private there;
# duplicated here so the engine doesn't depend on a private name).
_DONE_RE = re.compile(r"\b(done|complete|completed|shipped|closed|won|archived)\b",
                      re.IGNORECASE)

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


def _is_done(status: str | None) -> bool:
    if not status or not str(status).strip():
        return False
    return bool(_DONE_RE.search(str(status)))


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
        return the live feed ordered must → should → could (then oldest first)."""
        now = datetime.now(timezone.utc)
        candidates = []
        candidates.extend(self._date_candidates(user_id, now))
        candidates.extend(self._stalled_candidates(user_id, now))
        candidates.extend(self._commitment_candidates(user_id))

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
        return [self._public_nudge(n) for n in feed]

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
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        today = now.date()
        for task in self.ve.list_tasks(user_id) or []:
            if _is_done(task.get("status")):
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
                    "why_text": (
                        f"Overdue by {_human_days(-delta)}: “{title}” "
                        f"was due {due.isoformat()}."
                    ),
                    "entity_title": title, "suggested_seat": "Conductor",
                })
            elif delta <= G.APPROACH_DAYS:
                when = "today" if delta == 0 else f"in {delta} days" if delta > 1 else "tomorrow"
                out.append({
                    "kind": KIND_DATE_APPROACHING, "entity_type": "task",
                    "entity_id": task["id"], "severity": "should",
                    "why_text": f"“{title}” is due {when} ({due.isoformat()}).",
                    "entity_title": title, "suggested_seat": "Conductor",
                })
        return out

    def _stalled_candidates(
        self, user_id: str, now: datetime
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        growth = self.store.growth_user_ids(user_id)
        entities: list[tuple[str, dict[str, Any]]] = [
            ("task", t) for t in (self.ve.list_tasks(user_id) or [])
        ] + [
            ("project", p) for p in (self.ve.list_projects(user_id) or [])
        ]
        for entity_type, e in entities:
            if _is_done(e.get("status")):
                continue
            title = e.get("title") or f"Untitled {entity_type}"
            g = growth.get((entity_type, e["id"]))
            if g is not None:
                # Growth-state entities speak growth, not staleness: only the
                # gentle growth-stall nudge applies.
                stalled_for = _idle_days(g.get("transitioned_at"), now)
                if stalled_for is not None and stalled_for >= G.GROWTH_STALL_DAYS:
                    out.append({
                        "kind": KIND_GROWTH_STALL, "entity_type": entity_type,
                        "entity_id": e["id"], "severity": "could",
                        "why_text": (
                            f"“{title}” is still a {g['state']} after "
                            f"{_human_days(stalled_for)} — water it, or let it rest?"
                        ),
                        "entity_title": title, "suggested_seat": "Gardener",
                    })
                continue
            idle = _idle_days(e.get("updated_at"), now)
            if idle is not None and idle >= G.STALL_DAYS:
                out.append({
                    "kind": KIND_STALLED, "entity_type": entity_type,
                    "entity_id": e["id"], "severity": "should",
                    "why_text": (
                        f"No movement in {_human_days(idle)} on “{title}” — "
                        f"last touched {(e.get('updated_at') or '')[:10] or 'unknown'}."
                    ),
                    "entity_title": title, "suggested_seat": "Guardian",
                })
        return out

    def _commitment_candidates(self, user_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for c in self.store.list_commitments(user_id, status="open"):
            linked = c.get("linked_task_id")
            if linked:
                task = self.ve.get_task(linked, user_id)
                if task is not None and _is_done(task.get("status")):
                    # The promise is fulfilled — close the commitment quietly.
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
