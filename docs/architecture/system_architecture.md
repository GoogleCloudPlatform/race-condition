# System Architecture

High-level architecture of the Race Condition backend: the Go services that
handle the high-frequency telemetry pipeline, and the Python agent network
built on Google ADK.

This diagram reflects what actually exists in the repo today (`cmd/`,
`internal/`, `agents/`). Earlier versions described aspirational components;
those have been pruned. If you add a new agent or service, update both
`system_architecture.mmd` and the inline mermaid block below.

```mermaid
flowchart TD
    %% Color palette
    classDef client fill:#E3F2FD,stroke:#1565C0,stroke-width:2px,color:#0D47A1;
    classDef golang fill:#E8F5E9,stroke:#2E7D32,stroke-width:2px,color:#1B5E20;
    classDef python fill:#FFF3E0,stroke:#E65100,stroke-width:2px,color:#E65100;
    classDef infra fill:#F3E5F5,stroke:#6A1B9A,stroke-width:2px,color:#4A148C;
    classDef web fill:#E0F7FA,stroke:#00838F,stroke-width:2px,color:#004D40;

    %% Subgraph styling
    style Frontend fill:#ffffff,stroke:#ccc,stroke-width:2px,stroke-dasharray: 5 5
    style GoServices fill:#f8f9fa,stroke:#adb5bd,stroke-width:2px
    style Infrastructure fill:#f8f9fa,stroke:#adb5bd,stroke-width:2px
    style AgentNetwork fill:#f8f9fa,stroke:#adb5bd,stroke-width:2px
    style RunnerPool fill:#ffffff,stroke:#dee2e6,stroke-width:1px
    style PlannerPool fill:#ffffff,stroke:#dee2e6,stroke-width:1px

    %% Frontend
    subgraph Frontend[Frontend]
        User(["User"]):::client
        SimUI["Simulation UI<br/>(Angular + three.js)"]:::web
        TesterUI["Tester UI<br/>(A2UI lab)"]:::web
        Admin["Admin dashboard"]:::web
    end

    %% Go services
    subgraph GoServices[Go services]
        Gateway["Gateway<br/>(WebSocket hub)"]:::golang
        FrontendBFF["Frontend BFF"]:::golang
        TesterServer["Tester server"]:::golang
        AdminServer["Admin server"]:::golang
    end

    %% Infrastructure
    subgraph Infrastructure[State & messaging]
        Redis["Redis<br/>(broadcast + registry)"]:::infra
        PubSub["Pub/Sub<br/>(orchestration + debug)"]:::infra
        AlloyDB["AlloyDB / Postgres<br/>(planner_with_memory)"]:::infra
    end

    %% Python agents (matches agents/ directory)
    subgraph AgentNetwork[Agent network: Python ADK]
        Simulator["simulator"]:::python
        SimulatorWithFailure["simulator_with_failure"]:::python

        subgraph PlannerPool[Planner pool]
            Planner["planner"]:::python
            PlannerEval["planner_with_eval"]:::python
            PlannerMemory["planner_with_memory"]:::python
        end

        subgraph RunnerPool[Runner pool]
            Runner["runner<br/>(LLM)"]:::python
            RunnerAutopilot["runner_autopilot<br/>(deterministic)"]:::python
        end
    end

    %% Telemetry plugin
    DashLog["RedisDashLogPlugin<br/>(per-agent telemetry)"]:::python

    %% Data flow
    User -->|interact| SimUI
    User -->|test A2UI| TesterUI
    User -->|control| Admin
    SimUI -->|WebSocket protobuf| FrontendBFF
    TesterUI -->|WebSocket| TesterServer
    Admin --> AdminServer
    FrontendBFF --> Gateway
    TesterServer --> Gateway
    AdminServer --> Gateway

    Gateway -->|broadcast| Redis
    Gateway -->|orchestration| PubSub

    Redis -->|subscriber dispatch| Runner
    Redis -->|subscriber dispatch| RunnerAutopilot
    PubSub -->|callable poke| Simulator
    PubSub -->|callable poke| Planner
    PubSub -->|callable poke| PlannerEval
    PubSub -->|callable poke| PlannerMemory
    PubSub -->|callable poke| SimulatorWithFailure

    PlannerMemory --> AlloyDB

    AgentNetwork -.->|lifecycle events| DashLog
    DashLog -->|publish| Redis
    DashLog -.->|debug log| PubSub
```

## Notes on the diagram

- **Two dispatch modes.** `runner` and `runner_autopilot` use *subscriber*
  mode — they hold a long-lived Redis subscription and react to broadcasts.
  All other agents use *callable* mode and are poked over Pub/Sub when needed.
  See `Procfile` for the `DISPATCH_MODE` per agent.
- **No BigQuery feedback loop.** Older versions of this diagram showed a
  BigQuery → Pub/Sub continuous-query loop and a `BQAnalyticsPlugin`. Neither
  exists in the repo. Telemetry is dual-emitted to Redis (live UI) and
  Pub/Sub (debug log) by the `RedisDashLogPlugin` and that's the whole
  pipeline.
- **GKE deployment**. The runner is also deployed on GKE in production via
  `infra/modules/gke-runner/`. Locally it runs as a single process on port
  9108. The diagram shows the local topology.
