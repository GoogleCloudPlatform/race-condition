# A2A Multi-Agent Communication

This guide describes how Race Condition implements Agent-to-Agent (A2A)
communication. The simulation gateway acts as an A2A broker, and agents use a
decoupled Redis-based orchestration layer for low-latency fan-out across
hundreds of concurrent runner sessions.

## 1. Topology

The gateway sits between the frontend and the agent network. Agents talk to
each other via the gateway (which proxies their agent cards) rather than
discovering each other directly. This single-broker shape lets the gateway
inject session context, route around scaled-to-zero agents, and keep
discovery O(1) regardless of agent count.

## 2. Agent endpoint registry

Each agent is mounted under a stable sub-path so the gateway can do path-based
routing.

| Endpoint               | Path                                      | Protocol             |
| :--------------------- | :---------------------------------------- | :------------------- |
| Well-known card        | `/a2a/{name}/.well-known/agent-card.json` | HTTP GET / JSON      |
| A2A RPC                | `/a2a/{name}/`                            | HTTP POST / JSON-RPC |
| Orchestration poke     | `/a2a/{name}/orchestration`               | HTTP POST / JSON     |
| Health check           | `/a2a/{name}/health`                      | HTTP GET / JSON      |

## 3. Implementation

### 3.1 Agent card construction

Agent cards are built dynamically by `AgentCardBuilder` and decorated by
`prepare_simulation_agent` (`agents/utils/a2a.py`). Use this helper rather
than hand-constructing a card dict — it expands env vars, attaches the
project's required extensions (including `n26:dispatch/1.0` for dispatch
mode), and adds the trailing slash that Starlette mount requires.

```python
# In your agent's agent.py:
from agents.utils.a2a import prepare_simulation_agent, register_a2a_routes

agent_card = prepare_simulation_agent(app, "agents")
register_a2a_routes(api_app, app, agent_card)
```

### 3.2 Push model

In Cloud Run / Agent Engine, agents can't reliably hold a Redis subscription
because they scale to zero. Instead, the gateway *pushes* orchestration
pulses directly to the agent's `/orchestration` endpoint over HTTP. The
agent's dispatcher receives the push and triggers a local fan-out to its
in-process sessions.

```python
# Simplified from agents/utils/a2a.py
@api_app.post("/a2a/{agent_name}/orchestration")
async def handle_orchestration_poke(request: Request):
    data = await request.json()
    await orchestration_plugin.dispatcher.handle_event(data)
    return {"status": "success"}
```

### 3.3 Multi-session fan-out

When the agent receives a push, it iterates through its in-memory sessions
and runs the ADK runner once per session. Results are relayed back to the
gateway by publishing to Redis:

```python
# Simplified from agents/utils/dispatcher.py
async def _process_event(self, data: dict):
    for sid in self.active_sessions:
        async for event in runner.run_async(session_id=sid, ...):
            await redis.publish("gateway:broadcast", wrapper.SerializeToString())
```

### 3.4 Gateway dual-dispatch

The gateway combines a low-latency Redis pulse (for warm agents that hold a
subscription) with an explicit HTTP poke (for cold agents that have scaled to
zero). Both paths are fired in parallel; whichever wakes the agent first
wins, and the dispatcher de-duplicates inside the agent process.

```go
// Illustrative — actual signature is on *RedisSwitchboard in
// internal/hub/switchboard.go.
func (sb *Switchboard) Broadcast(ctx context.Context, w *gateway.Wrapper) error {
    // Path A: low-latency Redis pulse for warm/local agents
    sb.redis.Publish(ctx, "simulation:broadcast", w.Payload)

    // Path B: scale-to-zero wake-up for cold/cloud agents
    for _, agent := range sb.catalog.Agents {
        go sb.httpClient.Post(agent.URL+"/orchestration", "application/json", ...)
    }
    return nil
}
```

This is the hybrid model the rest of this doc refers to: the same logical
event reaches every relevant agent regardless of whether it's currently warm.

### 3.5 Authorization

`AgentCardBuilder` populates `securitySchemes` on the agent card from the
project's auth config — you don't need to write the JSON by hand. Local
development runs without auth; deployed environments use Google service
account auth via Application Default Credentials. See
`agents/utils/a2a.py:prepare_simulation_agent` for the build path and the
relevant `agent-card.json` examples served at runtime by each agent.

## 4. Discovery and registry

### 4.1 Agent type catalog

The gateway maintains an authoritative catalog of all registered agent types,
populated at startup by fetching `/.well-known/agent-card.json` from each
URL listed in the `AGENT_URLS` env var.

- `GET /api/v1/agent-types` — returns the agent card for every registered
  agent type, including its base A2A URL.

### 4.2 Session registry

Sessions are individual NPC instances (a marathon has many runners but one
runner agent type). The gateway tracks them in Redis:

- `GET /api/v1/sessions` — lists active sessions. See section 4.3 below for
  scale considerations.

### 4.3 Listing at scale

A single JSON list of 100,000 sessions isn't useful — too big to transfer
and the request would block other gateway work for too long. Two patterns
help:

1. **Scope your listing.** List by agent type
   (`GET /api/v1/agent-types/{type}/sessions`) instead of globally. The
   working set shrinks immediately.
2. **Push, don't poll.** At 100k sessions the orchestrator should never poll
   the registry for addresses. It publishes one pulse to the gateway and
   lets the dual-dispatch path (section 3.4) reach every agent that needs
   to know.

### 4.4 The "introduction" pattern

Agents don't hunt for each other in A2A. They are introduced by the
orchestrator or the gateway:

1. The orchestrator fetches the URL of each required agent type from the
   gateway's catalog.
2. It sends one A2A message per type (via the gateway) asking the agent
   service to spawn the required number of sessions.
3. The gateway tracks the new session IDs in the registry. From this point
   forward, individual NPC interactions use point-to-point A2A with the
   shared agent URL plus the unique session ID.

## 5. Scaling: types vs. instances

### 5.1 The plugin contract

Every agent uses `SimulationCommunicationPlugin` to manage A2A client
lifecycles inside an invocation. This keeps non-serializable RPC clients
out of the session state.

```python
from agents.utils.communication_plugin import SimulationCommunicationPlugin

agent = Agent(
    # ...
    plugins=[SimulationCommunicationPlugin()],
)
```

### 5.2 Calling another agent

Use `call_agent` rather than constructing a client by hand. The helper does
the registry lookup, manages the connection, and unrolls the response.

```python
from agents.utils.communication import call_agent

# Inside a tool function:
result = await call_agent(
    agent_name="runner",
    message="Get current vitals",
    tool_context=tool_context,
)
```

### 5.3 Agent type vs. NPC instance

Per-NPC identity lives at the session level, not the URL level:

| Concept       | Level   | A2A addressing                                                          |
| :------------ | :------ | :---------------------------------------------------------------------- |
| Agent type    | Service | `AgentCard.url`, e.g. `https://runner-service/a2a/runner/`              |
| NPC instance  | Session | `context_id`, e.g. `https://runner-service/a2a/runner/sessions/{sid}`   |

10,000 active NPCs do not require 10,000 agent processes. They require a
handful of runner service instances each hosting thousands of lightweight
ADK sessions in memory.

When the orchestrator needs to broadcast, use the gateway hub (binary
fan-out). When one NPC needs to consult a specific peer, use point-to-point
A2A through `call_agent`.

## 6. Gotchas

- **Standard A2A clients don't know about `/orchestration`.**
  `RemoteA2aAgent` and other off-the-shelf clients only target `/a2a/{name}/`
  for RPC. To trigger simulation-wide events, use the project's `poke_sim_gateway`
  tool or call the orchestration endpoint directly.
- **Binary results travel via Redis.** All fanned-out A2A session results are
  relayed through the `gateway:broadcast` Redis channel as protobuf
  wrappers. Keep the gateway's broadcast logic in sync with `gateway.proto`.
- **Don't use SQLite for session state.** Use `InMemorySessionService`
  locally to avoid file-lock contention; switch to `VertexAiSessionService`
  in deployed environments.
