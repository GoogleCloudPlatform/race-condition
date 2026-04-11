# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Post-race tools for compiling results and cleaning up.

These tools wrap up the simulation after the race phase completes:
1. compile_results — aggregate tick snapshots into final metrics
2. stop_race_collector — shut down the Redis subscription
3. call_agent — delegate inter-agent communication for optional reporting
"""

import logging

import redis.exceptions
from google.adk.tools.tool_context import ToolContext

from agents.simulator.collector import RaceCollector

logger = logging.getLogger(__name__)


async def compile_results(tool_context: ToolContext) -> dict:
    """Aggregate all tick snapshots into final race metrics.

    Reads ``tick_snapshots`` from session state and produces:
    - vitals_trend: per-tick averages (velocity, water, distance)
    - final_status_counts: runner status distribution from the last tick
    - notable_events: collected notable events from all ticks
    - sampling_quality: ratio of ticks with reporting runners
    - avg_runners_reporting: mean runners per tick
    - finished_count / dnf_count: race completion statistics

    Args:
        tool_context: ADK tool context for session state access.

    Returns:
        dict with status and aggregated race results.
    """
    state = tool_context.state
    snapshots = state.get("tick_snapshots", [])
    total_ticks = len(snapshots)
    runner_count = state.get("runner_count", 0)
    finished_ids = set(state.get("finished_runner_ids", []))
    finished_count = len(finished_ids)

    # Aggregate vitals trend (per-tick averages)
    vitals_trend: list[dict] = []
    final_status_counts: dict[str, int] = {}
    notable_events: list[str] = []
    total_runners_reporting = 0
    ticks_with_runners = 0

    for snap in snapshots:
        # Per-tick vitals
        vitals_trend.append(
            {
                "tick": snap.get("tick", 0),
                "real_time_minutes": snap.get("real_time_minutes", 0.0),
                "avg_velocity": snap.get("avg_velocity", 0.0),
                "avg_water": snap.get("avg_water", 0.0),
                "avg_distance": snap.get("avg_distance", 0.0),
            }
        )

        # Final status counts — use the last tick's snapshot, not cumulative.
        # Each tick's status_counts already sums to the number of reporting
        # runners. Summing across ticks inflates the total (N runners x T ticks).
        final_status_counts = dict(snap.get("status_counts", {}))

        # Collect notable events
        notable_events.extend(snap.get("notable_events", []))

        # Runner reporting stats
        runners = snap.get("runners_reporting", 0)
        total_runners_reporting += runners
        if runners > 0:
            ticks_with_runners += 1

    avg_runners_reporting = total_runners_reporting / total_ticks if total_ticks > 0 else 0
    sampling_quality = ticks_with_runners / total_ticks if total_ticks > 0 else 0
    dnf_count = max(0, runner_count - finished_count) if runner_count > 0 else 0

    logger.info(
        "compile_results: %d ticks, %d finished, %d DNF, avg %.1f runners/tick",
        total_ticks,
        finished_count,
        dnf_count,
        avg_runners_reporting,
    )

    return {
        "status": "success",
        "simulation_id": state.get("simulation_id"),
        "total_ticks": total_ticks,
        "runner_count": runner_count,
        "finished_count": finished_count,
        "dnf_count": dnf_count,
        "vitals_trend": vitals_trend,
        "final_status_counts": final_status_counts,
        "notable_events": notable_events,
        "avg_runners_reporting": avg_runners_reporting,
        "sampling_quality": round(sampling_quality, 2),
        "message": f"Compiled {total_ticks} ticks: {finished_count} finished, {dnf_count} DNF",
    }


async def stop_race_collector(tool_context: ToolContext) -> dict:
    """Stop the RaceCollector for the current session.

    Looks up the collector by session_id and calls stop() to cancel the
    background Redis subscription task, unsubscribe, and clean up resources.

    Args:
        tool_context: ADK tool context for session state access.

    Returns:
        dict with status key.
    """
    session_id = tool_context.session.id
    collector = RaceCollector.get(session_id)

    if collector is not None:
        try:
            await collector.stop()
        except (redis.exceptions.ConnectionError, ConnectionError, OSError) as e:
            # The Redis connection may have been closed by the server due to
            # idle timeout after the race completed.  This is benign — the
            # race data is already collected; we're just cleaning up.
            logger.warning("stop_race_collector: Redis cleanup error (benign): %s", e)
        logger.info("stop_race_collector: stopped collector for session %s", session_id)
    else:
        logger.info("stop_race_collector: no collector found for session %s", session_id)

    # Publish end_simulation so dispatchers remove runner sessions.
    simulation_id = tool_context.state.get("simulation_id")
    if simulation_id:
        try:
            from agents.simulator.broadcast import publish_end_simulation

            await publish_end_simulation(simulation_id)
        except Exception as e:
            logger.warning("stop_race_collector: failed to publish end_simulation: %s", e)

    # Clear simulation flags to prevent the race engine from re-running
    # if the root LLM re-invokes simulation_pipeline after completion.
    tool_context.state["simulation_ready"] = False
    tool_context.state["simulation_in_progress"] = False

    return {
        "status": "success",
        "simulation_id": tool_context.state.get("simulation_id"),
        "session_id": session_id,
        "message": "Race collector stopped" if collector is not None else "No collector to stop",
    }


async def call_agent(agent_name: str, message: str, tool_context: ToolContext) -> dict:
    """Delegate inter-agent communication via the shared A2A utility.

    Args:
        agent_name: Name of the target agent (e.g., 'runner', 'planner').
        message: The instruction or query to send.
        tool_context: ADK tool context for A2A client access.

    Returns:
        dict with status and response from the target agent.
    """
    from agents.utils.communication import call_agent as _call_agent

    return await _call_agent(agent_name=agent_name, message=message, tool_context=tool_context)
