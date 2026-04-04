"""
Node substrate: cross-module identity and relationship layer.

NodeRef and NodeSnapshot are the internal multi-user–aware identity types.
SubjectRef remains the judgment-facing interface; use node_ref_to_subject_ref
to bridge so council/judgment code does not need to change.

Additive and internal only. No persistence, API, or frontend changes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class NodeRef(BaseModel):
    """Lightweight identity for a node with provenance and optional multi-user scope."""

    node_type: str
    node_id: str
    source_module: str
    source_entity_id: str
    workspace_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class NodeSnapshot(BaseModel):
    """
    Richer snapshot for reasoning, linking, and visibility.
    Same identity as NodeRef plus context (parent, related, status, payload).
    """

    node_type: str
    node_id: str
    source_module: str
    source_entity_id: str
    workspace_id: Optional[str] = None
    owner_user_id: Optional[str] = None

    title: str
    status: Optional[str] = None
    summary: Optional[str] = None
    parent_node_id: Optional[str] = None
    related_node_ids: List[str] = Field(default_factory=list)
    visibility: Optional[str] = None
    scope: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


def normalize_node_ref(
    data: Union[NodeRef, Dict[str, Any], None],
) -> Optional[NodeRef]:
    """
    Best-effort normalization into NodeRef.
    Accepts NodeRef (returned as-is), dict with node fields, or None.
    """
    if data is None:
        return None
    if isinstance(data, NodeRef):
        return data
    if not isinstance(data, dict):
        return None
    node_type = (data.get("node_type") or data.get("type") or "unknown").strip() or "unknown"
    node_id = (data.get("node_id") or data.get("source_entity_id") or "").strip() or ""
    source_entity_id = (data.get("source_entity_id") or data.get("node_id") or "").strip() or ""
    source_module = (data.get("source_module") or "unknown").strip() or "unknown"
    return NodeRef(
        node_type=node_type,
        node_id=node_id or source_entity_id,
        source_module=source_module,
        source_entity_id=source_entity_id or node_id,
        workspace_id=data.get("workspace_id"),
        owner_user_id=data.get("owner_user_id"),
        title=data.get("title"),
        summary=data.get("summary"),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "node_type",
                "type",
                "node_id",
                "source_module",
                "source_entity_id",
                "workspace_id",
                "owner_user_id",
                "title",
                "summary",
            )
        },
    )


def node_ref_to_subject_ref(node_ref: NodeRef):
    """
    Bridge NodeRef -> SubjectRef so council/judgment can stay on SubjectRef.
    """
    from local_ai.judgment_substrate import SubjectRef

    extra = dict(node_ref.extra)
    if node_ref.source_module:
        extra["source_module"] = node_ref.source_module
    if node_ref.workspace_id is not None:
        extra["workspace_id"] = node_ref.workspace_id
    if node_ref.owner_user_id is not None:
        extra["owner_user_id"] = node_ref.owner_user_id
    return SubjectRef(
        entity_type=node_ref.node_type,
        entity_id=node_ref.source_entity_id or node_ref.node_id,
        title=node_ref.title,
        summary=node_ref.summary,
        extra=extra,
    )
