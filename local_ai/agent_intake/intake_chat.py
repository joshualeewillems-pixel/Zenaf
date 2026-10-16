"""Conversational intake: the user talks to Muse, Muse runs the intake pipeline.

Instead of forms and render-job screens, the app embeds a chat widget backed
by Claude. The user pastes a conversation (or drops a share link); this module
routes the message to the right pipeline call and renders the result as a
warm conversational reply.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

SHARE_URL_RE = re.compile(r"https?://[^\s)>\"]+")
CONVERSATION_MARKERS = ("USER:", "ASSISTANT:", "Human:", "Assistant:", "ChatGPT", "Muse:")


def _claude_say(system: str, user: str, user_id: str | None = None) -> str | None:
    """Ask the intake provider for a reply; None when no key or the call fails."""
    from . import llm_keys

    try:
        return llm_keys.generate(
            f"{system}\n\nUser: {user}\n\nReply:",
            user_id=user_id,
            operation="intake_chat",
        )
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
seven faculties (Word/Voice, Number/Logic, Image/Eye, Sound/Ear, \
Body/Hands, People/Heart, Self/Compass) and mine it for projects.

Rules:
- Be warm, brief, plain-spoken. No jargon, no mention of render jobs or pipelines.
- They can paste the conversation text directly, or drop a share link.
- Reassure once, early: text is redacted at capture and nothing trains until they review and approve it.
- If their message is short or unclear, ask what conversation they'd like to connect.
- Never invent what an intake found — only describe results you're given."""


def handle_message(
    message: str, history: list[dict] | None = None, user_id: str | None = None
) -> dict:
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
            agent, job = pipeline.connect_via_share_link(urls[0], store=_store(user_id))
        except Exception as exc:
            # Never leak raw internals (e.g. sqlite errors) to the user; log them.
            logger.exception("intake share-link failed for %s", urls[0][:80])
            return {"reply": "I couldn't read that link — something went wrong on my end. Paste the conversation text instead and I'll connect it.", "agent": None}
        if agent is None:
            # A render job was queued; the registered reader picks it up within minutes.
            return {
                "reply": (
                    "On it — I'm having my reader open that page now. It'll land in your "
                    "review queue in a few minutes, sorted into your strands with projects "
                    "pulled out. Or paste the text here if you'd rather skip the wait."
                ),
                "agent": None,
                "render_job_id": job.id if job else None,
            }
        return _intake_done(agent, urls[0], user_id=user_id)

    # 2. Pasted conversation → run the full intake.
    if _looks_like_conversation(msg):
        try:
            agent = pipeline.connect_via_extracted_text(
                url="pasted-conversation", transcript=msg, store=_store(user_id)
            )
        except Exception:
            logger.exception("intake pasted-text failed")
            return {"reply": "That didn't go through — something went wrong on my end. Try pasting again?", "agent": None}
        mined = _mine(msg, user_id)
        return _intake_done(agent, "pasted-conversation", mined=mined, user_id=user_id)

    # 3. Anything else → Muse responds conversationally.
    reply = _claude_say(CONCIERGE_SYSTEM, msg, user_id)
    if reply is None:
        reply = (
            "I can connect one of your AI conversations — paste the text here or drop a share link. "
            "I'll sort it into your seven strands and pull out the projects hiding in it. "
            "Everything's redacted at capture, and nothing trains until you review it."
        )
    return {"reply": reply, "agent": None}


def _store(user_id: str | None = None):
    from local_ai.agent_intake.store import AgentStore

    return AgentStore(user_id=user_id)


def _mine(transcript: str, user_id: str | None = None) -> dict:
    from local_ai.agent_intake import project_miner

    try:
        from dataclasses import asdict

        result = project_miner.mine_projects(transcript, user_id=user_id)
        return {
            "initiatives": [asdict(i) for i in result.initiatives],
            "projects": [asdict(p) for p in result.projects],
            "standalone_tasks": [asdict(t) for t in result.standalone_tasks],
            "ideas": [asdict(i) for i in result.ideas],
        }
    except Exception:
        return {"initiatives": [], "projects": [], "standalone_tasks": [], "ideas": []}


def _intake_done(agent, source: str, mined: dict | None = None, user_id: str | None = None) -> dict:
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
        user_id,
    )
    if reply is None:
        reply = (
            f"Connected \u201c{d.get('name', 'untitled')}\u201d — mostly {strand_str}. "
            f"I pulled out {mined_str}. It's in your review queue; nothing trains until you approve it."
        )
    return {"reply": reply, "agent": d}
