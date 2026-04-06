"""
Bridge elicitation replies into Lane A: capture value → confirm → execute.

Supports ``person_assign``, ``text_set``, ``text_append`` (initiative risks/deps/notes merge), and ``collection_add`` (execution steps checklist).
Client echoes ``context.pending_ve_elicitation`` from SSE / direct_ve_action until cleared.
"""
from __future__ import annotations

import re
from typing import Any

from local_ai.integration_commit import user_affirms_precision_commit
from local_ai.vision_execution.action_coverage import find_text_set_row, find_tier1_row, resolve_direct_surface_action
from local_ai.vision_execution.direct_action_handlers import execute_direct_surface_action
from local_ai.vision_execution.ve_integration_schema import normalize_trunk_token_to_storage_key

PENDING_VERSION = 1
_MAX_TEXT_ELICITATION_LEN = 12000
_MAX_COLLECTION_ITEMS = 40
_MAX_COLLECTION_ITEM_LEN = 2000
_MAX_COLLECTION_BODY_LEN = 8000
_COLLECTION_SURFACES = frozenset({"risks", "dependencies", "execution_steps"})


def _result_ve(
    status: str,
    message: str = "",
    *,
    refresh_hint: str | None = None,
    pending_ve_elicitation: dict[str, Any] | None | bool = False,
) -> dict[str, Any]:
    """
    ``pending_ve_elicitation``:
    - False (default): omit key (client keeps prior ref).
    - None: explicit clear.
    - dict: replace client ref.
    """
    out: dict[str, Any] = {
        "kind": "direct_ve_action",
        "status": status,
        "message": message,
        "refresh_hint": refresh_hint,
        "created_entities": [],
    }
    if pending_ve_elicitation is not False:
        out["pending_ve_elicitation"] = pending_ve_elicitation
    return out


def _normalize_text_surface(entity_type: str, raw: str) -> str | None:
    et = (entity_type or "").strip().lower()
    s = (raw or "").strip()
    if not s or et not in ("idea", "initiative", "project", "task"):
        return None
    sk = normalize_trunk_token_to_storage_key(et, s) or s
    if find_text_set_row(et, sk):
        return sk
    return None


def _coerce_pending(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        if int(raw.get("version") or 0) != PENDING_VERSION:
            return None
    except (TypeError, ValueError):
        return None
    phase = str(raw.get("phase") or "").strip()
    kind = str(raw.get("elicitation_kind") or "").strip()
    et = str(raw.get("entity_type") or "").strip().lower()
    eid = str(raw.get("entity_id") or "").strip()
    if phase not in ("awaiting_value", "awaiting_confirm"):
        return None
    if not eid:
        return None

    if kind == "person_assign":
        if et not in ("initiative", "project", "task"):
            return None
        fk = str(raw.get("field_key") or "").strip()
        if fk not in ("owner_id", "assignee_id"):
            return None
        if et == "task" and fk != "assignee_id":
            return None
        if et in ("initiative", "project") and fk != "owner_id":
            return None
        return dict(raw)

    if kind == "text_set":
        if et not in ("idea", "initiative", "project", "task"):
            return None
        sk = _normalize_text_surface(et, str(raw.get("surface_key") or raw.get("field_key") or ""))
        if not sk:
            return None
        out = dict(raw)
        out["surface_key"] = sk
        out["field_key"] = sk
        return out

    if kind == "collection_add":
        if et != "initiative":
            return None
        sk_raw = str(raw.get("surface_key") or raw.get("field_key") or "").strip()
        sk = normalize_trunk_token_to_storage_key(et, sk_raw) or sk_raw
        if sk not in _COLLECTION_SURFACES:
            return None
        row = find_tier1_row(et, sk)
        h = str(row.get("handler") or "") if row else ""
        ok = row and (
            (h == "text_append" and sk in ("risks", "dependencies"))
            or (h == "checklist_row_crud" and sk == "execution_steps")
        )
        if not ok:
            return None
        out = dict(raw)
        out["surface_key"] = sk
        out["field_key"] = sk
        if phase == "awaiting_confirm":
            items = out.get("proposed_items")
            if not isinstance(items, list):
                return None
            clean: list[str] = []
            for x in items[:_MAX_COLLECTION_ITEMS]:
                s = str(x).strip()
                if s:
                    clean.append(s[:_MAX_COLLECTION_ITEM_LEN])
            if not clean:
                return None
            out["proposed_items"] = clean
        return out

    return None


def _user_declines_followup(q: str) -> bool:
    s = (q or "").strip().lower().rstrip(".!?")
    if s in ("no", "nope", "nah", "cancel", "stop", "wait"):
        return True
    return bool(re.match(r"^\s*(don\'t|do not)\b", s))


def _looks_like_short_question(q: str) -> bool:
    t = (q or "").strip()
    if len(t) > 100:
        return False
    if t.endswith("?"):
        return True
    low = t.lower()
    return bool(re.match(r"^\s*(what|which|how|why|when|where|who|should|could|would|is|are)\b", low))


def _apply_and_return(
    context: dict[str, Any],
    uid: str,
    peid: str,
    pet: str,
    intent: dict[str, Any],
) -> dict[str, Any]:
    row = resolve_direct_surface_action(parsed=intent, entity_id=peid, entity_type=pet, context=context)
    if not row:
        return _result_ve(
            "declined",
            "That save path is not available for this record in Lane A yet.",
            pending_ve_elicitation=None,
        )
    out = execute_direct_surface_action(
        row,
        intent,
        context=context,
        user_id=uid,
        entity_id=peid,
        entity_type=pet,
    )
    from local_ai.vision_execution.direct_action_executor import _apply_lane_a_guard

    _apply_lane_a_guard(context, intent, str(out.get("status") or "declined"))
    if isinstance(out, dict):
        out = dict(out)
        out["pending_ve_elicitation"] = None
    return out


def _resolve_person_pending(
    *,
    question: str,
    context: dict[str, Any],
    uid: str,
    pending: dict[str, Any],
    peid: str,
    pet: str,
) -> dict[str, Any] | None:
    phase = str(pending.get("phase") or "").strip()

    if phase == "awaiting_value":
        if _user_declines_followup(question):
            return _result_ve("handled", "Okay — I will not assign anyone from that thread.", pending_ve_elicitation=None)
        if user_affirms_precision_commit(question):
            return _result_ve(
                "handled",
                "I still need a **name** (exactly as in your people list). Who should it be?",
                pending_ve_elicitation=False,
            )
        if _looks_like_short_question(question):
            return None
        name = question.strip()
        if len(name) > 160:
            return _result_ve(
                "handled",
                "That name is too long for a quick assign — try a shorter person name.",
                pending_ve_elicitation=None,
            )
        if len(name) < 1:
            return None
        next_p = dict(pending)
        next_p["phase"] = "awaiting_confirm"
        next_p["proposed_person_name"] = name
        label = "owner" if next_p.get("field_key") == "owner_id" else "assignee"
        return _result_ve(
            "handled",
            f"Assign **{name}** as {label}? Reply **yes** to confirm.",
            pending_ve_elicitation=next_p,
        )

    if phase == "awaiting_confirm":
        if _user_declines_followup(question):
            return _result_ve("handled", "Okay — not assigning anyone.", pending_ve_elicitation=None)
        if not user_affirms_precision_commit(question):
            return None
        pname = str(pending.get("proposed_person_name") or "").strip()
        if not pname:
            return _result_ve("handled", "I lost the proposed name — who should it be?", pending_ve_elicitation=None)

        intent: dict[str, Any] = {
            "kind": "person_assign",
            "person_name": pname,
            "clear": False,
        }
        return _apply_and_return(context, uid, peid, pet, intent)

    return None


def _surface_label(surface_key: str) -> str:
    return (surface_key or "").replace("_", " ").strip().title() or "field"


def _parse_proposed_collection_items(q: str) -> list[str]:
    raw = (q or "").strip()
    if not raw:
        return []
    lines: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^[\-\*•]\s*", "", s)
        s = re.sub(r"^\d+[\.)]\s*", "", s).strip()
        if s:
            lines.append(s[:_MAX_COLLECTION_ITEM_LEN])
    if lines:
        return lines[:_MAX_COLLECTION_ITEMS]
    return [raw[:_MAX_COLLECTION_ITEM_LEN]]


def _resolve_collection_pending(
    *,
    question: str,
    context: dict[str, Any],
    uid: str,
    pending: dict[str, Any],
    peid: str,
    pet: str,
) -> dict[str, Any] | None:
    sk = str(pending.get("surface_key") or "").strip()
    if not sk or sk not in _COLLECTION_SURFACES:
        return None

    phase = str(pending.get("phase") or "").strip()

    if phase == "awaiting_value":
        if _user_declines_followup(question):
            return _result_ve("handled", "Okay — I will not add those to the list.", pending_ve_elicitation=None)
        if user_affirms_precision_commit(question):
            return _result_ve(
                "handled",
                f"I still need the lines for **{_surface_label(sk)}** (one per line or bullets). Paste them, then we will confirm.",
                pending_ve_elicitation=False,
            )
        if _looks_like_short_question(question):
            return None
        items = _parse_proposed_collection_items(question)
        if not items:
            return None
        next_p = dict(pending)
        next_p["phase"] = "awaiting_confirm"
        next_p["proposed_items"] = items
        prev = "\n".join(f"- {t}" for t in items[:12])
        more = len(items) - 12
        tail = f"\n… and {more} more" if more > 0 else ""
        return _result_ve(
            "handled",
            f"Add **{len(items)}** item(s) to **{_surface_label(sk)}**?\n\n{prev}{tail}\n\nReply **yes** to confirm.",
            pending_ve_elicitation=next_p,
        )

    if phase == "awaiting_confirm":
        if _user_declines_followup(question):
            return _result_ve("handled", "Okay — not adding those.", pending_ve_elicitation=None)
        if not user_affirms_precision_commit(question):
            return None
        items_raw = pending.get("proposed_items")
        if not isinstance(items_raw, list):
            return _result_ve(
                "handled",
                "I lost the proposed lines — paste them again (one per line or bullets).",
                pending_ve_elicitation=None,
            )
        items = [str(x).strip() for x in items_raw if str(x).strip()][: _MAX_COLLECTION_ITEMS]
        if not items:
            return _result_ve(
                "handled",
                "I lost the proposed lines — paste them again.",
                pending_ve_elicitation=None,
            )
        body = "\n\n".join(items).strip()[:_MAX_COLLECTION_BODY_LEN]
        if sk == "execution_steps":
            intent = {"kind": "collection_add", "surface_key": sk, "body": body}
        else:
            intent = {"kind": "text_append", "surface_key": sk, "value": body}
        return _apply_and_return(context, uid, peid, pet, intent)

    return None


def _resolve_text_pending(
    *,
    question: str,
    context: dict[str, Any],
    uid: str,
    pending: dict[str, Any],
    peid: str,
    pet: str,
) -> dict[str, Any] | None:
    sk = str(pending.get("surface_key") or "").strip()
    if not sk:
        return None

    phase = str(pending.get("phase") or "").strip()

    if phase == "awaiting_value":
        if _user_declines_followup(question):
            return _result_ve("handled", "Okay — I will not save that text.", pending_ve_elicitation=None)
        if user_affirms_precision_commit(question):
            return _result_ve(
                "handled",
                f"I still need the text for **{_surface_label(sk)}**. Paste or type it, then we will confirm.",
                pending_ve_elicitation=False,
            )
        body = question.strip()
        if not body:
            return None
        if len(body) > _MAX_TEXT_ELICITATION_LEN:
            return _result_ve(
                "handled",
                f"That text is too long (max {_MAX_TEXT_ELICITATION_LEN} characters). Try a shorter version.",
                pending_ve_elicitation=None,
            )
        next_p = dict(pending)
        next_p["phase"] = "awaiting_confirm"
        next_p["proposed_value"] = body
        preview = body if len(body) <= 200 else body[:197].rstrip() + "…"
        return _result_ve(
            "handled",
            f"Save this as **{_surface_label(sk)}**?\n\n{preview}\n\nReply **yes** to confirm.",
            pending_ve_elicitation=next_p,
        )

    if phase == "awaiting_confirm":
        if _user_declines_followup(question):
            return _result_ve("handled", "Okay — not saving that text.", pending_ve_elicitation=None)
        if not user_affirms_precision_commit(question):
            return None
        val = str(pending.get("proposed_value") or "").strip()
        if not val:
            return _result_ve(
                "handled",
                "I lost the proposed text — what should it say?",
                pending_ve_elicitation=None,
            )

        intent: dict[str, Any] = {
            "kind": "text_set",
            "surface_key": sk,
            "value": val,
        }
        return _apply_and_return(context, uid, peid, pet, intent)

    return None


def try_resolve_pending_ve_elicitation(
    question: str,
    context: dict[str, Any] | None,
    user_id: str,
) -> dict[str, Any] | None:
    """
    If ``context.pending_ve_elicitation`` matches, consume the user turn.

    Returns a ``direct_ve_action`` dict to return from ``evaluate_direct_ve_action``, or None.
    """
    uid = (user_id or "").strip()
    q = (question or "").strip()
    if not uid or not isinstance(context, dict):
        return None

    pending = _coerce_pending(context.get("pending_ve_elicitation"))
    if not pending:
        return None

    from local_ai.vision_execution.direct_action_executor import _resolve_scoped_ve_entity

    eid_scope, et_scope = _resolve_scoped_ve_entity(context)
    peid = str(pending.get("entity_id") or "").strip()
    pet = str(pending.get("entity_type") or "").strip().lower()
    if not eid_scope or not et_scope or eid_scope != peid or et_scope != pet:
        return _result_ve(
            "handled",
            "The focused record changed — repeat what you wanted to capture for **this** item.",
            pending_ve_elicitation=None,
        )

    kind = str(pending.get("elicitation_kind") or "").strip()
    if kind == "person_assign":
        return _resolve_person_pending(question=q, context=context, uid=uid, pending=pending, peid=peid, pet=pet)
    if kind == "text_set":
        return _resolve_text_pending(question=q, context=context, uid=uid, pending=pending, peid=peid, pet=pet)
    if kind == "collection_add":
        return _resolve_collection_pending(question=q, context=context, uid=uid, pending=pending, peid=peid, pet=pet)

    return None
