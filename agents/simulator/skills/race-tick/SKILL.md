---
name: race-tick
description:
  Per-tick race advancement tools for the simulation tick agent. Advances the
  simulation clock, broadcasts state to runners, drains telemetry, and checks
  for race completion.
---

# Race Tick

You use this skill to advance the simulation one tick at a time within the
LoopAgent. Each iteration of the loop corresponds to one simulation tick.

## Instructions

1. **Call `advance_tick` AND `compute_traffic_conditions` in the SAME response.**
   Both tools run in parallel. `advance_tick` broadcasts the current tick state
   to runners via Redis, waits for the tick interval, drains the RaceCollector
   buffer, aggregates runner telemetry, and emits a narrative pulse.
   `compute_traffic_conditions` computes traffic congestion in parallel.
2. **Then call `check_race_complete`.** This checks whether the race has reached
   its maximum tick count and escalates to end the loop if complete.
3. **Keep responses minimal.** The tick agent uses a low-cost model with no
   thinking budget. Do not generate lengthy commentary.

## Tools

- `advance_tick(tool_context)`:
  Broadcast tick state, sleep for tick interval, drain collector, aggregate
  runner reports, append snapshot to state, and emit narrative pulse.
- `check_race_complete(tool_context)`:
  Check if current_tick >= max_ticks. If so, escalate to end the loop.
  Otherwise report in_progress with ticks_remaining.
