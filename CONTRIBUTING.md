# Contributing to Zenaf

Thank you for exploring Zenaf. This is a **local-first, dev-oriented** application stack (FastAPI + React), not a production SaaS template.

## License

By contributing, you agree that your contributions are licensed under the **[GNU Affero General Public License v3.0](LICENSE)** (AGPL-3.0).

## Before you start

1. Read the root **[README.md](README.md)** for install and run.
2. Copy **[`.env.example`](.env.example)** to `.env.local` if you need optional env vars (never commit secrets).
3. Architecture and “what is actually built” live under **[`docs/01_TRUTH/README.md`](docs/01_TRUTH/README.md)**.

## Development setup

From repo root (Python 3.11+, Node LTS):

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r api/requirements.txt
cd frontend && npm install && cd ..
```

Run the stack:

- **Windows:** `.\open-cockpit.bat` or `.\operator_console.bat` (sync + Studio supervisor + cockpit)
- **Manual:** `python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8010` and `cd frontend && npm run dev`

Default dev login (first DB init): `owner@local.zenaf` — see [api/README.md](api/README.md) for bootstrap passwords. **Change passwords before any shared or public deployment.**

Regenerate local conformance state (optional):

```bash
python scripts/system_conformance_report.py
```

## Tests

```bash
pytest tests/
```

Some tests need no network; council/LLM paths may require Ollama or mocks depending on the test file.

## Pull requests

1. Fork the repository (after it is published — see [PUBLISHING.md](PUBLISHING.md) if you are the maintainer).
2. Create a branch from the default branch (`main` or current default).
3. Keep changes focused; match existing style in touched files.
4. Run `pytest tests/` for areas you changed.
5. Do **not** commit: `*.db`, `activity.log`, `.env.local`, OAuth tokens, `reports/notifications/`, `reports/operator_supervisor/`, or personal run logs.

## If you already pushed local data by mistake

If SQLite files, logs, or `.env` files were committed or pushed to a **public** remote, remove them from the index (see maintainer notes in [PUBLISHING.md](PUBLISHING.md)) and consider rewriting history with [git-filter-repo](https://github.com/newren/git-filter-repo) before advertising the repo.

## Questions

Open a GitHub issue once the public repository exists. For security-sensitive reports, see [SECURITY.md](SECURITY.md).
