"""New-undertaking diagnosis authoring + seat recompute (slice S5).

Temporal Orchestration, slice step S5 (brief
``zenaf-temporal-orchestration-slice-brief-2026-11-28.md`` §§5, 6,
7, 9). Two capabilities, both deterministic, **no model calls
anywhere in this module** — the seat conversation supplies the
elicitation; this module supplies structure:

1. **Authoring (§6, scenario 2).** ``propose_new_diagnosis``
   creates a diagnosis proposal for an undertaking that does NOT
   exist in VE yet. It infers the requirement categories the
   undertaking type implies from a template (data, keyed by
   ``undertaking_kind``, with a generic fallback), and emits a
   structured first-cut diagnosis in exactly the proposal-class
   shape S4 defined: goal → requirements → tasks, every node typed
   (origin, effort representation, confidence), and **named
   unknowns as gating requirement nodes** — each unknown carries a
   directed discovery task naming what would resolve it, and the
   tasks it gates are effort-unknown and dependency-bound to that
   discovery task until the unknown is resolved. The proposal is
   keyed by a prospective project id minted at authoring time; it
   flows through S4's edit / arrangement / approval machinery
   unchanged, and S4's establishment (extended minimally there)
   creates the project under that id as its first write. A fact
   the visitor already knows (``known_facts``, e.g. the platform
   is chosen) resolves its unknown at authoring: no question is
   emitted and the gated work keeps its template estimates.

2. **Seat recompute (§7).** ``recompute_arrangement`` is the one
   deterministic capability the seats deliberate with: given a base
   (a retained diagnosis proposal, or an ad-hoc hypothetical task
   set), scenario **deltas** (effort, capacity, dependencies,
   priority, competing commitments — added/removed windows and
   allocation changes) and **toggles** (the provisional layer,
   firm-only mode, target-advances), it assembles the world from
   the current record at a named fold_seq, applies the deltas as a
   scenario layer (namespaced ids, brief §5), runs the S3 kernel,
   and returns the stamped summary. **It persists nothing**: no
   decisions, no proposals, no canonical writes — a hypothetical
   is a temporary calculation (brief §1), retained only if the
   visitor later turns it into a proposal through S4's paths.

Capacity honesty (brief §5): the provisional layer — projects
whose only span standing is a provisional hypothesis — joins a
recompute ONLY when explicitly toggled, as scenario work. It
never enters the baseline and never reserves established
capacity, in either mode.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, timedelta
from typing import Any

from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as S
from local_ai.vision_execution import temporal_diagnosis as TD
from local_ai.vision_execution import temporal_kernel as K
from local_ai.vision_execution import temporal_standing as T

#: Scenario-layer id prefix (brief §5): work that exists only
#: inside a named scenario is namespaced so nothing canonical can
#: ever bind to it.
SCENARIO_PREFIX = "scenario:"

_DONE_STATUSES = frozenset({"done", "complete", "completed"})


def _exact(hours: float) -> dict[str, Any]:
    return {"kind": "exact", "hours": float(hours)}


def _interval(low: float, high: float) -> dict[str, Any]:
    return {"kind": "interval", "low_hours": float(low), "high_hours": float(high)}


_UNKNOWN_EFFORT: dict[str, Any] = {"kind": "unknown"}

_CAPACITY_ASSUMPTION = {
    "id": "recorded-capacity-holds",
    "type": "capacity",
    "statement": "The owner's recorded weekly capacity "
    "holds uninterrupted over the arranged window.",
}


# ---------------------------------------------------------------------------
# Undertaking templates (data; brief §6)
#
# A template is a list of requirement categories, each with first-cut
# tasks, plus a list of named unknowns. Task references are
# "<category>:<task key>" and resolve to node ids at authoring. An
# unknown gates task references: while it is unresolved those tasks
# carry unknown effort and depend on the unknown's discovery task.
# ---------------------------------------------------------------------------

STOREFRONT_TEMPLATE: dict[str, Any] = {
    "kind": "storefront",
    "categories": [
        {
            "key": "entity-tax",
            "title": "Entity & tax",
            "acceptance_criteria": "The selling entity is confirmed "
            "and its tax registrations are recorded.",
            "tasks": [
                {
                    "key": "confirm-entity",
                    "title": "Confirm the selling entity and EIN on record",
                    "effort": _exact(2),
                    "completion_criteria": "Entity name and EIN recorded",
                },
                {
                    "key": "sales-tax-registration",
                    "title": "Register for sales tax / seller's permit "
                    "where the store will sell",
                    "effort": _interval(2, 5),
                    "completion_criteria": "Registrations recorded for "
                    "each selling jurisdiction",
                },
            ],
        },
        {
            "key": "platform",
            "title": "Platform",
            "acceptance_criteria": "The storefront stands up on the "
            "chosen platform with its basics configured.",
            "tasks": [
                {
                    "key": "stand-up",
                    "title": "Stand up the storefront on the chosen platform",
                    "effort": _interval(4, 10),
                    "completion_criteria": "Store reachable with the "
                    "offer's structure in place",
                },
                {
                    "key": "configure-basics",
                    "title": "Configure store basics (name, currency, "
                    "policy placeholders)",
                    "effort": _exact(3),
                    "completion_criteria": "Basics saved and visible "
                    "in the storefront",
                    "depends_on": ["platform:stand-up"],
                },
            ],
        },
        {
            "key": "payments",
            "title": "Payments",
            "acceptance_criteria": "A test charge settles and a "
            "payout is verified end to end.",
            "tasks": [
                {
                    "key": "processor-setup",
                    "title": "Set up payment processing and verify a "
                    "test charge and payout",
                    "effort": _interval(3, 6),
                    "completion_criteria": "Test charge settled; "
                    "payout reached the entity's account",
                },
            ],
        },
        {
            "key": "offer-content",
            "title": "Offer & content",
            "acceptance_criteria": "The offer and product pages are "
            "written and the listing media meets the platform's spec.",
            "tasks": [
                {
                    "key": "offer-copy",
                    "title": "Write the offer and product pages",
                    "effort": _interval(5, 10),
                    "completion_criteria": "Pages published in draft "
                    "on the storefront",
                },
                {
                    "key": "media",
                    "title": "Produce product photos / listing media "
                    "to the platform's spec",
                    "effort": _interval(4, 8),
                    "completion_criteria": "Media uploaded and "
                    "rendering correctly on the listings",
                },
            ],
        },
        {
            "key": "fulfillment",
            "title": "Fulfillment",
            "acceptance_criteria": "An order can travel from "
            "checkout to the customer, and returns have a defined path.",
            "tasks": [
                {
                    "key": "shipping-setup",
                    "title": "Set up the shipping / fulfillment workflow",
                    "effort": _interval(3, 6),
                    "completion_criteria": "A test order fulfills "
                    "end to end",
                },
                {
                    "key": "returns-flow",
                    "title": "Define the returns and refund handling flow",
                    "effort": _exact(2),
                    "completion_criteria": "Returns flow written and "
                    "linked from the storefront",
                },
            ],
        },
        {
            "key": "compliance",
            "title": "Compliance",
            "acceptance_criteria": "Policy pages are published and "
            "the product category's permits are checked.",
            "tasks": [
                {
                    "key": "policy-pages",
                    "title": "Publish privacy, terms, and refund "
                    "policy pages",
                    "effort": _exact(2),
                    "completion_criteria": "Policy pages live on the "
                    "storefront",
                    "depends_on": ["platform:stand-up"],
                },
                {
                    "key": "license-check",
                    "title": "Check licenses / permits for the "
                    "product category",
                    "effort": _interval(1, 4),
                    "completion_criteria": "Permit position recorded, "
                    "or the needed permits obtained",
                },
            ],
        },
    ],
    "unknowns": [
        {
            "key": "platform",
            "fact_key": "platform",
            "question": "Which platform will the storefront run on "
            "(e.g. Shopify, WooCommerce, Etsy, or another)?",
            "discovery": "Compare the candidate platforms against "
            "the offer's needs — fees, fulfillment integrations, "
            "media specs — and record the choice and its reason.",
            "discovery_task": {
                "title": "Research and choose the storefront platform",
                "effort": _interval(2, 6),
                "completion_criteria": "Platform choice recorded "
                "with the reason",
            },
            "gates": [
                "platform:stand-up",
                "offer-content:offer-copy",
                "offer-content:media",
                "fulfillment:shipping-setup",
            ],
        },
        {
            "key": "fulfillment-model",
            "fact_key": "fulfillment_model",
            "question": "How will orders be fulfilled — "
            "self-fulfilled, print-on-demand, or drop-shipped?",
            "discovery": "Weigh the fulfillment models against the "
            "offer's margins and the time the owner can give it, "
            "and record the model chosen.",
            "discovery_task": {
                "title": "Choose the fulfillment model",
                "effort": _interval(1, 3),
                "completion_criteria": "Fulfillment model recorded "
                "with the reason",
            },
            "gates": ["fulfillment:shipping-setup"],
        },
    ],
}

GENERIC_TEMPLATE: dict[str, Any] = {
    "kind": "generic",
    "categories": [
        {
            "key": "outcome",
            "title": "Outcome",
            "acceptance_criteria": "The intended outcome is stated "
            "and recognizable when reached.",
            "tasks": [
                {
                    "key": "record-outcome",
                    "title": "Record the intended outcome and how it "
                    "will be recognized",
                    "effort": _exact(1),
                    "completion_criteria": "Outcome statement recorded",
                },
            ],
        },
        {
            "key": "scope",
            "title": "Scope",
            "acceptance_criteria": "What is in scope — and what is "
            "explicitly not — is recorded.",
            "tasks": [
                {
                    "key": "in-scope",
                    "title": "List what is in scope",
                    "effort": dict(_UNKNOWN_EFFORT),
                    "completion_criteria": "Scope list recorded",
                },
                {
                    "key": "non-goals",
                    "title": "List the explicit non-goals",
                    "effort": _exact(1),
                    "completion_criteria": "Non-goals recorded",
                },
            ],
        },
        {
            "key": "resources",
            "title": "Resources",
            "acceptance_criteria": "The people, money, and tools "
            "this needs are inventoried.",
            "tasks": [
                {
                    "key": "inventory",
                    "title": "Inventory the people, money, and tools "
                    "this undertaking needs",
                    "effort": dict(_UNKNOWN_EFFORT),
                    "completion_criteria": "Resource inventory recorded",
                },
            ],
        },
        {
            "key": "prerequisites",
            "title": "Prerequisites",
            "acceptance_criteria": "What must exist or happen first "
            "is named.",
            "tasks": [
                {
                    "key": "name-first",
                    "title": "Name what must exist or happen first",
                    "effort": dict(_UNKNOWN_EFFORT),
                    "completion_criteria": "Prerequisites recorded, "
                    "or confirmed none",
                },
            ],
        },
        {
            "key": "risks",
            "title": "Risks",
            "acceptance_criteria": "The main risks are named, each "
            "with what would retire it.",
            "tasks": [
                {
                    "key": "name-risks",
                    "title": "Name the main risks and what would "
                    "retire each",
                    "effort": _interval(1, 3),
                    "completion_criteria": "Risk list recorded",
                },
            ],
        },
    ],
    "unknowns": [
        {
            "key": "approach",
            "fact_key": "approach",
            "question": "What approach or vehicle will realize "
            "this undertaking?",
            "discovery": "Compare the plausible approaches against "
            "the outcome and record the choice and its reason.",
            "discovery_task": {
                "title": "Choose the approach",
                "effort": _interval(1, 4),
                "completion_criteria": "Approach recorded with the "
                "reason",
            },
            "gates": ["scope:in-scope", "resources:inventory"],
        },
    ],
}

#: Templates are data, keyed by undertaking kind. Unknown kinds
#: fall back to the generic skeleton — a first cut that knows its
#: own limits (its estimates are honestly unknown).
UNDERTAKING_TEMPLATES: dict[str, dict[str, Any]] = {
    "storefront": STOREFRONT_TEMPLATE,
    "commerce": STOREFRONT_TEMPLATE,
    "generic": GENERIC_TEMPLATE,
}


def template_for(undertaking_kind: str | None) -> dict[str, Any]:
    return UNDERTAKING_TEMPLATES.get(
        str(undertaking_kind or "").strip().lower(), GENERIC_TEMPLATE
    )


# ---------------------------------------------------------------------------
# Authoring (brief §6, scenario 2)
# ---------------------------------------------------------------------------


def _node_id(category_key: str, task_key: str) -> str:
    return f"task:prop:{category_key}:{task_key}"


def _req_id(category_key: str) -> str:
    return f"req:prop:{category_key}"


def _unknown_node_id(unknown_key: str) -> str:
    return f"task:prop:unknown:{unknown_key}"


def _unknown_req_id(unknown_key: str) -> str:
    return f"req:prop:unknown:{unknown_key}"


def _single_person_id(user_id: str) -> str | None:
    """The capacity person when the record holds exactly one —
    the founder's own person record is the ordinary case. More
    than one (or none) is genuinely ambiguous and stays a named
    question rather than a guess."""
    persons = S.list_persons(user_id)
    if len(persons) == 1:
        return str(persons[0]["id"])
    return None


def propose_new_diagnosis(
    user_id: str,
    *,
    title: str,
    goal_text: str,
    undertaking_kind: str,
    known_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Author a first-cut diagnosis for a NEW undertaking and
    persist it as a pending diagnosis proposal (brief §6).

    The undertaking has no VE project: the proposal is keyed by a
    prospective project id minted here, and the diagnosis carries
    ``prospective_project`` so S4's world assembly and
    establishment treat it as a not-yet-created undertaking.
    ``known_facts`` is what the seat's elicitation already
    established — a fact matching an unknown's ``fact_key``
    resolves that unknown at authoring, and ``person_id`` names
    whose capacity the undertaking draws on (defaulting to the
    owner's single person record when the record holds exactly
    one; otherwise capacity stays a named question, as in S4).

    No model calls: the categories are inferred from the template
    for ``undertaking_kind``; everything the template cannot know
    is emitted as a named unknown or an unknown effort, never
    filled in.
    """
    S._require_owner_id(user_id)
    known_facts = dict(known_facts or {})
    template = template_for(undertaking_kind)
    project_id = M.new_id()
    person_id = known_facts.get("person_id") or _single_person_id(user_id)
    if person_id is not None:
        person_id = str(person_id)

    # Task references in the template ("<category>:<key>") resolve
    # to node ids; unknowns gate by reference.
    ref_to_node: dict[str, str] = {}
    for category in template["categories"]:
        for task in category["tasks"]:
            ref_to_node[f"{category['key']}:{task['key']}"] = _node_id(
                category["key"], task["key"]
            )

    unknowns = template.get("unknowns") or []
    resolved_facts: dict[str, Any] = {}
    gated_by: dict[str, list[str]] = {}  # node id -> [unknown keys]
    for unknown in unknowns:
        fact = known_facts.get(unknown["fact_key"])
        if fact:
            resolved_facts[unknown["key"]] = fact
        for ref in unknown.get("gates") or []:
            node_id = ref_to_node.get(ref)
            if node_id:
                gated_by.setdefault(node_id, []).append(unknown["key"])

    task_nodes: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []

    for category in template["categories"]:
        node_ids: list[str] = []
        for task in category["tasks"]:
            node_id = _node_id(category["key"], task["key"])
            deps = [
                ref_to_node[ref]
                for ref in (task.get("depends_on") or [])
                if ref in ref_to_node
            ]
            effort = copy.deepcopy(task["effort"])
            for unknown_key in gated_by.get(node_id, []):
                unknown = next(u for u in unknowns if u["key"] == unknown_key)
                discovery_id = _unknown_node_id(unknown_key)
                if discovery_id not in deps:
                    deps.append(discovery_id)
                if unknown_key not in resolved_facts:
                    # Unresolved: the work cannot be estimated
                    # until the unknown is answered — its effort
                    # is honestly unknown, and the discovery task
                    # gates it.
                    effort = dict(_UNKNOWN_EFFORT)
            node = {
                "id": node_id,
                "ref_task_id": None,
                "requirement_id": _req_id(category["key"]),
                "title": task["title"],
                "origin": "derived",
                "effort": effort,
                "confidence_label": TD._effort_label(effort),
                "dependencies": deps,
                "status": "Todo",
                "priority": "",
                "due_date": None,
                "timeframe_commitment": None,
                "completion_criteria": task.get("completion_criteria") or "",
                "assumption_refs": [],
            }
            task_nodes.append(node)
            node_ids.append(node_id)
        cat_nodes = [n for n in task_nodes if n["id"] in node_ids]
        combined = TD._combined_effort(cat_nodes)
        requirements.append(
            {
                "id": _req_id(category["key"]),
                "ref_task_id": None,
                "title": category["title"],
                "acceptance_criteria": category.get("acceptance_criteria")
                or "",
                "origin": "derived",
                "effort": combined,
                "confidence_label": TD._effort_label(combined),
                "dependencies": [],
                "unlock": "task",
                "task_node_ids": node_ids,
                "assumption_refs": [],
            }
        )

    for unknown in unknowns:
        discovery_id = _unknown_node_id(unknown["key"])
        gated_nodes = [
            ref_to_node[ref]
            for ref in (unknown.get("gates") or [])
            if ref in ref_to_node
        ]
        fact = resolved_facts.get(unknown["key"])
        spec = unknown["discovery_task"]
        if fact:
            discovery_title = (
                f"Record the {unknown['fact_key']} choice "
                f"({fact}) and set up what it implies"
            )
            origin = "visitor-recorded"
        else:
            discovery_title = spec["title"]
            origin = "derived"
        effort = copy.deepcopy(spec["effort"])
        task_nodes.append(
            {
                "id": discovery_id,
                "ref_task_id": None,
                "requirement_id": _unknown_req_id(unknown["key"]),
                "title": discovery_title,
                "origin": origin,
                "effort": effort,
                "confidence_label": TD._effort_label(effort),
                "dependencies": [],
                "status": "Todo",
                "priority": "",
                "due_date": None,
                "timeframe_commitment": None,
                "completion_criteria": spec.get("completion_criteria") or "",
                "assumption_refs": [],
            }
        )
        requirement = {
            "id": _unknown_req_id(unknown["key"]),
            "ref_task_id": None,
            "title": f"Unknown: {unknown['question']}",
            "acceptance_criteria": spec.get("completion_criteria") or "",
            "origin": origin,
            "effort": effort,
            "confidence_label": TD._effort_label(effort),
            "dependencies": [],
            "unlock": "task",
            "task_node_ids": [discovery_id],
            "assumption_refs": [],
            "unknown": True,
            "fact_key": unknown["fact_key"],
            "gates": gated_nodes,
        }
        if fact:
            requirement["resolved_by_fact"] = fact
        requirements.append(requirement)
        if not fact:
            questions.append(
                {
                    "id": f"q:unknown:{unknown['key']}",
                    "question": unknown["question"],
                    "discovery": unknown["discovery"],
                    "gates": gated_nodes,
                    "origin": "derived",
                }
            )

    if person_id is None:
        questions.append(
            {
                "id": "q:capacity",
                "question": "No single person record names whose "
                "capacity this undertaking draws on.",
                "discovery": "Name the person whose capacity this "
                "undertaking draws on.",
                "gates": [n["id"] for n in task_nodes],
                "origin": "derived",
            }
        )

    diagnosis: dict[str, Any] = {
        "kind": "temporal_diagnosis",
        "project_id": project_id,
        "person_id": person_id,
        "seat": TD.DIAGNOSIS_SEAT,
        "source": "authored_new_undertaking",
        "undertaking_kind": template["kind"],
        "title": title,
        "prospective_project": {
            "id": project_id,
            "title": title,
            "brief": goal_text,
            "status": "Draft",
        },
        "known_facts": known_facts,
        "goal": {"title": title, "brief": goal_text, "origin": "visitor-recorded"},
        "requirements": requirements,
        "tasks": task_nodes,
        "unresolved_questions": questions,
        "assumptions": [dict(_CAPACITY_ASSUMPTION)],
    }
    return TD._create_next_version(
        user_id, project_id, diagnosis, supersedes_id=None
    )


# ---------------------------------------------------------------------------
# Seat recompute (brief §7)
# ---------------------------------------------------------------------------


def _adhoc_diagnosis(user_id: str, base: dict[str, Any]) -> dict[str, Any]:
    """Synthesize an (unpersisted) diagnosis for an ad-hoc task
    set, so a hypothetical with no retained proposal runs through
    the same world assembly as a real diagnosis."""
    person_id = base.get("person_id") or _single_person_id(user_id)
    target_project_id = str(base.get("target_project_id") or "scenario:adhoc")
    nodes: list[dict[str, Any]] = []
    for raw in base.get("tasks") or []:
        effort = raw.get("effort")
        if effort is None:
            effort = K.effort_from_hours(raw.get("estimated_hours"))
        nodes.append(
            {
                "id": str(raw["id"]),
                "ref_task_id": None,
                "requirement_id": None,
                "title": str(raw.get("title") or raw["id"]),
                "origin": "proposed",
                "effort": effort,
                "confidence_label": TD._effort_label(effort),
                "dependencies": [
                    str(d)
                    for d in (raw.get("dependencies") or raw.get("dependency_ids") or [])
                ],
                "status": raw.get("status") or "Todo",
                "priority": raw.get("priority") or "",
                "due_date": raw.get("due_date"),
                "timeframe_commitment": raw.get("timeframe_commitment"),
                "completion_criteria": raw.get("completion_criteria") or "",
                "assumption_refs": [],
            }
        )
    return {
        "kind": "temporal_diagnosis",
        "project_id": target_project_id,
        "person_id": str(person_id) if person_id else None,
        "seat": TD.DIAGNOSIS_SEAT,
        "source": "adhoc_scenario",
        "prospective_project": {
            "id": target_project_id,
            "title": str(base.get("title") or "Ad-hoc scenario"),
            "brief": "",
            "status": "Draft",
        },
        "goal": {
            "title": str(base.get("title") or "Ad-hoc scenario"),
            "brief": "",
            "origin": "proposed",
        },
        "requirements": [],
        "tasks": nodes,
        "unresolved_questions": [],
        "assumptions": [dict(_CAPACITY_ASSUMPTION)],
    }


def _provisional_layer(
    user_id: str,
    person_id: str,
    fold: dict[str, Any],
    *,
    world_task_ids: set[str],
    target_project_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The provisional layer (brief §5): open work from projects
    whose standing includes a provisional span, as scenario tasks
    with namespaced ids. Projects already counted as recorded
    demand (their tasks are in the world) are skipped — the layer
    adds only what the baseline cannot see, and it reserves
    nothing: scenario work never writes allocations."""
    layer: list[dict[str, Any]] = []
    project_ids: list[str] = []
    for pid, pdata in (fold.get("projects") or {}).items():
        if pid == target_project_id:
            continue
        spans = pdata.get("spans") or []
        if not any(s.get("standing") == "provisional" for s in spans):
            continue
        project = S.get_project(pid, user_id)
        if project is None or project.get("owner_id") != person_id:
            continue
        open_tasks = [
            t
            for t in S.list_tasks(user_id, project_id=pid)
            if (t.get("status") or "").lower() not in _DONE_STATUSES
        ]
        if not open_tasks:
            continue
        if any(str(t["id"]) in world_task_ids for t in open_tasks):
            continue
        id_map = {
            str(t["id"]): f"{SCENARIO_PREFIX}{t['id']}" for t in open_tasks
        }
        for t in open_tasks:
            deps = [
                id_map.get(str(d), str(d))
                for d in (t.get("dependency_ids") or [])
            ]
            layer.append(
                {
                    "id": id_map[str(t["id"])],
                    "project_id": pid,
                    "effort": K.effort_from_hours(t.get("estimated_hours")),
                    "dependencies": deps,
                    "timeframe_commitment": t.get("timeframe_commitment"),
                    "due_date": t.get("due_date"),
                    "priority": t.get("priority") or "",
                    "status": t.get("status") or "",
                }
            )
        project_ids.append(pid)
    return layer, project_ids


def _monday(iso: str) -> str:
    d = date.fromisoformat(str(iso)[:10])
    return (d - timedelta(days=d.weekday())).isoformat()


def _apply_allocation_deltas(
    series: Any, deltas: dict[str, Any]
) -> dict[str, Any]:
    """Apply competing-commitment changes to a copy of the fold's
    allocation series: ``add_allocations`` consumes capacity in a
    week bucket, ``remove_allocations`` releases it (never below
    zero). The fold itself is untouched — this is scenario state."""
    weeks: dict[str, dict[str, Any]] = {}
    if isinstance(series, dict):
        for week, bucket in (series.get("weeks") or {}).items():
            weeks[week] = {
                "established_hours": float(bucket.get("established_hours") or 0),
                "entries": list(bucket.get("entries") or []),
            }
    for week, hours in (deltas.get("add_allocations") or {}).items():
        bucket = weeks.setdefault(
            _monday(str(week)), {"established_hours": 0.0, "entries": []}
        )
        bucket["established_hours"] = round(
            bucket["established_hours"] + float(hours), 4
        )
    for week, hours in (deltas.get("remove_allocations") or {}).items():
        bucket = weeks.setdefault(
            _monday(str(week)), {"established_hours": 0.0, "entries": []}
        )
        bucket["established_hours"] = round(
            max(0.0, bucket["established_hours"] - float(hours)), 4
        )
    return {"weeks": weeks}


def recompute_arrangement(
    user_id: str,
    *,
    base: dict[str, Any],
    deltas: dict[str, Any] | None = None,
    toggles: dict[str, Any] | None = None,
    fold_seq: int | None = None,
    start_week: str | None = None,
    horizon_weeks: int = 104,
) -> dict[str, Any]:
    """Hypothetical recalculation over a diagnosis (brief §7).

    ``base`` is ``{"proposal_id": ...}`` (a retained diagnosis —
    pending, approved, or established; a hypothetical never needs
    the freeze's permission) or ``{"tasks": [...], "person_id":
    ..., "target_project_id": ...}`` for an ad-hoc set.

    ``deltas`` (all optional): ``effort`` / ``dependencies`` /
    ``priority`` map task ids (canonical, diagnosis-node, or
    scenario ids) to replacement values; ``capacity_hours_per_week``
    and ``capacity_overrides`` change availability;
    ``add_windows`` / ``remove_windows`` (exact-match on the keys
    given) change declared windows; ``add_allocations`` /
    ``remove_allocations`` map ISO week starts to hours of
    competing commitment.

    ``toggles``: ``include_provisional_layer`` (the §5 provisional
    projects' open work joins as scenario work — it never reserves,
    in either mode), ``firm_only`` (recorded non-firm demand is
    excluded from the passes, so the seat sees the arrangement
    against firm commitments alone; the exclusion is counted and
    labeled), ``target_advances`` (the kernel's named earliest-pass
    assumption, default True).

    The result is stamped with the fold_seq consumed, a scenario
    assumption-set id derived from the diagnosis's assumptions
    plus a fingerprint of the deltas/toggles, the kernel version,
    and the honesty labels. Nothing is persisted.
    """
    S._require_owner_id(user_id)
    deltas = copy.deepcopy(deltas) if deltas else {}
    toggles = dict(toggles) if toggles else {}

    if base.get("proposal_id"):
        proposal = TD._require_proposal(user_id, str(base["proposal_id"]))
        diagnosis = proposal["diagnosis"]
        base_ref: dict[str, Any] = {
            "kind": "diagnosis_proposal",
            "proposal_id": proposal["id"],
            "version": proposal["version"],
            "project_id": proposal["project_id"],
        }
    elif base.get("tasks") is not None:
        diagnosis = _adhoc_diagnosis(user_id, base)
        base_ref = {
            "kind": "adhoc_tasks",
            "project_id": diagnosis["project_id"],
        }
    else:
        raise ValueError(
            "base must name a diagnosis proposal or an ad-hoc task set"
        )

    world = TD._assemble_world(user_id, diagnosis, at_fold_seq=fold_seq)
    kwargs: dict[str, Any] = copy.deepcopy(world["kernel_kwargs"])
    person_id = world["person_id"]
    target_project_id = diagnosis["project_id"]

    target_advances = bool(toggles.get("target_advances", True))

    firm_only_info: dict[str, Any] = {"enabled": bool(toggles.get("firm_only"))}
    if firm_only_info["enabled"]:
        kept = [
            t
            for t in kwargs["tasks"]
            if t.get("timeframe_commitment") == "firm"
        ]
        firm_only_info["excluded_world_tasks"] = len(kwargs["tasks"]) - len(kept)
        kwargs["tasks"] = kept

    provisional_info: dict[str, Any] = {
        "included": bool(toggles.get("include_provisional_layer")),
        "project_ids": [],
        "task_count": 0,
    }
    if provisional_info["included"]:
        fold = T.derive_temporal_standing(user_id, at_fold_seq=world["fold_seq"])
        world_task_ids = {t["id"] for t in kwargs["tasks"]}
        layer, layer_projects = _provisional_layer(
            user_id,
            person_id,
            fold,
            world_task_ids=world_task_ids,
            target_project_id=target_project_id,
        )
        kwargs["scenario_tasks"] = list(kwargs.get("scenario_tasks") or []) + layer
        provisional_info["project_ids"] = layer_projects
        provisional_info["task_count"] = len(layer)

    applied: dict[str, Any] = {
        "effort": [],
        "dependencies": [],
        "priority": [],
        "capacity_changed": False,
        "windows_added": 0,
        "windows_removed": 0,
        "allocation_weeks_changed": [],
    }
    # Delta keys may name a diagnosis node or the canonical task
    # behind it — the seat layer holds both forms. Translate node
    # ids to the ids the assembled world actually carries (a
    # recorded task enters the world under its canonical id; a
    # proposed node under its own).
    aliases: dict[str, str] = {}
    for node in diagnosis.get("tasks", []):
        kernel_id = (
            str(node["ref_task_id"]) if node.get("ref_task_id") else node["id"]
        )
        aliases[node["id"]] = kernel_id
        aliases[kernel_id] = kernel_id
    pools = [kwargs["tasks"], list(kwargs.get("scenario_tasks") or [])]
    for section in ("effort", "dependencies", "priority"):
        for raw_id, value in (deltas.get(section) or {}).items():
            task_id = aliases.get(str(raw_id), str(raw_id))
            for pool in pools:
                for entry in pool:
                    if entry["id"] == task_id:
                        if section == "effort" and (
                            value is None or isinstance(value, (int, float))
                        ):
                            value = K.effort_from_hours(value)
                        entry[section] = value
                        applied[section].append(task_id)
    kwargs["scenario_tasks"] = pools[1]
    if deltas.get("capacity_hours_per_week") is not None:
        kwargs["capacity_hours_per_week"] = float(
            deltas["capacity_hours_per_week"]
        )
        applied["capacity_changed"] = True
    if deltas.get("capacity_overrides"):
        kwargs["capacity_overrides"] = dict(deltas["capacity_overrides"])
        applied["capacity_changed"] = True
    if deltas.get("add_windows"):
        kwargs["windows"] = list(kwargs.get("windows") or []) + list(
            deltas["add_windows"]
        )
        applied["windows_added"] = len(deltas["add_windows"])
    if deltas.get("remove_windows"):
        windows = list(kwargs.get("windows") or [])
        for match in deltas["remove_windows"]:
            before = len(windows)
            windows = [
                w
                for w in windows
                if not all(w.get(k) == v for k, v in match.items())
            ]
            applied["windows_removed"] += before - len(windows)
        kwargs["windows"] = windows
    if deltas.get("add_allocations") or deltas.get("remove_allocations"):
        kwargs["established_allocations"] = _apply_allocation_deltas(
            kwargs.get("established_allocations"), deltas
        )
        applied["allocation_weeks_changed"] = sorted(
            {_monday(str(w)) for w in (deltas.get("add_allocations") or {})}
            | {_monday(str(w)) for w in (deltas.get("remove_allocations") or {})}
        )

    fingerprint = hashlib.sha256(
        json.dumps(
            {"deltas": deltas, "toggles": toggles, "base": base_ref},
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:16]
    assumption_ids = [
        a["id"] for a in diagnosis.get("assumptions", [])
    ] + [f"recompute:{fingerprint}"]
    kwargs["assumption_set_id"] = T.assumption_set_id(assumption_ids)
    kwargs["fold_seq"] = world["fold_seq"]

    if start_week is None:
        today = date.fromisoformat(S._now()[:10])
        start_week = (today - timedelta(days=today.weekday())).isoformat()
    result = K.compute_arrangement(
        start_week=start_week,
        horizon_weeks=horizon_weeks,
        target_advances=target_advances,
        **kwargs,
    )
    return {
        "kind": "temporal_recompute",
        "base": base_ref,
        "fold_seq": world["fold_seq"],
        "assumption_set_id": kwargs["assumption_set_id"],
        "kernel_version": K.KERNEL_VERSION,
        "algorithm": K.ALGORITHM,
        "claim": K.CLAIM,
        "grain_disclaimer": K.GRAIN_DISCLAIMER,
        "target_advances": target_advances,
        "firm_only": firm_only_info,
        "provisional_layer": provisional_info,
        "deltas_applied": applied,
        "target": result.get("target"),
        "sustainable_status": (result.get("sustainable") or {}).get("status"),
        "displacement": result.get("displacement"),
        "arrangement": result,
    }
