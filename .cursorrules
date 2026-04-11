# Race Condition -- AI Assistant Instructions

You are helping a developer work with **Race Condition**, an open-source
multi-agent marathon simulation built with Google ADK and Gemini. It was
demonstrated at the Google Cloud Next '26 Developer Keynote.

## Quick Orientation

This is a monorepo with three language ecosystems:

| Layer | Language | Location | Build tool |
|---|---|---|---|
| Gateway + web servers | Go 1.25+ | `cmd/`, `internal/` | `go build` |
| AI agents | Python 3.13+ | `agents/` | `uv` |
| Frontends | TypeScript | `web/` | Angular CLI, Vite |
| Infrastructure | Docker Compose | `docker-compose.yml` | Redis, Pub/Sub, PostgreSQL |

**Key commands:** `make init` (first-time setup), `make start` (run
everything), `make test` (all tests), `make lint` (all linters).

## Project Conventions

- **Protobuf**: Generated code is committed in `gen_proto/`. Run `make proto`
  only if you modify `gen_proto/gateway/gateway.proto`.
- **Ports**: All service ports are configured in `.env`. Default range is
  9100--9119. See README for the full port table.
- **Testing**: Python tests run offline -- `conftest.py` mocks GCP credentials.
  Go integration tests need Redis (`docker compose up redis`).
- **Agents**: Each agent in `agents/` is a Google ADK agent with `agent.py` as
  entry point and `agent.json` as the A2A agent card.
- **A2A protocol**: Agents discover each other via `/.well-known/agent-card.json`.
  The gateway fetches these at startup.
- **No secrets in code**: GCP auth uses Application Default Credentials.
  API keys go in `.env` (gitignored).
