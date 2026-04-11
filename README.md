# Race Condition

[![CI](https://github.com/GoogleCloudPlatform/race-condition/actions/workflows/ci.yml/badge.svg)](https://github.com/GoogleCloudPlatform/race-condition/actions/workflows/ci.yml)

**A deployable reference architecture for orchestrating, scaling, and securing autonomous AI agents using Gemini Enterprise Agent Platform.**

## What is Race Condition?

Race Condition is a multi-agent simulation that models a marathon through Las
Vegas. Autonomous AI agents — powered by Google's Agent Development Kit (ADK)
and Gemini — take on roles as race planners, environment simulators, and
individual runner NPCs, each making independent decisions and communicating
through standardized protocols.

The project serves as a deployable reference architecture demonstrating how to
build, orchestrate, and scale autonomous AI agents on Google Cloud. It showcases
real-world patterns for agent-to-agent communication, tool use, state
management, and observability — all running on production-grade infrastructure
including AlloyDB, Redis, Pub/Sub, and Cloud Run.

Race Condition was demonstrated at Google Cloud Next as a showcase for the
Gemini Enterprise Agent Platform. It is designed to be both an educational
resource and a starting point for teams building their own multi-agent systems.

## Architecture Overview

Race Condition follows a service-oriented architecture with a central gateway
coordinating communication between web frontends and AI agent backends.

```
                         ┌─────────────────┐
                         │    Frontend      │
                         │  Angular + 3JS   │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │    Gateway        │
                         │  (Go, WebSocket)  │
                         └──┬─────┬─────┬───┘
                            │     │     │
               ┌────────────┘     │     └────────────┐
               │                  │                   │
      ┌────────▼───────┐  ┌──────▼───────┐  ┌───────▼────────┐
      │   Planner       │  │  Simulator   │  │   Runners      │
      │   Agent (Py)    │  │  Agent (Py)  │  │  Agents (Py)   │
      └────────┬───────┘  └──────┬───────┘  └───────┬────────┘
               │                  │                   │
               └──────────┬──────┘───────────────────┘
                          │
            ┌─────────────▼──────────────┐
            │  Infrastructure            │
            │  Redis · Pub/Sub · PgVector │
            └────────────────────────────┘
```

- **Gateway** — Central API and WebSocket hub written in Go. Routes requests,
  manages sessions, and bridges frontends with agents.
- **Frontend** — Angular 21 + Three.js application providing a 3D visualization
  of the marathon simulation.
- **Agents** — Python AI agents built with Google ADK:
  - *Planner*: Designs race courses and configures simulation parameters.
  - *Simulator*: Manages the race environment, weather, and event progression.
  - *Runners*: Individual NPC agents that make autonomous decisions during the race.
- **Infrastructure** — Redis (state/caching), Pub/Sub (event streaming),
  PostgreSQL with pgvector / AlloyDB (persistent storage and embeddings).
- **Agent Communication** — Agents communicate via the A2A (Agent-to-Agent)
  protocol for structured, interoperable messaging.

## Prerequisites

| Tool              | Version  |
| ----------------- | -------- |
| Go                | 1.25+    |
| Node.js           | 24+      |
| Python            | 3.13+    |
| [uv](https://docs.astral.sh/uv/) | latest |
| Docker & Compose  | latest   |
| Google Cloud SDK  | latest *(optional, for GCP features)* |

## Quickstart

```bash
# 1. Clone the repository
git clone https://github.com/GoogleCloudPlatform/race-condition.git
cd race-condition

# 2. Configure environment
cp .env.example .env
# Edit .env with your settings (defaults work for local dev)

# 3. Start infrastructure (Redis, Pub/Sub emulator, PostgreSQL)
docker-compose up -d

# 4. Build Go services
make build

# 5. Install frontend dependencies
cd web/frontend && npm ci && cd ../..

# 6. Start all services
honcho start

# 7. Open the frontend
# Navigate to http://localhost:8501
```

## Project Structure

```
race-condition/
├── agents/                  # Python AI agents
│   ├── planner/             #   Race planner agent
│   ├── simulator/           #   Environment simulator agent
│   └── runner/              #   Runner NPC agents
├── cmd/                     # Go service entrypoints
│   └── gateway/             #   Gateway server
├── internal/                # Go internal packages
├── web/                     # Web frontends
│   ├── frontend/            #   Angular + Three.js (3D visualization)
│   ├── admin-dash/          #   Admin dashboard (Vanilla JS + Vite)
│   ├── tester/              #   Tester UI (TS + Vite + Tailwind)
│   └── agent-dash/          #   Agent dashboard (self-contained HTML)
├── scripts/                 # Build and utility scripts
├── docker-compose.yml       # Local infrastructure
├── Dockerfile               # Multi-stage container build
├── Makefile                 # Build targets
├── Procfile                 # Service definitions for honcho
└── pyproject.toml           # Python project configuration
```

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for
guidelines on how to submit patches and the CLA process.

## License

This project is licensed under the Apache License 2.0 — see [LICENSE](LICENSE)
for details.

## Disclaimer

This is not an officially supported Google product.
