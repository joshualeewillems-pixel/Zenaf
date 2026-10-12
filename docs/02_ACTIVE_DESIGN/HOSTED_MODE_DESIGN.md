# Hosted Mode — Design

**Status:** Implemented (staging-grade)
**Date:** 2026-10-12

## Why

Zenaf was built local-first: a personal Mac, localhost API, local Ollama,
SQLite under the repo. That was the right default — but it strands the
product. There is no local machine to run on right now, a private staging
environment needs a URL, and the doppelganger rental economy cannot run on
laptops. Hosted mode makes the app deployable to a server without forking it
into a "cloud version": one codebase, two postures.

## What changes

- **Env-gated production mode.** `ZENAF_PROD=1` switches hardening on;
  unset means local dev, byte-for-byte the old behavior. No config files, no
  build flavors — environment only.
- **Fail-fast secrets.** Prod refuses to boot without `ZENAF_SECRET_KEY` and
  `ZENAF_BOOTSTRAP_PASSWORD`. The dev fallback passwords
  (`local-dev-owner`, `phil-local-dev`) are unreachable in prod; the phil dev
  fixture account is not created at all on hosted deployments.
- **Secure cookies.** Session cookies get `Secure=True` in prod (the platform
  terminates TLS). Dev keeps `Secure=False` on plain http.
- **Deployable artifact.** Multi-stage Dockerfile: Vite build
  (`VITE_API_BASE=""` → same-origin API) baked into `api/static/`, served by
  the FastAPI process with an SPA fallback. One container, one port.
- **Configurable API base.** The frontend's hardcoded `127.0.0.1:8010` is now
  behind `apiBase()` (`src/apiBase.ts`): build-time `VITE_API_BASE`, defaulting
  to the old absolute URL in dev so cookie behavior is unchanged.
- **Provider selection via env.** `ZENAF_LLM_PROVIDER` sets the default LLM
  provider when the user profile has none (default: `ollama`, unchanged).
  API keys come from the existing env names (`OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`, or the
  `ZENAF_SYSTEM_*` variants) through the existing credential resolution —
  no new provider machinery.

## What does NOT change

- **Local dev is untouched.** No env vars → exactly today's behavior:
  same ports, same cookies, same fallbacks, same Ollama default.
- **SQLite stays.** Single-server staging does not need Postgres. The volume
  holds all DBs; backups are volume snapshots.
- **Ollama stays the default.** Hosted mode does not require a cloud LLM;
  it merely allows one. A staging box without Ollama boots fine — LLM
  features report "not configured" instead of crashing.
- **No multi-tenancy.** One deployment = one owner (the identity license
  model already assumes this). The login exists; there is no signup flow
  and no tenant isolation to audit.

## Privacy story, reframed

Local-first promised "your data never leaves your laptop." Hosted mode moves
the promise, not the principle: **"your data never leaves your server."**
Everything that made the local story trustworthy still holds — redaction at
capture, the identity license and consent scopes, approval gates before
training, takeout/deletion — because those are enforced by the application,
not by the laptop. The threat model changes in exactly one place: you now
trust the host (Fly.io/Render/your VPS) with the disk, the way you trusted
Apple with the SSD. The application never phones home; there is no telemetry,
no external training, no third party in the loop except the LLM provider you
explicitly configure.

## Deliberately deferred

- Multi-user Postgres, read replicas, horizontal scaling.
- Managed secret rotation (keys live in env / platform secrets).
- PKI for the identity license (still HMAC tamper-evidence).
- SSO / OAuth login (the app login + platform-level access control suffice
  for staging).
- Zero-downtime deploys (single container; brief restart on redeploy).

## Files

- `local_ai/hosted_config.py` — the whole env contract in one place.
- `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`.
- `frontend/src/apiBase.ts`; `api/main.py` (static serving, `/healthz`).
- `docs/04_REFERENCE/DEPLOY_STAGING.md` — the operator guide.
