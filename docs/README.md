# Documentation

Welcome to the Race Condition documentation. The repository's top-level
`README.md` is the right place to start — it covers what the project is, how
to set it up, and how the agents split the work. This `docs/` tree is the
deeper reference: glossary, troubleshooting, architecture, design notes, and
guides for specific subsystems.

## Quick links

- New here? Read `../README.md` first, then come back for the depth.
- Stuck? Check [`troubleshooting.md`](troubleshooting.md).
- Confused by a term? Check [`glossary.md`](glossary.md).

## Reference

| Doc | What it covers |
| :--- | :--- |
| [`glossary.md`](glossary.md) | Project-specific terms (A2A, A2UI, ADK, dispatch mode, simulation_id, hub, switchboard, runner variants). |
| [`troubleshooting.md`](troubleshooting.md) | Common failures and fixes — gcloud auth, port conflicts, Vertex quota, blank frontend, dead honcho proc. |
| [`api/REFERENCE.md`](api/REFERENCE.md) | Auto-generated API reference for the simulation gateway. |

## Architecture (`architecture/`)

How the system is built and why.

| Doc | What it covers |
| :--- | :--- |
| [`architecture/README.md`](architecture/README.md) | Map of the architecture subtree with a suggested reading order. |
| [`architecture/system_architecture.md`](architecture/system_architecture.md) | High-level diagram of services, agents, and infrastructure. |
| [`architecture/agent_architecture.md`](architecture/agent_architecture.md) | A2A network topology, telemetry streaming, design rationale. |
| [`architecture/communication_protocol.md`](architecture/communication_protocol.md) | Wire schema, the `gateway.Wrapper` envelope, multi-session routing, agent-to-client response flow. |
| [`architecture/a2ui_protocol.md`](architecture/a2ui_protocol.md) | The 18 A2UI primitives and how agents emit them. |
| [`architecture/route_planning.md`](architecture/route_planning.md) | The Spine and Sprout algorithm for generating exact 26.2-mile routes. |
| [`architecture/ports.md`](architecture/ports.md) | Port assignments for local services. The source of truth is `.env.example`. |

## Design notes (`design/`)

Component-level design discussion that's deeper than architecture but
narrower than guides.

| Doc | What it covers |
| :--- | :--- |
| [`design/gateway-messaging.md`](design/gateway-messaging.md) | Session-aware message routing inside the gateway, dispatch modes, and agent discovery. |

## Guides (`guides/`)

How to do specific things.

| Doc | What it covers |
| :--- | :--- |
| [`guides/a2a-implementation-guide.md`](guides/a2a-implementation-guide.md) | Implementing A2A on top of ADK: agent cards, push model, dual dispatch, scaling patterns. |
| [`guides/adk-agent-performance-optimization.md`](guides/adk-agent-performance-optimization.md) | 21 techniques (model selection, context caching, parallelism, prompt engineering) ranked by ROI. |
| [`guides/implementing_skills.md`](guides/implementing_skills.md) | Adding ADK skills to agents — directory layout, frontmatter rules, auto-discovery, naming conventions. |
| [`guides/local-ollama-setup.md`](guides/local-ollama-setup.md) | Running the runner agent on a local Gemma 4 via Ollama instead of Vertex AI. |
| [`guides/testing.md`](guides/testing.md) | Test architecture, commands, coverage targets, pre-commit hooks. |

## Project policies

- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — how to contribute.
- [`../CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) — community norms.
- [`../SECURITY.md`](../SECURITY.md) — how to report security issues.
- [`../LICENSE`](../LICENSE) — Apache 2.0.
