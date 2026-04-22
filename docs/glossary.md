# Project Glossary

This document defines core terms and concepts used throughout the simulation.

## Core Concepts

- **NPC (Non-Player Character)**: An autonomous simulation entity (Runner) that
  acts like a user or participant.
- **Agent**: A simulation entity powered by the Agent Development Kit (ADK).
- **A2A (Agent-to-Agent)**: The communication protocol enabling inter-agent
  messaging and coordination.
- **A2UI**: The framework-agnostic protocol for delivering UI updates from
  agents to the simulation dashboard. See `.gemini/a2ui-spec/` for the v0.8.0
  spec.
- **Skill (ADK)**: An encapsulated capability loaded by an agent at startup.
  Skills contain instructions (`SKILL.md`) and tool implementations
  (`tools.py`).

## Agents

- **Planner Agent**: ADK-powered GIS analyst that generates mathematically
  precise marathon routes using the Las Vegas road network.
- **Simulation Agent**: Manages overall simulation lifecycle, scenario state,
  and agent coordination.
- **Runner Agent**: Individual NPC that simulates a marathon runner's race
  behavior. Available in two variants: **Runner Autopilot** (deterministic
  physics) and **Runner LLM** (model-driven decisions).

## Telemetry & Scalability

- **Batching**: The process of grouping high-frequency simulation tick events
  into time-windowed segments to reduce network overhead.
- **Fan-out**: Distributing a single incoming message to multiple active
  observers (e.g., thousands of visualizers).
- **Backpressure**: A signal or mechanism that slows down the sender when the
  receiver is saturated.
- **NDJ (Newline Delimited JSON)**: A format for streaming multiple JSON objects
  over a single TCP/WebSocket connection.
- **Hydration**: The process of restoring agent state from a persistent store
  when resuming a simulation session.

## Infrastructure

- **ECS (Entity Component System)**: An architectural pattern that separates
  data (Components) from logic (Systems) for high-performance simulation.
- **Orchestrator**: The central agent that manages the simulation lifecycle and
  scenario state.
- **Gateway**: The primary entry point for event distribution and agent
  communication.
- **Switchboard**: Redis-backed message relay that enables cross-instance
  broadcast and orchestration routing between multiple Gateway processes.
- **Dispatcher**: Python-side event router that translates orchestration
  messages from Redis into agent actions.
- **DashLogPlugin**: ADK callback plugin that publishes agent narrative events
  to Redis for dashboard consumption.
- **Route Planning**: GIS-based marathon route generation using `networkx` and
  `osmnx`, producing GeoJSON output with water stations and medical tents.
