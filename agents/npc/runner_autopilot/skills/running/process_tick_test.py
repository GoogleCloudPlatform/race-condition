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

"""Tests for the process_tick tool."""

import pytest
from unittest.mock import MagicMock

from agents.npc.runner_autopilot.skills.running.tools import process_tick

MARATHON_MI = 26.2188


@pytest.fixture
def mock_tool_context():
    ctx = MagicMock()
    ctx.state = {
        "velocity": 1.0,
        "distance": 0.0,
        "water": 100.0,
        "exhausted": False,
        "collapsed": False,
        "finished": False,
        "will_hit_wall": False,
        "wall_mi": 18.6411,
        "wall_severity": 0.25,
        "hydration_efficiency": 1.0,
    }
    ctx.session = MagicMock()
    ctx.session.id = "test-runner-001"
    return ctx


@pytest.mark.asyncio
async def test_advances_distance(mock_tool_context):
    """Distance should increase based on velocity and minutes_per_tick."""
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=15.0,
        race_distance_mi=MARATHON_MI,
        tick=1,
        tool_context=mock_tool_context,
    )
    assert result["status"] == "success"
    assert result["distance_mi"] > 0.0
    assert result["distance"] == pytest.approx(result["distance_mi"], rel=1e-3)
    assert result["mi_this_tick"] > 0.0
    assert mock_tool_context.state["distance"] > 0.0
    # effective_velocity should be <= base velocity (degradation factors)
    assert 0.0 < result["effective_velocity"] <= result["velocity"]


@pytest.mark.asyncio
async def test_depletes_water(mock_tool_context):
    """Water should decrease after processing a tick."""
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=15.0,
        race_distance_mi=MARATHON_MI,
        tick=1,
        tool_context=mock_tool_context,
    )
    assert result["water"] < 100.0
    assert mock_tool_context.state["water"] < 100.0


@pytest.mark.asyncio
async def test_detects_finish(mock_tool_context):
    """Runner near the finish should be marked finished."""
    mock_tool_context.state["distance"] = 25.8
    mock_tool_context.state["velocity"] = 1.0
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=300.0,
        race_distance_mi=MARATHON_MI,
        tick=20,
        tool_context=mock_tool_context,
    )
    assert result["runner_status"] == "finished"
    assert mock_tool_context.state["finished"] is True
    assert result["finish_time_minutes"] is not None
    assert result["pace_min_per_mi"] is not None
    assert result["pace_min_per_mi"] > 0


@pytest.mark.asyncio
async def test_finished_runner_is_noop(mock_tool_context):
    """Already-finished runners should not move further."""
    mock_tool_context.state["finished"] = True
    mock_tool_context.state["distance"] = 26.2188
    mock_tool_context.state["finish_time_minutes"] = 250.0
    mock_tool_context.state["pace_min_per_mi"] = 5.93
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=300.0,
        race_distance_mi=MARATHON_MI,
        tick=20,
        tool_context=mock_tool_context,
    )
    assert result["runner_status"] == "finished"
    assert result["mi_this_tick"] == 0.0
    assert result["distance"] == pytest.approx(26.2188, rel=1e-3)
    assert result["effective_velocity"] == 0.0


@pytest.mark.asyncio
async def test_collapsed_runner_is_noop(mock_tool_context):
    """Collapsed runners should not move."""
    mock_tool_context.state["collapsed"] = True
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=300.0,
        race_distance_mi=MARATHON_MI,
        tick=20,
        tool_context=mock_tool_context,
    )
    assert result["runner_status"] == "collapsed"
    assert result["mi_this_tick"] == 0.0
    assert result["effective_velocity"] == 0.0


@pytest.mark.asyncio
async def test_hydration_affects_speed(mock_tool_context):
    """Dehydrated runner should travel less distance per tick."""
    # Full hydration run
    mock_tool_context.state["water"] = 100.0
    result_full = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=15.0,
        race_distance_mi=MARATHON_MI,
        tick=1,
        tool_context=mock_tool_context,
    )
    # Reset state for dehydrated run
    mock_tool_context.state["distance"] = 0.0
    mock_tool_context.state["water"] = 20.0
    result_dehydrated = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=15.0,
        race_distance_mi=MARATHON_MI,
        tick=1,
        tool_context=mock_tool_context,
    )
    assert result_dehydrated["mi_this_tick"] < result_full["mi_this_tick"]


@pytest.mark.asyncio
async def test_wall_effect_reduces_distance(mock_tool_context):
    """Runner past the wall should travel less per tick."""
    mock_tool_context.state["will_hit_wall"] = True
    mock_tool_context.state["wall_mi"] = 18.6411
    mock_tool_context.state["wall_severity"] = 0.3
    # Before wall
    mock_tool_context.state["distance"] = 15.5
    result_before = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=150.0,
        race_distance_mi=MARATHON_MI,
        tick=10,
        tool_context=mock_tool_context,
    )
    # After wall
    mock_tool_context.state["distance"] = 19.3
    mock_tool_context.state["water"] = result_before["water"]
    result_after = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=165.0,
        race_distance_mi=MARATHON_MI,
        tick=11,
        tool_context=mock_tool_context,
    )
    assert result_after["mi_this_tick"] < result_before["mi_this_tick"]


@pytest.mark.asyncio
async def test_auto_hydration_station(mock_tool_context):
    """Crossing a ~1.86mi marker with low water should trigger auto-rehydration."""
    mock_tool_context.state["distance"] = 1.8
    mock_tool_context.state["water"] = 30.0  # Low enough to always trigger
    mock_tool_context.state["velocity"] = 1.0
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=45.0,
        race_distance_mi=MARATHON_MI,
        tick=3,
        tool_context=mock_tool_context,
    )
    # Should have crossed ~1.86mi marker and rehydrated
    assert result["distance_mi"] > 1.8641
    # Water should be higher than pure depletion would produce
    assert result["water"] > 20.0


@pytest.mark.asyncio
async def test_returns_structured_dict(mock_tool_context):
    """Output must contain all required fields for collector aggregation."""
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=15.0,
        race_distance_mi=MARATHON_MI,
        tick=1,
        tool_context=mock_tool_context,
    )
    required_keys = {
        "status",
        "runner_status",
        "velocity",
        "effective_velocity",
        "distance_mi",
        "distance",
        "water",
        "pace_min_per_mi",
        "elapsed_minutes",
        "mi_this_tick",
        "finish_time_minutes",
        "exhausted",
        "collapsed",
    }
    assert required_keys.issubset(result.keys()), f"Missing keys: {required_keys - result.keys()}"


@pytest.mark.asyncio
async def test_exhaustion_at_low_water(mock_tool_context):
    """Water dropping below 30% should trigger exhaustion."""
    mock_tool_context.state["water"] = 32.0
    mock_tool_context.state["velocity"] = 1.5  # Fast enough to deplete water
    mock_tool_context.state["hydration_efficiency"] = 3.0  # High depletion
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=15.0,
        race_distance_mi=MARATHON_MI,
        tick=1,
        tool_context=mock_tool_context,
    )
    if result["water"] < 30.0:
        assert result["exhausted"] is True


# ---------------------------------------------------------------------------
# inner_thought field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inner_thought_default_empty(mock_tool_context):
    """When no inner_thought is provided, the field defaults to empty string."""
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=15.0,
        race_distance_mi=MARATHON_MI,
        tick=1,
        tool_context=mock_tool_context,
    )
    assert "inner_thought" in result
    assert result["inner_thought"] == ""


@pytest.mark.asyncio
async def test_inner_thought_passed_through(mock_tool_context):
    """When inner_thought is provided, it appears verbatim in the result."""
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=15.0,
        race_distance_mi=MARATHON_MI,
        tick=1,
        tool_context=mock_tool_context,
        inner_thought="Why did I register?",
    )
    assert result["inner_thought"] == "Why did I register?"


@pytest.mark.asyncio
async def test_inner_thought_in_finished_response(mock_tool_context):
    """Finished runners still include inner_thought in their response."""
    mock_tool_context.state["finished"] = True
    mock_tool_context.state["distance"] = 26.3
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=300.0,
        race_distance_mi=MARATHON_MI,
        tick=10,
        tool_context=mock_tool_context,
        inner_thought="Never again. Maybe.",
    )
    assert result["runner_status"] == "finished"
    assert result["inner_thought"] == "Never again. Maybe."


# ---------------------------------------------------------------------------
# tick number in result (dedup filtering)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_includes_tick_number(mock_tool_context):
    """process_tick result must include the tick number for dedup filtering."""
    result = await process_tick(
        minutes_per_tick=30.0,
        elapsed_minutes=60.0,
        race_distance_mi=26.2188,
        tick=2,
        tool_context=mock_tool_context,
    )
    assert result["tick"] == 2


@pytest.mark.asyncio
async def test_finished_runner_result_includes_tick(mock_tool_context):
    """Finished runners must also include tick in their early-return result."""
    mock_tool_context.state["finished"] = True
    result = await process_tick(
        minutes_per_tick=30.0,
        elapsed_minutes=60.0,
        race_distance_mi=26.2188,
        tick=5,
        tool_context=mock_tool_context,
    )
    assert result["tick"] == 5
    assert result["runner_status"] == "finished"


@pytest.mark.asyncio
async def test_finish_time_interpolated_with_distance_cap(mock_tool_context):
    """Finish time should be sub-tick interpolated even with distance capping."""
    mock_tool_context.state["velocity"] = 2.0
    mock_tool_context.state["distance"] = 26.0
    result = await process_tick(
        minutes_per_tick=30.0,
        elapsed_minutes=300.0,
        race_distance_mi=MARATHON_MI,
        tick=10,
        tool_context=mock_tool_context,
    )
    assert result["runner_status"] == "finished"
    assert result["distance"] <= MARATHON_MI
    # Finish time should be LESS than elapsed_minutes (sub-tick interpolation)
    assert result["finish_time_minutes"] < 300.0


@pytest.mark.asyncio
async def test_distance_capped_at_race_distance(mock_tool_context):
    """Distance should never exceed race_distance_mi."""
    mock_tool_context.state["velocity"] = 2.0  # Fast runner
    mock_tool_context.state["distance"] = 26.0  # Near finish
    result = await process_tick(
        minutes_per_tick=15.0,
        elapsed_minutes=300.0,
        race_distance_mi=MARATHON_MI,
        tick=20,
        tool_context=mock_tool_context,
    )
    assert result["distance_mi"] <= MARATHON_MI
    assert result["distance"] <= MARATHON_MI
    assert mock_tool_context.state["distance"] <= MARATHON_MI
