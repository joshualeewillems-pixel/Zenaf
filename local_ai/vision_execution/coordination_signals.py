"""
Coordination-layer signals: execution checkpoints (ActivityEvent) and flow readings (node_judgment_history).

Single choke point for ``execution_flow_reading`` rows: ``append_execution_flow_reading``.
See plan: docs alignment with ActivityEvent.source vs evidence_source / pointer_kind.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from local_ai.judgment_substrate import (
    JudgmentMechanism,
    JudgmentObservation,
    JudgmentTrunk,
    JudgmentVerdict,
    SubjectRef,
)

PointerKind = Literal["activity_event", "council_stream_run"]
EvidenceSource = Literal["zenaf-client-trace", "server-execution", "council_stream"]
Impact = Literal["positive", "neutral", "negative"]
Dimension = Literal["clarity", "capacity", "friction"]

_CONTEXT_POINTER_KIND = "pointer_kind"
_CONTEXT_COORDINATION_EVIDENCE_SOURCE = "coordination_evidence_source"

_VERDICT_KIND = "execution_flow_reading"
_PAYLOAD_TYPE = "execution_flow_reading"

_ID_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

# Council pointer contract: ``pointer`` for pointer_kind=council_stream_run must equal
# ``council_stream_runs.id`` (return value of storage.append_council_stream_run), never
# integrity_run_id, client correlation ids, or council "artifact" aliases.


def _validate_bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"type", "impact", "dimension", "confidence"}
    if set(payload.keys()) != allowed:
        raise ValueError("execution_flow_reading payload must have exactly keys: type, impact, dimension, confidence")
    if payload.get("type") != _PAYLOAD_TYPE:
        raise ValueError("payload.type must be execution_flow_reading")
    if payload.get("impact") not in ("positive", "neutral", "negative"):
        raise ValueError("invalid impact")
    if payload.get("dimension") not in ("clarity", "capacity", "friction"):
        raise ValueError("invalid dimension")
    c = payload.get("confidence")
    if not isinstance(c, (int, float)) or c < 0.0 or c > 1.0:
        raise ValueError("confidence must be a number in [0, 1]")
    return {
        "type": _PAYLOAD_TYPE,
        "impact": str(payload["impact"]),
        "dimension": str(payload["dimension"]),
        "confidence": float(c),
    }


def _validate_pointer_pair(pointer: str, pointer_kind: str, evidence_source: str) -> None:
    p = (pointer or "").strip()
    if not p or not _ID_SAFE.match(p):
        raise ValueError("Judgment requires evidence pointer")
    if pointer_kind not in ("activity_event", "council_stream_run"):
        raise ValueError("invalid pointer_kind")
    if evidence_source not in ("zenaf-client-trace", "server-execution", "council_stream"):
        raise ValueError("invalid evidence_source")
    if pointer_kind == "council_stream_run" and evidence_source != "council_stream":
        raise ValueError("pointer_kind council_stream_run requires evidence_source council_stream")
    if pointer_kind == "activity_event" and evidence_source == "council_stream":
        raise ValueError("pointer_kind activity_event cannot use evidence_source council_stream")


def append_execution_flow_reading(
    *,
    user_id: str,
    entity_type: str,
    entity_id: str,
    pointer: str,
    pointer_kind: PointerKind,
    evidence_source: EvidenceSource,
    impact: Impact,
    dimension: Dimension,
    confidence: float,
) -> dict[str, Any]:
    """
    Append one ``execution_flow_reading`` judgment. All feature code must use this entrypoint.
    """
    _validate_pointer_pair(pointer, pointer_kind, evidence_source)
    uid = (user_id or "").strip() or "anonymous"
    if pointer_kind == "council_stream_run":
        from local_ai.vision_execution import storage as ve_storage

        p = (pointer or "").strip()
        row = ve_storage.get_council_stream_run_for_user(p, uid)
        if row is None:
            raise ValueError(
                "council_stream_run pointer must be council_stream_runs.id for this user "
                "(from append_council_stream_run return value; not integrity_run_id or client ids)"
            )
    payload = _validate_bounded_payload(
        {
            "type": _PAYLOAD_TYPE,
            "impact": impact,
            "dimension": dimension,
            "confidence": confidence,
        }
    )
    et = (entity_type or "").strip().lower()
    eid = (entity_id or "").strip()
    if not et or not eid:
        raise ValueError("entity_type and entity_id required")

    obs_ctx: dict[str, Any] = {
        _CONTEXT_POINTER_KIND: pointer_kind,
        _CONTEXT_COORDINATION_EVIDENCE_SOURCE: evidence_source,
    }
    trunk = JudgmentTrunk(
        subject=SubjectRef(entity_type=et, entity_id=eid),
        observation=JudgmentObservation(pointer=(pointer or "").strip(), context=obs_ctx),
        verdict=JudgmentVerdict(kind=_VERDICT_KIND, payload=payload),
        mechanism=JudgmentMechanism(mode="llm"),
        effect="proposal",
        state="proposed",
    )
    refs: dict[str, Any] = {}
    if pointer_kind == "council_stream_run":
        refs["council_stream_run_id"] = (pointer or "").strip()

    from local_ai.vision_execution import storage as ve_storage

    jid = ve_storage.append_node_judgment(uid, et, eid, trunk, refs=refs)
    return {"judgment_row_id": jid, "verdict_kind": _VERDICT_KIND}


def summarize_execution_flow_trunk(trunk: dict[str, Any]) -> dict[str, Any] | None:
    """Extract bounded summary from parsed trunk dict; None if not execution_flow_reading."""
    if not isinstance(trunk, dict):
        return None
    verdict = trunk.get("verdict") or {}
    if not isinstance(verdict, dict) or verdict.get("kind") != _VERDICT_KIND:
        return None
    payload = verdict.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    try:
        _validate_bounded_payload(payload)
    except ValueError:
        return None
    obs = trunk.get("observation") or {}
    pointer = obs.get("pointer") if isinstance(obs, dict) else None
    ctx = obs.get("context") if isinstance(obs, dict) else {}
    if not isinstance(ctx, dict):
        ctx = {}
    return {
        "impact": payload["impact"],
        "dimension": payload["dimension"],
        "confidence": payload["confidence"],
        "pointer": str(pointer or ""),
        "pointer_kind": ctx.get(_CONTEXT_POINTER_KIND),
        "coordination_evidence_source": ctx.get(_CONTEXT_COORDINATION_EVIDENCE_SOURCE),
    }


def list_execution_flow_summaries_for_entity(
    user_id: str, entity_type: str, entity_id: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    from local_ai.vision_execution import storage as ve_storage

    rows = ve_storage.list_node_judgments(user_id, entity_type, entity_id, limit=max(1, min(limit, 100)))
    out: list[dict[str, Any]] = []
    for r in rows:
        trunk = r.get("trunk")
        if isinstance(trunk, str):
            try:
                trunk = json.loads(trunk)
            except Exception:
                trunk = {}
        summ = summarize_execution_flow_trunk(trunk if isinstance(trunk, dict) else {})
        if summ is None:
            continue
        out.append(
            {
                **summ,
                "created_at": r.get("created_at"),
                "judgment_row_id": r.get("id"),
            }
        )
    return out
