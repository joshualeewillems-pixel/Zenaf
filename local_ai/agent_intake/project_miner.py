"""Project/task mining: read a transcript and propose projects and tasks.

After an agent is connected (or a transcript is ingested), this module reads
the material the way a chief of staff would: what is this person actually
working on? What did they ask for? What did they say they'd do?

Proposes Vision Execution projects (ongoing endeavors with a goal) and tasks
(concrete next actions), each linked to the source transcript. The user reviews
and confirms before anything is created — nothing is auto-filed.
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


@dataclass
class ProposedProject:
    title: str
    goal: str = ""
    status_hint: str = ""  # e.g. "draft exists", "just started", "ongoing inquiry"
    source_quote: str = ""
    tasks: list[ProposedTask] = field(default_factory=list)


@dataclass
class MiningResult:
    projects: list[ProposedProject]
    standalone_tasks: list[ProposedTask]  # tasks not attached to a project
    engine: str  # "anthropic" | "rule_based"


_MINING_PROMPT = """Read this conversation transcript like a chief of staff. Identify:

1. PROJECTS — ongoing endeavors with a goal. Things the person is building, writing, learning, or pursuing across multiple sessions. For each: a short title, the apparent goal, a status hint (draft exists / just started / ongoing inquiry), and a brief quote from the transcript that evidences it.

2. TASKS — concrete next actions the person asked for, was offered, or implied. For each: a short title, detail, and a brief quote evidencing it. Attach each task to its project when one fits; otherwise list it standalone.

Transcript:
{transcript}

Respond with ONLY valid JSON in this exact shape:
{{
  "projects": [
    {{"title": "...", "goal": "...", "status_hint": "...", "source_quote": "...",
      "tasks": [{{"title": "...", "detail": "...", "source_quote": "..."}}]}}
  ],
  "standalone_tasks": [
    {{"title": "...", "detail": "...", "source_quote": "..."}}
  ]
}}

Be conservative: only propose what the transcript evidences. Prefer fewer, sharper items over many vague ones."""


def _api_key() -> str | None:
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None


def _parse_mining_json(raw: str) -> tuple[list[ProposedProject], list[ProposedTask]]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise RuntimeError("miner returned no JSON")
    data = json.loads(m.group(0))
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
    return projects, standalone


def mine_projects(transcript: str, model: str | None = None) -> MiningResult:
    """Propose projects and tasks from a transcript. LLM-first, rule fallback."""
    transcript = (transcript or "").strip()
    if not transcript:
        return MiningResult(projects=[], standalone_tasks=[], engine="rule_based")

    api_key = _api_key()
    if api_key:
        try:
            from local_ai.providers import anthropic as provider

            raw = provider.generate(
                api_key,
                _MINING_PROMPT.format(transcript=transcript[:12000]),
                model=model,
            )
            projects, standalone = _parse_mining_json(raw)
            return MiningResult(projects=projects, standalone_tasks=standalone, engine="anthropic")
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
    return MiningResult(projects=[], standalone_tasks=unique[:10], engine="rule_based")
