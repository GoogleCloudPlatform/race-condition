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

import pytest
from unittest.mock import MagicMock
from agents.npc.runner_autopilot.skills.running.tools import accelerate, brake, get_vitals


@pytest.fixture
def mock_tool_context():
    context = MagicMock()
    context.state = {
        "velocity": 1.0,
        "distance": 0.0,
        "water": 100.0,
        "exhausted": False,
        "collapsed": False,
    }
    return context


@pytest.mark.asyncio
async def test_accelerate_returns_dict_and_scales_velocity(mock_tool_context):
    intensity = 0.5
    result = await accelerate(intensity, mock_tool_context)

    assert isinstance(result, dict), "Tool must return a dictionary payload"
    assert result.get("status") == "success"
    assert "velocity" in result

    # Base is 1.0, multiplier is 2.0, intensity 0.5, water 100% -> factor 1.0
    # 1.0 + (0.5 * 2.0 * 1.0) = 2.0
    expected_velocity = 2.0
    assert result["velocity"] == expected_velocity
    assert mock_tool_context.state["velocity"] == expected_velocity


@pytest.mark.asyncio
async def test_brake_returns_dict_and_reduces_velocity(mock_tool_context):
    intensity = 0.5
    result = await brake(intensity, mock_tool_context)

    assert isinstance(result, dict), "Tool must return a dictionary payload"
    assert result.get("status") == "success"
    assert "velocity" in result

    # Base is 1.0, brake multiplier is 1.5, intensity 0.5 -> max(0, 1.0 - 0.75) = 0.25
    expected_velocity = 0.25
    assert result["velocity"] == expected_velocity
    assert mock_tool_context.state["velocity"] == expected_velocity


@pytest.mark.asyncio
async def test_get_vitals_returns_dict(mock_tool_context):
    result = await get_vitals(mock_tool_context)

    assert isinstance(result, dict), "Tool must return a dictionary payload"
    assert result.get("velocity") == 1.0
    assert result.get("distance") == 0.0
    assert result.get("water") == 100.0
    assert result.get("exhausted") is False
    assert result.get("collapsed") is False


@pytest.mark.asyncio
async def test_accelerate_dehydration_penalty(mock_tool_context):
    """At 0% water, acceleration effectiveness is halved."""
    mock_tool_context.state["water"] = 0.0
    mock_tool_context.state["velocity"] = 0.0
    result = await accelerate(1.0, mock_tool_context)

    # hydration_factor = 0.5 + 0.5*(0/100) = 0.5
    # new_velocity = 0 + (1.0 * 2.0 * 0.5) = 1.0
    assert result["velocity"] == 1.0
    assert mock_tool_context.state["velocity"] == 1.0
