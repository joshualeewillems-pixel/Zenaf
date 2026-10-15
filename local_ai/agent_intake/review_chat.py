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
    pending_proposal: dict | None = None,
    is_confirmation: bool = False,
) -> dict:
    """Process one chat turn with the Zenaf review bot.
    
    Returns {"reply": str, "signal_created": dict | None, "pending_proposal": dict | None, "done": bool}
    
    If is_confirmation is True, the message is a response to a pending filing proposal
    (from the distinct confirmation UI). "yes" files it; anything else returns to conversation.
    """
    from . import llm_keys
    
    # Handle explicit confirmation via the distinct UI
    if is_confirmation and pending_proposal:
        msg_lower = message.lower().strip()
        # Yes = file it. Anything else = not confirmed, continue conversation.
        if re.match(r'^\s*(yes|yeah|yep|y|sure|ok|okay|do it|file it)\s*[.!]?\s*$', msg_lower):
            signal = _create_signal_from_proposal(agent, pending_proposal, user_id)
            if signal:
                return {
                    "reply": f"Filed in {pending_proposal['strand_name']}. What would you like to explore next?",
                    "signal_created": signal,
                    "pending_proposal": None,
                    "done": False,
                }
        # Not a yes — clear the proposal and continue the conversation normally
        # (the user's message becomes the new conversation turn)
        pending_proposal = None
    
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
        return {"reply": reply, "signal_created": None, "pending_proposal": None, "done": False}
    
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
                "pending_proposal": None,
                "done": False,
            }
        
        raw = llm_keys.generate(prompt, api_key=api_key, user_id=user_id, operation="review_chat")
        # Clean up the response (remove any JSON wrapping)
        reply = raw.strip()
        # Remove common LLM artifacts
        reply = re.sub(r'^["\']|["\']$', '', reply)
        
        # Detect if the LLM proposed a filing — extract as pending_proposal for the distinct UI
        new_proposal = _extract_proposal_from_reply(reply, agent, moments)
        
        return {"reply": reply, "signal_created": None, "pending_proposal": new_proposal, "done": False}
        
    except Exception as e:
        return {
            "reply": f"I'm having trouble thinking right now ({e}). What would you like to discuss about this conversation?",
            "signal_created": None,
            "pending_proposal": None,
            "done": False,
        }

def _extract_proposal_from_reply(reply: str, agent, moments: list) -> dict | None:
    """Extract a filing proposal from the LLM's reply.
    
    Looks for: "Here's what I'd add to Mediator: [synopsis]. Does that sound right?"
    Returns {"strand": "people", "strand_name": "Mediator", "synopsis": "...", "quote": "..."} or None.
    """
    # Match "Here's what I'd add to [Strand]:" 
    m = re.search(r"Here's what I'd add to (\w+):", reply, re.IGNORECASE)
    if not m:
        return None
    
    strand_name = m.group(1)
    # Map strand name to key
    strand_map = {
        'storyteller': 'word', 'patternist': 'number', 'seer': 'image',
        'songwriter': 'sound', 'maker': 'body', 'mediator': 'people', 'guide': 'self',
    }
    strand_key = strand_map.get(strand_name.lower())
    if not strand_key:
        return None
    
    # Extract synopsis: text after the colon, up to "Does that sound right?" or end of sentence
    after_colon = reply[m.end():].strip()
    # Take up to the question mark or "Does that"
    syn_match = re.split(r'\.\s*Does that|\?\s*', after_colon, maxsplit=1)
    synopsis = syn_match[0].strip().strip('"').strip()
    # Remove trailing period if present (we'll add our own formatting)
    if synopsis.endswith('.'):
        synopsis = synopsis[:-1]
    
    if not synopsis or len(synopsis) < 10:
        return None
    
    # Find a relevant quote from moments for this strand (best effort)
    quote = ""
    for mom in moments:
        if getattr(mom, 'strand', '').lower() == strand_key:
            quote = getattr(mom, 'quote', '')[:500]
            break
    
    return {
        "strand": strand_key,
        "strand_name": strand_name,
        "synopsis": synopsis,
        "quote": quote,
    }

def _create_signal_from_proposal(agent, proposal: dict, user_id: str | None) -> dict | None:
    """Create a TrainingSignal from an explicitly confirmed proposal."""
    try:
        from local_ai.presence_ingest.store import PresenceStore
        from local_ai.presence_ingest.models import TrainingSignal
        import time as _time
        
        signal = TrainingSignal(
            id=f"review-chat-{agent.id}-{proposal['strand']}-{int(_time.time())}",
            actor=user_id or "",
            zone=proposal['strand'],
            signal_type="endorsed",
            kind="behavior",
            payload_redacted=proposal.get('quote', '')[:1000],
            summary=proposal['synopsis'][:500],
            correction_diff="",
            source="review-chat-confirmation",
            created_at=_time.time(),
        )
        PresenceStore().save_candidate_signals([signal])
        return {"strand": proposal['strand'], "strand_name": proposal['strand_name']}
    except Exception:
        return None

