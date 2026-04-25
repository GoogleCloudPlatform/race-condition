---
name: pre-race
description: >
  Use when the simulator receives a validated plan from the planner and
  must initialize the race: parsing the plan, spawning runner agents,
  starting the telemetry collector, and firing the start gun. Triggered
  once per simulation, before the first tick.
license: Apache-2.0
---

# Pre-Race Setup

You use this skill to prepare and initialize the simulation before the race
begins. This is the first phase after receiving a validated plan from the
planner.

## Instructions

**CRITICAL**: These steps require SEPARATE responses. Do NOT call all tools at
once. `prepare_simulation` sets state that the other tools depend on
(`simulation_ready`, `runner_count`, `simulation_id`). Calling them in the same
response will fail with a guard error.

1. **Response 1 — Parse the Plan**: Call ONLY `prepare_simulation` with the JSON
   plan received from the planner. This extracts the route, computes tick
   parameters, and stores configuration in your session state. Do NOT call any
   other tool in this response.
2. **Response 2 — Spawn Runners + Start Collector (parallel)**: After
   `prepare_simulation` returns, call `spawn_runners` AND
   `start_race_collector` together in the SAME response. These two tools are
   independent — spawning runners and subscribing to broadcasts have no data
   dependency — so they execute simultaneously for faster startup.
3. **Response 3 — Fire Start Gun**: After both complete, call `fire_start_gun`
   to broadcast the START_GUN event to all spawned runner agents.

## Tools

- `prepare_simulation(plan_json, tool_context, duration_seconds=120, tick_interval_seconds=10, total_race_hours=6.0)`:
  Parse the plan JSON, compute max_ticks, and store simulation config in state.
- `spawn_runners(count, tool_context)`:
  HTTP POST to the gateway spawn API to create runner agent sessions.
- `start_race_collector(tool_context)`:
  Start a RaceCollector subscribed to gateway:broadcast for runner telemetry.
- `fire_start_gun(tool_context)`:
  Broadcast a START_GUN RunnerEvent to all spawned runner agents via Redis.
- `call_agent(agent_name, message, tool_context)`:
  Delegate inter-agent communication via the shared A2A utility.
