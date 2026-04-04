"""
Presort / placement suggestions for meeting extraction review (suggest-only; no writes).

Returns a single structured JSON proposal for type + link + optional parent. Uses the same
execution seam as other Vision Execution LLM routes when ``routing_context`` is provided.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from local_ai.vision_execution.entity_judgment_primitives import (
    clamp01,
    compute_novelty,
    infer_entity_type_for_heuristic_new,
    placement_heuristic_confidence_from_ratio,
    placement_heuristic_target_confidence,
    select_best_catalog_row_match,
)
from local_ai.vision_execution.idea_evaluate import _extract_json_object

logger = logging.getLogger(__name__)

PROPOSED_TYPES = frozenset({"idea", "initiative", "project", "task", "signal"})
PLACEMENT_MODES = frozenset({"new", "attach", "amend"})
LINK_ENTITY_TYPES = frozenset({"idea", "initiative", "project", "task"})
MAX_ENTITIES_PER_KIND = 40
TASK_NAME = "candidate_placement_suggest"

STRATEGIC_FIT_LEVELS = frozenset({"high", "medium", "low"})
CAPACITY_RISK_LEVELS = frozenset({"low", "medium", "high"})

PROFILE_SYNTHESIS_KEYS: tuple[tuple[str, str], ...] = (
    ("core_definition", "Core definition"),
    ("current_goals", "Current goals"),
    ("growth_focus_12_months", "Growth focus (12 months)"),
    ("economic_engine", "Economic engine"),
    ("non_negotiables", "Non-negotiables"),
    ("strategic_filter", "Strategic filter"),
    ("current_constraints", "Current constraints"),
    ("capacity_limit", "Capacity limit"),
    ("kill_philosophy", "Kill philosophy"),
    ("strength_positioning", "Strength positioning"),
)

_PLACEMENT_JSON_BASE = """
Respond with exactly one JSON object (no markdown, no code fences):
{{
  "proposed_type": "idea",
  "confidence": 0.0,
  "placement_mode": "new",
  "target": null,
  "suggested_parent": null,
  "reason": "one or two sentences (semantic / entity fit)",
  "alternatives": []
}}

target and suggested_parent when non-null must be objects:
{{ "id": "...", "type": "idea|initiative|project|task", "title": "...", "confidence": 0.0 }}
"""

_PLACEMENT_JSON_PROFILE = """
When ACTIVE CORE PROFILE is present above, also include (same JSON object):
  "profile_alignment": 0.0-1.0,
  "profile_reason": "1-2 sentences: goals, economic engine, non-negotiables, capacity, kill philosophy, constraints",
  "strategic_fit": "high" | "medium" | "low",
  "capacity_risk": "low" | "medium" | "high"

Profile-aware placement guidance:
- Prefer attach or a concrete suggested_parent under existing work when capacity_limit implies avoiding new top-level streams; reflect that in capacity_risk.
- If the candidate supports current_goals / economic_engine / growth_focus, favor stronger strategic_fit and explain in profile_reason.
- If it likely violates non_negotiables or fails strategic_filter, prefer signal or contained attach/amend; say so in profile_reason.
- Apply kill_philosophy to avoid inventing work the profile would deprioritize; use signal for noise.
- Respect current_constraints in placement_mode and parent choice.
"""

PLACEMENT_PROMPT = """You classify one extraction candidate against the user's existing workspace entities (internal mirror). Suggest only — the user will confirm.

Rules:
- proposed_type: one of idea | initiative | project | task | signal (signal = radar attention item, not executable work).
- placement_mode:
  - "new" — create a new entity; use suggested_parent if the candidate should live under an existing parent (child).
  - "attach" — treat as the same record as an existing entity (duplicate / same workstream); target must be that entity.
  - "amend" — candidate extends or updates an existing entity; same as attach for linking (user merges manually).
- target: required when placement_mode is attach or amend — must copy id, type, title EXACTLY from ENTITY_CATALOG.
- suggested_parent: optional when placement_mode is new — parent entity to create under (idea/initiative/project/task only).
- Use ONLY ids that appear in ENTITY_CATALOG. If nothing fits, placement_mode "new", target null, suggested_parent null.
- alternatives: at most 2 other options; each has type (proposed_type), short reason, confidence 0–1.
- confidence fields: conservative decimals 0–1.
{profile_section}
ENTITY_CATALOG:
{catalog}

OPTIONAL_CONTEXT:
{context}

CANDIDATE:
Title: {title}
Summary: {summary}
Evidence: {evidence}
{placement_json_tail}

JSON:"""


def _truncate_field(text: str, max_len: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def profile_has_synthesis_content(profile: Mapping[str, Any] | None) -> bool:
    if not profile:
        return False
    for key, _ in PROFILE_SYNTHESIS_KEYS:
        if _truncate_field(str(profile.get(key) or ""), 1):
            return True
    return False


def profile_has_output_metadata(profile: Mapping[str, Any] | None) -> bool:
    """True if we should attach profile_id / profile-scored fields to the response."""
    if not profile:
        return False
    if profile_has_synthesis_content(profile):
        return True
    return bool(str(profile.get("name") or "").strip())


def format_profile_block_for_prompt(profile: Mapping[str, Any]) -> str:
    lines: list[str] = []
    pname = _truncate_field(str(profile.get("name") or ""), 200)
    if pname:
        lines.append(f"Profile name: {pname}")
    for key, label in PROFILE_SYNTHESIS_KEYS:
        val = _truncate_field(str(profile.get(key) or ""), 520)
        if val:
            lines.append(f"{label}: {val}")
    if not lines:
        return ""
    return "\n".join(lines)


def blank_profile_response() -> dict[str, Any]:
    return {
        "profile_id": None,
        "profile_name": None,
        "profile_alignment": None,
        "profile_reason": None,
        "strategic_fit": None,
        "capacity_risk": None,
    }


def _normalize_strategic_fit(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    return s if s in STRATEGIC_FIT_LEVELS else "medium"


def _normalize_capacity_risk(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    return s if s in CAPACITY_RISK_LEVELS else "medium"


def profile_output_from_llm(
    data: Mapping[str, Any],
    *,
    active_profile: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not active_profile or not profile_has_output_metadata(active_profile):
        return blank_profile_response()
    pid = str(active_profile.get("id") or "").strip() or None
    pname = str(active_profile.get("name") or "").strip() or None
    raw_align = data.get("profile_alignment")
    if raw_align is None or (isinstance(raw_align, str) and not str(raw_align).strip()):
        alignment = 0.55
    else:
        alignment = clamp01(raw_align)
    pr = _truncate_field(str(data.get("profile_reason") or ""), 800)
    if not pr:
        pr = "Evaluated against active profile; verify fit with goals, constraints, and capacity."
    return {
        "profile_id": pid,
        "profile_name": pname,
        "profile_alignment": alignment,
        "profile_reason": pr,
        "strategic_fit": _normalize_strategic_fit(data.get("strategic_fit")),
        "capacity_risk": _normalize_capacity_risk(data.get("capacity_risk")),
    }


def _merge_profile_into_result(
    result: dict[str, Any],
    raw_llm: Mapping[str, Any] | None,
    *,
    active_profile: Mapping[str, Any] | None,
) -> dict[str, Any]:
    out = dict(result)
    po = profile_output_from_llm(raw_llm or {}, active_profile=active_profile)
    out.update(po)
    return out


def _build_catalog(existing: Mapping[str, Any] | None) -> tuple[str, dict[tuple[str, str], dict[str, str]]]:
    """Return prompt block and index (type_lower, id) -> row."""
    existing = existing or {}
    lines: list[str] = []
    index: dict[tuple[str, str], dict[str, str]] = {}

    def add(kind: str, rows: list[Any] | None, label: str) -> None:
        if not rows:
            return
        for row in rows[:MAX_ENTITIES_PER_KIND]:
            if not isinstance(row, dict):
                continue
            eid = str(row.get("id") or "").strip()
            if not eid:
                continue
            if kind == "idea":
                title = str(row.get("title") or "").strip()
                extra = str(row.get("summary") or row.get("description") or "")[:200]
            elif kind in ("initiative", "project", "task"):
                title = str(row.get("title") or "").strip()
                extra = str(row.get("brief") or row.get("description") or "")[:200]
            elif kind == "asset":
                title = str(row.get("name") or "").strip()
                extra = ""
            elif kind == "person":
                title = str(row.get("name") or "").strip()
                extra = ""
            else:
                continue
            fk = kind.lower()
            index[(fk, eid)] = {"title": title, "type": fk}
            rel = ""
            if kind == "project" and row.get("initiative_id"):
                rel = f" initiative_id={row.get('initiative_id')}"
            if kind == "task" and row.get("project_id"):
                rel = f" project_id={row.get('project_id')}"
            lines.append(f"- [{fk}] id={eid} title={title[:120]}{rel} {extra}".strip())

    add("idea", list(existing.get("ideas") or []), "ideas")
    add("initiative", list(existing.get("initiatives") or []), "initiatives")
    add("project", list(existing.get("projects") or []), "projects")
    add("task", list(existing.get("tasks") or []), "tasks")
    add("asset", list(existing.get("assets") or []), "assets")
    add("person", list(existing.get("people") or []), "people")

    if not lines:
        return "(no existing entities)", index
    return "\n".join(lines), index


def _validate_node(
    node: Any,
    index: dict[tuple[str, str], dict[str, str]],
    *,
    allow_types: frozenset[str],
) -> dict[str, Any] | None:
    if node is None:
        return None
    if not isinstance(node, dict):
        return None
    eid = str(node.get("id") or "").strip()
    et = str(node.get("type") or "").strip().lower()
    if not eid or et not in allow_types:
        return None
    if (et, eid) not in index:
        return None
    title = str(node.get("title") or index[(et, eid)]["title"]).strip()
    return {
        "id": eid,
        "type": et,
        "title": title[:500],
        "confidence": clamp01(node.get("confidence")),
    }


def _normalize_alternatives(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for x in raw[:2]:
        if not isinstance(x, dict):
            continue
        t = str(x.get("type") or "").strip().lower()
        if t not in PROPOSED_TYPES:
            continue
        out.append(
            {
                "type": t,
                "reason": str(x.get("reason") or "")[:400],
                "confidence": clamp01(x.get("confidence")),
            }
        )
    return out


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    js = _extract_json_object(raw)
    if not js:
        return None
    try:
        return json.loads(js)
    except json.JSONDecodeError:
        return None


def _heuristic_profile_stub(active: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": str(active.get("id") or "").strip() or None,
        "profile_name": str(active.get("name") or "").strip() or None,
        "profile_alignment": 0.45,
        "profile_reason": "Heuristic match only; full profile-aware scoring unavailable. Verify against your core profile.",
        "strategic_fit": "medium",
        "capacity_risk": "medium",
    }


def _heuristic_suggestion(
    title: str,
    summary: str,
    existing: Mapping[str, Any] | None,
    index: dict[tuple[str, str], dict[str, str]],
    *,
    active_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    blob = f"{title} {summary}".lower().strip()
    best_ratio, best = select_best_catalog_row_match(
        blob,
        existing,
        max_entities_per_kind=MAX_ENTITIES_PER_KIND,
        include_row_text_context=False,
    )
    if best and not compute_novelty(best_ratio, existing_match_threshold=0.35):
        bt, bid, btitle = best
        out = {
            "proposed_type": infer_entity_type_for_heuristic_new(),
            "confidence": placement_heuristic_confidence_from_ratio(best_ratio),
            "placement_mode": "attach",
            "target": {
                "id": bid,
                "type": bt,
                "title": btitle,
                "confidence": placement_heuristic_target_confidence(best_ratio),
            },
            "suggested_parent": None,
            "reason": "Heuristic match to an existing title (LLM unavailable or parse failed). Verify before commit.",
            "alternatives": [],
            "_fallback": True,
        }
    else:
        out = {
            "proposed_type": infer_entity_type_for_heuristic_new(),
            "confidence": 0.4,
            "placement_mode": "new",
            "target": None,
            "suggested_parent": None,
            "reason": "No strong entity match heuristically; defaulting to new idea. Refine type and links manually.",
            "alternatives": [],
            "_fallback": True,
        }
    if active_profile and profile_has_output_metadata(active_profile):
        out.update(_heuristic_profile_stub(active_profile))
    else:
        out.update(blank_profile_response())
    return out


def _normalize_llm_payload(data: dict[str, Any], index: dict[tuple[str, str], dict[str, str]]) -> dict[str, Any]:
    pt = str(data.get("proposed_type") or "idea").strip().lower()
    if pt not in PROPOSED_TYPES:
        pt = "idea"
    pm = str(data.get("placement_mode") or "new").strip().lower()
    if pm not in PLACEMENT_MODES:
        pm = "new"

    target = _validate_node(data.get("target"), index, allow_types=LINK_ENTITY_TYPES)
    parent = _validate_node(data.get("suggested_parent"), index, allow_types=LINK_ENTITY_TYPES)

    if pm in ("attach", "amend") and target is None:
        pm = "new"
    if pm != "new":
        parent = None

    return {
        "proposed_type": pt,
        "confidence": clamp01(data.get("confidence")),
        "placement_mode": pm,
        "target": target,
        "suggested_parent": parent,
        "reason": str(data.get("reason") or "")[:1200],
        "alternatives": _normalize_alternatives(data.get("alternatives")),
    }


def suggest_candidate_placement(
    candidate: Mapping[str, Any],
    existing_entities: Mapping[str, Any] | None,
    context: str | None,
    *,
    active_profile: Mapping[str, Any] | None = None,
    user_id: str | None,
    use_execution_seam: bool,
    exec_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return placement JSON or { "error": str, ... }.

    ``candidate`` keys: title (or text), summary, evidence_quote (or evidence / sourceExcerpt).
    ``active_profile``: optional core profile row (id, name, synthesis fields) to shape strategic placement.
    """
    title = str(candidate.get("title") or candidate.get("text") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    evidence = str(
        candidate.get("evidence_quote") or candidate.get("evidence") or candidate.get("sourceExcerpt") or ""
    ).strip()

    ap: Mapping[str, Any] | None = active_profile if active_profile and profile_has_output_metadata(active_profile) else None
    if ap:
        pblock = format_profile_block_for_prompt(ap)
        profile_section = (
            "\nACTIVE CORE PROFILE (use to shape type, placement, attach vs new, and risk — user confirms):\n"
            + (pblock if pblock else "(profile present but synthesis fields empty)")
            + "\n"
        )
        placement_json_tail = (_PLACEMENT_JSON_BASE + _PLACEMENT_JSON_PROFILE).strip()
    else:
        profile_section = ""
        placement_json_tail = _PLACEMENT_JSON_BASE.strip()

    catalog, index = _build_catalog(existing_entities)
    ctx = (context or "").strip()[:2000] or "(none)"

    from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id, principal_for_vision_execution_user
    from local_ai.vision_execution.llm_seam import ve_eval_provider_shim

    principal = principal_for_vision_execution_user(user_id) if user_id else execution_principal_from_legacy_user_id(None)
    provider = ve_eval_provider_shim(principal, use_execution_seam=use_execution_seam)

    prompt = PLACEMENT_PROMPT.format(
        profile_section=profile_section,
        catalog=catalog,
        context=ctx,
        title=title[:500] or "(untitled)",
        summary=summary[:2000] or "(none)",
        evidence=evidence[:2000] or "(none)",
        placement_json_tail=placement_json_tail,
    )

    try:
        raw = provider.generate(prompt, timeout=60)
    except Exception as e:
        logger.warning("[candidate-placement] generate failed: %s", e)
        out = _heuristic_suggestion(title, summary, existing_entities, index, active_profile=ap)
        out["error"] = str(e)[:300]
        return out

    if not raw or not isinstance(raw, str):
        return _heuristic_suggestion(title, summary, existing_entities, index, active_profile=ap)

    data = _parse_llm_json(raw)
    if not isinstance(data, dict):
        return _heuristic_suggestion(title, summary, existing_entities, index, active_profile=ap)

    try:
        normalized = _normalize_llm_payload(data, index)
    except Exception:
        return _heuristic_suggestion(title, summary, existing_entities, index, active_profile=ap)

    normalized = _merge_profile_into_result(normalized, data, active_profile=ap)

    mu = (exec_meta or {}).get("model_used")
    pu = (exec_meta or {}).get("provider_used")
    if mu is not None:
        normalized["model_used"] = mu
    if pu is not None:
        normalized["provider_used"] = pu
    return normalized
