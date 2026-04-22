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

"""Tests for resilient listener management in the dispatcher.

The dispatcher runs two concurrent listeners via asyncio:
  - PubSub listener (receives TICK broadcasts)
  - Queue listener (dequeues spawn events via BLPOP)

When the queue listener hits pool exhaustion, it catches the exception
internally and returns normally (break out of loop → function returns None).
asyncio.gather only cancels siblings when one RAISES — a normal return
keeps gather waiting for the other task forever.  This is the bug that
causes 800/1000 runners to be lost.

These tests verify that if EITHER listener exits (normally or via exception),
the surviving listener is cancelled and the outer reconnect loop restarts both.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agents.utils.dispatcher import RedisOrchestratorDispatcher


def _make_dispatcher() -> RedisOrchestratorDispatcher:
    """Create a minimal dispatcher for listener tests."""
    mock_runner = MagicMock()
    mock_runner.app_name = "test_agent"
    dispatcher = RedisOrchestratorDispatcher.__new__(RedisOrchestratorDispatcher)
    dispatcher.agent_type = "test_agent"
    dispatcher.runner = mock_runner
    dispatcher.dispatch_mode = "subscriber"
    dispatcher._background_tasks = set()
    dispatcher._session_locks = {}
    dispatcher.session_simulation_map = {}
    dispatcher.active_sessions = set()
    dispatcher._seen_events = set()
    dispatcher._simulation_subscriptions = set()
    dispatcher._pubsub = None
    dispatcher._loop = None
    dispatcher._stop_event = asyncio.Event()  # type: ignore[assignment]
    dispatcher.allowed_authors = {"agent", "tool", "model", "test_agent"}
    dispatcher.redis_url = ""
    return dispatcher


@pytest.mark.asyncio
async def test_queue_listener_normal_exit_cancels_pubsub_listener():
    """When queue listener returns normally, pubsub listener must be cancelled.

    This is the exact failure mode: the queue listener catches a Redis
    ConnectionError internally, breaks out of its loop, and returns None.
    asyncio.gather sees a normal return and keeps waiting for the PubSub
    listener, which runs indefinitely.  The outer reconnect loop never fires.
    """
    dispatcher = _make_dispatcher()

    async def silently_exiting_queue(r):
        """Simulate queue listener that exits normally (like the real break path)."""
        return  # Normal return, no exception — this is the bug trigger

    async def long_running_pubsub(r):
        """Simulate pubsub listener that runs indefinitely."""
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            return

    async def counting_listen_loop():
        """Run _listen_loop counting reconnect cycles via queue_listener calls."""
        call_count = 0

        async def counting_queue(r):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                # Stop after 2 reconnect cycles to prove it reconnects
                dispatcher._stop_event.set()
            return  # Normal exit — this is the bug trigger

        with patch.object(dispatcher, "_pubsub_listener", side_effect=long_running_pubsub):
            with patch.object(dispatcher, "_queue_listener", side_effect=counting_queue):
                with patch("agents.utils.dispatcher.get_shared_redis_client", return_value=MagicMock()):
                    await dispatcher._listen_loop()

    # This must complete within 5 seconds. With the asyncio.gather bug,
    # it would hang forever because pubsub never gets cancelled.
    try:
        await asyncio.wait_for(counting_listen_loop(), timeout=5.0)
    except asyncio.TimeoutError:
        pytest.fail(
            "Timed out: _listen_loop hung because the surviving PubSub "
            "listener was never cancelled after the queue listener exited. "
            "This is the asyncio.gather bug."
        )


@pytest.mark.asyncio
async def test_pubsub_listener_normal_exit_cancels_queue_listener():
    """When pubsub listener returns normally, queue listener must be cancelled."""
    dispatcher = _make_dispatcher()

    async def long_running_queue(r):
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            return

    async def silently_exiting_pubsub(r):
        """Simulate pubsub listener disconnecting and returning normally."""
        return

    async def counting_listen_loop():
        call_count = 0

        async def counting_pubsub(r):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                dispatcher._stop_event.set()
            return

        with patch.object(dispatcher, "_pubsub_listener", side_effect=counting_pubsub):
            with patch.object(dispatcher, "_queue_listener", side_effect=long_running_queue):
                with patch("agents.utils.dispatcher.get_shared_redis_client", return_value=MagicMock()):
                    await dispatcher._listen_loop()

    try:
        await asyncio.wait_for(counting_listen_loop(), timeout=5.0)
    except asyncio.TimeoutError:
        pytest.fail(
            "Timed out: _listen_loop hung because the surviving queue "
            "listener was never cancelled after the PubSub listener exited."
        )


@pytest.mark.asyncio
async def test_listener_exception_also_triggers_restart():
    """When a listener raises an exception, the other is cancelled and both restart.

    This case already works with asyncio.gather (exceptions propagate), but
    we test it to ensure the new implementation doesn't regress.
    The backoff sleep is ~5-6s, so we need a generous timeout.
    """
    dispatcher = _make_dispatcher()

    async def long_running_pubsub(r):
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            return

    async def counting_listen_loop():
        call_count = 0

        async def counting_queue(r):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                # After one crash+reconnect cycle, stop cleanly
                dispatcher._stop_event.set()
                return
            raise RuntimeError("pool exhaustion")

        with patch.object(dispatcher, "_pubsub_listener", side_effect=long_running_pubsub):
            with patch.object(dispatcher, "_queue_listener", side_effect=counting_queue):
                with patch("agents.utils.dispatcher.get_shared_redis_client", return_value=MagicMock()):
                    await dispatcher._listen_loop()

    # Backoff is 5s + jitter after first crash, so need >7s timeout
    try:
        await asyncio.wait_for(counting_listen_loop(), timeout=15.0)
    except asyncio.TimeoutError:
        pytest.fail("Timed out: listener exception did not trigger restart.")
