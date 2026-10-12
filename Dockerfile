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
# Bake the built SPA where api/main.py serves it from in prod.
COPY --from=frontend /app/frontend/dist ./api/static/
# Data lives here; mount a volume over it (see docker-compose.yml).
VOLUME ["/app/data"]
EXPOSE 8010
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8010}"]
