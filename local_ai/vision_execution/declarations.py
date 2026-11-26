"""Board declarations — Rivers and Holds as recorded decisions.

Founder direction (2026-11-25, the Board interaction pass): a River
(a project's declared window) and a Hold (a visitor-placed review
checkpoint) are the visitor's own fixings of the terrain. They used
to live as PROVISIONAL session-local state in the Campaign Board's
frontend — stored nowhere, gone on the next visit (a recorded
residual gap). Declarations are now made conversationally with
Valen and recorded through the conversation (the declaration tail,
``local_ai/conversation/declaration_tail.py``).

Persistence — discovered before building, per the brief: VE project
records DO carry ``start_date`` / ``end_date``, but those fields
already have a different job — they are the project's recorded span,
the window the board's routes are drawn over (``projectSpan``'s
'project' source) and editable VE data in their own right. A River
is a separate visitor declaration (it can be declared from a signal
mid-project and withdrawn without touching the project's recorded
dates), and Holds have no project field at all. So declarations
persist as VE **decisions** — the owner-scoped, append-only store
whose provenance (who/when) the server stamps — with dedicated
decision types:

- ``river_declaration``  — final snapshot ``{start, end}`` (ISO)
- ``river_withdrawal``   — final snapshot ``{}``
- ``hold_placed``        — final snapshot ``{at}`` (ISO); the
  decision's own id IS the hold's id from then on
- ``hold_moved``         — final snapshot ``{hold_id, at}``
- ``hold_removed``       — final snapshot ``{hold_id}``

One River per project: the latest river event wins (a declaration
sets the window, a withdrawal clears it, a later declaration sets a
new one). Holds are many per project, keyed by their placing
decision's id, moved and removed by later decisions naming that id.
Current state is DERIVED by folding the project's declaration
decisions in recorded order — the derived-state pattern
``derived.py`` already uses. No new table, no new store.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as S

RIVER_DECLARATION = "river_declaration"
RIVER_WITHDRAWAL = "river_withdrawal"
HOLD_PLACED = "hold_placed"
HOLD_MOVED = "hold_moved"
HOLD_REMOVED = "hold_removed"

DECLARATION_TYPES = frozenset(
    {RIVER_DECLARATION, RIVER_WITHDRAWAL, HOLD_PLACED, HOLD_MOVED, HOLD_REMOVED}
)


def valid_iso_datetime(value: Any) -> str | None:
    """The value as an ISO date/datetime string, or None.

    Accepts the shapes the tail grammar admits (``YYYY-MM-DD`` or a
    full ISO datetime); anything else — free text, a number, an
    empty string — is not a date this store will carry.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return None
    return text


def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
    snap = row.get("final_values_snapshot")
    return snap if isinstance(snap, dict) else {}


def fold_declarations(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Fold decision rows into per-project declaration state.

    ``rows`` are decision dicts in ``list_decisions`` order
    (newest first); the fold replays them oldest-first. Rows whose
    type is not a declaration type, or whose payload is malformed,
    are ignored — a corrupt row degrades to no declaration, never
    to a broken read. Returns ``{project_id: {"river": {...}|None,
    "holds": [{"id", "at"}, ...]}}``; projects with no live
    declaration state are omitted.
    """
    state: dict[str, dict[str, Any]] = {}
    for row in reversed(rows):
        dtype = row.get("decision_type")
        if dtype not in DECLARATION_TYPES:
            continue
        project_id = str(row.get("entity_id") or "")
        if not project_id:
            continue
        entry = state.setdefault(project_id, {"river": None, "holds": {}})
        snap = _snapshot(row)
        if dtype == RIVER_DECLARATION:
            start = valid_iso_datetime(snap.get("start"))
            end = valid_iso_datetime(snap.get("end"))
            if start is not None and end is not None:
                entry["river"] = {
                    "start": start,
                    "end": end,
                    "decision_id": row.get("id"),
                }
        elif dtype == RIVER_WITHDRAWAL:
            entry["river"] = None
        elif dtype == HOLD_PLACED:
            at = valid_iso_datetime(snap.get("at"))
            hold_id = str(row.get("id") or "")
            if at is not None and hold_id:
                entry["holds"][hold_id] = {"id": hold_id, "at": at}
        elif dtype == HOLD_MOVED:
            hold_id = str(snap.get("hold_id") or "")
            at = valid_iso_datetime(snap.get("at"))
            if hold_id in entry["holds"] and at is not None:
                entry["holds"][hold_id] = {"id": hold_id, "at": at}
        elif dtype == HOLD_REMOVED:
            hold_id = str(snap.get("hold_id") or "")
            entry["holds"].pop(hold_id, None)
    out: dict[str, dict[str, Any]] = {}
    for project_id, entry in state.items():
        holds = sorted(entry["holds"].values(), key=lambda h: h["at"])
        if entry["river"] is not None or holds:
            out[project_id] = {"river": entry["river"], "holds": holds}
    return out


def derive_project_declarations(
    user_id: str, project_id: str
) -> dict[str, Any]:
    """The caller's current declaration state for one project:
    ``{"river": {...}|None, "holds": [...]}`` — owner-scoped through
    the decisions list (another owner's rows are never read)."""
    rows = S.list_decisions(
        user_id, entity_type="project", entity_id=project_id
    )
    folded = fold_declarations(rows)
    return folded.get(project_id, {"river": None, "holds": []})


def record_declaration(
    user_id: str,
    project_id: str,
    decision_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Append one declaration decision, owner-stamped by the store."""
    return S.create_decision(
        M.DecisionCreate(
            user_id=user_id,
            entity_type="project",
            entity_id=project_id,
            decision_type=decision_type,
            final_values_snapshot=payload,
        )
    )


def apply_declaration_act(
    user_id: str, staged_project_id: str, act: dict[str, Any]
) -> bool:
    """Record one parsed declaration act, or refuse it.

    The act is honored only against the turn's staged project (the
    brief's rule): declare/withdraw/place must name that project;
    move/remove must name a hold that stands in that project's
    current derived state. Dates are re-validated here — the parser
    is not trusted twice over. Returns True when a decision was
    written. Never raises on act shape; a refusal is a False.
    """
    verb = act.get("verb")
    if verb in ("declare-window", "withdraw-window", "place-hold"):
        if str(act.get("project") or "") != staged_project_id:
            return False
    if verb == "declare-window":
        start = valid_iso_datetime(act.get("start"))
        end = valid_iso_datetime(act.get("end"))
        if start is None or end is None:
            return False
        if not datetime.fromisoformat(end) > datetime.fromisoformat(start):
            return False
        record_declaration(
            user_id, staged_project_id, RIVER_DECLARATION,
            {"start": start, "end": end},
        )
        return True
    if verb == "withdraw-window":
        current = derive_project_declarations(user_id, staged_project_id)
        if current["river"] is None:
            return False
        record_declaration(user_id, staged_project_id, RIVER_WITHDRAWAL, {})
        return True
    if verb == "place-hold":
        at = valid_iso_datetime(act.get("at"))
        if at is None:
            return False
        record_declaration(
            user_id, staged_project_id, HOLD_PLACED, {"at": at}
        )
        return True
    if verb in ("move-hold", "remove-hold"):
        hold_id = str(act.get("hold") or "")
        if not hold_id:
            return False
        current = derive_project_declarations(user_id, staged_project_id)
        if hold_id not in {h["id"] for h in current["holds"]}:
            return False
        if verb == "move-hold":
            at = valid_iso_datetime(act.get("at"))
            if at is None:
                return False
            record_declaration(
                user_id, staged_project_id, HOLD_MOVED,
                {"hold_id": hold_id, "at": at},
            )
        else:
            record_declaration(
                user_id, staged_project_id, HOLD_REMOVED,
                {"hold_id": hold_id},
            )
        return True
    return False
