"""
Pass 0: literal / near-literal anchors to known VE entities (extraction context).

Runs before segment LLM extraction. Matches are **grounding and diagnostics only**:
they never become review candidates on their own. Review rows must come from
transcript-native model extraction (or future merge into model rows).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from local_ai.vision_execution.extraction_canonization import _title_similarity, _word_set
from local_ai.vision_execution.meeting_evidence_pipeline import ExtractionCandidate

MIN_LABEL_LEN = 3
MAX_LABEL_LEN = 220
# Jaccard on word sets (extra filler words in the line are OK).
NEAR_LITERAL_JACCARD = 0.55
# Near matches below this are flagged as low-value (passing gate but weak overlap).
WEAK_NEAR_JACCARD = 0.72
MAX_ENTITIES_PER_KIND = 150
# Prevent anchor spam per chunk (cap); literal anchors never skip transcript LLM extraction.
MAX_LITERAL_ANCHORS_PER_CHUNK = 3
MAX_WORKSPACE_HINTS = MAX_ENTITIES_PER_KIND
MIN_LABEL_CHARS_FOR_QUALITY = 6
# Local window around evidence for proposition cues (chars).
_MAX_NEIGHBOR_CONTEXT_CHARS = 650

WORKSPACE_HINT_TYPE = "workspace_hint"

# Action / artifact / workflow cues in neighboring transcript text (diagnostics only).
_PROPOSITION_CUE_RE = re.compile(
    r"(?i)\b("
    r"need|needs|needed|should|must|shall|will|won't|wont|going to|gonna|let's|lets|"
    r"we're|we are|i'm|i am|they're|they are|"
    r"working on|work on|worked on|"
    r"building|build|rebuild|rebuilding|rebuilt|"
    r"updat|ship|shipping|shipped|launch|launching|launched|"
    r"fix|fixing|fixed|improv|migrat|automat|automation|integrat|integrations?|connected?|connect|"
    r"roll\s*out|priorit|decided?|decide|agreed?|agree|"
    r"next step|action item|todo|follow\s*up|followup|"
    r"dashboard|landing page|web\s*site|website|workflow|workflows|app|"
    r"program|programs|content|track|onboarding|explainer|clinic|patient|"
    r"discuss|discussed|discussion|talked|talk about|plan|planning|timeline|timelines|"
    r"proposal|proposed|deploy|implementation|deliver|visit|schedule|book|rebuild"
    r")\b"
)

GENERIC_ENTITY_LABELS = frozenset(
    {
        "video",
        "videos",
        "template",
        "templates",
        "dashboard",
        "dashboards",
        "slide",
        "slides",
        "deck",
        "doc",
        "docs",
        "document",
        "file",
        "files",
        "meeting",
        "meetings",
        "notes",
        "note",
        "report",
        "reports",
        "update",
        "updates",
        "link",
        "links",
        "email",
        "list",
        "sheet",
    }
)

_HINT_JUNK_VFL_RE = re.compile(r"vfl[a-z0-9]{5,}", re.IGNORECASE)
_PROSE_DOC_IN_HINT_RE = re.compile(
    r"\.(docx?|pdf|pptx?|xlsx?|rtf|odt|odp|ods|epub|txt)\b",
    re.IGNORECASE,
)


def _domain_hint_shape_is_noise(label: str) -> bool:
    """Drop CDN / browser-cache style mirror strings from workspace literal matching."""
    low = label.casefold().strip()
    if not low:
        return True
    if low.startswith("rs=") and len(low) >= 12:
        return True
    if "async_usersync" in low or "saved_resource" in low:
        return True
    if low == "api-surface":
        return True
    if "_files" in low and (" co-occurring" in low or "co-occurring items" in low):
        return True
    if "rs=" in low and ("/" in low or "\\" in low):
        return True
    if low.startswith("copy of ") or low.startswith("copy_of_"):
        return True
    if " — " in low or " – " in low:
        return True
    if "[" in low and "]" in low and len(low) > 22:
        return True
    if _PROSE_DOC_IN_HINT_RE.search(low):
        if low in {
            "readme.txt",
            "license.txt",
            "changelog.txt",
            "requirements.txt",
            "robots.txt",
            "security.txt",
            "todo.txt",
            "manifest.txt",
            "authors.txt",
            "contributing.txt",
            "copying.txt",
            "install.txt",
        } or (low.startswith("requirements") and low.endswith(".txt")):
            return False
        return True
    if "font-awesome" in low:
        return True
    if low.startswith(("www-main-", "www-player-", "www-onepick-")):
        return True
    if "www-" in low and ("skeleton" in low or "-webp-" in low or "webp-" in low):
        return True
    if _HINT_JUNK_VFL_RE.search(low):
        return True
    if low.count(",") >= 4 and len(low) <= 500:
        return True
    if low.count(",") >= 3 and len(low) <= 120 and re.fullmatch(r"[a-z0-9_=,\-]+", low):
        return True
    return False


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _snippet_for_substring(haystack: str, needle: str) -> str:
    """Best-effort line or bounded window around first case-insensitive occurrence."""
    if not haystack or not needle:
        return (needle or "")[:800]
    hl = haystack.lower()
    nl = needle.strip().lower()
    if not nl:
        return haystack[:800].strip()
    i = hl.find(nl)
    if i < 0:
        return haystack[:800].strip()
    line_start = haystack.rfind("\n", 0, i)
    line_start = 0 if line_start < 0 else line_start + 1
    line_end = haystack.find("\n", i)
    line_end = len(haystack) if line_end < 0 else line_end
    line = haystack[line_start:line_end].strip()
    return (line if line else haystack[max(0, i - 40) : i + len(needle) + 40])[:800]


def _neighbor_context_window(full_notes: str, evidence_quote: str, label: str, line_pool: list[str]) -> str:
    """Previous + hit + next line, joined, for local proposition heuristics."""
    raw_lines = [ln.rstrip() for ln in (full_notes or "").splitlines()]
    norm_label = (label or "").strip().lower()
    eq = (evidence_quote or "").strip()
    idx = -1
    for i, ln in enumerate(raw_lines):
        low = ln.lower()
        if norm_label and norm_label in low:
            idx = i
            break
        if eq and eq in ln:
            idx = i
            break
    if idx < 0 and line_pool:
        pool_set = {p.strip() for p in line_pool if p and len(p.strip()) >= 8}
        for i, ln in enumerate(raw_lines):
            if ln.strip() in pool_set:
                idx = i
                break
    if idx < 0:
        return re.sub(r"\s+", " ", (eq or label or "")[:_MAX_NEIGHBOR_CONTEXT_CHARS]).strip()
    start = max(0, idx - 1)
    end = min(len(raw_lines), idx + 2)
    chunk = " ".join(x.strip() for x in raw_lines[start:end] if x.strip())
    return chunk.strip()[:_MAX_NEIGHBOR_CONTEXT_CHARS]


def _window_suggests_proposition(window: str, label: str) -> bool:
    if not window or len(window.strip()) < 6:
        return False
    if not _PROPOSITION_CUE_RE.search(window):
        return False
    lab = (label or "").strip()
    if 2 <= len(lab) <= 6 and lab.isupper() and lab.isalpha():
        alnum = re.sub(r"[^\w\s]+", " ", window)
        tokens = [x for x in alnum.split() if x]
        if len(tokens) <= 1:
            return False
    return True


# Cap diagnostic payload: all anchors are listed in meta, not as review rows.
_MAX_GROUNDING_ANCHORS_IN_META = 48


def _line_candidates(text: str) -> list[str]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    out: list[str] = []
    for ln in lines:
        if len(ln) < 8 or len(ln) > 600:
            continue
        out.append(ln)
    return out


def _stable_workspace_hint_id(label: str) -> str:
    """Opaque id for possibleMatches; not a VE entity id."""
    raw = _norm_ws(label)
    if not raw:
        return "wh:empty"
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:48]
    if slug:
        return f"wh:{slug}"
    digest = hashlib.sha256(label.strip().encode("utf-8")).hexdigest()[:16]
    return f"wh:{digest}"


def _iter_domain_hints(workspace_packet: dict[str, Any] | None) -> list[tuple[str, str]]:
    """(hint_id, label) from prebuilt packet only — no filesystem access."""
    if not workspace_packet or not isinstance(workspace_packet, dict):
        return []
    lists: list[list[Any]] = []
    for key in ("literalAnchors", "literal_anchors", "domainHints", "domain_hints"):
        raw = workspace_packet.get(key)
        if isinstance(raw, list) and raw:
            lists.append(raw)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in lists:
        for item in raw:
            lab = str(item).strip()
            if len(lab) < MIN_LABEL_LEN or len(lab) > MAX_LABEL_LEN:
                continue
            if _label_is_generic(lab) or _domain_hint_shape_is_noise(lab):
                continue
            key = lab.lower()
            if key in seen:
                continue
            seen.add(key)
            hid = _stable_workspace_hint_id(lab)
            out.append((hid, lab))
            if len(out) >= MAX_WORKSPACE_HINTS:
                return out
    return out


def _iter_labeled_entities(context: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(entity_type, entity_id, label)"""
    out: list[tuple[str, str, str]] = []
    if not context or not isinstance(context, dict):
        return out

    def drain(lst: Any, typ: str, id_key: str, label_key: str) -> None:
        if not isinstance(lst, list):
            return
        for ent in lst[:MAX_ENTITIES_PER_KIND]:
            if not isinstance(ent, dict):
                continue
            eid = str(ent.get(id_key) or "").strip()
            lab = str(ent.get(label_key) or "").strip()
            if not eid or not lab:
                continue
            if len(lab) < MIN_LABEL_LEN or len(lab) > MAX_LABEL_LEN:
                continue
            out.append((typ, eid, lab))

    drain(context.get("initiatives"), "initiative", "id", "title")
    drain(context.get("projects"), "project", "id", "title")
    drain(context.get("tasks"), "task", "id", "title")
    drain(context.get("assets"), "asset", "id", "name")
    drain(context.get("people"), "person", "id", "name")
    return out


def _label_is_generic(label: str) -> bool:
    t = _norm_ws(label)
    if not t:
        return True
    if t in GENERIC_ENTITY_LABELS:
        return True
    parts = t.split()
    if len(parts) == 1 and parts[0] in GENERIC_ENTITY_LABELS:
        return True
    return False


def _anchor_low_value(
    label: str,
    *,
    exact: bool,
    via_subset: bool,
    score: float,
) -> bool:
    """Heuristic signal only — does not filter anchors."""
    lab = label.strip()
    if len(lab) < MIN_LABEL_CHARS_FOR_QUALITY:
        return True
    if _label_is_generic(label):
        return True
    if not exact and not via_subset and score < WEAK_NEAR_JACCARD:
        return True
    return False


@dataclass
class _AnchorDraft:
    typ: str
    eid: str
    label: str
    exact: bool
    via_subset: bool
    score: float
    evidence_quote: str
    low_value: bool
    workspace_mirror: bool


def _draft_for_label(
    typ: str,
    eid: str,
    label: str,
    *,
    norm_doc: str,
    lines: list[str],
    full_notes: str,
    workspace_mirror: bool,
) -> _AnchorDraft | None:
    norm_label = _norm_ws(label)
    if len(norm_label) < MIN_LABEL_LEN:
        return None

    exact = norm_label in norm_doc
    evidence_quote = ""
    via_subset = False
    best_sc = 0.0

    if exact:
        evidence_quote = _snippet_for_substring(full_notes, label)
        best_sc = 1.0
    else:
        wb = _word_set(label)
        best_line = ""
        winner_subset = False
        for ln in lines:
            wa = _word_set(ln)
            if len(wb) >= 2 and wb and wb <= wa:
                sc = 1.0
                wsub = True
            else:
                sc = _title_similarity(ln, label)
                wsub = False
            if sc > best_sc:
                best_sc = sc
                best_line = ln
                winner_subset = wsub
        if best_sc < NEAR_LITERAL_JACCARD:
            return None
        evidence_quote = best_line[:800]
        via_subset = winner_subset

    low_v = _anchor_low_value(label, exact=exact, via_subset=via_subset, score=best_sc)
    return _AnchorDraft(
        typ=typ,
        eid=eid,
        label=label,
        exact=exact,
        via_subset=via_subset,
        score=best_sc,
        evidence_quote=evidence_quote[:800],
        low_value=low_v,
        workspace_mirror=workspace_mirror,
    )


def literal_anchor_candidates_for_chunk(
    notes: str,
    context: dict[str, Any] | None,
    *,
    workspace_packet: dict[str, Any] | None = None,
    segment_id: str = "literal-anchor",
) -> tuple[list[ExtractionCandidate], dict[str, Any]]:
    """
    Scan notes for exact or near-exact references to context entities / workspace hints.

    Returns **no** ``ExtractionCandidate`` rows: literal/workspace matches are recorded only in
    ``meta`` (``grounding_only_anchors``) for matching, diagnostics, and future merge hints.
    Review candidates must come from segment LLM extraction.

    ``skip_llm`` in meta is always False: literal anchors do not replace segment LLM calls.
    """
    _ = segment_id
    t = (notes or "").strip()
    meta: dict[str, Any] = {
        "count": 0,
        "exact_hits": 0,
        "near_hits": 0,
        "skip_llm": False,
        "low_value_literal_anchor": False,
        "anchors_capped": False,
        "raw_anchor_count": 0,
        "grounding_only_anchors": [],
        "grounding_only_count": 0,
        "promoted_literal_count": 0,
        "literal_review_promotion_disabled": True,
    }
    if len(t) < 4:
        return [], meta

    entities = _iter_labeled_entities(context or {})
    workspace_pairs = _iter_domain_hints(workspace_packet)

    if not entities and not workspace_pairs:
        return [], meta

    norm_doc = _norm_ws(t)
    seen_ids: set[tuple[str, str]] = set()
    drafts: list[_AnchorDraft] = []
    lines = _line_candidates(t)

    for typ, eid, label in entities:
        key = (typ, eid)
        if key in seen_ids:
            continue
        d = _draft_for_label(
            typ,
            eid,
            label,
            norm_doc=norm_doc,
            lines=lines,
            full_notes=t,
            workspace_mirror=False,
        )
        if d is None:
            continue
        drafts.append(d)
        seen_ids.add(key)

    for hid, label in workspace_pairs:
        key = (WORKSPACE_HINT_TYPE, hid)
        if key in seen_ids:
            continue
        d = _draft_for_label(
            WORKSPACE_HINT_TYPE,
            hid,
            label,
            norm_doc=norm_doc,
            lines=lines,
            full_notes=t,
            workspace_mirror=True,
        )
        if d is None:
            continue
        drafts.append(d)
        seen_ids.add(key)

    meta["raw_anchor_count"] = len(drafts)
    if len(drafts) > MAX_LITERAL_ANCHORS_PER_CHUNK:
        meta["anchors_capped"] = True
    drafts_sorted = sorted(drafts, key=lambda d: (-int(d.exact), -d.score, -len(d.label)))

    grounding_only: list[dict[str, Any]] = []

    for d in drafts_sorted:
        win = _neighbor_context_window(t, d.evidence_quote, d.label, lines)
        if d.workspace_mirror:
            pm = [{"id": d.eid, "type": WORKSPACE_HINT_TYPE, "similarity": round(float(d.score), 3)}]
        else:
            pm = [{"id": d.eid, "type": d.typ, "similarity": round(float(d.score), 3)}]
        grounding_only.append(
            {
                "label": d.label,
                "workspaceMirror": d.workspace_mirror,
                "entityType": None if d.workspace_mirror else d.typ,
                "entityId": d.eid,
                "evidenceQuote": (d.evidence_quote or "")[:400],
                "neighborWindowPreview": (win or "")[:400] if win else None,
                "neighborHasActionCues": _window_suggests_proposition(win, d.label),
                "exactMatch": d.exact,
                "matchScore": round(float(d.score), 4),
                "lowValueHeuristic": d.low_value,
                "possibleMatches": pm,
            }
        )

    meta["grounding_only_anchors"] = grounding_only[:_MAX_GROUNDING_ANCHORS_IN_META]
    meta["grounding_only_count"] = len(grounding_only)
    meta["promoted_literal_count"] = 0
    meta["exact_hits"] = sum(1 for d in drafts_sorted if d.exact)
    meta["near_hits"] = sum(1 for d in drafts_sorted if not d.exact)
    meta["count"] = 0
    meta["skip_llm"] = False
    meta["low_value_literal_anchor"] = any(d.low_value for d in drafts_sorted)
    return [], meta

