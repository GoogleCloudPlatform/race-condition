# Project Glossary

## Core concepts

- **A2A (Agent-to-Agent)**: HTTP protocol for inter-agent messaging. Each
  agent advertises an `agent-card.json` at `/.well-known/agent-card.json`; the
  gateway discovers agents from `AGENT_URLS` at startup.
- **A2UI (Agent-to-UI)**: Schema-driven protocol for sending UI components from
  an agent to a frontend as part of a normal message. Spec details and the 18
  catalog primitives are in `docs/architecture/a2ui_protocol.md`.
- **ADK (Agent Development Kit)**: Google's Python framework for building
  agents. Each Race Condition agent exposes a `root_agent` in its `agent.py`.
- **Agent**: A simulation entity built on ADK, running in its own process.
- **Agent Card**: JSON descriptor served at `/.well-known/agent-card.json`.
  Lists the agent's name, capabilities, A2A endpoints, and security schemes.
  The gateway fetches it at startup to populate its routing table.
- **Cached / live mode**: Toggle in the frontend. Cached mode replays the
  Cloud Next '26 keynote NDJSON recordings shipped under
  `web/frontend/public/assets/sim-*-log.ndjson`. Live mode drives a real
  simulation through the gateway.
- **NPC (Non-Player Character)**: An autonomous simulation entity (typically a
  Runner) that acts like a participant rather than a human user.
- **Skill (ADK)**: Encapsulated capability that a `LlmAgent` loads at
  construction time. A skill is a directory containing a `SKILL.md`
  (instructions + frontmatter) and optionally `tools.py` (Python functions
  exposed as tools).

## Agents

- **Planner**: GIS-driven agent that generates 26.2-mile marathon routes from
  the Las Vegas road network. See `agents/planner/`.
- **Planner with eval / Planner with memory**: Planner variants used in
  evaluation pipelines (`planner_with_eval`) and for AlloyDB-backed route
  memory (`planner_with_memory`).
- **Runner**: The default LLM-driven runner agent (`agents/runner/`). Decides
  pace, hydration, and route choices via Gemini calls each tick.
- **Runner Autopilot**: Deterministic runner variant
  (`agents/runner_autopilot/`) that follows a precomputed plan with no LLM
  calls. Used for high-density simulations and load tests.
- **Simulator**: Manages overall simulation lifecycle, scenario state, and
  per-tick coordination. See `agents/simulator/`.
- **Simulator with failure**: Variant (`agents/simulator_with_failure/`) that
  injects deterministic failures for chaos and recovery tests.

## Telemetry & scalability

- **Backpressure**: Mechanism that slows the sender when the receiver is
  saturated.
- **Batching**: Grouping high-frequency simulation tick events into
  time-windowed segments to reduce network overhead.
- **Dispatch mode**: How the gateway invokes an agent. *Subscriber* mode talks
  to a warm process over Redis Pub/Sub. *Callable* mode sends an HTTP
  `/a2a/` poke to wake an agent that has scaled to zero on Cloud Run.
- **Fan-out**: Distributing one incoming message to many active observers
  (e.g. thousands of dashboard clients).
- **NDJSON (Newline-Delimited JSON)**: Streaming format where each line is a
  standalone JSON object. Used for the cached keynote recordings and for the
  agent debug log.
- **`simulation_id`**: UUID identifying one simulation run. Used as the Redis
  key prefix for that run's session state and as the filter key on event
  topics.

## Infrastructure

- **Dispatcher**: Python-side event router (`agents/utils/dispatcher.py`) that
  translates orchestration messages from Redis into ADK runner invocations.
- **Gateway**: Primary entry point for client traffic and agent
  communication. Routes WebSocket frames between the frontend and the agent
  network. Runs on port 9101 by default.
- **Hub**: In-process map of `session_id` → WebSocket connection inside one
  gateway instance. Distinct from the agent registry; the Hub only knows
  which sessions are connected to *this* gateway node.
- **Hydration (runner)**: Per-runner water level that depletes during the
  race. Drives the runner's decisions about hydration stations. Not to be
  confused with state-restoration hydration in web frameworks — Race
  Condition uses the term for runner physiology.
- **`RedisDashLogPlugin`**: ADK lifecycle plugin
  (`agents/utils/plugins.py`) that publishes every agent/tool/model event to
  two channels: `gateway:broadcast` on Redis (live UI source) and a Pub/Sub
  debug topic (audit log).
- **Route planning**: GIS-based marathon route generation using the Spine and
  Sprout algorithm. See `docs/architecture/route_planning.md`.
- **Switchboard**: Redis-backed message relay that enables cross-instance
  broadcast and orchestration routing between multiple gateway processes.
