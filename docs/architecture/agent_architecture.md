# Agent System Architecture

This document details the topological and data-flow architecture of the N26
Developer Key Simulation Agent Infrastructure.

## A2A Network Topology

The simulation relies on a distributed Agent-to-Agent (A2A) pattern. Agents are
isolated processes that communicate via HTTP, routed through local domains for
consistency.

```mermaid
graph TD
    classDef external fill:#f9f,stroke:#333,stroke-width:2px;
    classDef core fill:#bbf,stroke:#333,stroke-width:2px;
    classDef infra fill:#bfb,stroke:#333,stroke-width:2px;

    Client(["Tester UI (web/tester)"]):::external
    Gateway["Gateway (Port 8101)"]:::infra

    subgraph "Orchestration Fabric (Redis)"
        Orch_Chan["simulation:orchestration"]:::infra
        Registry["Distributed Session Registry"]:::infra
    end

    subgraph "Agent Sub-Systems (uv run honcho)"
        Agent_Process["Agent CLI (api_server)"]:::core
        subgraph "Internal Agent Logic"
            Dispatcher["Background Redis Dispatcher"]:::core
            Runner["ADK Runner/Orchestrator"]:::core
        end
    end

    Client -->|HTTP POST /api/v1/sessions| Gateway
    Gateway -->|1. Publish Event| Orch_Chan
    Gateway -->|2. Track Session| Registry
    Orch_Chan -->|3. Trigger| Dispatcher
    Dispatcher -->|4. Invoke Agent| Runner
```

### Key Architectural Decisions

1. **Hybrid Dispatch**: The Gateway uses a **Dual Dispatch** model. It publishes
   low-latency events to Redis Pub/Sub for active agents and sends explicit HTTP
   POST "wake-up" pokes via `/a2a/` endpoints for agents that are scaled to
   zero.
2. **Always-On Subscribers**: Agents run a dedicated background thread
   (`RedisDispatcher`) that listens for messages independently of the ADK's HTTP
   invocation lifecycle.
3. **Domain Routing**: Agents still communicate with each other using standard
   local ports for A2A data exchange, but lifecycle management is now
   event-driven.

### GKE Deployment Variant

The LLM-powered runner agent is also deployed on a dedicated GKE cluster
(`runner-cluster`) on the main VPC. This GKE deployment:

- Uses the **same container image** as `runner_cloudrun` (Cloud Run)
- Advertises a **distinct agent name** (`runner_gke`) via the `AGENT_NAME` env var
- Exposes an **Internal LoadBalancer** for gateway discovery via `AGENT_URLS`
- Provides **Kubernetes-native autoscaling** (HPA, 20-200 pods)

The gateway treats `runner_gke` as a separate agent pool alongside
`runner_cloudrun` and `runner_autopilot`.

## Telemetry Streaming Flow

Agent telemetry (tools, model invocations, routing events) is extracted globally
without polluting the core Agent logic.

```mermaid
graph LR
    classDef agent fill:#bbf,stroke:#333,stroke-width:2px;
    classDef plugin fill:#fbd,stroke:#333,stroke-width:2px;
    classDef redis fill:#bfb,stroke:#333,stroke-width:2px;
    classDef ui fill:#f9f,stroke:#333,stroke-width:2px;

    Agent["ADK Agent Run"]:::agent
    Plugin["RedisDashLogPlugin (Callbacks)"]:::plugin
    Redis["Redis (Channel: gateway:broadcast)"]:::redis
    Visualizer["Web Dashboard (index.html)"]:::ui

    Agent -->|1. Event Fires| Plugin
    Plugin -->|2. Async Publish| Redis
    Redis -->|3. Subscription Stream| Visualizer
```

### The `DashLogPlugin` Lifecycle

1. **Intercept**: The plugin hooks into intrinsic ADK lifecycle events
   (`agent_start`, `tool_start`, `model_end`).
2. **Enrichment**: The plugin attaches the critical `session_id` and
   `invocation_id` to every stray payload.
3. **Transport**: The enriched JSON payload is fired asynchronously to the local
   GCP Pub/Sub emulator to avoid blocking the synchronous Agent execution
   thread.
4. **Reconstitution**: The Dashboard connects to the Pub/Sub emulator's
   WebSocket interface and mathematically reconstructs the interleaved logs by
   sorting chronologically on `invocation_id`.
