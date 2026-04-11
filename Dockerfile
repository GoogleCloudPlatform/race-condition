# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# ============================================================
# Per-service multi-stage Dockerfile
#
# Build individual service images with:
#   docker build --target <service> -t <tag> .
#
# Available targets:
#   Go:     gateway, admin, tester, frontend
#   Python: runner_autopilot, runner_cloudrun, dash
# ============================================================


# ============================================================
# BASE STAGES
# ============================================================

# --- Go: build base with deps and shared source ---
# Use $BUILDPLATFORM so the Go compiler runs natively (no QEMU emulation).
# Cross-compilation is handled via GOOS/GOARCH env vars.
FROM --platform=$BUILDPLATFORM golang:1.25 AS go-base
ARG TARGETOS TARGETARCH
ENV GOOS=${TARGETOS} GOARCH=${TARGETARCH}
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY internal/ internal/
COPY gen_proto/ gen_proto/

# --- Web: build Vite/React frontends (admin-dash + tester) ---
# NOTE: Node version must match the project's local dev environment to ensure
# npm lockfile compatibility (npm lockfile v3 format varies across major versions).
FROM node:24-slim AS web-builder

# admin-dash — deps first for layer caching
WORKDIR /app/web/admin-dash
COPY web/admin-dash/package.json web/admin-dash/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/admin-dash/ ./
RUN npm run build

# tester — deps first for layer caching
WORKDIR /app/web/tester
COPY web/tester/package.json web/tester/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/tester/ ./
RUN npm run build

WORKDIR /app

# --- Python: dependency cache (rebuilt only when pyproject.toml/uv.lock change) ---
FROM python:3.13-slim AS python-deps
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv==0.7.12
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev


# ============================================================
# GO BUILD STAGES — one per service, parallelized by BuildKit
# ============================================================

FROM go-base AS build-gateway
COPY cmd/gateway/ cmd/gateway/
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /bin/service ./cmd/gateway

FROM go-base AS build-admin
COPY cmd/admin/ cmd/admin/
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /bin/service ./cmd/admin

FROM go-base AS build-tester
COPY cmd/tester/ cmd/tester/
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /bin/service ./cmd/tester

FROM go-base AS build-frontend
COPY cmd/frontend/ cmd/frontend/
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /bin/service ./cmd/frontend


# ============================================================
# FINAL IMAGES — Go services (distroless, ~10-25MB each)
# ============================================================

# --- gateway: API entry point, WebSocket hub, session routing ---
FROM gcr.io/distroless/static-debian12:nonroot AS gateway
WORKDIR /app
COPY --from=build-gateway /bin/service /bin/service
ENTRYPOINT ["/bin/service"]

# --- admin: Admin dashboard BFF + React SPA ---
FROM gcr.io/distroless/static-debian12:nonroot AS admin
WORKDIR /app
COPY --from=build-admin /bin/service /bin/service
COPY --from=web-builder /app/web/admin-dash/dist/ ./web/admin-dash/dist/
ENTRYPOINT ["/bin/service"]

# --- tester: Tester UI BFF + React SPA ---
FROM gcr.io/distroless/static-debian12:nonroot AS tester
WORKDIR /app
COPY --from=build-tester /bin/service /bin/service
COPY --from=web-builder /app/web/tester/dist/ ./web/tester/dist/
ENTRYPOINT ["/bin/service"]

# --- frontend: Consumer frontend BFF + Angular dist ---
# NOTE: web/frontend/dist/ must be pre-built externally (Angular from ../frontend/)
FROM gcr.io/distroless/static-debian12:nonroot AS frontend
WORKDIR /app
COPY --from=build-frontend /bin/service /bin/service
COPY web/frontend/dist/ ./web/frontend/dist/
ENTRYPOINT ["/bin/service"]


# ============================================================
# FINAL IMAGES — Python services (~200MB each)
# ============================================================

# --- runner_autopilot: Deterministic NPC runner (Cloud Run, subscriber dispatch) ---
FROM python-deps AS runner_autopilot
COPY agents/__init__.py ./agents/__init__.py
COPY agents/utils/ ./agents/utils/
COPY agents/npc/ ./agents/npc/
COPY gen_proto/ ./gen_proto/
ENV PYTHONPATH=.
CMD [".venv/bin/python", "agents/npc/runner_autopilot/agent.py"]

# --- runner_cloudrun: LLM-powered runner (Cloud Run, subscriber dispatch) ---
FROM python-deps AS runner_cloudrun
COPY agents/__init__.py ./agents/__init__.py
COPY agents/utils/ ./agents/utils/
COPY agents/npc/ ./agents/npc/
COPY gen_proto/ ./gen_proto/
ENV PYTHONPATH=.
CMD [".venv/bin/python", "agents/npc/runner/agent.py"]

# --- dash: Agent telemetry dashboard (FastAPI + WebSocket) ---
FROM python-deps AS dash
COPY agents/__init__.py ./agents/__init__.py
COPY agents/utils/ ./agents/utils/
COPY gen_proto/ ./gen_proto/
COPY scripts/ ./scripts/
COPY web/agent-dash/ ./web/agent-dash/
ENV PYTHONPATH=.
CMD [".venv/bin/python", "scripts/core/agent_dash.py"]
