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

"""Tests for dispatcher session handling behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.utils.dispatcher import RedisOrchestratorDispatcher


@pytest.mark.asyncio
async def test_trigger_agent_run_does_not_call_get_session_directly():
    """Dispatcher must NOT pre-check sessions — runner.run_async handles it."""
    mock_runner = MagicMock()
    mock_runner.app_name = "test_agent"
    mock_session_service = AsyncMock()
    mock_runner.session_service = mock_session_service

    # run_async returns an empty async generator
    async def empty_gen(*a, **kw):
        return
        yield  # noqa: F811 — unreachable yield makes this an async generator

    mock_runner.run_async = MagicMock(return_value=empty_gen())

    dispatcher = RedisOrchestratorDispatcher.__new__(RedisOrchestratorDispatcher)
    dispatcher.agent_type = "test_agent"
    dispatcher.runner = mock_runner
    dispatcher._background_tasks = set()

    await dispatcher._trigger_agent_run_logic("session-1", "hello")

    # The dispatcher must NOT call get_session — that's the runner's job
    mock_session_service.get_session.assert_not_called()
    mock_session_service.create_session.assert_not_called()
    # But run_async MUST be called
    mock_runner.run_async.assert_called_once()
