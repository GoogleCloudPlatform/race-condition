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

"""Runner-Simulator integration test.

Validates the data contract between runner process_tick output and
advance_tick aggregation. This test bridges:
- The runner E2E test (test_runner_sim_e2e.py) which drives runners but
  skips the collector
- The advance_tick unit tests (test_tick_tools.py) which mock collector
  drain with hand-written fixtures

Uses real runner agents via InMemoryRunner to generate actual telemetry,
then feeds that through advance_tick with a mock collector.
"""

import importlib.util
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.runner_autopilot.agent import root_agent as runner_agent
from agents.utils.runner_protocol import (
    RunnerEvent,
    RunnerEventType,
    serialize_runner_event,
)

# Dynamic import since the skill directory is hyphenated
tools_path = pathlib.Path(__file__).parents[1] / "skills" / "advancing-race-ticks" / "tools.py"
spec = importlib.util.spec_from_file_location("race_tick.tools", tools_path)
assert spec is not None, f"Could not find module spec for {tools_path}"
assert spec.loader is not None, f"Module spec has no loader for {tools_path}"
tools_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools_module)

advance_tick = tools_module.advance_tick

# Test constants
RUNNER_COUNT = 5
MARATHON_MI = 26.2188
TOTAL_RACE_HOURS = 6.0
MAX_TICKS = 6
APP_NAME = "test_runner_sim_integration"


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


def _make_tool_context(state: dict | None = None) -> MagicMock:
    """Create a mock ToolContext with a mutable state dict and actions."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    ctx.session = MagicMock()
    ctx.session.id = "sim-integration-session"
    ctx.invocation_id = "inv-integration"
    ctx.agent_name = "tick-agent"
    ctx.actions = MagicMock()
    ctx.actions.escalate = False
    return ctx


def _build_drain_message(
    session_id: str,
    runner_state: dict,
) -> dict:
    """Build a collector drain message from actual runner session state.

    Produces the format that RaceCollector._parse_wrapper outputs:
    a tool_end event with process_tick result containing the runner's
    current vitals.

    The runner stores distance in miles in state['distance']. The
    process_tick tool returns distance_mi (miles) and distance (miles).
    We replicate that here.
    """
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
        "timestamp": "2026-03-21T10:00:00",
        "payload": {
            "tool_name": "process_tick",
            "result": {
                "status": "success",
                "runner_status": runner_status,
                "velocity": velocity,
                # Approximation -- not consumed by advance_tick aggregation.
                "effective_velocity": velocity * 0.9,
                "distance_mi": distance_mi,
                "distance": round(distance_mi, 4),
                "water": water,
                "pace_min_per_mi": runner_state.get("pace_min_per_mi"),
                # Approximation -- not consumed by advance_tick aggregation.
                "mi_this_tick": distance_mi / max(1, MAX_TICKS),
                "exhausted": exhausted,
                "collapsed": collapsed,
                "finish_time_minutes": runner_state.get("finish_time_minutes"),
            },
        },
    }


@pytest.mark.slow
@pytest.mark.asyncio
async def test_advance_tick_aggregates_real_runner_output():
    """Run 5 runners through 6 ticks and verify advance_tick aggregation.

    For each tick:
    1. Send TICK event to all runners via InMemoryRunner
    2. Read session state from each runner
    3. Build drain messages from actual state
    4. Call advance_tick with mock collector returning those messages
    5. Assert aggregation invariants
    """
    minutes_per_tick = (TOTAL_RACE_HOURS * 60) / MAX_TICKS

    # --- Setup runners ---
    runner_sessions = [f"runner-int-{i:03d}" for i in range(RUNNER_COUNT)]
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

    # --- Run through ticks, feeding output to advance_tick ---
    prev_avg_distance = -1.0

    # Shared state for the simulator tool context across ticks
    sim_state = {
        "current_tick": 0,
        "max_ticks": MAX_TICKS,
        "simulation_config": {
            "tick_interval_seconds": 0,
            "total_race_hours": TOTAL_RACE_HOURS,
        },
        "tick_snapshots": [],
        "runner_session_ids": runner_sessions,
    }

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
            assert session is not None
            drain_messages.append(_build_drain_message(sid, dict(session.state)))

        # Set up mock collector returning real drain messages
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=drain_messages)

        # Update current_tick in state (advance_tick reads it, then increments)
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

        # --- Per-tick assertions ---
        assert result["runners_reporting"] == RUNNER_COUNT, (
            f"Tick {tick}: expected {RUNNER_COUNT} runners, got {result['runners_reporting']}"
        )

        assert result["avg_velocity"] > 0, f"Tick {tick}: avg_velocity should be positive"

        assert result["avg_water"] <= 100.0, f"Tick {tick}: avg_water {result['avg_water']} exceeds 100"

        # Distance should be monotonically non-decreasing
        assert result["avg_distance"] >= prev_avg_distance, (
            f"Tick {tick}: avg_distance {result['avg_distance']} < previous {prev_avg_distance}"
        )
        prev_avg_distance = result["avg_distance"]

        # Snapshot should have been appended
        assert len(sim_state["tick_snapshots"]) == tick + 1, (
            f"Tick {tick}: expected {tick + 1} snapshots, got {len(sim_state['tick_snapshots'])}"
        )

        # All tick data flows through the return dict (tool_end event)
        assert result["max_ticks"] > 0, f"Tick {tick}: max_ticks missing from result"

        # status_counts should be populated
        assert result["status_counts"], f"Tick {tick}: status_counts is empty"

        # Note: advance_tick already incremented current_tick in sim_state
        # (ctx.state IS sim_state -- same dict reference), so no copy needed.


@pytest.mark.asyncio
async def test_runner_output_format_matches_aggregator_expectations():
    """Verify runner session state contains all fields advance_tick needs.

    Sets up 1 runner, sends START_GUN then 1 TICK, reads session state,
    and asserts all fields that advance_tick aggregation reads are present
    with correct types.
    """
    minutes_per_tick = (TOTAL_RACE_HOURS * 60) / MAX_TICKS

    # Setup single runner
    sid = "runner-format-check"
    r = InMemoryRunner(agent=runner_agent, app_name=APP_NAME)
    await r.session_service.create_session(
        user_id="sim",
        session_id=sid,
        app_name=APP_NAME,
    )

    # Send START_GUN
    start_msg = _msg(RunnerEventType.START_GUN)
    await _run_agent(r, sid, start_msg)

    # Send 1 TICK
    tick_msg = _msg(
        RunnerEventType.TICK,
        tick=0,
        max_ticks=MAX_TICKS,
        minutes_per_tick=minutes_per_tick,
        elapsed_minutes=minutes_per_tick,
        race_distance_mi=MARATHON_MI,
    )
    await _run_agent(r, sid, tick_msg)

    # Read session state
    session = await r.session_service.get_session(
        user_id="sim",
        session_id=sid,
        app_name=APP_NAME,
    )
    assert session is not None
    state = dict(session.state)

    # --- Assert all fields advance_tick reads are present ---

    # velocity: used for avg_velocity aggregation
    assert "velocity" in state, "Missing 'velocity' in runner state"
    assert isinstance(state["velocity"], (int, float)), f"velocity should be numeric, got {type(state['velocity'])}"
    assert state["velocity"] > 0, f"velocity should be positive, got {state['velocity']}"

    # water: used for avg_water aggregation
    assert "water" in state, "Missing 'water' in runner state"
    assert isinstance(state["water"], (int, float)), f"water should be numeric, got {type(state['water'])}"
    assert 0.0 <= state["water"] <= 100.0, f"water out of range: {state['water']}"

    # distance: used (as distance_mi) for avg_distance aggregation
    # Runner stores distance in miles in state
    assert "distance" in state, "Missing 'distance' in runner state"
    assert isinstance(state["distance"], (int, float)), f"distance should be numeric, got {type(state['distance'])}"
    assert state["distance"] > 0, f"distance should be positive after a tick, got {state['distance']}"

    # runner_status: used for status_counts aggregation
    assert "runner_status" in state, "Missing 'runner_status' in runner state"
    assert isinstance(state["runner_status"], str), f"runner_status should be str, got {type(state['runner_status'])}"
    assert state["runner_status"] in {"running", "exhausted", "collapsed", "finished"}, (
        f"unexpected runner_status: {state['runner_status']}"
    )

    # Verify the drain message format works with these values
    drain_msg = _build_drain_message(sid, state)
    result = drain_msg["payload"]["result"]

    # advance_tick reads these specific keys from result:
    assert "velocity" in result, "Drain message missing 'velocity'"
    assert "water" in result, "Drain message missing 'water'"
    assert "distance_mi" in result, "Drain message missing 'distance_mi'"
    assert "runner_status" in result, "Drain message missing 'runner_status'"

    # Values should be positive where expected
    assert result["velocity"] > 0, f"Drain velocity should be positive: {result['velocity']}"
    assert result["water"] > 0, f"Drain water should be positive: {result['water']}"
    assert result["distance_mi"] > 0, f"Drain distance_mi should be positive: {result['distance_mi']}"
