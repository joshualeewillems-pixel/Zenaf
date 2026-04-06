"""
Vision & Execution field labels and trunk-token routing.

**Source of truth for UI labels:** ``docs/04_REFERENCE/vision_execution_field_inventory.json``.

**Integration commit (precision PATCH)** supports only a small transitional subset of storage keys;
see ``_INTEGRATION_SUPPORTED_STORAGE_KEYS``. Aliases map capture tokens into those keys when possible.

``hydrated_structured_bullets`` emits council PRIMARY lines using **only** contract-backed labels
for the entity (plus explicit legacy header bridges).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

# --- Repo-relative contract path (local_ai/vision_execution → repo root) ---
_CONTRACT_PATH = Path(__file__).resolve().parents[2] / "docs" / "04_REFERENCE" / "vision_execution_field_inventory.json"

_ENTITY_TYPE_UI: Final[dict[str, str]] = {
    "idea": "Idea",
    "initiative": "Initiative",
    "project": "Project",
    "task": "Task",
}

# Keys ``commit_precision`` / ``_patch_for_entity`` can actually write today (integration_commit.py).
_INTEGRATION_SUPPORTED_STORAGE_KEYS: Final[dict[str, frozenset[str]]] = {
    "idea": frozenset({"title", "summary", "description", "desired_outcome", "notes"}),
    "initiative": frozenset({"title", "brief", "next_step_ai", "notes"}),
    "project": frozenset({"title", "brief", "next_step_ai", "notes"}),
    "task": frozenset({"title", "description", "completion_criteria", "notes"}),
}

# Transitional capture routing: trunk / informal tokens → canonical storage_key (must pass integration gate).
_ALIAS_POLICY: Final[dict[str, dict[str, str]]] = {
    "task": {
        "title": "title",
        "description": "description",
        "brief": "description",
        "summary": "description",
        "desired_outcome": "description",
        "goal": "description",
        "next_step": "description",
        "acceptance_criteria": "completion_criteria",
        "completion_criteria": "completion_criteria",
        "notes": "notes",
        "constraints": "notes",
        "audience_split": "notes",
        "unknown": "notes",
    },
    "idea": {
        "title": "title",
        "summary": "summary",
        "brief": "description",
        "description": "description",
        "desired_outcome": "desired_outcome",
        "goal": "desired_outcome",
        "notes": "notes",
        "acceptance_criteria": "notes",
        "constraints": "notes",
        "audience_split": "notes",
        "next_step": "notes",
        "unknown": "notes",
    },
    "initiative": {
        "title": "title",
        "brief": "brief",
        "summary": "brief",
        "desired_outcome": "brief",
        "goal": "brief",
        "next_step": "next_step_ai",
        "next_step_ai": "next_step_ai",
        "notes": "notes",
        "acceptance_criteria": "notes",
        "constraints": "notes",
        "audience_split": "notes",
        "description": "brief",
    },
    "project": {
        "title": "title",
        "brief": "brief",
        "summary": "brief",
        "desired_outcome": "brief",
        "goal": "brief",
        "next_step": "next_step_ai",
        "next_step_ai": "next_step_ai",
        "notes": "notes",
        "acceptance_criteria": "notes",
        "constraints": "notes",
        "audience_split": "notes",
        "description": "brief",
    },
}

# Preferred (short) disambiguation choices when capture target is ambiguous — policy, not the full contract.
_DISAMBIGUATION_PREFERRED_STORAGE_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "task": ("description", "notes"),
    "idea": ("description", "notes"),
    "initiative": ("brief", "notes"),
    "project": ("brief", "notes"),
}

_SKIPPED_STORAGE_PREFIXES: Final[tuple[str, ...]] = ("session:", "client:")
_DISPLAY_ONLY_STORAGE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "linked_projects_display",
        "participation_summary",
        "required_by_display",
        "execution_steps",
    }
)


@lru_cache(maxsize=1)
def load_ve_field_contract() -> dict[str, Any]:
    with _CONTRACT_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _field_rows() -> tuple[dict[str, Any], ...]:
    doc = load_ve_field_contract()
    rows = doc.get("fields")
    if not isinstance(rows, list):
        return ()
    return tuple(r for r in rows if isinstance(r, dict))


@lru_cache(maxsize=1)
def _rows_by_entity() -> dict[str, tuple[dict[str, Any], ...]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in _field_rows():
        et = str(row.get("entity_type", "")).strip().lower()
        if not et:
            continue
        out.setdefault(et, []).append(row)
    return {k: tuple(v) for k, v in out.items()}


def _row_storage_key(row: dict[str, Any]) -> str:
    return str(row.get("storage_key", "")).strip().lower()


def _contract_row_by_storage_key(entity_type: str, storage_key: str) -> dict[str, Any] | None:
    et = (entity_type or "").strip().lower()
    sk = (storage_key or "").strip().lower()
    for row in _rows_by_entity().get(et, ()):
        if _row_storage_key(row) == sk:
            return row
    return None


def _hydration_skip_row(row: dict[str, Any]) -> bool:
    sk = _row_storage_key(row)
    if not sk:
        return True
    if sk in _DISPLAY_ONLY_STORAGE_KEYS:
        return True
    if any(sk.startswith(p) for p in _SKIPPED_STORAGE_PREFIXES):
        return True
    ft = str(row.get("field_type", "")).strip().lower()
    if ft == "derived":
        return True
    return False


@lru_cache(maxsize=32)
def _hydration_allowed_label_map(entity_type: str) -> dict[str, str]:
    """Lowercased UI label → canonical UI label (contract-backed)."""
    et = (entity_type or "").strip().lower()
    m: dict[str, str] = {}
    for row in _rows_by_entity().get(et, ()):
        if _hydration_skip_row(row):
            continue
        label = str(row.get("ui_label", "")).strip()
        if not label:
            continue
        m[label.lower()] = label
    return m


def _legacy_hydration_header_to_label(entity_type: str, header_lower: str) -> str | None:
    """
    Map old client/snapshot headers to the current contract ``ui_label`` when the
    header text no longer matches (e.g. short ``Notes:`` on initiatives, ``Next step (AI):``).
    """
    et = (entity_type or "").strip().lower()
    h = (header_lower or "").strip().lower()
    if not h:
        return None
    if et == "initiative" and h == "notes":
        return ui_label_for_storage_key("initiative", "notes")
    if et == "project" and h == "deliverables":
        return ui_label_for_storage_key("project", "deliverables")
    if et in ("initiative", "project") and h == "next step (ai)":
        return ui_label_for_storage_key(et, "next_step_ai")
    return None


def entity_type_ui_heading(entity_type: str | None) -> str:
    t = (entity_type or "").strip().lower()
    return _ENTITY_TYPE_UI.get(t, (entity_type or "Item").strip().title() or "Item")


def allowed_storage_keys(entity_type: str) -> frozenset[str]:
    """Storage keys that integration commit + trunk normalization treat as writable for this entity."""
    return _INTEGRATION_SUPPORTED_STORAGE_KEYS.get((entity_type or "").strip().lower(), frozenset())


def ui_label_for_storage_key(entity_type: str, storage_key: str) -> str | None:
    et = (entity_type or "").strip().lower()
    sk = (storage_key or "").strip().lower()
    row = _contract_row_by_storage_key(et, sk)
    if not row:
        return None
    label = str(row.get("ui_label", "")).strip()
    return label or None


def hydration_field_block(
    entity_type: str,
    storage_key: str,
    body: str,
    *,
    max_body_len: int = 4000,
) -> str | None:
    """
    ``{contract ui_label}:\\n{body}`` for council ``ve_focus_description`` / expanded text.
    Matches ``hydrated_structured_bullets`` chunk parsing (label-in, label-out).
    """
    label = ui_label_for_storage_key(entity_type, storage_key)
    if not label:
        return None
    text = (body or "").strip()
    if not text:
        return None
    if len(text) > max_body_len:
        text = text[: max_body_len - 1] + "…"
    return f"{label}:\n{text}"


def hydration_inline_list(
    entity_type: str,
    storage_key: str,
    items: list[str],
    *,
    max_items: int = 16,
) -> str | None:
    """Single line ``Label: a, b, c`` using the contract label (idea linked fields, etc.)."""
    label = ui_label_for_storage_key(entity_type, storage_key)
    if not label:
        return None
    vals = [str(x).strip() for x in items if str(x).strip()][:max_items]
    if not vals:
        return None
    return f"{label}: {', '.join(vals)}"


def normalize_trunk_token_to_storage_key(entity_type: str, token: str | None) -> str | None:
    """Map internal/trunk capture token to a canonical storage key commit can use, or None."""
    et = (entity_type or "").strip().lower()
    t = (token or "").strip().lower()
    if not t or not et:
        return None
    supported = _INTEGRATION_SUPPORTED_STORAGE_KEYS.get(et, frozenset())
    policy = _ALIAS_POLICY.get(et, {})
    sk = policy.get(t)
    if sk is None:
        if t in supported and _contract_row_by_storage_key(et, t) is not None:
            sk = t
    if sk is None:
        return None
    if sk not in supported:
        return None
    if _contract_row_by_storage_key(et, sk) is None:
        return None
    return sk


def hydrated_structured_bullets(expanded: str | None, entity_type: str) -> list[str]:
    """
    Turn storage/hydration chunks ('Header: body') into PRIMARY bullets using only
    contract-backed UI labels for the given entity type.
    """
    ex = (expanded or "").strip()
    if not ex:
        return []
    et = (entity_type or "").strip().lower()
    if not et:
        return []

    allowed_labels = _hydration_allowed_label_map(et)
    chunks = [c.strip() for c in re.split(r"\n\s*\n", ex) if c.strip()]
    out: list[str] = []

    for ch in chunks:
        if ":" not in ch:
            continue
        raw_header, raw_body = ch.split(":", 1)
        header_key = raw_header.strip().lower()
        body = " ".join(raw_body.strip().split())
        if not body:
            continue

        label = allowed_labels.get(header_key) or _legacy_hydration_header_to_label(et, header_key)
        if not label:
            continue
        if len(body) > 2000:
            body = body[:1999] + "…"
        out.append(f"- {label}: {body}")

    return out


def field_disambiguation_user_message(entity_type: str, entity_display_name: str) -> str:
    """
    When capture cannot be mapped to a single field, never imply a save.
    Preferred targets are **policy** (short list); labels always come from the contract.
    """
    et = (entity_type or "").strip().lower()
    name = (entity_display_name or "").strip() or "this item"
    pref = _DISAMBIGUATION_PREFERRED_STORAGE_KEYS.get(et)
    if pref and len(pref) >= 2:
        labels: list[str] = []
        for k in pref:
            ul = ui_label_for_storage_key(et, k)
            if ul:
                labels.append(ul)
        if len(labels) >= 2:
            a, b = labels[0], labels[1]
            return (
                f"I don't have a clear field for that on {name} — I can add it to **{a}** or **{b}**. Which do you want?"
            )
    return (
        "I don't have a clear Vision & Execution field for that yet — say which part of the item to update, "
        "or open the item in Vision & Execution and we'll align on the next turn."
    )


def clear_ve_field_contract_cache() -> None:
    """Test hook: invalidate loaders after mutating the JSON on disk."""
    load_ve_field_contract.cache_clear()
    _field_rows.cache_clear()
    _rows_by_entity.cache_clear()
    _hydration_allowed_label_map.cache_clear()
