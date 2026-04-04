"""
Thin authenticated soil API: transport only; logic lives in local_ai.soil.

POST /vision-execution/soil/append
POST /vision-execution/soil/promote
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.soil.api_guard import SoilApiReject, verify_ve_subject_exists_for_soil_api
from local_ai.soil.append import append_soil_item
from local_ai.soil.discover import find_soil_md_by_id, parse_soil_frontmatter_ids
from local_ai.soil.manifest import read_manifest
from local_ai.soil.paths import node_dir, relative_path_posix, resolve_soil_root
from local_ai.soil.promotion import write_promotion_record

logger = logging.getLogger(__name__)

_MAX_SOIL_BODY_CHARS = 262_144

API_APPEND_CAPTURE_SOURCES = frozenset({"user_action", "named_system_capture"})


class SoilAppendRequest(BaseModel):
    entity_type: str = Field(..., min_length=1, max_length=64)
    entity_id: str = Field("", max_length=512)
    soil_type: str = Field(..., min_length=1, max_length=64)
    body: str = Field(
        ...,
        max_length=_MAX_SOIL_BODY_CHARS,
        description=f"Markdown body (UTF-8). Max {_MAX_SOIL_BODY_CHARS} chars; larger requests get 422.",
    )
    capture_source: Literal["user_action", "named_system_capture"]
    capture_name: str | None = Field(None, max_length=128)
    title: str = Field("", max_length=512, description="Stored in node.json on first create (truncated to 512 server-side).")
    status: str = Field("seed", max_length=32)
    source_refs: list[str] | None = None
    tags: list[str] | None = None
    promotion_score: int = 0
    """When entity_type is _root, must be true or the request is rejected."""
    explicit_root_bucket: bool = False


class SoilPromoteRequest(BaseModel):
    entity_type: str = Field(..., min_length=1, max_length=64)
    entity_id: str = Field("", max_length=512)
    from_soil_id: str = Field(..., min_length=1, max_length=256)
    from_path_rel: str | None = Field(None, max_length=2048)
    to_node_id: str | None = Field(None, max_length=256)
    reason: str = Field("", max_length=16_384)
    supporting_soil_ids: list[str] | None = None
    to_canonical_ref: dict[str, Any] | None = None
    explicit_root_bucket: bool = False


def _reject_as_http(exc: SoilApiReject) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def attach_soil_routes(router: APIRouter) -> None:
    @router.post("/soil/append")
    def soil_append(
        body: SoilAppendRequest,
        current_user: dict = Depends(get_current_user),
    ) -> dict[str, Any]:
        if body.capture_source not in API_APPEND_CAPTURE_SOURCES:
            raise HTTPException(status_code=400, detail="soil_api_capture_source_not_allowed")
        if body.capture_source == "named_system_capture":
            if not (body.capture_name or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail="soil_api_named_capture_requires_capture_name",
                )
        try:
            verify_ve_subject_exists_for_soil_api(
                current_user["id"],
                body.entity_type,
                body.entity_id or None,
                explicit_root_bucket=body.explicit_root_bucket,
            )
        except SoilApiReject as e:
            _reject_as_http(e)

        root = resolve_soil_root()
        try:
            path, soil_id = append_soil_item(
                body.entity_type.strip().lower(),
                (body.entity_id or "").strip() or None,
                soil_type=body.soil_type,
                body=body.body,
                capture_source=body.capture_source,
                root=root,
                status=body.status,
                source_refs=body.source_refs,
                tags=body.tags,
                promotion_score=body.promotion_score,
                capture_name=(body.capture_name or "").strip() or None,
                title=body.title,
            )
        except ValueError as e:
            logger.info("soil append rejected: %s", e)
            raise HTTPException(status_code=400, detail=str(e)) from e

        rel = relative_path_posix(path, root)
        logger.info(
            "soil append user=%s soil_id=%s entity=%s:%s",
            current_user["id"],
            soil_id,
            body.entity_type,
            body.entity_id,
        )
        return {"ok": True, "soil_id": soil_id, "relative_path": rel}

    @router.post("/soil/promote")
    def soil_promote(
        body: SoilPromoteRequest,
        current_user: dict = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            verify_ve_subject_exists_for_soil_api(
                current_user["id"],
                body.entity_type,
                body.entity_id or None,
                explicit_root_bucket=body.explicit_root_bucket,
            )
        except SoilApiReject as e:
            _reject_as_http(e)

        root = resolve_soil_root()
        entity_type = body.entity_type.strip().lower()
        entity_id = (body.entity_id or "").strip() or None
        if entity_type != "_root" and not entity_id:
            raise HTTPException(status_code=400, detail="soil_api_entity_id_required")

        try:
            nd = node_dir(root, entity_type, entity_id)
            expected_node_id = read_manifest(nd)["node_id"]
        except FileNotFoundError:
            raise HTTPException(
                status_code=400,
                detail="soil_api_node_missing_run_append_or_ensure_first",
            ) from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        from_soil_id = body.from_soil_id.strip()
        if body.from_path_rel:
            soil_path = (root / body.from_path_rel).resolve()
            try:
                soil_path.relative_to(root.resolve())
            except ValueError:
                raise HTTPException(status_code=400, detail="soil_api_from_path_outside_root") from None
            if not soil_path.is_file():
                raise HTTPException(status_code=400, detail="soil_api_from_path_not_found")
            text = soil_path.read_text(encoding="utf-8")
            sid_fm, nid_fm = parse_soil_frontmatter_ids(text)
            if sid_fm != from_soil_id:
                raise HTTPException(
                    status_code=400,
                    detail="soil_api_from_soil_id_mismatch_with_file",
                )
            if not nid_fm:
                raise HTTPException(status_code=400, detail="soil_api_frontmatter_missing_node_id")
            from_path_rel = Path(body.from_path_rel).as_posix()
            from_node_id = nid_fm
        else:
            try:
                _abs, from_path_rel, from_node_id = find_soil_md_by_id(root, from_soil_id)
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail="soil_api_soil_id_not_found") from None
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

        if from_node_id != expected_node_id:
            raise HTTPException(
                status_code=400,
                detail="soil_api_soil_belongs_to_different_node",
            )

        if body.to_canonical_ref is not None:
            if not isinstance(body.to_canonical_ref, dict):
                raise HTTPException(status_code=400, detail="soil_api_to_canonical_ref_must_be_object")
            to_canonical_ref = dict(body.to_canonical_ref)
        else:
            to_canonical_ref = {
                "kind": "unspecified",
                "note": "API promotion audit only (no canonical write)",
            }

        accepted_by = f"api:{current_user['id']}"
        try:
            out = write_promotion_record(
                root,
                entity_type,
                entity_id,
                from_soil_id=from_soil_id,
                from_path_rel=from_path_rel,
                from_node_id=from_node_id,
                to_canonical_ref=to_canonical_ref,
                reason=(body.reason or "").strip() or "(no reason given)",
                accepted_by=accepted_by,
                supporting_soil_ids=body.supporting_soil_ids,
                to_node_id=(body.to_node_id or "").strip() or None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        rel = relative_path_posix(out, root)
        promo = json.loads(out.read_text(encoding="utf-8"))
        logger.info(
            "soil promote user=%s promotion_id=%s from_soil_id=%s",
            current_user["id"],
            promo.get("promotion_id"),
            from_soil_id,
        )
        return {
            "ok": True,
            "promotion_id": promo.get("promotion_id"),
            "relative_path": rel,
        }
