# Scripts Directory

Automation, deployment, testing, and operational utilities organized into
semantic subdirectories.

## Directory Structure

```
scripts/
  core/       Simulation lifecycle, infrastructure, build tooling
  deploy/     Deployment, CI, Git configuration
  bench/      Performance benchmarks and stress tests
  e2e/        End-to-end integration tests (run against live services)
  ops/        Operational and ad-hoc utilities
  tests/      Tests for the scripts themselves
```

---

## `core/` -- Lifecycle & Infrastructure

| Script | Integration | Description |
|:---|:---|:---|
| `sim.py` | `pyproject.toml` (`uv run start/stop/restart/test`) | Simulation lifecycle CLI: boots Redis, PubSub, Go services, and Python agents via Honcho |
| `agent_dash.py` | `Procfile`, `Dockerfile` | FastAPI telemetry dashboard with PubSub WebSocket relay |
| `gen_worktree_env.py` | `Makefile` (`worktree-env`) | Generates worktree-specific `.env` and `docker-compose.override.yml` with port offsets |
| `generate_proto.sh` | `Makefile` (`proto`) | Generates Go + Python protobuf bindings from `gen_proto/` |
| `start_db.sh` | `Procfile` | Starts local Postgres (Docker) or AlloyDB Auth Proxy |
| `install_alloydb_proxy.sh` | Called by `start_db.sh` | Downloads AlloyDB Auth Proxy binary |
| `run_agent.sh` | -- | Thin ADK CLI wrapper for starting an agent API server |

## `deploy/` -- Deployment & CI

| Script | Integration | Description |
|:---|:---|:---|
| `deploy.py` | `pyproject.toml` (`uv run deploy`) | Deploys to Cloud Run, Agent Engine, and GKE |
| `ssm_pr.sh` | `AGENTS.md`, `CONTRIBUTING.md` | Creates Pull Requests in Secure Source Manager via REST API |
| `setup_git.sh` | `.pre-commit-config.yaml`, `README.md` | Configures Git SSH signing, credential helper, and pre-commit hooks |
| `coverage_ratchet.sh` | `Makefile` (`coverage-ratchet-go`) | Enforces Go coverage never decreases below the recorded baseline |
| `generate_seed_plans.py` | -- | Generates deterministic seed plan JSON files for `planner_with_memory` |

## `bench/` -- Performance & Stress Testing

| Script | Integration | Description |
|:---|:---|:---|
| `perf_diagnostic.py` | `Makefile` (`perf-diagnostic`) | Gateway performance diagnostic: HTTP health, WebSocket stability, simulation lifecycle |
| `perf_test.py` | `Makefile` (`perf-test`) | Generic ADK agent perf test with OTel span capture |
| `bench_concurrency.py` | `Makefile` (`bench-concurrency`) | Benchmarks per-instance session capacity for Cloud Run sizing |
| `bench_helpers.py` | Imported by `bench_concurrency.py` | Percentile, duration, and byte formatting utilities |
| `eval_stress_test.py` | `Makefile` (`eval-stress`) | Runs `planner_with_eval` N times, reports latency and eval consistency |
| `stress_test_a2a.py` | -- | Benchmarks A2A communication via `SimulationA2AClient` |
| `stress_test_db.py` | -- | Tests DB pool contention under old vs new defaults |

## `e2e/` -- End-to-End Tests

| Script | Integration | Description |
|:---|:---|:---|
| `e2e_simulation_test.py` | `Makefile` (`test-e2e-simulation`) | Full planner-to-simulator integration test |
| `e2e_fanout_test.py` | -- | Fan-out scale test: spawns N runner sessions, sends broadcast |
| `e2e_scale_test.py` | `Makefile` (`scale-test`) | 10k session GCP scale validation |
| `e2e_dispatch_test.sh` | -- | Gateway dispatch routing E2E with mock agents |
| `test_runner.py` | -- | Multi-mode runner harness (A2A, Gateway, Redis transports) |
| `test_vllm_runner.py` | -- | vLLM server integration test (OpenAI-compatible API) |

## `ops/` -- Operational Utilities

| Script | Integration | Description |
|:---|:---|:---|
| `emergency_flush.py` | -- | Clears all state across Redis, AlloyDB, and PubSub; can kill/revive Cloud Run instances |
| `discover_maps_tools.py` | -- | Validates Maps MCP server tools against documented SKILL.md |
| `spark_alloydb_processor.py` | `README.md` | PySpark + Document AI pipeline for ingesting PDF regulations into AlloyDB |

## `tests/` -- Script Tests

| Test File | Tests For |
|:---|:---|
| `test_sim_logging.py` | `core/sim.py` (Honcho log tee) |
| `test_gen_worktree_env.py` | `core/gen_worktree_env.py` (port offsets, env generation) |
| `test_agent_dash_reconnect.py` | `core/agent_dash.py` (PubSub reconnect backoff) |
| `deploy_test.py` | `deploy/deploy.py` (env vars, staging, deploy modes) |
| `test_deploy.py` | `deploy/deploy.py` (URL patterns, service config) |
| `test_deploy_gke.py` | `deploy/deploy.py` (GKE service registration) |
| `test_bench_concurrency.py` | `bench/bench_concurrency.py` (agent loading, concurrency runs) |
| `test_bench_helpers.py` | `bench/bench_helpers.py` (percentiles, formatting) |
| `test_perf_diagnostic.py` | `bench/perf_diagnostic.py` (latency buckets, phases, reporting) |

Run all script tests: `make bench-test`
