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
from agents.npc.runner_autopilot.skills.hydration.tools import (
    deplete_water,
    rehydrate,
)


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
async def test_deplete_water_reduces_hydration(mock_tool_context):
    result = await deplete_water(15.0, mock_tool_context)

    assert result["status"] == "success"
    assert result["water"] == 85.0
    assert mock_tool_context.state["water"] == 85.0


@pytest.mark.asyncio
async def test_deplete_water_floors_at_zero(mock_tool_context):
    result = await deplete_water(200.0, mock_tool_context)

    assert result["water"] == 0.0
    assert mock_tool_context.state["water"] == 0.0


@pytest.mark.asyncio
async def test_deplete_water_triggers_exhaustion(mock_tool_context):
    """Hydration dropping below 30 should trigger exhaustion."""
    result = await deplete_water(75.0, mock_tool_context)

    # 100 - 75 = 25, which is below EXHAUSTION_THRESHOLD (30)
    assert result["water"] == 25.0
    assert result["exhausted"] is True
    assert result["status"] == "exhausted"
    assert mock_tool_context.state["exhausted"] is True


@pytest.mark.asyncio
async def test_deplete_water_triggers_collapse(mock_tool_context):
    """Hydration dropping below 10 while exhausted should trigger collapse."""
    mock_tool_context.state["water"] = 15.0
    mock_tool_context.state["exhausted"] = True

    result = await deplete_water(10.0, mock_tool_context)

    # 15 - 10 = 5, which is below COLLAPSE_THRESHOLD (10), and already exhausted
    assert result["water"] == 5.0
    assert result["collapsed"] is True
    assert result["status"] == "collapsed"
    assert mock_tool_context.state["collapsed"] is True


@pytest.mark.asyncio
async def test_deplete_water_resets_exhaustion_above_threshold(mock_tool_context):
    """Small depletion keeping hydration above 30 should not cause exhaustion."""
    mock_tool_context.state["exhausted"] = True
    mock_tool_context.state["water"] = 80.0

    result = await deplete_water(5.0, mock_tool_context)

    # 80 - 5 = 75, still above 30
    assert result["exhausted"] is False
    assert mock_tool_context.state["exhausted"] is False


@pytest.mark.asyncio
async def test_rehydrate_adds_amount(mock_tool_context):
    mock_tool_context.state["water"] = 40.0
    result = await rehydrate(30.0, mock_tool_context)

    assert result["status"] == "success"
    assert result["water"] == 70.0
    assert mock_tool_context.state["water"] == 70.0


@pytest.mark.asyncio
async def test_rehydrate_caps_at_100(mock_tool_context):
    mock_tool_context.state["water"] = 80.0
    result = await rehydrate(30.0, mock_tool_context)

    assert result["water"] == 100.0
    assert mock_tool_context.state["water"] == 100.0


@pytest.mark.asyncio
async def test_rehydrate_resets_exhaustion(mock_tool_context):
    """Rehydrating above exhaustion threshold should clear exhaustion."""
    mock_tool_context.state["water"] = 20.0
    mock_tool_context.state["exhausted"] = True
    mock_tool_context.state["collapsed"] = True

    result = await rehydrate(30.0, mock_tool_context)

    # 20 + 30 = 50, which is >= 30
    assert result["water"] == 50.0
    assert mock_tool_context.state["exhausted"] is False
    assert mock_tool_context.state["collapsed"] is False
