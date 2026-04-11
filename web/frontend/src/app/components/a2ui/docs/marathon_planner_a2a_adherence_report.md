# Marathon Planning Multi-Agent System: A2A and A2UI Protocol Adherence Report

## 1. Executive Summary

This report evaluates the **Marathon Planner Multi-Agent System** implementation
against the standards defined in the Agent-to-Agent (A2A) and Agent-to-User
Interface (A2UI) protocols. Based on an analysis of the local environment
(`docs/local_execution_guide.md`), the agent source code
(`src/marathon_planner_agent`), and the underlying Python SDKs (`google.adk` and
`a2a`), the system demonstrates robust compliance with the core architectural
primitives, communication standards, and execution lifecycles mandated by the
protocols.

## 2. Distributed Architecture and Discovery

The A2A protocol mandates a decentralized, service-oriented architecture where
agents act as modular building blocks. The Marathon Planning system perfectly
mirrors this topology:

- **Hub-and-Spoke Topology**: The system operates with a central orchestrator
  (`marathon_planner_agent` on port 8084) delegating sub-tasks to specialized
  peer agents (`evaluator_agent`, `traffic_planner_agent`,
  `community_planner_agent`, and `economic_planner_agent`) running on distinct
  ports.
- **Agent Cards (.well-known/agent-card.json)**: The system strictly adheres to
  the protocol's capability discovery mechanism. Each agent publishes an Agent
  Card at the standardized endpoint (e.g.,
  `http://localhost:8084/.well-known/agent-card.json`). Code execution in
  `local_server.py` explicitly constructs these cards and configures their
  `preferred_transport` as `TransportProtocol.jsonrpc`.
- **Dynamic Routing**: The orchestrator dynamically routes to sub-agents using
  these endpoints. The `_get_agent_a2a_endpoint` function in `tools.py`
  successfully translates environment variable configurations (like
  `TRAFFIC_PLANNER_AGENT_RESOURCE_NAME`) into valid A2A Agent Card URLs.

## 3. Communication & JSON-RPC 2.0 Integration

The implementation strictly utilizes the highly predictable JSON-RPC 2.0
standard across HTTP transports, as dictated by A2A:

- **Request Handlers**: The underlying `a2a` Python library actively utilizes
  the `DefaultRequestHandler` (located in
  `a2a/server/request_handlers/default_request_handler.py`) to manage incoming
  JSON-RPC methods including `message/send`, `message/stream`, `tasks/get`, and
  `tasks/cancel`.
- **Timeouts and Connections**: In `tools.py`, the `SerializableRemoteA2aAgent`
  correctly lazy-loads an `httpx.AsyncClient` with a dedicated 120-second
  timeout, ensuring that complex generative processes do not prematurely
  terminate HTTP connections, and explicitly configuring the `A2AClientFactory`
  with jsonrpc transport support.

## 4. Task and Message Lifecycle Management

The Agent Development Kit (ADK) translates fluidly to the stateful A2A Task
primitives:

- **A2A Agent Executor**: The `A2aAgentExecutor` (found in
  `google/adk/a2a/executor/a2a_agent_executor.py`) intercepts A2A requests and
  converts them into an ADK `AgentRunRequest` (via `request_converter`). It
  guarantees that tasks transition through strictly defined states (`submitted`,
  `working`, `completed`, `failed`).
- **State Separation**: The executor meticulously publishes state transitions
  independently via the `EventQueue`. When a new request starts, it emits a
  `TaskStatusUpdateEvent(state=TaskState.submitted)`, followed immediately by
  `TaskState.working`.
- **Session Rehydration**: The implementation correctly maps A2A contexts to ADK
  sessions using the `InMemorySessionService`, ensuring multi-turn
  conversational persistence.

## 5. Streaming Transport and Server-Sent Events (SSE)

To mitigate latency issues typical of Generative AI, the system supports
real-time streaming:

- **SSE Handlers**: The `on_message_send_stream` asynchronous generator in the
  `DefaultRequestHandler` is responsible for handling SSE. It binds an ongoing
  ADK run to an `EventConsumer` and streams `TaskStatusUpdateEvent` and
  `TaskArtifactUpdateEvent` chunks as they become available.
- **Buffer Management**: The A2A backend code confirms proper error handling for
  network disconnections (raising `asyncio.CancelledError`), and includes
  background consumption routines to prevent data loss or orphaned tasks if a
  client disconnects unexpectedly.

## 6. A2UI Encapsulation

While the `marathon_planner_agent` logic natively focuses on A2A delegation, the
underlying SDK fully accommodates A2UI payloads:

- **Agent Output to UI**: The `A2aAgentExecutor` aggregates all generative
  outputs into a final `TaskArtifactUpdateEvent`. If an ADK agent generates
  specific tool calls that output A2UI declarative JSON representations, the
  engine correctly wraps these inside an A2A `DataPart` (distinguished via
  specific MIME type typing if configured), separating the raw application state
  from the generative UI tree using the ADK's `A2APartToGenAIPartConverter`.

## 7. Conclusion

The current implementation is fully compliant with the A2A standard. It
effectively leverages the Google ADK and A2A libraries to wrap complex
conversational and logical agent instances into standardized, JSON-RPC
controllable network services, fulfilling the decentralized vision of the
protocol.
