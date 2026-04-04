"""
Coarse list-level presort for meeting extraction review (triage only; no structural placement).

Returns existing vs new vs unsure (unsure should be rare), optional coarse type, optional catalog ref,
and a short presort_reason. Per-card suggest-candidate-placement remains the detailed path.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping

from local_ai.vision_execution.candidate_placement_suggest import _build_catalog
from local_ai.vision_execution.entity_judgment_primitives import (
    clamp01,
    infer_entity_type_for_heuristic_new,
    presort_confidence_for_catalog_existing,
    presort_confidence_for_idea_title_duplicate,
    presort_confidence_for_new_weak_overlap,
    select_best_catalog_row_match,
    select_best_idea_title_sequence_match,
)
from local_ai.vision_execution.idea_evaluate import _extract_json_object

logger = logging.getLogger(__name__)

BUCKETS = frozenset({"existing", "new", "unsure"})
COARSE_TYPES = frozenset({"idea", "initiative", "project", "task"})
CATALOG_TYPES = frozenset({"idea", "initiative", "project", "task", "asset", "person"})
MAX_ENTITIES_PER_KIND = 40

TRIAGE_PROMPT = """You sort ONE meeting-extraction candidate against the user's existing workspace (ENTITY_CATALOG). This is a fast triage for scanning a list — not final placement.

Return exactly one JSON object (no markdown, no code fences):
{{
  "presort_bucket": "existing" | "new" | "unsure",
  "presort_type": "idea" | "initiative" | "project" | "task" | null,
  "presort_confidence": 0.0,
  "presort_existing_id": null,
  "presort_existing_title": null,
  "presort_reason": "short phrase (see below)"
}}
(Server also sets presort_existing_type from the catalog when presort_existing_id is valid — you may omit it in the model output.)

Core rule — commit to a useful lean:
- Almost always choose **existing** OR **new**. Use **unsure** only in genuinely bad cases (see below).
- Medium confidence is fine. Triage is a first pass; the user refines per card.

presort_bucket:
- **existing** — Plausible same work / duplicate / continuation of ONE catalog row (idea, initiative, project, or task). Copy presort_existing_id and presort_existing_title EXACTLY from ENTITY_CATALOG. Overlap in title, summary, or evidence with that row is enough; perfection is not required.
- **new** — Reads as distinct work, a new stream, or no row is a reasonable match. Default here when you hesitate between "weak maybe duplicate" and new — prefer **new** over **unsure**.
- **unsure** — RARE. Only if: (1) candidate is too vague or content-free to lean either way, OR (2) truly contradictory signals, OR (3) two+ catalog rows are equally strong matches with no way to lean. Do **not** use unsure merely because confidence is not high.

presort_type: For **new**, best guess kind (idea/initiative/project/task). Null if unknown. For **existing**, null (kind follows the matched row).

presort_reason: One short phrase, e.g. "matched existing initiative", "title overlap with task", "appears distinct", "too vague to classify", "weak overlap — lean new".

ENTITY_CATALOG:
{catalog}

OPTIONAL_CONTEXT:
{context}

CANDIDATE:
Title: {title}
Summary: {summary}
Evidence: {evidence}

JSON:"""


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    js = _extract_json_object(raw)
    if not js:
        return None
    try:
        out = json.loads(js)
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None


def _truncate_reason(s: str | None, max_len: int = 200) -> str | None:
    if not s:
        return None
    t = str(s).strip()
    if not t:
        return None
    return t[:max_len]


def _catalog_entity_type_for_id(
    eid: str | None,
    index: dict[tuple[str, str], dict[str, str]],
) -> str | None:
    """Return catalog kind (idea, initiative, …) for a validated entity id, or None."""
    if not eid or not str(eid).strip():
        return None
    sid = str(eid).strip()
    for (fk, key) in index:
        if key == sid and fk in CATALOG_TYPES:
            return fk
    return None


def _validate_catalog_ref(
    eid: str | None,
    etitle: str | None,
    index: dict[tuple[str, str], dict[str, str]],
) -> tuple[str | None, str | None]:
    if not eid or not str(eid).strip():
        return None, None
    sid = str(eid).strip()
    for (fk, key), row in index.items():
        if key == sid and fk in CATALOG_TYPES:
            title = str(etitle or row.get("title") or "").strip() or row.get("title") or sid
            return sid, title[:500]
    return None, None


def _pick_candidate_str(candidate: Mapping[str, Any], *keys: str) -> str | None:
    for k in keys:
        v = candidate.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _row_in_catalog(etype: str, eid: str, index: dict[tuple[str, str], dict[str, str]]) -> tuple[str | None, str | None]:
    key = (etype.lower(), str(eid).strip())
    if key not in index:
        return None, None
    row = index[key]
    tit = str(row.get("title") or eid).strip()[:500]
    return str(eid).strip(), tit


def _extract_match_confidence(candidate: Mapping[str, Any]) -> float | None:
    raw = candidate.get("matchConfidence")
    if raw is None:
        raw = candidate.get("match_confidence")
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _extract_confidence_word(candidate: Mapping[str, Any]) -> str:
    c = candidate.get("confidence")
    return str(c).strip().lower() if c is not None else ""


def _extract_source_stage(candidate: Mapping[str, Any]) -> str:
    s = candidate.get("sourceStage") or candidate.get("source_stage")
    return str(s).strip().lower() if s is not None else ""


def _extractor_existing_confidence(match_conf: float | None, conf_word: str, source_stage: str) -> float:
    if match_conf is not None:
        base = 0.52 + 0.38 * clamp01(match_conf)
    else:
        base = 0.74
    if conf_word == "high":
        base = min(0.93, base + 0.07)
    elif conf_word == "medium":
        base = min(0.9, base + 0.03)
    if source_stage in ("lexical", "clause") and match_conf is not None and match_conf >= 0.45:
        base = min(0.93, base + 0.04)
    return round(clamp01(base), 2)


def _extraction_signal_existing(
    candidate: Mapping[str, Any],
    staged_section: str | None,
    index: dict[tuple[str, str], dict[str, str]],
    _existing: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Meeting extraction already surfaces likely duplicates (existing*MatchId, initiativeId, projectId).
    Honor those before generic title overlap.
    """
    if not staged_section:
        return None
    sec = staged_section.strip().lower()
    attempts: list[tuple[str, str | None]] = []

    if sec == "initiatives":
        attempts.append(
            ("initiative", _pick_candidate_str(candidate, "existingInitiativeMatchId", "existing_initiative_match_id")),
        )
    elif sec == "projects":
        attempts.append(("project", _pick_candidate_str(candidate, "existingProjectMatchId", "existing_project_match_id")))
        attempts.append(("initiative", _pick_candidate_str(candidate, "initiativeId", "initiative_id")))
        attempts.append(("initiative", _pick_candidate_str(candidate, "existingInitiativeMatchId", "existing_initiative_match_id")))
    elif sec == "tasks":
        attempts.append(("task", _pick_candidate_str(candidate, "existingTaskMatchId", "existing_task_match_id")))
        attempts.append(("project", _pick_candidate_str(candidate, "projectId", "project_id")))
        attempts.append(("project", _pick_candidate_str(candidate, "existingProjectMatchId", "existing_project_match_id")))
    elif sec == "assets":
        attempts.append(("asset", _pick_candidate_str(candidate, "existingAssetMatchId", "existing_asset_match_id")))
    elif sec == "people":
        attempts.append(("person", _pick_candidate_str(candidate, "existingPersonMatchId", "existing_person_match_id")))
    elif sec == "ideas":
        attempts.append(("idea", _pick_candidate_str(candidate, "existingIdeaMatchId", "existing_idea_match_id")))
    else:
        return None

    mc = _extract_match_confidence(candidate)
    cw = _extract_confidence_word(candidate)
    ss = _extract_source_stage(candidate)

    for etype, eid in attempts:
        if not eid:
            continue
        vid, vtitle = _row_in_catalog(etype, eid, index)
        if not vid:
            continue
        label = {"initiative": "initiative", "project": "project", "task": "task", "asset": "asset", "person": "person"}.get(
            etype, etype
        )
        return {
            "presort_bucket": "existing",
            "presort_type": None,
            "presort_confidence": _extractor_existing_confidence(mc, cw, ss),
            "presort_existing_id": vid,
            "presort_existing_title": vtitle,
            "presort_existing_type": etype,
            "presort_reason": f"extractor linked existing {label}",
            "_extractor_signal": True,
        }
    return None


def _idea_title_duplicate_existing(
    candidate: Mapping[str, Any],
    staged_section: str | None,
    existing: Mapping[str, Any] | None,
    index: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any] | None:
    if staged_section != "ideas":
        return None
    title = str(candidate.get("title") or candidate.get("text") or "").strip()
    if len(title) < 5:
        return None
    best_r, best = select_best_idea_title_sequence_match(
        title,
        list((existing or {}).get("ideas") or []),
        max_entities=MAX_ENTITIES_PER_KIND,
    )
    if not best:
        return None
    threshold = 0.58
    ss = _extract_source_stage(candidate)
    mc = _extract_match_confidence(candidate)
    if ss in ("lexical", "clause"):
        threshold = 0.52
    if mc is not None and mc >= 0.55:
        threshold = min(threshold, 0.52)
    if best_r < threshold:
        return None
    eid, itit = best
    vid, vtitle = _row_in_catalog("idea", eid, index)
    if not vid:
        return None
    return {
        "presort_bucket": "existing",
        "presort_type": None,
        "presort_confidence": presort_confidence_for_idea_title_duplicate(best_r),
        "presort_existing_id": vid,
        "presort_existing_title": vtitle or itit[:500],
        "presort_existing_type": "idea",
        "presort_reason": "idea title near-duplicate in catalog (meeting extraction heuristic)",
        "_extractor_signal": True,
    }


_PLACEHOLDER_SUMMARY = re.compile(r"^(needs\s+summary|\(none\)|none|n/a)$", re.IGNORECASE)


def _effective_candidate_blob(title: str, summary: str, evidence: str) -> str:
    """Strip UI placeholders so 'Needs summary' alone does not mark every row vague."""
    t = (title or "").strip()
    s = (summary or "").strip()
    if _PLACEHOLDER_SUMMARY.match(s):
        s = ""
    e = (evidence or "").strip()
    return f"{t} {s} {e}".strip()


def _is_vague_candidate(title: str, summary: str, evidence: str) -> bool:
    """True only for almost-empty rows; thin but titled items are not vague."""
    combined = _effective_candidate_blob(title, summary, evidence)
    if len(combined) < 10:
        return True
    words = [w for w in re.split(r"\s+", combined) if w]
    if len(words) < 2 and len(combined) < 24:
        return True
    return False


def _best_catalog_row(
    title: str,
    summary: str,
    evidence: str,
    existing: Mapping[str, Any] | None,
) -> tuple[float, tuple[str, str, str] | None]:
    """Return (best_ratio, (kind, id, title)) for ideas/initiatives/projects/tasks."""
    blob = f"{title} {summary} {evidence}".lower().strip()
    return select_best_catalog_row_match(
        blob,
        existing,
        max_entities_per_kind=MAX_ENTITIES_PER_KIND,
        include_row_text_context=True,
    )


def _heuristic_triage_core(
    title: str,
    summary: str,
    evidence: str,
    existing: Mapping[str, Any] | None,
    index: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    """Deterministic triage: thin rows → lean new; strong overlap → existing; else → new."""
    if _is_vague_candidate(title, summary, evidence):
        return {
            "presort_bucket": "new",
            "presort_type": infer_entity_type_for_heuristic_new(),
            "presort_confidence": 0.44,
            "presort_existing_id": None,
            "presort_existing_title": None,
            "presort_existing_type": None,
            "presort_reason": "minimal text — lean new (batch triage)",
            "_fallback": True,
        }

    ratio, best = _best_catalog_row(title, summary, evidence, existing)
    if best and ratio >= 0.34:
        kind, bid, btitle = best
        vid, vtitle = _validate_catalog_ref(bid, btitle, index)
        if vid:
            return {
                "presort_bucket": "existing",
                "presort_type": None,
                "presort_confidence": presort_confidence_for_catalog_existing(ratio),
                "presort_existing_id": vid,
                "presort_existing_title": (vtitle or btitle)[:500],
                "presort_existing_type": kind,
                "presort_reason": "title/summary overlap with catalog (heuristic)",
                "_fallback": True,
            }

    return {
        "presort_bucket": "new",
        "presort_type": infer_entity_type_for_heuristic_new(),
        "presort_confidence": presort_confidence_for_new_weak_overlap(ratio),
        "presort_existing_id": None,
        "presort_existing_title": None,
        "presort_existing_type": None,
        "presort_reason": "no strong catalog match — lean new (heuristic)"
        if ratio < 0.22
        else "weak catalog overlap — treat as distinct (heuristic)",
        "_fallback": True,
    }


def _normalize_triage_payload(data: dict[str, Any], index: dict[tuple[str, str], dict[str, str]]) -> dict[str, Any]:
    raw_bucket = str(data.get("presort_bucket") or "new").strip().lower()
    bucket = raw_bucket if raw_bucket in BUCKETS else "new"

    raw_type = data.get("presort_type")
    pt: str | None
    if raw_type is None or (isinstance(raw_type, str) and not str(raw_type).strip()):
        pt = None
    else:
        t = str(raw_type).strip().lower()
        pt = t if t in COARSE_TYPES else None

    conf = clamp01(data.get("presort_confidence"))
    reason = _truncate_reason(data.get("presort_reason"))

    ex_id, ex_title = _validate_catalog_ref(
        str(data.get("presort_existing_id") or "").strip() or None,
        str(data.get("presort_existing_title") or "").strip() or None,
        index,
    )
    ex_type: str | None = None

    if bucket == "existing":
        if ex_id is None:
            bucket = "new"
            ex_id, ex_title = None, None
            if pt is None:
                pt = infer_entity_type_for_heuristic_new()
            conf = max(0.5, min(conf, 0.72)) if conf else 0.55
            if not reason:
                reason = "stated existing but id not in catalog — lean new"
        else:
            if pt is not None:
                pt = None
            ex_type = _catalog_entity_type_for_id(ex_id, index)
    else:
        ex_id, ex_title = None, None

    out: dict[str, Any] = {
        "presort_bucket": bucket,
        "presort_type": pt,
        "presort_confidence": conf,
        "presort_existing_id": ex_id,
        "presort_existing_title": ex_title,
        "presort_existing_type": ex_type,
    }
    if reason:
        out["presort_reason"] = reason
    return out


def _strip_internal_triage_keys(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if not (isinstance(k, str) and k.startswith("_"))}


def _heuristic_triage_full(
    candidate: Mapping[str, Any],
    title: str,
    summary: str,
    evidence: str,
    existing: Mapping[str, Any] | None,
    index: dict[tuple[str, str], dict[str, str]],
    staged_section: str | None,
) -> dict[str, Any]:
    ex = _extraction_signal_existing(candidate, staged_section, index, existing)
    if ex:
        return _strip_internal_triage_keys(ex)
    idea = _idea_title_duplicate_existing(candidate, staged_section, existing, index)
    if idea:
        return _strip_internal_triage_keys(idea)
    return _heuristic_triage_core(title, summary, evidence, existing, index)


def _merge_extractor_over_llm_new(
    normalized: dict[str, Any],
    candidate: Mapping[str, Any],
    staged_section: str | None,
    index: dict[tuple[str, str], dict[str, str]],
    existing: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if str(normalized.get("presort_bucket") or "").lower() != "new":
        return normalized
    ex = _extraction_signal_existing(candidate, staged_section, index, existing)
    if ex:
        return {**normalized, **_strip_internal_triage_keys(ex)}
    idea = _idea_title_duplicate_existing(candidate, staged_section, existing, index)
    if idea:
        return {**normalized, **_strip_internal_triage_keys(idea)}
    return normalized


def _collapse_excess_unsure(
    normalized: dict[str, Any],
    candidate: Mapping[str, Any],
    title: str,
    summary: str,
    evidence: str,
    existing: Mapping[str, Any] | None,
    index: dict[tuple[str, str], dict[str, str]],
    staged_section: str | None = None,
) -> dict[str, Any]:
    """Model often returns unsure; always fold to existing/new for batch usefulness."""
    if normalized.get("presort_bucket") != "unsure":
        return normalized
    if _is_vague_candidate(title, summary, evidence):
        return {
            **normalized,
            "presort_bucket": "new",
            "presort_type": normalized.get("presort_type") or infer_entity_type_for_heuristic_new(),
            "presort_confidence": max(0.42, min(0.55, float(normalized.get("presort_confidence") or 0.46))),
            "presort_existing_id": None,
            "presort_existing_title": None,
            "presort_existing_type": None,
            "presort_reason": "model unsure; thin row — lean new",
        }

    h = _heuristic_triage_full(candidate, title, summary, evidence, existing, index, staged_section)
    merged = {**normalized}
    merged["presort_bucket"] = h["presort_bucket"]
    merged["presort_type"] = h.get("presort_type")
    merged["presort_confidence"] = h.get("presort_confidence", merged.get("presort_confidence"))
    merged["presort_existing_id"] = h.get("presort_existing_id")
    merged["presort_existing_title"] = h.get("presort_existing_title")
    merged["presort_existing_type"] = h.get("presort_existing_type")
    hr = h.get("presort_reason")
    merged["presort_reason"] = hr or "adjusted from model unsure (heuristic lean)"
    return merged


def suggest_candidate_presort_triage(
    candidate: Mapping[str, Any],
    existing_entities: Mapping[str, Any] | None,
    context: str | None,
    *,
    user_id: str | None,
    use_execution_seam: bool,
    exec_meta: Mapping[str, Any] | None = None,
    staged_section: str | None = None,
) -> dict[str, Any]:
    title = str(candidate.get("title") or candidate.get("text") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    evidence = str(
        candidate.get("evidence_quote") or candidate.get("evidence") or candidate.get("sourceExcerpt") or ""
    ).strip()

    catalog, index = _build_catalog(existing_entities)
    ctx = (context or "").strip()[:1200] or "(none)"

    def _finish(result: dict[str, Any]) -> dict[str, Any]:
        mu = (exec_meta or {}).get("model_used")
        pu = (exec_meta or {}).get("provider_used")
        if mu is not None:
            result["model_used"] = mu
        if pu is not None:
            result["provider_used"] = pu
        return result

    early_ex = _extraction_signal_existing(candidate, staged_section, index, existing_entities)
    if early_ex:
        return _finish(_strip_internal_triage_keys(early_ex))
    early_idea = _idea_title_duplicate_existing(candidate, staged_section, existing_entities, index)
    if early_idea:
        return _finish(_strip_internal_triage_keys(early_idea))

    from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id, principal_for_vision_execution_user
    from local_ai.vision_execution.llm_seam import ve_eval_provider_shim

    principal = principal_for_vision_execution_user(user_id) if user_id else execution_principal_from_legacy_user_id(None)
    provider = ve_eval_provider_shim(principal, use_execution_seam=use_execution_seam)

    prompt = TRIAGE_PROMPT.format(
        catalog=catalog,
        context=ctx,
        title=title[:400] or "(untitled)",
        summary=summary[:1200] or "(none)",
        evidence=evidence[:800] or "(none)",
    )

    def _heuristic_fallback() -> dict[str, Any]:
        return _heuristic_triage_full(
            candidate, title, summary, evidence, existing_entities, index, staged_section
        )

    try:
        raw = provider.generate(prompt, timeout=28)
    except Exception as e:
        logger.warning("[candidate-presort-triage] generate failed: %s", e)
        out = _heuristic_fallback()
        out["error"] = str(e)[:300]
        return _finish(out)

    if not raw or not isinstance(raw, str):
        return _finish(_heuristic_fallback())

    data = _parse_llm_json(raw)
    if not isinstance(data, dict):
        return _finish(_heuristic_fallback())

    try:
        normalized = _normalize_triage_payload(data, index)
        normalized = _collapse_excess_unsure(
            normalized, candidate, title, summary, evidence, existing_entities, index, staged_section
        )
    except Exception:
        return _finish(_heuristic_fallback())

    normalized = _merge_extractor_over_llm_new(
        normalized, candidate, staged_section, index, existing_entities
    )
    normalized = _guard_no_trailing_unsure(
        normalized, candidate, title, summary, evidence, existing_entities, index, staged_section
    )
    return _finish(normalized)


def _guard_no_trailing_unsure(
    normalized: dict[str, Any],
    candidate: Mapping[str, Any],
    title: str,
    summary: str,
    evidence: str,
    existing: Mapping[str, Any] | None,
    index: dict[tuple[str, str], dict[str, str]],
    staged_section: str | None = None,
) -> dict[str, Any]:
    if normalized.get("presort_bucket") != "unsure":
        return normalized
    h = _heuristic_triage_full(candidate, title, summary, evidence, existing, index, staged_section)
    out = {
        **normalized,
        "presort_bucket": h["presort_bucket"],
        "presort_type": h.get("presort_type"),
        "presort_confidence": h.get("presort_confidence"),
        "presort_existing_id": h.get("presort_existing_id"),
        "presort_existing_title": h.get("presort_existing_title"),
        "presort_existing_type": h.get("presort_existing_type"),
    }
    if h.get("presort_reason"):
        out["presort_reason"] = h["presort_reason"]
    return out


def heuristic_presort_only(
    candidate: Mapping[str, Any],
    existing_entities: Mapping[str, Any] | None,
    *,
    staged_section: str | None = None,
) -> dict[str, Any]:
    """No LLM — extractor-linked ids first, then title/catalog overlap. Used when execution is blocked."""
    title = str(candidate.get("title") or candidate.get("text") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    evidence = str(
        candidate.get("evidence_quote") or candidate.get("evidence") or candidate.get("sourceExcerpt") or ""
    ).strip()
    _, index = _build_catalog(existing_entities)
    return _heuristic_triage_full(
        candidate, title, summary, evidence, existing_entities, index, staged_section
    )
