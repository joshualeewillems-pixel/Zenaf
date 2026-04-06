#!/usr/bin/env python3
"""
Replace Vision Execution demo seed with an execution graph derived from in-repo
planning/docs (not generic product fiction).

- Clears ideas / initiatives / projects / tasks for the default local owner.
- Clears all persons, capacity_profiles, assets (demo-era global rows).
- Keeps one core profile for owner@local.atria (oldest by created_at); deletes extras.
- Inserts ideas, initiatives, projects, and tasks with description citations to source docs.

Run from repo root:
  python scripts/seed_vision_execution_from_repo_docs.py

Requires default owner user (bootstrap). See storage._DEFAULT_OWNER_EMAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from local_ai.vision_execution import storage, models as M

# Tag for ideas that still need an architecture or product decision (not dev-ready).
LC = "architecture-open"


def _clear_execution_graph(owner_id: str) -> None:
    for t in list(storage.list_tasks(owner_id)):
        storage.delete_task(t["id"], owner_id)
    for p in list(storage.list_projects(owner_id)):
        storage.delete_project(p["id"], owner_id)
    conn = storage.get_connection()
    inits = list(storage.list_initiatives(owner_id))
    for i in inits:
        conn.execute("DELETE FROM initiative_seats WHERE initiative_id = ?", (i["id"],))
    conn.commit()
    for i in inits:
        storage.delete_initiative(i["id"], owner_id)
    for idea in list(storage.list_ideas(owner_id)):
        storage.delete_idea(idea["id"], owner_id)


def _clear_demo_globals() -> None:
    """Remove all persons/assets (global tables) after demo seed removal."""
    for a in storage.list_assets():
        storage.delete_asset(a["id"])
    for p in storage.list_persons():
        try:
            storage.delete_person(p["id"])
        except Exception:
            conn = storage.get_connection()
            conn.execute("DELETE FROM capacity_profiles WHERE person_id = ?", (p["id"],))
            conn.execute("DELETE FROM persons WHERE id = ?", (p["id"],))
            conn.commit()


def _dedupe_core_profiles(owner_id: str) -> dict:
    profiles = storage.list_core_profiles(owner_id)
    if not profiles:
        return storage.create_core_profile(
            M.CoreProfileCreate(
                name="Atria — local build",
                core_definition=(
                    "Atria is a local-first assistant: email intake, a council of advisor perspectives, "
                    "and Vision & Execution so plans stay tied to real work (people, assets, tasks)."
                ),
                current_goals=(
                    "Finish the honest operational chain: email poll → mirror state → what Vision & Execution "
                    "and the council see. Tighten council briefs (order of context, seats/roles, written "
                    "truth rules). Make assets and capacity legible in the UI."
                ),
                raw_notes="Seeded by scripts/seed_vision_execution_from_repo_docs.py (re-run to refresh sample rows).",
            ),
            owner_id,
        )
    profiles.sort(key=lambda x: x.get("created_at") or "")
    keep = profiles[0]
    conn = storage.get_connection()
    for p in profiles[1:]:
        conn.execute("DELETE FROM core_profiles WHERE id = ? AND user_id = ?", (p["id"], owner_id))
    conn.commit()
    return keep


def _idea(
    title: str,
    summary: str,
    description: str,
    *,
    desired_outcome: str = "",
    status: str = "Captured",
    tags: list[str] | None = None,
    low_confidence: bool = False,
) -> M.IdeaCreate:
    t = list(tags or [])
    if low_confidence:
        t.append(LC)
    return M.IdeaCreate(
        title=title,
        summary=summary,
        description=description,
        status=status,
        tags=t,
        created_by="",
        desired_outcome=desired_outcome,
    )


def main() -> None:
    storage.get_connection()
    owner = storage.get_user_by_email("owner@local.atria")
    if not owner:
        raise SystemExit("owner@local.atria not found — run API once to bootstrap users.")
    owner_id = owner["id"]

    print("Clearing user-scoped execution graph + global demo persons/assets…")
    _clear_execution_graph(owner_id)
    _clear_demo_globals()
    profile = _dedupe_core_profiles(owner_id)
    print("Kept core profile:", profile.get("id"), profile.get("name"))

    # --- Ideas (doc-sourced; architecture-open tag = needs a product/architecture decision) ---
    ideas_spec = [
        _idea(
            "Council seats should live on the server when you are signed in",
            (
                "Older flows kept advisor seats only in the browser. Today, signed-in users can load and save "
                "council workspace data on the server so the same seats come back after refresh or on another device."
            ),
            (
                "Status: largely in place — API and storage exist; the app should prefer server data over "
                "browser-only copies. Detail: docs/01_TRUTH/TRUTH_CONVERGENCE.md."
            ),
            desired_outcome="You always see the same advisor lineup for your account, backed by the server.",
            status="Contextualized",
        ),
        _idea(
            "After a successful email poll, the inbox mirror should record that sync honestly",
            (
                "When the app finishes polling email, downstream screens should see up-to-date sync metadata "
                "(last run, cursor position) instead of looking stale."
            ),
            (
                "Status: started on the API side; the poll success path does not yet write that state everywhere "
                "we document. Detail: docs/01_TRUTH/ACTIVE_VS_PLANNED.md, docs/OPEN_QUESTIONS.md."
            ),
            desired_outcome="Anyone reading Vision & Execution or diagnostics trusts that “last synced” matches reality.",
            status="Contextualized",
        ),
        _idea(
            "Load deferred or sensitive inbox content only through a deliberate permission step",
            (
                "Some messages stay queued until a policy check says it is safe to fetch full body text. "
                "The low-level helper to fetch with policy exists; a user-facing flow still needs design."
            ),
            (
                "Status: backend building block exists; no dedicated route or UI yet. "
                "Detail: docs/01_TRUTH/ACTIVE_VS_PLANNED.md, docs/OPEN_QUESTIONS.md."
            ),
            desired_outcome="Tiered inbox handling stays safe and explainable, not a hidden bypass.",
            status="Clarifying",
        ),
        _idea(
            "Council brief: put the human question before the operator’s priority list",
            (
                "The packet the council sees should lead with the task framing (context + question), "
                "then tool summaries and priorities — so advice stays grounded in what you actually asked."
            ),
            (
                "Status: planned change in the council packet builder. "
                "Detail: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md (step 1)."
            ),
            desired_outcome="Council answers read like responses to your question, not a generic status dump.",
            status="Contextualized",
        ),
        _idea(
            "Advisor role names in the UI should match the real seat model (including risk)",
            (
                "Labels like “Strategist” or “Skeptic” should match the documented seat taxonomy, "
                "and risk should appear as a first-class seat where we say it should."
            ),
            (
                "Status: planned UI and config pass. "
                "Detail: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md (step 2)."
            ),
            desired_outcome="What you see in the product matches the architecture docs without mental translation.",
            status="Contextualized",
        ),
        _idea(
            "Write down the agreed order of truth for the council",
            (
                "We should have a short, explicit description of which sources the council considers first "
                "and how packet sections relate — so future changes do not silently drift behavior."
            ),
            (
                "Status: documentation pass (and optional inline references in code comments). "
                "Detail: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md (step 3), "
                "docs/ATRIA_PROMPT_AND_TRUTH_ARCHITECTURE.md."
            ),
            desired_outcome="New contributors can answer “what does the council read first?” from docs alone.",
            status="Contextualized",
        ),
        _idea(
            "One permission style for intake, council, and future modules",
            (
                "Today the mirror path uses a structured policy layer; other modules may still reach for data "
                "directly. Long term, similar checks should apply anywhere we touch deferred or sensitive content."
            ),
            (
                "Status: concept and partial use — needs a deliberate decision on rollout. "
                "Detail: docs/01_TRUTH/ACTIVE_VS_PLANNED.md, docs/ATRIA_ARCHITECTURE.md."
            ),
            desired_outcome="No feature accidentally skips the same safety bar we use elsewhere.",
            status="Captured",
            low_confidence=True,
        ),
        _idea(
            "Assets in Vision & Execution should read like real-world tools, not database rows",
            (
                "People should see whether an asset is merely related to work or actually required to proceed, "
                "with readable titles and a clear “who uses this?” picture."
            ),
            (
                "Status: documented direction; UI still catching up. Detail: docs/MATERIAL_ENTITY_NODE_DIRECTION.md."
            ),
            desired_outcome="You open an asset and immediately understand how it connects to active initiatives and projects.",
            status="Contextualized",
        ),
        _idea(
            "Pick one long-term pattern for calling language models",
            (
                "Some code paths use a shared adapter or registry; others call a default provider directly. "
                "We still need to decide the single supported pattern for new work."
            ),
            (
                "Status: open design choice. Detail: docs/01_TRUTH/ACTIVE_VS_PLANNED.md, docs/OPEN_QUESTIONS.md."
            ),
            desired_outcome="Every new LLM feature plugs into one obvious, testable entry point.",
            status="Captured",
            low_confidence=True,
        ),
        _idea(
            "Configurable locations for inbox mirror data and the Vision & Execution database",
            (
                "Installs should not assume a fixed folder layout on disk; operators may want explicit paths "
                "for backup, portability, or multiple environments."
            ),
            (
                "Status: open product/config question. Detail: docs/OPEN_QUESTIONS.md."
            ),
            desired_outcome="A normal install can point storage at sensible paths without editing code.",
            status="Captured",
            low_confidence=True,
        ),
        _idea(
            "If any council seat data still lives only in the browser, plan its retirement",
            (
                "This idea is the safety net for stragglers: anything not yet on the server should be listed "
                "and migrated so “signed in” always means “server is canonical.”"
            ),
            (
                "Status: mostly superseded by server workspace work; keep until we confirm no local-only paths remain. "
                "Detail: docs/OPEN_QUESTIONS.md."
            ),
            desired_outcome="Zero silent divergence between browser cache and server records.",
            status="Captured",
            low_confidence=True,
        ),
        _idea(
            "Carry structured judgment beyond the email mirror",
            (
                "Judgment flows today focus on intake. We have not fully specified how the same rigor applies "
                "to Vision & Execution entities or council-facing summaries."
            ),
            (
                "Status: conceptual / unclear wiring. Detail: docs/OPEN_QUESTIONS.md."
            ),
            desired_outcome="Important decisions leave the same kind of audit trail everywhere, not only in intake.",
            status="Captured",
            low_confidence=True,
        ),
    ]

    created_ideas = [storage.create_idea(spec, owner_id) for spec in ideas_spec]
    ids = {f"i{i+1}": created_ideas[i]["id"] for i in range(len(created_ideas))}

    def ini(
        title: str,
        brief: str,
        *,
        status: str = "Active",
        source_key: str | None = None,
    ) -> str:
        sid = ids[source_key] if source_key else None
        row = storage.create_initiative(
            M.InitiativeCreate(
                source_idea_id=sid,
                title=title,
                brief=brief,
                status=status,
                owner_id=None,
                next_step_ai="",
                notes="Seeded from in-repo planning docs; edit freely in Vision & Execution.",
            ),
            owner_id,
        )
        return row["id"]

    in1 = ini(
        "Email intake: honest sync state, deferred content, and shared rules",
        (
            "Make polling email update the mirror’s sync story, decide how deferred message bodies surface, "
            "and keep permission checks consistent with the rest of the product. Pulls together the email sync, "
            "deferred content, and shared-rules themes from the idea list."
        ),
        status="Approved",
        source_key="i2",
    )
    in2 = ini(
        "Council experience: brief order, seat names, and written truth rules",
        (
            "Tighten what the council sees first, align on-screen advisor roles with the documented model "
            "(including risk), and capture the agreed reading order in docs."
        ),
        status="Active",
        source_key="i4",
    )
    in3 = ini(
        "Architecture pilots: permissions everywhere and one LLM entry style",
        (
            "Exploratory initiative: roll policy-style access beyond the mirror where it makes sense, "
            "and converge on a single pattern for language-model calls. Expect decisions before large builds."
        ),
        status="Draft",
        source_key="i7",
    )
    in4 = ini(
        "Execution reality for assets and materials",
        (
            "Vision & Execution should show how assets relate to work (linked vs required), human-readable names, "
            "and reverse lookups from initiatives and projects — without a database migration."
        ),
        status="Active",
        source_key="i8",
    )

    projects_raw: list[M.ProjectCreate] = [
        M.ProjectCreate(
            initiative_id=in1,
            title="Verify council workspace saves on the server",
            brief=(
                "Sign in, open council seat settings, and confirm reads/writes hit the Vision & Execution API "
                "so the same advisors appear after refresh or on another session — not only in browser storage."
            ),
            status="Active",
            owner_id=None,
            priority="High",
            deliverables="Short test note: login → load seats → edit → confirm saved row for the account.",
            current_focus="Vision & Execution API route and main app shell",
            notes="Background: docs/01_TRUTH/TRUTH_CONVERGENCE.md",
        ),
        M.ProjectCreate(
            initiative_id=in1,
            title="When email polling succeeds, persist mirror sync metadata",
            brief=(
                "Find the code path that finishes a successful inbox poll and write durable sync state "
                "(timestamps, cursor) so dashboards and diagnostics do not lie about freshness."
            ),
            status="Active",
            owner_id=None,
            priority="High",
            deliverables="After a poll, stored state matches what the user just saw complete successfully.",
            current_focus="Email intake polling flow",
            notes="Background: docs/OPEN_QUESTIONS.md, docs/01_TRUTH/ACTIVE_VS_PLANNED.md",
        ),
        M.ProjectCreate(
            initiative_id=in1,
            title="Expose a minimal API for deferred message bodies (policy-checked)",
            brief=(
                "The low-level helper to fetch content with policy already exists. Add a small authenticated "
                "HTTP surface and document who may call it — enough for one pilot consumer later."
            ),
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="One route plus plain-language notes on access levels and failure modes.",
            current_focus="API layer for intake",
            notes="Background: docs/01_TRUTH/ACTIVE_VS_PLANNED.md",
        ),
        M.ProjectCreate(
            initiative_id=in2,
            title="Reorder the council decision brief for clarity",
            brief=(
                "Adjust the automatic council packet so it presents context and your question before tool chatter "
                "and priority lists, matching the cleanup proposal."
            ),
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="Updated packet builder plus a one-line comment pointing to the doc.",
            current_focus="Council packet assembly in the local AI tools layer",
            notes="Background: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md step 1",
        ),
        M.ProjectCreate(
            initiative_id=in2,
            title="Align mandate labels and add an explicit risk seat",
            brief=(
                "Rename on-screen advisor roles to match the documented seat list and ensure risk appears "
                "where the architecture expects it."
            ),
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="UI strings and config IDs line up with the canonical seat taxonomy.",
            current_focus="Frontend mandates and perspectives",
            notes="Background: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md step 2",
        ),
        M.ProjectCreate(
            initiative_id=in2,
            title="Document the intended council truth order",
            brief=(
                "Add a concise subsection to the prompt/truth architecture doc describing which sections matter most. "
                "Optionally mirror that order in a non-behavioral code comment."
            ),
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Doc subsection reviewers can quote; optional inline pointer in packet code.",
            current_focus="Architecture docs and council tooling",
            notes="Background: docs/03_IMPLEMENTATION_PLANS/NEXT_CLEANUP_STEPS_PROPOSAL.md step 3",
        ),
        M.ProjectCreate(
            initiative_id=in3,
            title="Pilot shared permission checks outside the mirror",
            brief=(
                "Pick one additional place (for example council reading a queued body) and route it through "
                "the same style of access request used for deferred intake content — or document a deliberate deferral."
            ),
            status="Draft",
            owner_id=None,
            priority="Low",
            deliverables="Decision memo plus either one integrated call site or an explicit “not yet” note with rationale.",
            current_focus="Cross-cutting policy design",
            notes="Background: docs/OPEN_QUESTIONS.md, architecture intent in docs/ATRIA_ARCHITECTURE.md",
        ),
        M.ProjectCreate(
            initiative_id=in3,
            title="Inventory where language models are invoked",
            brief=(
                "List call sites that go through adapters versus direct provider helpers so we can converge on one pattern."
            ),
            status="Draft",
            owner_id=None,
            priority="Low",
            deliverables="Short table or bullet list checked into docs or a ticket.",
            current_focus="Local AI and council code paths",
            notes="Background: docs/01_TRUTH/ACTIVE_VS_PLANNED.md",
        ),
        M.ProjectCreate(
            initiative_id=in4,
            title="Clarify asset panels: related work versus hard requirements",
            brief=(
                "In Vision & Execution, separate “linked for context” from “required before we ship” and prefer "
                "human titles over raw identifiers when data is available."
            ),
            status="Draft",
            owner_id=None,
            priority="High",
            deliverables="Asset detail views read clearly to a non-engineer.",
            current_focus="Vision & Execution asset UI",
            notes="Background: docs/MATERIAL_ENTITY_NODE_DIRECTION.md",
        ),
        M.ProjectCreate(
            initiative_id=in4,
            title="Show where each asset is required across the execution graph",
            brief=(
                "Scan initiatives, projects, and tasks for required-asset fields and surface a deterministic summary "
                "such as “required by these three active projects.”"
            ),
            status="Draft",
            owner_id=None,
            priority="Medium",
            deliverables="Reverse lookup summaries visible in the UI without new database tables.",
            current_focus="Vision & Execution data already loaded in the client",
            notes="Background: docs/MATERIAL_ENTITY_NODE_DIRECTION.md",
        ),
    ]

    proj_ids: list[str] = []
    for pcreate in projects_raw:
        row = storage.create_project(pcreate, owner_id)
        proj_ids.append(row["id"])

    # Tasks (project index matches projects_raw order)
    task_specs: list[tuple[int, str, str, str]] = [
        (
            0,
            "Load council workspace after sign-in",
            "Use the signed-in session to fetch saved advisor seats and confirm you get a real response (new row or migration path), not an empty error.",
            "Todo",
        ),
        (
            0,
            "Edit a seat and confirm it saves without spamming the server",
            "Change a label or selection, wait for debounced save, and verify the database row updates once.",
            "Todo",
        ),
        (
            1,
            "Find where a successful email poll finishes",
            "Trace the code from “poll succeeded” to the last function called so we know where to attach sync bookkeeping.",
            "Todo",
        ),
        (
            1,
            "Persist sync metadata right after a successful poll",
            "Write last-run time and cursor information to the same store the mirror reads so status screens stay accurate.",
            "Todo",
        ),
        (
            1,
            "Write a short note on cursor semantics",
            "Explain in docs or a comment what the cursor means so future changes do not break inbox ordering silently.",
            "Todo",
        ),
        (
            2,
            "Draft the deferred-content API contract",
            "Describe who may call it, what justification or access level is required, and what errors look like.",
            "Todo",
        ),
        (
            2,
            "Implement the route using the existing policy-aware fetch helper",
            "Wire authentication and ensure no code path bypasses the helper’s checks.",
            "Todo",
        ),
        (
            3,
            "Reorder council packet sections only as agreed",
            "Implement the step-one reorder from the cleanup proposal without adding new sections yet.",
            "Todo",
        ),
        (
            3,
            "Add a single-line comment pointing to the packet-order doc",
            "Future readers should see which document owns the ordering decision.",
            "Todo",
        ),
        (
            4,
            "Refresh built-in mandate display names",
            "Replace shorthand labels with the human-facing role names from the architecture doc.",
            "Todo",
        ),
        (
            4,
            "Introduce a risk mandate entry end-to-end",
            "Ensure the identifier is accepted by the backend and visible wherever other mandates appear.",
            "Todo",
        ),
        (
            5,
            "Add an “intended truth order” subsection to the architecture doc",
            "Plain-language description of what the council should weigh first.",
            "Todo",
        ),
        (
            5,
            "Optionally echo that order in a code comment",
            "Non-functional comment only — behavior change belongs in the packet task.",
            "Todo",
        ),
        (
            6,
            "Decide whether to extend policy checks beyond the mirror now",
            "Capture approve/defer with reasoning so the team does not re-litigate silently.",
            "Todo",
        ),
        (
            6,
            "If approved, integrate the smallest additional call site",
            "Pick one real workflow (for example council reading a deferred body) and route it through the shared access path.",
            "Todo",
        ),
        (
            7,
            "Search the codebase for direct model calls versus adapter calls",
            "Produce a simple categorized list.",
            "Todo",
        ),
        (
            7,
            "Publish the inventory where others can comment",
            "Drop it into docs or a tracking ticket with space for follow-ups.",
            "Todo",
        ),
        (
            8,
            "Split “linked” and “required by” presentation for assets",
            "Match the material-entity direction doc for layout and emphasis.",
            "Todo",
        ),
        (
            8,
            "Prefer titles over raw IDs wherever entity data is already loaded",
            "Reuse names from ideas, initiatives, and projects already in memory.",
            "Todo",
        ),
        (
            9,
            "Compute reverse required-asset relationships deterministically",
            "Walk initiatives, projects, and tasks for required asset fields without hand-maintained lists.",
            "Todo",
        ),
        (
            9,
            "Render human-readable summaries in the asset UI",
            "Examples: unused, linked for context, required by active delivery work.",
            "Todo",
        ),
    ]

    for pi, title, desc, st in task_specs:
        pid = proj_ids[pi]
        storage.create_task(
            M.TaskCreate(
                project_id=pid,
                title=title,
                description=desc,
                status=st,
                priority="Medium" if st == "Todo" else "Medium",
                notes="From doc-based seed script; safe to edit or close in Vision & Execution.",
            ),
            owner_id,
        )

    print(f"Created {len(created_ideas)} ideas, 4 initiatives, {len(proj_ids)} projects, {len(task_specs)} tasks.")
    print("Ideas tagged", LC, "still need an explicit architecture or product decision before major build-out.")
    print("Done.")


if __name__ == "__main__":
    main()
