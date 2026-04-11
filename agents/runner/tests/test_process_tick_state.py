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

"""Tests for process_tick reading tick params from state."""

import pytest
from unittest.mock import MagicMock

from agents.runner.running import process_tick


def _make_tool_context(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    ctx.session = MagicMock()
    ctx.session.id = "test-session-001"
    return ctx


@pytest.mark.asyncio
async def test_process_tick_reads_params_from_state():
    """process_tick should read tick/timing from _tick_params in state."""
    state = {
        "velocity": 1.0,
        "distance": 0.0,
        "water": 100.0,
        "exhausted": False,
        "collapsed": False,
        "finished": False,
        "_tick_params": {
            "tick": 3,
            "minutes_per_tick": 5.0,
            "elapsed_minutes": 15.0,
            "race_distance_mi": 26.2188,
        },
    }
    ctx = _make_tool_context(state)
    result = await process_tick(inner_thought="Legs feel great", tool_context=ctx)
    assert result["status"] == "success"
    assert result["tick"] == 3
    assert result["elapsed_minutes"] == 15.0
    assert result["inner_thought"] == "Legs feel great"
    assert result["distance_mi"] > 0


@pytest.mark.asyncio
async def test_process_tick_explicit_args_override_state():
    """Explicit args should still work (backward compat with autopilot)."""
    state = {
        "velocity": 1.0,
        "distance": 0.0,
        "water": 100.0,
        "exhausted": False,
        "collapsed": False,
        "finished": False,
        "_tick_params": {
            "tick": 99,
            "minutes_per_tick": 99.0,
            "elapsed_minutes": 99.0,
            "race_distance_mi": 99.0,
        },
    }
    ctx = _make_tool_context(state)
    result = await process_tick(
        minutes_per_tick=5.0,
        elapsed_minutes=15.0,
        race_distance_mi=26.2188,
        tick=3,
        inner_thought="Override test",
        tool_context=ctx,
    )
    assert result["tick"] == 3
    assert result["elapsed_minutes"] == 15.0


@pytest.mark.asyncio
async def test_process_tick_no_params_returns_error():
    """process_tick with no args and no _tick_params should return error dict."""
    state = {
        "velocity": 1.0,
        "distance": 0.0,
        "water": 100.0,
        "exhausted": False,
        "collapsed": False,
        "finished": False,
    }
    ctx = _make_tool_context(state)
    result = await process_tick(inner_thought="", tool_context=ctx)
    assert result["status"] == "error"
    assert "tick event" in result["message"].lower()


@pytest.mark.asyncio
async def test_process_tick_collector_buffer_from_state():
    """collector_buffer_key should be read from _tick_params when empty."""
    state = {
        "velocity": 1.0,
        "distance": 0.0,
        "water": 100.0,
        "exhausted": False,
        "collapsed": False,
        "finished": False,
        "_tick_params": {
            "tick": 1,
            "minutes_per_tick": 5.0,
            "elapsed_minutes": 5.0,
            "race_distance_mi": 26.2188,
            "collector_buffer_key": "collector:buffer:test-abc",
        },
    }
    ctx = _make_tool_context(state)
    # Should not raise; collector_buffer_key is read from state.
    # We can't easily verify the Redis write without mocking, but we
    # verify the function completes successfully with the key present.
    result = await process_tick(inner_thought="Testing buffer", tool_context=ctx)
    assert result["status"] == "success"
