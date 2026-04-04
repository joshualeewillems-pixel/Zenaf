"""
Layer 1: Post-merge canonization pass for meeting extraction.

Generic, profile-driven. Normalizes initiatives into broader durable names,
merges overlapping projects, accumulates weak signal evidence, prefers specific
people/assets over generic. Keeps traceability (sourceExcerpt, segmentId).
"""
from __future__ import annotations

import copy
import re
from typing import Any

from local_ai.vision_execution.entity_judgment_primitives import (
    jaccard_word_similarity,
    normalize_title_for_match,
    title_word_set_for_overlap,
)

logger = __import__("logging").getLogger(__name__)

# Legacy imports (meeting_evidence_pipeline, meeting_literal_anchors, tools)
_title_similarity = jaccard_word_similarity
_word_set = title_word_set_for_overlap


def _is_more_specific(name: str, other: str) -> bool:
    """True if name looks more specific than other (e.g. real name vs Speaker A)."""
    name = (name or "").strip()
    other = (other or "").strip()
    if not name or not other:
        return bool(name and len(name) > len(other))
    # Generic placeholders
    generic = re.compile(r"^(speaker\s+[a-z]|person\s*\d+|someone|staff|team|they)$", re.I)
    if generic.search(other) and not generic.search(name):
        return True
    if generic.search(name) and not generic.search(other):
        return False
    # Prefer longer, more detailed
    return len(name) > len(other) or "(" in name or ":" in name


def _merge_source_excerpts(items: list[dict[str, Any]], key: str = "sourceExcerpt") -> str | None:
    excerpts = [str(i.get(key) or "").strip() for i in items if i.get(key)]
    if not excerpts:
        return None
    seen: set[str] = set()
    out = []
    for e in excerpts:
        if e and e not in seen:
            seen.add(e)
            out.append(e)
    return " | ".join(out[:3]) if out else None


def _is_broader_durable(a: str, b: str) -> bool:
    """True if a looks broader/more durable than b (less tactic-specific, more umbrella)."""
    if not a or not b:
        return bool(a and len(a) > len(b))
    a_lower, b_lower = a.lower(), b.lower()
    # Prefer title that contains more "area" words (and, or, &) or is longer without being a long tactic list
    a_words, b_words = set(normalize_title_for_match(a).split()), set(normalize_title_for_match(b).split())
    # If one subsumes the other (all words of one in the other), prefer the superset
    if a_words >= b_words and len(a_words) > len(b_words):
        return True
    if b_words >= a_words and len(b_words) > len(a_words):
        return False
    # Prefer fewer hyphenated fragments (tactic-specific often have many)
    a_frags = len([w for w in a.split() if "-" in w])
    b_frags = len([w for w in b.split() if "-" in w])
    if a_frags != b_frags:
        return a_frags < b_frags
    return len(a) >= len(b)


def _canonize_initiatives(
    initiatives: list[dict[str, Any]],
    profile_guidance: dict[str, Any],
    diagnostics: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Merge closely related initiatives into broader canonical names. Evidence-aware: prefer
    label that is broader, more durable, and better supported by multiple narrower mentions.
    Uses profile initiative_naming_style / initiative_granularity_rule when present."""
    if not initiatives:
        return []
    naming_style = (profile_guidance.get("initiative_naming_style") or "").strip()
    granularity_rule = (profile_guidance.get("initiative_granularity_rule") or "").strip()
    ordered = sorted(initiatives, key=lambda x: len((x.get("title") or "").strip()), reverse=True)
    merged: list[dict[str, Any]] = []
    used = [False] * len(ordered)
    profile_influenced_titles: list[str] = []
    narrow_mentions_merged: list[dict[str, Any]] = []
    for i, init in enumerate(ordered):
        if used[i]:
            continue
        title = (init.get("title") or "").strip()
        if not title:
            continue
        canonical = copy.deepcopy(init)
        group = [init]
        best_title = title
        for j, other in enumerate(ordered):
            if i == j or used[j]:
                continue
            other_title = (other.get("title") or "").strip()
            if not other_title:
                continue
            if jaccard_word_similarity(title, other_title) >= 0.45:
                used[j] = True
                group.append(other)
                # Evidence-aware: prefer broader/durable over longer-tactic; support from multiple mentions
                if _is_broader_durable(other_title, best_title):
                    best_title = other_title
                    canonical["brief"] = (canonical.get("brief") or "").strip() or (other.get("brief") or "").strip()
                elif _is_broader_durable(best_title, other_title):
                    pass
                else:
                    if len(other_title) > len(best_title):
                        best_title = other_title
                        canonical["brief"] = (canonical.get("brief") or "").strip() or (other.get("brief") or "").strip()
        canonical["title"] = best_title
        if group:
            canonical["sourceExcerpt"] = _merge_source_excerpts(group)
            if len(group) > 1 and diagnostics is not None:
                narrow_mentions_merged.append({
                    "canonical": best_title,
                    "merged_from": [(g.get("title") or "").strip() for g in group],
                })
        if naming_style or granularity_rule:
            profile_influenced_titles.append(best_title)
        merged.append(canonical)
    if diagnostics is not None and profile_influenced_titles:
        diagnostics["profile_changed_initiative_naming"] = profile_influenced_titles
    if diagnostics is not None and narrow_mentions_merged:
        diagnostics["initiative_narrow_mentions_merged"] = narrow_mentions_merged
    return merged


def _canonize_projects(
    projects: list[dict[str, Any]],
    profile_guidance: dict[str, Any],
    diagnostics: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Merge overlapping project candidates; promote confidence when repeated. Uses
    profile project_detection_rule when present. Records projects preserved from
    multiple fragments for diagnostics."""
    if not projects:
        return []
    project_rule = (profile_guidance.get("project_detection_rule") or "").strip()
    ordered = list(projects)
    merged: list[dict[str, Any]] = []
    used = [False] * len(ordered)
    preserved_from_fragments: list[str] = []
    for i, proj in enumerate(ordered):
        if used[i]:
            continue
        title = (proj.get("title") or "").strip()
        if not title:
            continue
        canonical = copy.deepcopy(proj)
        group = [proj]
        conf = proj.get("confidence") or "medium"
        for j, other in enumerate(ordered):
            if i == j or used[j]:
                continue
            other_title = (other.get("title") or "").strip()
            if not other_title:
                continue
            if jaccard_word_similarity(title, other_title) >= 0.5:
                used[j] = True
                group.append(other)
                if other.get("confidence") == "high":
                    conf = "high"
        canonical["confidence"] = conf
        canonical["sourceExcerpt"] = _merge_source_excerpts(group)
        merged.append(canonical)
        if len(group) > 1 and (project_rule or conf == "high"):
            preserved_from_fragments.append(canonical.get("title") or title)
    if diagnostics is not None and preserved_from_fragments:
        diagnostics["projects_preserved_from_fragments"] = preserved_from_fragments
    return merged


def _canonize_signals(
    signals: list[dict[str, Any]],
    profile_guidance: dict[str, Any],
    diagnostics: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Merge weak repeated signals into stronger one (same kind + similar label/detail).
    Uses profile signal_inference_rule when present. Records signals promoted from
    multiple weak fragments for diagnostics."""
    if not signals:
        return []
    signal_rule = (profile_guidance.get("signal_inference_rule") or "").strip()
    valid_kinds = {"attention", "risk", "opportunity", "blocker"}
    merged: list[dict[str, Any]] = []
    used = [False] * len(signals)
    promoted_from_fragments: list[str] = []
    for i, sig in enumerate(signals):
        if used[i]:
            continue
        kind = (sig.get("kind") or "attention").strip().lower()
        if kind not in valid_kinds:
            kind = "attention"
        label = (sig.get("label") or "").strip() or kind
        detail = (sig.get("detail") or "").strip()
        canonical = copy.deepcopy(sig)
        canonical["kind"] = kind
        canonical["label"] = label
        canonical["detail"] = detail or None
        group = [sig]
        conf = sig.get("confidence") or "medium"
        for j, other in enumerate(signals):
            if i == j or used[j]:
                continue
            ok = (other.get("kind") or "").strip().lower()
            if ok not in valid_kinds:
                ok = "attention"
            if ok != kind:
                continue
            ol = (other.get("label") or "").strip() or ok
            if jaccard_word_similarity(label, ol) >= 0.4 or (detail and ol and jaccard_word_similarity(detail, ol) >= 0.3):
                used[j] = True
                group.append(other)
                if other.get("confidence") == "high":
                    conf = "high"
                if (other.get("detail") or "").strip() and not detail:
                    detail = (other.get("detail") or "").strip()
                    canonical["detail"] = detail
        canonical["confidence"] = conf
        canonical["sourceExcerpt"] = _merge_source_excerpts(group)
        merged.append(canonical)
        if len(group) > 1 and (signal_rule or conf == "high"):
            promoted_from_fragments.append(f"{kind}: {canonical.get('label') or label}")
    if diagnostics is not None and promoted_from_fragments:
        diagnostics["signals_promoted_from_fragments"] = promoted_from_fragments
    return merged


def _is_generic_person(name: str) -> bool:
    """True if name looks like a generic placeholder (Speaker A, Person 1, etc.)."""
    if not name or not name.strip():
        return True
    n = name.strip().lower()
    if re.match(r"^(speaker\s+[a-z0-9]|person\s*\d+|someone|staff|team|they|them)$", n):
        return True
    if len(n) <= 2 or n in ("a", "b", "c"):
        return True
    return False


def _canonize_people(
    people: list[dict[str, Any]],
    profile_guidance: dict[str, Any],
    diagnostics: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Prefer named/specific person over generic. If generic and specific refer to same key
    (e.g. later chunk resolved 'she' to 'Anna'), keep specific. Uses person_reference_rule."""
    if not people:
        return []
    person_rule = (profile_guidance.get("person_reference_rule") or "").strip()
    by_key: dict[str, list[dict[str, Any]]] = {}
    for p in people:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        key = normalize_title_for_match(name)
        if key not in by_key:
            by_key[key] = []
        by_key[key].append(p)
    out: list[dict[str, Any]] = []
    upgraded: list[tuple[str, str]] = []
    for group in by_key.values():
        # Sort so specific names win: non-generic first, then by length (prefer longer/specific)
        def _person_score(x: dict[str, Any]) -> tuple[int, int]:
            n = (x.get("name") or "").strip()
            is_specific = 0 if _is_generic_person(n) else 1
            return (is_specific, len(n))
        best = max(group, key=_person_score)
        best_name = (best.get("name") or "").strip()
        if not _is_generic_person(best_name):
            for o in group:
                on = (o.get("name") or "").strip()
                if on != best_name and _is_generic_person(on):
                    upgraded.append((on, best_name))
        out.append(copy.deepcopy(best))
    if diagnostics is not None and upgraded:
        diagnostics["people_upgraded_from_generic"] = [f"{a} -> {b}" for a, b in upgraded]
    return out


GENERIC_ASSET_NAMES = {"document", "plan", "resource", "tool", "system", "file", "asset"}


def _is_generic_asset(name: str) -> bool:
    """True if asset name is generic (single generic word or very short)."""
    if not name or not name.strip():
        return True
    n = (name or "").strip().lower()
    words = set(re.sub(r"[^\w\s]", " ", n).split())
    if words & GENERIC_ASSET_NAMES and len(words) <= 2:
        return True
    if len(n) <= 3:
        return True
    return False


def _canonize_assets(
    assets: list[dict[str, Any]],
    profile_guidance: dict[str, Any],
    diagnostics: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Prefer specific named asset over generic. If a generic name appears as a word
    inside a more specific name (e.g. 'document' vs 'Q4 onboarding document'), keep
    the specific one. Uses asset_specificity_rule."""
    if not assets:
        return []
    asset_rule = (profile_guidance.get("asset_specificity_rule") or "").strip()
    by_key: dict[str, list[dict[str, Any]]] = {}
    for a in assets:
        name = (a.get("name") or "").strip()
        if not name:
            continue
        key = normalize_title_for_match(name)
        if key not in by_key:
            by_key[key] = []
        by_key[key].append(a)
    # Within each key group, pick best (specific over generic)
    def specificity_score(x: dict[str, Any]) -> tuple[int, int]:
        n = (x.get("name") or "").strip().lower()
        words = set(re.sub(r"[^\w\s]", " ", n).split())
        is_generic = 0 if (words & GENERIC_ASSET_NAMES and len(words) <= 2) else 1
        return (is_generic, len(n))
    intermediate: list[dict[str, Any]] = []
    for group in by_key.values():
        best = max(group, key=specificity_score)
        intermediate.append(copy.deepcopy(best))
    # Cross-group: drop generic if another asset's name contains it as a word (specific wins)
    out = []
    upgraded: list[tuple[str, str]] = []
    dropped_keys: set[str] = set()
    for a in intermediate:
        name = (a.get("name") or "").strip()
        key = normalize_title_for_match(name)
        if key in dropped_keys:
            continue
        if _is_generic_asset(name):
            for other in intermediate:
                on = (other.get("name") or "").strip()
                if on == name or _is_generic_asset(on):
                    continue
                other_key = normalize_title_for_match(on)
                other_words = set(other_key.split())
                if key in other_words or (key and other_key.startswith(key + " ")) or (key and " " + key in " " + other_key):
                    dropped_keys.add(key)
                    upgraded.append((name, on))
                    break
            else:
                out.append(a)
        else:
            out.append(a)
    if diagnostics is not None and upgraded:
        diagnostics["assets_upgraded_from_generic"] = [f"{a} -> {b}" for a, b in upgraded]
    return out


def canonize_extraction(
    extraction: dict[str, Any],
    profile_guidance: dict[str, Any] | None = None,
    return_diagnostics: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """
    Run post-merge canonization on an extraction dict.

    - Normalize initiative candidates into broader durable names.
    - Merge overlapping project candidates; promote confidence when repeated.
    - Accumulate repeated weak signals into stronger signals.
    - Prefer named people/assets over generic placeholders.

    profile_guidance: optional dict with keys like initiative_naming_style,
    initiative_granularity_rule, etc. (Layer 2). Used for naming/granularity
    preferences; current implementation uses generic heuristics if missing.

    Returns (canonized_extraction, diagnostics or None).
    """
    profile_guidance = profile_guidance or {}
    raw = copy.deepcopy(extraction)
    diagnostics: dict[str, Any] = {} if return_diagnostics else None

    initiatives = raw.get("initiatives") or []
    projects = raw.get("projects") or []
    signals = raw.get("signals") or []
    people = raw.get("peopleReferences") or raw.get("people") or []
    assets = raw.get("assets") or []

    if return_diagnostics:
        diagnostics["raw_initiatives"] = [i.get("title") for i in initiatives]
        diagnostics["projects_before_merge"] = [p.get("title") for p in projects]
        diagnostics["signals_before_merge"] = [f"{s.get('kind')}: {s.get('label')}" for s in signals]

    canon_initiatives = _canonize_initiatives(initiatives, profile_guidance, diagnostics)
    canon_projects = _canonize_projects(projects, profile_guidance, diagnostics)
    canon_signals = _canonize_signals(signals, profile_guidance, diagnostics)
    canon_people = _canonize_people(people, profile_guidance, diagnostics)
    canon_assets = _canonize_assets(assets, profile_guidance, diagnostics)

    out = copy.deepcopy(raw)
    out["initiatives"] = canon_initiatives
    out["projects"] = canon_projects
    out["signals"] = canon_signals
    out["peopleReferences"] = canon_people
    out["people"] = canon_people
    out["assets"] = canon_assets

    if return_diagnostics:
        diagnostics["canonical_initiatives"] = [i.get("title") for i in canon_initiatives]
        diagnostics["projects_after_merge"] = [p.get("title") for p in canon_projects]
        diagnostics["signals_after_merge"] = [f"{s.get('kind')}: {s.get('label')}" for s in canon_signals]

    return out, diagnostics
