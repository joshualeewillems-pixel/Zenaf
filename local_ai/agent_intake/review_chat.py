"""Zenaf review chatbot — conversational intake review.

Instead of a card queue, the user talks with Zenaf (the bot) about their
imported conversation. Zenaf has read the full transcript and the LLM's
flagged moments. It's humble, curious, and explains its reasoning.

Flow:
1. Opening: Zenaf gives a paragraph overview of key findings, user chooses
   which moment to discuss first.
2. Discussion: Zenaf asks curious questions, digs deeper, proposes strand
   placements with humble explanations.
3. Confirmation: When user agrees ("yes, file in Mediator"), a TrainingSignal
   is created via the intake→signal bridge.
4. Spin-offs: New insights from the dialogue become their own signals.

The cards remain in the backend as the bot's "notes" (catalyst), but the
chat is the primary UI.
"""

from __future__ import annotations

import json
import re
import time

from local_ai.strands import STRANDS

# Bot persona: humble, curious, explains reasoning. Explicit about what it's adding.
_ZENAF_SYSTEM = """You are Zenaf, a curious assistant helping the user review their imported AI conversation for training material.

You have read their full conversation and identified moments that might be valuable training signals for their seven strand agents (Word/Storyteller, Number/Patternist, Image/Seer, Sound/Songwriter, Body/Maker, People/Mediator, Self/Guide).

Your job:
- Be humble and curious. You are proposing, not declaring.
- Explain your reasoning simply: "This feels like Mediator to me because..."
- Ask genuine questions: "What was going on when you said that?" "Why that phrasing?"
- BEFORE filing anything, be explicit and confident about what you're proposing:
  "Here's what I'd add to Mediator: [specific synopsis of the training signal].
  Does that sound right? Is there more to it? Any further differentiations
  before I file it?"
- Your main goal is to be as correct as possible before making any changes.
  Don't rush to file — the conversation IS the value.
- If the synopsis changes AT ALL after the user confirmed it (new detail, refined wording, added context), you MUST present the updated version and ask for confirmation again. Never file an updated version without explicit approval.
- When the user confirms a placement, acknowledge it warmly. Do NOT say "Filed in X" or "I'm filing this" — the system handles the actual filing automatically and will confirm it separately.
- If the conversation reveals a NEW insight (different strand, different angle), note it: "Wait — that's actually a Self insight too. Want me to capture that?"
- Philosophy is welcome when it reveals something trainable — but always gravitate toward practicality. If the conversation drifts into abstraction, connect it back: "That's a rich idea — how would you want that to show up in practice? What should it train?"
- Never be a therapist. Focus on: "what should this train?"

Keep responses concise (2-4 sentences). Ask one question at a time.
"""

_STRAND_NAMES = {
    "word": "Storyteller",
    "number": "Patternist", 
    "image": "Seer",
    "sound": "Songwriter",
    "body": "Maker",
    "people": "Mediator",
    "self": "Guide",
}


def _build_opening(agent, moments: list) -> str:
    """Generate the opening paragraph: key findings, user chooses."""
    # Group moments by strand
    by_strand: dict[str, list] = {}
    for m in moments:
        by_strand.setdefault(m.strand, []).append(m)
    
    # Build a paragraph overview
    parts = []
    parts.append(f"I've read your '{agent.name}' conversation. ")
    
    if not moments:
        parts.append("I didn't flag any specific training moments — want to talk through it together anyway?")
        return "".join(parts)
    
    # Summarize by strand
    strand_summaries = []
    for strand_key, ms in sorted(by_strand.items(), key=lambda x: -len(x[1])):
        name = _STRAND_NAMES.get(strand_key, strand_key)
        count = len(ms)
        strand_summaries.append(f"{count} in {name}")
    
    parts.append(f"I flagged {len(moments)} moments that might be training material: ")
    parts.append(", ".join(strand_summaries))
    parts.append(". ")
    parts.append("Which one do you want to dig into first? Or I can start with the one I'm most curious about.")
    
    return "".join(parts)


def handle_message(
    agent,
    message: str,
    history: list[dict],
    user_id: str | None = None,
) -> dict:
    """Process one chat turn with the Zenaf review bot.
    
    Returns {"reply": str, "signal_created": dict | None, "done": bool}
    """
    from . import llm_keys
    
    # Get the agent's moments (LLM-identified or rule-based fallback)
    moments = []
    if agent.sort and getattr(agent.sort, 'moments', None):
        moments = agent.sort.moments
    
    # Build context for the LLM
    # Include: transcript summary, flagged moments, conversation history
    examples_text = "\n---\n".join(agent.examples[:10]) if agent.examples else "(no examples)"
    
    moments_text = ""
    if moments:
        moments_text = "\n".join([
            f"- [{m.strand}] \"{m.quote[:200]}\" → {m.inference[:200]}"
            for m in moments[:20]
        ])
    else:
        moments_text = "(no flagged moments)"
    
    history_text = ""
    for h in history[-10:]:  # last 10 turns
        role = h.get("role", "user")
        content = h.get("content", "")[:500]
        history_text += f"\n{role}: {content}"
    
    # Check if this is the opening (empty history)
    is_opening = not history and not message.strip()
    
    if is_opening:
        # Return the scripted opening (no LLM call needed)
        reply = _build_opening(agent, moments)
        return {"reply": reply, "signal_created": None, "done": False}
    
    # Build the prompt for the LLM
    prompt = f"""{_ZENAF_SYSTEM}

The user's imported conversation (agent: {agent.name}):
{examples_text[:3000]}

Flagged training moments:
{moments_text}

Conversation so far:{history_text}

User just said: {message}

Respond as Zenaf. Be humble, curious, concise (2-4 sentences). If the user is confirming a placement (e.g., "yes", "file it", "sounds right"), acknowledge warmly. If they're pushing back, be curious about why. If a new insight emerges, note it.
"""
    
    try:
        from . import llm_keys as _lk
        # Resolve API key the same way sorter_llm does
        api_key = _lk.resolve_key(_lk.resolve_intake_provider(), user_id, operation="review_chat")
        if not api_key:
            # Fallback: simple rule-based response
            return {
                "reply": "I don't have API access right now, but I'm here to discuss. What moment stands out to you?",
                "signal_created": None,
                "done": False,
            }
        
        raw = llm_keys.generate(prompt, api_key=api_key, user_id=user_id, operation="review_chat")
        # Clean up the response (remove any JSON wrapping)
        reply = raw.strip()
        # Remove common LLM artifacts
        reply = re.sub(r'^["\']|["\']$', '', reply)
        
        # Check if user is confirming a placement — if so, create the signal
        signal_created = _detect_and_create_signal(agent, message, history, user_id)
        if signal_created:
            reply += f"\n\n✓ Filed in {signal_created['strand_name']}."
        
        return {"reply": reply, "signal_created": signal_created, "done": False}
        
    except Exception as e:
        return {
            "reply": f"I'm having trouble thinking right now ({e}). What would you like to discuss about this conversation?",
            "signal_created": None,
            "done": False,
        }

def _detect_and_create_signal(agent, message: str, history: list[dict], user_id: str | None) -> dict | None:
    """Detect if the user is confirming a strand placement, and create the signal."""
    msg_lower = message.lower().strip()
    
    # Only file on EXPLICIT, UNAMBIGUOUS confirmation.
    # A "yes" at the start of a long explanation ("Yes though, morality...") is NOT
    # a confirmation to file — it's agreement with the bot's understanding.
    # Require either: (1) short message with confirmation word, OR (2) explicit filing language.
    
    msg_len = len(msg_lower)
    
    # Explicit filing phrases — these are unambiguous regardless of length
    explicit_file_phrases = [
        r'\bfile it\b', r'\bfile that\b', r'\bsounds right\b', 
        r'\bgo ahead\b', r'\bdo it\b',
    ]
    has_explicit = any(re.search(p, msg_lower) for p in explicit_file_phrases)
    
    # Simple confirmations — only valid if the message is SHORT (not a long explanation)
    simple_confirms = [
        r'^\s*yes\s*[.!]?\s*$', r'^\s*yeah\s*[.!]?\s*$', r'^\s*yep\s*[.!]?\s*$',
        r'^\s*exactly\s*[.!]?\s*$', r'^\s*perfect\s*[.!]?\s*$', 
        r'^\s*agreed\s*[.!]?\s*$', r'^\s*correct\s*[.!]?\s*$',
    ]
    is_simple_confirm = any(re.search(p, msg_lower) for p in simple_confirms)
    
    # "that captures it" / "that's right" — valid if message is under 50 chars
    capture_patterns = [
        r'\bthat (does |do )?captures? it\b', r"\bthat'?s right\b", r'\bnailed it\b',
    ]
    is_capture = any(re.search(p, msg_lower) for p in capture_patterns) and msg_len < 50
    
    is_confirm = has_explicit or is_simple_confirm or is_capture
    if not is_confirm:
        return None
    
    strand_map = {
        'storyteller': 'word', 'patternist': 'number', 'seer': 'image',
        'songwriter': 'sound', 'maker': 'body', 'mediator': 'people', 'guide': 'self',
        'word': 'word', 'number': 'number', 'image': 'image', 'sound': 'sound',
        'body': 'body', 'people': 'people', 'self': 'self',
    }
    
    strand_key = None
    for name, key in strand_map.items():
        if name in msg_lower:
            strand_key = key
            break
    
    if not strand_key:
        for h in reversed(history[-5:]):
            if h.get('role') == 'zenaf':
                content = h.get('content', '').lower()
                for name, key in strand_map.items():
                    if name in content:
                        strand_key = key
                        break
                if strand_key:
                    break
    
    if not strand_key:
        return None
    
    moments = []
    if agent.sort and getattr(agent.sort, 'moments', None):
        moments = [m for m in agent.sort.moments if m.strand == strand_key]
    
    if not moments:
        return None
    
    moment = moments[0]
    
    try:
        from local_ai.presence_ingest.schema import TrainingSignal
        from local_ai.presence_ingest.store import PresenceStore
        
        signal = TrainingSignal(
            signal_id=f"chat:{agent.id}:{strand_key}:{int(time.time()*1000)}",
            ts_ms=int(time.time() * 1000),
            layer="behavior",
            zone=strand_key,
            actor=user_id or "",
            summary=moment.inference,
            context_ref={"source": "review_chat"},
            payload_redacted=moment.quote,
            valence="endorsed",
            correction_diff=None,
            provenance={"source": "review_chat", "agent_id": agent.id, "strand": strand_key},
            supersedes=None,
            status="approved",
            session_id="",
        )
        PresenceStore().save_candidate_signals([signal])
        
        strand_name = _STRAND_NAMES.get(strand_key, strand_key)
        return {"strand": strand_key, "strand_name": strand_name, "signal_id": signal.signal_id}
    except Exception:
        return None

