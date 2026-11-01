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

The same background generation also runs the progression reader: it judges
the conversation's arc and stores a per-session verdict — the set of seats
whose move the progression could genuinely use next (the live forks, with a
short reason each). Clients light a "!" over those seats; the visitor chooses
the road. The reader is background-only, best-effort, and restrained by
design: an empty verdict (silence) is common and valid.

Fork choices are a training metric, so every stored verdict also appends a
fork event to the session's log ({exchange, offered, reasons, at,
resolution}). The visitor's NEXT request resolves the outstanding event —
chose:<seat> (tapped an offered seat), off_menu:<seat> (tapped another),
self_directed (typed their own message) — a revealed preference with the
situation and the alternatives attached. Events are session-side only: the
claim flow's payload is the visitor's own words, kept verbatim for intake,
so fork metadata deliberately does not ride into it.

Guards (the demo is a cost center — Character.AI lesson):
- Session cap: DEMO_EXCHANGE_CAP exchanges per anonymous session.
- IP rate limit: DEMO_IP_MAX messages per DEMO_IP_WINDOW_S sliding window.
- Input cap: DEMO_MSG_MAX chars.
- Session transcripts are memory-only with SESSION_TTL_S TTL; nothing trains.
- Claim codes persist in SQLite (data/demo/demo_claims.db) so deploys don't
  strand outstanding codes; still single-instance in the sense that a
  multi-instance deploy would need a shared store (note, not a silent
  assumption).
- In-memory stores: correct for a single instance; a multi-instance deploy
  would need a shared store (note, not a silent assumption).

The transcript belongs to the client for the save flow; the server keeps its
own copy only to sustain the conversation within the cap.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.conversation.weave import sanitize_weave as _sanitize_weave
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

# Shared with the authenticated chat path (local_ai/conversation/reply.py):
# one sanitizer for every surface that renders woven replies, imported above
# as _sanitize_weave so existing tests and call sites are untouched.

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

# (moved to local_ai.conversation.weave.sanitize_weave; demo_routes keeps the
# _sanitize_weave alias so existing tests and call sites are untouched)

# In-memory session + rate-limit stores (single-instance; see module docstring).
#: session -> {"created": float, "transcript": [...], "exchanges": int,
#:             "memory": str, "progression": {...}, "forks": [...],
#:             "last_register_flag": ...}
_sessions: dict[str, dict] = {}
_ip_hits: dict[str, list[float]] = {}
#: Claim-code TTL: 24h, single-use.
CLAIM_TTL_S = 86400
_CLAIM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/l

#: Claim codes persist in SQLite (data/demo/demo_claims.db) — the old
#: in-memory dict was wiped by every staging deploy, stranding codes.
_DEMO_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "demo"
_DEMO_CLAIMS_DB = _DEMO_DATA_DIR / "demo_claims.db"

_CLAIM_SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_claims (
  code TEXT PRIMARY KEY,
  transcript TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""


class DemoClaimStore:
    """SQLite-backed store for demo claim codes.

    Follows the per-domain sqlite convention (conversations, followthrough):
    one connection guarded by a lock, CREATE TABLE IF NOT EXISTS on init.
    Single-use and 24h TTL are enforced against the table.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEMO_CLAIMS_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_CLAIM_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def sweep_expired(self, now: float | None = None) -> int:
        """Delete expired rows. Returns the number removed."""
        cutoff = (time.time() if now is None else now) - CLAIM_TTL_S
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM demo_claims WHERE created_at <= ?", (cutoff,)
            )
            self._conn.commit()
            return cur.rowcount or 0

    def exists(self, code: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM demo_claims WHERE code = ?", (code,)
            ).fetchone()
            return row is not None

    def issue(self, code: str, transcript: str, now: float | None = None) -> None:
        ts = time.time() if now is None else now
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO demo_claims (code, transcript, created_at)"
                " VALUES (?, ?, ?)",
                (code, transcript, ts),
            )
            self._conn.commit()

    def consume(self, code: str, now: float | None = None) -> str | None:
        """Single-use claim: returns the transcript, or None if unknown/expired.

        The row is deleted whether or not it was still valid — a code works once.
        """
        ts = time.time() if now is None else now
        with self._lock:
            row = self._conn.execute(
                "SELECT transcript, created_at FROM demo_claims WHERE code = ?",
                (code,),
            ).fetchone()
            self._conn.execute("DELETE FROM demo_claims WHERE code = ?", (code,))
            self._conn.commit()
        if row is None:
            return None
        if ts - row["created_at"] > CLAIM_TTL_S:
            return None
        return row["transcript"]


_claim_store: DemoClaimStore | None = None
_claim_store_lock = threading.Lock()


def _get_claim_store() -> DemoClaimStore:
    """Lazy singleton — avoids creating data dirs at import time, since this
    module is imported widely (including by tests)."""
    global _claim_store
    if _claim_store is None:
        with _claim_store_lock:
            if _claim_store is None:
                _claim_store = DemoClaimStore()
    return _claim_store


class DemoChatBody(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    voice: str = Field(default="mentor", max_length=32)
    # Empty message = "speak" turn: the tapped voice responds to the
    # conversation so far with no new visitor message.
    message: str = Field(default="", max_length=DEMO_MSG_MAX)
    # Speak-turn mode: "respond" (voice answers the conversation) or
    # "question" (voice asks the visitor one penetrating question). Applies
    # to voice-chip taps (empty message) AND to typed messages.
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
    #: Seat whose register a speak-turn reply substantially sat in, parsed
    #: from the reply's [[register:<seat>]] marker (stripped from `reply`);
    #: None when the reply stayed in the speaker's own register. The client
    #: lights a "!" over that seat's chip. Always None outside speak turns
    #: in respond mode.
    register_flag: str | None = None
    #: The progression reader's latest verdict for this session (assessed in
    #: the background after the PREVIOUS exchange — the current exchange's
    #: verdict lands later; poll GET /demo/progression for it). A set of
    #: seat ids whose move the progression could use next, with a short
    #: situation reason each. Empty = silence, a common and valid verdict.
    progression_flags: list[str] = Field(default_factory=list)
    progression_reasons: dict[str, str] = Field(default_factory=dict)


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
    sess = {
        "created": now,
        "transcript": [],
        "exchanges": 0,
        "memory": "",
        "progression": {"flags": [], "reasons": {}, "exchanges_used": 0},
        "forks": [],
        "last_register_flag": None,
    }
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


def _last_voice_turn(transcript: list[dict]) -> dict | None:
    """Most recent voice (non-visitor) turn in the transcript, or None."""
    for turn in reversed(transcript):
        if turn.get("role") != "visitor":
            return turn
    return None


#: Conductor orchestration (conductor-orchestration v1, mechanism 1):
#: appended to the Conductor's speak-turn prompt in respond mode only.
#: The Conductor conducts — it finds the shape underneath the disagreement
#: instead of smoothing it away. This operationalizes its shadow line
#: (PR #169): subordinating the ensemble to its own conception of harmony
#: by forcing resolution is its characteristic failure mode, so the prompt
#: names the opposite duty explicitly.
_CONDUCTOR_ORCHESTRATION_BLOCK = (
    "You conduct this council — you do not smooth it. Name the standing "
    "disagreements in this thread explicitly, and let them stand where they "
    "stand: your job is the shape underneath the disagreement, never a "
    "consensus the thread hasn't reached. Never declare agreement that isn't "
    "there. If another voice here has moved your own position, say what "
    "changed it, in plain words. A tension left standing is a result, not a "
    "failure."
)

#: Each seat's home ground, for the speak-turn recusal rule
#: (conductor-orchestration v1, mechanism 2). The Skeptic is deliberately
#: absent: examining is always its ground, so it never recuses.
_SEAT_TERRITORY: dict[str, str] = {
    "mentor": "what a thing can teach, and the long view",
    "champion": "what is worth fighting for, and the brave move",
    "guardian": "what must be protected, and who gets hurt",
    "maverick": "whether the rules are wrong, and the door nobody questions",
    "ambassador": "translating between worlds, and what brings people together",
    "conductor": "how the parts fit into a whole",
}


def _recusal_instruction(voice_id: str) -> str:
    """Speak-turn recusal permission for one seat; "" for the Skeptic.

    A recusal is a complete one-sentence reply naming whose ground the
    topic is — it happens inside the turn's single generation, never as an
    extra call. It is deliberately narrow: plainly another seat's ground
    only, never a dodge for a hard question on the seat's own ground.
    """
    territory = _SEAT_TERRITORY.get(voice_id)
    if not territory:
        return ""
    return (
        f"Your home ground is {territory}. If what you are being asked to "
        "address is squarely another seat's ground and not yours, you may "
        "recuse instead of bluffing an answer: one short sentence naming "
        "whose ground it is ('This is the Guardian's ground — protection, "
        "not translation'), and nothing more — a recusal is a complete "
        "reply. Recuse rarely: only when the topic is plainly another "
        "seat's, never to dodge a hard question on your own ground."
    )


#: Each seat's register, for the speak-turn register flag (companion to
#: conductor-orchestration v1). Same ground as _SEAT_TERRITORY, plus the
#: Skeptic: it never recuses, but a reply can still land in its register —
#: examining is a register any seat can drift into.
_SEAT_REGISTERS: dict[str, str] = {
    **_SEAT_TERRITORY,
    "skeptic": "examining what is being assumed, and whether it holds up",
}

#: Machine-read marker a speak-turn voice appends on its own final line when
#: its answer substantially sits in another seat's register:
#: [[register:<seat_id>]]. Stripped before the reply is shown or stored;
#: surfaced to the client as DemoChatResponse.register_flag (chat) or the
#: done event's register_flag (stream), which lights a "!" over that seat's
#: chip. The strict pattern is the only flag-bearing shape; the loose one
#: exists so marker-shaped remnants (empty/unknown seat, missing bracket)
#: never leak into visible text either.
_REGISTER_MARKER_RE = re.compile(r"\[\[\s*register\s*:\s*([A-Za-z_]+)\s*\]\]")
_REGISTER_MARKER_LOOSE_RE = re.compile(r"\[\[\s*register\s*:[^\]\n]*\]?\]?")
_REGISTER_MARKER_OPEN = "[[register:"


def _register_flag_instruction(voice_id: str) -> str:
    """Speak-turn register flag instruction for one seat.

    The listener-side twin of recusal: recusal is the speaker yielding its
    turn to the seat whose ground the topic is; the register flag is a
    delivered answer pointing at whose register it actually did its work
    in. Detection is prompt-level, inside the turn's single generation —
    no extra call. The marker is machine-read and stripped before the
    visitor sees the reply; the visitor is never told it exists.
    """
    others = []
    for seat_id, register in _SEAT_REGISTERS.items():
        if seat_id == voice_id:
            continue
        arch = get_archetype(seat_id)
        name = arch.display_name if arch else seat_id
        others.append(f"the {name} ({seat_id}) — {register}")
    return (
        "Last, a silent judgment: once your answer is composed, ask whose "
        "register it substantially sits in. The other seats' registers: "
        + "; ".join(others)
        + ". If the substance of your answer does its work in another "
        "seat's register — not a passing mention of their theme, not a "
        "brief quote of their view, but the answer itself thinking the way "
        "they think — append exactly one marker on its own final line, "
        "after everything else: [[register:seat_id]], using that seat's "
        "id from the list. At most one marker, for the strongest case "
        "only, and never your own seat. Most answers sit in your own "
        "register and carry no marker — the flag is rare and literal, "
        "never a habit. If your whole reply is a hand-off — one sentence "
        "naming whose ground this is, instead of an answer — add no "
        "marker: the hand-off already names the seat. Never mention the "
        "marker or explain it."
    )


#: A recusal's shape, per the recusal rule above: one short sentence naming
#: whose ground the topic is ("This is the Guardian's ground — ...").
_RECUSAL_SHAPE_RE = re.compile(
    r"^(this is|that is|that's)\b[^.]*\bground\b", re.IGNORECASE
)


def _looks_like_recusal(text: str) -> bool:
    """True when the visible reply is a recusal. A recusal already names
    its seat, so it never also carries a register flag."""
    t = " ".join(text.split())
    if len(t) > 240:
        return False
    if len([s for s in t.split(".") if s.strip()]) > 1:
        return False
    return bool(_RECUSAL_SHAPE_RE.match(t))


def _extract_register_flag(
    text: str, speaker_id: str, *, enabled: bool = True
) -> tuple[str, str | None]:
    """Split a raw reply into (visible text, register flag seat id | None).

    The flag is the first well-formed [[register:<seat>]] marker naming a
    real seat other than the speaker. Every marker-shaped remnant —
    malformed, unknown seat, self-flag, duplicate — is stripped from the
    visible text: marker text never reaches the visitor, whether or not
    the turn was allowed to flag (enabled=False strips but never flags).
    A recusal never carries a flag.
    """
    flag: str | None = None
    if enabled:
        for m in _REGISTER_MARKER_RE.finditer(text):
            seat = m.group(1).strip().lower()
            if seat in stock_archetype_ids() and seat != speaker_id:
                flag = seat
                break
    cleaned = _REGISTER_MARKER_LOOSE_RE.sub("", text)
    # Removing a final-line marker can leave dangling blank lines behind.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if flag is not None and _looks_like_recusal(cleaned):
        flag = None
    return cleaned, flag


def _split_stream_safe(buffer: str) -> tuple[str, str]:
    """Split pending streamed text into (safe to emit, hold back).

    The register marker rides the reply's final line and may arrive split
    across chunks; hold back any tail that could still grow into one so it
    never reaches the client in a token event. Whatever stays held back at
    end-of-stream is dropped from the token flow — the done event carries
    the canonical (stripped) reply and the parsed flag either way, the
    same settle-on-done pattern the [[u]] weave markers already use.
    """
    m = re.search(r"\[\[\s*register\s*:[^\]]*\]{0,2}\s*$", buffer)
    if m:
        return buffer[: m.start()], buffer[m.start() :]
    # A trailing partial of the "[[register:" opener itself ("[[", "[[r",
    # "[[reg", ...) could still grow into the marker — hold it back too.
    for n in range(len(_REGISTER_MARKER_OPEN) - 1, 0, -1):
        if buffer.endswith(_REGISTER_MARKER_OPEN[:n]):
            return buffer[:-n], buffer[-n:]
    return buffer, ""


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
    responds to the LAST voice response in the transcript (named and quoted),
    not the conversation in general.
    question_mode=True: instead of answering, the voice asks the visitor one
    penetrating question. With speak=True the question targets the last voice
    response; with a typed message it addresses that message —
    the message is not answered, it is questioned.
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
        last = _last_voice_turn(transcript)
        if last is not None:
            last_id = str(last.get("role") or "")
            last_arch = get_archetype(last_id)
            last_name = last_arch.display_name if last_arch else last_id
            quote = (last.get("content") or "").strip().replace("\n", " ")
            if len(quote) > 220:
                quote = quote[:220].rstrip() + "…"
            target = "your own last response" if last_id == voice_id else f"{last_name}'s last response"
            if question_mode:
                prompt.append(
                    "The visitor has tapped you to question the thread — no new message. "
                    f"Ask ONE penetrating question about {target}: \"{quote}\" — the "
                    "single question that would most unlock what was said. Let your "
                    "defining question guide you. Output the question plus at most one "
                    "short sentence of context — no advice, no preamble. "
                    "Speak to the visitor, never about the other voices: do not narrate "
                    "what another voice said, asked, or assumes ('Ambassador assumes...', "
                    "'Mentor is asking...'). Take up the point itself and address the "
                    "visitor directly. Your question must open a door that is still "
                    "closed — bring something new that the visitor hasn't said and no "
                    "voice has named yet: a fact, a tradeoff, a consequence, a stance. "
                    "Never rephrase the previous voice's question in different words."
                )
            else:
                prompt.append(
                    "The visitor has tapped you to respond — no new message. "
                    f"Respond to {target} specifically: \"{quote}\" — from your "
                    "perspective: advance it, challenge it, or deepen it. Do not "
                    "summarize what has been said. "
                    "Speak to the visitor, never about the other voices: do not narrate "
                    "what another voice said, asked, or assumes ('Ambassador assumes...', "
                    "'Mentor is asking...'). Take up the point itself and address the "
                    "visitor directly. Bring something new that the visitor hasn't said "
                    "and no voice has named yet — a fact, a tradeoff, a consequence, or "
                    "a clear stance. Do not restate the previous voice's point in "
                    "different words."
                )
                if voice_id == "conductor":
                    prompt.append(_CONDUCTOR_ORCHESTRATION_BLOCK)
                recusal = _recusal_instruction(voice_id)
                if recusal:
                    prompt.append(recusal)
                prompt.append(_register_flag_instruction(voice_id))
        else:
            # No voice turn yet (defensive — the endpoint 422s on a truly empty
            # transcript, but a visitor-only transcript is possible).
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
                recusal = _recusal_instruction(voice_id)
                if recusal:
                    prompt.append(recusal)
                prompt.append(_register_flag_instruction(voice_id))
        prompt.append("")
    elif question_mode:
        # Typed message in question mode: the voice does not answer the
        # message — it asks the single most penetrating question the message
        # calls for, guided by its defining question.
        prompt.append(
            "The visitor wrote you a message in question mode — do not answer it. "
            "Ask the single most penetrating question it calls for: the one question "
            "that would most unlock this situation. Let your defining question guide "
            "you and draw on the visitor's own words and the council memory. Output "
            "the question plus at most one short sentence of context — no advice, "
            "no preamble."
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
    prompt.append(
        "Speak plainly — an 11th grader should understand every sentence on first read. "
        "Short sentences, direct questions, never stack clauses inside a question. "
        'Awkward: "What can your constraints teach us about what you already know well '
        'enough to charge for next week?" Plain: "What do you already know well enough '
        'to charge for next week?" If the visitor speaks more richly, you may rise to '
        "meet them — but start plain. Validate using the visitor's OWN words — "
        "never name or label an emotion they didn't name themselves ('That sounds "
        "lonely', 'That must be ...'); presuming is worse than silence. No "
        "reflective-listening openers; engage the substance of what they said "
        "first, and let any warmth follow their words, never precede them. Your "
        "seat's warmth register sets the tone: Guardian, Ambassador, and Mentor "
        "may be warm in their own voice — protective, understanding, patient; "
        "the rest stay sparing and direct; the Skeptic never does reflective "
        "warmth — its love language is the hard question."
    )
    if transcript:
        prompt.append("")
        prompt.append("Conversation so far:")
        for turn in transcript[-10:]:
            prompt.append(f"{turn['role']}: {turn['content']}")
    return "\n".join(prompt)


def _speaker_lines(turns: list[dict]) -> list[str]:
    """Transcript turns as 'Speaker: text' lines (visitor + display names)."""
    lines = []
    for turn in turns:
        role = turn["role"]
        if role == "visitor":
            speaker = "Visitor"
        else:
            arch = get_archetype(role)
            speaker = arch.display_name if arch else role
        lines.append(f"{speaker}: {(turn['content'] or '')[:500]}")
    return lines


#: The progression reader (companion to the register flag): a second product
#: of the memory-fold generation. After each exchange it judges the
#: conversation's ARC and stores a per-session verdict — the set of seats
#: whose move the progression could genuinely use next (the live forks),
#: each with a short reason naming the situation. The client lights "!"
#: over those seats and the visitor chooses the road; the reader proposes
#: branches, never paths. Restraint is load-bearing: precision beats
#: coverage, and the empty verdict (silence) is common and valid.

#: Marker separating the memory bullets from the verdict JSON in the
#: background generation's output. Chosen to be prose-implausible so the
#: split never fires on memory text itself.
_PROGRESSION_VERDICT_MARKER = "VERDICT:"


def _empty_verdict() -> dict:
    return {"flags": [], "reasons": {}}


def _parse_progression_verdict(text: str) -> dict:
    """Validate one progression-reader JSON verdict.

    Seat ids are checked against the stock archetypes and deduped; reasons
    are kept only for flagged seats and trimmed to one short line. Anything
    unparseable or malformed yields the empty verdict — the suggestions
    honesty rule: no verdict rather than junk.
    """
    try:
        data = json.loads(text)
    except Exception:
        return _empty_verdict()
    if not isinstance(data, dict):
        return _empty_verdict()
    valid = set(stock_archetype_ids())
    flags: list[str] = []
    raw_flags = data.get("flags")
    if isinstance(raw_flags, list):
        for item in raw_flags:
            seat = str(item).strip().lower()
            if seat in valid and seat not in flags:
                flags.append(seat)
    reasons: dict[str, str] = {}
    raw_reasons = data.get("reasons")
    if isinstance(raw_reasons, dict):
        for seat in flags:
            reason = raw_reasons.get(seat)
            if isinstance(reason, str) and reason.strip():
                reasons[seat] = " ".join(reason.split())[:80]
    return {"flags": flags, "reasons": reasons}


def _split_memory_and_verdict(raw: str) -> tuple[str, dict]:
    """Split the background generation into (memory text, verdict).

    The verdict is control data: it is split off here and never stored in
    the session's memory text or transcript. No marker (the model forgot,
    or an old-format reply) → the whole text is memory and the verdict is
    empty; a malformed verdict JSON → empty verdict, memory still kept.
    """
    idx = raw.rfind(_PROGRESSION_VERDICT_MARKER)
    if idx == -1:
        return raw.strip(), _empty_verdict()
    mem = raw[:idx].strip()
    tail = raw[idx + len(_PROGRESSION_VERDICT_MARKER) :]
    m = re.search(r"\{.*\}", tail, re.DOTALL)
    verdict = _parse_progression_verdict(m.group(0)) if m else _empty_verdict()
    return mem, verdict


def _progression_reader_section(
    window_lines: list[str],
    register_flag: str | None,
) -> str:
    """The progression-reader half of the background generation's prompt.

    Judges the arc, not the last answer's accent. Inputs: the council
    memory (already in the prompt above this section), the last ~6
    transcript turns, and the last reply's self-reported register flag
    — weighed together, none deciding alone.

    Phase 5 (retired fragment): the deterministic strand-signal line
    that used to join these signals is deleted — it was the demo-only
    third path for casting data, with no callers beyond demo. The
    reader weighs the register flag and the window only; casting data
    for any future reader comes through the steward read model.
    """
    if register_flag:
        arch = get_archetype(register_flag)
        name = arch.display_name if arch else register_flag
        register_line = (
            f"- The last voice's reply substantially sat in the {name}'s "
            f"register — that seat's territory was flagged from inside the reply."
        )
    else:
        register_line = "- No seat flagged the last reply's register."
    signals = [register_line]
    seats = ", ".join(stock_archetype_ids())
    return (
        "After the memory bullets, one more job. You are also the council's "
        "progression reader. Judge the ARC — where this visitor's story is "
        "heading — not the last answer's accent. A seat is a live fork when "
        "its move would take the progression somewhere genuinely different: "
        "the Skeptic when a bias is hardening, the Guardian when the visitor "
        "is being pummeled, the Maverick when the conversation keeps walking "
        "the same circle, the Ambassador when two worlds in the story have "
        "stopped hearing each other. Weigh the open tensions in the memory "
        "above, how the visitor is actually doing inside the story, and "
        "these signals (weigh them; none decides alone):\n"
        + "\n".join(signals)
        + "\n\nRecent conversation:\n"
        + "\n".join(window_lines)
        + "\n\nRestraint is the job: precision beats coverage. An empty "
        "verdict is common and valid. Name only genuine forks — often two "
        "to four, sometimes one, often none. Never light all seven: a fork "
        "with every road lit is no fork at all. The visitor chooses the "
        "road; you only mark the forks.\n\n"
        f"Then, on its own line, write {_PROGRESSION_VERDICT_MARKER} and "
        "after it ONLY this JSON object — no prose, no code fences:\n"
        '{"flags": ["seat_id", ...], "reasons": {"seat_id": "short reason"}}'
        f"\nSeat ids, exactly: {seats}. Each reason is at most 10 words and "
        "names the situation in the visitor's story ('a bias is hardening "
        "here', 'the visitor is being pummeled') — never the seat's job "
        "description."
    )


def _refresh_council_memory(session_id: str) -> None:
    """Fold the latest exchange into the session's shared council memory,
    and assess the conversation's progression (the reader verdict).

    Runs in a daemon thread after the reply is delivered — best-effort, never
    raises into the request path. One generation, two products: the memory
    text (what lets each voice build on the conversation's arc) and the
    progression verdict (which seats the arc could use next). The verdict is
    split off the generation and stored on the session only — it never
    enters the memory text or the transcript.
    """
    try:
        from local_ai.providers import meta as _meta

        sess = _sessions.get(session_id)
        if not sess or not sess["transcript"]:
            return
        transcript = sess["transcript"]
        assessed_exchanges = sess.get("exchanges", 0)
        recent = transcript[-4:]  # last two exchanges (the fold's window)
        window = transcript[-6:]  # the reader reads a slightly wider arc
        convo_lines = _speaker_lines(recent)
        prompt = (
            "You are the council's shared memory keeper. Update the council's running "
            "memory in exactly 3 short bullets: (1) what the visitor seems to want or "
            "is circling around, (2) open tensions or unanswered questions, "
            "(3) exact short phrases of the visitor's worth echoing back later.\n\n"
            f"Previous memory:\n{(sess.get('memory') or '(none yet)')[:800]}\n\n"
            f"Latest exchanges:\n" + "\n".join(convo_lines) + "\n\n"
            "Updated memory (3 bullets, terse):"
        )
        prompt += "\n\n" + _progression_reader_section(
            _speaker_lines(window),
            sess.get("last_register_flag"),
        )
        raw = _meta.generate("", prompt, timeout=45, reasoning_effort="minimal").strip()
        if not raw:
            return
        mem, verdict = _split_memory_and_verdict(raw)
        if mem:
            sess["memory"] = mem[:1200]
        # A slower worker for an older exchange must not overwrite a newer
        # verdict with its staler read of the arc.
        stored = sess.get("progression") or {}
        if assessed_exchanges >= (stored.get("exchanges_used") or 0):
            sess["progression"] = {
                "flags": verdict["flags"],
                "reasons": verdict["reasons"],
                "exchanges_used": assessed_exchanges,
            }
            # Log the fork this verdict offered. The visitor's next request
            # resolves it (see _resolve_outstanding_fork) — the pick is a
            # revealed preference and a grade on the reader. An empty
            # verdict offered no fork; it is logged pre-resolved ("no_fork")
            # so the log also shows how often the reader stayed silent, and
            # it never becomes the outstanding event.
            sess.setdefault("forks", []).append(
                {
                    "exchange": assessed_exchanges,
                    "offered": list(verdict["flags"]),
                    "reasons": dict(verdict["reasons"]),
                    "at": time.time(),
                    "resolution": None if verdict["flags"] else "no_fork",
                }
            )
    except Exception:
        pass  # memory + verdict are best-effort; the conversation must never break


def _resolve_outstanding_fork(sess: dict, *, speak: bool, voice_id: str) -> None:
    """Resolve the session's outstanding fork event from the visitor's act.

    Called when the NEXT request arrives, before the turn is processed: a
    speak-turn tap on an offered seat is a pick (chose:<seat>); a tap on
    any other seat went off the reader's menu (off_menu:<seat>); a typed
    message means the visitor took the floor themselves (self_directed).
    Only the latest unresolved event resolves — an older unresolved event
    was superseded by a newer verdict before the visitor acted, and stays
    unresolved in the log as its own datum.
    """
    outstanding = None
    for event in reversed(sess.get("forks") or []):
        if event.get("resolution") is None:
            outstanding = event
            break
    if outstanding is None:
        return
    if not speak:
        outstanding["resolution"] = "self_directed"
    elif voice_id in (outstanding.get("offered") or []):
        outstanding["resolution"] = f"chose:{voice_id}"
    else:
        outstanding["resolution"] = f"off_menu:{voice_id}"


def _kick_memory_refresh(session_id: str) -> None:
    """Refresh council memory off the request path."""
    t = threading.Thread(target=_refresh_council_memory, args=(session_id,), daemon=True)
    t.start()


def _speak_turn_params(body: DemoChatBody, sess: dict) -> tuple[bool, bool]:
    """(speak_mode, question_mode) for a demo turn.

    speak_mode: empty message — the tapped voice addresses the last voice
    response in the transcript.
    question_mode: the tapMode toggle is on "question" — honored for voice-chip
    taps AND for typed messages. With a typed message the voice asks one
    penetrating question about the message instead of answering it.
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
    question_mode = mode == "question"
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


class DemoProgressionResponse(BaseModel):
    """The progression reader's latest verdict for one session.

    flags: seat ids whose move the progression could genuinely use next
    (the live forks). reasons: per-seat short situation phrases. An empty
    verdict is the reader's silence — common and valid. exchanges_used is
    the exchange count the verdict was assessed at, so a polling client
    can tell a fresh verdict from a stale one.
    """

    flags: list[str] = Field(default_factory=list)
    reasons: dict[str, str] = Field(default_factory=dict)
    exchanges_used: int = 0


def _current_progression(sess: dict) -> tuple[list[str], dict[str, str]]:
    """(flags, reasons) of the session's stored progression verdict."""
    verdict = sess.get("progression") or {}
    return (
        list(verdict.get("flags") or []),
        dict(verdict.get("reasons") or {}),
    )


@router.get("/progression", response_model=DemoProgressionResponse)
def demo_progression(session_id: str = "") -> DemoProgressionResponse:
    """Latest progression-reader verdict for a demo session — no auth.

    Read-only and quiet: unknown or expired sessions get the empty verdict,
    never an error. The verdict is assessed in the background after each
    exchange, so it can lag the conversation by one exchange.
    """
    sess = _sessions.get((session_id or "").strip())
    if not sess:
        return DemoProgressionResponse()
    verdict = sess.get("progression") or {}
    return DemoProgressionResponse(
        flags=list(verdict.get("flags") or []),
        reasons=dict(verdict.get("reasons") or {}),
        exchanges_used=int(verdict.get("exchanges_used") or 0),
    )


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

    store = _get_claim_store()
    for _ in range(20):
        code = "".join(secrets.choice(_CLAIM_ALPHABET) for _ in range(6))
        if not store.exists(code):
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
    "continue the conversation." Single-use, 24h TTL. Codes persist in SQLite
    so deploys don't strand them.
    """
    store = _get_claim_store()
    store.sweep_expired()

    sess = _sessions.get((body.session_id or "").strip())
    if not sess or not sess["transcript"]:
        raise HTTPException(status_code=404, detail="Demo session not found or empty.")
    text = _format_transcript_text(sess["transcript"])
    if not text:
        raise HTTPException(status_code=422, detail="Nothing to save yet — say something first.")

    code = _new_claim_code()
    store.issue(code, text)
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
    transcript = _get_claim_store().consume(code)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Claim code not found or expired.")
    return DemoClaimResponse(transcript=transcript)


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

    # The visitor's act resolves the outstanding fork before this turn
    # is processed: the pick (or the refusal of the menu) is the signal,
    # and it belongs to the moment of choice.
    _resolve_outstanding_fork(sess, speak=speak_mode, voice_id=voice_id)

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

    # Register flag: the [[register:...]] marker is control data, not prose —
    # split it off before the reply is stored or shown. Speak turns in
    # respond mode are the only turns instructed to flag; marker-shaped
    # text is stripped on every turn regardless.
    reply, register_flag = _extract_register_flag(
        reply, voice_id, enabled=speak_mode and not question_mode
    )

    if not speak_mode:
        transcript.append({"role": "visitor", "content": message})
    transcript.append({"role": voice_id, "content": reply})
    sess["exchanges"] += 1
    # The background reader weighs the last reply's register flag as one of
    # its signals; the verdict delivered here is the PREVIOUS exchange's
    # (this exchange's lands in the background — poll /demo/progression).
    sess["last_register_flag"] = register_flag
    progression_flags, progression_reasons = _current_progression(sess)
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
        register_flag=register_flag,
        progression_flags=progression_flags,
        progression_reasons=progression_reasons,
    )


@router.post("/stream")
def demo_stream(body: DemoChatBody, request: Request) -> StreamingResponse:
    """Streaming twin of /demo/chat: Server-Sent Events with token deltas.

    Same body, same guards. Events:
      data: {"type": "token", "text": "..."}   — reply chunks as they arrive
      data: {"type": "done", "session_id": ..., "voice": ..., "voice_color": ...,
             "exchanges_used": N, "exchanges_left": M, "capped": bool,
             "register_flag": <seat id or null>,
             "progression_flags": [...], "progression_reasons": {...}}
    The progression fields carry the reader's verdict from the PREVIOUS
    exchange (this exchange's is assessed in the background afterwards).
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

    # The visitor's act resolves the outstanding fork before this turn
    # is processed: the pick (or the refusal of the menu) is the signal,
    # and it belongs to the moment of choice.
    _resolve_outstanding_fork(sess, speak=speak_mode, voice_id=voice_id)

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
        held = ""
        try:
            # api_key="" -> server env key; low effort keeps latency and cost down.
            for chunk in _meta.generate_stream(
                "", full_prompt, timeout=90, reasoning_effort="low"
            ):
                chunks.append(chunk)
                # Hold back any tail that could still grow into a
                # [[register:...]] marker: it is control data and must never
                # reach the client in a token event, even split across
                # chunks. Everything else streams raw, as before. A tail
                # still held at end-of-stream is dropped here — the done
                # event carries the canonical reply either way.
                held += chunk
                safe, held = _split_stream_safe(held)
                if safe:
                    yield f"data: {_json.dumps({'type': 'token', 'text': safe})}\n\n"
        except Exception as exc:  # noqa: BLE001 — honest error event, then stop
            yield f"data: {_json.dumps({'type': 'error', 'detail': f'Demo voice unavailable: {exc}'})}\n\n"
            return
        # Sanitize the assembled reply: mid-stream chunks are raw, so the done
        # event carries the corrected full text for the client to settle on.
        reply = _sanitize_weave("".join(chunks).strip())
        reply, register_flag = _extract_register_flag(
            reply, voice_id, enabled=speak_mode and not question_mode
        )
        if not speak_mode:
            transcript.append({"role": "visitor", "content": message})
        transcript.append({"role": voice_id, "content": reply})
        sess["exchanges"] += 1
        sess["last_register_flag"] = register_flag
        progression_flags, progression_reasons = _current_progression(sess)
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
            "register_flag": register_flag,
            "progression_flags": progression_flags,
            "progression_reasons": progression_reasons,
        }
        yield f"data: {_json.dumps(done)}\n\n"
        _kick_memory_refresh(session_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
