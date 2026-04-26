# Troubleshooting Guide

Common failures when setting up or running Race Condition locally, and what to
do about each one.

## Environment & setup

### `make init` fails

- **Symptoms**: First-run install errors out before any service starts.
- **Fix**: `make check-prereqs` lists exactly which tool versions are missing
  or wrong. The current minimums are Go 1.25+, Python 3.13+, Node 20+, `uv`,
  Docker. If you upgraded Node or Go after a prior `make init`, delete
  `node_modules/` and `.venv/` and re-run.

### `gcloud` authentication errors

- **Symptoms**: Services fail with `401 Unauthorized` or `permission denied`
  when connecting to Pub/Sub or Vertex AI.
- **Fix**: Run `gcloud auth application-default login` to refresh credentials.
  Race Condition uses Application Default Credentials throughout — there are
  no service-account keys checked in or generated locally.

### Vertex AI quota exhausted

- **Symptoms**: Runner agents log `429 Resource exhausted` against
  `gemini-3.1-flash-lite-preview` (or whatever `RUNNER_MODEL` is set to).
- **Fix**: The default model has region-specific quotas. Either reduce
  `MAX_RUNNERS_LLM` in `.env`, switch `GOOGLE_CLOUD_LOCATION` to a region with
  more headroom, or override the model: `RUNNER_MODEL=ollama_chat/gemma4:e2b`
  for local Ollama (see `docs/guides/local-ollama-setup.md`).

### Port conflicts

- **Symptoms**: `uv run start` fails with "address already in use", or the UI
  can't reach a service.
- **Fix**:
  1. Run `uv run stop` to clear dangling processes from a previous run.
  2. Confirm nothing else is bound to ports `9100-9119` (`lsof -i :9100-9119`).
  3. Local services bind explicitly to `127.0.0.1` on those ports — they don't
     listen on `0.0.0.0` and they don't do path-based routing. Hit each one at
     its assigned port directly (e.g. `http://127.0.0.1:9100`).

### Redis connection failure

- **Symptoms**: Logs show `connection refused` on port `9102` (or `8102` if
  you're running the integration test stack).
- **Fix**: Redis starts as part of `uv run start`. If the container failed to
  come up, check `docker ps -a | grep redis` and `docker logs redis`. The
  integration test suite uses an isolated Redis on port 8102 via
  `docker-compose.test.yml`.

## Communication & logic

### Agent timeouts

- **Symptoms**: Runner agents fail to respond inside the simulator's tick
  window.
- **Fix**: Check the per-process honcho output — `uv run start` writes one
  named stream per agent. Search for `tick:advance` slowdowns in the
  simulator's stream and Vertex AI latency in the runner's. High-density runs
  (100+ runners) may saturate the local CPU; reduce `MAX_RUNNERS_LLM` in
  `.env`.

### One honcho process dies and the dashboard goes blank

- **Symptoms**: The dashboard renders but stops updating. The honcho output
  shows `process X exited with code 1` for one of the 13 procs.
- **Fix**: Honcho doesn't auto-restart dead procs by default. Identify which
  one died from the honcho output (each line is prefixed with the proc
  name from the `Procfile`). Stop the whole stack (`uv run stop`), fix the
  underlying cause from that proc's logs, and restart.

### Frontend opens but shows nothing

- **Symptoms**: `http://localhost:9119` loads, but the simulation never starts
  or the agent log is empty.
- **Fix**: Check the cached/live mode toggle in the frontend. *Cached* mode
  replays an NDJSON recording from
  `web/frontend/public/assets/sim-*-log.ndjson` and never talks to the
  gateway — useful for keynote-style demos but a dead end if you actually
  want the agents running. Switch to *live* and confirm the gateway is up
  (`curl http://localhost:9101/healthz`).

## Configuration errors

### Required configuration variable is missing

- **Symptoms**: A service panics or raises `ValueError` at startup citing a
  missing env var.
- **Fix**: Configuration is validated at startup. The error names the
  specific variable; add it to your `.env` (see `.env.example` for the
  canonical list and inline defaults).

## Agent & skill issues

### Agent skill loading failures

- **Symptoms**: An agent starts but logs `No skills found` or its tool list is
  empty.
- **Fix**:
  1. Verify the agent has a `skills/` directory.
  2. Each skill needs `SKILL.md` (with valid frontmatter) and, if it exposes
     tools, a `tools.py` whose public functions return `dict`.
  3. Check `load_agent_skills()` output in the agent's startup log.
  4. The compliance test `agents/tests/test_skill_compliance.py` will catch
     most of these locally — run it before debugging at runtime.

### A2UI rendering issues

- **Symptoms**: Frontend shows blank cards, missing components, or malformed
  UI.
- **Fix**:
  1. Verify the agent emits valid A2UI JSONL — see
     `docs/architecture/a2ui_protocol.md` for the spec, and
     `agents/skills/a2ui-rendering/SKILL.md` for the validation rules the
     `validate_and_emit_a2ui` tool enforces.
  2. Property values must use the typed wrappers (`literalString`,
     `literalNumber`).
  3. Component IDs must be unique within a `surfaceUpdate`, and every
     `componentRef` must resolve to one of those IDs.

## Development tooling

### Pre-commit hook failures

- **Symptoms**: `git commit` fails with hook errors.
- **Fix**:
  1. `addlicense`: ensure all source files have the Apache 2.0 header.
  2. `ruff`: `uv run ruff check agents/ --fix` auto-fixes Python lint errors.
  3. `go vet`: `go vet ./...` reports the issue location.
  4. Install hooks if you skipped that step:
     `pre-commit install && pre-commit install --hook-type pre-push`.

### Docker Compose test environment

- **Symptoms**: Integration tests fail with `Redis not available on
  localhost:9102`.
- **Fix**: Start the test Redis explicitly: `docker compose -f
  docker-compose.test.yml up -d`. The integration suite uses port 8102 (a
  separate, isolated Redis) so it doesn't collide with the dev Redis on 9102.
