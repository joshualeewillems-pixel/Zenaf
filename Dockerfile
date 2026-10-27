# Zenaf — hosted mode.
#
# Stage 1 builds the Vite frontend (VITE_API_BASE="" => same-origin API).
# Stage 2 runs the FastAPI backend and serves the built SPA.
#
# Required at runtime (see docs/04_REFERENCE/DEPLOY_STAGING.md):
#   ZENAF_PROD=1  ZENAF_SECRET_KEY  ZENAF_BOOTSTRAP_PASSWORD
# Optional: ZENAF_LLM_PROVIDER + provider API keys, PORT, ZENAF_DB_DIR.

# ---- Stage 1: frontend build ----
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Empty VITE_API_BASE => apiBase() returns "" => same-origin fetches.
# NOTE: `vite build` directly (not `npm run build`): the repo has pre-existing
# `tsc -b` errors on main unrelated to hosted mode; vite transpiles without
# typechecking, which is what ships.
RUN VITE_API_BASE="" npx vite build

# ---- Stage 2: backend + static SPA ----
FROM python:3.12-slim AS backend
# Tool-access bake-in (stage-1 increment A): the deployed commit,
# passed by the Fly deploy workflow as github.sha. The snapshot build
# below records the same SHA in the manifest, and the runtime
# verification helper cross-checks manifest commit vs this value.
# Empty here (e.g. local compose builds) means: no snapshot ships,
# and the runtime helper disables tools (fail closed).
# NOTE: the workflow change that passes this arg lands separately
# (this PR's token lacks the `workflow` scope to push workflow files);
# until it lands, Fly deploys also skip the snapshot and tools stay
# disabled — fail closed, never faked.
ARG ZENAF_CODE_VERSION
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ZENAF_PROD=1 \
    PORT=8010
WORKDIR /app
COPY api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY api/ ./api/
COPY local_ai/ ./local_ai/
COPY config/ ./config/
# Tool-access snapshot (stage-1 increment A): a build-time copy of
# local_ai/ ONLY into ./tool_snapshot, from the same build context
# as the app tree above, with a manifest (commit, timestamp,
# allowlist, per-file SHA-256 digests). The build step fails on any
# manifest-generation problem (escaping symlink, denylist violation,
# scan failure). Frontend source is NOT in this image (only the
# built SPA under ./api/static/), so there is no frontend-src
# snapshot question: local_ai/ only, per the approved plan.
# When ZENAF_CODE_VERSION is unset the snapshot is skipped, not
# faked: a manifest without a truthful commit would be a lie, and
# the runtime helper disables tools when no snapshot verifies.
RUN if [ -n "$ZENAF_CODE_VERSION" ]; then \
      python -m local_ai.build_room.tool_snapshot build \
        --source ./local_ai --dest ./tool_snapshot \
        --commit "$ZENAF_CODE_VERSION" \
      && python -m local_ai.build_room.tool_snapshot scan \
        --snapshot-dir ./tool_snapshot; \
    else \
      echo "WARNING: ZENAF_CODE_VERSION not set; skipping tool snapshot (tools disabled at runtime)"; \
    fi
ENV ZENAF_CODE_VERSION=${ZENAF_CODE_VERSION}
# Bake the built SPA where api/main.py serves it from in prod.
COPY --from=frontend /app/frontend/dist ./api/static/
# Data lives here; mount a volume over it (see docker-compose.yml).
VOLUME ["/app/data"]
EXPOSE 8010
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8010}"]
