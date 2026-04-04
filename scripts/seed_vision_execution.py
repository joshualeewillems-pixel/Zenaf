#!/usr/bin/env python3
"""
Seed the Vision Execution DB with sample data for development/demo.

Populates: 1 core profile, 6 ideas, 4 initiatives, 6 projects, 15 tasks, 3 people, 6 assets.
Capacity profiles are created for each person.

Run from repo root: python scripts/seed_vision_execution.py
Or: PYTHONPATH=. python scripts/seed_vision_execution.py
"""
import sys
from pathlib import Path

# Allow importing local_ai from repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from local_ai.vision_execution import storage, models as M


def main() -> None:
    # Ensure DB init/migrations run and default owner bootstrap is available.
    storage.get_connection()
    owner = storage.get_user_by_email("owner@local.atria")
    if not owner:
        raise RuntimeError(
            "Default local owner user is missing. Run API/storage init and verify ATRIA_BOOTSTRAP_PASSWORD setup."
        )
    owner_id = owner["id"]

    # --- 1 core profile ---
    core = storage.create_core_profile(M.CoreProfileCreate(
        name="Atria Core",
        core_definition="Align execution with vision; prioritize by strategic value and energy impact.",
        current_goals="Ship key initiatives on time; keep capacity visible; kill low-alignment work.",
        growth_focus_12_months="Product–market fit and sustainable delivery rhythm.",
        economic_engine="Value delivery and capacity utilization.",
        non_negotiables="Quality, transparency, no hero culture.",
        strategic_filter="Fits core definition and current goals.",
        current_constraints="Limited capacity; no new initiatives without capacity check.",
        capacity_limit="Track weekly hours; flag overcapacity.",
        kill_philosophy="Kill early if alignment drops or capacity is exceeded.",
        strength_positioning="Leverage strengths; avoid misalignment.",
    ), owner_id)
    print("Created 1 core profile:", core["id"])

    # --- 3 people (then capacity) ---
    people_data = [
        {"name": "Alex Chen", "role": "Product", "relationship_type": "Core", "contact_info": "alex@example.com", "strengths": "Prioritization", "needs": "Clear scope", "wants": "Shipped outcomes", "availability": "Full-time", "notes": ""},
        {"name": "Sam Rivera", "role": "Engineering", "relationship_type": "Core", "contact_info": "sam@example.com", "strengths": "Systems thinking", "needs": "Stable scope", "wants": "Quality first", "availability": "Full-time", "notes": ""},
        {"name": "Jordan Lee", "role": "Design", "relationship_type": "Core", "contact_info": "jordan@example.com", "strengths": "UX", "needs": "User access", "wants": "Coherent UX", "availability": "Part-time", "notes": ""},
    ]
    people = [storage.create_person(M.PersonCreate(**p)) for p in people_data]
    person_ids = [p["id"] for p in people]
    for i, p in enumerate(people):
        storage.upsert_capacity_profile(M.CapacityProfileUpsert(person_id=p["id"], weekly_capacity_hours=[40, 40, 20][i]))
    print("Created 3 people + capacity profiles:", person_ids)

    # --- 6 ideas ---
    ideas_data = [
        {"title": "Unified dashboard", "summary": "Single view for vision and execution.", "description": "Bring initiatives, projects, and capacity into one dashboard.", "status": "Contextualized", "tags": ["product", "dashboard"], "created_by": person_ids[0], "desired_outcome": "One place to see everything."},
        {"title": "Capacity alerts", "summary": "Notify when over capacity.", "description": "Alert when someone is over their weekly capacity.", "status": "Captured", "tags": ["capacity"], "created_by": person_ids[1], "desired_outcome": "No silent overcommit."},
        {"title": "Initiative evaluation", "summary": "AI-assisted initiative scoring.", "description": "Use AI to estimate cost, timeframe, alignment.", "status": "Evaluated", "tags": ["ai", "initiatives"], "created_by": person_ids[0], "desired_outcome": "Faster go/no-go."},
        {"title": "Asset registry", "summary": "Track shared assets and ownership.", "description": "Register tools, spaces, and link to ideas/initiatives.", "status": "Clarifying", "tags": ["assets"], "created_by": person_ids[2], "desired_outcome": "Clear ownership."},
        {"title": "Kill criteria automation", "summary": "Auto-flag initiatives that hit kill criteria.", "description": "Compare initiative state to kill criteria and surface risks.", "status": "Captured", "tags": ["governance"], "created_by": person_ids[1], "desired_outcome": "Early kill decisions."},
        {"title": "Retro integration", "summary": "Feed retros into strategy.", "description": "Link retrospectives to goals and non-negotiables.", "status": "Parked", "tags": ["retro"], "created_by": person_ids[0], "desired_outcome": "Learning loops."},
    ]
    ideas = [storage.create_idea(M.IdeaCreate(**d), owner_id) for d in ideas_data]
    idea_ids = [i["id"] for i in ideas]
    print("Created 6 ideas:", idea_ids)

    # --- 4 initiatives (link some to ideas and people) ---
    initiatives_data = [
        {"source_idea_id": idea_ids[0], "title": "Ship unified dashboard", "brief": "Deliver the single dashboard for vision/execution.", "status": "Approved", "owner_id": person_ids[0], "priority_rank_manual": 4, "evaluation_priority": 4, "strategic_value_manual": 5, "energy_impact_manual": 4, "estimated_cost_ai": "Medium", "estimated_timeframe_ai": "8 weeks", "next_step_ai": "Finalize scope with design.", "required_people": person_ids, "required_assets": [], "dependencies": "", "risks": "Scope creep.", "recommendation": "Proceed.", "counts_toward_capacity": 1, "manual_override": "", "kill_criteria": "If no launch by Q2.", "notes": ""},
        {"source_idea_id": idea_ids[2], "title": "AI initiative evaluation", "brief": "Single-pass AI evaluation for initiatives.", "status": "Active", "owner_id": person_ids[0], "priority_rank_manual": 5, "evaluation_priority": 5, "strategic_value_manual": 4, "energy_impact_manual": 3, "estimated_cost_ai": "Low", "estimated_timeframe_ai": "2 weeks", "next_step_ai": "Ship and iterate.", "required_people": [person_ids[1]], "required_assets": [], "dependencies": "", "risks": "", "recommendation": "Done.", "counts_toward_capacity": 1, "manual_override": "", "kill_criteria": "", "notes": ""},
        {"source_idea_id": idea_ids[1], "title": "Capacity alerts", "brief": "Overcapacity notifications.", "status": "Draft", "owner_id": person_ids[1], "priority_rank_manual": 3, "evaluation_priority": 3, "strategic_value_manual": 4, "energy_impact_manual": 5, "estimated_cost_ai": "", "estimated_timeframe_ai": "", "next_step_ai": "", "required_people": [], "required_assets": [], "dependencies": "", "risks": "", "recommendation": "", "counts_toward_capacity": 1, "manual_override": "", "kill_criteria": "", "notes": ""},
        {"source_idea_id": idea_ids[3], "title": "Asset registry", "brief": "Central asset list and links.", "status": "Draft", "owner_id": person_ids[2], "priority_rank_manual": 2, "evaluation_priority": 2, "strategic_value_manual": 3, "energy_impact_manual": 3, "estimated_cost_ai": "", "estimated_timeframe_ai": "", "next_step_ai": "", "required_people": [], "required_assets": [], "dependencies": "", "risks": "", "recommendation": "", "counts_toward_capacity": 1, "manual_override": "", "kill_criteria": "", "notes": ""},
    ]
    initiatives = [storage.create_initiative(M.InitiativeCreate(**d), owner_id) for d in initiatives_data]
    initiative_ids = [i["id"] for i in initiatives]
    print("Created 4 initiatives:", initiative_ids)

    # --- 6 projects (link to initiatives and people; 1 unanchored) ---
    projects_data = [
        {"initiative_id": initiative_ids[0], "title": "Dashboard backend", "brief": "APIs and data for dashboard.", "status": "Active", "owner_id": person_ids[1], "supporting_owner_ids": [person_ids[0]], "priority": "High", "start_date": "2025-02-01", "end_date": "2025-04-15", "estimated_weekly_hours": 15.0, "deliverables": "API; derived fields.", "complexity": "Medium", "current_focus": "Derived fields.", "next_step_ai": "Ship and monitor.", "notes": ""},
        {"initiative_id": initiative_ids[0], "title": "Dashboard frontend", "brief": "UI for vision/execution.", "status": "Ready", "owner_id": person_ids[2], "supporting_owner_ids": [], "priority": "High", "start_date": "2025-03-01", "end_date": "2025-05-01", "estimated_weekly_hours": 20.0, "deliverables": "Tabs; detail panels.", "complexity": "Medium", "current_focus": "Detail panels.", "next_step_ai": "Polish and ship.", "notes": ""},
        {"initiative_id": initiative_ids[1], "title": "Evaluate endpoint", "brief": "POST evaluate for initiatives.", "status": "Complete", "owner_id": person_ids[1], "supporting_owner_ids": [], "priority": "High", "start_date": "2025-01-15", "end_date": "2025-02-28", "estimated_weekly_hours": 8.0, "deliverables": "Single-pass AI eval.", "complexity": "Low", "current_focus": "Done.", "next_step_ai": "", "notes": ""},
        {"initiative_id": initiative_ids[1], "title": "Eval UI", "brief": "Apply/Discard proposal in UI.", "status": "Active", "owner_id": person_ids[0], "supporting_owner_ids": [person_ids[2]], "priority": "High", "start_date": "2025-02-01", "end_date": "2025-03-15", "estimated_weekly_hours": 5.0, "deliverables": "Button + proposal box.", "complexity": "Low", "current_focus": "UX polish.", "next_step_ai": "", "notes": ""},
        {"initiative_id": initiative_ids[2], "title": "Capacity alert logic", "brief": "Compute overcapacity and alert.", "status": "Draft", "owner_id": person_ids[1], "supporting_owner_ids": [], "priority": "Medium", "start_date": None, "end_date": None, "estimated_weekly_hours": 10.0, "deliverables": "Backend + notifications.", "complexity": "Medium", "current_focus": "Design.", "next_step_ai": "", "notes": ""},
        {"initiative_id": None, "title": "Unanchored project", "brief": "Not linked to any initiative.", "status": "Draft", "owner_id": person_ids[0], "supporting_owner_ids": [], "priority": "Low", "start_date": None, "end_date": None, "estimated_weekly_hours": None, "deliverables": "", "complexity": "", "current_focus": "", "next_step_ai": "", "notes": "Demo unanchoredFlag."},
    ]
    projects = [storage.create_project(M.ProjectCreate(**d), owner_id) for d in projects_data]
    project_ids = [p["id"] for p in projects]
    print("Created 6 projects:", project_ids)

    # --- 15 tasks (spread across projects, assignees) ---
    tasks_data = [
        {"project_id": project_ids[0], "parent_task_id": None, "title": "Design API contract", "description": "OpenAPI for dashboard.", "assignee_id": person_ids[1], "status": "Done", "priority": "High", "estimated_hours": 4, "due_date": "2025-02-10", "dependency_ids": [], "completion_criteria": "Reviewed.", "notes": ""},
        {"project_id": project_ids[0], "parent_task_id": None, "title": "Implement derived fields", "description": "Backend derived values.", "assignee_id": person_ids[1], "status": "In Progress", "priority": "High", "estimated_hours": 16, "due_date": "2025-03-15", "dependency_ids": [], "completion_criteria": "Tests pass.", "notes": ""},
        {"project_id": project_ids[0], "parent_task_id": None, "title": "Add list filters", "description": "Filter by status/owner.", "assignee_id": person_ids[1], "status": "Todo", "priority": "Medium", "estimated_hours": 8, "due_date": None, "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[1], "parent_task_id": None, "title": "Build tab layout", "description": "Tabs for entities.", "assignee_id": person_ids[2], "status": "Done", "priority": "High", "estimated_hours": 12, "due_date": "2025-03-01", "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[1], "parent_task_id": None, "title": "Initiative detail panel", "description": "Form + evaluate.", "assignee_id": person_ids[2], "status": "Done", "priority": "High", "estimated_hours": 10, "due_date": None, "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[1], "parent_task_id": None, "title": "Project detail panel", "description": "Edit project + tasks list.", "assignee_id": person_ids[2], "status": "In Progress", "priority": "High", "estimated_hours": 8, "due_date": "2025-04-01", "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[1], "parent_task_id": None, "title": "Task detail panel", "description": "Edit task.", "assignee_id": person_ids[0], "status": "Todo", "priority": "Medium", "estimated_hours": 4, "due_date": None, "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[2], "parent_task_id": None, "title": "Implement evaluate endpoint", "description": "POST evaluate.", "assignee_id": person_ids[1], "status": "Done", "priority": "High", "estimated_hours": 6, "due_date": "2025-02-20", "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[2], "parent_task_id": None, "title": "Wire to LLM", "description": "Single-pass prompt.", "assignee_id": person_ids[1], "status": "Done", "priority": "High", "estimated_hours": 8, "due_date": None, "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[3], "parent_task_id": None, "title": "Evaluate button", "description": "Call API from UI.", "assignee_id": person_ids[0], "status": "Done", "priority": "High", "estimated_hours": 2, "due_date": None, "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[3], "parent_task_id": None, "title": "Proposal box", "description": "Show proposal; Apply/Discard.", "assignee_id": person_ids[2], "status": "In Progress", "priority": "High", "estimated_hours": 4, "due_date": "2025-03-10", "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[4], "parent_task_id": None, "title": "Spec alert rules", "description": "When to alert.", "assignee_id": person_ids[1], "status": "Todo", "priority": "Medium", "estimated_hours": 4, "due_date": None, "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[4], "parent_task_id": None, "title": "Implement overcapacity flag", "description": "Use derived overcapacity.", "assignee_id": person_ids[1], "status": "Todo", "priority": "Medium", "estimated_hours": 6, "due_date": None, "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[5], "parent_task_id": None, "title": "Decide initiative", "description": "Link or kill.", "assignee_id": person_ids[0], "status": "Todo", "priority": "Low", "estimated_hours": 1, "due_date": None, "dependency_ids": [], "completion_criteria": "", "notes": ""},
        {"project_id": project_ids[5], "parent_task_id": None, "title": "Document purpose", "description": "Why this project exists.", "assignee_id": person_ids[0], "status": "Todo", "priority": "Low", "estimated_hours": 2, "due_date": None, "dependency_ids": [], "completion_criteria": "", "notes": ""},
    ]
    for d in tasks_data:
        storage.create_task(M.TaskCreate(**d), owner_id)
    print("Created 15 tasks")

    # --- 6 assets ---
    assets_data = [
        {"name": "Design system", "asset_type": "Tool", "owner_id": person_ids[2], "status": "Active", "availability": "Shared", "cost": "Internal", "time_availability": "Always", "linked_idea_ids": [idea_ids[0]], "linked_initiative_ids": [initiative_ids[0]], "linked_project_ids": [project_ids[1]], "notes": ""},
        {"name": "API runtime", "asset_type": "Infrastructure", "owner_id": person_ids[1], "status": "Active", "availability": "Shared", "cost": "Cloud", "time_availability": "24/7", "linked_idea_ids": [], "linked_initiative_ids": [initiative_ids[0]], "linked_project_ids": [project_ids[0]], "notes": ""},
        {"name": "LLM gateway", "asset_type": "Service", "owner_id": person_ids[1], "status": "Active", "availability": "Shared", "cost": "API", "time_availability": "Always", "linked_idea_ids": [idea_ids[2]], "linked_initiative_ids": [initiative_ids[1]], "linked_project_ids": [project_ids[2]], "notes": ""},
        {"name": "Meeting room A", "asset_type": "Space", "owner_id": None, "status": "Available", "availability": "Bookable", "cost": "N/A", "time_availability": "Business hours", "linked_idea_ids": [], "linked_initiative_ids": [], "linked_project_ids": [], "notes": ""},
        {"name": "Figma workspace", "asset_type": "Tool", "owner_id": person_ids[2], "status": "Active", "availability": "Team", "cost": "Subscription", "time_availability": "Always", "linked_idea_ids": [idea_ids[3]], "linked_initiative_ids": [initiative_ids[3]], "linked_project_ids": [], "notes": ""},
        {"name": "CI pipeline", "asset_type": "Infrastructure", "owner_id": person_ids[1], "status": "Active", "availability": "Shared", "cost": "Internal", "time_availability": "24/7", "linked_idea_ids": [], "linked_initiative_ids": [], "linked_project_ids": [], "notes": ""},
    ]
    for d in assets_data:
        storage.create_asset(M.AssetCreate(**d))
    print("Created 6 assets")

    print("Done. Vision Execution DB seeded.")


if __name__ == "__main__":
    main()
