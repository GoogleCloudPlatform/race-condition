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

"""Tests for _runner_before_agent_callback tick param extraction."""

import json
from typing import Any

import pytest
from unittest.mock import MagicMock

from agents.runner.agent import _runner_before_agent_callback


def _make_callback_context(state: dict[str, Any], user_text: str = "", session_id: str = "test-sess") -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    ctx.session = MagicMock()
    ctx.session.id = session_id

    if user_text:
        part = MagicMock()
        part.text = user_text
        content = MagicMock()
        content.parts = [part]
        ctx.user_content = content
    else:
        ctx.user_content = None

    return ctx


@pytest.mark.asyncio
async def test_before_agent_extracts_tick_params():
    """Callback should parse tick event from user_content into state."""
    tick_event = json.dumps(
        {
            "event": "tick",
            "tick": 5,
            "minutes_per_tick": 10.0,
            "elapsed_minutes": 50.0,
            "race_distance_mi": 26.2188,
            "collector_buffer_key": "collector:buffer:abc",
            "runner_count": 10,
        }
    )
    state: dict[str, Any] = {"velocity": 1.0}  # Already initialized
    ctx = _make_callback_context(state, user_text=tick_event)

    await _runner_before_agent_callback(ctx)

    assert "_tick_params" in state
    tp: dict[str, Any] = state["_tick_params"]
    assert tp["tick"] == 5
    assert tp["minutes_per_tick"] == 10.0
    assert tp["elapsed_minutes"] == 50.0
    assert tp["race_distance_mi"] == 26.2188
    assert tp["collector_buffer_key"] == "collector:buffer:abc"


@pytest.mark.asyncio
async def test_before_agent_ignores_non_tick_events():
    """Non-tick events should not set _tick_params."""
    start_event = json.dumps({"event": "start_gun"})
    state = {"velocity": 1.0}
    ctx = _make_callback_context(state, user_text=start_event)

    await _runner_before_agent_callback(ctx)

    assert "_tick_params" not in state


@pytest.mark.asyncio
async def test_before_agent_ignores_non_json():
    """Plain text messages should not crash or set _tick_params."""
    state = {"velocity": 1.0}
    ctx = _make_callback_context(state, user_text="Hello, how are you?")

    await _runner_before_agent_callback(ctx)

    assert "_tick_params" not in state


@pytest.mark.asyncio
async def test_before_agent_handles_no_user_content():
    """Missing user_content should not crash."""
    state = {"velocity": 1.0}
    ctx = _make_callback_context(state, user_text="")

    await _runner_before_agent_callback(ctx)

    assert "_tick_params" not in state


@pytest.mark.asyncio
async def test_before_agent_still_initializes_runner():
    """On first tick (velocity is None), runner should still be initialized."""
    tick_event = json.dumps(
        {
            "event": "tick",
            "tick": 0,
            "minutes_per_tick": 0.0,
            "elapsed_minutes": 0.0,
            "race_distance_mi": 26.2188,
            "runner_count": 5,
        }
    )
    state = {}  # velocity not set = first tick
    ctx = _make_callback_context(state, user_text=tick_event, session_id="init-test")

    await _runner_before_agent_callback(ctx)

    # Runner should be initialized (velocity set)
    assert state.get("velocity") is not None
    # Tick params should also be extracted
    assert state["_tick_params"]["tick"] == 0


@pytest.mark.asyncio
async def test_before_agent_updates_tick_params_each_call():
    """_tick_params should be updated on every tick, not just the first."""
    state: dict[str, Any] = {"velocity": 1.0}  # Already initialized

    # First tick
    tick1 = json.dumps(
        {"event": "tick", "tick": 1, "minutes_per_tick": 5.0, "elapsed_minutes": 5.0, "race_distance_mi": 26.2188}
    )
    ctx1 = _make_callback_context(state, user_text=tick1)
    await _runner_before_agent_callback(ctx1)
    tp1: dict[str, Any] = state["_tick_params"]
    assert tp1["tick"] == 1

    # Second tick
    tick2 = json.dumps(
        {"event": "tick", "tick": 2, "minutes_per_tick": 5.0, "elapsed_minutes": 10.0, "race_distance_mi": 26.2188}
    )
    ctx2 = _make_callback_context(state, user_text=tick2)
    await _runner_before_agent_callback(ctx2)
    tp2: dict[str, Any] = state["_tick_params"]
    assert tp2["tick"] == 2
    assert tp2["elapsed_minutes"] == 10.0
