"""Conversational intake: the user talks to Muse, Muse runs the intake pipeline.

Instead of forms and render-job screens, the app embeds a chat widget backed
by Claude. The user pastes a conversation (or drops a share link); this module
routes the message to the right pipeline call and renders the result as a
warm conversational reply.
"""

from __future__ import annotations

import os
import re

SHARE_URL_RE = re.compile(r"https?://[^\s)>\"]+")
CONVERSATION_MARKERS = ("USER:", "ASSISTANT:", "Human:", "Assistant:", "ChatGPT", "Muse:")


def _api_key() -> str | None:
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None


def _claude_say(system: str, user: str) -> str | None:
    """Ask Claude for a reply; None when no key or the call fails."""
    key = _api_key()
    if not key:
        return None
    try:
        from local_ai.providers import anthropic

        return anthropic.generate(key, f"{system}\n\nUser: {user}\n\nReply:")
    except Exception:
        return None


def _looks_like_conversation(msg: str) -> bool:
    if len(msg) > 600:
        return True
    markers = sum(1 for m in CONVERSATION_MARKERS if m in msg)
    return markers >= 2


def _share_urls(msg: str) -> list[str]:
    return [
        u for u in SHARE_URL_RE.findall(msg)
        if "chatgpt.com/share" in u or "claude.ai/share" in u
    ]


CONCIERGE_SYSTEM = """You are Muse, the intake guide inside Zenaf — an app that trains \
personal AI agents from the user's own conversations. The user is chatting with you to \
connect one of their AI conversations (ChatGPT, Claude) so Zenaf can sort it into their \
seven faculties (Word/Storyteller, Number/Patternist, Image/Seer, Sound/Songwriter, \
Body/Maker, People/Mediator, Self/Guide) and mine it for projects.

Rules:
- Be warm, brief, plain-spoken. No jargon, no mention of render jobs or pipelines.
- They can paste the conversation text directly, or drop a share link.
- Reassure once, early: text is redacted at capture and nothing trains until they review and approve it.
- If their message is short or unclear, ask what conversation they'd like to connect.
- Never invent what an intake found — only describe results you're given."""


def handle_message(message: str, history: list[dict] | None = None) -> dict:
    """Route one chat message. Returns {"reply": str, "agent": dict | None}."""
    from local_ai.agent_intake import pipeline, project_miner

    msg = (message or "").strip()
    if not msg:
        return {"reply": "Paste a conversation or drop a share link and I'll take it from there.", "agent": None}

    # 1. Share link → try the direct pipeline; if it needs a browser render,
    #    just ask for the text instead of exposing render-job machinery.
    urls = _share_urls(msg)
    if urls:
        try:
            agent, job = pipeline.connect_via_share_link(urls[0], store=_store())
        except Exception as exc:
            return {"reply": f"I couldn't read that link ({exc}). Paste the conversation text instead and I'll connect it.", "agent": None}
        if agent is None:
            return {
                "reply": (
                    "I can't open that page from here — it needs a browser to render. "
                    "Easiest path: open the link, select all, copy, and paste the text right here. "
                    "I'll sort it and pull out your projects."
                ),
                "agent": None,
            }
        return _intake_done(agent, urls[0])

    # 2. Pasted conversation → run the full intake.
    if _looks_like_conversation(msg):
        try:
            agent = pipeline.connect_via_extracted_text(url="pasted-conversation", transcript=msg, store=_store())
        except Exception as exc:
            return {"reply": f"That didn't go through ({exc}). Try pasting again?", "agent": None}
        mined = _mine(msg)
        return _intake_done(agent, "pasted-conversation", mined=mined)

    # 3. Anything else → Muse responds conversationally.
    reply = _claude_say(CONCIERGE_SYSTEM, msg)
    if reply is None:
        reply = (
            "I can connect one of your AI conversations — paste the text here or drop a share link. "
            "I'll sort it into your seven strands and pull out the projects hiding in it. "
            "Everything's redacted at capture, and nothing trains until you review it."
        )
    return {"reply": reply, "agent": None}


def _store():
    from local_ai.agent_intake.store import AgentStore

    return AgentStore()


def _mine(transcript: str) -> dict:
    from local_ai.agent_intake import project_miner

    try:
        from dataclasses import asdict

        result = project_miner.mine_projects(transcript)
        return {
            "initiatives": [asdict(i) for i in result.initiatives],
            "projects": [asdict(p) for p in result.projects],
            "standalone_tasks": [asdict(t) for t in result.standalone_tasks],
            "ideas": [asdict(i) for i in result.ideas],
        }
    except Exception:
        return {"initiatives": [], "projects": [], "standalone_tasks": [], "ideas": []}


def _intake_done(agent, source: str, mined: dict | None = None) -> dict:
    """Turn a connected agent into Muse's conversational reply."""
    d = agent.to_dict() if hasattr(agent, "to_dict") else dict(agent)
    sort = d.get("sort") or {}
    weights = sort.get("strand_weights") or {}
    top = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:3]
    strand_str = ", ".join(f"{k} ({v:.1f})" for k, v in top) or sort.get("primary_strand", "")

    mined = mined or {}
    counts = {
        "initiatives": len(mined.get("initiatives", [])),
        "projects": len(mined.get("projects", [])),
        "tasks": len(mined.get("standalone_tasks", [])),
        "ideas": len(mined.get("ideas", [])),
    }
    mined_str = ", ".join(f"{v} {k}" for k, v in counts.items() if v) or "nothing actionable yet"

    facts = (
        f"Connected agent: {d.get('name', 'untitled')}. "
        f"Strands: {strand_str}. Mined: {mined_str}. "
        f"Status: pending review — nothing trains until the user approves."
    )
    reply = _claude_say(
        CONCIERGE_SYSTEM
        + " Tell the user what you found, warmly and briefly. Name the agent, "
          "the top strands in plain words, and what you pulled out. Remind them "
          "it's in their review queue and nothing trains until they approve.",
        facts,
    )
    if reply is None:
        reply = (
            f"Connected \u201c{d.get('name', 'untitled')}\u201d — mostly {strand_str}. "
            f"I pulled out {mined_str}. It's in your review queue; nothing trains until you approve it."
        )
    return {"reply": reply, "agent": d}
