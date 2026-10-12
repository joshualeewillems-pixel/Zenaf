# Deploying Zenaf to Staging (Hosted Mode)

Private staging for GUI iteration and feature testing. The app runs as one
Docker container (FastAPI + built SPA). "Blocked to the public" is handled at
the access layer (see below), not in the app.

## 0. Prerequisites

- Docker (for local compose testing), or a Fly.io / Render account.
- A secret key: `python -c 'import secrets; print(secrets.token_hex(32))'`
- A bootstrap password for the owner login (pick something strong).

## 1. Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ZENAF_PROD=1` | yes | Enables production hardening (set in Dockerfile by default). |
| `ZENAF_SECRET_KEY` | yes | App secret. Boot fails without it. |
| `ZENAF_BOOTSTRAP_PASSWORD` | yes | Initial password for `owner@local.zenaf` (admin). Dev fallback is disabled in prod. |
| `PORT` | no | Listen port (default `8010`). Platforms like Render inject their own. |
| `ZENAF_DB_DIR` | no | Data dir override (default `/app/data`, which you mount a volume over). |
| `ZENAF_LLM_PROVIDER` | no | Default LLM when the profile has none: `ollama` (default), `openai`, `anthropic`, `google`, `xai`. |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `XAI_API_KEY` | if cloud LLM | Provider keys (existing names; the credential resolver already reads them). |

## 2. Local parity test (docker compose)

```bash
cp .env.example .env   # fill in ZENAF_SECRET_KEY and ZENAF_BOOTSTRAP_PASSWORD
docker compose up --build
```

Open `http://127.0.0.1:8010`, log in as `owner@local.zenaf`. `GET /healthz`
should return `{"ok": true}`.

## 3. Fly.io

```bash
fly launch --no-deploy   # accept the Dockerfile
fly volumes create zenaf_data --size 1
fly secrets set ZENAF_SECRET_KEY=... ZENAF_BOOTSTRAP_PASSWORD=... \
  ANTHROPIC_API_KEY=...   # as needed
# mount the volume at /app/data in fly.toml [[mounts]]
fly deploy
```

`fly.toml` needs `internal_port = 8010` (or `$PORT`) and a `[[mounts]]`
section: `source = "zenaf_data"`, `destination = "/app/data"`.

## 4. Render

- New → Web Service → point at the repo (Docker runtime).
- It builds the Dockerfile; set `PORT` is automatic (Render injects it —
  the container honors `$PORT`).
- Add a Disk, mount path `/app/data`.
- Environment → add the secrets above.
- Health check path: `/healthz`.

## 5. First boot checklist

1. `GET /healthz` → `{"ok": true}`.
2. Open the URL, log in as `owner@local.zenaf` with your bootstrap password.
   Change it in Settings after first login.
3. Optional: issue your identity license — `POST /identity/license/issue`
   (or via the app once the UI exists). Imports require it.
4. Optional: set `ZENAF_LLM_PROVIDER` + key if you want cloud LLM; otherwise
   LLM features report "not configured" and everything else works.

## 6. Blocking public access ("private staging")

Pick one — the app itself only has its own login, so put one of these in
front:

- **Cloudflare Access** (recommended): put the hostname behind Cloudflare,
  add an Access policy (e.g. your email / an allowlist). Zero app changes.
- **Basic-auth sidecar**: run a tiny reverse proxy (caddy with `basic_auth`)
  in front of the container.
- **IP allowlist**: Fly.io and Render both support restricting ingress;
  allow only your IPs.

Do not rely on URL obscurity.

## 7. Notes

- SQLite on a volume is fine for staging. Back up by snapshotting the volume.
- Redeploys restart the container (brief downtime); the volume persists.
- Logs: `docker compose logs`, `fly logs`, or the Render dashboard.
- To return to local dev, just don't set `ZENAF_PROD` — everything behaves
  exactly as before.
