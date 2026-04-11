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

"""Tests for dispatcher Redis reconnect backoff behavior."""

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.utils.dispatcher import RedisOrchestratorDispatcher


class TestDispatcherReconnectBackoff:
    """Tests for exponential backoff in _listen_loop reconnect."""

    def _make_dispatcher(self) -> RedisOrchestratorDispatcher:
        """Create a dispatcher with minimal mocks for testing."""
        runner = MagicMock()
        runner.app_name = "test-agent"
        d = RedisOrchestratorDispatcher(runner, redis_url="redis://localhost:6379")
        d._stop_event = threading.Event()
        return d

    @pytest.mark.asyncio
    async def test_reconnect_uses_exponential_backoff(self):
        """Reconnect delay should increase exponentially after failures."""
        d = self._make_dispatcher()

        sleep_values: list[float] = []

        async def capture_sleep(seconds: float) -> None:
            sleep_values.append(seconds)
            if len(sleep_values) >= 4:
                d._stop_event.set()

        mock_client = AsyncMock()
        # Make gather raise to trigger reconnect
        with (
            patch(
                "agents.utils.dispatcher.get_shared_redis_client",
                return_value=mock_client,
            ),
            patch.object(d, "_pubsub_listener", side_effect=ConnectionError("refused")),
            patch.object(d, "_queue_listener", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=capture_sleep),
        ):
            await d._listen_loop()

            assert len(sleep_values) == 4
            assert 5.0 <= sleep_values[0] <= 6.25
            assert 10.0 <= sleep_values[1] <= 12.5
            assert 20.0 <= sleep_values[2] <= 25.0
            assert 40.0 <= sleep_values[3] <= 50.0

    @pytest.mark.asyncio
    async def test_backoff_caps_at_60_seconds(self):
        """Backoff should never exceed 60 seconds (+ jitter)."""
        d = self._make_dispatcher()

        sleep_values: list[float] = []

        async def capture_sleep(seconds: float) -> None:
            sleep_values.append(seconds)
            if len(sleep_values) >= 6:
                d._stop_event.set()

        mock_client = AsyncMock()
        with (
            patch(
                "agents.utils.dispatcher.get_shared_redis_client",
                return_value=mock_client,
            ),
            patch.object(d, "_pubsub_listener", side_effect=ConnectionError("refused")),
            patch.object(d, "_queue_listener", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=capture_sleep),
        ):
            await d._listen_loop()

            for val in sleep_values:
                assert val <= 75.0, f"Sleep value {val} exceeds cap"

    @pytest.mark.asyncio
    async def test_backoff_resets_on_successful_connection(self):
        """After a successful connection cycle, backoff should reset."""
        d = self._make_dispatcher()

        sleep_values: list[float] = []
        call_count = 0

        async def capture_sleep(seconds: float) -> None:
            sleep_values.append(seconds)
            if len(sleep_values) >= 3:
                d._stop_event.set()

        async def flaky_pubsub(r):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Second iteration succeeds (returns normally)
                return
            raise ConnectionError("refused")

        mock_client = AsyncMock()
        with (
            patch(
                "agents.utils.dispatcher.get_shared_redis_client",
                return_value=mock_client,
            ),
            patch.object(d, "_pubsub_listener", side_effect=flaky_pubsub),
            patch.object(d, "_queue_listener", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=capture_sleep),
        ):
            await d._listen_loop()

            assert 5.0 <= sleep_values[0] <= 6.25
            # After success, backoff resets -- next failure should be ~5 again
            assert 5.0 <= sleep_values[1] <= 6.25

    @pytest.mark.asyncio
    async def test_handles_none_redis_client(self):
        """Should sleep and retry when shared client returns None."""
        d = self._make_dispatcher()

        sleep_values: list[float] = []

        async def capture_sleep(seconds: float) -> None:
            sleep_values.append(seconds)
            if len(sleep_values) >= 2:
                d._stop_event.set()

        with (
            patch(
                "agents.utils.dispatcher.get_shared_redis_client",
                return_value=None,
            ),
            patch("asyncio.sleep", side_effect=capture_sleep),
        ):
            await d._listen_loop()

            # Should have slept (waiting for Redis to become available)
            assert len(sleep_values) >= 1
