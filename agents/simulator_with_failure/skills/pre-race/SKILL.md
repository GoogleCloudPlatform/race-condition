---
name: pre-race
description:
  Failing pre-race tools for error handling verification. Replaces the base
  simulator's prepare_simulation with a version that raises RuntimeError.
---

# Pre-Race Setup (Failure Variant)

This skill replaces the base simulator's pre-race setup with a version that
intentionally fails during `prepare_simulation`. It tests how the ADK and
SimulationCommunicationPlugin handle `tool_error` callbacks when the simulation
engine encounters failures.

## Tools

- `prepare_simulation`: Accepts a plan JSON string but raises `RuntimeError`
  after a brief processing delay, simulating an unhandled internal exception.
