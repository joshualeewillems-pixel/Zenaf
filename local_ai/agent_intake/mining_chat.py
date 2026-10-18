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
   enough. Don't graduate for them; the user picks the level in the amber box.
   When you propose an idea, also propose what would make it REAL — a short
   checklist, in the same tag via a checklist attribute:
   [PROPOSAL type=idea title="Sock company" checklist="Name the brand | Check a domain > .com first | Find a supplier > Get 3 quotes"]Socks with philosophy quotes, sold online[/PROPOSAL]
   Separate items with |. Nest one level with > ("Parent > child" groups children
   under the parent). Keep it to 3-6 items, concrete and checkable — the user
   confirms or edits the list in the amber box, then checks items off as you
   talk through them. An idea graduates when its checklist is worked through.

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


def _parse_checklist_attr(text: str) -> list[dict[str, Any]]:
    """Parse the checklist="..." attribute of a PROPOSAL tag.

    Convention: items separated by |, one nesting level via >
    ("Parent > child" groups children under the parent).
    Defensive: anything unparseable is dropped, never fatal.
    """
    m = re.search(r'\bchecklist="([^"]*)"', text)
    if not m:
        return []
    out: list[dict[str, Any]] = []
    parents: dict[str, dict[str, Any]] = {}
    for seg in m.group(1).split("|"):
        seg = seg.strip()
        if not seg:
            continue
        if ">" in seg:
            parent_title, _, child_title = seg.partition(">")
            parent_title = parent_title.strip()
            child_title = child_title.strip()
            if not parent_title or not child_title:
                continue
            parent = parents.get(parent_title)
            if parent is None:
                parent = {"title": parent_title, "children": []}
                parents[parent_title] = parent
                out.append(parent)
            parent["children"].append({"title": child_title})
        else:
            if seg not in parents:
                node = {"title": seg, "children": []}
                parents[seg] = node
                out.append(node)
    return out


def _parse_proposal_tag(text: str) -> dict[str, Any] | None:
    """Extract [PROPOSAL type=X title="Y"]body[/PROPOSAL] from LLM output."""
    m = re.search(
        r'\[PROPOSAL\s+type=(\w+)\s+title="([^"]+)"[^\]]*\](.*?)\[/PROPOSAL\]',
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
        "checklist": _parse_checklist_attr(m.group(0)),
    }


def _strip_proposal_tags(text: str) -> str:
    """Remove [PROPOSAL] tags from text shown to user."""
    return re.sub(
        r'\[PROPOSAL\s+type=\w+\s+title="[^"]*"[^\]]*\].*?\[/PROPOSAL\]',
        '',
        text,
        flags=re.DOTALL,
    ).strip()


def _suggest_checklist_links(title: str) -> dict[str, Any]:
    """Light-touch person/asset tagging for a checklist item title.

    Keyword matching (word-boundary, case-insensitive) against known persons
    and assets. Informational only — the amber box shows the suggestion and the
    user confirms (or dismisses) it. Not NER; v1 heuristic.
    """
    from local_ai.vision_execution import storage as ve_store

    out: dict[str, Any] = {}
    low = f" {title.lower()} "
    try:
        persons = ve_store.list_persons()
    except Exception:
        persons = []
    try:
        assets = ve_store.list_assets()
    except Exception:
        assets = []
    for p in persons:
        name = (p.get("name") or "").strip()
        if len(name) >= 2 and re.search(r"\b" + re.escape(name.lower()) + r"\b", low):
            out["person_id"] = p["id"]
            out["person_name"] = name
            break
    for a in assets:
        name = (a.get("name") or "").strip()
        if len(name) >= 2 and re.search(r"\b" + re.escape(name.lower()) + r"\b", low):
            out["asset_id"] = a["id"]
            out["asset_name"] = name
            break
    return out


def _enrich_proposal_checklist_links(proposal: dict[str, Any]) -> None:
    """Attach suggested person/asset links to a proposal's checklist items (in place)."""
    raw = proposal.get("checklist")
    if not isinstance(raw, list):
        return

    def _enrich(nodes: list) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            title = (node.get("title") or "").strip()
            if title:
                node.update(_suggest_checklist_links(title))
            _enrich(node.get("children") or [])

    _enrich(raw)


def _normalize_checklist(raw: Any) -> list[dict[str, Any]]:
    """Normalize a proposed checklist to [{title, children, person_id?, asset_id?}]. Defensive."""
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        children = []
        for centry in entry.get("children") or []:
            if not isinstance(centry, dict):
                continue
            ctitle = (centry.get("title") or "").strip()
            if ctitle:
                child: dict[str, Any] = {"title": ctitle}
                if centry.get("person_id"):
                    child["person_id"] = centry["person_id"]
                if centry.get("asset_id"):
                    child["asset_id"] = centry["asset_id"]
                children.append(child)
        node: dict[str, Any] = {"title": title, "children": children}
        if entry.get("person_id"):
            node["person_id"] = entry["person_id"]
        if entry.get("asset_id"):
            node["asset_id"] = entry["asset_id"]
        out.append(node)
    return out


def _create_entity_from_proposal(
    proposal: dict[str, Any],
    user_id: str | None,
) -> dict[str, Any] | None:
    """Create the actual Vision Execution entity. Returns the created record or None.

    For idea proposals the user may choose a target_level (idea|task|project|
    initiative) in the amber box — an explicit verdict, so readiness is
    advisory, not a gate (see GET /ideas/{id}/graduation for the hint).
    The idea is always persisted first (for checklist provenance); graduating
    unfolds its checklist into the work breakdown via promote_idea.
    """
    from local_ai.vision_execution import graduation as G
    from local_ai.vision_execution import service as ve_service
    from local_ai.vision_execution.models import IdeaCreate

    ptype = proposal["type"]
    title = proposal["title"]
    detail = proposal["detail"]
    target_level = (proposal.get("target_level") or "").strip().lower() or None

    try:
        from local_ai.vision_execution import storage as ve_store
        from local_ai.vision_execution.models import (
            InitiativeCreate, ProjectCreate, TaskCreate, AssetCreate, PersonCreate,
        )

        if ptype == "idea":
            obj = IdeaCreate(
                title=title,
                description=detail,
                desired_outcome=proposal.get("desired_outcome", ""),
                notes=proposal.get("source_quote", ""),
                status="Captured",
            )
            created_idea = ve_store.create_idea(obj, user_id=user_id)
            idea_id = created_idea.get("id") if isinstance(created_idea, dict) else None
            checklist = _normalize_checklist(proposal.get("checklist"))
            if idea_id and checklist:
                ve_service.create_checklist_items_batch(idea_id, checklist, user_id)
            if target_level in G.GRADUATE_LEVELS and idea_id:
                # Explicit user verdict in the amber box: graduate now, unfolding
                # whatever checklist exists (readiness is advisory here).
                out = ve_service.promote_idea(idea_id, target_level, user_id)
                return {
                    "id": out["entity"].get("id") if isinstance(out["entity"], dict) else None,
                    "type": out["entity_type"],
                    "title": title,
                    "graduated_from": "idea",
                    "task_ids": out.get("task_ids", []),
                }
            return {"id": idea_id, "type": "idea", "title": title}

        if ptype == "initiative":
            obj = InitiativeCreate(title=title, brief=detail, status="Draft")
            created = ve_service.create_initiative(obj, user_id=user_id)
        elif ptype == "project":
            obj = ProjectCreate(title=title, brief=detail, status="Draft")
            created = ve_service.create_project(obj, user_id=user_id)
        elif ptype == "task":
            obj = TaskCreate(title=title, description=detail, status="Todo")
            created = ve_service.create_task(obj, user_id=user_id)
        elif ptype == "asset":
            obj = AssetCreate(name=title, notes=detail, status="Active")
            created = ve_service.create_asset(obj, user_id=user_id)
        elif ptype == "person":
            obj = PersonCreate(name=title, notes=detail)
            created = ve_service.create_person(obj, user_id=user_id)
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
            entity = _create_entity_from_proposal(pending_proposal, user_id)
            if entity:
                filed_as = entity.get("type", pending_proposal["type"])
                extra = ""
                if entity.get("graduated_from") == "idea" and entity.get("task_ids"):
                    n = len(entity["task_ids"])
                    extra = f" Its checklist unfolded into {n} task{'s' if n != 1 else ''}."
                return {
                    "reply": f"Filed as {filed_as.capitalize()}: {pending_proposal['title']}.{extra} What should we pull next?",
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
    if proposal and proposal.get("type") == "idea" and proposal.get("checklist"):
        # Light-touch: tag person/asset mentions in proposed checklist items.
        # Informational — the amber box shows them and the user confirms.
        _enrich_proposal_checklist_links(proposal)

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
