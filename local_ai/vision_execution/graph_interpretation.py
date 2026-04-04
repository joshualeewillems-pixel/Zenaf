"""
Lightweight interpretation pass: classify each extracted row against the workspace context graph.

Runs after post_process_extraction. Rule-based only (no LLM): existing*MatchId, matchConfidence,
possibleMatches, title similarity.

**Architectural intent:** This module is the reference implementation for “mirror graph interpretation”
(proposed graph ops + payload). Extend other pipelines toward the same contract when touched; see
``docs/02_ACTIVE_DESIGN/MIRROR_GRAPH_INTERPRETATION_SYSTEM_NOTE.md`` and ``SYSTEM_REFERENCE.md`` §2.5.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from local_ai.vision_execution.extraction_canonization import _title_similarity

InterpretType = Literal[
    "existing_enrichment",
    "existing_amendment",
    "child_of_existing",
    "genuinely_new",
    "signal_only",
]

# Tunable thresholds (heuristic).
_STRONG_MC = 0.72
_AMEND_MC = 0.82
_STRONG_SIM = 0.68
_MEDIUM_SIM = 0.48
_PM_STRONG = 0.55

# Row keys to offer as structured patches (camelCase JSON / extractor shape).
_PATCH_ROW_KEYS: tuple[str, ...] = (
    "title",
    "name",
    "brief",
    "description",
    "summary",
    "status",
    "notes",
    "initiativeTitle",
    "initiativeId",
    "projectTitle",
    "projectId",
    "ownerName",
    "assigneeName",
    "suggestedOwner",
    "kind",
    "role",
    "context",
)


def _interp(it: InterpretType, *, target_id: str | None = None, confidence: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": it}
    if target_id:
        out["targetId"] = str(target_id).strip()
    if confidence is not None:
        out["confidence"] = round(float(confidence), 4)
    return out


def _row_primary_label(row: dict[str, Any]) -> str | None:
    for k in ("title", "name", "text", "statement", "label"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _row_description_blob(row: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for k in ("description", "brief", "summary", "text", "statement", "detail"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return "\n\n".join(parts) if parts else None


def _row_notes_only(row: dict[str, Any]) -> str | None:
    v = row.get("notes")
    return v.strip() if isinstance(v, str) and v.strip() else None


def _jsonable_patch_value(val: Any) -> bool:
    if isinstance(val, bool) or isinstance(val, int):
        return True
    if isinstance(val, float):
        return math.isfinite(val)
    if isinstance(val, str):
        return True
    return False


def _build_payload_update(row: dict[str, Any]) -> dict[str, Any]:
    pl: dict[str, Any] = {}
    notes = _row_notes_only(row)
    if notes:
        pl["notes"] = notes
    desc = _row_description_blob(row)
    if desc:
        pl["description"] = desc
    if not pl:
        ex = row.get("sourceExcerpt")
        if isinstance(ex, str) and ex.strip():
            pl["notes"] = ex.strip()[:8000]
    return pl


def _build_payload_patch(row: dict[str, Any]) -> dict[str, Any]:
    ftp: dict[str, Any] = {}
    for k in _PATCH_ROW_KEYS:
        if k not in row:
            continue
        val = row.get(k)
        if val is None or val == "":
            continue
        if _jsonable_patch_value(val):
            ftp[k] = val
    desc = _row_description_blob(row)
    if desc and "description" not in ftp and "brief" not in ftp and "summary" not in ftp:
        ftp["description"] = desc
    return {"fieldsToPatch": ftp} if ftp else {}


def _build_payload_create_child(row: dict[str, Any], parent_id: str) -> dict[str, Any]:
    pl: dict[str, Any] = {}
    pid = (parent_id or "").strip()
    if pid:
        pl["parentId"] = pid
    t = _row_primary_label(row)
    if t:
        pl["title"] = t
    desc = _row_description_blob(row)
    if desc:
        pl["description"] = desc
    notes = _row_notes_only(row)
    if notes:
        pl["notes"] = notes
    return pl


def _build_payload_create_new(row: dict[str, Any]) -> dict[str, Any]:
    pl: dict[str, Any] = {}
    t = _row_primary_label(row)
    if t:
        pl["title"] = t
    desc = _row_description_blob(row)
    if desc:
        pl["description"] = desc
    notes = _row_notes_only(row)
    if notes:
        pl["notes"] = notes
    # Extractor placement hints (not match-ids — those imply a different interpretation path).
    proj = row.get("projectId") or row.get("project_id")
    ini = row.get("initiativeId") or row.get("initiative_id")
    for hint in (proj, ini):
        if isinstance(hint, str) and hint.strip():
            pl["parentId"] = hint.strip()
            break
    return pl


def _build_payload_ignore(row: dict[str, Any]) -> dict[str, Any]:
    pl: dict[str, Any] = {}
    note = _row_primary_label(row)
    if note:
        pl["notes"] = note[:8000]
    ex = row.get("sourceExcerpt") or row.get("sourceQuote")
    if isinstance(ex, str) and ex.strip():
        pl["notes"] = ex.strip()[:8000]
    return pl


def _with_graph_ops(base: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Attach ``action`` and optional ``payload`` from classification + row text (no LLM)."""
    it = base.get("type")
    tid = str(base.get("targetId") or "").strip()
    out = dict(base)
    pl: dict[str, Any] = {}

    if it == "existing_enrichment":
        out["action"] = "update"
        pl = _build_payload_update(row)
    elif it == "existing_amendment":
        out["action"] = "patch"
        pl = _build_payload_patch(row)
    elif it == "child_of_existing":
        out["action"] = "create_child"
        pl = _build_payload_create_child(row, tid)
    elif it == "genuinely_new":
        out["action"] = "create_new"
        pl = _build_payload_create_new(row)
    elif it == "signal_only":
        out["action"] = "ignore"
        pl = _build_payload_ignore(row)
    else:
        out["action"] = "ignore"
        pl = {}

    if pl:
        out["payload"] = pl
    return out


def _ctx_entries(ctx: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    if not isinstance(ctx, dict):
        return []
    raw = ctx.get(key)
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _valid_id_set(entries: list[dict[str, Any]]) -> set[str]:
    return {str(e.get("id") or "").strip() for e in entries if str(e.get("id") or "").strip()}


def _norm_mc(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip().lower()
        if s == "high":
            return 0.85
        if s == "medium":
            return 0.55
        if s == "low":
            return 0.3
    try:
        f = float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if f > 1.0 and f <= 100.0:
        f = f / 100.0
    return f if 0.0 <= f <= 1.0 else None


def _best_title_match(title: str, entries: list[dict[str, Any]], title_key: str = "title") -> tuple[str | None, float]:
    title = (title or "").strip()
    if not title or not entries:
        return None, 0.0
    best_id: str | None = None
    best_s = 0.0
    for e in entries:
        tid = str(e.get("id") or "").strip()
        t2 = str(e.get(title_key) or e.get("name") or "").strip()
        if not tid or not t2:
            continue
        s = float(_title_similarity(title, t2))
        if s > best_s:
            best_s = s
            best_id = tid
    return best_id, best_s


def _best_possible_match(row: dict[str, Any]) -> tuple[str | None, float]:
    pm = row.get("possibleMatches")
    if not isinstance(pm, list) or not pm:
        return None, 0.0
    best_id: str | None = None
    best_s = 0.0
    for m in pm:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "").strip()
        try:
            sim = float(m.get("similarity") or 0.0)
        except (TypeError, ValueError):
            sim = 0.0
        if mid and sim > best_s:
            best_s = sim
            best_id = mid
    return best_id, best_s


def _enrich_or_amend(*, has_id: bool, mc: float | None, sim: float | None, target_id: str) -> dict[str, Any]:
    conf = mc if mc is not None else sim
    if not has_id:
        return _interp("genuinely_new", confidence=conf)
    if mc is not None and mc >= _AMEND_MC:
        return _interp("existing_amendment", target_id=target_id, confidence=mc)
    if mc is not None and mc >= _STRONG_MC:
        return _interp("existing_enrichment", target_id=target_id, confidence=mc)
    if sim is not None and sim >= _STRONG_SIM:
        return _interp("existing_enrichment", target_id=target_id, confidence=sim)
    if mc is not None and mc >= _MEDIUM_SIM:
        return _interp("existing_enrichment", target_id=target_id, confidence=mc)
    if sim is not None and sim >= _MEDIUM_SIM:
        return _interp("existing_enrichment", target_id=target_id, confidence=sim)
    # Model supplied an id but similarity scores are weak — still treat as enrichment on that node.
    return _interp("existing_enrichment", target_id=target_id, confidence=conf if conf is not None else 0.45)


def _interpret_initiative(row: dict[str, Any], init_ids: set[str], initiatives: list[dict[str, Any]]) -> dict[str, Any]:
    mid = str(row.get("existingInitiativeMatchId") or row.get("existing_initiative_match_id") or "").strip()
    mc = _norm_mc(row.get("matchConfidence") if row.get("matchConfidence") is not None else row.get("match_confidence"))
    title = str(row.get("title") or "")
    if mid and mid in init_ids:
        sim = float(_title_similarity(title, next((str(i.get("title") or "") for i in initiatives if str(i.get("id")) == mid), "")))
        return _enrich_or_amend(has_id=True, mc=mc, sim=sim, target_id=mid)
    bid, sim = _best_title_match(title, initiatives)
    if bid and sim >= _STRONG_SIM:
        return _enrich_or_amend(has_id=True, mc=mc, sim=sim, target_id=bid)
    return _interp("genuinely_new", confidence=mc or (sim if sim >= _MEDIUM_SIM else None))


def _interpret_project(
    row: dict[str, Any],
    proj_ids: set[str],
    init_ids: set[str],
    projects: list[dict[str, Any]],
    initiatives: list[dict[str, Any]],
) -> dict[str, Any]:
    pid = str(row.get("existingProjectMatchId") or row.get("existing_project_match_id") or "").strip()
    iid = str(row.get("existingInitiativeMatchId") or row.get("existing_initiative_match_id") or "").strip()
    mc = _norm_mc(row.get("matchConfidence") if row.get("matchConfidence") is not None else row.get("match_confidence"))
    title = str(row.get("title") or "")

    if pid and pid in proj_ids:
        sim = float(_title_similarity(title, next((str(p.get("title") or "") for p in projects if str(p.get("id")) == pid), "")))
        return _enrich_or_amend(has_id=True, mc=mc, sim=sim, target_id=pid)

    if iid and iid in init_ids and (not pid or pid not in proj_ids):
        sim = float(_title_similarity(title, next((str(x.get("title") or "") for x in initiatives if str(x.get("id")) == iid), "")))
        conf = mc if mc is not None else sim
        if (mc is not None and mc >= _MEDIUM_SIM) or sim >= _MEDIUM_SIM:
            return _interp("child_of_existing", target_id=iid, confidence=conf)

    bid, sim = _best_title_match(title, projects)
    if bid and sim >= _STRONG_SIM:
        return _enrich_or_amend(has_id=True, mc=mc, sim=sim, target_id=bid)

    bid2, sim2 = _best_title_match(title, initiatives)
    if bid2 and sim2 >= _STRONG_SIM:
        return _interp("child_of_existing", target_id=bid2, confidence=mc if mc is not None else sim2)

    return _interp("genuinely_new", confidence=mc)


def _interpret_task(
    row: dict[str, Any],
    task_ids: set[str],
    proj_ids: set[str],
    tasks: list[dict[str, Any]],
    projects: list[dict[str, Any]],
) -> dict[str, Any]:
    tid = str(row.get("existingTaskMatchId") or row.get("existing_task_match_id") or "").strip()
    pid = str(row.get("existingProjectMatchId") or row.get("existing_project_match_id") or "").strip()
    mc = _norm_mc(row.get("matchConfidence") if row.get("matchConfidence") is not None else row.get("match_confidence"))
    title = str(row.get("title") or "")

    if tid and tid in task_ids:
        sim = float(_title_similarity(title, next((str(t.get("title") or "") for t in tasks if str(t.get("id")) == tid), "")))
        return _enrich_or_amend(has_id=True, mc=mc, sim=sim, target_id=tid)

    if pid and pid in proj_ids and (not tid or tid not in task_ids):
        sim = float(_title_similarity(title, next((str(p.get("title") or "") for p in projects if str(p.get("id")) == pid), "")))
        conf = mc if mc is not None else sim
        if (mc is not None and mc >= _MEDIUM_SIM) or sim >= _MEDIUM_SIM:
            return _interp("child_of_existing", target_id=pid, confidence=conf)

    bid, sim = _best_title_match(title, tasks)
    if bid and sim >= _STRONG_SIM:
        return _enrich_or_amend(has_id=True, mc=mc, sim=sim, target_id=bid)

    bid2, sim2 = _best_title_match(title, projects)
    if bid2 and sim2 >= _STRONG_SIM:
        return _interp("child_of_existing", target_id=bid2, confidence=mc if mc is not None else sim2)

    return _interp("genuinely_new", confidence=mc)


def _interpret_asset(row: dict[str, Any], asset_ids: set[str], assets: list[dict[str, Any]]) -> dict[str, Any]:
    aid = str(row.get("existingAssetMatchId") or row.get("existing_asset_match_id") or "").strip()
    mc = _norm_mc(row.get("matchConfidence") if row.get("matchConfidence") is not None else row.get("match_confidence"))
    name = str(row.get("name") or "")
    if aid and aid in asset_ids:
        sim = float(_title_similarity(name, next((str(a.get("name") or "") for a in assets if str(a.get("id")) == aid), "")))
        return _enrich_or_amend(has_id=True, mc=mc, sim=sim, target_id=aid)
    bid, sim = _best_title_match(name, assets, title_key="name")
    if bid and sim >= _STRONG_SIM:
        return _enrich_or_amend(has_id=True, mc=mc, sim=sim, target_id=bid)
    return _interp("genuinely_new", confidence=mc)


def _interpret_person(row: dict[str, Any], people_ids: set[str], people: list[dict[str, Any]]) -> dict[str, Any]:
    pid = str(row.get("existingPersonMatchId") or row.get("existing_person_match_id") or "").strip()
    mc = _norm_mc(row.get("matchConfidence") if row.get("matchConfidence") is not None else row.get("match_confidence"))
    name = str(row.get("name") or "")
    if pid and pid in people_ids:
        sim = float(_title_similarity(name, next((str(p.get("name") or "") for p in people if str(p.get("id")) == pid), "")))
        return _enrich_or_amend(has_id=True, mc=mc, sim=sim, target_id=pid)
    bid, sim = _best_title_match(name, people, title_key="name")
    if bid and sim >= _STRONG_SIM:
        return _enrich_or_amend(has_id=True, mc=mc, sim=sim, target_id=bid)
    return _interp("genuinely_new", confidence=mc)


def _interpret_idea(
    row: dict[str, Any],
    initiatives: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    ck = str(row.get("candidateKind") or row.get("candidate_kind") or "").strip().lower()
    if ck in ("workspace_hint",):
        return _interp("signal_only", confidence=0.35)
    title = str(row.get("title") or "")
    if not title.strip():
        return _interp("signal_only", confidence=0.25)

    best_id: str | None = None
    best_s = 0.0
    for lst in (initiatives, projects, tasks):
        bid, sim = _best_title_match(title, lst, title_key="title")
        if bid and sim > best_s:
            best_s = sim
            best_id = bid
    if best_id and best_s >= _STRONG_SIM:
        return _interp("existing_enrichment", target_id=best_id, confidence=best_s)
    if best_id and best_s >= _MEDIUM_SIM:
        return _interp("genuinely_new", confidence=best_s)
    return _interp("genuinely_new", confidence=0.4)


def _interpret_signal(row: dict[str, Any]) -> dict[str, Any]:
    return _interp("signal_only", confidence=_norm_mc(row.get("confidence")) or 0.5)


def _interpret_insight(row: dict[str, Any]) -> dict[str, Any]:
    return _interp("signal_only", confidence=_norm_mc(row.get("confidence")) or 0.45)


def _interpret_summary(row: dict[str, Any]) -> dict[str, Any]:
    return _interp("signal_only", confidence=_norm_mc(row.get("confidence")) or 0.4)


def _interpret_candidate(row: dict[str, Any]) -> dict[str, Any]:
    pm_id, pm_s = _best_possible_match(row)
    if pm_id and pm_s >= _PM_STRONG:
        return _interp("existing_enrichment", target_id=pm_id, confidence=pm_s)
    text = str(row.get("text") or "").strip()
    if len(text) < 24:
        return _interp("signal_only", confidence=0.35)
    conf_raw = row.get("confidence")
    if conf_raw in ("low", None, ""):
        return _interp("signal_only", confidence=0.4)
    return _interp("genuinely_new", confidence=0.55)


def interpret_against_graph(
    extraction: dict[str, Any],
    context: dict[str, Any] | None,
    notes: str = "",
) -> dict[str, Any]:
    """
    Mutate ``extraction`` in place: each entity row gains ``interpretation``:
    ``{ type, targetId?, confidence?, action, payload? }`` (camelCase for JSON parity).

    ``action`` proposes a graph operation (update / patch / create_child / create_new / ignore).
    ``payload`` pre-fills notes, description, parentId, or ``fieldsToPatch`` from the row (no LLM).

    ``notes`` is reserved for future chunk-scoped retrieval; unused in the rule-based v1.
    """
    _ = notes  # reserved
    initiatives = _ctx_entries(context, "initiatives")
    projects = _ctx_entries(context, "projects")
    tasks = _ctx_entries(context, "tasks")
    assets = _ctx_entries(context, "assets")
    people = _ctx_entries(context, "people")

    init_ids = _valid_id_set(initiatives)
    proj_ids = _valid_id_set(projects)
    task_ids = _valid_id_set(tasks)
    asset_ids = _valid_id_set(assets)
    people_ids = _valid_id_set(people)

    def apply_list(key: str, fn: Any) -> None:
        arr = extraction.get(key)
        if not isinstance(arr, list):
            return
        for row in arr:
            if isinstance(row, dict):
                row["interpretation"] = _with_graph_ops(fn(row), row)

    apply_list("ideas", lambda r: _interpret_idea(r, initiatives, projects, tasks))
    apply_list("initiatives", lambda r: _interpret_initiative(r, init_ids, initiatives))
    apply_list("projects", lambda r: _interpret_project(r, proj_ids, init_ids, projects, initiatives))
    apply_list("tasks", lambda r: _interpret_task(r, task_ids, proj_ids, tasks, projects))
    apply_list("assets", lambda r: _interpret_asset(r, asset_ids, assets))
    apply_list("peopleReferences", lambda r: _interpret_person(r, people_ids, people))
    peo = extraction.get("people")
    if isinstance(peo, list) and peo is not extraction.get("peopleReferences"):
        for row in peo:
            if isinstance(row, dict) and "interpretation" not in row:
                row["interpretation"] = _with_graph_ops(_interpret_person(row, people_ids, people), row)

    apply_list("signals", _interpret_signal)
    apply_list("insights", _interpret_insight)
    apply_list("candidates", _interpret_candidate)

    summ = extraction.get("summary")
    if isinstance(summ, dict):
        summ["interpretation"] = _with_graph_ops(_interpret_summary(summ), summ)

    return extraction
