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

import json
import logging
import random

from google.adk.tools.tool_context import ToolContext

from agents.utils.redis_pool import get_shared_redis_client

from agents.runner.constants import (
    BASE_DEPLETION_RATE,
    COLLAPSE_THRESHOLD,
    EXHAUSTION_THRESHOLD,
    FATIGUE_DEPLETION_GROWTH,
    HYDRATION_STATION_INTERVAL_MI,
    HYDRATION_STATION_REFILL,
    MIN_FATIGUE_FACTOR,
    NATURAL_FATIGUE_RATE,
    SPEED_SCALE,
    runner_seed,
)

logger = logging.getLogger(__name__)


async def accelerate(intensity: float, tool_context: ToolContext) -> dict:
    """Increase the runner's speed based on the specified intensity.

    Speed is reduced when dehydrated: at 0% water, max speed is halved.

    Args:
        intensity: Acceleration intensity (0.0 to 1.0).
        tool_context: ADK tool context for state management.
    """
    velocity = tool_context.state.get("velocity", 0.0)
    water = tool_context.state.get("water", 100.0)
    crowd_responsiveness = tool_context.state.get("crowd_responsiveness", 0.5)
    boost_multiplier = 0.1
    # Dehydration penalty: linearly scale from 1.0 (full water) to 0.5 (no water)
    hydration_factor = 0.5 + 0.5 * (water / 100.0)
    new_velocity = velocity + (intensity * boost_multiplier * hydration_factor * crowd_responsiveness)
    tool_context.state["velocity"] = new_velocity
    logger.info(f"Runner accelerating: velocity={new_velocity:.2f} (hydration: {water:.0f}%)")
    return {
        "status": "success",
        "message": f"Accelerated to velocity={new_velocity:.2f} (hydration: {water:.0f}%).",
        "velocity": new_velocity,
    }


async def brake(intensity: float, tool_context: ToolContext) -> dict:
    """Decrease the runner's speed.

    Args:
        intensity: Braking intensity (0.0 to 1.0).
        tool_context: ADK tool context for state management.
    """
    velocity = tool_context.state.get("velocity", 0.0)
    new_velocity = max(0.0, velocity - (intensity * 1.5))
    tool_context.state["velocity"] = new_velocity
    logger.info(f"Runner braking: velocity={new_velocity:.2f}")
    return {
        "status": "success",
        "message": f"Braked to velocity={new_velocity:.2f}.",
        "velocity": new_velocity,
    }


async def get_vitals(tool_context: ToolContext) -> dict:
    """Get current runner vitals including speed, distance, hydration, and status.

    Args:
        tool_context: ADK tool context for state management.
    """
    vitals = {
        "status": "success",
        "message": "Vitals retrieved successfully.",
        "velocity": tool_context.state.get("velocity", 0.0),
        "distance": tool_context.state.get("distance", 0.0),
        "water": tool_context.state.get("water", 100.0),
        "exhausted": tool_context.state.get("exhausted", False),
        "collapsed": tool_context.state.get("collapsed", False),
    }
    logger.info(f"Runner vitals: {vitals}")
    return vitals


async def process_tick(
    tool_context: ToolContext,
    inner_thought: str,
    minutes_per_tick: float = -1.0,
    elapsed_minutes: float = -1.0,
    race_distance_mi: float = -1.0,
    tick: int = -1,
    collector_buffer_key: str = "",
) -> dict:
    """Advance the simulation by one tick and record your inner thought.

    Call this once per tick after setting your speed with accelerate or brake.
    Timing parameters (tick number, elapsed time, race distance) are provided
    automatically by the simulation -- you only need to supply inner_thought.

    ``inner_thought`` has no default value: ADK's auto-generated tool schema
    marks it as required, which materially improves small-model (e.g.
    gemma4:e2b) tool-call reliability. Optional fields are routinely
    dropped by 2-3B models.

    Args:
        tool_context: ADK tool context for state management.
        inner_thought: Short internal monologue (5 words max) about what
            the runner is thinking RIGHT NOW. Required (no default) so
            ADK marks it required in the tool schema -- small models
            reliably honor required fields and routinely drop optional
            ones. The autopilot path passes an empty string.
        minutes_per_tick: (Auto-provided) Simulated minutes per tick.
        elapsed_minutes: (Auto-provided) Total elapsed simulated time.
        race_distance_mi: (Auto-provided) Race distance in miles.
        tick: (Auto-provided) Current tick number.
        collector_buffer_key: (Auto-provided) Redis key for telemetry.

    Returns:
        Dict with runner vitals: distance, velocity, water, status.
    """
    state = tool_context.state

    # Read tick params from state if the caller didn't provide them.
    # Sentinel detection: ``-1`` / ``-1.0`` means "not provided." The
    # sentinel-default approach (vs. ``T | None = None``) is required to
    # work around an ADK schema-builder bug where union-with-None
    # parameter types cause ``required`` to be cleared on the entire tool
    # schema -- which lets small models (gemma4:e2b) drop the
    # ``inner_thought`` arg too. See Task I in
    # docs/plans/2026-04-19-llm-runner-cap-task-i-required-inner-thought.md.
    tick_params = state.get("_tick_params", {})
    if tick < 0:
        tick = tick_params.get("tick")
    if minutes_per_tick < 0:
        minutes_per_tick = tick_params.get("minutes_per_tick")
    if elapsed_minutes < 0:
        elapsed_minutes = tick_params.get("elapsed_minutes")
    if race_distance_mi < 0:
        race_distance_mi = tick_params.get("race_distance_mi")
    if not collector_buffer_key:
        collector_buffer_key = tick_params.get("collector_buffer_key", "")

    # Validate we have all required params from either source.
    # Return an error dict (not raise) so the LLM can recover if it calls
    # process_tick before any tick event has been received (e.g. during spawn).
    if tick is None or minutes_per_tick is None or elapsed_minutes is None or race_distance_mi is None:
        logger.warning("process_tick called without tick params -- no tick event received yet")
        return {
            "status": "error",
            "message": (
                "No tick event received yet. Wait for the simulation to send a tick event before calling process_tick."
            ),
        }

    velocity = state.get("velocity", 0.0)
    distance = state.get("distance", 0.0)
    water = state.get("water", 100.0)
    exhausted = state.get("exhausted", False)
    collapsed = state.get("collapsed", False)
    finished = state.get("finished", False)

    # Already finished or collapsed: no-op
    if finished or collapsed:
        return {
            "status": "success",
            "tick": tick,
            "runner_status": "finished" if finished else "collapsed",
            "velocity": velocity,
            "effective_velocity": 0.0,
            "distance_mi": distance,
            "distance": round(distance, 4),
            "water": water,
            "pace_min_per_mi": state.get("pace_min_per_mi"),
            "elapsed_minutes": elapsed_minutes,
            "mi_this_tick": 0.0,
            "finish_time_minutes": state.get("finish_time_minutes"),
            "exhausted": exhausted,
            "collapsed": collapsed,
            "inner_thought": inner_thought,
        }

    # --- Effective velocity with degradation factors ---
    # 1. Hydration: 50-100% of base speed
    hydration_factor = 0.5 + 0.5 * (water / 100.0)

    # 2. Wall: sharp pace degradation if past wall_mi
    wall_factor = 1.0
    if state.get("will_hit_wall") and distance > state.get("wall_mi", 18.6411):
        wall_factor = 1.0 - state.get("wall_severity", 0.25)

    # 3. Natural fatigue: gradual slowdown ~0.2% per tick
    fatigue_factor = max(MIN_FATIGUE_FACTOR, 1.0 - NATURAL_FATIGUE_RATE * tick)

    effective_velocity = velocity * hydration_factor * wall_factor * fatigue_factor

    # --- Distance computation ---
    effective_mph = effective_velocity * SPEED_SCALE
    mi_this_tick = effective_mph / 60.0 * minutes_per_tick
    raw_distance = distance + mi_this_tick
    new_distance = min(raw_distance, race_distance_mi)
    state["distance"] = new_distance

    # --- Hydration depletion ---
    efficiency = state.get("hydration_efficiency", 1.0)
    base_depletion = BASE_DEPLETION_RATE * mi_this_tick * efficiency
    fatigue_growth = 1.0 + FATIGUE_DEPLETION_GROWTH * new_distance
    depletion = base_depletion * fatigue_growth
    new_water = max(0.0, water - depletion)

    # --- Auto hydration station check (every ~1.86mi) ---
    # Check EVERY station crossed this tick (fast runners may cross 2-3).
    prev_marker = int(distance / HYDRATION_STATION_INTERVAL_MI)
    new_marker = int(new_distance / HYDRATION_STATION_INTERVAL_MI)
    if new_marker > prev_marker:
        session_id = getattr(getattr(tool_context, "session", None), "id", "default")
        for marker in range(prev_marker + 1, new_marker + 1):
            # Fresh RNG per station for determinism
            rng = random.Random(runner_seed(session_id, marker))
            should_drink = (
                new_water <= 40.0
                or exhausted
                or (new_water <= 60.0 and rng.random() < 0.5)
                or (new_water > 60.0 and rng.random() < 0.3)
            )
            if should_drink:
                new_water = min(100.0, new_water + HYDRATION_STATION_REFILL)

    state["water"] = new_water

    # --- Exhaustion / collapse ---
    if new_water < EXHAUSTION_THRESHOLD:
        exhausted = True
    else:
        exhausted = False
    state["exhausted"] = exhausted

    if exhausted and new_water < COLLAPSE_THRESHOLD:
        collapsed = True
    state["collapsed"] = collapsed

    # --- Finish detection ---
    runner_status = "running"
    finish_time = state.get("finish_time_minutes")
    pace = state.get("pace_min_per_mi")

    if new_distance >= race_distance_mi and not finished:
        finished = True
        state["finished"] = True
        runner_status = "finished"
        # Interpolate exact finish time (use raw_distance, before clamping)
        overshoot = raw_distance - race_distance_mi
        fraction = 1.0 - (overshoot / mi_this_tick) if mi_this_tick > 0 else 1.0
        finish_time = elapsed_minutes - minutes_per_tick * (1.0 - fraction)
        pace = finish_time / race_distance_mi if race_distance_mi > 0 else 0.0
        state["finish_time_minutes"] = round(finish_time, 2)
        state["pace_min_per_mi"] = round(pace, 2)
    elif collapsed:
        runner_status = "collapsed"
    elif exhausted:
        runner_status = "exhausted"

    state["runner_status"] = runner_status

    result = {
        "status": "success",
        "tick": tick,
        "runner_status": runner_status,
        "velocity": velocity,
        "effective_velocity": round(effective_velocity, 4),
        "distance_mi": min(round(new_distance, 3), race_distance_mi),
        "distance": min(round(new_distance, 4), race_distance_mi),
        "water": round(new_water, 1),
        "pace_min_per_mi": pace,
        "elapsed_minutes": elapsed_minutes,
        "mi_this_tick": round(mi_this_tick, 3),
        "finish_time_minutes": finish_time,
        "exhausted": exhausted,
        "collapsed": collapsed,
        "inner_thought": inner_thought,
        "wave_number": state.get("wave_number", 0),
    }

    # Stagger the first movement tick's gateway emission by wave so the
    # frontend sees runners start in waves (~2s between each wave).
    WAVE_STAGGER_SECONDS = 2.0
    wave = state.get("wave_number", 0)
    if tick == 1 and wave > 0:
        result["gateway_delay_seconds"] = wave * WAVE_STAGGER_SECONDS

    # --- Direct-write to collector buffer (bypass PubSub bottleneck) ---
    if collector_buffer_key:
        try:
            r = get_shared_redis_client()
            if r is not None:
                session_id = getattr(getattr(tool_context, "session", None), "id", "")
                direct_msg = json.dumps(
                    {
                        "session_id": session_id,
                        "payload": {
                            "tool_name": "process_tick",
                            "result": result,
                        },
                    },
                    default=str,
                )
                await r.rpush(collector_buffer_key, direct_msg)  # type: ignore[misc]
                await r.expire(collector_buffer_key, 7200)
        except Exception:
            logger.warning(
                "process_tick: direct-write RPUSH failed for %s",
                collector_buffer_key,
                exc_info=True,
            )

    return result
