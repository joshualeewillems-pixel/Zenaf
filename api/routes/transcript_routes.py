"""
Transcript sorter API: paste transcript → structured topics and candidate tasks/decisions.

Prefix: /transcripts
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from local_ai.transcripts import sort_transcript


router = APIRouter(prefix="/transcripts", tags=["transcripts"])


class TranscriptSortBody(BaseModel):
    raw_transcript_text: str
    call_context: Optional[Dict[str, Any]] = None
    speaker_labels: Optional[list[Dict[str, Any]]] = None


@router.post("/sort")
def post_sort_transcript(body: TranscriptSortBody):
    """
    Thin transcript sorter:
    - segments transcript into topics,
    - extracts deliverables, open questions, candidate tasks/decisions.

    Judgment-only; no storage and no auto-created tasks.
    """
    text = (body.raw_transcript_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="raw_transcript_text is required")
    return sort_transcript(text, call_context=body.call_context or {}, speaker_labels=body.speaker_labels or [])

