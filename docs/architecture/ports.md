# Port Standardization Architecture

This document defines the local developer port allocation strategy for the Race Condition project to ensure stability, discoverability, and organization.

## Port Allocation Blocks

| Range | Category | Description |
| :--- | :--- | :--- |
| **8000 - 8099** | **Admin & System** | Centralized dashboards and administrative tools. |
| **8100 - 8199** | **Core Infrastructure** | Core Go services (Gateway, etc). |
| **8200 - 8299** | **AI Agents (Python)** | Simulation agents using the ADK framework. |
| **8300 - 8399** | **Developer UIs** | Specialized tools for monitoring and testing. |
| **8500 - 8599** | **Frontend** | Reserved for the primary frontend application. |

## Service Mapping

| Service | Port | Category | Notes |
| :--- | :--- | :--- | :--- |
| **Admin Dash** | 8000 | Admin | Entry point for developers. |
| **Gateway** | 8101 | Core | Primary API gateway. |
| **Redis** | 8102 | Core | Session state & orchestration store. |
| **PubSub** | 8103 | Core | Global telemetry bus emulator. |
| **Postgres / AlloyDB Proxy** | 8104 | Core | Local pgvector container or AlloyDB Auth Proxy. |
| **Tester UI** | 8304 | Dev UI | Manual A2UI testing lab. |
| **Simulator** | 8202 | Agent | Lifecycle management agent. |
| **Planner** | 8204 | Agent | Strategy and execution orchestration. |
| **Planner with Eval** | 8205 | Agent | Planner with evaluation tools. |
| **Simulator w/ Failure** | 8206 | Agent | Intentional failure injection agent. |
| **Runner** | 8207 | Agent | LLM-powered runner (Cloud Run). |
| **Runner GKE** | 8207 | Agent | LLM-powered runner (GKE). Same image, distinct agent name. |
| **Planner w/ Memory** | 8209 | Agent | Route planner with AlloyDB memory. |
| **Runner Autopilot** | 8210 | Agent | Deterministic autopilot runner. |

## Best Practices

- **Never Hardcode**: Always use the `PORT` environment variable with these as defaults.
- **Bind to 0.0.0.0**: Ensure services are accessible via the Gateway.

## Worktree Port Offset Scheme

For parallel development using git worktrees, each worktree is assigned a
**slot** (0-3). The slot number is multiplied by 1000 and added to all base
ports, giving each worktree a completely isolated port space.

### Port Ranges per Slot

| Slot | Service Ports   | Redis   | PubSub  | Use                     |
| :--- | :-------------- | :------ | :------ | :---------------------- |
| 0    | 8000 -- 8599    | 8102    | 8103    | Main checkout (default) |
| 1    | 9000 -- 9599    | 9102    | 9103    | Worktree A              |
| 2    | 10000 -- 10599  | 10102   | 10103   | Worktree B              |
| 3    | 11000 -- 11599  | 11102   | 11103   | Worktree C              |

### Setup

```bash
# After creating a worktree, generate its .env with offset ports:
make worktree-env SLOT=1

# Start normally -- honcho reads the local .env:
uv run start --skip-tests

# Stop normally -- reads ports from local .env:
uv run stop
```

### Infrastructure Isolation

Each worktree gets its own Redis and PubSub Docker containers via a generated
`docker-compose.override.yml`. Container names include the slot number (e.g.,
`redis-slot-1`) to avoid conflicts. See the `worktree-port-management` skill
for full details.

## Local vs. Cloud Routing

> [!IMPORTANT]
> **Localhost**: Path-based routing (e.g., `/admin`) is **not supported** in local development. Access services directly via their root URL on assigned ports (e.g., `http://127.0.0.1:8000`).
> **GCloud/Production**: Path-based routing is handled by the Cloud Load Balancer URL Map.
