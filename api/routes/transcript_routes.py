"""
Transcript sorter API: paste transcript → structured topics and candidate tasks/decisions.

Prefix: /transcripts

DEPRECATION NOTICE (2026-10-12, agent-economy refocus): the transcript sorter is
PARKED — deprioritized, not maintained. The backend was relocated to
parked/local_ai-transcripts/ and is loaded from there for backward compatibility.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Parked module: load from parked/local_ai-transcripts (relocated 2026-10-12).
_PARKED_TRANSCRIPTS = str(Path(__file__).resolve().parent.parent.parent / "parked" / "local_ai-transcripts")
if _PARKED_TRANSCRIPTS not in sys.path:
    sys.path.insert(0, _PARKED_TRANSCRIPTS)
from sorter import sort_transcript  # noqa: E402  (parked module)


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

