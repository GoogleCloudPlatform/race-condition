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

"""Tests asserting submit_plan_to_simulator persists the simulator's response to state.

Per the state-driven memory persistence design, downstream tools (record_simulation,
store_simulation_summary) read simulation_result from session state instead of
receiving it as an LLM-supplied JSON string.  Therefore submit_plan_to_simulator
MUST write the simulator's response to tool_context.state["simulation_result"]
on a successful call.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.planner_with_eval.tools import submit_plan_to_simulator


def _make_tool_context() -> MagicMock:
    ctx = MagicMock()
    ctx.state = {"marathon_route": {"type": "FeatureCollection", "features": []}}
    ctx.session = MagicMock()
    ctx.session.id = "planner-session-state"
    ctx.invocation_id = "inv-state-001"
    ctx.agent_name = "planner_with_eval"
    return ctx


@pytest.mark.asyncio
async def test_submit_plan_to_simulator_writes_response_to_state():
    """A successful call_agent response MUST be persisted to state["simulation_result"]."""
    ctx = _make_tool_context()
    fake_response = {
        "status": "success",
        "summary": "Simulation complete",
        "metrics": {"finishers": 9421, "median_minutes": 247},
    }

    with (
        patch(
            "agents.utils.communication.call_agent",
            new=AsyncMock(return_value=fake_response),
        ),
        patch(
            "agents.utils.simdata.store_simulation_data",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await submit_plan_to_simulator(
            action="execute",
            message="Run it",
            tool_context=ctx,
        )

    assert result["status"] == "success"
    assert "simulation_result" in ctx.state, "submit_plan_to_simulator did not write simulation_result to state"
    assert ctx.state["simulation_result"] == fake_response


@pytest.mark.asyncio
async def test_submit_plan_to_simulator_no_state_write_on_call_failure():
    """If call_agent raises, no stale simulation_result should be written."""
    ctx = _make_tool_context()
    ctx.state.pop("simulation_result", None)

    with (
        patch(
            "agents.utils.communication.call_agent",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch(
            "agents.utils.simdata.store_simulation_data",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await submit_plan_to_simulator(
            action="execute",
            message="Run it",
            tool_context=ctx,
        )

    assert result["status"] == "error"
    assert "simulation_result" not in ctx.state, (
        "submit_plan_to_simulator wrote simulation_result despite call_agent failure"
    )


@pytest.mark.asyncio
async def test_submit_plan_to_simulator_writes_response_for_verify_action():
    """State write must happen for action='verify' as well, not just execute."""
    ctx = _make_tool_context()
    fake_response = {"status": "verified", "estimated_minutes": 240}

    with (
        patch(
            "agents.utils.communication.call_agent",
            new=AsyncMock(return_value=fake_response),
        ),
        patch(
            "agents.utils.simdata.store_simulation_data",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await submit_plan_to_simulator(
            action="verify",
            message="Verify it",
            tool_context=ctx,
        )

    assert result["status"] == "success"
    assert ctx.state.get("simulation_result") == fake_response
