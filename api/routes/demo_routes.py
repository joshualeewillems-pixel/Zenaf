"""Anonymous landing-page demo: talk to the 7 base (aspirational) voices.

No auth. The visitor chats with stock archetype voices, watches their own
words woven back in [[u]]...[[/u]] markers (rendered as colored spans), and
after DEMO_EXCHANGE_CAP exchanges is invited to save the conversation —
"start your council with it, or continue the conversation in your account."

Guards (the demo is a cost center — Character.AI lesson):
- Session cap: DEMO_EXCHANGE_CAP exchanges per anonymous session.
- IP rate limit: DEMO_IP_MAX messages per DEMO_IP_WINDOW_S sliding window.
- Input cap: DEMO_MSG_MAX chars.
- Session transcripts are memory-only with SESSION_TTL_S TTL; nothing trains.
- In-memory stores: correct for a single instance; a multi-instance deploy
  would need a shared store (note, not a silent assumption).

The transcript belongs to the client for the save flow; the server keeps its
own copy only to sustain the conversation within the cap.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from local_ai.council.archetypes import (
    STOCK_ARCHETYPES,
    build_archetype_prompt_lines,
    compute_skeptic_weights,
    get_archetype,
    stock_archetype_ids,
    voice_color,
)

router = APIRouter(prefix="/demo", tags=["demo"])

#: Exchanges (user+assistant pairs) per anonymous session before the save prompt.
DEMO_EXCHANGE_CAP = 6
#: Max chars per visitor message.
DEMO_MSG_MAX = 2000
#: Sliding-window IP rate limit.
DEMO_IP_WINDOW_S = 3600
DEMO_IP_MAX = 30
#: Anonymous session transcript TTL (seconds).
SESSION_TTL_S = 3600

#: Marker convention for visitor words woven into a voice's reply.
WEAVE_OPEN = "[[u]]"
WEAVE_CLOSE = "[[/u]]"

_COLOR_WEAVE_INSTRUCTION = (
    "As you reply, when you genuinely echo, quote, or build directly on the "
    "visitor's own words or phrasing, wrap those exact words in [[u]]...[[/u]] "
    "markers. Use this sparingly — only for real echoes of their language, a "
    "few words at a time, when it sharpens the reply. Never wrap your own "
    "words, and never invent markers around paraphrase. Example: they say "
    '"I\'m drowning in ideas" and you reply "When you\'re [[u]]drowning in '
    'ideas[[/u]], the brave move is to pick one."'
)

# In-memory session + rate-limit stores (single-instance; see module docstring).
_sessions: dict[str, dict] = {}
_ip_hits: dict[str, list[float]] = {}


class DemoChatBody(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    voice: str = Field(default="mentor", max_length=32)
    message: str = Field(min_length=1, max_length=DEMO_MSG_MAX)


class DemoVoiceInfo(BaseModel):
    id: str
    name: str
    color: str
    frame: str


class DemoChatResponse(BaseModel):
    reply: str
    session_id: str
    voice: str
    voice_color: str
    exchanges_used: int
    exchanges_left: int
    capped: bool = False


def _client_ip(request: Request) -> str:
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if fwd:
        return fwd
    return (request.client.host if request.client else "unknown")


def _check_ip_limit(ip: str) -> None:
    now = time.time()
    hits = [t for t in _ip_hits.get(ip, []) if now - t < DEMO_IP_WINDOW_S]
    if len(hits) >= DEMO_IP_MAX:
        raise HTTPException(
            status_code=429,
            detail="Demo rate limit reached. Come back in a bit — or save the conversation and keep going in your account.",
        )
    hits.append(now)
    _ip_hits[ip] = hits


def _get_session(session_id: str | None) -> tuple[str, dict]:
    now = time.time()
    # Opportunistic expiry sweep.
    expired = [sid for sid, s in _sessions.items() if now - s["created"] > SESSION_TTL_S]
    for sid in expired:
        del _sessions[sid]
    if session_id and session_id in _sessions:
        return session_id, _sessions[session_id]
    sid = uuid.uuid4().hex
    sess = {"created": now, "transcript": [], "exchanges": 0}
    _sessions[sid] = sess
    return sid, sess


def _build_demo_prompt(voice_id: str, transcript: list[dict]) -> str:
    arch = get_archetype(voice_id)
    weights_override = None
    if arch is not None and arch.strand_weights is None:
        # Skeptic: no user data exists anonymously — uniform fallback weights.
        weights_override = compute_skeptic_weights(None)
    lines = build_archetype_prompt_lines(voice_id, weights_override=weights_override)
    prompt = [
        "You are a voice in Zenaf's council, talking to a first-time visitor "
        "on the landing page. They have no account and no training data — you "
        "are the aspirational base voice, not their trained self.",
        "",
        *lines,
        "",
        _COLOR_WEAVE_INSTRUCTION,
        "",
        "Keep replies short (2-4 sentences) — this is a first taste, not a deep session.",
    ]
    if transcript:
        prompt.append("")
        prompt.append("Conversation so far:")
        for turn in transcript[-10:]:
            prompt.append(f"{turn['role']}: {turn['content']}")
    return "\n".join(prompt)


@router.get("/voices", response_model=list[DemoVoiceInfo])
def demo_voices() -> list[DemoVoiceInfo]:
    """The 7 base voices with their canonical colors — no auth."""
    return [
        DemoVoiceInfo(
            id=a.id,
            name=a.display_name,
            color=voice_color(a.id),
            frame=a.prompt_frame,
        )
        for a in STOCK_ARCHETYPES
    ]


@router.post("/chat", response_model=DemoChatResponse)
def demo_chat(body: DemoChatBody, request: Request) -> DemoChatResponse:
    """One anonymous demo exchange with a base voice."""
    _check_ip_limit(_client_ip(request))

    voice_id = (body.voice or "").strip().lower()
    if voice_id not in stock_archetype_ids():
        raise HTTPException(status_code=422, detail=f"Unknown voice: {body.voice!r}")

    session_id, sess = _get_session(body.session_id)
    if sess["exchanges"] >= DEMO_EXCHANGE_CAP:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "cap_reached",
                "message": (
                    "That's the demo — save this conversation to keep going: "
                    "start your council with it, or continue the conversation "
                    "in your account."
                ),
            },
        )

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message is empty.")

    transcript = sess["transcript"]
    system = _build_demo_prompt(voice_id, transcript)
    full_prompt = f"{system}\n\nVisitor: {message}\n{get_archetype(voice_id).display_name}:"

    try:
        from local_ai.providers import meta as _meta

        # api_key="" -> server env key (META_API_KEY); the platform pays.
        reply = _meta.generate("", full_prompt, timeout=60).strip()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — loud failure, honest 502
        raise HTTPException(status_code=502, detail=f"Demo voice unavailable: {exc}")

    transcript.append({"role": "visitor", "content": message})
    transcript.append({"role": voice_id, "content": reply})
    sess["exchanges"] += 1
    left = DEMO_EXCHANGE_CAP - sess["exchanges"]

    return DemoChatResponse(
        reply=reply,
        session_id=session_id,
        voice=voice_id,
        voice_color=voice_color(voice_id),
        exchanges_used=sess["exchanges"],
        exchanges_left=left,
        capped=left == 0,
    )
