"""Project/task mining: read a transcript and propose projects and tasks.

After an agent is connected (or a transcript is ingested), this module reads
the material the way a chief of staff would: what is this person actually
working on? What did they ask for? What did they say they'd do?

Proposes Vision Execution projects (ongoing endeavors with a goal) and tasks
(concrete next actions), each linked to the source transcript. The user reviews
and confirms before anything is created — nothing is auto-filed.

FIELD MAPPING (backend field -> GUI label, from VisionExecutionView.tsx):
- Initiative: title->"Title", brief->"Brief", status->"Status"
- Project: title->"Title", brief->"Brief (scope & outcomes)",
  initiative_id->"Initiative", current_focus->(project detail)
- Task: title->"Title", description->"Description", notes->"Notes", status->"Status"
- Idea: title->"Title", summary->"Short note", description->"Expanded description",
  desired_outcome->"Intent / what this idea is trying to become"
Keep these aligned if the GUI labels change.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProposedTask:
    title: str
    detail: str = ""
    source_quote: str = ""  # brief verbatim anchor from the transcript

    def to_task_create(self, project_id: str | None = None) -> dict[str, Any]:
        """Map to a Vision Execution TaskCreate payload."""
        return {
            "project_id": project_id,
            "title": self.title,
            "description": self.detail,
            "notes": f"Mined from transcript: {self.source_quote}" if self.source_quote else "",
            "status": "Todo",
        }


@dataclass
class ProposedProject:
    title: str
    goal: str = ""
    status_hint: str = ""  # e.g. "draft exists", "just started", "ongoing inquiry"
    source_quote: str = ""
    tasks: list[ProposedTask] = field(default_factory=list)
    initiative_title: str | None = None  # parent initiative, if the miner placed it

    def to_project_create(self, initiative_id: str | None = None) -> dict[str, Any]:
        """Map to a Vision Execution ProjectCreate payload."""
        brief = self.goal
        if self.source_quote:
            brief += f"\n\nFrom transcript: {self.source_quote}"
        return {
            "initiative_id": initiative_id,
            "title": self.title,
            "brief": brief,
            "status": "Draft",
            "current_focus": self.status_hint,
        }


@dataclass
class ProposedInitiative:
    title: str
    brief: str = ""
    source_quote: str = ""
    project_titles: list[str] = field(default_factory=list)  # projects under it

    def to_initiative_create(self) -> dict[str, Any]:
        """Map to a Vision Execution InitiativeCreate payload."""
        brief = self.brief
        if self.source_quote:
            brief += f"\n\nFrom transcript: {self.source_quote}"
        return {"title": self.title, "brief": brief, "status": "Draft"}


@dataclass
class ProposedIdea:
    title: str
    detail: str = ""
    source_quote: str = ""
    desired_outcome: str = ""  # intent — what the idea is trying to become
    suggested_level: str | None = None  # miner's suggestion; the user decides at review
    target_level: str | None = None  # user's verdict: idea|task|project|initiative (None = stays an idea)
    # Proposed checklist ("what would make this real?"), defined by conversation.
    # Each item: {"title": str, "done": bool, "children": [...]} (one nesting level per entry).
    checklist: list[dict[str, Any]] | None = None

    def to_idea_create(self) -> dict[str, Any]:
        """Map to a Vision Execution IdeaCreate payload.

        Field mapping follows the GUI labels:
        - "Title" -> title
        - "Expanded description" -> description
        - "Intent / what this idea is trying to become" -> desired_outcome
        - source quote -> notes
        """
        return {
            "title": self.title,
            "description": self.detail,
            "desired_outcome": self.desired_outcome,
            "notes": f"Mined from transcript: {self.source_quote}" if self.source_quote else "",
            "status": "Captured",
        }

    def to_checklist_items(self) -> list[dict[str, Any]]:
        """Normalize the proposed checklist to [{title, done, children}]."""
        out: list[dict[str, Any]] = []
        for raw in self.checklist or []:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            if not title:
                continue
            children = []
            for craw in raw.get("children") or []:
                if not isinstance(craw, dict):
                    continue
                ctitle = (craw.get("title") or "").strip()
                if ctitle:
                    children.append({"title": ctitle, "done": bool(craw.get("done", False)), "children": []})
            out.append({"title": title, "done": bool(raw.get("done", False)), "children": children})
        return out


@dataclass
class MiningResult:
    initiatives: list[ProposedInitiative]
    projects: list[ProposedProject]
    standalone_tasks: list[ProposedTask]  # tasks not attached to a project
    ideas: list[ProposedIdea]  # early-stage, not yet committed
    engine: str  # "anthropic" | "rule_based"


_MINING_PROMPT = """Read this conversation transcript like a chief of staff. Identify work across the full hierarchy:

1. INITIATIVES — large endeavors that span multiple projects. A body of work with a unifying direction (e.g. "building a philosophy practice" spanning a book, a teaching inquiry, and public writing). For each: title, brief, source quote, and which of the proposed projects belong under it.

2. PROJECTS — specific endeavors with a goal. Things the person is building, writing, learning, or pursuing. For each: title, goal, status hint (draft exists / just started / ongoing inquiry), source quote, nested tasks, and the parent initiative title if one fits.

3. TASKS — concrete next actions the person asked for, was offered, or implied. For each: title, detail, source quote. Attach to a project when one fits; otherwise standalone.

4. IDEAS — early-stage thoughts, "I've been thinking about..." — real but not yet committed to. Captured, not actioned.
   For each idea include desired_outcome (the intent: what is this idea trying to become?).
   When an idea already reads like work at a clear scope, you may add suggested_level
   ("task", "project", or "initiative") — a suggestion only; the user decides at review.

Transcript:
{transcript}

Respond with ONLY valid JSON in this exact shape:
{{
  "initiatives": [
    {{"title": "...", "brief": "...", "source_quote": "...",
      "project_titles": ["..."]}}
  ],
  "projects": [
    {{"title": "...", "goal": "...", "status_hint": "...", "source_quote": "...",
      "initiative_title": "...", "tasks": [{{"title": "...", "detail": "...", "source_quote": "..."}}]}}
  ],
  "standalone_tasks": [
    {{"title": "...", "detail": "...", "source_quote": "..."}}
  ],
  "ideas": [
    {{"title": "...", "detail": "...", "source_quote": "...",
      "desired_outcome": "...", "suggested_level": "task"}}
  ]
}}

Be conservative: only propose what the transcript evidences. Prefer fewer, sharper items over many vague ones. Not every transcript has initiatives — only propose one when multiple projects clearly share a unifying direction. Omit suggested_level when the idea is genuinely just a thought, not work yet."""


def _api_key(user_id: str | None = None) -> str | None:
    from . import llm_keys

    return llm_keys.resolve_key(llm_keys.resolve_intake_provider(), user_id, operation="mine")


def _parse_mining_json(raw: str) -> MiningResult:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise RuntimeError("miner returned no JSON")
    data = json.loads(m.group(0))

    initiatives: list[ProposedInitiative] = []
    for i in data.get("initiatives") or []:
        if not i.get("title"):
            continue
        initiatives.append(
            ProposedInitiative(
                title=str(i["title"])[:200],
                brief=str(i.get("brief", ""))[:800],
                source_quote=str(i.get("source_quote", ""))[:300],
                project_titles=[str(t)[:200] for t in (i.get("project_titles") or [])],
            )
        )

    projects: list[ProposedProject] = []
    for p in data.get("projects") or []:
        tasks = [
            ProposedTask(
                title=str(t.get("title", ""))[:200],
                detail=str(t.get("detail", ""))[:500],
                source_quote=str(t.get("source_quote", ""))[:300],
            )
            for t in (p.get("tasks") or [])
            if t.get("title")
        ]
        if not p.get("title"):
            continue
        projects.append(
            ProposedProject(
                title=str(p["title"])[:200],
                goal=str(p.get("goal", ""))[:500],
                status_hint=str(p.get("status_hint", ""))[:200],
                source_quote=str(p.get("source_quote", ""))[:300],
                initiative_title=(str(p.get("initiative_title", "")).strip() or None),
                tasks=tasks,
            )
        )
    standalone = [
        ProposedTask(
            title=str(t.get("title", ""))[:200],
            detail=str(t.get("detail", ""))[:500],
            source_quote=str(t.get("source_quote", ""))[:300],
        )
        for t in (data.get("standalone_tasks") or [])
        if t.get("title")
    ]
    ideas = [
        ProposedIdea(
            title=str(i.get("title", ""))[:200],
            detail=str(i.get("detail", ""))[:500],
            source_quote=str(i.get("source_quote", ""))[:300],
            desired_outcome=str(i.get("desired_outcome", ""))[:300],
            suggested_level=(
                str(i.get("suggested_level", "")).strip().lower() or None
            ),
        )
        for i in (data.get("ideas") or [])
        if i.get("title")
    ]
    return MiningResult(
        initiatives=initiatives,
        projects=projects,
        standalone_tasks=standalone,
        ideas=ideas,
        engine="anthropic",
    )


def mine_projects(transcript: str, model: str | None = None, user_id: str | None = None) -> MiningResult:
    """Propose projects and tasks from a transcript. LLM-first, rule fallback."""
    transcript = (transcript or "").strip()
    if not transcript:
        return MiningResult(initiatives=[], projects=[], standalone_tasks=[], ideas=[], engine="rule_based")

    api_key = _api_key(user_id)
    if api_key:
        try:
            from . import llm_keys

            raw = llm_keys.generate(
                _MINING_PROMPT.format(transcript=transcript[:12000]),
                api_key=api_key,
                user_id=user_id,
                operation="mine",
            )
            return _parse_mining_json(raw)
        except Exception:
            pass  # fall through to rule-based

    return _rule_based_mine(transcript)


# ---------------------------------------------------------------------------
# Rule-based fallback: surface explicit requests as standalone tasks.
# ---------------------------------------------------------------------------

_REQUEST_RES = [
    (re.compile(r"\bcan you (please )?(summarize|distill|read|explain|research|find|write|draft|sharpen)\b", re.I), "requested"),
    (re.compile(r"\bplease (summarize|distill|read|explain|research|find)\b", re.I), "requested"),
]


def _rule_based_mine(transcript: str) -> MiningResult:
    tasks: list[ProposedTask] = []
    for line in transcript.splitlines():
        line = line.strip()
        if len(line) < 20 or len(line) > 300:
            continue
        for rx, _ in _REQUEST_RES:
            if rx.search(line):
                tasks.append(
                    ProposedTask(
                        title=line[:120],
                        detail="Detected as an explicit request in the transcript.",
                        source_quote=line[:200],
                    )
                )
                break
    # de-dupe
    seen: set[str] = set()
    unique: list[ProposedTask] = []
    for t in tasks:
        if t.title not in seen:
            seen.add(t.title)
            unique.append(t)
    return MiningResult(
        initiatives=[], projects=[], standalone_tasks=unique[:10], ideas=[], engine="rule_based"
    )


def _infer_entity_strands(user_id: str, entity_type: str, entity_id: str, text: str) -> None:
    """Light inference hook: suggest strand weights for a freshly mined entity.

    Uses the rule-based strand scorer (no LLM call). Stored with
    source="inferred" — the user confirms or corrects. Never raises:
    inference must never break entity creation.
    """
    try:
        from local_ai.entity_strands import set_entity_strands, suggest_weights
        from local_ai.journal.story import analyze_entry_strands

        weights = suggest_weights(analyze_entry_strands(text))
        if weights:
            set_entity_strands(user_id, entity_type, entity_id, weights, source="inferred")
    except Exception:
        pass


def create_confirmed(
    result: MiningResult,
    user_id: str,
    selected_titles: set[str] | None = None,
) -> dict[str, list[str]]:
    """Create Vision Execution entities from user-confirmed proposals.

    Respects the hierarchy: initiatives first, projects linked to them,
    ideas captured, tasks under their projects. Only creates items whose
    title is in selected_titles (or all if None).
    Returns {"initiative_ids": [...], "project_ids": [...], "task_ids": [...], "idea_ids": [...]}.
    Uses the existing VE service layer — no parallel structures.
    """
    from local_ai.vision_execution import models as M
    from local_ai.vision_execution import service as ve_service
    from local_ai.vision_execution import graduation as G

    def _id(obj: Any) -> str | None:
        return obj.get("id") if isinstance(obj, dict) else getattr(obj, "id", None)

    def _wanted(title: str) -> bool:
        return selected_titles is None or title in selected_titles

    def _validate_target_level(idea: ProposedIdea) -> str | None:
        """Normalize and validate the user's chosen target level for an idea."""
        level = (idea.target_level or "").strip().lower() or None
        if level is None:
            return None
        if level not in G.TARGET_LEVELS:
            raise ValueError(
                f"unknown target_level {idea.target_level!r} for idea "
                f"'{idea.title}' (expected one of {G.TARGET_LEVELS})"
            )
        return level

    initiative_ids: list[str] = []
    project_ids: list[str] = []
    task_ids: list[str] = []
    idea_ids: list[str] = []

    # Initiatives first (projects link to them).
    initiative_id_by_title: dict[str, str] = {}
    for i in result.initiatives:
        if not _wanted(i.title):
            continue
        created = ve_service.create_initiative(M.InitiativeCreate(**i.to_initiative_create()), user_id)
        iid = _id(created)
        if iid:
            initiative_ids.append(iid)
            initiative_id_by_title[i.title] = iid

    # Projects (linked to their initiative when the miner placed one).
    project_id_by_title: dict[str, str] = {}
    for p in result.projects:
        if not _wanted(p.title):
            continue
        iid = initiative_id_by_title.get(p.initiative_title or "")
        created = ve_service.create_project(M.ProjectCreate(**p.to_project_create(iid)), user_id)
        pid = _id(created)
        if pid:
            project_ids.append(pid)
            project_id_by_title[p.title] = pid
            _infer_entity_strands(
                user_id, "project", pid,
                f"{p.title} {p.goal} {p.source_quote}",
            )
        for t in p.tasks:
            if not _wanted(t.title):
                continue
            tc = ve_service.create_task(M.TaskCreate(**t.to_task_create(project_id=pid)), user_id)
            tid = _id(tc)
            if tid:
                task_ids.append(tid)
                _infer_entity_strands(
                    user_id, "task", tid,
                    f"{t.title} {t.detail} {t.source_quote}",
                )

    # Ideas: captured as ideas, or graduated to task/project/initiative when the
    # user chose a target level at review. The batch path enforces the checklist
    # readiness gate up front (two passes): a not-ready idea fails loudly
    # before anything is created. (Explicit single-item commands — the mining
    # amber box, POST /ideas/{id}/promote — bypass the gate; the user decides.)
    wanted_ideas = [idea for idea in result.ideas if _wanted(idea.title)]
    graduation_plans: list[tuple[ProposedIdea, str, list[dict]]] = []
    for idea in wanted_ideas:
        level = _validate_target_level(idea)
        if level in G.GRADUATE_LEVELS:
            proposed = idea.to_checklist_items()
            probe = [
                {"title": p["title"],
                 "status": "done" if p["done"] else "open",
                 "superseded": False}
                for p in proposed
            ]
            ready, missing, _stats = G.checklist_readiness(probe)
            if not ready:
                raise G.IdeaNotReadyError(missing, idea.title)
            graduation_plans.append((idea, level, proposed))

    for idea, level, proposed in graduation_plans:
        # Persist the idea (for checklist provenance), then graduate through
        # the standard path: shell entity + checklist unfolding.
        created_idea = ve_service.create_idea(M.IdeaCreate(**idea.to_idea_create()), user_id)
        iid = _id(created_idea)
        batch = [
            {
                "title": p["title"],
                "status": "done" if p["done"] else "open",
                "children": [
                    {"title": c["title"], "status": "done" if c["done"] else "open"}
                    for c in p["children"]
                ],
            }
            for p in proposed
        ]
        if batch:
            ve_service.create_checklist_items_batch(iid, batch, user_id)
        out = ve_service.promote_idea(iid, level, user_id)
        entity_type = out["entity_type"]
        if entity_type == "task":
            tid = _id(out["entity"])
            if tid:
                task_ids.append(tid)
                _infer_entity_strands(
                    user_id, "task", tid,
                    f"{idea.title} {idea.detail} {idea.source_quote}",
                )
        elif entity_type == "project":
            pid = _id(out["entity"])
            if pid:
                project_ids.append(pid)
                _infer_entity_strands(
                    user_id, "project", pid,
                    f"{idea.title} {idea.detail} {idea.source_quote}",
                )
        else:
            niid = _id(out["entity"])
            if niid:
                initiative_ids.append(niid)
                initiative_id_by_title[idea.title] = niid

    graduated_titles = {idea.title for idea, _, _ in graduation_plans}
    for idea in wanted_ideas:
        if idea.title in graduated_titles:
            continue  # graduated above — the idea became the work itself
        created = ve_service.create_idea(M.IdeaCreate(**idea.to_idea_create()), user_id)
        iid = _id(created)
        if iid:
            idea_ids.append(iid)
            # Keep the proposed checklist on the idea so it can be worked
            # through conversationally and graduated later via promote.
            proposed = idea.to_checklist_items()
            if proposed:
                batch = [
                    {
                        "title": p["title"],
                        "status": "done" if p["done"] else "open",
                        "children": [
                            {"title": c["title"], "status": "done" if c["done"] else "open"}
                            for c in p["children"]
                        ],
                    }
                    for p in proposed
                ]
                ve_service.create_checklist_items_batch(iid, batch, user_id)

    # Standalone tasks (no project).
    for t in result.standalone_tasks:
        if not _wanted(t.title):
            continue
        tc = ve_service.create_task(M.TaskCreate(**t.to_task_create()), user_id)
        tid = _id(tc)
        if tid:
            task_ids.append(tid)
            _infer_entity_strands(
                user_id, "task", tid,
                f"{t.title} {t.detail} {t.source_quote}",
            )

    return {
        "initiative_ids": initiative_ids,
        "project_ids": project_ids,
        "task_ids": task_ids,
        "idea_ids": idea_ids,
    }
