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

"""Tests for per-session lock serialization in the single-loop dispatcher."""

import asyncio
from unittest.mock import MagicMock

import pytest

from agents.utils.dispatcher import RedisOrchestratorDispatcher


def _make_dispatcher() -> RedisOrchestratorDispatcher:
    """Create a minimal dispatcher for lock testing."""
    mock_runner = MagicMock()
    mock_runner.app_name = "test_agent"
    dispatcher = RedisOrchestratorDispatcher.__new__(RedisOrchestratorDispatcher)
    dispatcher.agent_type = "test_agent"
    dispatcher.runner = mock_runner
    dispatcher._background_tasks = set()
    dispatcher._session_locks = {}
    dispatcher.session_simulation_map = {}
    dispatcher.active_sessions = set()
    dispatcher._seen_events = set()
    dispatcher._simulation_subscriptions = set()
    dispatcher._pubsub = None
    dispatcher._loop = None
    dispatcher._stop_event = MagicMock()
    dispatcher.allowed_authors = {"agent", "tool", "model", "test_agent"}
    return dispatcher


@pytest.mark.asyncio
async def test_same_session_serialized():
    """Two concurrent calls for the SAME session must be serialized."""
    dispatcher = _make_dispatcher()

    call_order = []

    async def slow_logic(session_id, content, pulses_collector=None):
        call_order.append(("start", session_id))
        await asyncio.sleep(0.05)
        call_order.append(("end", session_id))

    dispatcher._trigger_agent_run_logic = slow_logic

    # Both calls target the same session
    await asyncio.gather(
        dispatcher._locked_trigger("session-A", "msg1"),
        dispatcher._locked_trigger("session-A", "msg2"),
    )

    # Must be serialized: start-A, end-A, start-A, end-A
    assert call_order[0] == ("start", "session-A")
    assert call_order[1] == ("end", "session-A")
    assert call_order[2] == ("start", "session-A")
    assert call_order[3] == ("end", "session-A")


@pytest.mark.asyncio
async def test_different_sessions_concurrent():
    """Two concurrent calls for DIFFERENT sessions must run concurrently."""
    dispatcher = _make_dispatcher()

    call_order = []

    async def slow_logic(session_id, content, pulses_collector=None):
        call_order.append(("start", session_id))
        await asyncio.sleep(0.05)
        call_order.append(("end", session_id))

    dispatcher._trigger_agent_run_logic = slow_logic

    await asyncio.gather(
        dispatcher._locked_trigger("session-A", "msg1"),
        dispatcher._locked_trigger("session-B", "msg2"),
    )

    # Both should start before either ends (concurrent)
    starts = [i for i, (action, _) in enumerate(call_order) if action == "start"]
    ends = [i for i, (action, _) in enumerate(call_order) if action == "end"]
    assert len(starts) == 2
    assert len(ends) == 2
    # Both starts happen before both ends
    assert max(starts) < min(ends)


@pytest.mark.asyncio
async def test_environment_reset_clears_locks():
    """environment_reset must clear the session locks dict."""
    dispatcher = _make_dispatcher()

    # Pre-populate a lock
    dispatcher._session_locks["session-X"] = asyncio.Lock()
    assert len(dispatcher._session_locks) == 1

    # Process environment_reset event
    await dispatcher._process_event({"type": "environment_reset"})

    assert len(dispatcher._session_locks) == 0


@pytest.mark.asyncio
async def test_lock_created_lazily():
    """Locks should be created on first access, not pre-allocated."""
    dispatcher = _make_dispatcher()
    assert len(dispatcher._session_locks) == 0

    async def noop_logic(session_id, content, pulses_collector=None):
        pass

    dispatcher._trigger_agent_run_logic = noop_logic
    await dispatcher._locked_trigger("session-new", "msg")

    # Lock should have been created
    assert "session-new" in dispatcher._session_locks
