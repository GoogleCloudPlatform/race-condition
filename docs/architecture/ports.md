# Port Allocation

This document is the source of truth for which Race Condition service binds
which port locally. The values match `.env.example`. If they ever drift, treat
`.env.example` as authoritative and file an issue against this doc.

## Default port range

All services bind in the **9100–9119** range on `127.0.0.1`. Pick this range
for any new local service you add so it stays out of the way of common dev
tools (8080, 8000, 5000) and so that `uv run stop` can reap stragglers
predictably.

## Service map

| Service | Port | Env var | Notes |
| :--- | :--- | :--- | :--- |
| Admin dashboard | 9100 | `ADMIN_PORT` / `PORT` | Dev entry point. |
| Gateway | 9101 | `GATEWAY_PORT` | WebSocket hub and A2A router. |
| Redis | 9102 | `REDIS_ADDR` | Session state and broadcast fan-out. |
| Pub/Sub emulator | 9103 | `PUBSUB_EMULATOR_HOST` | Agent debug-log topic. |
| Simulator | 9104 | `SIMULATOR_PORT` | Race lifecycle and tick orchestration. |
| Planner | 9105 | `PLANNER_PORT` | Route + spatial planning. |
| Planner (with eval) | 9106 | `PLANNER_WITH_EVAL_PORT` | Planner variant with evaluation tools. |
| Simulator (with failure) | 9107 | `SIMULATOR_WITH_FAILURE_PORT` | Failure-injection variant for chaos tests. |
| Runner (LLM) | 9108 | `RUNNER_PORT` | Model-driven runner agent. |
| Planner (with memory) | 9109 | `PLANNER_WITH_MEMORY_PORT` | Planner variant backed by AlloyDB. |
| Runner (autopilot) | 9110 | `RUNNER_AUTOPILOT_PORT` | Deterministic runner — no LLM calls. |
| Dashboard backend | 9111 | `DASH_PORT` | Telemetry dashboard server. |
| Tester UI | 9112 | `TESTER_PORT` | Manual A2UI testing lab. |
| Postgres / AlloyDB proxy | 9113 | `ALLOYDB_PORT` | Local pgvector container or AlloyDB Auth Proxy. |
| Frontend BFF | 9118 | `FRONTEND_BFF_PORT` | Backend-for-frontend that proxies to the gateway. |
| Frontend app | 9119 | `FRONTEND_APP_PORT` | Angular dev server. |

The runner LLM agent is also deployed on GKE in production. Locally it runs as
a single process on 9108; the GKE deployment uses an Internal LoadBalancer
discovered via `RUNNER_GKE_INTERNAL_URL`.

## Conventions

- **Always read from env.** Don't hard-code port numbers in code or scripts;
  read `os.getenv("GATEWAY_PORT", "9101")` (Python) or
  `os.Getenv("GATEWAY_PORT")` (Go) so worktrees with different slot offsets
  don't collide.
- **Bind to `127.0.0.1`, not `0.0.0.0`.** The gateway is the only ingress
  point. Other services are reachable from the host but not over LAN.

## Worktree slot scheme

Parallel checkouts on different branches need disjoint port spaces so they
don't fight for the same socket. Race Condition supports this via a slot
marker file `.port-slot` at the repo root:

- **Slot 0** (default — file absent or contains `0`): use the 9100–9119 range
  documented above. Containers are named `redis`, `pubsub`.
- **Slot N > 0**: offset all ports by `1000 * N` (slot 1 → 10100s, slot 2 →
  11100s) and rename containers to `redis-slot-N`, `pubsub-slot-N`. The
  `scripts/core/sim.py` start/stop logic reads `.port-slot` and applies the
  offset automatically.

To enable a non-default slot, write the slot number to `.port-slot`, copy
`.env.example` to `.env`, and edit each `*_PORT` value with the offset. A
helper script for this is on the roadmap; for now, do it by hand.

## Local vs. cloud routing

> [!IMPORTANT]
> **Local**: path-based routing (e.g. `/admin`) is **not** supported. Hit each
> service directly at its assigned port (e.g. `http://127.0.0.1:9100`).
>
> **Cloud Run**: path-based routing is handled by the Cloud Load Balancer URL
> map. Local emulation of that routing is intentionally absent.
