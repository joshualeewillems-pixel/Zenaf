"""Today aggregate API — the ranked morning briefing.

``GET /today`` consumes the follow-through engine's nudge feed server-side
and applies the decided ranking policy. Session-stateless: every interaction
signal arrives on the request.

Query params:
  cursor          opaque deck cursor from a previous response ("next" button);
                  absent/invalid restarts the deck
  dismissed_ids   nudge ids swiped away this briefing (repeatable, or comma
                  separated) — "not now" for the item, "not my mode" for the
                  seat pattern
  engaged_id      nudge id the user stopped on — its seat becomes
                  ``suggested_mode`` ("seems like you're in Conductor mode?")
  mode            accepted seat name — the deck's lens: within each tier
                  the seat's own cards lead (see TodayService.briefing)

Response (stable contract for the frontend — keep backward compatible):
  {items[<=3], has_more, cursor|null, suggested_mode|null}

ADHD rule: no counts, no totals, no badges anywhere in this response. The
client must not render red dots off this feed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.routes.auth_routes import get_current_user
from local_ai.today.service import TodayService

router = APIRouter(prefix="/today", tags=["today"])


def _svc() -> TodayService:
    return TodayService()


def _uid(user: dict) -> str:
    return user["id"]


@router.get("")
def get_today(
    cursor: str | None = Query(default=None),
    dismissed_ids: list[str] = Query(default=[]),
    engaged_id: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    try:
        flat: list[str] = []
        for value in dismissed_ids:
            flat.extend(p for p in (s.strip() for s in value.split(",")) if p)
        return _svc().briefing(
            _uid(user),
            cursor=cursor,
            dismissed_ids=flat,
            engaged_id=engaged_id,
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001 — thin translation layer
        raise HTTPException(status_code=500, detail="today briefing error") from exc
