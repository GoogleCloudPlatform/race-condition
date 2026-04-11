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

"""Tests for the publish batching worker in pulses.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.utils.pulses as pulses_mod


class TestPublishBatching:
    def setup_method(self) -> None:
        pulses_mod.reset()

    def teardown_method(self) -> None:
        pulses_mod.reset()

    @pytest.mark.asyncio
    async def test_messages_are_batched_via_pipeline(self) -> None:
        """Putting 10 messages should result in 1 pipeline.execute() call."""
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=False)

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        with patch.object(pulses_mod, "_get_redis_client", return_value=mock_redis):
            # Enqueue 10 messages
            for i in range(10):
                await pulses_mod._publish_to_gateway(f"msg-{i}".encode())

            # Give the worker time to drain the queue
            await asyncio.sleep(0.1)

        # Pipeline should have been used at least once
        mock_redis.pipeline.assert_called()
        # All messages should have been published
        assert mock_pipeline.publish.call_count == 10
        # But execute should have been called far fewer times than 10
        assert mock_pipeline.execute.call_count < 10

    @pytest.mark.asyncio
    async def test_queue_full_drops_gracefully(self) -> None:
        """When the queue is full, new messages should be dropped, not crash."""
        mock_redis = MagicMock()

        with patch.object(pulses_mod, "_get_redis_client", return_value=mock_redis):
            queue = pulses_mod._get_queue()
            # Fill the queue to capacity
            for i in range(queue.maxsize):
                queue.put_nowait(f"fill-{i}".encode())

            # This should NOT raise -- should log a warning and drop
            await pulses_mod._publish_to_gateway(b"overflow-message")

        # Queue should still be at capacity (overflow was dropped)
        queue = pulses_mod._get_queue()
        assert queue.qsize() == queue.maxsize

    @pytest.mark.asyncio
    async def test_worker_starts_on_first_publish(self) -> None:
        """The background worker pool should be created on first _publish_to_gateway call."""
        assert len(pulses_mod._worker_tasks) == 0

        mock_redis = MagicMock()

        with patch.object(pulses_mod, "_get_redis_client", return_value=mock_redis):
            await pulses_mod._publish_to_gateway(b"trigger")

        assert len(pulses_mod._worker_tasks) == pulses_mod._NUM_PUBLISH_WORKERS
        assert all(not t.done() for t in pulses_mod._worker_tasks)

    @pytest.mark.asyncio
    async def test_worker_continues_after_pipeline_error(self) -> None:
        """Worker should keep processing after a pipeline.execute() failure."""
        call_count = 0

        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=False)

        original_execute = mock_pipeline.execute

        async def execute_side_effect() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Simulated Redis failure")
            return await original_execute()

        mock_pipeline.execute = AsyncMock(side_effect=execute_side_effect)

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        with patch.object(pulses_mod, "_get_redis_client", return_value=mock_redis):
            # First message will trigger a pipeline error
            await pulses_mod._publish_to_gateway(b"msg-fail")
            await asyncio.sleep(0.1)

            # Second message should still be processed
            await pulses_mod._publish_to_gateway(b"msg-ok")
            await asyncio.sleep(0.1)

        # Worker should have attempted pipeline at least twice
        assert mock_pipeline.execute.call_count >= 2
        # Workers should still be alive
        assert len(pulses_mod._worker_tasks) > 0
        assert any(not t.done() for t in pulses_mod._worker_tasks)

    @pytest.mark.asyncio
    async def test_worker_logs_when_redis_client_is_none(self) -> None:
        """Worker should log a warning when Redis client is unavailable."""
        with patch.object(pulses_mod, "_get_redis_client", return_value=None):
            await pulses_mod._publish_to_gateway(b"orphaned-message")
            await asyncio.sleep(0.1)

        # Workers should still be alive (not crashed)
        assert len(pulses_mod._worker_tasks) > 0
        assert any(not t.done() for t in pulses_mod._worker_tasks)
        # Queue should be empty (message was consumed and dropped)
        assert pulses_mod._get_queue().empty()

    @pytest.mark.asyncio
    async def test_multiple_workers_drain_concurrently(self) -> None:
        """Multiple workers should drain the queue in parallel."""
        mock_redis = MagicMock()
        mock_pipe = AsyncMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch.object(pulses_mod, "_get_redis_client", return_value=mock_redis):
            # Queue 400 messages
            queue = pulses_mod._get_queue()
            for i in range(400):
                queue.put_nowait(f"msg-{i}".encode())

            # Start workers (should be 4 by default)
            await pulses_mod._ensure_worker()
            # Give workers time to drain
            await asyncio.sleep(0.5)

        # With 4 workers, we expect multiple pipeline.execute() calls
        # (each worker batches up to 100)
        assert mock_pipe.execute.call_count >= 4, (
            f"Expected at least 4 execute() calls with 4 workers, got {mock_pipe.execute.call_count}"
        )

        assert pulses_mod._get_queue().empty(), "Queue should be fully drained"


class TestPublishQueueReset:
    """Verify lazy-init Queue works across event loops."""

    def test_reset_clears_queue_and_workers(self):
        """After reset(), queue is None and workers are empty."""
        import agents.utils.pulses as mod

        mod.reset()
        assert mod._publish_queue is None
        assert mod._worker_tasks == []


def test_publish_workers_count():
    """NUM_PUBLISH_WORKERS should be 16 for high-throughput simulations."""
    from agents.utils.pulses import _NUM_PUBLISH_WORKERS

    assert _NUM_PUBLISH_WORKERS == 16
