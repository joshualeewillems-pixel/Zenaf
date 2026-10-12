"""
Vision Execution API safeguards for soil writes.

- Implicit ensure_node via append/promote is allowed only when the subject exists
  in VE for the authenticated user (or explicit _root bucket flag).
  Tasks/projects/etc. are scoped by `user_id` in storage; another user's id
  returns no row → SoilApiReject 404 (`soil_api_ve_subject_not_found`).
- named_system_capture is validated elsewhere (allowlist + capture_name); the API
  layer always uses Depends(get_current_user), so system captures cannot be
  anonymous on this surface.
"""

from __future__ import annotations

import json
from typing import Any

from local_ai.vision_execution import service as VeService
from local_ai.vision_execution import storage as VEStorage


class SoilApiReject(Exception):
    """Raise from guard helpers; routes map to HTTPException."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _perspective_row(user_id: str, perspective_id: str) -> dict[str, Any] | None:
    cw = VEStorage.get_user_council_workspace(user_id)
    if not cw:
        return None
    raw = cw.get("perspectives_json")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, list):
        arr = raw
    else:
        return None
    if not isinstance(arr, list):
        return None
    for p in arr:
        if isinstance(p, dict) and str(p.get("id", "")).strip() == perspective_id.strip():
            return p
    return None


def verify_ve_subject_exists_for_soil_api(
    user_id: str,
    entity_type: str,
    entity_id: str | None,
    *,
    explicit_root_bucket: bool,
) -> None:
    """
    Ensure API callers cannot spray node dirs for arbitrary types/ids.

    _root requires explicit_root_bucket=True (opt-in).
    Other types require a non-empty entity_id and a VE row owned by user_id.
    """
    et = (entity_type or "").strip().lower()
    if et == "_root":
        if not explicit_root_bucket:
            raise SoilApiReject(
                403,
                "soil_api_root_bucket_requires_explicit_root_bucket_true",
            )
        return

    eid = (entity_id or "").strip()
    if not eid:
        raise SoilApiReject(400, "soil_api_entity_id_required")

    row: dict[str, Any] | None = None
    if et == "task":
        row = VeService.get_task(eid, user_id)
    elif et == "project":
        row = VeService.get_project(eid, user_id)
    elif et == "initiative":
        row = VeService.get_initiative(eid, user_id)
    elif et == "idea":
        row = VeService.get_idea(eid, user_id)
    elif et == "core_profile":
        row = VeService.get_core_profile(eid, user_id)
    elif et == "perspective_agent":
        row = _perspective_row(user_id, eid)
    else:
        raise SoilApiReject(400, f"soil_api_entity_type_not_allowed:{et}")

    if row is None:
        raise SoilApiReject(404, "soil_api_ve_subject_not_found")
