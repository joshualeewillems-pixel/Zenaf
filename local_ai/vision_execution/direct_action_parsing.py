"""
Parse user text into normalized Lane A intents (regex/heuristics live here, not the executor).
"""
from __future__ import annotations

import re
from typing import Any, Literal, TypedDict


class TextSetIntent(TypedDict):
    kind: Literal["text_set"]
    surface_key: str
    value: str


class ChildCreateProjectIntent(TypedDict):
    kind: Literal["child_create_project"]
    title: str


class ChildCreateTasksIntent(TypedDict):
    kind: Literal["child_create_tasks"]
    titles: list[str]


class PersonAssignIntent(TypedDict):
    kind: Literal["person_assign"]
    person_name: str
    clear: bool


class EnumSetIntent(TypedDict):
    kind: Literal["enum_set"]
    surface_key: Literal["status", "priority"]
    raw_value: str


class CollectionAddIntent(TypedDict):
    kind: Literal["collection_add"]
    surface_key: Literal["risks", "dependencies", "execution_steps"]
    body: str


DirectIntent = (
    TextSetIntent
    | ChildCreateProjectIntent
    | ChildCreateTasksIntent
    | PersonAssignIntent
    | EnumSetIntent
    | CollectionAddIntent
)


def _strip_wrapping_quotes(s: str) -> str:
    t = s.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1].strip()
    return t


def normalize_field_update_value(raw: str) -> str:
    """
    Turn captured text after ``to``/``:`` into the string we persist.

    Handles: ``to this "long text"``, curly quotes, and a single quoted span inside noise.
    """
    v = (raw or "").strip()
    if not v:
        return ""
    v = re.sub(r"(?is)^(this|that|the\s+following|as\s+follows)\s*[:\s,]+", "", v).strip()
    v = _strip_wrapping_quotes(v)
    for left, right in (('"', '"'), ("\u201c", "\u201d"), ("'", "'"), ("\u2018", "\u2019")):
        i = v.find(left)
        if i == -1:
            continue
        j = v.find(right, i + 1)
        if j == -1:
            continue
        inner = v[i + 1 : j].strip()
        if inner:
            return re.sub(r"^\s*[:：]\s*", "", inner).strip()
    out = re.sub(r"^\s*[:：]\s*", "", v).strip()
    return out


# Imperative field update (brief / notes / description-style fields).
_RE_FIELD_UPDATE = re.compile(
    r"(?is)(?:\b(?:please|kindly)\s+)?\b(?:change|set|update|edit|replace)\s+(?:the\s+)?"
    r"(?P<tok>brief|notes|summary|description|next\s*step(?:\s*ai)?|admin\s+notes|diagnostics)\b"
    r".{0,64}?"
    r"(?:to|:|=)\s*(?P<val>.+)$"
)


_RE_ADD_PROJECT = re.compile(
    r"(?is)^\s*(?:(?:please|kindly)\s+)?"
    r"(?:add|create|start)\s+(?:a\s+)?(?:new\s+)?project\b"
    r"(?:\s+(?:named|called|titled|with\s+(?:the\s+)?title))?\s*[:\s,]?\s*(?P<title>.+?)\s*$"
)

_RE_ADD_PROJECT_FOR = re.compile(
    r"(?is)^\s*(?:(?:please|kindly)\s+)?"
    r"(?:add|create)\s+(?:a\s+)?(?:new\s+)?project\s+for\s+(?P<title>.+)\s*$"
)


def field_token_to_trunk_key(raw: str) -> str:
    t = (raw or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    if "diagnostic" in t or t == "admin notes":
        return "notes"
    if "next step" in t:
        return "next_step_ai"
    return t.replace(" ", "_")


def parse_task_titles(question: str) -> list[str]:
    q = (question or "").strip()
    if not q:
        return []
    body = q
    m = re.search(
        r"(?is)\b(?:tasks?|todos?|action\s+items)\b\s*[:\-—]\s*(.+)$",
        q,
    )
    if m:
        body = m.group(1).strip()
    titles: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^[\s*•\-\d.)]+\s*", "", s)
        if len(s) >= 2:
            titles.append(s[:500])
    if len(titles) == 1 and ("," in titles[0] or ";" in titles[0]):
        parts = re.split(r"[,;]", titles[0])
        titles = [p.strip() for p in parts if len(p.strip()) >= 2]
    if not titles and ("," in body or ";" in body):
        flat = body.replace("\n", " ").strip()
        parts = re.split(r"[,;]", flat)
        titles = [p.strip() for p in parts if len(p.strip()) >= 2]
    seen: set[str] = set()
    out: list[str] = []
    for t in titles:
        k = t.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out[:40]


_RE_TASK_INTENT = re.compile(
    r"(?i)\b(?:add|create|make)\b.*\b(?:tasks?|todos?|action\s+items)\b"
    r"|\b(?:add|create)\s+(?:some\s+)?(?:tasks?|todos?)\b",
)


def _parse_person_assign_intent(question: str, entity_type: str) -> PersonAssignIntent | None:
    q = (question or "").strip()
    et = (entity_type or "").strip().lower()
    if et == "task":
        if re.search(r"(?is)\b(?:clear|remove|unset)\s+(?:the\s+)?assignee\b", q):
            return PersonAssignIntent(kind="person_assign", person_name="", clear=True)
        m = re.search(r"(?is)\b(?:assign|set)\s+(?:the\s+)?assignee\s+to\s+(?P<name>.+)$", q)
        if not m:
            m = re.search(r"(?is)\bassign\s+this\s+task\s+to\s+(?P<name>.+)$", q)
        if not m:
            m = re.search(r"(?is)\bassign\s+to\s+(?P<name>.+)$", q)
        if not m:
            return None
        name = _strip_wrapping_quotes(m.group("name").strip())
        if not name:
            return None
        return PersonAssignIntent(kind="person_assign", person_name=name[:500], clear=False)
    if et in ("initiative", "project"):
        if re.search(r"(?is)\b(?:clear|remove|unset)\s+(?:the\s+)?owner\b", q):
            return PersonAssignIntent(kind="person_assign", person_name="", clear=True)
        m = re.search(r"(?is)\b(?:assign|set)\s+(?:the\s+)?owner\s+to\s+(?P<name>.+)$", q)
        if not m:
            m = re.search(r"(?is)\bmake\s+(?P<name>.+?)\s+the\s+owner\s*$", q)
        if not m:
            return None
        name = _strip_wrapping_quotes(m.group("name").strip())
        if not name:
            return None
        return PersonAssignIntent(kind="person_assign", person_name=name[:500], clear=False)
    return None


def _parse_enum_set_intent(question: str, entity_type: str) -> EnumSetIntent | None:
    q = (question or "").strip()
    et = (entity_type or "").strip().lower()
    if et not in ("idea", "initiative", "project", "task"):
        return None

    def _tail(group: str) -> str:
        return _strip_wrapping_quotes((group or "").strip())[:500]

    if et in ("project", "task"):
        m = re.search(r"(?is)\b(?:set|change|update)\s+(?:the\s+)?priority\s+(?:to|as|=)\s*(?P<v>.+)$", q)
        if m:
            return EnumSetIntent(kind="enum_set", surface_key="priority", raw_value=_tail(m.group("v")))
        m = re.search(
            r"(?is)\b(?:make|set)\s+(?:it|this)\s+(?:a\s+)?(?P<v>[^.\n]+?)\s+priority\s*$",
            q,
        )
        if m:
            return EnumSetIntent(kind="enum_set", surface_key="priority", raw_value=_tail(m.group("v")))

    m = re.search(r"(?is)\b(?:set|change|update)\s+(?:the\s+)?status\s+(?:to|as|=)\s*(?P<v>.+)$", q)
    if m:
        return EnumSetIntent(kind="enum_set", surface_key="status", raw_value=_tail(m.group("v")))
    m = re.search(r"(?is)\b(?:mark|set)\s+(?:this\s+)?(?:as\s+)?(?P<v>[a-z][a-z\s\-]{1,40})\s+status\s*$", q)
    if m:
        return EnumSetIntent(kind="enum_set", surface_key="status", raw_value=_tail(m.group("v")))
    return None


def _parse_collection_add_intent(question: str, entity_type: str) -> CollectionAddIntent | None:
    q = (question or "").strip()
    et = (entity_type or "").strip().lower()
    if et != "initiative":
        return None

    def _body(g: str) -> str:
        return (g or "").strip()[:8000]

    m = re.search(r"(?is)\badd\s+(?:an?\s+)?execution\s+step\s*[:\-]?\s*(?P<body>.+)$", q)
    if m:
        b = _body(m.group("body"))
        if len(b) >= 2:
            return CollectionAddIntent(kind="collection_add", surface_key="execution_steps", body=b)
    m = re.search(r"(?is)\badd\s+(?:a\s+)?step\s*[:\-]?\s*(?P<body>.+)$", q)
    if m:
        b = _body(m.group("body"))
        if len(b) >= 2:
            return CollectionAddIntent(kind="collection_add", surface_key="execution_steps", body=b)
    m = re.search(r"(?is)\badd\s+(?:a\s+)?(?:risk|risks)\s*[:\-]?\s*(?P<body>.+)$", q)
    if m:
        b = _body(m.group("body"))
        if len(b) >= 2:
            return CollectionAddIntent(kind="collection_add", surface_key="risks", body=b)
    m = re.search(r"(?is)\badd\s+(?:a\s+)?(?:dependency|dependencies)\s*[:\-]?\s*(?P<body>.+)$", q)
    if m:
        b = _body(m.group("body"))
        if len(b) >= 2:
            return CollectionAddIntent(kind="collection_add", surface_key="dependencies", body=b)
    return None


def parse_direct_action_intent(
    question: str,
    entity_type: str | None = None,
) -> DirectIntent | None:
    """
    Return a single normalized intent, or None if this question is not a Lane A pattern we parse.

    Last imperative wins for field updates (``finditer`` tail).
    """
    q = (question or "").strip()
    if not q:
        return None

    matches = list(_RE_FIELD_UPDATE.finditer(q))
    if matches:
        m = matches[-1]
        tok = field_token_to_trunk_key(m.group("tok"))
        value = normalize_field_update_value(m.group("val"))
        if not value:
            return None
        return TextSetIntent(kind="text_set", surface_key=tok, value=value)

    pm = _RE_ADD_PROJECT.match(q) or _RE_ADD_PROJECT_FOR.match(q)
    if pm:
        title = _strip_wrapping_quotes(pm.group("title"))
        if not title:
            return None
        return ChildCreateProjectIntent(kind="child_create_project", title=title[:500])

    if _RE_TASK_INTENT.search(q):
        titles = parse_task_titles(q)
        if titles:
            return ChildCreateTasksIntent(kind="child_create_tasks", titles=titles)

    et = (entity_type or "").strip().lower() or None
    if et:
        hit = _parse_person_assign_intent(q, et)
        if hit:
            return hit
        hit = _parse_enum_set_intent(q, et)
        if hit:
            return hit
        hit = _parse_collection_add_intent(q, et)
        if hit:
            return hit

    return None
