"""Aggregate artifact for a multi-seat council run (returned from run_council when requested)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from local_ai.judgment_substrate import JudgmentSnapshot, SeatJudgment, SubjectRef


class CouncilRunArtifact(BaseModel):
    """Aggregate artifact for a council run (for VE snapshots and analysis)."""

    question: str
    subject: Optional[SubjectRef] = None
    context_ref: Dict[str, Any] = Field(default_factory=dict)

    seats: List[SeatJudgment] = Field(default_factory=list)
    synthesis_text: Optional[str] = None
    synthesis_summary: Optional[JudgmentSnapshot] = None

    # Aggregated judgment
    recommended_action: Optional[str] = None
    distinct_positions: List[str] = Field(default_factory=list)
    positions_disagree: bool = False

    # Execution diagnostics
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None
