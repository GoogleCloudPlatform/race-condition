# Troubleshooting Guide

Common issues encountered when setting up or running the simulation.

## Environment & Setup

### `gcloud` Authentication Errors

- **Symptoms**: Services fail with `401 Unauthorized` or `permission denied`
  when connecting to Pub/Sub or Vertex AI.
- **Fix**: Run `gcloud auth application-default login` to refresh your local
  credentials.

### Port Conflicts & Local Routing

- **Symptoms**: `uv run start` fails with "address already in use" or UI cannot
  find services.
- **Fix**:
  1. Ensure no other services are running on ports `8000-8502`. Run
     `uv run stop` to clear any dangling processes.
  2. **Local Requirement**: We use explicit ports (e.g., `127.0.0.1:8101`) for
     all local services. Avoid using same-domain path routing locally.

### Redis Connection Failure

- **Symptoms**: Logs show `connection refused` on port `8102`.
- **Fix**: Redis is typically started as part of `uv run start`. If it fails,
  ensure Docker is running and healthy.

## Communication & Logic

### Agent Timeouts

- **Symptoms**: Runner agents fail to respond to the Orchestrator.
- **Fix**: Check `RESOURCES` in the Orchestrator logs. High-concurrency
  simulations (100+ agents) may hit local CPU limits if running on older
  hardware.

## Configuration Errors

### "❌ CRITICAL ERROR: Required configuration variable '...' is missing"

- **Symptoms**: Service fails to start with a panic or ValueError.
- **Fix**: We use defensive configuration validation. Check the error message
  for the specific missing variable and ensure it is defined in your `.env`
  file. See `.env.example` for the full list of required variables.

## Agent & Skill Issues

### Agent Skill Loading Failures

- **Symptoms**: Agent starts but logs `No skills found` or tools are missing.
- **Fix**:
  1. Verify the `skills/` directory exists under the agent directory.
  2. Each skill must have a `SKILL.md` file and `tools.py` with importable tool
     functions.
  3. Check `load_agent_skills()` output in agent startup logs.

### A2UI Rendering Issues

- **Symptoms**: Frontend shows blank cards, missing components, or malformed UI.
- **Fix**:
  1. Verify the agent emits valid A2UI JSONL (check
     `.agents/skills/a2ui-compliance/SKILL.md`).
  2. Ensure all property values use typed wrappers (`literalString`,
     `literalNumber`).
  3. Check that component IDs are unique and all references resolve.


## Development Tooling

### Pre-commit Hook Failures

- **Symptoms**: `git commit` fails with hook errors.
- **Fix**:
  1. `addlicense`: Ensure all Go files have the Apache 2.0 license header.
  2. `ruff`: Run `uv run ruff check agents/ --fix` to auto-fix Python lint
     errors.
  3. `go vet`: Run `go vet ./...` to check for Go issues.
  4. Install hooks:
     `pre-commit install && pre-commit install --hook-type pre-push`.

### `gcert` Authentication

- **Symptoms**: `uv sync` or `go mod tidy` fails with registry access errors.
- **Fix**: Run `gcert` before any command that interacts with internal package
  registries.

### Docker Compose Test Environment

- **Symptoms**: Integration tests fail with
  `Redis not available on localhost:8102`.
- **Fix**: Start the test Redis:
  `docker compose -f docker-compose.test.yml up -d`. The test suite uses port
  `8102` for an isolated Redis instance.
