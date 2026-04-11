# Architecture Documentation Map

This directory contains formal proofs and detailed logic for the simulation's
core components. Use the map below to find the specific documentation for your
area of interest.

## 🗺️ Architectural Map

### 1. The Simulation Engine

- [Scalability Proof](simulation_scalability_proof.md): How we reach 10k+
  agents.

### 2. The Agent Network

How agents communicate and coordinate.

- [Agent Architecture](agent_architecture.md): Topology of the ADK/A2A network.
- [Agent Logic Proof](agent_logic_proof.md): Consistency and session integrity
  proofs.
- [Communication Protocol](communication_protocol.md): Low-level schema and
  handshake logic.
- [Multi-Session Routing](multi_session_routing.md): How agents maintain state
  across multiple sessions.
- [Route Planning](route_planning.md): GIS-based marathon route generation
  logic.

### 3. Simulation Standards

- [A2UI Protocol](a2ui_protocol.md): Standardizing agent-to-UI communication.
- [Port Mapping](ports.md): Standardized port assignments across all services.

## 🎓 Learning from the Architecture

If you are using this project for educational purposes, we recommend reading in
this order:

1. [Onboarding Guide](../onboarding.md)
2. [Agent Architecture](agent_architecture.md)
3. [A2UI Protocol](a2ui_protocol.md)
4. [Implementing Skills (Guide)](../guides/implementing_skills.md)
