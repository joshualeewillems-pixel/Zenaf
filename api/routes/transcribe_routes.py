"""
Speech-to-text for Vision & Execution: multipart audio in, transcript JSON out.
Uses OpenAI Whisper when an API key is available for the signed-in user.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.routes.auth_routes import get_current_user
from local_ai.execution_policy.openai_credentials import resolve_openai_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["transcribe"])


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    raw = await file.read()
    if not raw or len(raw) < 32:
        raise HTTPException(status_code=400, detail="Empty or too-short audio payload")

    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    api_key, _src = resolve_openai_api_key(str(user_id))
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="No OpenAI API key configured for transcription. Set OPENAI_API_KEY or add an OpenAI key in Settings.",
        )

    filename = file.filename or "audio.webm"
    content_type = file.content_type or "application/octet-stream"

    try:
        import httpx
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail="Transcription requires the 'httpx' package, which is not installed.",
        ) from e

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (filename, raw, content_type)},
                data={"model": "whisper-1"},
            )
    except httpx.RequestError as e:
        logger.warning("transcribe request failed: %s", e)
        raise HTTPException(status_code=502, detail="Could not reach transcription service") from e

    if r.status_code != 200:
        snippet = (r.text or "")[:800]
        logger.warning("transcribe provider error %s: %s", r.status_code, snippet)
        raise HTTPException(status_code=502, detail="Transcription failed")

    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Invalid transcription response")

    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str):
        raise HTTPException(status_code=502, detail="Missing transcript in provider response")

    return {"transcript": text.strip()}
