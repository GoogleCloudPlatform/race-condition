---
name: preparing-the-race
description: >
  Use when the simulator receives a validated plan from the planner and
  must initialize the race: parsing the plan, spawning runner agents,
  starting the telemetry collector, and firing the start gun. Triggered
  once per simulation, before the first tick.
license: Apache-2.0
---

# Preparing the Race

This skill initializes the simulation after a validated plan arrives
from the planner.

## Workflow

Each numbered step is a **separate model response**. The skill toolset
guards against multi-step responses with an error.

```
Pre-Race Progress:
- [ ] Response 1: prepare_simulation (alone)
- [ ] Response 2: spawn_runners + start_race_collector (parallel)
- [ ] Response 3: fire_start_gun
```

**Why separate responses:** `prepare_simulation` sets state
(`simulation_ready`, `runner_count`, `simulation_id`) that the other
tools read. The skill guard rejects parallel calls that would race
with that state write.

### Response 1: Parse the plan

Call only `prepare_simulation` with the JSON plan from the planner.
The tool extracts the route, computes tick parameters, and stores
configuration in session state.

### Response 2: Spawn runners + start collector (parallel)

Call `spawn_runners` and `start_race_collector` together in the same
response. The two tools are independent: spawning runners and
subscribing to broadcasts have no data dependency, so they execute
simultaneously for faster startup.

### Response 3: Fire the start gun

Call `fire_start_gun` to broadcast the START_GUN event to all spawned
runner agents.

## Tools

- `prepare_simulation(plan_json, tool_context, duration_seconds=120, tick_interval_seconds=10, total_race_hours=6.0)`:
  Parse the plan JSON, compute max_ticks, and store simulation config
  in state.
- `spawn_runners(count, tool_context)`:
  HTTP POST to the gateway spawn API to create runner agent sessions.
- `start_race_collector(tool_context)`:
  Start a RaceCollector subscribed to gateway:broadcast for runner
  telemetry.
- `fire_start_gun(tool_context)`:
  Broadcast a START_GUN RunnerEvent to all spawned runner agents via
  Redis.
- `call_agent(agent_name, message, tool_context)`:
  Delegate inter-agent communication via the shared A2A utility.
