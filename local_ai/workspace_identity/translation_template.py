"""
Workspace translation template: **circumstance-specific** vocabulary on top of core mirror output.

Loaded from ``translation-template.json`` beside ``snapshot.json`` (gitignored). Applied only when
building the workspace packet — scan mechanics, buffers, and junk/cache filters stay in core.

**Integration echoes elsewhere (same repo, not coupled in code yet):**

- **Brand / perspectives** — Built-in Brand perspective and ``PerspectiveAgent`` fields (purpose,
  domain, examplePhrases) are narrative “who we are”; this file is structural “what this workspace
  calls things.” Both inform extraction and council, but Brand lives in the perspectives layer;
  translation lives next to workspace identity snapshot.
- **Operator / mission brief** — Optional ``phil_brand_brief.md`` (council “Operator priorities:”);
  disable loading with ``ATRIA_OPERATOR_BRIEF_ENABLED=0``. Translation template is per-workspace
  surface grounding (domainHints / capsule), separate from that file.
- **Developmental / traces** — ``AiActionTrace``, workspace council intents, and
  ``buildDevelopmentalGuidanceContext`` capture *behavior and outcomes*; translation captures
  *stable local naming and noise*. Traces may eventually suggest template edits; template should
  not silently learn from traces without explicit user edits (see HUMAN_AI_SYMBIOSIS_DIRECTION).
- **Meeting extract** — ``_workspace_mirror_prompt_block`` consumes ``reasoningCapsule.themes``,
  ``namedPrograms``, ``tags``; structural hints merge into themes, functional mappings into tags.

Schema (``schemaVersion`` 2 on write; readers accept legacy v1-shaped files):

- ``preferredPhrases`` — show first; workspace- or domain-specific anchors.
- ``blockedPhrases`` — drop from core literals (case-insensitive). Whole-string by default; an entry
  ending with ``*`` matches any literal whose normalized string **starts with** the part before ``*``
  (e.g. ``www-main-desktop-*``). Legacy: ``blockFromMirror`` merged on read.
- ``aliases`` — JSON object mapping local variant → canonical name; applied to core literals
  before merge (deduped by canonical).
- ``alwaysAllow`` — force-include phrases not blocked (e.g. scan missed a meaningful name).
- ``functionalMappings`` — map surface phrase → functional tag(s); tags added when that surface
  appears in the final literal list. Legacy: ``functionalHints`` = unconditional tag strings.
- ``structuralHints`` — prepended into ``reasoningCapsule.themes`` (deduped, capped).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TRANSLATION_TEMPLATE_FILENAME = "translation-template.json"
# Keep in sync with snapshot.MAX_PACKET_HINTS (avoid import cycle with snapshot).
_MAX_PACKET_HINTS = 36
MAX_REASONING_TAGS = 20
# Match snapshot.build_workspace_packet_from_snapshot theme slice and meeting prompt budget.
MAX_CAPSULE_THEMES = 12


def _default_identity_dir() -> Path:
    return Path(__file__).resolve().parents[2] / ".atria" / "workspace-identity" / "v1"


def translation_template_path(base_dir: Path | None = None) -> Path:
    return (base_dir or _default_identity_dir()) / TRANSLATION_TEMPLATE_FILENAME


def read_translation_template(base_dir: Path | None = None) -> dict[str, Any]:
    """Return normalized template dict (possibly empty). Never raises for missing file."""
    path = translation_template_path(base_dir)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[workspace-identity] translation template read failed: %s", e)
        return {}
    if not isinstance(raw, dict):
        return {}
    return _normalize_template(raw)


def _str_list(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    out: list[str] = []
    for x in val:
        s = str(x).strip()
        if s:
            out.append(s)
    return out


def _merge_blocked_phrases(raw: dict[str, Any]) -> list[str]:
    merged: list[str] = []
    merged.extend(_str_list(raw.get("blockedPhrases")))
    merged.extend(_str_list(raw.get("blockFromMirror")))
    out: list[str] = []
    seen: set[str] = set()
    for x in merged:
        k = _norm_key(x)
        if k in seen:
            continue
        seen.add(k)
        out.append(x.strip())
    return out


def _aliases_forward(raw: Any) -> dict[str, str]:
    """Variant string (as authored) -> canonical display string; keys preserved for JSON round-trip."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        a = str(k).strip()
        b = str(v).strip()
        if a and b:
            out[a] = b
    return out


def _aliases_norm_to_canon(forward: dict[str, str]) -> dict[str, str]:
    return {_norm_key(k): v for k, v in forward.items()}


def _functional_mappings(val: Any) -> dict[str, list[str]]:
    if not isinstance(val, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in val.items():
        surf = str(k).strip()
        if not surf:
            continue
        tags: list[str] = []
        if isinstance(v, list):
            tags = [str(x).strip() for x in v if str(x).strip()]
        else:
            t = str(v).strip()
            if t:
                tags = [t]
        if tags:
            out[surf] = tags
    return out


def _normalize_template(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "preferredPhrases": _str_list(raw.get("preferredPhrases")),
        "blockedPhrases": _merge_blocked_phrases(raw),
        "alwaysAllow": _str_list(raw.get("alwaysAllow")),
        "aliases": _aliases_forward(raw.get("aliases")),
        "functionalMappings": _functional_mappings(raw.get("functionalMappings")),
        "functionalHints": _str_list(raw.get("functionalHints")),
        "structuralHints": _str_list(raw.get("structuralHints")),
    }


def write_translation_template(data: dict[str, Any], *, base_dir: Path | None = None) -> Path:
    """Write template JSON; creates parent dirs. Returns path written."""
    path = translation_template_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_template(data)
    fm_out: dict[str, Any] = {}
    for k, v in sorted(normalized["functionalMappings"].items(), key=lambda x: x[0].lower()):
        fm_out[k] = v[0] if len(v) == 1 else v
    payload = {
        "schemaVersion": 2,
        "preferredPhrases": normalized["preferredPhrases"],
        "blockedPhrases": normalized["blockedPhrases"],
        "alwaysAllow": normalized["alwaysAllow"],
        "aliases": {k: normalized["aliases"][k] for k in sorted(normalized["aliases"], key=str.lower)},
        "functionalMappings": fm_out,
        "functionalHints": normalized["functionalHints"],
        "structuralHints": normalized["structuralHints"],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _norm_key(s: str) -> str:
    return s.strip().casefold()


def _blocked_rules(blocked_phrases: list[str]) -> tuple[set[str], list[str]]:
    """Exact normalized phrases plus prefix rules (entry ending with ``*``, star not counted in prefix)."""
    exact: set[str] = set()
    prefixes: list[str] = []
    for x in blocked_phrases:
        s = str(x).strip()
        if not s:
            continue
        if s.endswith("*") and len(s) > 1:
            prefixes.append(_norm_key(s[:-1].rstrip()))
        else:
            exact.add(_norm_key(s))
    return exact, prefixes


def _phrase_blocked(norm_key: str, exact: set[str], prefixes: list[str]) -> bool:
    if norm_key in exact:
        return True
    return any(norm_key.startswith(p) for p in prefixes)


def _canonicalize(phrase: str, aliases_norm_to_canon: dict[str, str]) -> str:
    return aliases_norm_to_canon.get(_norm_key(phrase), phrase.strip())


def _merge_tags_functional(
    existing_tags: list[str],
    unconditional: list[str],
    literal_norms: set[str],
    mappings: dict[str, list[str]],
) -> list[str]:
    tag_seen: set[str] = set()
    merged: list[str] = []

    for t in unconditional:
        if not t.strip():
            continue
        nk = _norm_key(t)
        if nk in tag_seen:
            continue
        tag_seen.add(nk)
        merged.append(t.strip())

    for surface, tags in mappings.items():
        if _norm_key(surface) not in literal_norms:
            continue
        for t in tags:
            if not t.strip():
                continue
            nk = _norm_key(t)
            if nk in tag_seen:
                continue
            tag_seen.add(nk)
            merged.append(t.strip())

    for t in existing_tags:
        nk = _norm_key(t)
        if nk in tag_seen:
            continue
        tag_seen.add(nk)
        merged.append(t)

    return merged[:MAX_REASONING_TAGS]


def _merge_themes_structural(existing: list[str], structural: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in structural:
        s = t.strip()
        if not s:
            continue
        nk = _norm_key(s)
        if nk in seen:
            continue
        seen.add(nk)
        out.append(s)
    for t in existing:
        s = str(t).strip()
        if not s:
            continue
        nk = _norm_key(s)
        if nk in seen:
            continue
        seen.add(nk)
        out.append(s)
    return out[:MAX_CAPSULE_THEMES]


def apply_workspace_translation_template(
    literal_pool: list[str],
    reasoning_capsule: dict[str, Any],
    template: dict[str, Any] | None,
    *,
    max_hints: int = _MAX_PACKET_HINTS,
) -> tuple[list[str], dict[str, Any]]:
    """
    Merge user template after core packet literals are built.

    Literal order: preferredPhrases → alwaysAllow → remaining core (blocked removed, aliases →
    canonical). functionalHints and functionalMappings (when surfaces present) feed tags;
    structuralHints prepend themes.
    """
    tpl = _normalize_template(template or {})
    block_exact, block_prefixes = _blocked_rules(tpl["blockedPhrases"])
    aliases_norm = _aliases_norm_to_canon(tpl["aliases"])

    def blocked_phrase(s: str) -> bool:
        return _phrase_blocked(_norm_key(s), block_exact, block_prefixes)

    core_raw = [p for p in literal_pool if not blocked_phrase(p)]
    core: list[str] = []
    core_seen: set[str] = set()
    for p in core_raw:
        c = _canonicalize(p, aliases_norm)
        if blocked_phrase(c):
            continue
        nk = _norm_key(c)
        if nk in core_seen:
            continue
        core_seen.add(nk)
        core.append(c)

    seen: set[str] = set()
    out: list[str] = []

    for p in tpl["preferredPhrases"]:
        c = _canonicalize(p, aliases_norm)
        if blocked_phrase(p) or blocked_phrase(c) or len(c) < 3:
            continue
        k = _norm_key(c)
        if k in seen:
            continue
        seen.add(k)
        out.append(c)

    for a in tpl["alwaysAllow"]:
        c = _canonicalize(a, aliases_norm)
        if blocked_phrase(a) or blocked_phrase(c) or len(c) < 3:
            continue
        k = _norm_key(c)
        if k in seen:
            continue
        seen.add(k)
        out.append(c)

    for p in core:
        k = _norm_key(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
        if len(out) >= max_hints:
            break

    out = out[:max_hints]
    literal_norms = {_norm_key(x) for x in out}

    cap = {
        "themes": list((reasoning_capsule or {}).get("themes") or []),
        "namedPrograms": list((reasoning_capsule or {}).get("namedPrograms") or []),
        "tags": [str(t).strip() for t in ((reasoning_capsule or {}).get("tags") or []) if str(t).strip()],
    }
    cap["themes"] = _merge_themes_structural(cap["themes"], tpl["structuralHints"])
    cap["tags"] = _merge_tags_functional(
        cap["tags"],
        tpl["functionalHints"],
        literal_norms,
        tpl["functionalMappings"],
    )

    return out, cap
