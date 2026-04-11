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

"""Tests for dispatcher suppress_gateway_emission flag."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.utils.dispatcher import RedisOrchestratorDispatcher


def _make_mock_runner(agent_name: str = "test_runner") -> MagicMock:
    runner = MagicMock()
    runner.app = MagicMock()
    runner.app.name = agent_name
    runner.app.root_agent = MagicMock()
    runner.app.root_agent.name = agent_name
    return runner


def test_dispatcher_default_does_not_suppress():
    """By default, suppress_gateway_emission should be False."""
    runner = _make_mock_runner()
    d = RedisOrchestratorDispatcher(runner=runner, dispatch_mode="callable")
    assert d.suppress_gateway_emission is False


def test_dispatcher_accepts_suppress_flag():
    """Dispatcher should accept suppress_gateway_emission=True."""
    runner = _make_mock_runner()
    d = RedisOrchestratorDispatcher(runner=runner, dispatch_mode="callable", suppress_gateway_emission=True)
    assert d.suppress_gateway_emission is True


@pytest.mark.asyncio
async def test_dispatcher_suppresses_gateway_emission():
    """When suppress_gateway_emission=True, no gateway messages should be emitted."""
    runner = _make_mock_runner("runner_test")

    # Create a mock event with a function_response part (simulating process_tick result)
    mock_event = MagicMock()
    mock_event.author = "runner_test"
    mock_part = MagicMock()
    mock_part.text = None
    mock_part.function_call = None
    mock_part.function_response = MagicMock()
    mock_part.function_response.response = {"status": "success", "tick": 1}
    mock_event.content = MagicMock()
    mock_event.content.parts = [mock_part]

    # Make run_async return our mock event
    async def mock_run_async(**kwargs):
        yield mock_event

    runner.run_async = mock_run_async

    d = RedisOrchestratorDispatcher(runner=runner, dispatch_mode="callable", suppress_gateway_emission=True)
    d.session_simulation_map["test-session"] = "sim-001"

    with patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_emit:
        content = MagicMock()
        await d._trigger_agent_run_logic("test-session", content)
        # Gateway emission should NOT have been called
        mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_dispatcher_emits_when_not_suppressed():
    """When suppress_gateway_emission=False, gateway messages should be emitted."""
    runner = _make_mock_runner("runner_test")

    mock_event = MagicMock()
    mock_event.author = "runner_test"
    mock_part = MagicMock()
    mock_part.text = "I finished the race."
    mock_part.function_call = None
    mock_part.function_response = None
    mock_event.content = MagicMock()
    mock_event.content.parts = [mock_part]

    async def mock_run_async(**kwargs):
        yield mock_event

    runner.run_async = mock_run_async

    d = RedisOrchestratorDispatcher(runner=runner, dispatch_mode="callable", suppress_gateway_emission=False)
    d.session_simulation_map["test-session"] = "sim-001"

    with patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_emit:
        content = MagicMock()
        await d._trigger_agent_run_logic("test-session", content)
        # Gateway emission SHOULD have been called
        mock_emit.assert_called()
