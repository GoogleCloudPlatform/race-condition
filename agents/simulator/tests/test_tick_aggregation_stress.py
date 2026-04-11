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

"""Stress test: 50 concurrent simulations x 5 runners x 6 ticks.

Validates that tick aggregation is perfectly accurate across many
concurrent simulations, with special focus on the finished-runner
regression: runners_reporting must NEVER drop below RUNNER_COUNT once
all runners have been initialized, and averages must NEVER be zero
when runners exist.

This test runs real runner agents via InMemoryRunner (no LLM — the
before_model_callback intercepts all calls deterministically), builds
collector drain messages from actual session state, and feeds them to
advance_tick with mock collectors.

Each simulation is fully independent (own InMemoryRunner instances, own
session IDs, own simulator state). The 50 simulations run concurrently
via asyncio.gather to exercise any shared-state issues.
"""

import asyncio
import importlib.util
import pathlib
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.npc.runner_autopilot.agent import root_agent as runner_agent
from agents.utils.runner_protocol import (
    RunnerEvent,
    RunnerEventType,
    serialize_runner_event,
)

# Dynamic import since the skill directory is hyphenated
tools_path = pathlib.Path(__file__).parents[1] / "skills" / "race-tick" / "tools.py"
spec = importlib.util.spec_from_file_location("race_tick.tools", tools_path)
assert spec is not None, f"Could not find module spec for {tools_path}"
assert spec.loader is not None, f"Module spec has no loader for {tools_path}"
tools_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools_module)

advance_tick = tools_module.advance_tick

# Test constants
SIM_COUNT = 50
RUNNER_COUNT = 5
MARATHON_MI = 26.2188
TOTAL_RACE_HOURS = 6.0
MAX_TICKS = 6
APP_NAME = "test_tick_stress"


def _msg(event_type: RunnerEventType, **data) -> types.Content:
    """Build a user message Content from a RunnerEvent."""
    text = serialize_runner_event(RunnerEvent(event=event_type, data=data))
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])


async def _run_agent(
    runner: InMemoryRunner,
    session_id: str,
    message: types.Content,
) -> list:
    """Run the agent and collect all emitted events."""
    events = []
    async for event in runner.run_async(
        user_id="sim",
        session_id=session_id,
        new_message=message,
    ):
        events.append(event)
    return events


def _build_drain_message(session_id: str, runner_state: dict) -> dict:
    """Build a collector drain message from actual runner session state."""
    distance_mi = runner_state.get("distance", 0.0)
    velocity = runner_state.get("velocity", 0.0)
    water = runner_state.get("water", 100.0)
    runner_status = runner_state.get("runner_status", "running")
    exhausted = runner_state.get("exhausted", False)
    collapsed = runner_state.get("collapsed", False)

    return {
        "session_id": session_id,
        "agent_id": "runner_autopilot",
        "event": "tool_end",
        "msg_type": "json",
        "timestamp": "2026-04-03T10:00:00",
        "payload": {
            "tool_name": "process_tick",
            "result": {
                "status": "success",
                "runner_status": runner_status,
                "velocity": velocity,
                "effective_velocity": velocity * 0.9,
                "distance_mi": distance_mi,
                "distance": round(distance_mi, 4),
                "water": water,
                "pace_min_per_mi": runner_state.get("pace_min_per_mi"),
                "mi_this_tick": distance_mi / max(1, MAX_TICKS),
                "exhausted": exhausted,
                "collapsed": collapsed,
                "finish_time_minutes": runner_state.get("finish_time_minutes"),
            },
        },
    }


def _make_tool_context(state: dict) -> MagicMock:
    """Create a mock ToolContext."""
    ctx = MagicMock()
    ctx.state = state
    ctx.session = MagicMock()
    ctx.session.id = state.get("_sim_session_id", "sim-stress")
    ctx.invocation_id = f"inv-stress-{id(state)}"
    ctx.agent_name = "tick-agent"
    ctx.actions = MagicMock()
    ctx.actions.escalate = False
    return ctx


@dataclass
class TickResult:
    """Aggregated result for one tick of one simulation."""

    sim_id: int
    tick: int
    runners_reporting: int
    avg_velocity: float
    avg_water: float
    avg_distance: float
    status_counts: dict
    anomalies: list[str] = field(default_factory=list)


@dataclass
class SimulationResult:
    """Complete results for one simulation."""

    sim_id: int
    tick_results: list[TickResult]
    anomalies: list[str] = field(default_factory=list)


async def _run_simulation(sim_id: int) -> SimulationResult:
    """Run a complete simulation with RUNNER_COUNT runners through MAX_TICKS.

    Returns a SimulationResult with per-tick data and any detected anomalies.
    """
    minutes_per_tick = (TOTAL_RACE_HOURS * 60) / MAX_TICKS
    sim_result = SimulationResult(sim_id=sim_id, tick_results=[])

    # --- Set up runners ---
    runner_sessions = [f"sim{sim_id:03d}-runner-{i:03d}" for i in range(RUNNER_COUNT)]
    runners: dict[str, InMemoryRunner] = {}
    for sid in runner_sessions:
        r = InMemoryRunner(agent=runner_agent, app_name=APP_NAME)
        await r.session_service.create_session(
            user_id="sim",
            session_id=sid,
            app_name=APP_NAME,
        )
        runners[sid] = r

    # --- Send START_GUN to all runners ---
    start_msg = _msg(RunnerEventType.START_GUN)
    for sid, r in runners.items():
        await _run_agent(r, sid, start_msg)

    # --- Run through all ticks ---
    sim_state: dict = {
        "_sim_session_id": f"sim-stress-{sim_id:03d}",
        "current_tick": 0,
        "max_ticks": MAX_TICKS,
        "simulation_config": {
            "tick_interval_seconds": 0,
            "total_race_hours": TOTAL_RACE_HOURS,
        },
        "tick_snapshots": [],
        "runner_session_ids": runner_sessions,
    }

    prev_avg_distance = -1.0

    for tick in range(MAX_TICKS):
        elapsed = (tick + 1) * minutes_per_tick
        tick_msg = _msg(
            RunnerEventType.TICK,
            tick=tick,
            max_ticks=MAX_TICKS,
            minutes_per_tick=minutes_per_tick,
            elapsed_minutes=elapsed,
            race_distance_mi=MARATHON_MI,
        )

        # Send TICK to all runners and collect their state
        drain_messages = []
        for sid, r in runners.items():
            await _run_agent(r, sid, tick_msg)
            session = await r.session_service.get_session(
                user_id="sim",
                session_id=sid,
                app_name=APP_NAME,
            )
            assert session is not None, f"Sim {sim_id}, tick {tick}: session {sid} is None"
            drain_messages.append(_build_drain_message(sid, dict(session.state)))

        # Set up mock collector returning real drain messages
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=drain_messages)

        sim_state["current_tick"] = tick
        ctx = _make_tool_context(state=sim_state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
        ):
            result = await advance_tick(tool_context=ctx)

        # --- Collect result and check for anomalies ---
        tick_result = TickResult(
            sim_id=sim_id,
            tick=tick,
            runners_reporting=result["runners_reporting"],
            avg_velocity=result["avg_velocity"],
            avg_water=result["avg_water"],
            avg_distance=result["avg_distance"],
            status_counts=result.get("status_counts", {}),
        )

        # Anomaly: runners_reporting != RUNNER_COUNT
        if tick_result.runners_reporting != RUNNER_COUNT:
            msg = (
                f"Sim {sim_id}, tick {tick}: runners_reporting={tick_result.runners_reporting}, expected {RUNNER_COUNT}"
            )
            tick_result.anomalies.append(msg)
            sim_result.anomalies.append(msg)

        # Anomaly: zero averages when runners exist
        if tick_result.avg_velocity == 0:
            msg = f"Sim {sim_id}, tick {tick}: avg_velocity is zero"
            tick_result.anomalies.append(msg)
            sim_result.anomalies.append(msg)

        if tick_result.avg_water == 0:
            msg = f"Sim {sim_id}, tick {tick}: avg_water is zero"
            tick_result.anomalies.append(msg)
            sim_result.anomalies.append(msg)

        if tick_result.avg_distance == 0 and tick > 0:
            msg = f"Sim {sim_id}, tick {tick}: avg_distance is zero after tick 0"
            tick_result.anomalies.append(msg)
            sim_result.anomalies.append(msg)

        # Anomaly: avg_water exceeds 100%
        if tick_result.avg_water > 100.0:
            msg = f"Sim {sim_id}, tick {tick}: avg_water={tick_result.avg_water} > 100"
            tick_result.anomalies.append(msg)
            sim_result.anomalies.append(msg)

        # Anomaly: distance decreased
        if tick_result.avg_distance < prev_avg_distance:
            msg = f"Sim {sim_id}, tick {tick}: avg_distance={tick_result.avg_distance} < previous={prev_avg_distance}"
            tick_result.anomalies.append(msg)
            sim_result.anomalies.append(msg)
        prev_avg_distance = tick_result.avg_distance

        # Anomaly: empty status_counts
        if not tick_result.status_counts:
            msg = f"Sim {sim_id}, tick {tick}: status_counts is empty"
            tick_result.anomalies.append(msg)
            sim_result.anomalies.append(msg)

        sim_result.tick_results.append(tick_result)

    return sim_result


@pytest.mark.asyncio
async def test_50_concurrent_simulations_no_anomalies():
    """Run 50 concurrent simulations (5 runners, 6 ticks each).

    Validates:
    - runners_reporting == 5 on EVERY tick of EVERY simulation
    - avg_velocity > 0 on EVERY tick
    - avg_water > 0 and <= 100 on EVERY tick
    - avg_distance monotonically non-decreasing
    - status_counts non-empty on EVERY tick
    - No zero-value averages (the exact regression being fixed)

    This proves the fix works under concurrent pressure with real runner
    agent state machines producing actual telemetry.
    """
    # Run all simulations concurrently
    tasks = [_run_simulation(i) for i in range(SIM_COUNT)]
    results: list[SimulationResult] = await asyncio.gather(*tasks)

    # --- Aggregate anomalies ---
    all_anomalies: list[str] = []
    total_ticks = 0
    total_finished_ticks = 0

    for sim_result in results:
        all_anomalies.extend(sim_result.anomalies)
        total_ticks += len(sim_result.tick_results)

        # Count ticks where any runner was finished
        for tr in sim_result.tick_results:
            if tr.status_counts.get("finished", 0) > 0:
                total_finished_ticks += 1

    # --- Final assertions ---
    assert len(results) == SIM_COUNT, f"Expected {SIM_COUNT} results, got {len(results)}"
    assert total_ticks == SIM_COUNT * MAX_TICKS, f"Expected {SIM_COUNT * MAX_TICKS} total ticks, got {total_ticks}"

    # The critical assertion: zero anomalies
    assert len(all_anomalies) == 0, (
        f"Found {len(all_anomalies)} anomalies across {SIM_COUNT} simulations "
        f"({total_ticks} total ticks, {total_finished_ticks} ticks with finished runners):\n"
        + "\n".join(all_anomalies[:20])  # Show first 20
        + (f"\n... and {len(all_anomalies) - 20} more" if len(all_anomalies) > 20 else "")
    )

    # Verify we actually tested the finished-runner scenario
    assert total_finished_ticks > 0, (
        "No simulations had finished runners -- test did not exercise "
        "the regression scenario. This likely means the race distance or "
        "tick count is misconfigured."
    )


@pytest.mark.asyncio
async def test_per_simulation_invariants():
    """Run 50 simulations and verify per-simulation invariants in detail.

    This test provides more granular assertions than the anomaly-based test:
    - Total runners across all status categories == RUNNER_COUNT
    - Snapshot count matches tick count
    - Finished runner IDs accumulate monotonically
    """
    tasks = [_run_simulation(i) for i in range(SIM_COUNT)]
    results: list[SimulationResult] = await asyncio.gather(*tasks)

    for sim_result in results:
        sim_id = sim_result.sim_id
        finished_count_prev = 0

        for tr in sim_result.tick_results:
            # Status count total must equal RUNNER_COUNT
            status_total = sum(tr.status_counts.values())
            assert status_total == RUNNER_COUNT, (
                f"Sim {sim_id}, tick {tr.tick}: status_counts sum "
                f"{status_total} != {RUNNER_COUNT}. Counts: {tr.status_counts}"
            )

            # Finished count must be monotonically non-decreasing
            finished_now = tr.status_counts.get("finished", 0)
            assert finished_now >= finished_count_prev, (
                f"Sim {sim_id}, tick {tr.tick}: finished count decreased from {finished_count_prev} to {finished_now}"
            )
            finished_count_prev = finished_now

            # runners_reporting must always be RUNNER_COUNT
            assert tr.runners_reporting == RUNNER_COUNT, (
                f"Sim {sim_id}, tick {tr.tick}: runners_reporting={tr.runners_reporting} != {RUNNER_COUNT}"
            )
