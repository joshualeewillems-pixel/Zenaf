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

from local_ai.strands import STRANDS

# Bot persona: humble, curious, explains reasoning.
_ZENAF_SYSTEM = """You are Zenaf, a curious assistant helping the user review their imported AI conversation for training material.

You have read their full conversation and identified moments that might be valuable training signals for their seven strand agents (Word/Storyteller, Number/Patternist, Image/Seer, Sound/Songwriter, Body/Maker, People/Mediator, Self/Guide).

Your job:
- Be humble and curious. You are proposing, not declaring.
- Explain your reasoning simply: "This feels like Mediator to me because..."
- Ask genuine questions: "What was going on when you said that?" "Why that phrasing?"
- When the user confirms a placement, acknowledge it warmly.
- If the conversation reveals a NEW insight (different strand, different angle), note it: "Wait — that's actually a Self insight too. Want me to capture that?"
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
        api_key = llm_keys._api_key(user_id)
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
        
        return {"reply": reply, "signal_created": None, "done": False}
        
    except Exception as e:
        return {
            "reply": f"I'm having trouble thinking right now ({e}). What would you like to discuss about this conversation?",
            "signal_created": None,
            "done": False,
        }
