"""Today aggregate: the ranked morning briefing.

Consumes the follow-through engine's nudge feed server-side (same process,
no HTTP loop) and applies the decided ranking policy (2026-10-18):

- must-see = cost-of-waiting, not importance
- tiers: must / should / could
- within-tier sort: the context envelope (Stakes x Reversibility x Time
  pressure); the envelope is derived conservatively from what the engine
  feed honestly carries, unknown elsewhere (never guessed)
- "someone waiting on you" outranks "due today"
- deck, not list: 3 cards + an opaque cursor (the "next" button)
- mode discovery is bottom-up and session-stateless: the client sends
  dismissed_ids / engaged_id / mode on each request; the server re-ranks
  from that alone. No server-side briefing session in v1.

ADHD rule (load-bearing): this API returns no counts, no totals, no badges.
The client must not render red dots off this feed.

Integration points (documented, not built in v1):
- open persona / unlock threads ("the seat wants to talk" — unlock
  mechanic not built yet)
- review-queue aging (unconfirmed proposals have no server-side home yet)
- per-seat live tensions (not built yet)
- the council's "stance" line for the day (heuristic or later)
- the "closing windows" must-tier member (no engine kind emits it yet)
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Any

#: Cards per deck page (the "next" button pages the rest).
DECK_SIZE = 3

TIER_MUST = "must"
TIER_SHOULD = "should"
TIER_COULD = "could"
TIER_ORDER = {TIER_MUST: 0, TIER_SHOULD: 1, TIER_COULD: 2}

#: Engine nudge kind -> base briefing tier. date_approaching is upgraded to
#: must when the due date is today (checked against the entity, not parsed
#: out of the why-text).
KIND_TIER = {
    "date_overdue": TIER_MUST,
    "date_approaching": TIER_SHOULD,
    "stalled": TIER_SHOULD,
    "commitment_open": TIER_SHOULD,
    "growth_stall": TIER_COULD,
}

#: Exactly one pre-chewed next action per nudge kind. The briefing minimizes
#: decisions, not just items.
NEXT_ACTIONS: dict[str, tuple[str, str]] = {
    "date_overdue": ("done", "Mark done"),
    "date_approaching": ("open", "Open it"),
    "stalled": ("open", "Open it"),
    "commitment_open": ("make_task", "Make it a task"),
    "growth_stall": ("snooze", "Let it rest"),
}

#: Envelope level -> sort weight. Unknown is neutral (ties the lowest known
#: level): honest gaps neither boost nor sink an item.
_LEVEL_SCORE = {
    "stakes": {"life-altering": 3, "significant": 2, "low": 1, "unknown": 1},
    "reversibility": {"irreversible": 3, "costly": 2, "easily": 1, "unknown": 1},
    "time_pressure": {"urgent": 3, "deliberative": 2, "open-ended": 1, "unknown": 1},
}


def envelope_score(stakes: str, reversibility: str, time_pressure: str) -> int:
    """Within-tier sort weight from the context envelope.

    Only the three decided dimensions participate (Stakes x Reversibility x
    Time pressure). Unknown levels are neutral, never penalized.
    """
    s = _LEVEL_SCORE["stakes"].get(stakes, 1)
    r = _LEVEL_SCORE["reversibility"].get(reversibility, 1)
    t = _LEVEL_SCORE["time_pressure"].get(time_pressure, 1)
    return s + r + t


def _encode_cursor(offset: int) -> str:
    raw = json.dumps({"o": offset}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(raw: str | None) -> int:
    if not raw:
        return 0
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        offset = int(data.get("o", 0))
        return max(0, offset)
    except (ValueError, binascii.Error, AttributeError, KeyError):
        return 0  # forgiving: a bad cursor restarts the deck


def _parse_day(raw: str | None):
    if not raw or not str(raw).strip():
        return None
    try:
        dt = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        return None
    return dt.date()


class TodayService:
    """The briefing. ``ft`` is the follow-through service, ``ve`` the VE
    service module — both injectable for tests."""

    def __init__(self, ft: Any = None, ve: Any = None) -> None:
        if ft is None:
            from local_ai.followthrough.service import FollowthroughService
            from local_ai.followthrough.store import FollowthroughStore
            ft = FollowthroughService(FollowthroughStore())
        self.ft = ft
        if ve is None:
            from local_ai.vision_execution import service as ve_service
            ve = ve_service
        self.ve = ve

    # -- public API -----------------------------------------------------------
    def briefing(
        self,
        user_id: str,
        cursor: str | None = None,
        dismissed_ids: tuple[str, ...] | list[str] = (),
        engaged_id: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Rank the engine feed into a 3-card deck.

        Session-stateless: every interaction signal (dismissed_ids,
        engaged_id, mode) arrives on the request. A dismissed id is out of
        *this* briefing only ("not now"); the dismissal *pattern* down-weights
        that seat live ("not my mode").
        """
        feed = self.ft.compute_nudges(user_id) or []
        by_id = {n["id"]: n for n in feed if n.get("id")}

        dismissed = {d for d in (dismissed_ids or ()) if d}
        if engaged_id in dismissed:
            dismissed.discard(engaged_id)  # engaged wins a contradiction

        enriched = []
        for n in feed:
            if n["id"] in dismissed:
                continue
            enriched.append(self._enrich(user_id, n))

        # Dismissal pattern -> live seat down-weighting ("not my mode").
        seat_dismissals: dict[str, int] = {}
        for did in dismissed:
            n = by_id.get(did)
            seat = (n or {}).get("suggested_seat")
            if seat:
                seat_dismissals[seat] = seat_dismissals.get(seat, 0) + 1

        engaged = by_id.get(engaged_id) if engaged_id else None
        suggested_mode = (engaged or {}).get("suggested_seat")
        mode_norm = (mode or "").strip().lower() or None

        def sort_key(e: dict[str, Any]):
            n = e["nudge"]
            seat = n.get("suggested_seat") or ""
            return (
                TIER_ORDER[e["tier"]],
                -int(e["people_waiting"]),
                -int(bool(mode_norm) and seat.strip().lower() == mode_norm),
                seat_dismissals.get(seat, 0),
                -e["envelope_score"],
                n.get("created_at", ""),
            )

        enriched.sort(key=sort_key)

        offset = _decode_cursor(cursor)
        page = enriched[offset : offset + DECK_SIZE]
        has_more = offset + DECK_SIZE < len(enriched)

        return {
            "items": [self._public_item(e) for e in page],
            "has_more": has_more,
            "cursor": _encode_cursor(offset + DECK_SIZE) if has_more else None,
            "suggested_mode": suggested_mode,
        }

    # -- enrichment -----------------------------------------------------------
    def _enrich(self, user_id: str, n: dict[str, Any]) -> dict[str, Any]:
        kind = n.get("kind")
        tier = KIND_TIER.get(kind, TIER_SHOULD)
        people_waiting = self._people_waiting(user_id, n)

        due_today = False
        if kind == "date_approaching":
            due_today = self._due_today(user_id, n)
            if due_today:
                tier = TIER_MUST

        # "Someone waiting on you" is a must-tier member: a should-tier item
        # with a person attached gets promoted. Growth stalls stay gentle.
        if people_waiting and tier == TIER_SHOULD:
            tier = TIER_MUST

        time_pressure = self._time_pressure(kind, due_today)
        score = envelope_score("unknown", "unknown", time_pressure)
        code, label = NEXT_ACTIONS.get(kind, ("open", "Open it"))
        return {
            "nudge": n,
            "tier": tier,
            "people_waiting": people_waiting,
            "envelope_score": score,
            "next_action": {"code": code, "label": label},
        }

    def _people_waiting(self, user_id: str, n: dict[str, Any]) -> bool:
        """V1 heuristic: the entity links a person. Tasks via assignee_id;
        projects via supporting_owner_ids. Commitments carry no person link
        in v1."""
        etype, eid = n.get("entity_type"), n.get("entity_id")
        try:
            if etype == "task":
                t = self.ve.get_task(eid, user_id)
                return bool(t and (t.get("assignee_id") or "").strip())
            if etype == "project":
                p = self.ve.get_project(eid, user_id)
                if not p:
                    return False
                raw = p.get("supporting_owner_ids") or "[]"
                ids = json.loads(raw) if isinstance(raw, str) else raw
                return bool(ids)
        except Exception:
            return False
        return False

    def _due_today(self, user_id: str, n: dict[str, Any]) -> bool:
        if n.get("entity_type") != "task":
            return False
        try:
            t = self.ve.get_task(n.get("entity_id"), user_id)
            due = _parse_day((t or {}).get("due_date"))
        except Exception:
            return False
        return due is not None and due == datetime.now(timezone.utc).date()

    @staticmethod
    def _time_pressure(kind: str | None, due_today: bool) -> str:
        if kind == "date_overdue":
            return "urgent"
        if kind == "date_approaching":
            return "urgent" if due_today else "deliberative"
        return "unknown"

    # -- response shaping (stable contract for the frontend) -------------------
    @staticmethod
    def _public_item(e: dict[str, Any]) -> dict[str, Any]:
        n = e["nudge"]
        return {
            "id": n["id"],
            "kind": n.get("kind"),
            "tier": e["tier"],
            "entity_type": n.get("entity_type"),
            "entity_id": n.get("entity_id"),
            "entity_title": n.get("entity_title", ""),
            "why": n.get("why", ""),
            "suggested_seat": n.get("suggested_seat"),
            "people_waiting": e["people_waiting"],
            "next_action": e["next_action"],
        }
