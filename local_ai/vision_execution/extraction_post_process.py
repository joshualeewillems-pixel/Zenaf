"""
Unified post-processing after meeting extraction (discovery): alignment → canonization →
consolidation → document-level budget.

Ports deterministic logic from frontend meeting-intelligence (consolidation.ts, extractionBudget.ts)
so server responses match client-shaped output without duplicate passes on single-call paths.
"""

from __future__ import annotations

import copy
import math
import re
import secrets
from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeVar

from local_ai.vision_execution.extraction_canonization import canonize_extraction
from local_ai.vision_execution.meeting_evidence_pipeline import apply_context_entity_links

Confidence = Literal["high", "medium", "low"] | None

_STOP = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "for",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "we",
        "our",
        "you",
        "your",
        "they",
        "their",
        "i",
        "me",
        "my",
    }
)


def normalize_candidate_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]+", " ", (s or "").lower())).strip()


def _token_set(norm: str) -> set[str]:
    out: set[str] = set()
    for p in norm.split():
        if len(p) < 2 or p in _STOP:
            continue
        out.add(p)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    inter = sum(1 for t in a if t in b)
    union = len(a) + len(b) - inter
    return 0.0 if union == 0 else inter / union


def should_cluster_by_title(na: str, nb: str) -> bool:
    if not na or not nb:
        return False
    if na == nb:
        return True
    min_len = min(len(na), len(nb))
    longer, shorter = (na, nb) if len(na) >= len(nb) else (nb, na)
    if len(shorter) >= 4 and shorter in longer:
        return True
    ta, tb = _token_set(na), _token_set(nb)
    jac = _jaccard(ta, tb)
    if jac >= 0.55:
        return True
    sig_shared = [t for t in ta if len(t) >= 4 and t in tb]
    if len(sig_shared) >= 1 and jac >= 0.35:
        return True
    if len(sig_shared) >= 2 and jac >= 0.25:
        return True
    if min_len >= 6 and jac >= 0.45:
        return True
    return False


class _DSU:
    __slots__ = ("p",)

    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, i: int) -> int:
        if self.p[i] != i:
            self.p[i] = self.find(self.p[i])
        return self.p[i]

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _max_confidence(cs: list[Confidence]) -> Confidence:
    order = ("high", "medium", "low")
    best: Confidence = None
    bi = -1
    for c in cs:
        if not c:
            continue
        try:
            i = order.index(c)
        except ValueError:
            continue
        if i > bi:
            bi = i
            best = c
    return best


def _unique_non_empty(lines: list[str | None]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in lines:
        s = (raw or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def _chunk_count_for(items: list[dict[str, Any]]) -> int:
    return len({str(i.get("segmentId") or "") for i in items if i.get("segmentId")})


def _anchor_roles_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ra = str(a.get("anchorRole") or "").strip()
    rb = str(b.get("anchorRole") or "").strip()
    if not ra or not rb:
        return True
    if ra == "general" or rb == "general":
        return True
    return ra == rb


def _merged_anchor_role(items: list[dict[str, Any]]) -> str | None:
    rs = [str(i.get("anchorRole") or "").strip() for i in items]
    rs = [x for x in rs if x]
    if not rs:
        return None
    u = set(rs)
    if len(u) == 1:
        return rs[0]
    return "general"


def _new_merge_id() -> str:
    return f"ext-{secrets.token_hex(6)}"


def _merge_meta(group: list[dict[str, Any]]) -> dict[str, Any]:
    cc = _chunk_count_for(group)
    return {"mergedCount": len(group), "chunkCount": cc, "mentionCount": len(group)}


T = TypeVar("T", bound=dict[str, Any])


def _cluster_indices(items: list[T], get_title: Callable[[T], str]) -> list[list[int]]:
    n = len(items)
    if n <= 1:
        return [[i] for i in range(n)]
    norms = [normalize_candidate_text(get_title(it)) for it in items]
    dsu = _DSU(n)
    for i in range(n):
        for j in range(i + 1, n):
            if should_cluster_by_title(norms[i], norms[j]) and _anchor_roles_compatible(items[i], items[j]):
                dsu.union(i, j)
    buckets: dict[int, list[int]] = {}
    for i in range(n):
        r = dsu.find(i)
        buckets.setdefault(r, []).append(i)
    return sorted(buckets.values(), key=lambda arr: arr[0])


def _consolidate_by_title(
    items: list[dict[str, Any]],
    get_title: Callable[[dict[str, Any]], str],
    merge_fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> list[dict[str, Any]]:
    if not items:
        return []
    clusters = _cluster_indices(items, get_title)
    out: list[dict[str, Any]] = []
    for idxs in clusters:
        group = [items[i] for i in idxs]
        out.append(group[0] if len(group) == 1 else merge_fn(group))
    return out


def _merge_ideas(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=lambda x: len(str(x.get("title") or "")), reverse=True)
    rep = copy.deepcopy(sorted_items[0])
    excerpts = _unique_non_empty([str(i.get("sourceExcerpt") or "") for i in items])
    bodies = _unique_non_empty(
        [str(i.get("description") or "") for i in items] + [str(i.get("summary") or "") for i in items]
    )
    rep["id"] = _new_merge_id()
    rep["description"] = "\n\n".join(bodies)[:8000] or rep.get("description", "")
    rep["sourceExcerpt"] = "\n\n---\n\n".join(excerpts)[:8000] or rep.get("sourceExcerpt")
    rep["confidence"] = _max_confidence([i.get("confidence") for i in items])  # type: ignore[arg-type]
    rep["consolidationMeta"] = _merge_meta(items)
    mar = _merged_anchor_role(items)
    if mar:
        rep["anchorRole"] = mar
    return rep


def _merge_initiatives(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=lambda x: len(str(x.get("title") or "")), reverse=True)
    rep = copy.deepcopy(sorted_items[0])
    excerpts = _unique_non_empty([str(i.get("sourceExcerpt") or "") for i in items])
    briefs = _unique_non_empty(
        [str(i.get("brief") or i.get("description") or "") for i in items]
    )
    notes = _unique_non_empty([str(i.get("notes") or "") for i in items])
    merged_brief = "\n\n".join(briefs)[:8000]
    rep["id"] = _new_merge_id()
    rep["brief"] = merged_brief or rep.get("brief", "")
    rep["description"] = merged_brief or rep.get("description", "")
    rep["notes"] = "\n\n".join(notes)[:4000] or rep.get("notes", "")
    rep["sourceExcerpt"] = "\n\n---\n\n".join(excerpts)[:8000] or rep.get("sourceExcerpt")
    rep["confidence"] = _max_confidence([i.get("confidence") for i in items])  # type: ignore[arg-type]
    rep["consolidationMeta"] = _merge_meta(items)
    mar = _merged_anchor_role(items)
    if mar:
        rep["anchorRole"] = mar
    return rep


def _merge_tasks(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=lambda x: len(str(x.get("title") or "")), reverse=True)
    rep = copy.deepcopy(sorted_items[0])
    excerpts = _unique_non_empty([str(i.get("sourceExcerpt") or "") for i in items])
    descs = _unique_non_empty([str(i.get("description") or "") for i in items])
    notes = _unique_non_empty([str(i.get("notes") or "") for i in items])
    rep["id"] = _new_merge_id()
    rep["description"] = "\n\n".join(descs)[:8000] or rep.get("description", "")
    rep["notes"] = "\n\n".join(notes)[:4000] or rep.get("notes", "")
    rep["sourceExcerpt"] = "\n\n---\n\n".join(excerpts)[:8000] or rep.get("sourceExcerpt")
    rep["confidence"] = _max_confidence([i.get("confidence") for i in items])  # type: ignore[arg-type]
    rep["consolidationMeta"] = _merge_meta(items)
    mar = _merged_anchor_role(items)
    if mar:
        rep["anchorRole"] = mar
    return rep


def _merge_projects(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=lambda x: len(str(x.get("title") or "")), reverse=True)
    rep = copy.deepcopy(sorted_items[0])
    excerpts = _unique_non_empty([str(i.get("sourceExcerpt") or "") for i in items])
    briefs = _unique_non_empty([str(i.get("brief") or "") for i in items])
    merged_brief = "\n\n".join(briefs)[:8000]
    rep["id"] = _new_merge_id()
    rep["brief"] = merged_brief or rep.get("brief", "")
    rep["sourceExcerpt"] = "\n\n---\n\n".join(excerpts)[:8000] or rep.get("sourceExcerpt")
    rep["confidence"] = _max_confidence([i.get("confidence") for i in items])  # type: ignore[arg-type]
    rep["consolidationMeta"] = _merge_meta(items)
    return rep


def _merge_assets(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=lambda x: len(str(x.get("name") or "")), reverse=True)
    rep = copy.deepcopy(sorted_items[0])
    excerpts = _unique_non_empty([str(i.get("sourceExcerpt") or "") for i in items])
    descs = _unique_non_empty([str(i.get("description") or "") for i in items])
    rep["id"] = _new_merge_id()
    rep["description"] = "\n\n".join(descs)[:8000] or rep.get("description", "")
    rep["sourceExcerpt"] = "\n\n---\n\n".join(excerpts)[:8000] or rep.get("sourceExcerpt")
    rep["confidence"] = _max_confidence([i.get("confidence") for i in items])  # type: ignore[arg-type]
    rep["consolidationMeta"] = _merge_meta(items)
    mar = _merged_anchor_role(items)
    if mar:
        rep["anchorRole"] = mar
    return rep


def _merge_people(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=lambda x: len(str(x.get("name") or "")), reverse=True)
    rep = copy.deepcopy(sorted_items[0])
    excerpts = _unique_non_empty([str(i.get("sourceExcerpt") or "") for i in items])
    contexts = _unique_non_empty([str(i.get("context") or "") for i in items])
    roles = _unique_non_empty([str(i.get("role") or "") for i in items])
    rep["id"] = _new_merge_id()
    rep["role"] = roles[0] if roles else rep.get("role", "")
    rep["context"] = "\n\n".join(contexts)[:8000] or rep.get("context", "")
    rep["sourceExcerpt"] = "\n\n---\n\n".join(excerpts)[:8000] or rep.get("sourceExcerpt")
    rep["confidence"] = _max_confidence([i.get("confidence") for i in items])  # type: ignore[arg-type]
    rep["consolidationMeta"] = _merge_meta(items)
    mar = _merged_anchor_role(items)
    if mar:
        rep["anchorRole"] = mar
    return rep


def _merge_signals(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=lambda x: len(str(x.get("label") or "")), reverse=True)
    rep = copy.deepcopy(sorted_items[0])
    excerpts = _unique_non_empty([str(i.get("sourceExcerpt") or "") for i in items])
    details = _unique_non_empty([str(i.get("detail") or "") for i in items])
    rep["id"] = _new_merge_id()
    rep["detail"] = "\n\n".join(details)[:8000] or rep.get("detail", "")
    rep["sourceExcerpt"] = "\n\n---\n\n".join(excerpts)[:8000] or rep.get("sourceExcerpt")
    rep["confidence"] = _max_confidence([i.get("confidence") for i in items])  # type: ignore[arg-type]
    rep["consolidationMeta"] = _merge_meta(items)
    mar = _merged_anchor_role(items)
    if mar:
        rep["anchorRole"] = mar
    return rep


def consolidate_meeting_extraction_dict(extraction: dict[str, Any]) -> dict[str, Any]:
    """Mirror of frontend ``consolidateMeetingExtraction`` (entity arrays only)."""
    out = copy.deepcopy(extraction)
    ideas = [copy.deepcopy(x) for x in (out.get("ideas") or []) if isinstance(x, dict)]
    initiatives = [copy.deepcopy(x) for x in (out.get("initiatives") or []) if isinstance(x, dict)]
    projects = [copy.deepcopy(x) for x in (out.get("projects") or []) if isinstance(x, dict)]
    tasks = [copy.deepcopy(x) for x in (out.get("tasks") or []) if isinstance(x, dict)]
    assets = [copy.deepcopy(x) for x in (out.get("assets") or []) if isinstance(x, dict)]
    people = [copy.deepcopy(x) for x in (out.get("peopleReferences") or out.get("people") or []) if isinstance(x, dict)]
    signals = [copy.deepcopy(x) for x in (out.get("signals") or []) if isinstance(x, dict)]

    out["ideas"] = _consolidate_by_title(ideas, lambda i: str(i.get("title") or ""), _merge_ideas)
    out["initiatives"] = _consolidate_by_title(
        initiatives, lambda i: str(i.get("title") or ""), _merge_initiatives
    )
    out["tasks"] = _consolidate_by_title(tasks, lambda i: str(i.get("title") or ""), _merge_tasks)
    out["projects"] = _consolidate_by_title(projects, lambda i: str(i.get("title") or ""), _merge_projects)
    out["assets"] = _consolidate_by_title(assets, lambda i: str(i.get("name") or ""), _merge_assets)
    out["peopleReferences"] = _consolidate_by_title(people, lambda i: str(i.get("name") or ""), _merge_people)
    out["people"] = out["peopleReferences"]
    out["signals"] = _consolidate_by_title(signals, lambda i: str(i.get("label") or ""), _merge_signals)
    return out


def _confidence_rank(c: Confidence) -> int:
    if c == "high":
        return 3
    if c == "medium":
        return 2
    if c == "low":
        return 1
    return 0


def _take_sorted_confidence(items: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    if len(items) <= cap:
        return items
    tagged = [
        {"item": item, "idx": idx, "r": _confidence_rank(item.get("confidence"))}  # type: ignore[arg-type]
        for idx, item in enumerate(items)
    ]
    tagged.sort(key=lambda x: (-x["r"], x["idx"]))
    kept = tagged[:cap]
    kept.sort(key=lambda x: x["idx"])
    return [x["item"] for x in kept]


def _budget_primary_buckets(
    ideas: list[dict[str, Any]],
    initiatives: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    primary_cap: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tagged: list[tuple[str, int, int, dict[str, Any]]] = []
    for idx, item in enumerate(ideas):
        tagged.append(("idea", _confidence_rank(item.get("confidence")), idx, item))  # type: ignore[arg-type]
    for idx, item in enumerate(initiatives):
        tagged.append(("initiative", _confidence_rank(item.get("confidence")), idx, item))  # type: ignore[arg-type]
    for idx, item in enumerate(projects):
        tagged.append(("project", _confidence_rank(item.get("confidence")), idx, item))  # type: ignore[arg-type]
    for idx, item in enumerate(tasks):
        tagged.append(("task", _confidence_rank(item.get("confidence")), idx, item))  # type: ignore[arg-type]
    tagged.sort(key=lambda x: (-x[1], x[0], x[2]))
    kept = tagged[:primary_cap]
    return (
        [t[3] for t in kept if t[0] == "idea"],
        [t[3] for t in kept if t[0] == "initiative"],
        [t[3] for t in kept if t[0] == "project"],
        [t[3] for t in kept if t[0] == "task"],
    )


def apply_document_level_extraction_budget_dict(
    extraction: dict[str, Any], transcript_char_length: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mirror of frontend ``applyDocumentLevelExtractionBudget``."""
    out = copy.deepcopy(extraction)
    ln = max(0, int(transcript_char_length))
    scale = min(1.35, 1.0 + ln / 140_000.0)
    primary_cap = min(40, math.ceil((10 + math.floor(ln / 16_000)) * scale))
    signal_cap = min(28, math.ceil((8 + math.floor(ln / 22_000)) * scale))
    insight_cap = min(40, math.ceil((12 + math.floor(ln / 16_000)) * scale))
    asset_cap = min(18, math.ceil(9 * scale))
    people_cap = min(18, math.ceil(9 * scale))

    ideas = [x for x in (out.get("ideas") or []) if isinstance(x, dict)]
    initiatives = [x for x in (out.get("initiatives") or []) if isinstance(x, dict)]
    projects = [x for x in (out.get("projects") or []) if isinstance(x, dict)]
    tasks = [x for x in (out.get("tasks") or []) if isinstance(x, dict)]

    bi, bini, bp, bt = _budget_primary_buckets(ideas, initiatives, projects, tasks, primary_cap)
    out["ideas"] = bi
    out["initiatives"] = bini
    out["projects"] = bp
    out["tasks"] = bt
    out["signals"] = _take_sorted_confidence([x for x in (out.get("signals") or []) if isinstance(x, dict)], signal_cap)
    out["insights"] = _take_sorted_confidence(
        [x for x in (out.get("insights") or []) if isinstance(x, dict)], insight_cap
    )
    out["assets"] = _take_sorted_confidence([x for x in (out.get("assets") or []) if isinstance(x, dict)], asset_cap)
    people_refs = [x for x in (out.get("peopleReferences") or out.get("people") or []) if isinstance(x, dict)]
    out["peopleReferences"] = _take_sorted_confidence(people_refs, people_cap)
    out["people"] = out["peopleReferences"]

    meta = {
        "transcriptCharLength": ln,
        "primaryCap": primary_cap,
        "signalCap": signal_cap,
        "insightCap": insight_cap,
        "assetCap": asset_cap,
        "peopleCap": people_cap,
    }
    return out, meta


@dataclass
class PostProcessExtractionOptions:
    """Options for :func:`post_process_extraction`."""

    profile_guidance: dict[str, Any]
    return_diagnostics: bool = False
    apply_document_budget: bool = True
    document_budget_char_length: int | None = None


def post_process_extraction(
    extraction: dict[str, Any],
    notes: str,
    context: dict[str, Any] | None,
    options: PostProcessExtractionOptions,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Run alignment → canonization → consolidation → optional document budget.

    Mutates nothing in the caller's ``extraction`` beyond what ``apply_context_entity_links`` does
    in-place on the passed dict; the returned dict is the canonizer output with consolidation/budget
    applied on copies where needed.
    """
    apply_context_entity_links(extraction, context)
    out, canon_diag = canonize_extraction(
        extraction, options.profile_guidance, return_diagnostics=options.return_diagnostics
    )
    out = consolidate_meeting_extraction_dict(out)

    pp_diag: dict[str, Any] = {
        "consolidation_applied": True,
        "document_budget_applied": False,
        "document_budget_skipped_reason": None,
    }
    budget_meta: dict[str, Any] = {}

    if options.apply_document_budget:
        doc_len = options.document_budget_char_length
        if doc_len is None:
            doc_len = len(notes or "")
        out, budget_meta = apply_document_level_extraction_budget_dict(out, doc_len)
        pp_diag["document_budget_applied"] = True
    else:
        pp_diag["document_budget_skipped_reason"] = "disabled_for_chunked_extract"

    diag_out: dict[str, Any] = {}
    if options.return_diagnostics:
        if isinstance(canon_diag, dict):
            diag_out.update(canon_diag)
        diag_out["post_process"] = pp_diag
        if budget_meta:
            diag_out["budget"] = budget_meta

    return out, diag_out


def should_skip_document_budget_for_chunked_request(routing_context: dict[str, Any] | None) -> bool:
    """When client splits a transcript into multiple extract-meeting calls, budget once after merge."""
    if not isinstance(routing_context, dict):
        return False
    return bool(routing_context.get("meetingExtractChunked"))
