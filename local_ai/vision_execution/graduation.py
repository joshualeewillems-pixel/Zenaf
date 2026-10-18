"""Idea graduation: an idea becomes work when its checklist is worked through.

Decided 2026-10-18 (reworked): instead of fixed "practical fields," each idea
defines its own "practical" as a nested hierarchical checklist, built
conversationally ("what would make this real?"). An idea is ready to graduate
when its checklist is non-empty and every item is done — thought experiment
-> work in progress. The hierarchy is levels of importance/scope ("buy socks"
is a task, "start a sock company" is an initiative), never a rigid pipeline.

On graduation the checklist unfolds into the work breakdown (top-level items
-> tasks, nested items -> subtasks, dependencies carried over) and is kept as
provenance, marked superseded.

Readiness is advisory for explicit user commands (the user decides); the
batch confirm path enforces it via assert_checklist_ready.
"""
from __future__ import annotations

from typing import Any

#: Every level an idea can land on. None (stays an idea) is the default.
TARGET_LEVELS = ("idea", "task", "project", "initiative")

#: Levels that count as graduation (leaving idea-hood behind).
GRADUATE_LEVELS = ("task", "project", "initiative")


class IdeaNotReadyError(Exception):
    """Graduation attempted before the idea's checklist is worked through."""

    def __init__(self, missing: list[str], idea_title: str = ""):
        self.missing = missing
        self.idea_title = idea_title
        where = f" '{idea_title}'" if idea_title else ""
        super().__init__(
            f"This idea{where} isn't ready to graduate yet — it's still a thought "
            f"experiment. {'; '.join(missing)}."
        )


def checklist_readiness(items: list[dict[str, Any]]) -> tuple[bool, list[str], dict]:
    """Check whether an idea's checklist is worked through.

    `items` are the idea's non-superseded checklist items (flat). Ready means
    a non-empty checklist with every item done. Returns (ready, missing, stats)
    with missing named in plain language and stats = {total, done, remaining}.
    """
    live = [it for it in items if not it.get("superseded")]
    total = len(live)
    done = sum(1 for it in live if (it.get("status") or "") == "done")
    remaining = total - done
    stats = {"total": total, "done": done, "remaining": remaining}
    if total == 0:
        return (
            False,
            ["it needs a checklist of what would make it real — talk it through and we'll build one together"],
            stats,
        )
    if remaining:
        open_items = [it for it in live if (it.get("status") or "") != "done"]
        named = [
            f"'{(it.get('title') or 'untitled').strip()}' is still open"
            for it in open_items[:5]
        ]
        if remaining > 5:
            named.append(f"and {remaining - 5} more still open")
        return False, named, stats
    return True, [], stats


def assert_checklist_ready(items: list[dict[str, Any]], idea_title: str = "") -> None:
    """Raise IdeaNotReadyError naming the unfinished items when not ready."""
    ready, missing, _ = checklist_readiness(items)
    if not ready:
        raise IdeaNotReadyError(missing, idea_title)


def build_checklist_tree(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nest flat checklist items by parent_id into a tree.

    Returns root nodes, each with `children` (sorted by position) and the
    item's own `depends_on` ids preserved. Orphaned parent refs and self-refs
    are treated as roots (defensive; the API validates on write).
    """
    by_id: dict[str, dict[str, Any]] = {
        it["id"]: {**it, "children": []} for it in items
    }
    roots: list[dict[str, Any]] = []
    for it in items:
        node = by_id[it["id"]]
        pid = it.get("parent_id")
        if pid and pid in by_id and pid != it["id"]:
            by_id[pid]["children"].append(node)
        else:
            roots.append(node)

    def _sort(nodes: list[dict[str, Any]]) -> None:
        nodes.sort(key=lambda n: (n.get("position") or 0))
        for n in nodes:
            _sort(n["children"])

    _sort(roots)
    return roots


def build_graduated_payload(
    idea: dict[str, Any],
    target_level: str,
    source_idea_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a VE Create payload for the graduated entity.

    Preserves the idea's content (title, description, intent) and links
    provenance back to the source idea: initiatives carry source_idea_id
    (schema-native); projects/tasks carry it in notes.
    Returns (entity_type, payload_dict).
    """
    if target_level not in GRADUATE_LEVELS:
        raise ValueError(
            f"unknown target_level: {target_level!r} (expected one of {GRADUATE_LEVELS})"
        )
    title = (idea.get("title") or "").strip()
    description = (idea.get("description") or "").strip()
    summary = (idea.get("summary") or "").strip()
    desired_outcome = (idea.get("desired_outcome") or "").strip()
    notes = (idea.get("notes") or "").strip()

    detail = description or summary
    if desired_outcome:
        detail = (detail + "\n\nIntent: " + desired_outcome).strip()

    provenance = f"Graduated from idea '{title}'"
    if source_idea_id:
        provenance += f" ({source_idea_id})"
    full_notes = (provenance + ("\n\n" + notes if notes else "")).strip()

    if target_level == "task":
        return ("task", {
            "title": title,
            "description": detail,
            "notes": full_notes,
            "status": "Todo",
        })
    if target_level == "project":
        return ("project", {
            "title": title,
            "brief": detail,
            "notes": full_notes,
            "status": "Draft",
            "current_focus": desired_outcome,
        })
    payload: dict[str, Any] = {
        "title": title,
        "brief": detail,
        "notes": full_notes,
        "status": "Draft",
    }
    if source_idea_id:
        payload["source_idea_id"] = source_idea_id
    return ("initiative", payload)
