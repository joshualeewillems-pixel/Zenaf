"""
Lane A handler implementations: coverage row + parsed payload → persistence + deterministic reply.

Lane A handlers: ``text_set``, ``text_append``, ``child_create`` (workflow rows), ``person_assign``, ``enum_set``, ``collection_add`` (checklist steps only).
"""
from __future__ import annotations

import string
from typing import Any, Callable, Literal

from local_ai.integration_commit import commit_precision
from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.direct_action_enum_normalize import (
    normalize_priority_value,
    normalize_status_value,
)
from local_ai.vision_execution.direct_action_parsing import DirectIntent
from local_ai.vision_execution.ve_integration_schema import entity_type_ui_heading

Status = Literal["handled", "declined", "error"]


def _result(
    status: Status,
    message: str = "",
    *,
    refresh_hint: str | None = None,
    created_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "direct_ve_action",
        "status": status,
        "message": message,
        "refresh_hint": refresh_hint,
        "created_entities": created_entities or [],
    }


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def format_confirmation_template(template: str, **kwargs: Any) -> str:
    """Fill ``deterministic_confirmation_template``; unknown placeholders stay literal."""
    t = (template or "").strip()
    if not t:
        return ""
    try:
        return string.Formatter().vformat(t, (), _SafeDict(kwargs))
    except Exception:
        return t


def resolve_person_id_by_name_exact(name: str) -> str | None:
    """
    Exact case-insensitive match on ``persons.name`` only.
    Multiple matches (duplicate names) → None (caller declines).
    """
    key = (name or "").strip()
    if not key:
        return None
    key_cf = key.casefold()
    people = ve_storage.list_persons()
    matches = [p for p in people if (str(p.get("name") or "").strip()).casefold() == key_cf]
    if len(matches) == 1:
        return str(matches[0].get("id") or "").strip() or None
    return None


def _last_created_project_id(context: dict[str, Any] | None) -> str | None:
    if not isinstance(context, dict):
        return None
    hints = context.get("ve_direct_session")
    if isinstance(hints, dict) and hints.get("last_created_project_id"):
        s = str(hints["last_created_project_id"]).strip()
        return s or None
    return None


def handle_text_set(
    row: dict[str, Any],
    parsed: DirectIntent,
    *,
    context: dict[str, Any] | None,
    user_id: str,
    entity_id: str,
    entity_type: str,
) -> dict[str, Any]:
    if parsed.get("kind") != "text_set":
        return _result("declined")
    uid = (user_id or "").strip()
    value = str(parsed.get("value") or "").strip()
    sk = str(parsed.get("surface_key") or "").strip()
    if not uid or not value or not sk:
        return _result("declined")
    res = commit_precision(entity_id, entity_type, sk, value, user_id=uid)
    if res.get("ok"):
        tmpl = str(row.get("deterministic_confirmation_template") or "")
        fl = str(res.get("field_label") or sk).strip()
        heading = entity_type_ui_heading(entity_type)
        msg = format_confirmation_template(tmpl, value=value, field_label=fl, heading=heading)
        if not msg:
            msg = f"Recorded → {heading} → {fl}"
        return _result("handled", msg, refresh_hint=f"{entity_type}:{entity_id}")
    err = str(res.get("error") or "write_failed")
    if err in ("field_unresolved", "unsupported_storage_field", "unsupported_field_for_entity"):
        return _result("declined")
    return _result("error", f"Save didn't complete — {err}")


def handle_child_create(
    row: dict[str, Any],
    parsed: DirectIntent,
    *,
    context: dict[str, Any] | None,
    user_id: str,
    entity_id: str | None,
    entity_type: str | None,
) -> dict[str, Any]:
    uid = (user_id or "").strip()
    if not uid:
        return _result("declined")
    sk = str(row.get("surface_key") or "")

    if parsed.get("kind") == "child_create_project":
        if entity_type != "initiative" or not entity_id:
            return _result("declined")
        title = str(parsed.get("title") or "").strip()
        if not title:
            return _result("declined")
        proj = ve_storage.create_project(
            M.ProjectCreate(initiative_id=entity_id, title=title[:500]),
            uid,
        )
        pid = str(proj.get("id") or "")
        ptitle = str(proj.get("title") or title).strip()
        tmpl = str(row.get("deterministic_confirmation_template") or "")
        msg = format_confirmation_template(tmpl, title=ptitle)
        if not msg:
            msg = f"Created → Project → {ptitle}"
        return _result(
            "handled",
            msg,
            refresh_hint="vision_execution:projects",
            created_entities=[
                {"entity_type": "project", "entity_id": pid, "title": ptitle},
            ],
        )

    if parsed.get("kind") == "child_create_tasks":
        et = (entity_type or "").strip().lower() if entity_type else None
        eid = (entity_id or "").strip() if entity_id else None
        project_id: str | None = None
        if et == "project" and eid:
            project_id = eid
        if not project_id:
            project_id = _last_created_project_id(context)
        if not project_id:
            return _result("declined")
        titles = list(parsed.get("titles") or [])
        if not titles:
            return _result("declined")
        created: list[dict[str, Any]] = []
        for t in titles:
            row_t = ve_storage.create_task(
                M.TaskCreate(project_id=project_id, title=t),
                uid,
            )
            tid = str(row_t.get("id") or "")
            created.append({"entity_type": "task", "entity_id": tid, "title": t})
        prov = ve_storage.get_project(project_id, uid) or {}
        ptitle = str(prov.get("title") or "Project").strip()
        n = len(created)
        tmpl = str(row.get("deterministic_confirmation_template") or "")
        task_noun = "task" if n == 1 else "tasks"
        msg = format_confirmation_template(
            tmpl,
            task_count=n,
            task_noun=task_noun,
            project_title=ptitle,
        )
        if not msg:
            msg = f"Created {n} {task_noun} under Project → {ptitle}"
        return _result(
            "handled",
            msg,
            refresh_hint=f"project:{project_id}",
            created_entities=created,
        )

    return _result("declined")


def handle_person_assign(
    row: dict[str, Any],
    parsed: DirectIntent,
    *,
    context: dict[str, Any] | None,
    user_id: str,
    entity_id: str,
    entity_type: str,
) -> dict[str, Any]:
    if parsed.get("kind") != "person_assign":
        return _result("declined")
    uid = (user_id or "").strip()
    if not uid:
        return _result("declined")
    et = (entity_type or "").strip().lower()
    clear = bool(parsed.get("clear"))
    person_name = str(parsed.get("person_name") or "").strip()
    pid: str | None
    if clear:
        pid = None
        display_name = "unassigned"
    else:
        pid = resolve_person_id_by_name_exact(person_name)
        if not pid:
            return _result("declined")
        display_name = person_name
    if pid:
        p = ve_storage.get_person(pid)
        if p:
            display_name = str(p.get("name") or person_name).strip() or person_name

    tmpl = str(row.get("deterministic_confirmation_template") or "")
    if et == "initiative":
        out = ve_storage.update_initiative(entity_id, M.InitiativeUpdate(owner_id=pid), uid)
        if not out:
            return _result("error", "Save didn't complete — initiative not found")
        msg = format_confirmation_template(tmpl, person_name=display_name)
        if not msg:
            msg = f"Assigned → Initiative → Owner ({display_name})"
        return _result("handled", msg, refresh_hint=f"initiative:{entity_id}")
    if et == "project":
        out = ve_storage.update_project(entity_id, M.ProjectUpdate(owner_id=pid), uid)
        if not out:
            return _result("error", "Save didn't complete — project not found")
        msg = format_confirmation_template(tmpl, person_name=display_name)
        if not msg:
            msg = f"Assigned → Project → Owner ({display_name})"
        return _result("handled", msg, refresh_hint=f"project:{entity_id}")
    if et == "task":
        out = ve_storage.update_task(entity_id, M.TaskUpdate(assignee_id=pid), uid)
        if not out:
            return _result("error", "Save didn't complete — task not found")
        msg = format_confirmation_template(tmpl, person_name=display_name)
        if not msg:
            msg = f"Assigned → Task → Assignee ({display_name})"
        return _result("handled", msg, refresh_hint=f"task:{entity_id}")
    return _result("declined")


def handle_enum_set(
    row: dict[str, Any],
    parsed: DirectIntent,
    *,
    context: dict[str, Any] | None,
    user_id: str,
    entity_id: str,
    entity_type: str,
) -> dict[str, Any]:
    if parsed.get("kind") != "enum_set":
        return _result("declined")
    uid = (user_id or "").strip()
    sk = str(parsed.get("surface_key") or "")
    raw = str(parsed.get("raw_value") or "").strip()
    if not uid or not sk or not raw:
        return _result("declined")
    et = (entity_type or "").strip().lower()

    if sk == "status":
        canon = normalize_status_value(et, raw)
    elif sk == "priority":
        canon = normalize_priority_value(et, raw)
    else:
        return _result("declined")
    if not canon:
        return _result("declined")
    if et == "initiative" and sk == "priority":
        return _result("declined")

    tmpl = str(row.get("deterministic_confirmation_template") or "")
    msg = format_confirmation_template(tmpl, value=canon)
    if not msg:
        msg = f"Set {et} {sk} to {canon}."

    if et == "initiative":
        out = ve_storage.update_initiative(entity_id, M.InitiativeUpdate(status=canon), uid)
        if not out:
            return _result("error", "Save didn't complete — initiative not found")
        return _result("handled", msg, refresh_hint=f"initiative:{entity_id}")
    if et == "project":
        if sk == "status":
            out = ve_storage.update_project(entity_id, M.ProjectUpdate(status=canon), uid)
        else:
            out = ve_storage.update_project(entity_id, M.ProjectUpdate(priority=canon), uid)
        if not out:
            return _result("error", "Save didn't complete — project not found")
        return _result("handled", msg, refresh_hint=f"project:{entity_id}")
    if et == "task":
        if sk == "status":
            out = ve_storage.update_task(entity_id, M.TaskUpdate(status=canon), uid)
        else:
            out = ve_storage.update_task(entity_id, M.TaskUpdate(priority=canon), uid)
        if not out:
            return _result("error", "Save didn't complete — task not found")
        return _result("handled", msg, refresh_hint=f"task:{entity_id}")
    if et == "idea":
        if sk != "status":
            return _result("declined")
        out = ve_storage.update_idea(entity_id, M.IdeaUpdate(status=canon), uid)
        if not out:
            return _result("error", "Save didn't complete — idea not found")
        return _result("handled", msg, refresh_hint=f"idea:{entity_id}")
    return _result("declined")


def _append_initiative_text_field(
    *,
    entity_id: str,
    user_id: str,
    storage_key: str,
    chunk: str,
    tmpl: str,
) -> dict[str, Any]:
    uid = (user_id or "").strip()
    sk = (storage_key or "").strip()
    body = (chunk or "").strip()
    if not uid or not body or sk not in ("risks", "dependencies", "notes"):
        return _result("declined")
    cur = ve_storage.get_initiative(entity_id, uid) or {}
    old = str(cur.get(sk) or "").strip()
    merged = f"{old}\n\n{body}".strip() if old else body
    out = ve_storage.update_initiative(entity_id, M.InitiativeUpdate(**{sk: merged}), uid)
    if not out:
        return _result("error", "Save didn't complete — initiative not found")
    msg = format_confirmation_template(tmpl)
    if not msg:
        msg = f"Updated initiative {sk}."
    return _result("handled", msg, refresh_hint=f"initiative:{entity_id}")


def handle_text_append(
    row: dict[str, Any],
    parsed: DirectIntent,
    *,
    context: dict[str, Any] | None,
    user_id: str,
    entity_id: str,
    entity_type: str,
) -> dict[str, Any]:
    if (entity_type or "").strip().lower() != "initiative":
        return _result("declined")
    kind = str(parsed.get("kind") or "")
    if kind not in ("text_append", "collection_add"):
        return _result("declined")
    sk = str(parsed.get("surface_key") or "").strip()
    chunk = str(parsed.get("value") or parsed.get("body") or "").strip()
    tmpl = str(row.get("deterministic_confirmation_template") or "")
    if sk in ("risks", "dependencies", "notes") and chunk:
        return _append_initiative_text_field(
            entity_id=entity_id,
            user_id=user_id,
            storage_key=sk,
            chunk=chunk[:12000],
            tmpl=tmpl,
        )
    return _result("declined")


def handle_collection_add(
    row: dict[str, Any],
    parsed: DirectIntent,
    *,
    context: dict[str, Any] | None,
    user_id: str,
    entity_id: str,
    entity_type: str,
) -> dict[str, Any]:
    if parsed.get("kind") != "collection_add":
        return _result("declined")
    uid = (user_id or "").strip()
    sk = str(parsed.get("surface_key") or "")
    body = str(parsed.get("body") or "").strip()
    if not uid or not body or sk != "execution_steps":
        return _result("declined")
    if (entity_type or "").strip().lower() != "initiative":
        return _result("declined")

    tmpl = str(row.get("deterministic_confirmation_template") or "")

    ve_storage.create_execution_step(
        uid,
        ve_storage.EXECUTION_STEPS_SCOPE_INITIATIVE,
        entity_id,
        body[:4000],
        sort_order=None,
        source="user",
        source_evaluation_id=None,
    )
    msg = format_confirmation_template(tmpl)
    if not msg:
        msg = "Modified execution checklist on initiative."
    return _result("handled", msg, refresh_hint=f"initiative:{entity_id}")


def handler_name_for_row(row: dict[str, Any], parsed: dict[str, Any] | None = None) -> str:
    """Map coverage ``handler`` + parsed intent to executable handler bucket."""
    h = str(row.get("handler") or "")
    sk = str(row.get("surface_key") or "")
    ent = str(row.get("entity") or "")
    pkind = str((parsed or {}).get("kind") or "")
    if h == "workflow_router" and sk in (
        "workflow:create_project",
        "workflow:create_task_under_project",
    ):
        return "child_create"
    if h == "checklist_row_crud" and sk == "execution_steps" and ent == "initiative":
        return "collection_add"
    if pkind == "text_append" and h == "text_set" and sk == "notes" and ent == "initiative":
        return "text_append"
    if h == "text_append":
        return "text_append"
    return h


HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "text_set": handle_text_set,
    "text_append": handle_text_append,
    "child_create": handle_child_create,
    "person_assign": handle_person_assign,
    "enum_set": handle_enum_set,
    "collection_add": handle_collection_add,
}


def execute_direct_surface_action(
    row: dict[str, Any],
    parsed: DirectIntent,
    *,
    context: dict[str, Any] | None,
    user_id: str,
    entity_id: str | None,
    entity_type: str | None,
) -> dict[str, Any]:
    p = parsed if isinstance(parsed, dict) else {}
    name = handler_name_for_row(row, p)
    fn = HANDLERS.get(name)
    if not fn:
        return _result("declined")
    if name == "text_set":
        if not entity_id or not entity_type:
            return _result("declined")
        return handle_text_set(
            row,
            parsed,
            context=context,
            user_id=user_id,
            entity_id=entity_id,
            entity_type=entity_type,
        )
    if name == "text_append":
        if not entity_id or not entity_type:
            return _result("declined")
        return handle_text_append(
            row,
            parsed,
            context=context,
            user_id=user_id,
            entity_id=entity_id,
            entity_type=entity_type,
        )
    if name == "child_create":
        return handle_child_create(
            row,
            parsed,
            context=context,
            user_id=user_id,
            entity_id=entity_id,
            entity_type=entity_type,
        )
    if name in ("person_assign", "enum_set", "collection_add"):
        if not entity_id or not entity_type:
            return _result("declined")
        if name == "person_assign":
            return handle_person_assign(
                row,
                parsed,
                context=context,
                user_id=user_id,
                entity_id=entity_id,
                entity_type=entity_type,
            )
        if name == "enum_set":
            return handle_enum_set(
                row,
                parsed,
                context=context,
                user_id=user_id,
                entity_id=entity_id,
                entity_type=entity_type,
            )
        return handle_collection_add(
            row,
            parsed,
            context=context,
            user_id=user_id,
            entity_id=entity_id,
            entity_type=entity_type,
        )
    return _result("declined")
