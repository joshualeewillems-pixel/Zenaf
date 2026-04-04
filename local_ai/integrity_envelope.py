"""
Phase 1 council integrity: envelopes for traceability (bounded mode), no full claim graph.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from local_ai.judgment_substrate import SubjectRef, normalize_subject_ref


class IntegritySubjectRef(BaseModel):
    """Grounding handle for council outputs (VE focus / API subject_ref)."""

    entity_type: str
    entity_id: str | None = None
    role_in_output: str = "primary_subject"


class IntegrityProvenance(BaseModel):
    run_id: str


class CouncilIntegrityEnvelope(BaseModel):
    """Metadata attached to council seat or synthesis SSE payloads."""

    schema_version: int = 1
    surface: str  # "council_seat" | "council_synthesis"
    default_mode: str = "bounded"
    subject_refs: list[IntegritySubjectRef] = Field(default_factory=list)
    provenance: IntegrityProvenance
    policies_applied: list[str] = Field(default_factory=list)
    # Optional synthesis subtype marker (e.g., failure_template)
    synthesis_type: str | None = None
    # Optional effective integrity mode for special synthesis paths
    # (e.g., bounded_failure for refusal/failure templates).
    integrity_mode: str | None = None
    # Council synthesis only: coarse token overlap vs seat outputs;
    # values: supported | partially_supported | unsupported_expansion
    synthesis_support_status: str | None = None


def _dedupe_subject_refs(refs: list[IntegritySubjectRef]) -> list[IntegritySubjectRef]:
    seen: set[tuple[str, str | None]] = set()
    out: list[IntegritySubjectRef] = []
    for r in refs:
        key = (r.entity_type.strip().lower(), (r.entity_id or "").strip() or None)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def build_council_subject_refs(
    subject_ref: SubjectRef | dict[str, Any] | None,
    council_preflight: dict[str, Any] | None,
) -> list[IntegritySubjectRef]:
    refs: list[IntegritySubjectRef] = []
    subj = normalize_subject_ref(subject_ref)
    if subj and (subj.entity_type or subj.entity_id):
        refs.append(
            IntegritySubjectRef(
                entity_type=(subj.entity_type or "unknown").strip() or "unknown",
                entity_id=subj.entity_id.strip() if isinstance(subj.entity_id, str) and subj.entity_id.strip() else None,
                role_in_output="primary_subject",
            )
        )
    if council_preflight and isinstance(council_preflight, dict):
        vf = council_preflight.get("ve_focus")
        if isinstance(vf, dict) and vf:
            et = str(vf.get("entity_type") or "").strip() or None
            eid = vf.get("entity_id")
            sid = eid.strip() if isinstance(eid, str) and eid.strip() else None
            if et or sid:
                refs.append(
                    IntegritySubjectRef(
                        entity_type=et or "vision_execution_selection",
                        entity_id=sid,
                        role_in_output="primary_subject",
                    )
                )
        vs = council_preflight.get("ve_selection")
        if isinstance(vs, dict) and vs:
            for key, et_name in (
                ("initiativeId", "initiative"),
                ("projectId", "project"),
                ("taskId", "task"),
                ("assetId", "asset"),
            ):
                raw = vs.get(key)
                if isinstance(raw, str) and raw.strip():
                    refs.append(
                        IntegritySubjectRef(
                            entity_type=et_name,
                            entity_id=raw.strip(),
                            role_in_output="navigation_selection",
                        )
                    )
    return _dedupe_subject_refs(refs)


def build_council_policies_applied(
    *,
    wash_trace: dict[str, Any] | None,
    routing_allows_externalization: bool,
    routing_effective_cloud: bool,
) -> list[str]:
    policies: list[str] = ["wash_v0"]
    wt = wash_trace or {}
    if wt.get("wash_applied"):
        policies.append("wash_redaction_applied")
    if wt.get("safety_allow_cloud_with_wash"):
        policies.append("wash_safe_for_cloud")
    else:
        policies.append("wash_cloud_refused")
    policies.append(f"routing:allows_externalization={'true' if routing_allows_externalization else 'false'}")
    policies.append(f"routing:effective_cloud={'true' if routing_effective_cloud else 'false'}")
    return policies


def make_council_integrity_envelope(
    *,
    surface: str,
    run_id: str,
    subject_refs: list[IntegritySubjectRef],
    policies_applied: list[str],
    synthesis_type: str | None = None,
    integrity_mode: str | None = None,
    synthesis_support_status: str | None = None,
) -> CouncilIntegrityEnvelope:
    return CouncilIntegrityEnvelope(
        schema_version=1,
        surface=surface,
        default_mode="bounded",
        subject_refs=subject_refs,
        provenance=IntegrityProvenance(run_id=run_id),
        policies_applied=list(policies_applied),
        synthesis_type=synthesis_type,
        integrity_mode=integrity_mode,
        synthesis_support_status=synthesis_support_status,
    )


def council_envelope_to_dict(envelope: CouncilIntegrityEnvelope) -> dict[str, Any]:
    return envelope.model_dump(mode="json")
