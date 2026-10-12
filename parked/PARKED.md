# Parked modules

**Date:** 2026-10-12
**Context:** Zenaf re-centered from "local-first workflow cockpit" to an economy of
personally trained AI agents (digital doppelgänger). See
`docs/02_ACTIVE_DESIGN/TRAINING_SIGNAL_DESIGN.md`.

Nothing here is deleted — git history preserves everything, and each module can be
restored by moving it back. "Parked" means: deprioritized, not maintained, not part
of the active product surface.

## What was moved and why

| Location | Was | Why parked |
|----------|-----|------------|
| `parked/local_ai-soil/` | Soil layer v1: interpretive filesystem substrate (kernel, CLI, append/promote). | Already frozen per `docs/01_TRUTH/ACTIVE_VS_PLANNED.md` ("shipped and frozen unless explicitly re-chartered"). v2+ was never scheduled. |
| `parked/api-routes-soil_api.py` | Thin authenticated API transport for the soil layer (`POST /vision-execution/soil/append`, `/promote`). | Moved with the soil layer. Was not registered in `api/main.py` (dead route). |
| `parked/test_soil_api.py`, `parked/test_soil_kernel.py` | Tests for the soil layer. | Moved with the soil layer. |
| `parked/local_ai-transcripts/` | Transcript sorter backend (`sort_transcript`). | Satellite feature; not part of the agent-economy core. The API route (`api/routes/transcript_routes.py`) stays wired but is marked deprecated and loads the module from its parked location. |
| `parked/frontend-src-inbox-triage/` | Intake triage UI panels. | Intake *product surface* parked. Nothing imported it (already orphaned). The intake mirror/queue engine (`local_ai/intake/`) stays in place. |
| `parked/github-workflows-philosophy-enforcement.yml` | CI workflow enforcing the old workflow-cockpit philosophy matrix (`scripts/philosophy_enforcement/run_all.py` + routing tests on every PR to main). | Old-vision machinery: its TRUTH docs were archived by the agent-economy refocus, so the workflow fails on every run. `scripts/philosophy_enforcement/` is left in place but inert without the workflow trigger. Restore by moving the file back to `.github/workflows/`. |

## Parked in place (not moved — too deeply wired to relocate safely)

- **File Steward** (`tools/file_steward/`): the initial build, now deprioritized. `local_ai/zenaf_tools.py` lazily imports its `app.py` by path for the `/run` modes (`analyze`/`recommend`/`assess`/`simulate`), so relocation would break the import chain; it stays put, marked deprecated here. Four stale generated CSV reports (~60MB) were deleted per the repo's no-tracked-logs policy.
- **Content product surface** (`frontend/src/content/`): briefs, script/newsletter UI. Only `App.tsx` imports it, but `App.tsx` (7,700 lines) cannot be safely rewritten in this pass; the surface stays, marked deprecated in its index.
- **Workspace organizer UI** (`frontend/src/App.tsx`, workspace mode): the council UI lives inside the workspace shell, so the mode stays. File-organizer-specific features within it are deprioritized.
- **Meeting intelligence** (`frontend/src/meeting-intelligence/`): imported by kept modules (`vision-execution` views, `ai-actions`). Left untouched.

## Restoration

To restore any module: `git mv parked/<dir> <original-path>` and re-register any
routes/nav entries noted above. Four stale generated CSV reports
(`tools/file_steward/logs/stale_report_*.csv`, ~60MB) were deleted rather than
parked, per the repo's own no-tracked-logs policy.
