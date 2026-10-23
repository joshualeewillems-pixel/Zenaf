"""Mining dedupe tests (Joshua, 2026-10-23).

Mining used to be blind: the miner never saw the existing workspace and
confirm created whatever titles were selected, so mining two
conversations about the same project created it twice. These tests pin
the layered fix against a fake VE service: proposals are annotated with
their existing match, and create_confirmed links instead of creating.
Identity is normalized-title equality only.
"""

from __future__ import annotations

import pytest

from local_ai.agent_intake import project_miner as pm
from local_ai.vision_execution import service as ve_service


class FakeVE:
    """Dict-backed VE store recording every creation."""

    def __init__(self):
        self.initiatives: list[dict] = []
        self.projects: list[dict] = []
        self.tasks: list[dict] = []
        self.ideas: list[dict] = []
        self.created: list[tuple[str, str]] = []
        self._seq = 0

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    # -- lists ------------------------------------------------------
    def list_initiatives(self, user_id):
        return list(self.initiatives)

    def list_projects(self, user_id):
        return list(self.projects)

    def list_tasks(self, user_id, project_id=None):
        rows = self.tasks
        if project_id is not None:
            rows = [t for t in rows if t.get("project_id") == project_id]
        return list(rows)

    def list_ideas(self, user_id):
        return list(self.ideas)

    # -- creates ----------------------------------------------------
    def create_initiative(self, data, user_id):
        row = {"id": self._next("init"), "title": data.title}
        self.initiatives.append(row)
        self.created.append(("initiative", data.title))
        return row

    def create_project(self, data, user_id):
        row = {"id": self._next("proj"), "title": data.title,
               "initiative_id": data.initiative_id}
        self.projects.append(row)
        self.created.append(("project", data.title))
        return row

    def create_task(self, data, user_id):
        row = {"id": self._next("task"), "title": data.title,
               "project_id": data.project_id}
        self.tasks.append(row)
        self.created.append(("task", data.title))
        return row

    def create_idea(self, data, user_id):
        row = {"id": self._next("idea"), "title": data.title}
        self.ideas.append(row)
        self.created.append(("idea", data.title))
        return row

    def create_checklist_items_batch(self, idea_id, batch, user_id):
        return None


@pytest.fixture()
def fake_ve(monkeypatch):
    fake = FakeVE()
    for name in (
        "list_initiatives", "list_projects", "list_tasks", "list_ideas",
        "create_initiative", "create_project", "create_task", "create_idea",
        "create_checklist_items_batch",
    ):
        monkeypatch.setattr(ve_service, name, getattr(fake, name))
    return fake


def _result(**kw) -> pm.MiningResult:
    base = dict(initiatives=[], projects=[], standalone_tasks=[], ideas=[],
                engine="anthropic")
    base.update(kw)
    return pm.MiningResult(**base)


def test_norm_title_identity():
    assert pm._norm_title("Normalize  Confidence!") == pm._norm_title("normalize confidence")
    assert pm._norm_title("  My Project — v2 ") == "my project v2"


def test_annotate_existing_marks_matches(fake_ve):
    fake_ve.projects.append({"id": "proj-x", "title": "Normalize Confidence"})
    result = _result(projects=[pm.ProposedProject(title="normalize confidence!")])
    pm.annotate_existing(result, "u1")
    assert result.projects[0].existing_id == "proj-x"
    assert result.projects[0].existing_title == "Normalize Confidence"


def test_confirm_links_initiative_and_project_nests_under_both(fake_ve):
    fake_ve.initiatives.append({"id": "init-1", "title": "Zenaf Build"})
    fake_ve.projects.append({"id": "proj-1", "title": "Confidence UI",
                             "initiative_id": "init-1"})
    fake_ve.tasks.append({"id": "task-1", "title": "Old task",
                          "project_id": "proj-1"})
    result = _result(
        initiatives=[pm.ProposedInitiative(title="zenaf build")],
        projects=[pm.ProposedProject(
            title="Confidence UI", initiative_title="zenaf build",
            tasks=[pm.ProposedTask(title="Old task"),
                   pm.ProposedTask(title="New task")],
        )],
    )
    out = pm.create_confirmed(result, "u1")
    # Nothing at the initiative/project level was created again.
    assert fake_ve.created == [("task", "New task")]
    assert out["linked_initiative_ids"] == ["init-1"]
    assert out["linked_project_ids"] == ["proj-1"]
    # The genuinely new task landed under the EXISTING project.
    assert fake_ve.tasks[-1]["project_id"] == "proj-1"
    assert out["task_ids"] == [fake_ve.tasks[-1]["id"]]


def test_confirm_links_standalone_task_and_idea(fake_ve):
    fake_ve.tasks.append({"id": "task-9", "title": "Water the plants",
                          "project_id": None})
    fake_ve.ideas.append({"id": "idea-9", "title": "A quiet orchard"})
    result = _result(
        standalone_tasks=[pm.ProposedTask(title="Water the plants")],
        ideas=[pm.ProposedIdea(title="a quiet orchard")],
    )
    out = pm.create_confirmed(result, "u1")
    assert fake_ve.created == []
    assert out["linked_task_ids"] == ["task-9"]
    assert out["linked_idea_ids"] == ["idea-9"]


def test_confirm_creates_when_nothing_matches(fake_ve):
    result = _result(
        initiatives=[pm.ProposedInitiative(title="Fresh Initiative")],
        projects=[pm.ProposedProject(
            title="Fresh Project", initiative_title="Fresh Initiative",
            tasks=[pm.ProposedTask(title="First step")],
        )],
        standalone_tasks=[pm.ProposedTask(title="Loose end")],
        ideas=[pm.ProposedIdea(title="Fresh idea")],
    )
    out = pm.create_confirmed(result, "u1")
    assert out["initiative_ids"] and out["project_ids"] and out["idea_ids"]
    assert len(out["task_ids"]) == 2
    assert out["linked_project_ids"] == []
    # The project nested under the initiative created in the same batch.
    assert fake_ve.projects[0]["initiative_id"] == fake_ve.initiatives[0]["id"]
