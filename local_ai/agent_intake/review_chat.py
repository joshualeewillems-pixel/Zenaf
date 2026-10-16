"""Zenaf review chatbot — conversational intake review.

Instead of a card queue, the user talks with Zenaf (the bot) about their
imported conversation. Zenaf has read the full transcript and the LLM's
flagged moments. It's humble, curious, and explains its reasoning.

Flow:
1. Opening: Zenaf gives a paragraph overview of key findings, user chooses
   which moment to discuss first.
2. Discussion: Zenaf asks curious questions, digs deeper, proposes strand
   placements with humble explanations.
3. Confirmation: When user agrees ("yes, file in Heart"), a TrainingSignal
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

You have read their full conversation and identified moments that might be valuable training signals for their seven strand agents (Word/Voice, Number/Logic, Image/Eye, Sound/Ear, Body/Hands, People/Heart, Self/Compass).

Your job:
- Be humble and curious. You are proposing, not declaring.
- Use plain, accessible language by default (~11th grade reading level). No academic jargon, no philosophical terminology unless the user introduces it first. Say "how people treat each other" not "relational ethics." Say "knowing yourself" not "epistemic foundation."
- Match the user's register: if they speak simply, stay simple. If they go deep and use precise terms, follow them there. Always start accessible and adjust up, never start academic and talk down.
- Explain your reasoning simply: "This feels like Heart to me because..."
- Ask genuine questions: "What was going on when you said that?" "Why that phrasing?"
- BEFORE filing anything, be explicit and confident about what you're proposing.
  Present it naturally in conversation, then include a structured tag on its own line:
  [PROPOSAL strand=Heart]Your specific synopsis of the training signal here[/PROPOSAL]
  Then explain: "Tap '✓ File it' in the amber box to save this, or keep chatting here to refine it."
  The strand must be one of: Voice, Logic, Eye, Ear, Hands, Heart, Guide.
  Make sure the user understands: the amber box is for filing, normal chat is for discussion.
- If the user says "add this", "file this", "save this", or "capture this", formulate a proposal based on what you just discussed. Include the [PROPOSAL] tag so the amber box appears.
- Your main goal is to be as correct as possible before making any changes.
  Don't rush to file — the conversation IS the value.
- If the synopsis changes AT ALL after the user confirmed it (new detail, refined wording, added context), you MUST present the updated version and ask for confirmation again. Never file an updated version without explicit approval.
- When the user confirms a placement, acknowledge it warmly. NEVER claim the filing happened — do not say "filed", "that's filed", "I've filed it", "done", or any variation suggesting the action is complete. The system handles the actual filing and will confirm it separately. Just say something like "Wonderful" or "Got it" and continue the conversation.
- If the conversation reveals a NEW insight (different strand, different angle), note it: "Wait — that's actually a Self insight too. Want me to capture that?"
- Propose ONE signal at a time. If multiple strands are relevant, file the first one, then propose the second separately. Never try to hold multiple proposals simultaneously.
- Philosophy is welcome when it reveals something trainable — but always gravitate toward practicality. If the conversation drifts into abstraction, connect it back: "That's a rich idea — how would you want that to show up in practice? What should it train?"
- Never be a therapist. Focus on: "what should this train?"

Keep responses concise (2-4 sentences). Ask one question at a time.
"""

_STRAND_NAMES = {
    "word": "Voice",
    "number": "Logic", 
    "image": "Eye",
    "sound": "Ear",
    "body": "Hands",
    "people": "Heart",
    "self": "Compass",
}


def _build_moments_overview(moments: list) -> list[dict]:
    """Build structured overview of moments for checkbox UI.
    
    Returns [{strand, strand_name, moments: [{idx, label, quote, inference}]}]
    """
    by_strand: dict[str, list] = {}
    for idx, m in enumerate(moments):
        by_strand.setdefault(m.strand, []).append((idx, m))
    
    overview = []
    for strand_key, items in sorted(by_strand.items(), key=lambda x: -len(x[1])):
        strand_moments = []
        for idx, m in items:
            # Brief label from inference (first ~100 chars)
            label = m.inference[:100]
            if len(m.inference) > 100:
                # Cut at word boundary
                label = label.rsplit(' ', 1)[0] + "…"
            strand_moments.append({
                "idx": idx,
                "label": label,
                "quote": m.quote[:300],
                "inference": m.inference,
            })
        overview.append({
            "strand": strand_key,
            "strand_name": _STRAND_NAMES.get(strand_key, strand_key),
            "moments": strand_moments,
        })
    return overview


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
    parts.append("I've listed them below — check the ones that look like quick wins to file them, or tap 'Discuss in depth' on any to talk it through with me first.")
    
    return "".join(parts)


def handle_message(
    agent,
    message: str,
    history: list[dict],
    user_id: str | None = None,
    pending_proposal: dict | None = None,
    is_confirmation: bool = False,
    quick_file_indices: list[int] | None = None,
) -> dict:
    """Process one chat turn with the Zenaf review bot.
    
    Returns {"reply": str, "signal_created": dict | None, "pending_proposal": dict | None, 
             "moments_overview": list | None, "quick_filed": list | None, "done": bool}
    
    If is_confirmation is True, the message is a response to a pending filing proposal
    (from the distinct confirmation UI). "yes" files it; anything else returns to conversation.
    If quick_file_indices is provided, creates signals for those moment indices directly.
    """
    from . import llm_keys
    
    # Get the agent's moments (needed for quick-file and overview)
    moments = []
    if agent.sort and getattr(agent.sort, 'moments', None):
        moments = agent.sort.moments
    
    # Handle quick-file: user selected moments from the overview checkboxes
    if quick_file_indices:
        filed = []
        for idx in quick_file_indices:
            if 0 <= idx < len(moments):
                m = moments[idx]
                proposal = {
                    "strand": m.strand,
                    "strand_name": _STRAND_NAMES.get(m.strand, m.strand),
                    "synopsis": m.inference[:500],
                    "quote": m.quote[:1000],
                }
                signal = _create_signal_from_proposal(agent, proposal, user_id)
                if signal:
                    filed.append({"idx": idx, "strand_name": proposal["strand_name"]})
        # Return updated overview (with filed ones marked)
        overview = _build_moments_overview(moments)
        filed_indices = {f["idx"] for f in filed}
        for group in overview:
            for mom in group["moments"]:
                if mom["idx"] in filed_indices:
                    mom["filed"] = True
        reply = f"Filed {len(filed)} moment{'s' if len(filed) != 1 else ''}."
        if filed:
            strands = sorted(set(f["strand_name"] for f in filed))
            reply += f" ({', '.join(strands)})"
        reply += " Want to discuss any of the remaining ones in depth?"
        return {
            "reply": reply,
            "signal_created": None,
            "pending_proposal": None,
            "moments_overview": overview,
            "quick_filed": filed,
            "done": False,
        }
    
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
    
    # If there's a pending proposal but user replied in normal chat (not amber box),
    # redirect "yes" responses to the amber box instead of treating as conversation.
    if pending_proposal and not is_confirmation:
        msg_lower = message.lower().strip()
        if re.match(r'^\s*(yes|yeah|yep|y|sure|ok|okay|exactly|perfect|agreed|sounds good)\s*[.!]?\s*$', msg_lower):
            return {
                "reply": "To file that, tap '✓ File it' in the amber box above — that's what actually saves it. Or keep chatting here if you want to refine it first.",
                "signal_created": None,
                "pending_proposal": pending_proposal,
                "done": False,
            }
    
    # User-initiated filing: "add this" triggers the bot to formulate a proposal
    # from recent conversation context.
    if not is_confirmation and not pending_proposal:
        msg_lower = message.lower().strip()
        if re.match(r'^\s*(add this|file this|save this|capture this)\s*[.!]?\s*$', msg_lower):
            # Ask the LLM to formulate a proposal based on recent context
            # This will go through the normal LLM flow below, but we add a hint
            message = message + " [USER WANTS TO FILE: formulate a specific proposal with [PROPOSAL] tag based on what we just discussed]"
    
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
        overview = _build_moments_overview(moments) if moments else None
        return {
            "reply": reply, 
            "signal_created": None, 
            "pending_proposal": None, 
            "moments_overview": overview,
            "done": False,
        }
    
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
        # Strip the structured tag from the user-visible reply
        if new_proposal:
            reply = re.sub(r"\[PROPOSAL\s+strand=\w+\].*?\[/PROPOSAL\]", "", reply, flags=re.IGNORECASE | re.DOTALL).strip()
            # Clean up any double newlines left behind
            reply = re.sub(r"\n{3,}", "\n\n", reply)
        
        # Safety net: strip any hallucinated filing claims from the LLM.
        # Only the backend (after a real DB write) may confirm a filing.
        # This catches "Filed in X", "that's filed", "I've filed it", etc.
        reply = re.sub(
            r"\s*(✓\s*)?(Filed in \w+\.?|that's filed\.?|I've filed it\.?|it's filed\.?|done\.? filed\.?)",
            "",
            reply,
            flags=re.IGNORECASE,
        ).strip()
        
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
    
    Looks for structured tag: [PROPOSAL strand=Heart]synopsis here[/PROPOSAL]
    Returns {"strand": "people", "strand_name": "Heart", "synopsis": "...", "quote": "..."} or None.
    Also strips the tag from the reply before returning it to the user.
    """
    # Match structured proposal tag
    m = re.search(r"\[PROPOSAL\s+strand=(\w+)\](.*?)\[/PROPOSAL\]", reply, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    
    strand_name = m.group(1)
    synopsis = m.group(2).strip()
    
    # Map strand name to key
    strand_map = {
        'storyteller': 'word', 'patternist': 'number', 'seer': 'image',
        'songwriter': 'sound', 'maker': 'body', 'mediator': 'people', 'guide': 'self',
    }
    strand_key = strand_map.get(strand_name.lower())
    if not strand_key or not synopsis or len(synopsis) < 10:
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
        from local_ai.presence_ingest.schema import TrainingSignal
        import time as _time
        
        signal = TrainingSignal(
            signal_id=f"review-chat-{agent.id}-{proposal['strand']}-{int(_time.time())}",
            ts_ms=int(_time.time() * 1000),
            layer="behavior",
            zone=proposal['strand'],
            actor=user_id or "",
            summary=proposal['synopsis'][:500],
            payload_redacted=proposal.get('quote', '')[:1000],
            valence="endorsed",
            correction_diff="",
            provenance={"source": "review-chat-confirmation"},
            session_id=f"review-chat-{agent.id}",
        )
        PresenceStore().save_candidate_signals([signal])
        return {"strand": proposal['strand'], "strand_name": proposal['strand_name']}
    except Exception as e:
        # Log the error instead of silently swallowing it
        print(f"Failed to create signal from proposal: {e}")
        return None

