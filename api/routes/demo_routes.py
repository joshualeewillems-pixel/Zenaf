"""Anonymous landing-page demo: talk to the 7 base (aspirational) voices.

No auth. The visitor chats with stock archetype voices, watches their own
words woven back in [[u]]...[[/u]] markers (rendered as colored spans), and
after DEMO_EXCHANGE_CAP exchanges is invited to save the conversation —
"start your council with it, or continue the conversation in your account."

The council shares a rolling memory: after every exchange a background worker
folds what was established (visitor's aims, open tensions, their exact phrases)
into the session's memory, and every voice's prompt builds on it — perspectives
accumulate toward a solution instead of restarting each turn. The weave
instruction densifies as the conversation deepens.

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

import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
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
#: Set from Joshua's 25c/visitor budget (2026-10-16): ~12 exchanges lands well
#: under it at low reasoning effort, and feels like a real conversation.
DEMO_EXCHANGE_CAP = 12
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
    "visitor's own words or phrasing, wrap those words in [[u]]...[[/u]] markers. "
    "Adjust pronouns (my→your) and grammar lightly so the echo reads naturally "
    "inside your own sentence — a copied 'my' that should be 'your' breaks the spell. "
    "Use this sparingly — only for real echoes of their language, a few words at "
    "a time, when it sharpens the reply. Never wrap the visitor's question itself "
    "or a bare prompt ('what's your opinion?', 'final thoughts?', 'what's the "
    "difference?') — only substantive phrases that carry meaning. Never wrap your "
    "own words, and never invent markers around paraphrase. Example: they say "
    '"I\'m drowning in ideas" and you reply "When you\'re [[u]]drowning in '
    'ideas[[/u]], the brave move is to pick one."'
)

_WEAVE_CLOSE_RE = None  # compiled lazily below to keep module import light


def _sanitize_weave(text: str) -> str:
    """Normalize model-generated [[u]]...[[/u]] markers.

    When weaving densely the model occasionally emits malformed closings
    ([/u]], [/[/u]]). Normalize known variants to the canonical close, and
    drop orphan opens so broken markup never reaches the visitor.
    """
    import re

    global _WEAVE_CLOSE_RE
    if _WEAVE_CLOSE_RE is None:
        _WEAVE_CLOSE_RE = re.compile(r"\[/\[/u\]\]|\[/u\]\]|\[\[/u\]\]")
    parts = text.split(WEAVE_OPEN)
    out = [parts[0]]
    for seg in parts[1:]:
        m = _WEAVE_CLOSE_RE.search(seg)
        if m:
            out.append(WEAVE_OPEN + seg[: m.start()] + WEAVE_CLOSE + seg[m.end() :])
        else:
            out.append(seg)  # orphan open marker dropped, words kept
    return "".join(out)

# In-memory session + rate-limit stores (single-instance; see module docstring).
#: session -> {"created": float, "transcript": [...], "exchanges": int, "memory": str}
_sessions: dict[str, dict] = {}
_ip_hits: dict[str, list[float]] = {}
#: Claim codes: code -> {"transcript": str, "created": float}. TTL 24h, single-use.
_claims: dict[str, dict] = {}
CLAIM_TTL_S = 86400
_CLAIM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/l


class DemoChatBody(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    voice: str = Field(default="mentor", max_length=32)
    # Empty message = "speak" turn: the tapped voice responds to the
    # conversation so far with no new visitor message.
    message: str = Field(default="", max_length=DEMO_MSG_MAX)
    # Speak-turn mode: "respond" (voice answers the conversation) or
    # "question" (voice asks the visitor one penetrating question). Ignored
    # for normal typed messages.
    mode: str = Field(default="respond", max_length=16)


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
    sess = {"created": now, "transcript": [], "exchanges": 0, "memory": ""}
    _sessions[sid] = sess
    return sid, sess


def _weave_instruction(exchanges_used: int) -> str:
    """Weave instruction, densifying as the conversation deepens.

    Early on the voice echoes sparingly; once the council has learned the
    visitor's language, it should draw freely on their earlier words.
    """
    if exchanges_used >= 3:
        return _COLOR_WEAVE_INSTRUCTION + (
            " The conversation is deepening — draw freely on the visitor's earlier "
            "words and the council memory below. Echo their phrasing wherever it "
            "sharpens the reply; the weave should densify as you learn their language."
        )
    return _COLOR_WEAVE_INSTRUCTION


def _build_demo_prompt(
    voice_id: str,
    transcript: list[dict],
    memory: str = "",
    exchanges_used: int = 0,
    speak: bool = False,
    question_mode: bool = False,
) -> str:
    """System prompt for one demo turn.

    speak=True: the visitor tapped this voice with no new message — the voice
    responds to the conversation so far from its own perspective.
    question_mode=True (with speak): instead of responding, the voice asks the
    visitor one penetrating question from its perspective.
    """
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
    ]
    if speak:
        if question_mode:
            prompt.append(
                "The visitor has tapped you to question them — no new message. Ask the "
                "visitor ONE penetrating question from your perspective: the single "
                "question that would most unlock this situation. Let your defining "
                "question guide you and draw on the council memory. Output the question "
                "plus at most one short sentence of context — no advice, no preamble."
            )
        else:
            prompt.append(
                "The visitor has tapped you to speak — no new message. Respond to the "
                "conversation so far from your perspective: advance it, challenge it, "
                "or deepen it. Do not summarize what has been said."
            )
        prompt.append("")
    if memory:
        prompt.append(
            "Council memory — what the council has established so far. Build on this; "
            "do not restart the conversation, and do not contradict what the council "
            "has already learned unless the visitor corrects it:"
        )
        prompt.append(memory[:1200])
        prompt.append("")
    prompt.append(_weave_instruction(exchanges_used))
    prompt.append("")
    prompt.append("Keep replies short (2-4 sentences) — this is a first taste, not a deep session.")
    if transcript:
        prompt.append("")
        prompt.append("Conversation so far:")
        for turn in transcript[-10:]:
            prompt.append(f"{turn['role']}: {turn['content']}")
    return "\n".join(prompt)


def _refresh_council_memory(session_id: str) -> None:
    """Fold the latest exchange into the session's shared council memory.

    Runs in a daemon thread after the reply is delivered — best-effort, never
    raises into the request path. The memory is what lets each voice build on
    the conversation's arc instead of only the last message.
    """
    try:
        from local_ai.providers import meta as _meta

        sess = _sessions.get(session_id)
        if not sess or not sess["transcript"]:
            return
        recent = sess["transcript"][-4:]  # last two exchanges
        convo_lines = []
        for turn in recent:
            role = turn["role"]
            if role == "visitor":
                speaker = "Visitor"
            else:
                arch = get_archetype(role)
                speaker = arch.display_name if arch else role
            convo_lines.append(f"{speaker}: {(turn['content'] or '')[:500]}")
        prompt = (
            "You are the council's shared memory keeper. Update the council's running "
            "memory in exactly 3 short bullets: (1) what the visitor seems to want or "
            "is circling around, (2) open tensions or unanswered questions, "
            "(3) exact short phrases of the visitor's worth echoing back later.\n\n"
            f"Previous memory:\n{(sess.get('memory') or '(none yet)')[:800]}\n\n"
            f"Latest exchanges:\n" + "\n".join(convo_lines) + "\n\n"
            "Updated memory (3 bullets, terse):"
        )
        mem = _meta.generate("", prompt, timeout=45, reasoning_effort="minimal").strip()
        if mem:
            sess["memory"] = mem[:1200]
    except Exception:
        pass  # memory is best-effort; the conversation must never break


def _kick_memory_refresh(session_id: str) -> None:
    """Refresh council memory off the request path."""
    t = threading.Thread(target=_refresh_council_memory, args=(session_id,), daemon=True)
    t.start()


def _speak_turn_params(body: DemoChatBody, sess: dict) -> tuple[bool, bool]:
    """(speak_mode, question_mode) for a demo turn.

    speak_mode: empty message — the tapped voice addresses the conversation.
    question_mode: speak turn where the voice asks the visitor one question.
    Raises 422 if a speak turn arrives with no conversation yet.
    """
    message = body.message.strip()
    speak_mode = not message
    if speak_mode and not sess["transcript"]:
        raise HTTPException(
            status_code=422,
            detail="Say something first — then tap any voice to have them speak.",
        )
    mode = (body.mode or "respond").strip().lower()
    question_mode = speak_mode and mode == "question"
    return speak_mode, question_mode


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


def _format_transcript_text(transcript: list[dict]) -> str:
    """Demo transcript as plain training text. [[u]] markers are display-only."""
    lines = []
    for turn in transcript:
        role = turn.get("role", "")
        content = (turn.get("content") or "").replace(WEAVE_OPEN, "").replace(WEAVE_CLOSE, "")
        speaker = "You" if role == "visitor" else get_archetype(role).display_name if get_archetype(role) else role
        lines.append(f"{speaker}: {content.strip()}")
    return "\n\n".join(lines).strip()


def _new_claim_code() -> str:
    import secrets

    for _ in range(20):
        code = "".join(secrets.choice(_CLAIM_ALPHABET) for _ in range(6))
        if code not in _claims:
            return code
    raise HTTPException(status_code=503, detail="Could not issue a claim code. Try again.")


class DemoSaveBody(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


class DemoSaveResponse(BaseModel):
    claim_code: str
    expires_in_hours: int = 24


class DemoClaimBody(BaseModel):
    claim_code: str = Field(min_length=6, max_length=12)


class DemoClaimResponse(BaseModel):
    transcript: str
    title: str = "Landing demo conversation"


@router.post("/save", response_model=DemoSaveResponse)
def demo_save(body: DemoSaveBody) -> DemoSaveResponse:
    """Freeze an anonymous demo transcript under a claim code.

    No auth. The visitor gets a short code; entering it in their account
    (Foundation tab) pulls the transcript into the intake pipeline —
    "continue the conversation." Single-use, 24h TTL.
    """
    now = time.time()
    expired = [c for c, v in _claims.items() if now - v["created"] > CLAIM_TTL_S]
    for c in expired:
        del _claims[c]

    sess = _sessions.get((body.session_id or "").strip())
    if not sess or not sess["transcript"]:
        raise HTTPException(status_code=404, detail="Demo session not found or empty.")
    text = _format_transcript_text(sess["transcript"])
    if not text:
        raise HTTPException(status_code=422, detail="Nothing to save yet — say something first.")

    code = _new_claim_code()
    _claims[code] = {"transcript": text, "created": now}
    return DemoSaveResponse(claim_code=code)


@router.post("/claim", response_model=DemoClaimResponse)
def demo_claim(
    body: DemoClaimBody,
    current_user: dict = Depends(get_current_user),
) -> DemoClaimResponse:
    """Claim a demo transcript into the caller's account (auth required).

    Returns the transcript text; the frontend then POSTs it to
    /agents/connect/share-text — the same intake path as the bookmarklet.
    Single-use: the claim code is consumed.
    """
    code = (body.claim_code or "").strip().upper()
    entry = _claims.get(code)
    if not entry:
        raise HTTPException(status_code=404, detail="Claim code not found or expired.")
    if time.time() - entry["created"] > CLAIM_TTL_S:
        del _claims[code]
        raise HTTPException(status_code=404, detail="Claim code expired.")
    del _claims[code]
    return DemoClaimResponse(transcript=entry["transcript"])


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
    speak_mode, question_mode = _speak_turn_params(body, sess)

    transcript = sess["transcript"]
    system = _build_demo_prompt(
        voice_id,
        transcript,
        sess.get("memory", ""),
        sess["exchanges"],
        speak=speak_mode,
        question_mode=question_mode,
    )
    if speak_mode:
        full_prompt = f"{system}\n{get_archetype(voice_id).display_name}:"
    else:
        full_prompt = f"{system}\n\nVisitor: {message}\n{get_archetype(voice_id).display_name}:"

    try:
        from local_ai.providers import meta as _meta

        # api_key="" -> server env key (META_API_KEY); the platform pays.
        # reasoning_effort="low": demo replies are 2-4 sentences; low effort
        # cuts both latency and cost (reasoning tokens bill as output).
        reply = _sanitize_weave(
            _meta.generate("", full_prompt, timeout=60, reasoning_effort="low").strip()
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — loud failure, honest 502
        raise HTTPException(status_code=502, detail=f"Demo voice unavailable: {exc}")

    if not speak_mode:
        transcript.append({"role": "visitor", "content": message})
    transcript.append({"role": voice_id, "content": reply})
    sess["exchanges"] += 1
    _kick_memory_refresh(session_id)
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


@router.post("/stream")
def demo_stream(body: DemoChatBody, request: Request) -> StreamingResponse:
    """Streaming twin of /demo/chat: Server-Sent Events with token deltas.

    Same body, same guards. Events:
      data: {"type": "token", "text": "..."}   — reply chunks as they arrive
      data: {"type": "done", "session_id": ..., "voice": ..., "voice_color": ...,
             "exchanges_used": N, "exchanges_left": M, "capped": bool}
    A capped session returns 403 JSON (same as /demo/chat), not SSE.
    """
    import json as _json

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
    speak_mode, question_mode = _speak_turn_params(body, sess)

    transcript = sess["transcript"]
    system = _build_demo_prompt(
        voice_id,
        transcript,
        sess.get("memory", ""),
        sess["exchanges"],
        speak=speak_mode,
        question_mode=question_mode,
    )
    if speak_mode:
        full_prompt = f"{system}\n{get_archetype(voice_id).display_name}:"
    else:
        full_prompt = f"{system}\n\nVisitor: {message}\n{get_archetype(voice_id).display_name}:"

    def event_stream():
        from local_ai.providers import meta as _meta

        chunks: list[str] = []
        try:
            # api_key="" -> server env key; low effort keeps latency and cost down.
            for chunk in _meta.generate_stream(
                "", full_prompt, timeout=90, reasoning_effort="low"
            ):
                chunks.append(chunk)
                yield f"data: {_json.dumps({'type': 'token', 'text': chunk})}\n\n"
        except Exception as exc:  # noqa: BLE001 — honest error event, then stop
            yield f"data: {_json.dumps({'type': 'error', 'detail': f'Demo voice unavailable: {exc}'})}\n\n"
            return
        # Sanitize the assembled reply: mid-stream chunks are raw, so the done
        # event carries the corrected full text for the client to settle on.
        reply = _sanitize_weave("".join(chunks).strip())
        if not speak_mode:
            transcript.append({"role": "visitor", "content": message})
        transcript.append({"role": voice_id, "content": reply})
        sess["exchanges"] += 1
        left = DEMO_EXCHANGE_CAP - sess["exchanges"]
        done = {
            "type": "done",
            "reply": reply,
            "session_id": session_id,
            "voice": voice_id,
            "voice_color": voice_color(voice_id),
            "exchanges_used": sess["exchanges"],
            "exchanges_left": left,
            "capped": left == 0,
        }
        yield f"data: {_json.dumps(done)}\n\n"
        _kick_memory_refresh(session_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
