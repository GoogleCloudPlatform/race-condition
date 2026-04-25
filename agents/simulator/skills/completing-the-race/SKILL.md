---
name: completing-the-race
description: >
  Use when the simulator finishes its race-tick loop and must wrap up:
  compiling final results from tick snapshots, stopping the
  RaceCollector, and reporting outcomes to other agents. Triggered once
  per simulation, after the last tick.
license: Apache-2.0
---

# Post-Race

You use this skill to wrap up the simulation after the race phase completes.
This is the final phase of the simulation lifecycle.

## Instructions

1. **Compile Results**: Call `compile_results` first to aggregate all tick
   snapshots into final race metrics (vitals trends, status counts, notable
   events, and sampling quality).
2. **Stop Collector**: Call `stop_race_collector` to shut down the Redis
   subscription and clean up the RaceCollector resources.
3. **Report (Optional)**: Use `call_agent` to communicate final results to other
   agents (e.g., planner, dashboard) as needed for post-race reporting.

## Tools

- `compile_results(tool_context)`:
  Read tick_snapshots from state and aggregate into vitals_trend,
  final_status_counts, notable_events, sampling_quality, and
  avg_runners_reporting.
- `stop_race_collector(tool_context)`:
  Look up the RaceCollector by session_id and stop it to release Redis
  resources.
- `call_agent(agent_name, message, tool_context)`:
  Delegate inter-agent communication via the shared A2A utility.
