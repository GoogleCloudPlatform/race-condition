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

"""End-to-end simulation test using real Gemini models via the ADK Runner.

Proves the full pipeline: route planning → traffic assessment → simulation
tick loop using the LoopAgent + tick_agent with REAL LLM function calling.

Phase 1-2 call tool functions directly (no LLM needed).
Phase 3 runs the race_engine (LoopAgent wrapping tick_agent) through
InMemoryRunner with real Gemini model calls, proving the LLM reliably
generates function calls on EVERY tick iteration despite history accumulation.

Marked as 'slow' and 'integration' because it makes real API calls to Gemini.
"""

import importlib.util
import json
import logging
import pathlib

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from google.adk.runners import InMemoryRunner
from google.genai import types

# Test constants -- realistic simulation: 60s duration, 10s per tick = 6 ticks
MAX_TICKS = 6
RUNNER_COUNT = 3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dynamic imports for hyphenated skill directories
# ---------------------------------------------------------------------------
_AGENTS_DIR = pathlib.Path(__file__).parent.parent

# gis-spatial-engineering tools (planner)
_gis_tools_path = _AGENTS_DIR / "planner" / "skills" / "gis-spatial-engineering" / "scripts" / "tools.py"
_gis_spec = importlib.util.spec_from_file_location("gis_spatial_engineering.tools", _gis_tools_path)
assert _gis_spec is not None and _gis_spec.loader is not None
gis_tools = importlib.util.module_from_spec(_gis_spec)
_gis_spec.loader.exec_module(gis_tools)

# pre-race tools (simulator)
_pre_race_path = _AGENTS_DIR / "simulator" / "skills" / "pre-race" / "tools.py"
_pre_spec = importlib.util.spec_from_file_location("pre_race.tools", _pre_race_path)
assert _pre_spec is not None and _pre_spec.loader is not None
pre_race_tools = importlib.util.module_from_spec(_pre_spec)
_pre_spec.loader.exec_module(pre_race_tools)


def _make_tool_context(state: dict | None = None) -> MagicMock:
    """Build a mock ToolContext with mutable state dict."""
    tc = MagicMock()
    tc.state = state if state is not None else {}
    tc.session.id = "e2e-test-session"
    tc.actions = MagicMock()
    return tc


def _make_collector_drain_response(tick: int) -> list[dict]:
    """Build fake collector drain output for a given tick.

    Returns messages shaped like the RaceCollector's Redis buffer output:
    each entry has session_id, payload with tool_name="process_tick" and
    result dict containing velocity, water, distance_mi, runner_status.
    """
    return [
        {
            "session_id": f"runner-{i}",
            "agent_id": f"runner-agent-{i}",
            "event": "tool_end",
            "msg_type": "json",
            "timestamp": "",
            "payload": {
                "tool_name": "process_tick",
                "result": {
                    "velocity": 0.85 + (i * 0.05),
                    "water": max(10.0, 80.0 - (tick * 3)),
                    "distance_mi": (tick + 1) * 2.18,
                    "distance": (tick + 1) * 2.18,
                    "runner_status": "running",
                    "notable_event": None,
                },
            },
        }
        for i in range(RUNNER_COUNT)
    ]


@pytest.mark.slow
@pytest.mark.integration
class TestEndToEndSimulation:
    """Full pipeline test: plan route → assess traffic → simulate ticks via ADK Runner."""

    @pytest.mark.asyncio
    async def test_full_simulation_pipeline_with_runner(self):
        # ==================================================================
        # Phase 1: Plan a route using the REAL planner tools (no LLM)
        # ==================================================================
        plan_marathon_route = gis_tools.plan_marathon_route

        tc_planner = _make_tool_context()

        route_result = await plan_marathon_route(
            petal_names=[
                "west-flamingo-jones",
                "north-sahara-rainbow",
                "south-tropicana-vv-sunset",
            ],
            tool_context=tc_planner,
        )

        # Assert: route generated successfully
        assert route_result["status"] == "success", f"plan_marathon_route failed: {route_result.get('message')}"
        route_geojson = route_result["geojson"]
        assert route_geojson["type"] == "FeatureCollection"

        # Verify LineString features exist
        linestrings = [f for f in route_geojson["features"] if f.get("geometry", {}).get("type") == "LineString"]
        assert len(linestrings) > 0, "Route has no LineString features"

        # ==================================================================
        # Phase 1b: Assess traffic impact (mock Gemini enrichment)
        # ==================================================================
        assess_traffic_impact = gis_tools.assess_traffic_impact

        mock_enrichment = {
            "narrative": "Test narrative: marathon closures cause moderate congestion.",
            "congestion_zones": [
                {"zone_name": "Strip North", "severity": "high"},
                {"zone_name": "Flamingo Corridor", "severity": "medium"},
            ],
        }

        with patch.object(
            gis_tools,
            "_gemini_traffic_enrichment",
            new_callable=AsyncMock,
            return_value=mock_enrichment,
        ):
            traffic_result = await assess_traffic_impact(tool_context=tc_planner)

        assert traffic_result["status"] == "success", f"assess_traffic_impact failed: {traffic_result.get('message')}"
        assert isinstance(traffic_result["closed_segments"], list)
        # closed_segments excludes route-coincident segments (route lines).
        # Collateral closures may or may not exist depending on the route/network.
        # The impact score should still reflect the full closure impact.
        assert traffic_result["overall_impact_score"] > 0, "Impact score should be positive when route closes roads"

        # ==================================================================
        # Phase 2: Simulation setup — prepare_simulation (direct tool call)
        # ==================================================================
        prepare_simulation = pre_race_tools.prepare_simulation

        tc_sim = _make_tool_context(state={"simulation_id": "e2e-test-sim"})

        plan_payload = {
            "action": "execute",
            "narrative": "E2E test marathon simulation",
            "route": route_geojson,
            "traffic_assessment": traffic_result,
            "simulation_config": {
                "duration_seconds": MAX_TICKS * 1,  # 1 second per tick
                "tick_interval_seconds": 1,
                "total_race_hours": 6.0,
                "runner_count": RUNNER_COUNT,
            },
        }

        with patch(
            "agents.utils.simdata.load_simulation_data",
            new_callable=AsyncMock,
            return_value={"route_geojson": None, "traffic_assessment": None},
        ):
            prep_result = await prepare_simulation(
                plan_json=json.dumps(plan_payload),
                tool_context=tc_sim,
            )

        assert prep_result["status"] == "success", f"prepare_simulation failed: {prep_result.get('message')}"
        assert prep_result["max_ticks"] == MAX_TICKS
        assert prep_result["runner_count"] == RUNNER_COUNT

        # Verify traffic model was built
        traffic_model = tc_sim.state.get("traffic_model")
        assert traffic_model is not None, "traffic_model not built in state"
        segment_index = traffic_model.get("segment_index", [])
        assert len(segment_index) > 0, "segment_index is empty — route should produce segments"

        # ==================================================================
        # Phase 3: Tick execution — REAL LLM via ADK Runner (LoopAgent)
        # ==================================================================
        # Import the race_engine (LoopAgent wrapping tick_agent) from the
        # simulator agent module.
        from agents.simulator.agent import race_engine

        runner = InMemoryRunner(agent=race_engine, app_name="e2e_test")

        # Pre-populate session state with all data from Phase 1-2.
        # We pre-create the session with state since InMemoryRunner
        # does not auto-create sessions by default.
        initial_state = {
            "current_tick": 0,
            "max_ticks": MAX_TICKS,
            "simulation_config": {
                "tick_interval_seconds": 0,  # No wait in test
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": [f"runner-{i}" for i in range(RUNNER_COUNT)],
            "simulation_id": "e2e-test-sim",
            "simulation_ready": True,
            "route_geojson": route_geojson,
            "traffic_model": traffic_model,
        }

        await runner.session_service.create_session(
            app_name="e2e_test",
            user_id="e2e",
            session_id="e2e-session",
            state=initial_state,
        )

        # Build a drain side_effect that returns fresh data for each tick.
        # The advance_tick tool drains once per tick (assuming all runners
        # report on first drain). We make MAX_TICKS batches.
        drain_call_count = 0

        async def _drain_side_effect():
            nonlocal drain_call_count
            tick = drain_call_count
            drain_call_count += 1
            return _make_collector_drain_response(tick)

        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(side_effect=_drain_side_effect)

        # Patch infrastructure dependencies at the module level where the
        # tools import them.
        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch(
                "agents.simulator.broadcast.publish_to_runners",
                new_callable=AsyncMock,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(
                "agents.utils.pulses.emit_gateway_message",
                new_callable=AsyncMock,
            ),
        ):
            # Run the LoopAgent through the ADK Runner.
            # The LoopAgent will iterate, running tick_agent on each iteration.
            # The LLM should call advance_tick then check_race_complete each tick.
            # On the final tick, check_race_complete escalates to end the loop.
            events = []
            async for event in runner.run_async(
                user_id="e2e",
                session_id="e2e-session",
                new_message=types.Content(
                    role="user",
                    parts=[types.Part(text="Start the race simulation.")],
                ),
            ):
                events.append(event)

        # ==================================================================
        # Assertions on the collected events
        # ==================================================================

        # Collect all function calls and function responses from events.
        all_function_calls: list[str] = []
        advance_tick_responses: list[dict] = []
        check_race_complete_responses: list[dict] = []
        escalate_seen = False

        for event in events:
            # Collect function calls (LLM decided to call these tools)
            for fc in event.get_function_calls():
                all_function_calls.append(fc.name)
                logger.info("Function call: %s", fc.name)

            # Collect function responses (tool return values)
            for fr in event.get_function_responses():
                if fr.name == "advance_tick":
                    response_data = fr.response
                    if isinstance(response_data, dict):
                        advance_tick_responses.append(response_data)
                    logger.info("advance_tick response: %s", response_data)
                elif fr.name == "check_race_complete":
                    response_data = fr.response
                    if isinstance(response_data, dict):
                        check_race_complete_responses.append(response_data)
                    logger.info("check_race_complete response: %s", response_data)

            # Check for escalation events
            if event.actions and event.actions.escalate:
                escalate_seen = True

        # Log all function calls for debugging
        logger.info("All function calls: %s", all_function_calls)
        logger.info("advance_tick responses count: %d", len(advance_tick_responses))
        logger.info("check_race_complete responses count: %d", len(check_race_complete_responses))

        # ------------------------------------------------------------------
        # Assertion 1: Route planning produced valid GeoJSON with LineStrings
        # (already asserted in Phase 1)
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # Assertion 2: Traffic assessment identified closed segments
        # (already asserted in Phase 1b)
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # Assertion 3: Traffic model has segment_index entries
        # (already asserted in Phase 2)
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # Assertion 4: For EACH tick, LLM generated function calls
        # ------------------------------------------------------------------

        # 4a: Total advance_tick function calls == MAX_TICKS
        advance_tick_call_count = all_function_calls.count("advance_tick")
        assert advance_tick_call_count == MAX_TICKS, (
            f"Expected {MAX_TICKS} advance_tick function calls, "
            f"got {advance_tick_call_count}. All calls: {all_function_calls}"
        )

        # 4b: Each advance_tick response has runners_reporting == RUNNER_COUNT
        for i, resp in enumerate(advance_tick_responses):
            assert resp.get("runners_reporting") == RUNNER_COUNT, (
                f"Tick {i}: expected {RUNNER_COUNT} runners_reporting, "
                f"got {resp.get('runners_reporting')}. Response: {resp}"
            )

        # 4c: Each advance_tick response has traffic data with coordinates
        for i, resp in enumerate(advance_tick_responses):
            traffic = resp.get("traffic")
            assert traffic is not None, f"Tick {i}: missing 'traffic' key in advance_tick response"
            assert "overall_congestion" in traffic, f"Tick {i}: traffic missing 'overall_congestion'"
            assert "tev_impact" in traffic, f"Tick {i}: traffic missing 'tev_impact'"
            assert "segments" in traffic, f"Tick {i}: traffic missing 'segments'"
            # Each segment must include coordinates for frontend visualization
            for j, seg in enumerate(traffic["segments"]):
                assert "coordinates" in seg, f"Tick {i}, segment {j}: missing 'coordinates' for frontend visualization"
                assert len(seg["coordinates"]) >= 2, f"Tick {i}, segment {j}: coordinates must have at least 2 points"

        # 4d: LLM generated check_race_complete calls each tick
        check_race_call_count = all_function_calls.count("check_race_complete")
        assert check_race_call_count == MAX_TICKS, (
            f"Expected {MAX_TICKS} check_race_complete function calls, "
            f"got {check_race_call_count}. All calls: {all_function_calls}"
        )

        # ------------------------------------------------------------------
        # Assertion 5: On the final tick, check_race_complete set escalate
        # ------------------------------------------------------------------
        assert escalate_seen, "Expected escalate=True on the final tick but never saw it in events"

        # Verify the last check_race_complete response shows race_complete
        assert len(check_race_complete_responses) > 0, "No check_race_complete responses found"
        final_check = check_race_complete_responses[-1]
        assert final_check.get("status") == "race_complete", (
            f"Expected final check_race_complete status='race_complete', got: {final_check}"
        )
