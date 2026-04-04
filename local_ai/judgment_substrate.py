from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

if TYPE_CHECKING:
  from local_ai.judgment import JudgmentRecord


# ARCHITECTURE NOTE:
# Judgments point at Subjects (via SubjectRef). Over time, concrete
# entities like initiatives, projects, tasks, and content briefs may be
# treated as typed Subject/Node instances in a shared graph.

class SubjectRef(BaseModel):
  """Lightweight identity for the object under judgment."""

  entity_type: str
  entity_id: Optional[str] = None
  title: Optional[str] = None
  summary: Optional[str] = None
  extra: Dict[str, Any] = Field(default_factory=dict)


class SubjectSnapshot(BaseModel):
  """
  Minimal snapshot of a Subject/Node for internal reasoning.

  This is intentionally small and non-invasive: it does not replace
  existing business entities and is not persisted. It can be used by
  adapters to expose a uniform view over ideas, initiatives, projects,
  tasks, content briefs, intake items, etc.
  """

  subject_type: str
  subject_id: str

  title: str
  summary: Optional[str] = None
  status: Optional[str] = None

  parent_subject_id: Optional[str] = None
  related_subject_ids: List[str] = Field(default_factory=list)

  module_origin: Optional[str] = None
  payload: Dict[str, Any] = Field(default_factory=dict)


class JudgmentSnapshot(BaseModel):
  """Normalized snapshot of a judgment event (agnostic to source module)."""

  judgment_id: Optional[str] = None
  subject: Optional[SubjectRef] = None

  question: Optional[str] = None
  context_ref: Dict[str, Any] = Field(default_factory=dict)

  position: Optional[str] = None
  primary_reason: Optional[str] = None
  main_risk: Optional[str] = None
  required_guardrail: Optional[str] = None
  next_step: Optional[str] = None

  confidence: Optional[float] = None
  labels: List[str] = Field(default_factory=list)
  created_at: Optional[str] = None
  created_by: Optional[str] = None
  raw_text: Optional[str] = None


class SeatJudgment(JudgmentSnapshot):
  """Judgment produced by a single council seat (profile × mandate)."""

  seat_id: Optional[str] = None
  profile_id: Optional[str] = None
  mandate_id: Optional[str] = None

  status: str = "ok"
  error: Optional[str] = None
  duration_ms: Optional[int] = None


JudgmentEffect = Literal[
  "none",
  "proposal",
  "persist_queue",
  "persist_signal",
  "persist_decision",
  "mutate_graph",
  "stream_only",
]

JudgmentState = Literal["forming", "proposed", "applied", "dismissed", "superseded"]

JudgmentMechanismMode = Literal["rule", "llm", "hybrid", "human_override"]


class JudgmentObservation(BaseModel):
  """Opaque / structured evidence pointer for what triggered the judgment."""

  pointer: Optional[str] = None
  context: Dict[str, Any] = Field(default_factory=dict)


class JudgmentVerdict(BaseModel):
  """Registered verdict kind + extensible JSON payload (read-only mapping target)."""

  kind: str = "unspecified"
  payload: Dict[str, Any] = Field(default_factory=dict)


class JudgmentMechanism(BaseModel):
  """How the judgment was produced (rule / LLM / mix / human)."""

  mode: JudgmentMechanismMode = "rule"
  model_id: Optional[str] = None
  policy_ref: Optional[str] = None
  context: Dict[str, Any] = Field(default_factory=dict)


class JudgmentTrunk(BaseModel):
  """
  Shared six-part spine for interpreting legacy judgment shapes.
  Adapters map existing models to this view without replacing them.
  """

  subject: Optional[SubjectRef] = None
  observation: JudgmentObservation = Field(default_factory=JudgmentObservation)
  verdict: JudgmentVerdict = Field(default_factory=JudgmentVerdict)
  mechanism: JudgmentMechanism = Field(default_factory=JudgmentMechanism)
  effect: JudgmentEffect = "none"
  state: JudgmentState = "proposed"
  id: Optional[str] = None
  created_at: Optional[str] = None
  created_by: Optional[str] = None


def normalize_subject_ref(data: Union[SubjectRef, Dict[str, Any], None]) -> Optional[SubjectRef]:
  """
  Best-effort normalization of an incoming subject_ref into SubjectRef.

  Accepts:
  - SubjectRef (returned as-is)
  - dict with keys like entity_type, type, entity_id, title, summary, extra
  - None
  """
  if data is None:
    return None
  if isinstance(data, SubjectRef):
    return data
  if not isinstance(data, dict):
    return None
  entity_type = (data.get("entity_type") or data.get("type") or "unknown").strip() or "unknown"
  return SubjectRef(
    entity_type=entity_type,
    entity_id=data.get("entity_id"),
    title=data.get("title"),
    summary=data.get("summary"),
    extra={
      k: v
      for k, v in data.items()
      if k not in ("entity_type", "type", "entity_id", "title", "summary")
    },
  )


def judgment_snapshot_to_trunk(snapshot: JudgmentSnapshot) -> JudgmentTrunk:
  """Read-only Trunk view of a normalized JudgmentSnapshot (council / generic)."""
  payload: Dict[str, Any] = {}
  if snapshot.position is not None:
    payload["position"] = snapshot.position
  if snapshot.primary_reason is not None:
    payload["primary_reason"] = snapshot.primary_reason
  if snapshot.main_risk is not None:
    payload["main_risk"] = snapshot.main_risk
  if snapshot.required_guardrail is not None:
    payload["required_guardrail"] = snapshot.required_guardrail
  if snapshot.next_step is not None:
    payload["next_step"] = snapshot.next_step
  if snapshot.confidence is not None:
    payload["confidence"] = snapshot.confidence
  if snapshot.labels:
    payload["labels"] = list(snapshot.labels)

  obs_ctx: Dict[str, Any] = dict(snapshot.context_ref) if snapshot.context_ref else {}
  if snapshot.question is not None:
    obs_ctx["question"] = snapshot.question
  if snapshot.raw_text is not None:
    obs_ctx["raw_text"] = snapshot.raw_text

  return JudgmentTrunk(
    subject=snapshot.subject,
    observation=JudgmentObservation(pointer=None, context=obs_ctx),
    verdict=JudgmentVerdict(kind="judgment_snapshot", payload=payload),
    mechanism=JudgmentMechanism(mode="llm", model_id=None, policy_ref=None, context={}),
    effect="none",
    state="proposed",
    id=snapshot.judgment_id,
    created_at=snapshot.created_at,
    created_by=snapshot.created_by,
  )


def seat_judgment_to_trunk(seat: SeatJudgment) -> JudgmentTrunk:
  """Read-only Trunk view of a single council seat judgment."""
  base = judgment_snapshot_to_trunk(seat)
  mech_ctx = dict(base.mechanism.context)
  if seat.seat_id is not None:
    mech_ctx["seat_id"] = seat.seat_id
  if seat.profile_id is not None:
    mech_ctx["profile_id"] = seat.profile_id
  if seat.mandate_id is not None:
    mech_ctx["mandate_id"] = seat.mandate_id
  mech_ctx["seat_status"] = seat.status
  if seat.error is not None:
    mech_ctx["seat_error"] = seat.error
  if seat.duration_ms is not None:
    mech_ctx["duration_ms"] = seat.duration_ms

  return base.model_copy(
    update={
      "verdict": base.verdict.model_copy(update={"kind": "council_seat"}),
      "mechanism": base.mechanism.model_copy(update={"context": mech_ctx}),
    }
  )


def judgment_record_to_trunk(record: "JudgmentRecord") -> JudgmentTrunk:
  """Read-only Trunk view of an intake JudgmentRecord (lazy import avoids cycles)."""
  from local_ai.judgment import JudgmentRecord as _JudgmentRecord

  if not isinstance(record, _JudgmentRecord):
    raise TypeError(f"expected JudgmentRecord, got {type(record).__name__}")

  obs_ctx: Dict[str, Any] = {"domain": record.domain}
  if record.observation_ref:
    obs_ctx.update(dict(record.observation_ref))

  verdict_payload: Dict[str, Any] = {
    "interpretation": dict(record.interpretation),
    "proposed_action": dict(record.proposed_action),
    "confidence": record.confidence,
    "signal_codes": list(record.signal_codes),
    "interpretation_codes": list(record.interpretation_codes),
    "policy_codes": list(record.policy_codes),
  }
  if record.correction_note is not None:
    verdict_payload["correction_note"] = record.correction_note

  human = record.correction_note is not None or "interpretation_correction" in (
    record.interpretation_codes or []
  )
  mode: JudgmentMechanismMode = "human_override" if human else "rule"

  state: JudgmentState = "superseded" if record.superseded_by else "applied"

  return JudgmentTrunk(
    subject=SubjectRef(
      entity_type=record.domain,
      entity_id=record.entity_id,
      title=None,
      summary=None,
      extra={},
    ),
    observation=JudgmentObservation(pointer=record.entity_id, context=obs_ctx),
    verdict=JudgmentVerdict(kind="intake_judgment", payload=verdict_payload),
    mechanism=JudgmentMechanism(mode=mode, model_id=None, policy_ref=None, context={}),
    effect="persist_queue",
    state=state,
    id=record.id,
    created_at=record.created_at,
    created_by=None,
  )


from local_ai.council_run_artifact import CouncilRunArtifact

