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
        DashUI["Telemetry dashboard"]:::web
    end

    %% Go services
    subgraph GoServices[Go services]
        Gateway["Gateway<br/>(WebSocket hub)"]:::golang
        FrontendBFF["Frontend BFF"]:::golang
        TesterServer["Tester server"]:::golang
        AdminServer["Admin server"]:::golang
    end

    %% Python services (non-agent)
    subgraph PythonServices[Python services]
        DashServer["Dashboard backend<br/>(scripts/core/agent_dash.py)"]:::python
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
    User -->|inspect telemetry| DashUI
    SimUI -->|WebSocket protobuf| FrontendBFF
    TesterUI -->|WebSocket| TesterServer
    Admin --> AdminServer
    DashUI --> DashServer
    FrontendBFF --> Gateway
    TesterServer --> Gateway
    AdminServer --> Gateway
    DashServer -.->|subscribe| Redis

    Gateway -->|broadcast frames| Redis
    Gateway -->|orchestration pulse<br/>simulation:broadcast| Redis
    Gateway -->|HTTP /orchestration poke| Runner
    Gateway -->|HTTP /orchestration poke| RunnerAutopilot
    Gateway -->|HTTP /orchestration poke| Simulator
    Gateway -->|HTTP /orchestration poke| Planner
    Gateway -->|HTTP /orchestration poke| PlannerEval
    Gateway -->|HTTP /orchestration poke| PlannerMemory
    Gateway -->|HTTP /orchestration poke| SimulatorWithFailure
    Redis -.->|subscriber listener| Runner
    Redis -.->|subscriber listener| RunnerAutopilot

    PlannerMemory --> AlloyDB

    AgentNetwork -.->|lifecycle events| DashLog
    DashLog -->|publish| Redis
    DashLog -.->|debug log| PubSub
```

## Notes on the diagram

- **Two dispatch modes.** `runner` and `runner_autopilot` use *subscriber*
  mode (`DISPATCH_MODE=subscriber` in the `Procfile`) — they hold a long-lived
  Redis subscription on `simulation:broadcast` so they wake on a pulse with
  near-zero latency. Every other agent uses *callable* mode
  (`DISPATCH_MODE=callable`) and only reacts to HTTP pokes on its
  `/orchestration` endpoint. The gateway always sends the HTTP poke
  regardless of mode, so subscribers receive the event twice; the
  dispatcher de-duplicates inside the agent process. Callable mode is what
  makes scale-to-zero possible on Cloud Run / Agent Engine in production.
- **GCP Pub/Sub is only used for the debug-log topic.** The "orchestration"
  channel `simulation:broadcast` lives on Redis, not GCP Pub/Sub.
  `RedisDashLogPlugin` is the only thing in the system that publishes to
  GCP Pub/Sub.
- **No BigQuery feedback loop.** Older versions of this diagram showed a
  BigQuery → Pub/Sub continuous-query loop and a `BQAnalyticsPlugin`. Neither
  exists in the repo.
- **GKE deployment.** The runner is also deployed on GKE in production via
  `infra/modules/gke-runner/`. Locally it runs as a single process on port
  9108. The diagram shows the local topology.
