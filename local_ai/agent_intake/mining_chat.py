"""Conversational mining chat: pull tasks, projects, initiatives, assets, and people via dialogue.

After the strand-training review, the user can tap "Pull tasks & stuff" to shift
into a practical extraction mode. Zenaf reads the transcript like a chief of staff
and proposes, one by one in conversation:
- Initiatives (larger endeavors)
- Projects (ongoing work with a goal)
- Tasks (concrete next actions)
- Assets (things the user has: spaces, tools, inventory — with quantity/availability/utility)
- People (folks mentioned: skills, connections, invite offers)

Nothing is created until the user confirms in the amber box. The same
[PROPOSAL type=...]...[/PROPOSAL] mechanism as the strand review drives the
confirmation UI.
"""

from __future__ import annotations

import re
from typing import Any


# Proposal types and their human names
_PROPOSAL_TYPES = {
    "initiative": "Initiative",
    "project": "Project",
    "task": "Task",
    "asset": "Asset",
    "person": "Person",
    "idea": "Idea",
}

_MINING_SYSTEM = """You are Zenaf, helping the user pull practical things out of a conversation they imported.

You've already done the strand-training review. Now you're in practical mode: finding
the initiatives, projects, tasks, assets, and people hidden in what they talked about.

YOUR JOB:
- Read the transcript like a chief of staff. What is this person working on? What did
  they say they'd do? What do they have? Who did they mention?
- Propose ONE thing at a time in plain, everyday language (about 11th-grade reading level).
- Adapt to how the user talks — if they're casual, be casual. If they're precise, be precise.

THE FIVE THINGS YOU PULL:

1. INITIATIVES — bigger endeavors, the "why" behind the work.
   Example: "You're building toward an alternative economy vision."

2. PROJECTS — ongoing work with a concrete goal.
   Example: "Design the time-based currency system."

3. TASKS — specific next actions someone said they'd do.
   Example: "Draft the currency rules doc."

4. ASSETS — things the user has or uses: spaces, tools, equipment, inventory.
   When you spot an asset, ask what you need to record it properly:
   - What is it? How much/many? Is it available? What's it good for?
   Example: User mentions "my clinic for meetings" → "That clinic sounds useful. Is it available
   for regular meetings? How many people does it hold? Want me to file it as an asset?"

5. PEOPLE — folks mentioned by name with a skill, role, or connection.
   When you spot a person, note what they're good at and ask:
   - Do they connect to someone you already know? Want to invite them?
   Example: "Jim is really good with yardwork" → "Jim sounds handy. Is he someone you work
   with already, or should I note him as a potential contact? Want me to offer an invite?"

6. IDEAS — early-stage thoughts, "I've been thinking about..." — real but not yet committed.
   Propose these as type=idea. The amber box lets the user file it as an idea — or
   graduate it on the spot to a task, project, or initiative when it's fleshed out
   enough (clear description plus an intent or grounding detail). Don't graduate for
   them; the user picks the level in the amber box.

HOW TO PROPOSE:
Present it naturally in conversation, then include a structured tag on its own line:
[PROPOSAL type=project title="Design currency system"]Brief description of the goal and scope here[/PROPOSAL]
[PROPOSAL type=asset title="Downtown clinic"]Meeting space, holds ~20, available weekends[/PROPOSAL]
[PROPOSAL type=person title="Jim"]Good with yardwork, potential contact[/PROPOSAL]

The type must be one of: initiative, project, task, asset, person, idea.
The title should be short (a few words). The body is the detail.

Then explain: "Tap '✓ File it' in the amber box to save this, or keep chatting here to refine it."

CRITICAL RULES:
- ONE proposal at a time. Wait for confirmation before proposing the next.
- Each proposal must be anchored in something the user actually said. No invented items.
- For assets: don't file until you know what it is and roughly how it's useful.
  It's okay to ask 1-2 clarifying questions first ("How big is the clinic? Is it yours to schedule?").
- For people: don't assume a relationship. Ask if they're already connected or new.
- If the user says "add this" or taps "File this", formulate a proposal from what you just discussed.
- NEVER claim something was filed unless the system confirms it. The amber box is the only
  thing that files. Your words don't save anything.
- Keep it practical. This isn't philosophy — it's "what do we do with this information?"
"""


def _parse_proposal_tag(text: str) -> dict[str, Any] | None:
    """Extract [PROPOSAL type=X title="Y"]body[/PROPOSAL] from LLM output."""
    m = re.search(
        r'\[PROPOSAL\s+type=(\w+)\s+title="([^"]+)"\](.*?)\[/PROPOSAL\]',
        text,
        re.DOTALL,
    )
    if not m:
        return None
    ptype, title, body = m.group(1), m.group(2), m.group(3).strip()
    if ptype not in _PROPOSAL_TYPES:
        return None
    return {
        "type": ptype,
        "type_name": _PROPOSAL_TYPES[ptype],
        "title": title,
        "detail": body,
    }


def _strip_proposal_tags(text: str) -> str:
    """Remove [PROPOSAL] tags from text shown to user."""
    return re.sub(
        r'\[PROPOSAL\s+type=\w+\s+title="[^"]*"\].*?\[/PROPOSAL\]',
        '',
        text,
        flags=re.DOTALL,
    ).strip()


def _create_entity_from_proposal(
    proposal: dict[str, Any],
    user_id: str | None,
) -> dict[str, Any] | None:
    """Create the actual Vision Execution entity. Returns the created record or None.

    For idea proposals the user may choose a target_level (idea|task|project|
    initiative) in the amber box. Graduating validates the idea's practical
    fields first — raises IdeaNotReadyError naming what's missing (propagates
    out; the broad except below deliberately re-raises it).
    """
    from local_ai.vision_execution import graduation as G

    ptype = proposal["type"]
    title = proposal["title"]
    detail = proposal["detail"]
    target_level = (proposal.get("target_level") or "").strip().lower() or None

    # Validate graduation BEFORE the broad try/except so the readiness error
    # propagates to the caller (it becomes a conversational reply, not a
    # silent "couldn't save").
    if ptype == "idea" and target_level in G.GRADUATE_LEVELS:
        G.assert_ready(
            {
                "title": title,
                "description": detail,
                "desired_outcome": proposal.get("desired_outcome", ""),
                "notes": proposal.get("source_quote", ""),
            },
            title,
        )

    try:
        from local_ai.vision_execution import storage as ve_store
        from local_ai.vision_execution.models import (
            InitiativeCreate, ProjectCreate, TaskCreate, AssetCreate, PersonCreate,
            IdeaCreate,
        )

        if ptype == "idea" and target_level in G.GRADUATE_LEVELS:
            idea_dict = {
                "title": title,
                "description": detail,
                "desired_outcome": proposal.get("desired_outcome", ""),
                "notes": proposal.get("source_quote", ""),
            }
            entity_type, payload = G.build_graduated_payload(idea_dict, target_level)
            if entity_type == "task":
                created = ve_store.create_task(TaskCreate(**payload), user_id=user_id)
            elif entity_type == "project":
                created = ve_store.create_project(ProjectCreate(**payload), user_id=user_id)
            else:
                created = ve_store.create_initiative(InitiativeCreate(**payload), user_id=user_id)
            return {
                "id": getattr(created, "id", None),
                "type": entity_type,
                "title": title,
                "graduated_from": "idea",
            }

        if ptype == "idea":
            obj = IdeaCreate(title=title, description=detail, status="Captured")
            created = ve_store.create_idea(obj, user_id=user_id)
        elif ptype == "initiative":
            obj = InitiativeCreate(title=title, brief=detail, status="Draft")
            created = ve_store.create_initiative(obj, user_id=user_id)
        elif ptype == "project":
            obj = ProjectCreate(title=title, brief=detail, status="Draft")
            created = ve_store.create_project(obj, user_id=user_id)
        elif ptype == "task":
            obj = TaskCreate(title=title, description=detail, status="Todo")
            created = ve_store.create_task(obj, user_id=user_id)
        elif ptype == "asset":
            obj = AssetCreate(name=title, notes=detail, status="Active")
            created = ve_store.create_asset(obj, user_id=user_id)
        elif ptype == "person":
            obj = PersonCreate(name=title, notes=detail)
            created = ve_store.create_person(obj, user_id=user_id)
        else:
            return None

        return {"id": getattr(created, "id", None), "type": ptype, "title": title}
    except Exception:
        return None


def handle_message(
    agent,
    message: str,
    history: list[dict],
    user_id: str | None = None,
    pending_proposal: dict | None = None,
    is_confirmation: bool = False,
) -> dict:
    """Process one chat turn in mining mode.

    Returns {"reply": str, "entity_created": dict | None,
             "pending_proposal": dict | None, "done": bool}
    """
    from . import llm_keys

    # Handle explicit confirmation via the amber box
    if is_confirmation and pending_proposal:
        msg_lower = message.lower().strip()
        if re.match(r'^\s*(yes|yeah|yep|y|sure|ok|okay|do it|file it)\s*[.!]?\s*$', msg_lower):
            from local_ai.vision_execution import graduation as _G

            try:
                entity = _create_entity_from_proposal(pending_proposal, user_id)
            except _G.IdeaNotReadyError as exc:
                return {
                    "reply": (
                        f"Not quite ready to graduate — it's still a thought experiment. "
                        f"To become work it needs: {', '.join(exc.missing)}. "
                        f"Want to keep fleshing it out, or file it as an idea for now?"
                    ),
                    "entity_created": None,
                    "pending_proposal": pending_proposal,
                    "done": False,
                }
            if entity:
                filed_as = entity.get("type", pending_proposal["type"])
                return {
                    "reply": f"Filed as {filed_as.capitalize()}: {pending_proposal['title']}. What should we pull next?",
                    "entity_created": entity,
                    "pending_proposal": None,
                    "done": False,
                }
            else:
                return {
                    "reply": "I couldn't save that — something went wrong on my end. Want to try again?",
                    "entity_created": None,
                    "pending_proposal": pending_proposal,
                    "done": False,
                }
        # Not a yes — clear and continue conversation
        pending_proposal = None

    # Redirect "yes" in normal chat to the amber box
    if pending_proposal and not is_confirmation:
        msg_lower = message.lower().strip()
        if re.match(r'^\s*(yes|yeah|yep|y|sure|ok|okay|exactly|perfect|agreed|sounds good)\s*[.!]?\s*$', msg_lower):
            return {
                "reply": "To file that, tap '✓ File it' in the amber box above — that's what actually saves it. Or keep chatting here if you want to refine it first.",
                "entity_created": None,
                "pending_proposal": pending_proposal,
                "done": False,
            }

    # "Add this" trigger
    if not is_confirmation and not pending_proposal:
        msg_lower = message.lower().strip()
        if re.match(r'^\s*(add this|file this|save this|capture this)\s*[.!]?\s*$', msg_lower):
            message = message + " [USER WANTS TO FILE: formulate a specific proposal with [PROPOSAL] tag based on what we just discussed]"

    # Build context
    examples_text = "\n---\n".join(agent.examples[:10]) if agent.examples else "(no examples)"

    history_text = ""
    for h in history[-10:]:
        role = h.get("role", "user")
        content = h.get("content", "")[:500]
        history_text += f"\n{role}: {content}"

    is_opening = not history and not message.strip()

    prompt = f"""{_MINING_SYSTEM}

The user's imported conversation (agent: {agent.name}):
{examples_text[:3000]}

Conversation so far:
{history_text if history_text.strip() else "(just starting)"}

User's message: {message}

Respond as Zenaf. {'Give a brief opening: what kinds of practical things you spotted (initiatives, tasks, assets, people), then propose the first one.' if is_opening else 'Propose the next item, or respond to what they said.'}
"""

    # Call the LLM
    try:
        provider = llm_keys.get_provider()
        response = provider.complete(prompt, max_tokens=800)
        reply_text = response.strip()
    except Exception as e:
        return {
            "reply": "I'm having trouble thinking right now. What practical thing did you want to pull from this conversation?",
            "entity_created": None,
            "pending_proposal": None,
            "done": False,
        }

    # Check for a proposal tag
    proposal = _parse_proposal_tag(reply_text)
    clean_reply = _strip_proposal_tags(reply_text)

    # If LLM claimed to file without a tag, strip the hallucination
    if not proposal:
        clean_reply = re.sub(
            r'(?i)\b(i\'ve filed|filed it|saved it|it\'s filed|done, filed)\b[^.]*\.',
            '',
            clean_reply,
        ).strip()

    return {
        "reply": clean_reply if clean_reply else reply_text,
        "entity_created": None,
        "pending_proposal": proposal,
        "done": False,
    }
