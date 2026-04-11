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

"""Race-tick tools for per-tick simulation advancement.

These tools are called by the tick LoopAgent on each iteration:
1. advance_tick — broadcast, sleep, drain collector, aggregate, snapshot
2. check_race_complete — escalate when max ticks reached
"""

import asyncio
import logging
import time

from google.adk.tools.tool_context import ToolContext

from agents.simulator.broadcast import publish_to_runners
from agents.simulator.collector import RaceCollector
from agents.utils.runner_protocol import build_tick_event, serialize_runner_event
from agents.utils.sim_defaults import DEFAULT_MAX_TICKS, DEFAULT_TICK_INTERVAL_SECONDS

logger = logging.getLogger(__name__)


def _collect_reporting_runners(messages: list[dict], dest: set[str], *, current_tick: int = -1) -> None:
    """Extract unique runner session IDs with process_tick payloads into *dest*.

    When *current_tick* >= 0, messages whose ``result.tick`` doesn't match
    are silently skipped (stale-message filtering).
    """
    for msg in messages:
        payload = msg.get("payload", {})
        if isinstance(payload, dict) and payload.get("tool_name") == "process_tick":
            if current_tick >= 0:
                result = payload.get("result", {})
                if isinstance(result, dict):
                    msg_tick = result.get("tick")
                    if msg_tick is not None and msg_tick != current_tick:
                        continue
            sid = msg.get("session_id", "")
            if sid:
                dest.add(sid)


async def advance_tick(tool_context: ToolContext) -> dict:
    """Advance the simulation by one tick.

    Reads current_tick, max_ticks, and config from session state. Publishes a
    broadcast to the ``simulation:broadcast`` Redis channel, sleeps for the
    tick interval, drains the RaceCollector buffer, aggregates runner
    telemetry, appends a snapshot to state, and emits a narrative pulse.

    Args:
        tool_context: ADK tool context for session state access.

    Returns:
        dict with aggregated tick statistics.
    """
    state = tool_context.state
    current_tick = state.get("current_tick", 0)
    max_ticks = state.get("max_ticks", DEFAULT_MAX_TICKS)
    config = state.get("simulation_config", {})
    tick_interval = config.get("tick_interval_seconds", DEFAULT_TICK_INTERVAL_SECONDS)
    total_race_hours = config.get("total_race_hours", 6.0)
    session_id = tool_context.session.id

    simulation_id = state.get("simulation_id")

    # Compute simulated race time for this tick.  Tick 0 is the init tick
    # (minutes_per_tick=0, elapsed=0).  Movement ticks (1+) use
    # elapsed = tick * minutes_per_tick, matching build_tick_event().
    minutes_per_tick = (total_race_hours * 60) / max_ticks if max_ticks > 0 else 0
    real_time_minutes = current_tick * minutes_per_tick

    # ------------------------------------------------------------------
    # Flush stale messages before broadcasting — but rescue finish data
    # ------------------------------------------------------------------
    # The RaceCollector may contain stale results from previous ticks.
    # Drain before broadcasting this tick to prevent contamination.
    # However, check stale messages for runner_status=="finished" so
    # late-arriving finish results are not permanently lost (fixes the
    # DNF mismatch where runners finishing near the end of a tick window
    # are missed).
    collector = RaceCollector.get(session_id)
    if collector is not None:
        stale_messages = await collector.drain()
        # Rescue any finished runners from stale data
        existing_finished = set(state.get("finished_runner_ids", []))
        for msg in stale_messages:
            payload = msg.get("payload", {})
            if isinstance(payload, dict):
                result = payload.get("result", payload)
                if isinstance(result, dict) and result.get("runner_status") == "finished":
                    sid = msg.get("session_id", "")
                    if sid:
                        existing_finished.add(sid)
        state["finished_runner_ids"] = list(existing_finished)

    # ------------------------------------------------------------------
    # Publish TICK event to simulation:broadcast Redis channel
    # ------------------------------------------------------------------
    tick_event = build_tick_event(
        tick=current_tick,
        max_ticks=max_ticks,
        total_race_hours=total_race_hours,
        race_distance_mi=config.get("race_distance_mi", 26.2188),
        collector_buffer_key=f"collector:buffer:{session_id}",
    )
    await publish_to_runners(serialize_runner_event(tick_event), simulation_id=simulation_id)

    # ------------------------------------------------------------------
    # Progressive drain during sleep window, then poll if needed
    # ------------------------------------------------------------------
    expected_runner_ids = state.get("runner_session_ids", [])
    expected_count = len(expected_runner_ids)
    poll_interval = config.get("poll_interval", 0.2)
    max_collection = config.get("max_collection_seconds", tick_interval)
    drain_interval = 0.2  # drain every 200ms during sleep window

    messages: list[dict] = []
    reported_runners: set[str] = set()

    if collector is None:
        logger.warning("advance_tick: no RaceCollector for session %s", session_id)
        await asyncio.sleep(tick_interval)
    elif tick_interval <= 0:
        # Zero-interval mode (tests / instant ticks): single drain, no sleep
        messages = await collector.drain()
        _collect_reporting_runners(messages, reported_runners, current_tick=current_tick)
    else:
        # Early-wake drain: collect results during the sleep window
        t_sleep_start = time.perf_counter()
        while time.perf_counter() - t_sleep_start < tick_interval:
            remaining = tick_interval - (time.perf_counter() - t_sleep_start)
            await asyncio.sleep(min(drain_interval, remaining))
            new_msgs = await collector.drain()
            if new_msgs:
                messages.extend(new_msgs)
                _collect_reporting_runners(new_msgs, reported_runners, current_tick=current_tick)
                if len(reported_runners) >= expected_count:
                    # All runners reported -- wait for remaining tick_interval floor
                    remaining = tick_interval - (time.perf_counter() - t_sleep_start)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                    logger.info(
                        "PERF_TRACE: all %d runners reported at %.1fs (tick_interval=%.1f)",
                        expected_count,
                        time.perf_counter() - t_sleep_start,
                        tick_interval,
                    )
                    break

        # Post-sleep poll only if not all runners reported
        if len(reported_runners) < expected_count:
            poll_start = time.perf_counter()
            while len(reported_runners) < expected_count and (time.perf_counter() - poll_start) < max_collection:
                await asyncio.sleep(poll_interval)
                new_msgs = await collector.drain()
                if new_msgs:
                    messages.extend(new_msgs)
                    _collect_reporting_runners(new_msgs, reported_runners, current_tick=current_tick)

    if len(reported_runners) < expected_count:
        missing = set(expected_runner_ids) - reported_runners
        logger.warning(
            "advance_tick: timeout waiting for runners; got %d/%d, missing: %s",
            len(reported_runners),
            expected_count,
            missing,
        )

    # ------------------------------------------------------------------
    # Aggregate runner telemetry from process_tick tool_end events
    # ------------------------------------------------------------------
    # Runners emit multiple events per tick (function_call, tool_end,
    # text summary). Only process_tick tool_end events contain valid
    # telemetry. We filter for those and deduplicate by session_id
    # (one result per runner per tick).
    total_velocity = 0.0
    total_water = 0.0
    total_distance = 0.0
    status_counts: dict[str, int] = {}
    notable_events: list[str] = []
    finished_ids: list[str] = []
    seen_runners: set[str] = set()

    for msg in messages:
        payload = msg.get("payload", {})
        # Skip non-dict payloads (text summaries, etc.)
        if not isinstance(payload, dict):
            continue
        # Only aggregate process_tick tool_end results
        if payload.get("tool_name") != "process_tick":
            continue
        result = payload.get("result", {})
        if not isinstance(result, dict):
            continue

        # Skip stale results from previous ticks
        msg_tick = result.get("tick")
        if msg_tick is not None and msg_tick != current_tick:
            continue

        # Deduplicate by session_id (one result per runner per tick)
        sid = msg.get("session_id", "")
        if sid in seen_runners:
            continue
        seen_runners.add(sid)

        # Use effective_velocity (accounts for fatigue/hydration/wall) when
        # the runner is actively moving.  Finished/collapsed runners report
        # effective_velocity=0; fall back to base velocity so the field
        # average remains meaningful for pace display.
        eff_vel = result.get("effective_velocity", 0.0)
        total_velocity += eff_vel if eff_vel > 0 else result.get("velocity", 0.0)
        total_water += result.get("water", 0.0)
        total_distance += result.get("distance_mi", 0.0)

        runner_status = result.get("runner_status", "unknown")
        status_counts[runner_status] = status_counts.get(runner_status, 0) + 1

        # Track finished runners
        if runner_status == "finished" and sid:
            finished_ids.append(sid)

        notable = result.get("notable_event")
        if notable:
            notable_events.append(notable)

    runners_reporting = len(seen_runners)
    avg_velocity = total_velocity / runners_reporting if runners_reporting > 0 else 0.0
    avg_water = total_water / runners_reporting if runners_reporting > 0 else 0.0
    avg_distance = total_distance / runners_reporting if runners_reporting > 0 else 0.0

    # Update finished runner tracking in state (O(1) dedup via set)
    existing_finished = set(state.get("finished_runner_ids", []))
    existing_finished.update(finished_ids)
    state["finished_runner_ids"] = list(existing_finished)

    # Reconcile status_counts with cumulative finished state.
    # A runner that finished on a previous tick but didn't report on this
    # tick would be missing from per-tick status_counts.  The cumulative
    # finished_runner_ids is the source of truth for finisher count.
    if existing_finished:
        status_counts["finished"] = len(existing_finished)

    # ------------------------------------------------------------------
    # Build snapshot and append to state
    # ------------------------------------------------------------------
    snapshot = {
        "tick": current_tick,
        "max_ticks": max_ticks,
        "real_time_minutes": round(real_time_minutes, 2),
        "runners_reporting": runners_reporting,
        "avg_velocity": round(avg_velocity, 3),
        "avg_water": round(avg_water, 1),
        "avg_distance": round(avg_distance, 3),
        "status_counts": status_counts,
        "notable_events": notable_events,
        "finished_runner_ids": finished_ids,
    }

    if "tick_snapshots" not in state:
        state["tick_snapshots"] = []
    state["tick_snapshots"].append(snapshot)

    # Increment current_tick HERE inside the tool so it advances
    # even if the LLM calls advance_tick multiple times in one turn.
    state["current_tick"] = current_tick + 1

    # ------------------------------------------------------------------
    # Emit narrative pulse
    # ------------------------------------------------------------------
    narrative = (
        f"Tick {current_tick}/{max_ticks} ({round(real_time_minutes, 1)} min): {runners_reporting} runners reporting"
    )
    if notable_events:
        narrative += f" | Events: {', '.join(notable_events)}"

    # ------------------------------------------------------------------
    # Compute traffic conditions (code-level, not LLM-driven)
    # ------------------------------------------------------------------
    traffic: dict | None = None
    traffic_model = state.get("traffic_model")
    if traffic_model:
        try:
            from agents.utils.traffic import compute_tick_traffic

            segment_index = traffic_model.get("segment_index", [])
            ticks_closed = traffic_model.get("ticks_closed", {})
            sweep_distance = avg_distance * 0.6  # back-of-pack estimate

            traffic_result = compute_tick_traffic(
                segment_index=segment_index,
                sweep_distance_mi=sweep_distance,
                current_tick=current_tick,
                ticks_closed=ticks_closed,
            )
            traffic_model["ticks_closed"] = traffic_result["ticks_closed"]

            # Full per-segment data including coordinates for frontend
            # visualization.  The tick agent uses include_contents='none'
            # so prior tick responses don't accumulate in model context.
            traffic = {
                "sweep_distance_mi": round(sweep_distance, 3),
                "segments": traffic_result["segments"],
                "overall_congestion": traffic_result["overall_congestion"],
                "tev_impact": traffic_result["tev_impact"],
            }
        except Exception as e:
            logger.warning("advance_tick: traffic computation failed: %s", e)

    logger.info("advance_tick: %s", narrative)

    # All data flows through the tool_end event — no custom gateway
    # messages.  The frontend reads tick + traffic from tool_end payload.
    result: dict = {
        "status": "success",
        "simulation_id": simulation_id,
        "tick": current_tick,
        "max_ticks": max_ticks,
        "real_time_minutes": round(real_time_minutes, 2),
        "runners_reporting": runners_reporting,
        "avg_velocity": round(avg_velocity, 3),
        "avg_water": round(avg_water, 1),
        "avg_distance": round(avg_distance, 3),
        "status_counts": status_counts,
        "finished_runner_ids": list(existing_finished),
        "notable_events": notable_events,
        "message": narrative,
    }
    if traffic:
        result["traffic"] = traffic
    return result


async def check_race_complete(tool_context: ToolContext) -> dict:
    """Check whether the race has reached its maximum tick count.

    If current_tick >= max_ticks, sets ``tool_context.actions.escalate = True``
    to signal the LoopAgent to exit.

    Args:
        tool_context: ADK tool context for session state access.

    Returns:
        dict with race status and remaining ticks.
    """
    state = tool_context.state
    current_tick = state.get("current_tick", 0)
    max_ticks = state.get("max_ticks", DEFAULT_MAX_TICKS)

    if current_tick >= max_ticks:
        tool_context.actions.escalate = True
        logger.info(
            "check_race_complete: race complete at tick %d/%d",
            current_tick,
            max_ticks,
        )
        return {
            "status": "race_complete",
            "simulation_id": state.get("simulation_id"),
            "current_tick": current_tick,
            "max_ticks": max_ticks,
            "message": f"Race complete after {max_ticks} ticks",
        }

    ticks_remaining = max_ticks - current_tick
    logger.info(
        "check_race_complete: in_progress tick %d/%d (%d remaining)",
        current_tick,
        max_ticks,
        ticks_remaining,
    )
    return {
        "status": "in_progress",
        "simulation_id": state.get("simulation_id"),
        "current_tick": current_tick,
        "max_ticks": max_ticks,
        "ticks_remaining": ticks_remaining,
        "message": f"Race in progress: {ticks_remaining} ticks remaining",
    }
