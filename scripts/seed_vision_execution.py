#!/usr/bin/env python3
"""
Seed the Vision Execution DB with sample data for development/demo.

Populates: 1 core profile, 6 ideas, 4 initiatives, 6 projects, 15 tasks, 3 people, 6 assets.
Capacity profiles are created for each person.

Run from repo root: python scripts/seed_vision_execution.py
Or: PYTHONPATH=. python scripts/seed_vision_execution.py
"""
import argparse
import sys
from pathlib import Path

# Allow importing local_ai from repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from local_ai.vision_execution import storage, models as M


def main() -> None:
    ap = argparse.ArgumentParser(description="Demo Vision Execution seed (people, assets, graph) for one user.")
    ap.add_argument(
        "--user-email",
        default="owner@local.zenaf",
        help="Account to seed (default: owner@local.zenaf). Examples: owner@local.zenaf",
    )
    args = ap.parse_args()
    email = (args.user_email or "").strip()
    if not email:
        raise SystemExit("--user-email cannot be empty")

    # Ensure DB init/migrations run and default owner bootstrap is available.
    storage.get_connection()
    owner = storage.get_user_by_email(email)
    if not owner:
        raise RuntimeError(
            f"User {email!r} is missing. Run API/storage init and verify bootstrap passwords."
        )
    owner_id = owner["id"]
    print(f"Demo seed for {email} (id={owner_id})…")

    # --- 1 core profile ---
    core = storage.create_core_profile(M.CoreProfileCreate(
        name="Zenaf — sample core profile",
        core_definition=(
            "Zenaf connects email intake, advisor-style council perspectives, and Vision & Execution so thinking "
            "turns into owned work: initiatives, projects, tasks, people, and assets in one place."
        ),
        current_goals=(
            "Keep the execution graph trustworthy (honest capacity, clear owners), ship council and intake integrations "
            "without silent drift, and make AI suggestions easy to accept or discard."
        ),
        growth_focus_12_months="Harden local-first workflows and the operational chain from inbox poll to council context.",
        economic_engine="Sustainable solo or small-team delivery with transparent load and kill criteria.",
        non_negotiables="No hidden state: sync status, advisor seats, and execution data should match reality.",
        strategic_filter="Fits the local assistant vision and reduces coordination fog without adding busywork.",
        current_constraints="Limited people-hours; avoid parallel initiatives without an owner and measurable outcome.",
        capacity_limit="Track estimated weekly hours per person; surface overcapacity before commitments harden.",
        kill_philosophy="Stop or park work when alignment, capacity, or honesty breaks — document why.",
        strength_positioning="Deep integration between intake, council, and execution rather than another isolated task list.",
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
        {"title": "One workspace from idea to shipped task", "summary": "Ideas, initiatives, projects, tasks, people, and assets visible together.", "description": "Vision & Execution is the shell: capture thinking, decide, break down work, and see load — without hopping tools.", "status": "Contextualized", "tags": ["product", "vision-execution"], "created_by": person_ids[0], "desired_outcome": "Anyone can answer “what are we doing and who owns it?” inside Zenaf."},
        {"title": "Show real capacity before we commit", "summary": "Make overload visible from estimated weekly hours versus capacity.", "description": "Derived totals from active projects should warn before we stack another initiative.", "status": "Captured", "tags": ["capacity"], "created_by": person_ids[1], "desired_outcome": "No silent overcommit; trade-offs are explicit."},
        {"title": "AI initiative review you can trust", "summary": "Model proposes cost, timeframe, alignment — humans apply or discard.", "description": "Evaluation flow should feel like a structured brief, not a black-box score.", "status": "Evaluated", "tags": ["ai", "initiatives"], "created_by": person_ids[0], "desired_outcome": "Faster go/no-go with clear reasoning attached."},
        {"title": "Assets that explain how work depends on them", "summary": "Register tools and services; link to initiatives and projects.", "description": "Distinguish casual references from true blockers; show who needs access.", "status": "Clarifying", "tags": ["assets"], "created_by": person_ids[2], "desired_outcome": "No mystery tools gating delivery."},
        {"title": "Surface kill criteria early", "summary": "Initiatives carry explicit tripwires; risks stay visible.", "description": "Compare status and risks to kill criteria during reviews — manual first, automation later.", "status": "Captured", "tags": ["governance"], "created_by": person_ids[1], "desired_outcome": "We stop drifting projects before they burn surprise time."},
        {"title": "Feed retrospectives back into strategy", "summary": "Capture learnings alongside core profile and goals.", "description": "Parked: tie retrospective notes to non-negotiables and current goals.", "status": "Parked", "tags": ["retro"], "created_by": person_ids[0], "desired_outcome": "Less repeated failure; more deliberate adjustment."},
    ]
    ideas = [storage.create_idea(M.IdeaCreate(**d), owner_id) for d in ideas_data]
    idea_ids = [i["id"] for i in ideas]
    print("Created 6 ideas:", idea_ids)

    # --- 4 initiatives (link some to ideas and people) ---
    initiatives_data = [
        {"source_idea_id": idea_ids[0], "title": "Deliver the Vision & Execution daily experience", "brief": "Polish tabs, detail panels, and navigation so ideas through tasks feel like one continuous workspace.", "status": "Approved", "owner_id": person_ids[0], "priority_rank_manual": 4, "evaluation_priority": 4, "strategic_value_manual": 5, "energy_impact_manual": 4, "estimated_cost_ai": "Medium", "estimated_timeframe_ai": "About two months", "next_step_ai": "Lock UX scope with design and engineering.", "required_people": person_ids, "required_assets": [], "dependencies": "", "risks": "Scope creep if we chase every nice-to-have panel.", "recommendation": "Proceed with a tight MVP cut line.", "counts_toward_capacity": 1, "manual_override": "", "kill_criteria": "Pause if we cannot show a coherent end-to-end create-to-task flow by the agreed milestone.", "notes": ""},
        {"source_idea_id": idea_ids[2], "title": "Trustworthy AI evaluation for initiatives", "brief": "Single-pass evaluation with apply/discard so humans stay in control.", "status": "Active", "owner_id": person_ids[0], "priority_rank_manual": 5, "evaluation_priority": 5, "strategic_value_manual": 4, "energy_impact_manual": 3, "estimated_cost_ai": "Low", "estimated_timeframe_ai": "A couple of weeks", "next_step_ai": "Iterate on prompt clarity after first user tests.", "required_people": [person_ids[1]], "required_assets": [], "dependencies": "", "risks": "", "recommendation": "Keep shipping small improvements; monitor for hallucinated estimates.", "counts_toward_capacity": 1, "manual_override": "", "kill_criteria": "", "notes": ""},
        {"source_idea_id": idea_ids[1], "title": "Honest capacity signaling", "brief": "Turn derived weekly load into something people notice before they commit.", "status": "Draft", "owner_id": person_ids[1], "priority_rank_manual": 3, "evaluation_priority": 3, "strategic_value_manual": 4, "energy_impact_manual": 5, "estimated_cost_ai": "", "estimated_timeframe_ai": "", "next_step_ai": "", "required_people": [], "required_assets": [], "dependencies": "", "risks": "", "recommendation": "", "counts_toward_capacity": 1, "manual_override": "", "kill_criteria": "", "notes": ""},
        {"source_idea_id": idea_ids[3], "title": "Asset registry people actually use", "brief": "Central list of tools and services with clear ownership and links to active work.", "status": "Draft", "owner_id": person_ids[2], "priority_rank_manual": 2, "evaluation_priority": 2, "strategic_value_manual": 3, "energy_impact_manual": 3, "estimated_cost_ai": "", "estimated_timeframe_ai": "", "next_step_ai": "", "required_people": [], "required_assets": [], "dependencies": "", "risks": "", "recommendation": "", "counts_toward_capacity": 1, "manual_override": "", "kill_criteria": "", "notes": ""},
    ]
    initiatives = [storage.create_initiative(M.InitiativeCreate(**d), owner_id) for d in initiatives_data]
    initiative_ids = [i["id"] for i in initiatives]
    print("Created 4 initiatives:", initiative_ids)

    # --- 6 projects (link to initiatives and people; 1 unanchored) ---
    projects_data = [
        {"initiative_id": initiative_ids[0], "title": "Vision & Execution API and derived fields", "brief": "Stable JSON APIs plus derived capacity and readiness fields the UI relies on.", "status": "Active", "owner_id": person_ids[1], "supporting_owner_ids": [person_ids[0]], "priority": "High", "start_date": "2026-02-01", "end_date": "2026-04-15", "estimated_weekly_hours": 15.0, "deliverables": "Endpoints and derived summaries documented for the frontend.", "complexity": "Medium", "current_focus": "Derived load and radar fields.", "next_step_ai": "Monitor for regressions after each release.", "notes": ""},
        {"initiative_id": initiative_ids[0], "title": "Vision & Execution UI shell", "brief": "Tabs, lists, and detail panels for ideas through tasks.", "status": "Ready", "owner_id": person_ids[2], "supporting_owner_ids": [], "priority": "High", "start_date": "2026-03-01", "end_date": "2026-05-01", "estimated_weekly_hours": 20.0, "deliverables": "Cohesive navigation and forms for every entity type.", "complexity": "Medium", "current_focus": "Detail panel polish and empty states.", "next_step_ai": "Ship incremental UX fixes weekly.", "notes": ""},
        {"initiative_id": initiative_ids[1], "title": "Initiative evaluation service", "brief": "Server endpoint that returns structured evaluation prose and scores.", "status": "Complete", "owner_id": person_ids[1], "supporting_owner_ids": [], "priority": "High", "start_date": "2026-01-15", "end_date": "2026-02-28", "estimated_weekly_hours": 8.0, "deliverables": "Single-pass evaluation contract tests green.", "complexity": "Low", "current_focus": "Maintenance only.", "next_step_ai": "", "notes": ""},
        {"initiative_id": initiative_ids[1], "title": "Evaluation apply/discard UX", "brief": "Buttons and copy so users trust applying AI suggestions to initiatives.", "status": "Active", "owner_id": person_ids[0], "supporting_owner_ids": [person_ids[2]], "priority": "High", "start_date": "2026-02-01", "end_date": "2026-03-15", "estimated_weekly_hours": 5.0, "deliverables": "Clear proposal panel with undo-friendly messaging.", "complexity": "Low", "current_focus": "Wording and guardrails.", "next_step_ai": "", "notes": ""},
        {"initiative_id": initiative_ids[2], "title": "Overcapacity surfacing", "brief": "Compute when people exceed weekly capacity and show it in the team view.", "status": "Draft", "owner_id": person_ids[1], "supporting_owner_ids": [], "priority": "Medium", "start_date": None, "end_date": None, "estimated_weekly_hours": 10.0, "deliverables": "Visible warning state backed by derived totals.", "complexity": "Medium", "current_focus": "Design how loud the signal should be.", "next_step_ai": "", "notes": ""},
        {"initiative_id": None, "title": "Sample project without an initiative", "brief": "Demonstrates a project that is not anchored to a parent initiative — useful for radar testing.", "status": "Draft", "owner_id": person_ids[0], "supporting_owner_ids": [], "priority": "Low", "start_date": None, "end_date": None, "estimated_weekly_hours": None, "deliverables": "", "complexity": "", "current_focus": "", "next_step_ai": "", "notes": "Demo data for unanchored radar flag."},
    ]
    projects = [storage.create_project(M.ProjectCreate(**d), owner_id) for d in projects_data]
    project_ids = [p["id"] for p in projects]
    print("Created 6 projects:", project_ids)

    # --- 15 tasks (spread across projects, assignees) ---
    tasks_data = [
        {"project_id": project_ids[0], "parent_task_id": None, "title": "Document the Vision & Execution API shapes", "description": "Capture request/response examples for ideas, initiatives, projects, and tasks.", "assignee_id": person_ids[1], "status": "Done", "priority": "High", "estimated_hours": 4, "due_date": "2026-02-10", "dependency_ids": [], "completion_criteria": "Another developer can integrate without reading every route by hand.", "notes": ""},
        {"project_id": project_ids[0], "parent_task_id": None, "title": "Implement derived readiness and load fields", "description": "Backend summaries for radar and capacity views.", "assignee_id": person_ids[1], "status": "In Progress", "priority": "High", "estimated_hours": 16, "due_date": "2026-03-15", "dependency_ids": [], "completion_criteria": "Automated tests cover happy path and empty graphs.", "notes": ""},
        {"project_id": project_ids[0], "parent_task_id": None, "title": "Add list filters for owners and status", "description": "Let people slice long lists without leaving the shell.", "assignee_id": person_ids[1], "status": "Todo", "priority": "Medium", "estimated_hours": 8, "due_date": None, "dependency_ids": [], "completion_criteria": "Filters apply client- or server-side consistently.", "notes": ""},
        {"project_id": project_ids[1], "parent_task_id": None, "title": "Build primary tab layout", "description": "Ideas, initiatives, projects, tasks, people, assets tabs wired to routes.", "assignee_id": person_ids[2], "status": "Done", "priority": "High", "estimated_hours": 12, "due_date": "2026-03-01", "dependency_ids": [], "completion_criteria": "Navigation state survives refresh where expected.", "notes": ""},
        {"project_id": project_ids[1], "parent_task_id": None, "title": "Initiative detail experience", "description": "Form fields, evaluation entry point, execution steps.", "assignee_id": person_ids[2], "status": "Done", "priority": "High", "estimated_hours": 10, "due_date": None, "dependency_ids": [], "completion_criteria": "Create, edit, and evaluate without console errors.", "notes": ""},
        {"project_id": project_ids[1], "parent_task_id": None, "title": "Project detail experience", "description": "Edit project metadata and embedded task list.", "assignee_id": person_ids[2], "status": "In Progress", "priority": "High", "estimated_hours": 8, "due_date": "2026-04-01", "dependency_ids": [], "completion_criteria": "Tasks can be added, completed, and reordered logically.", "notes": ""},
        {"project_id": project_ids[1], "parent_task_id": None, "title": "Task detail experience", "description": "Single task editor with dependencies and completion criteria.", "assignee_id": person_ids[0], "status": "Todo", "priority": "Medium", "estimated_hours": 4, "due_date": None, "dependency_ids": [], "completion_criteria": "Matches initiative/project polish level.", "notes": ""},
        {"project_id": project_ids[2], "parent_task_id": None, "title": "Ship initiative evaluation endpoint", "description": "Server route returning structured evaluation payload.", "assignee_id": person_ids[1], "status": "Done", "priority": "High", "estimated_hours": 6, "due_date": "2026-02-20", "dependency_ids": [], "completion_criteria": "Contract tests and manual smoke pass.", "notes": ""},
        {"project_id": project_ids[2], "parent_task_id": None, "title": "Connect evaluation to the language model stack", "description": "Single-pass prompt with guardrails and logging.", "assignee_id": person_ids[1], "status": "Done", "priority": "High", "estimated_hours": 8, "due_date": None, "dependency_ids": [], "completion_criteria": "Failures surface readable errors to the UI.", "notes": ""},
        {"project_id": project_ids[3], "parent_task_id": None, "title": "Evaluation trigger in the UI", "description": "Button, loading state, and error handling.", "assignee_id": person_ids[0], "status": "Done", "priority": "High", "estimated_hours": 2, "due_date": None, "dependency_ids": [], "completion_criteria": "Users know when a run starts and finishes.", "notes": ""},
        {"project_id": project_ids[3], "parent_task_id": None, "title": "Proposal presentation and apply/discard", "description": "Human-readable proposal with explicit actions.", "assignee_id": person_ids[2], "status": "In Progress", "priority": "High", "estimated_hours": 4, "due_date": "2026-03-10", "dependency_ids": [], "completion_criteria": "Apply writes only what the user confirmed.", "notes": ""},
        {"project_id": project_ids[4], "parent_task_id": None, "title": "Define when overcapacity warnings appear", "description": "Product rules for yellow versus red states.", "assignee_id": person_ids[1], "status": "Todo", "priority": "Medium", "estimated_hours": 4, "due_date": None, "dependency_ids": [], "completion_criteria": "Written spec reviewed by design and product.", "notes": ""},
        {"project_id": project_ids[4], "parent_task_id": None, "title": "Implement overcapacity highlighting", "description": "Use derived totals already exposed by the API.", "assignee_id": person_ids[1], "status": "Todo", "priority": "Medium", "estimated_hours": 6, "due_date": None, "dependency_ids": [], "completion_criteria": "Matches the agreed warning thresholds.", "notes": ""},
        {"project_id": project_ids[5], "parent_task_id": None, "title": "Decide whether to anchor this demo project", "description": "Link to a real initiative or archive the sample.", "assignee_id": person_ids[0], "status": "Todo", "priority": "Low", "estimated_hours": 1, "due_date": None, "dependency_ids": [], "completion_criteria": "Initiative field no longer empty or intentionally documented as demo.", "notes": ""},
        {"project_id": project_ids[5], "parent_task_id": None, "title": "Write a one-paragraph purpose statement", "description": "Explain why this unanchored project exists for testers.", "assignee_id": person_ids[0], "status": "Todo", "priority": "Low", "estimated_hours": 2, "due_date": None, "dependency_ids": [], "completion_criteria": "Brief field tells a newcomer what to expect.", "notes": ""},
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
