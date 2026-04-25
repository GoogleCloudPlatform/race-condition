---
name: pre-race
description: >
  Use when running the simulator-with-failure test variant and the
  pre-race phase begins. The prepare_simulation tool intentionally
  raises RuntimeError to exercise the ADK and
  SimulationCommunicationPlugin tool_error callback path. Not intended
  for production simulations.
license: Apache-2.0
---

# Pre-Race Setup (Failure Variant)

This skill replaces the base simulator's pre-race setup with a version that
intentionally fails during `prepare_simulation`. It tests how the ADK and
SimulationCommunicationPlugin handle `tool_error` callbacks when the simulation
engine encounters failures.

## Tools

- `prepare_simulation`: Accepts a plan JSON string but raises `RuntimeError`
  after a brief processing delay, simulating an unhandled internal exception.
