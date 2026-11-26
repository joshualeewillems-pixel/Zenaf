"""Palace tails — the conversational verdict and weighing seams.

The chat-is-the-work law (founder, 2026-11-25 13:44 PT): processes
happen in chat with the seat; the Palace's verdict buttons (#432)
and weighing panel (#433) are superseded AS FORMS, their semantics
carried unchanged into conversation. These are the two tails that
carry them, built on the chalk carriage's discipline (#428,
local_ai/conversation/chalk_tail.py) — the machinery is the same
because the problem is the same:

* a delimiter line ([[verdict]] / [[weighing]]) opens the tail;
  instruction lines follow to the end of the reply;
* strip-always: on every outcome the returned body contains no
  delimiter line and no tail lines from a recognized tail — a
  failed tail never leaks bookkeeping into the visitor's chat;
* fail-closed: a grammar failure drops the WHOLE tail (the body
  stays intact), a bad line drops that line, nothing partially
  executes, nothing guesses;
* identical acts within one reply dedupe.

On top of the carriage discipline, two gates the brief pins:

* the subject-match gate: a verdict act executes only against the
  staged subject's own attributed-read pending set (or, for
  reconsider, its accepted readings) — a tail naming another
  subject's item, however well-formed, writes nothing. The gate is
  fail-closed by construction: the steward consent gate empties the
  pending set, so a closed gate executes nothing;
* the settle-language gate: a weighing tail executes only when the
  visitor's own current-turn words settle the figures
  (visitor_settles). Exploration — the model talking figures
  through — writes nothing, ever; the tail without his settle
  words is dropped with a diagnostic, exactly as an unsettled
  panel applied nothing in #433.

Execution mirrors the routes the panels called: verdicts through
review.apply_verdict (the ONE verdict writer), endorsements and
reconsiderations through the store's own methods, weighing figures
through the VE storage writers in #433's order, with the
scales_weighing decision record composed server-side in the
panel's exact shape when the decisions permission is on. The
service never imports the narrative package: executors are
injected, mirroring the noting writer's injection.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

VERDICT_DELIMITER = "[[verdict]]"
WEIGHING_DELIMITER = "[[weighing]]"

_TAIL_CHAR_CAP = 4000
_MAX_ACTS = 8

#: The review item kinds (local_ai/narrative/review.py ITEM_KINDS —
#: the same eight the door's buttons addressed).
VERDICT_KINDS = frozenset(
    {
        "birth",
        "reading",
        "change",
        "fitting",
        "revision",
        "oversight",
        "correspondence",
        "reconsideration",
    }
)

_VERDICT_WORDS = {
    "accept": "accepted",
    "reject": "rejected",
    "unresolved": "unresolved",
}

_ROW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


# ---------------------------------------------------------------------------
# The verdict tail
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerdictAct:
    act: str  # accept | reject | unresolved | endorse | reconsider
    kind: str
    row_id: str
    cause: str | None = None

    @property
    def item_id(self) -> str:
        return f"{self.kind}:{self.row_id}"


@dataclass
class VerdictParseResult:
    body: str
    acts: list[VerdictAct] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    status: str = "absent"  # absent | ok | malformed


def _split_tail(text: str, delimiter: str) -> tuple[str, list[str] | None]:
    """Split a reply at its delimiter line. Returns (body, tail
    lines) or (text, None) when no delimiter line exists — the text
    is then untouched, byte-identical."""
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        if line.strip() == delimiter:
            return "\n".join(lines[:idx]).rstrip(), lines[idx + 1 :]
    return text, None


def _parse_verdict_line(line: str) -> VerdictAct | None:
    """One verdict instruction line → an act, or None when the line
    is not a well-formed verdict instruction (the caller decides
    whether that is a line drop or a whole-tail failure)."""
    # Split with a maxsplit so the cause — the visitor's own words —
    # survives verbatim: everything after the cause marker, inner
    # pipes and spacing preserved, ends stripped only.
    head = line.split("|", 4)
    parts = [part.strip() for part in head]
    if len(parts) < 3 or parts[0] != "verdict":
        return None
    act = parts[1]
    kind, sep, row_id = parts[2].partition(":")
    if not sep or kind not in VERDICT_KINDS or not _ROW_ID_RE.match(row_id):
        return None
    cause: str | None = None
    if len(parts) > 3:
        if parts[3] != "cause" or len(parts) < 5:
            return None
        cause = parts[4].strip()
        if not cause:
            return None
    if act in _VERDICT_WORDS:
        if cause is not None:
            return None
        return VerdictAct(act=act, kind=kind, row_id=row_id)
    if act == "endorse":
        if kind != "reading" or cause is not None:
            return None
        return VerdictAct(act=act, kind=kind, row_id=row_id)
    if act == "reconsider":
        if kind != "reading" or not cause:
            return None
        return VerdictAct(act=act, kind=kind, row_id=row_id, cause=cause)
    return None


def parse_verdict_tail(text: str) -> VerdictParseResult:
    """Strip a [[verdict]] tail from a guardian reply and parse its
    acts. Never raises; a malformed tail yields no acts and leaves
    the body (everything before the delimiter) intact."""
    try:
        body, tail_lines = _split_tail(text, VERDICT_DELIMITER)
        if tail_lines is None:
            return VerdictParseResult(body=text, status="absent")
        diagnostics: list[str] = []
        tail_text = "\n".join(tail_lines)
        if len(tail_text) > _TAIL_CHAR_CAP:
            return VerdictParseResult(
                body=body,
                diagnostics=["verdict tail exceeds its size cap; dropped"],
                status="malformed",
            )
        acts: list[VerdictAct] = []
        seen: set[tuple[str, str, str]] = set()
        for raw in tail_lines:
            line = raw.strip()
            if not line:
                continue
            if not line.startswith("verdict"):
                # A non-instruction line inside the tail is a
                # structural failure: the whole tail drops (chalk
                # discipline — never guess where bookkeeping ends).
                return VerdictParseResult(
                    body=body,
                    diagnostics=[
                        "verdict tail held a non-instruction line; dropped whole"
                    ],
                    status="malformed",
                )
            act = _parse_verdict_line(line)
            if act is None:
                diagnostics.append(f"verdict line dropped (grammar): {line[:80]}")
                continue
            key = (act.act, act.kind, act.row_id)
            if key in seen:
                continue
            seen.add(key)
            acts.append(act)
        if len(acts) > _MAX_ACTS:
            return VerdictParseResult(
                body=body,
                diagnostics=["verdict tail exceeds its act cap; dropped"],
                status="malformed",
            )
        if not acts:
            diagnostics.append("verdict tail held no executable acts; dropped")
            return VerdictParseResult(
                body=body, diagnostics=diagnostics, status="malformed"
            )
        return VerdictParseResult(
            body=body, acts=acts, diagnostics=diagnostics, status="ok"
        )
    except Exception:
        logger.exception("palace tails: verdict parse failed")
        return VerdictParseResult(body=text, status="malformed")


# ---------------------------------------------------------------------------
# The weighing tail
# ---------------------------------------------------------------------------

_WEIGHING_FIGURES = frozenset(
    {"project_hours", "task_hours", "keeper", "keeper_capacity"}
)


@dataclass
class WeighingParseResult:
    body: str
    figures: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    status: str = "absent"  # absent | ok | malformed


def parse_weighing_tail(text: str) -> WeighingParseResult:
    """Strip a [[weighing]] tail and parse its settled figures.
    Same discipline as the verdict tail: strip-always, fail-closed,
    line drops for bad figures, whole-tail drop for structure."""
    try:
        body, tail_lines = _split_tail(text, WEIGHING_DELIMITER)
        if tail_lines is None:
            return WeighingParseResult(body=text, status="absent")
        diagnostics: list[str] = []
        tail_text = "\n".join(tail_lines)
        if len(tail_text) > _TAIL_CHAR_CAP:
            return WeighingParseResult(
                body=body,
                diagnostics=["weighing tail exceeds its size cap; dropped"],
                status="malformed",
            )
        figures: dict[str, Any] = {}
        for raw in tail_lines:
            line = raw.strip()
            if not line:
                continue
            if not line.startswith("settle"):
                return WeighingParseResult(
                    body=body,
                    diagnostics=[
                        "weighing tail held a non-instruction line; dropped whole"
                    ],
                    status="malformed",
                )
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 3 or parts[0] != "settle" or parts[1] not in _WEIGHING_FIGURES:
                diagnostics.append(f"weighing line dropped (grammar): {line[:80]}")
                continue
            name, raw_value = parts[1], parts[2]
            if name in figures:
                diagnostics.append(f"weighing figure repeated, first stands: {name}")
                continue
            if name == "keeper":
                if not _ROW_ID_RE.match(raw_value):
                    diagnostics.append("weighing keeper dropped (not a person id)")
                    continue
                figures[name] = raw_value
            else:
                try:
                    value = float(raw_value)
                except ValueError:
                    diagnostics.append(f"weighing figure dropped (not a number): {name}")
                    continue
                if not math.isfinite(value) or value < 0:
                    diagnostics.append(f"weighing figure dropped (out of range): {name}")
                    continue
                figures[name] = value
        if not figures:
            diagnostics.append("weighing tail held no figures; dropped")
            return WeighingParseResult(
                body=body, diagnostics=diagnostics, status="malformed"
            )
        return WeighingParseResult(
            body=body, figures=figures, diagnostics=diagnostics, status="ok"
        )
    except Exception:
        logger.exception("palace tails: weighing parse failed")
        return WeighingParseResult(body=text, status="malformed")


# ---------------------------------------------------------------------------
# The settle-language gate
# ---------------------------------------------------------------------------

#: The visitor's settle words — plain, contiguous phrases a person
#: says when they mean "establish it" (the firebrand round's
#: deterministic word-sequence discipline: no model judgement, no
#: fuzzy matching). Deliberately tight: exploration talk ("what if
#: we set it to 6?", "maybe settle later") never matches.
_SETTLE_PHRASES: tuple[tuple[str, ...], ...] = (
    ("settle", "it"),
    ("settle", "these"),
    ("settle", "those"),
    ("settle", "them"),
    ("settle", "the", "figures"),
    ("settle", "the", "figure"),
    ("make", "it", "so"),
    ("lock", "it", "in"),
    ("lock", "them", "in"),
    ("lock", "those", "in"),
    ("lock", "these", "in"),
    ("establish", "it"),
    ("establish", "these"),
    ("establish", "those"),
    ("establish", "them"),
    ("that's", "settled"),
    ("that", "is", "settled"),
    ("go", "with", "that"),
    ("go", "with", "those"),
    ("go", "with", "these"),
    ("go", "with", "it"),
    ("keep", "those", "figures"),
    ("keep", "that", "figure"),
    ("keep", "these", "figures"),
)

_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")


def visitor_settles(message: str) -> bool:
    """True when the visitor's own words settle the figures —
    a contiguous settle phrase in this turn's message. The weighing
    tail is honored only when this is true; everything else is
    exploration, and exploration writes nothing."""
    words = _WORD_RE.findall((message or "").lower())
    for phrase in _SETTLE_PHRASES:
        n = len(phrase)
        for start in range(0, len(words) - n + 1):
            if tuple(words[start : start + n]) == phrase:
                return True
    return False


# ---------------------------------------------------------------------------
# Executors (injected into the service; the service never imports
# the narrative package — the noting writer's pattern).
# ---------------------------------------------------------------------------


class PalaceVerdictExecutor:
    """Executes parsed verdict acts against the staged subject.

    Lazy NarrativeStore, mirroring NotingCaptureWriter: built on
    first use, injectable for tests. Every act passes the
    subject-match gate against a fresh attributed read of the
    staged subject before any writer is touched."""

    def __init__(self, store: Any = None) -> None:
        self._store = store

    def _narrative_store(self) -> Any:
        if self._store is None:
            from local_ai.narrative.store import NarrativeStore

            self._store = NarrativeStore()
        return self._store

    def execute(
        self,
        *,
        user_id: str,
        entity_type: str,
        entity_id: str,
        acts: list[VerdictAct],
    ) -> list[str]:
        from local_ai.conversation.attributed_read import attributed_read_for_subject
        from local_ai.narrative import review

        diagnostics: list[str] = []
        store = self._narrative_store()
        read = attributed_read_for_subject(
            user_id, entity_type, entity_id, narrative_store=store
        )
        if not read.get("resolved"):
            return ["verdict tail: staged subject did not resolve; nothing written"]
        pending_ids = {
            str(item.get("item_id")) for item in read.get("pending") or []
        }
        accepted_reading_ids = set()
        kintsugi = read.get("kintsugi") or {}
        for thread in kintsugi.get("threads") or []:
            for reading in thread.get("readings") or []:
                if (
                    reading.get("status") == "accepted"
                    and reading.get("placement") == "current"
                ):
                    accepted_reading_ids.add(str(reading.get("reading_id")))
        for act in acts:
            try:
                if act.act in _VERDICT_WORDS:
                    if act.item_id not in pending_ids:
                        diagnostics.append(
                            f"verdict not executed (not pending at this "
                            f"subject): {act.item_id}"
                        )
                        continue
                    review.apply_verdict(
                        store, user_id, act.item_id, _VERDICT_WORDS[act.act]
                    )
                elif act.act == "endorse":
                    if act.item_id not in pending_ids:
                        diagnostics.append(
                            f"endorsement not executed (not pending at this "
                            f"subject): {act.item_id}"
                        )
                        continue
                    store.record_card_endorsement(
                        user_id, act.row_id, "endorsed", ""
                    )
                elif act.act == "reconsider":
                    if act.row_id not in accepted_reading_ids:
                        diagnostics.append(
                            f"reconsideration not executed (no accepted "
                            f"reading by that id at this subject): "
                            f"{act.item_id}"
                        )
                        continue
                    # The store refuses a duplicate candidacy by
                    # returning the standing one — asking twice is
                    # safe, and the first asking is what stands.
                    store.propose_reading_reconsideration(
                        user_id, act.row_id, act.cause or ""
                    )
            except ValueError as exc:
                diagnostics.append(
                    f"verdict not executed ({act.item_id}): {exc}"
                )
            except Exception:
                logger.exception("palace tails: verdict execution failed")
                diagnostics.append(
                    f"verdict execution failed ({act.item_id}); see server log"
                )
        return diagnostics


def _round1(value: float) -> float:
    """One-decimal rounding, half toward +infinity — the frontend's
    Math.round semantics #433's snapshots were recorded with."""
    return math.floor(value * 10 + 0.5) / 10


class PalaceWeighingExecutor:
    """Executes settled weighing figures against the staged
    subject's anchor, mirroring #433's settleWeighing exactly:
    changes-only against the recorded baselines, a figure with no
    recorded baseline dropped, writes in the panel's order
    (project, task, capacity, decision), stop on first failure —
    no decision record when a figure write failed."""

    def execute(
        self,
        *,
        user_id: str,
        entity_type: str,
        entity_id: str,
        figures: dict[str, Any],
    ) -> list[str]:
        from local_ai.vision_execution import models as ve_models
        from local_ai.vision_execution import storage as ve

        diagnostics: list[str] = []
        project: dict[str, Any] | None = None
        task: dict[str, Any] | None = None
        if entity_type == "project":
            project = ve.get_project(entity_id, user_id)
        elif entity_type == "task":
            task = ve.get_task(entity_id, user_id)
            if task is not None and task.get("project_id"):
                project = ve.get_project(str(task["project_id"]), user_id)
        if project is None:
            return [
                "weighing not executed: the staged subject has no "
                "project anchor on the scales"
            ]
        try:
            all_projects = ve.list_projects(user_id)
            persons = ve.list_persons(user_id)
            profiles = ve.list_capacity_profiles(user_id)
            all_tasks = ve.list_tasks(user_id)
        except Exception:
            logger.exception("palace tails: weighing load failed")
            return ["weighing not executed: the record could not be read"]

        def recorded_capacity(person_id: Any) -> float | None:
            for profile in profiles:
                if profile.get("person_id") == person_id:
                    hours = profile.get("weekly_capacity_hours")
                    try:
                        return float(hours) if hours is not None else None
                    except (TypeError, ValueError):
                        return None
            return None

        def person_name(person_id: Any) -> str:
            for person in persons:
                if person.get("id") == person_id:
                    return str(person.get("name") or "")
            return ""

        baseline = {
            "project_hours": project.get("estimated_weekly_hours"),
            "task_hours": task.get("estimated_hours") if task else None,
            "keeper": project.get("owner_id"),
            "keeper_capacity": recorded_capacity(project.get("owner_id")),
        }
        # Baseline-presence: a figure with no recorded baseline
        # cannot settle (the panel rendered no such input).
        settled = dict(figures)
        for name in ("project_hours", "task_hours", "keeper_capacity"):
            if name in settled and baseline[name] is None:
                diagnostics.append(
                    f"weighing figure dropped (no recorded baseline): {name}"
                )
                del settled[name]
        if "keeper" in settled and baseline["keeper"] is None:
            diagnostics.append("weighing keeper dropped (no recorded keeper)")
            del settled["keeper"]
        if "task_hours" in settled and task is None:
            diagnostics.append("weighing task figure dropped (no task anchor)")
            del settled["task_hours"]
        if not settled:
            diagnostics.append("weighing settled nothing")
            return diagnostics

        arranged = {
            "project_hours": settled.get("project_hours", baseline["project_hours"]),
            "task_hours": settled.get("task_hours", baseline["task_hours"]),
            "keeper": settled.get("keeper", baseline["keeper"]),
        }
        if "keeper" in settled:
            arranged_capacity = recorded_capacity(arranged["keeper"])
        else:
            arranged_capacity = baseline["keeper_capacity"]
        if "keeper_capacity" in settled:
            if recorded_capacity(arranged["keeper"]) is None:
                # The capacity figure's baseline is the arranged
                # keeper's recorded capacity (the panel's input
                # followed the keeper): a keeper with none recorded
                # has no capacity baseline to settle against.
                diagnostics.append(
                    "weighing figure dropped (no recorded baseline): "
                    "keeper_capacity"
                )
                del settled["keeper_capacity"]
            else:
                arranged_capacity = settled["keeper_capacity"]
        arranged["keeper_capacity"] = arranged_capacity

        def num(value: Any) -> float | None:
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        project_patch: dict[str, Any] = {}
        if num(arranged["project_hours"]) != num(baseline["project_hours"]):
            project_patch["estimated_weekly_hours"] = arranged["project_hours"]
        if arranged["keeper"] != baseline["keeper"]:
            project_patch["owner_id"] = arranged["keeper"]
        task_patch: dict[str, Any] = {}
        if task is not None and num(arranged["task_hours"]) != num(baseline["task_hours"]):
            task_patch["estimated_hours"] = arranged["task_hours"]
        capacity_put: dict[str, Any] | None = None
        if (
            arranged["keeper"] is not None
            and num(arranged_capacity) != num(recorded_capacity(arranged["keeper"]))
            and arranged_capacity is not None
        ):
            capacity_put = {
                "person_id": arranged["keeper"],
                "weekly_capacity_hours": arranged_capacity,
            }
        if not project_patch and not task_patch and capacity_put is None:
            diagnostics.append(
                "weighing matched the record as it stands; nothing written"
            )
            return diagnostics

        def figure_snapshot(figs: dict[str, Any]) -> dict[str, Any]:
            snap: dict[str, Any] = {
                "project_id": project["id"],
                "project_weekly_hours": num(figs["project_hours"]),
                "keeper_id": figs["keeper"],
                "keeper_capacity_hours": num(figs["keeper_capacity"]),
            }
            if task is not None:
                snap["task_id"] = task["id"]
                snap["task_estimated_hours"] = num(figs["task_hours"])
            return snap

        def capacity_picture(
            project_rows: list[dict[str, Any]], capacity: float | None, pid: str
        ) -> tuple[float, float | None, bool]:
            active = 0.0
            for row in project_rows:
                if str(row.get("status") or "").strip().lower() not in (
                    "ready",
                    "active",
                ):
                    continue
                hours = num(row.get("estimated_weekly_hours")) or 0.0
                if row.get("owner_id") == pid:
                    active += hours
                elif pid in (row.get("supporting_owner_ids") or []):
                    active += hours
            committed = _round1(active)
            if capacity is None:
                return committed, None, False
            delta = _round1(active - capacity)
            return committed, delta, (active - capacity) > 0

        def consequences(
            figs: dict[str, Any], *, arranged_side: bool
        ) -> list[dict[str, Any]]:
            if arranged_side:
                rows = [
                    (
                        {
                            **row,
                            "estimated_weekly_hours": figs["project_hours"],
                            "owner_id": figs["keeper"],
                        }
                        if row.get("id") == project["id"]
                        else row
                    )
                    for row in all_projects
                ]

                def cap_of(pid: str) -> float | None:
                    if pid == figs["keeper"]:
                        return num(figs["keeper_capacity"])
                    return recorded_capacity(pid)
            else:
                rows = all_projects

                def cap_of(pid: str) -> float | None:
                    return recorded_capacity(pid)

            touched: list[str] = []
            for pid in (figs["keeper"], baseline["keeper"]):
                if pid and pid not in touched:
                    touched.append(pid)
            for pid in project.get("supporting_owner_ids") or []:
                if pid not in touched:
                    touched.append(pid)
            for t in all_tasks:
                if t.get("project_id") == project["id"] and t.get("assignee_id"):
                    if t["assignee_id"] not in touched:
                        touched.append(t["assignee_id"])
            out: list[dict[str, Any]] = []
            for pid in touched:
                cap = cap_of(pid)
                committed, delta, over = capacity_picture(rows, cap, pid)
                out.append(
                    {
                        "person_id": pid,
                        "name": person_name(pid),
                        "committed_hours": committed,
                        "capacity_hours": cap,
                        "capacity_delta": delta,
                        "overcapacity": over,
                    }
                )
            return out

        recorded_before = figure_snapshot(baseline)
        settled_snapshot = figure_snapshot(arranged)
        on_project = bool(project_patch) or capacity_put is not None or task is None
        decision = {
            "entity_type": "project" if on_project else "task",
            "entity_id": project["id"] if on_project else task["id"],
            "decision_type": "scales_weighing",
            "ai_proposal_snapshot": {
                "kind": "scales_weighing",
                "explored": settled_snapshot,
                "recorded_before": recorded_before,
                "consequences": consequences(arranged, arranged_side=True),
            },
            "final_values_snapshot": {
                "kind": "scales_weighing",
                "settled": settled_snapshot,
                "recorded_before": recorded_before,
            },
        }

        # Writes in the panel's order; stop on first failure — the
        # decision record is never written when a figure failed.
        if project_patch:
            if (
                ve.update_project(
                    project["id"], ve_models.ProjectUpdate(**project_patch), user_id
                )
                is None
            ):
                diagnostics.append(
                    "weighing stopped: the project figure write failed; "
                    "nothing further written"
                )
                return diagnostics
        if task_patch:
            if (
                ve.update_task(
                    task["id"], ve_models.TaskUpdate(**task_patch), user_id
                )
                is None
            ):
                diagnostics.append(
                    "weighing stopped: the task figure write failed; "
                    "the decision was not recorded"
                )
                return diagnostics
        if capacity_put is not None:
            ve.upsert_capacity_profile(
                ve_models.CapacityProfileUpsert(**capacity_put), user_id
            )
        # The decision record rides the decisions permission, as the
        # POST /decisions route gates it: refused, the figures still
        # stand (they are the visitor's own record) and no decision
        # is kept — the same split the route enforces.
        try:
            if ve.user_permission_enabled(user_id, "profile_learning"):
                ve.create_decision(
                    ve_models.DecisionCreate(user_id=user_id, **decision)
                )
            else:
                diagnostics.append(
                    "weighing figures stand; the decision record was "
                    "not kept (decisions permission off)"
                )
        except Exception:
            logger.exception("palace tails: weighing decision write failed")
            diagnostics.append(
                "weighing figures stand; the decision record failed to write"
            )
        return diagnostics


def default_palace_verdict_executor() -> PalaceVerdictExecutor:
    return PalaceVerdictExecutor()


def default_palace_weighing_executor() -> PalaceWeighingExecutor:
    return PalaceWeighingExecutor()
