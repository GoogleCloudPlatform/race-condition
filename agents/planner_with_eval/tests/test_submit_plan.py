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

"""Tests for start_simulation and submit_plan_to_simulator tools."""

import asyncio
import json
import re
from unittest.mock import MagicMock, patch

import pytest

from agents.planner_with_eval.tools import start_simulation, submit_plan_to_simulator

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _make_tool_context(state: dict | None = None) -> MagicMock:
    """Create a mock ToolContext with a mutable state dict."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    ctx.session = MagicMock()
    ctx.session.id = "planner-session-1"
    ctx.invocation_id = "inv-001"
    ctx.agent_name = "planner_with_eval"
    return ctx


class TestSubmitPlanPayload:
    """Verify the A2A payload is small (route/traffic go via Redis side-channel)."""

    @pytest.mark.asyncio
    async def test_payload_excludes_route_geojson(self):
        """Route GeoJSON goes via Redis side-channel, NOT in the A2A payload.

        The simulator's prepare_simulation reads it from Redis using
        load_simulation_data(). Keeping the payload small prevents LLM
        function-call JSON corruption.
        """
        route = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Las Vegas Blvd"},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-115.17, 36.08], [-115.17, 36.09]],
                    },
                }
            ],
        }

        ctx = _make_tool_context(state={"marathon_route": route})
        captured_message = None

        async def capture_call_agent(**kwargs):
            nonlocal captured_message
            captured_message = kwargs.get("message")
            return "Simulator acknowledged"

        with (
            patch(
                "agents.utils.communication.call_agent",
                side_effect=capture_call_agent,
            ),
            patch(
                "agents.utils.simdata.store_simulation_data",
                new_callable=lambda: __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=True),
            ),
        ):
            result = await submit_plan_to_simulator(
                action="execute",
                message="Run the Strip Classic marathon",
                tool_context=ctx,
            )

        assert result["status"] == "success"
        assert captured_message is not None

        payload = json.loads(captured_message)

        assert "route" not in payload, "Route should go via Redis, NOT in A2A payload"
        assert "traffic_assessment" not in payload, "Traffic should go via Redis, NOT in A2A payload"
        assert payload["action"] == "execute"
        assert "narrative" in payload

    @pytest.mark.asyncio
    async def test_stores_simulation_data_in_redis(self):
        """submit_plan_to_simulator must call store_simulation_data before the A2A call."""
        route = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0]]}, "properties": {}}
            ],
        }
        traffic = {"overall_rating": "A"}
        ctx = _make_tool_context(state={"marathon_route": route, "traffic_assessment": traffic})

        from unittest.mock import AsyncMock as AM

        mock_store = AM(return_value=True)

        with (
            patch(
                "agents.utils.communication.call_agent",
                return_value="ack",
            ),
            patch(
                "agents.utils.simdata.store_simulation_data",
                mock_store,
            ),
        ):
            result = await submit_plan_to_simulator(
                action="execute",
                message="Run it",
                tool_context=ctx,
            )

        assert result["status"] == "success"
        mock_store.assert_called_once()
        call_kwargs = mock_store.call_args[1]
        assert call_kwargs["route_geojson"] == route
        assert call_kwargs["traffic_assessment"] == traffic
        assert call_kwargs["simulation_id"] == ctx.state["simulator_session_id"]

    @pytest.mark.asyncio
    async def test_returns_error_without_marathon_route(self):
        """If no marathon_route in state, should return an error."""
        ctx = _make_tool_context(state={})

        result = await submit_plan_to_simulator(
            action="execute",
            message="Run the marathon",
            tool_context=ctx,
        )

        assert result["status"] == "error"
        assert "No marathon route" in result["message"]


class TestSimulatorSessionLifecycle:
    """Verify simulator session ID is created, reused, and voided correctly."""

    ROUTE_STATE = {
        "marathon_route": {"type": "FeatureCollection", "features": []},
    }

    @pytest.mark.asyncio
    async def test_creates_simulator_session_if_absent(self):
        """A UUID4 session_id is generated and stored when none exists."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        with patch(
            "agents.utils.communication.call_agent",
            return_value="ack",
        ):
            await submit_plan_to_simulator(
                action="verify",
                message="check plan",
                tool_context=ctx,
            )

        sid = ctx.state.get("simulator_session_id")
        assert sid is not None, "simulator_session_id must be stored in state"
        assert UUID_RE.match(sid), f"Expected UUID4, got: {sid}"

    @pytest.mark.asyncio
    async def test_reuses_existing_simulator_session(self):
        """An existing session_id in state must be reused, not regenerated."""
        existing_id = "existing-session-abc"
        ctx = _make_tool_context(
            state={**self.ROUTE_STATE, "simulator_session_id": existing_id},
        )

        with patch(
            "agents.utils.communication.call_agent",
            return_value="ack",
        ):
            await submit_plan_to_simulator(
                action="verify",
                message="check plan",
                tool_context=ctx,
            )

        assert ctx.state["simulator_session_id"] == existing_id

    @pytest.mark.asyncio
    async def test_preserves_session_after_execute(self):
        """After action='execute', simulator_session_id must persist for plugin callbacks."""
        ctx = _make_tool_context(
            state={**self.ROUTE_STATE, "simulator_session_id": "sess-123"},
        )

        with patch(
            "agents.utils.communication.call_agent",
            return_value="ack",
        ):
            await submit_plan_to_simulator(
                action="execute",
                message="run it",
                tool_context=ctx,
            )

        assert ctx.state["simulator_session_id"] == "sess-123"

    @pytest.mark.asyncio
    async def test_keeps_session_after_verify(self):
        """After action='verify', simulator_session_id must NOT be voided."""
        ctx = _make_tool_context(
            state={**self.ROUTE_STATE, "simulator_session_id": "sess-456"},
        )

        with patch(
            "agents.utils.communication.call_agent",
            return_value="ack",
        ):
            await submit_plan_to_simulator(
                action="verify",
                message="check plan",
                tool_context=ctx,
            )

        assert ctx.state["simulator_session_id"] == "sess-456"

    @pytest.mark.asyncio
    async def test_passes_session_id_to_call_agent(self):
        """The session_id kwarg must be forwarded to call_agent()."""
        ctx = _make_tool_context(
            state={**self.ROUTE_STATE, "simulator_session_id": "sess-forward"},
        )
        captured_kwargs = {}

        async def capture_call(**kwargs):
            captured_kwargs.update(kwargs)
            return "ack"

        with patch(
            "agents.utils.communication.call_agent",
            side_effect=capture_call,
        ):
            await submit_plan_to_simulator(
                action="verify",
                message="check plan",
                tool_context=ctx,
            )

        assert captured_kwargs.get("session_id") == "sess-forward", (
            f"Expected session_id='sess-forward', got: {captured_kwargs.get('session_id')}"
        )

    @pytest.mark.asyncio
    async def test_verify_does_not_set_simulation_id(self):
        """verify must NOT set simulation_id — it would poison the frontend.

        Setting simulation_id during verify causes the simulator's internal
        events to arrive at the frontend with an unknown session + the new
        simulation_id. The frontend's session filter sees unknown session +
        no subscribed sim, calls unsubscribeSimulation, and the gateway Hub
        stops delivering all subsequent messages with that simulation_id.
        """
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        with patch(
            "agents.utils.communication.call_agent",
            return_value="ack",
        ):
            await submit_plan_to_simulator(
                action="verify",
                message="check plan",
                tool_context=ctx,
            )

        assert ctx.state.get("simulation_id") is None, (
            "simulation_id must NOT be set during verify — only during execute"
        )

    @pytest.mark.asyncio
    async def test_execute_sets_simulation_id_in_planner_state(self):
        """simulation_id must be set in planner state during execute for plugin emission."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        with patch(
            "agents.utils.communication.call_agent",
            return_value="ack",
        ):
            await submit_plan_to_simulator(
                action="execute",
                message="run it",
                tool_context=ctx,
            )

        sim_id = ctx.state.get("simulation_id")
        assert sim_id is not None, "simulation_id must be set during execute"
        assert sim_id == ctx.state["simulator_session_id"]

    @pytest.mark.asyncio
    async def test_simulation_id_persists_after_execute(self):
        """simulation_id must remain in state after execute for plugin callbacks.

        Regression test: a finally block used to clear simulation_id before
        ADK's after_tool_callback fired, causing tool_end events to lose
        their simulation_id.  The fix removes the finally block so the
        DashLogPlugin can still read simulation_id from session state.
        """
        ctx = _make_tool_context(
            state={
                **self.ROUTE_STATE,
                "simulator_session_id": "sess-xyz",
                "simulation_id": "sess-xyz",
            },
        )

        with patch(
            "agents.utils.communication.call_agent",
            return_value="ack",
        ):
            await submit_plan_to_simulator(
                action="execute",
                message="run it",
                tool_context=ctx,
            )

        assert ctx.state["simulation_id"] == "sess-xyz", (
            "simulation_id must persist after execute so DashLogPlugin can include it in tool_end events"
        )
        assert ctx.state["simulator_session_id"] == "sess-xyz", (
            "simulator_session_id must persist after execute — "
            "session belongs to the simulation lifecycle, not a single tool call"
        )


class TestStartSimulation:
    """Verify the start_simulation tool initializes a simulation session."""

    ROUTE_STATE = {
        "marathon_route": {"type": "FeatureCollection", "features": []},
    }

    @pytest.mark.asyncio
    async def test_start_simulation_returns_simulation_id(self):
        """start_simulation must return a dict with status='ready' and a simulation_id."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        result = await start_simulation(
            action="execute",
            message="Run the marathon",
            tool_context=ctx,
        )

        assert result["status"] == "ready"
        assert result["simulation_id"] is not None
        assert UUID_RE.match(result["simulation_id"])
        assert result["action"] == "execute"

    @pytest.mark.asyncio
    async def test_start_simulation_sets_state(self):
        """start_simulation must set simulator_session_id and simulation_id in state."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        result = await start_simulation(
            action="execute",
            message="Run the marathon",
            tool_context=ctx,
        )

        assert ctx.state["simulator_session_id"] == result["simulation_id"]
        assert ctx.state["simulation_id"] == result["simulation_id"]

    @pytest.mark.asyncio
    async def test_start_simulation_generates_fresh_session(self):
        """start_simulation must generate a fresh session_id."""
        existing_id = "existing-session-abc"
        ctx = _make_tool_context(
            state={**self.ROUTE_STATE, "simulator_session_id": existing_id},
        )
        # Use a different invocation_id so the guard doesn't block
        ctx.invocation_id = "inv-fresh"

        result = await start_simulation(
            action="execute",
            message="Run the marathon",
            tool_context=ctx,
        )

        assert result["simulation_id"] != existing_id
        assert UUID_RE.match(result["simulation_id"])
        assert ctx.state["simulator_session_id"] == result["simulation_id"]

    @pytest.mark.asyncio
    async def test_start_simulation_requires_route(self):
        """start_simulation must return error without marathon_route in state."""
        ctx = _make_tool_context(state={})

        result = await start_simulation(
            action="execute",
            message="Run the marathon",
            tool_context=ctx,
        )

        assert result["status"] == "error"
        assert "No marathon route" in result["message"]

    @pytest.mark.asyncio
    async def test_parallel_dispatch_submit_waits_for_start(self):
        """When both tools run in parallel, submit must use start's simulation_id."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        async def delayed_start():
            await asyncio.sleep(0.3)
            return await start_simulation(
                action="execute",
                message="Run the marathon",
                tool_context=ctx,
                simulation_config={"runner_count": 10},
            )

        async def submit():
            async def capture_call_agent(**kwargs):
                return "Simulator acknowledged"

            with (
                patch("agents.utils.communication.call_agent", side_effect=capture_call_agent),
                patch(
                    "agents.utils.simdata.store_simulation_data",
                    new_callable=lambda: __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
                        return_value=True
                    ),
                ),
            ):
                return await submit_plan_to_simulator(
                    action="execute",
                    message="Run the marathon",
                    tool_context=ctx,
                )

        # submit starts immediately, start is delayed 0.3s
        submit_result, start_result = await asyncio.gather(submit(), delayed_start())

        # Both must use the same simulation_id (from start_simulation)
        assert start_result["simulation_id"] == submit_result["simulation_id"]

    @pytest.mark.asyncio
    async def test_two_tool_flow_preserves_simulation_id(self):
        """The start→submit two-tool flow must use the same simulation_id throughout."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        # Step 1: start_simulation initializes session
        start_result = await start_simulation(
            action="execute",
            message="Run the marathon",
            tool_context=ctx,
            simulation_config={"runner_count": 10},
        )
        canonical_id = start_result["simulation_id"]

        # Step 2: submit_plan_to_simulator uses the same session
        captured_kwargs: dict = {}

        async def capture_call_agent(**kwargs):
            captured_kwargs.update(kwargs)
            return "Simulator acknowledged"

        with patch(
            "agents.utils.communication.call_agent",
            side_effect=capture_call_agent,
        ):
            submit_result = await submit_plan_to_simulator(
                action="execute",
                message="Run the marathon",
                tool_context=ctx,
                simulation_config={"runner_count": 10},
            )

        assert submit_result["status"] == "success"
        assert submit_result["simulation_id"] == canonical_id
        assert captured_kwargs["session_id"] == canonical_id

    @pytest.mark.asyncio
    async def test_submit_calls_start_simulation_when_not_called(self):
        """If start_simulation was skipped, submit_plan_to_simulator calls it internally."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})
        captured_message = None

        async def capture_call_agent(**kwargs):
            nonlocal captured_message
            captured_message = kwargs.get("message")
            return "Simulator acknowledged"

        with (
            patch(
                "agents.utils.communication.call_agent",
                side_effect=capture_call_agent,
            ),
            patch(
                "agents.utils.simdata.store_simulation_data",
                new_callable=lambda: __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=True),
            ),
        ):
            result = await submit_plan_to_simulator(
                action="execute",
                message="Run the marathon",
                tool_context=ctx,
                simulation_config={"runner_count": 5},
            )

        assert result["status"] == "success"
        assert result["simulation_id"] is not None
        # start_simulation was called internally, so simulation_id must be in state
        assert ctx.state.get("simulation_id") == result["simulation_id"]
        assert ctx.state.get("simulator_session_id") == result["simulation_id"]
        # Payload should be constructed fresh
        assert captured_message is not None
        payload = json.loads(captured_message)
        assert payload["action"] == "execute"
        assert payload["simulation_config"] == {"runner_count": 5}

    @pytest.mark.asyncio
    async def test_start_simulation_stores_simulation_config_in_state(self):
        """start_simulation must persist simulation_config in session state."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        await start_simulation(
            action="execute",
            message="Run the marathon",
            tool_context=ctx,
            simulation_config={"runner_count": 1},
        )

        assert ctx.state.get("simulation_config") == {"runner_count": 1}

    @pytest.mark.asyncio
    async def test_submit_inherits_simulation_config_from_state(self):
        """submit_plan_to_simulator must use simulation_config from state when not passed directly."""
        ctx = _make_tool_context(
            state={
                **self.ROUTE_STATE,
                "simulation_config": {"runner_count": 1},
            }
        )
        captured_message = None

        async def capture_call_agent(**kwargs):
            nonlocal captured_message
            captured_message = kwargs.get("message")
            return "Simulator acknowledged"

        with patch(
            "agents.utils.communication.call_agent",
            side_effect=capture_call_agent,
        ):
            result = await submit_plan_to_simulator(
                action="execute",
                message="Run the marathon",
                tool_context=ctx,
                # NOT passing simulation_config — should come from state
            )

        assert result["status"] == "success"
        assert captured_message is not None
        payload = json.loads(captured_message)
        assert payload.get("simulation_config") == {"runner_count": 1}, (
            f"Expected simulation_config from state, got: {payload}"
        )

    @pytest.mark.asyncio
    async def test_start_then_submit_carries_runner_count(self):
        """Full two-tool flow: start_simulation sets config, submit reads it from state."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        # Step 1: LLM calls start_simulation with runner_count=1
        await start_simulation(
            action="execute",
            message="Run with 1 runner",
            tool_context=ctx,
            simulation_config={"runner_count": 1},
        )

        # Step 2: LLM calls submit_plan_to_simulator WITHOUT simulation_config
        captured_message = None

        async def capture_call_agent(**kwargs):
            nonlocal captured_message
            captured_message = kwargs.get("message")
            return "Simulator acknowledged"

        with patch(
            "agents.utils.communication.call_agent",
            side_effect=capture_call_agent,
        ):
            await submit_plan_to_simulator(
                action="execute",
                message="Run with 1 runner",
                tool_context=ctx,
                # No simulation_config — must come from state
            )

        assert captured_message is not None
        payload = json.loads(captured_message)
        assert payload.get("simulation_config") == {"runner_count": 1}, (
            f"runner_count=1 should carry from start_simulation to submit, got: {payload}"
        )


class TestRedisFallback:
    """Verify payload includes route/traffic when Redis is unavailable."""

    @pytest.mark.asyncio
    async def test_payload_includes_route_when_redis_unavailable(self):
        """When store_simulation_data returns False, route and traffic go in the A2A payload."""
        route = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Fallback Blvd"},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-115.17, 36.08], [-115.17, 36.09]],
                    },
                }
            ],
        }
        traffic = {"overall_rating": "B", "segments": []}
        ctx = _make_tool_context(state={"marathon_route": route, "traffic_assessment": traffic})
        captured_message = None

        async def capture_call_agent(**kwargs):
            nonlocal captured_message
            captured_message = kwargs.get("message")
            return "Simulator acknowledged"

        from unittest.mock import AsyncMock as AM

        with (
            patch(
                "agents.utils.communication.call_agent",
                side_effect=capture_call_agent,
            ),
            patch(
                "agents.utils.simdata.store_simulation_data",
                AM(return_value=False),
            ),
        ):
            result = await submit_plan_to_simulator(
                action="execute",
                message="Run the fallback marathon",
                tool_context=ctx,
            )

        assert result["status"] == "success"
        assert captured_message is not None

        payload = json.loads(captured_message)
        assert payload["route"] == route, "Route should be in payload when Redis is unavailable"
        assert payload["traffic_assessment"] == traffic, (
            "Traffic assessment should be in payload when Redis is unavailable"
        )


class TestRunnerTypeParam:
    """Verify runner_type parameter is injected into simulation_config."""

    ROUTE_STATE = {
        "marathon_route": {"type": "FeatureCollection", "features": []},
    }

    @pytest.mark.asyncio
    async def test_second_execute_is_rejected(self):
        """A second execute call in the same invocation must be rejected."""
        ctx = _make_tool_context(
            state={**self.ROUTE_STATE, "simulation_executed_invocation": "inv-001"},
        )

        result = await submit_plan_to_simulator(
            action="execute",
            message="Run it again",
            tool_context=ctx,
        )

        assert result["status"] == "error"
        assert "already" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_submit_guard_steers_to_next_step(self):
        """The guard response must steer the LLM toward record-keeping tools."""
        ctx = _make_tool_context(
            state={**self.ROUTE_STATE, "simulation_executed_invocation": "inv-001"},
        )

        result = await submit_plan_to_simulator(
            action="execute",
            message="Run it again",
            tool_context=ctx,
        )

        assert result["status"] == "error"
        assert "record_simulation" in result["message"]
        assert "store_simulation_summary" in result["message"]
        assert "validate_and_emit_a2ui" in result["message"]

    @pytest.mark.asyncio
    async def test_start_guard_steers_to_next_step(self):
        """The start_simulation guard response must steer the LLM toward record-keeping."""
        ctx = _make_tool_context(
            state={**self.ROUTE_STATE, "simulation_executed_invocation": "inv-001"},
        )

        result = await start_simulation(
            action="execute",
            message="Run again",
            tool_context=ctx,
        )

        assert result["status"] == "error"
        assert "record_simulation" in result["message"]
        assert "store_simulation_summary" in result["message"]
        assert "validate_and_emit_a2ui" in result["message"]

    @pytest.mark.asyncio
    async def test_first_execute_sets_invocation(self):
        """A successful execute must store the invocation_id in state."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})
        captured_message = None

        async def capture_call_agent(**kwargs):
            nonlocal captured_message
            captured_message = kwargs.get("message")
            return "Simulator acknowledged"

        with patch(
            "agents.utils.communication.call_agent",
            side_effect=capture_call_agent,
        ):
            result = await submit_plan_to_simulator(
                action="execute",
                message="Test with runner type",
                tool_context=ctx,
                runner_type="runner_gke",
            )

        assert result["status"] == "success"
        assert captured_message is not None
        payload = json.loads(captured_message)
        assert payload["simulation_config"]["runner_type"] == "runner_gke"

    @pytest.mark.asyncio
    async def test_submit_plan_runner_type_merges_with_existing_config(self):
        """runner_type should merge into existing simulation_config."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})
        captured_message = None

        async def capture_call_agent(**kwargs):
            nonlocal captured_message
            captured_message = kwargs.get("message")
            return "Simulator acknowledged"

        with patch(
            "agents.utils.communication.call_agent",
            side_effect=capture_call_agent,
        ):
            result = await submit_plan_to_simulator(
                action="execute",
                message="Test merge",
                tool_context=ctx,
                simulation_config={"runner_count": 50},
                runner_type="runner_cloudrun",
            )

        assert result["status"] == "success"
        assert captured_message is not None
        payload = json.loads(captured_message)
        assert payload["simulation_config"]["runner_count"] == 50
        assert payload["simulation_config"]["runner_type"] == "runner_cloudrun"

    @pytest.mark.asyncio
    async def test_submit_plan_no_runner_type_no_injection(self):
        """When runner_type is None, simulation_config should not have it injected."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})
        captured_message = None

        async def capture_call_agent(**kwargs):
            nonlocal captured_message
            captured_message = kwargs.get("message")
            return "Simulator acknowledged"

        with patch(
            "agents.utils.communication.call_agent",
            side_effect=capture_call_agent,
        ):
            result = await submit_plan_to_simulator(
                action="execute",
                message="Test no runner type",
                tool_context=ctx,
                simulation_config={"runner_count": 10},
            )

        assert result["status"] == "success"
        assert captured_message is not None
        payload = json.loads(captured_message)
        assert payload["simulation_config"] == {"runner_count": 10}

    @pytest.mark.asyncio
    async def test_start_simulation_runner_type_stored_in_config(self):
        """runner_type on start_simulation should be stored in state config."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        result = await start_simulation(
            action="execute",
            message="Run with GKE runners",
            tool_context=ctx,
            simulation_config={"runner_count": 20},
            runner_type="runner_gke",
        )

        assert result["status"] == "ready"
        assert ctx.state["simulation_config"]["runner_type"] == "runner_gke"
        assert ctx.state["simulation_config"]["runner_count"] == 20

    @pytest.mark.asyncio
    async def test_start_simulation_runner_type_without_config(self):
        """runner_type on start_simulation works even without simulation_config."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        result = await start_simulation(
            action="execute",
            message="Run with local runners",
            tool_context=ctx,
            runner_type="runner",
        )

        assert result["status"] == "ready"
        assert ctx.state["simulation_config"]["runner_type"] == "runner"

    @pytest.mark.asyncio
    async def test_two_tool_flow_carries_runner_type(self):
        """Full start->submit flow should carry runner_type from start to submit."""
        ctx = _make_tool_context(state={**self.ROUTE_STATE})

        # Step 1: start_simulation with runner_type
        await start_simulation(
            action="execute",
            message="Run with CloudRun runners",
            tool_context=ctx,
            simulation_config={"runner_count": 5},
            runner_type="runner_cloudrun",
        )

        # Step 2: submit without runner_type -- should carry from state
        captured_message = None

        async def capture_call_agent(**kwargs):
            nonlocal captured_message
            captured_message = kwargs.get("message")
            return "Simulator acknowledged"

        with patch(
            "agents.utils.communication.call_agent",
            side_effect=capture_call_agent,
        ):
            await submit_plan_to_simulator(
                action="execute",
                message="Run with CloudRun runners",
                tool_context=ctx,
            )

        assert captured_message is not None
        payload = json.loads(captured_message)
        assert payload["simulation_config"]["runner_type"] == "runner_cloudrun"
        assert payload["simulation_config"]["runner_count"] == 5
