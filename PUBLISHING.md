# Publishing Zenaf as a public open source repository

Maintainer checklist for the first **public** GitHub release (AGPL-3.0). Contributors cloning the repo only need [README.md](README.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Pre-push verification (local)

```bash
# No tracked databases or logs
git ls-files "*.db" activity.log debug-*.log

# Should return nothing. If not, run git rm --cached on those paths.

pytest tests/
```

Confirm [LICENSE](LICENSE), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [.env.example](.env.example) exist at repo root.

## Create the GitHub repository

1. On GitHub: **New repository** → name e.g. `zenaf` → **Public**.
2. Do **not** add a README, license, or .gitignore (this repo already has them).
3. Copy the empty repo URL, e.g. `https://github.com/YOUR_ORG/zenaf.git`.

## Push (first time or new remote)

From repo root, after committing the open-source prep changes:

```bash
# If replacing old remote:
git remote remove origin
git remote add origin https://github.com/YOUR_ORG/zenaf.git

# Or add a second remote:
git remote add zenaf-public https://github.com/YOUR_ORG/zenaf.git

git push -u origin HEAD:main
```

Use your actual default branch name if it is not `main`.

## Repository settings (recommended)

| Setting | Suggestion |
|---------|------------|
| Description | Local-first workflow cockpit with Philosophy Council, Vision Execution, and operator supervision |
| Topics | `local-first`, `fastapi`, `react`, `vite`, `llm`, `workflow`, `sqlite` |
| Issues | Enabled |
| Discussions | Optional, for “how do I run X?” |
| Actions secrets | Do not add Twilio secrets until you want CI SMS |

Workflows under `.github/workflows/` are mostly `workflow_dispatch`; review before enabling scheduled jobs on a public fork.

## If local data was ever pushed to a public remote

SQLite files (`intake_mirror.db`, `data/vision_execution/*.db`), `activity.log`, or personal paths under `reports/arc_detection/` must not remain in **public history**.

Options:

1. **Never pushed publicly** — removing files from the index (already done in prep) is enough going forward.
2. **Already pushed** — use [git-filter-repo](https://github.com/newren/git-filter-repo) to purge paths, then force-push (coordinate with any collaborators), or publish a **fresh repo** with a clean initial commit.

## After publish

- Update [SECURITY.md](SECURITY.md) replace `YOUR_ORG/zenaf` with the real advisory URL.
- Add the repo link to [README.md](README.md) community section.
- Announce when ready (blog, social, friends who want to “mess with it”).

## License reminder

Zenaf is **AGPL-3.0**. If you run a **modified** version as a **network service** for others, you must offer corresponding source to users per AGPL section 13. See [LICENSE](LICENSE).
