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

"""Tests for RaceCollector utility."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gen_proto.gateway import gateway_pb2

from redis.exceptions import ConnectionError as RedisConnectionError

from agents.simulator.collector import RaceCollector, _DrainProxy


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------
class TestRaceCollectorLifecycle:
    """Test start registers instance, stop removes instance, get returns proxy for unknown."""

    @pytest.mark.asyncio
    async def test_start_registers_instance(self):
        """start() should register the collector in the module-level registry."""
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="sim-1",
                runner_session_ids={"runner-a"},
            )

            assert RaceCollector.get("sim-1") is collector

            # cleanup
            await collector.stop()

    @pytest.mark.asyncio
    async def test_stop_removes_instance(self):
        """stop() should remove the collector from the registry."""
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="sim-2",
                runner_session_ids={"runner-b"},
            )

            await collector.stop()

            # After stop, get() should return a DrainProxy (not the local instance)
            result = RaceCollector.get("sim-2")
            assert not isinstance(result, RaceCollector)

    @pytest.mark.asyncio
    async def test_uses_shared_redis_client(self):
        """RaceCollector should use the shared pool, not create its own client."""
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="test-session",
                runner_session_ids={"r1"},
            )
            # Verify it used the shared client
            assert collector._redis is mock_redis
            await collector.stop()

    def test_get_returns_proxy_when_no_local_collector(self):
        """get() should return a _DrainProxy when no local collector exists."""
        mock_redis = AsyncMock()
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = RaceCollector.get("nonexistent-session")
            assert isinstance(result, _DrainProxy)

    def test_get_returns_none_without_redis(self):
        """get() should return None when Redis is unavailable."""
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=None,
        ):
            assert RaceCollector.get("any-session") is None


# ---------------------------------------------------------------------------
# Graceful stop tests
# ---------------------------------------------------------------------------
class TestGracefulStop:
    """Test that stop() handles broken Redis connections gracefully.

    After cancelling the PubSub reader task, the connection may be in a
    corrupted state. Teardown must not propagate errors.
    """

    @pytest.mark.asyncio
    async def test_stop_does_not_call_unsubscribe(self):
        """stop() should NOT call unsubscribe() — server cleans up on close."""
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="graceful-1",
                runner_session_ids={"r1"},
            )
            await collector.stop()

        mock_pubsub.unsubscribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_survives_pubsub_close_error(self):
        """stop() should complete even if PubSub close() raises ConnectionError."""
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_pubsub.close = AsyncMock(side_effect=RedisConnectionError("Connection closed by server."))
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="graceful-2",
                runner_session_ids={"r1"},
            )
            # Must not raise
            await collector.stop()

        # Verify cleanup still happened
        assert not RaceCollector.is_running("graceful-2")

    @pytest.mark.asyncio
    async def test_stop_survives_redis_delete_error(self):
        """stop() should complete even if Redis delete() raises ConnectionError."""
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        mock_redis.delete = AsyncMock(side_effect=RedisConnectionError("Connection closed by server."))
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="graceful-3",
                runner_session_ids={"r1"},
            )
            # Must not raise
            await collector.stop()

        assert not RaceCollector.is_running("graceful-3")

    @pytest.mark.asyncio
    async def test_drain_proxy_stop_survives_connection_error(self):
        """_DrainProxy.stop() should handle ConnectionError from delete gracefully."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(side_effect=RedisConnectionError("Connection closed by server."))

        proxy = _DrainProxy("graceful-4", mock_redis)
        # Must not raise
        await proxy.stop()


# ---------------------------------------------------------------------------
# Drain tests (Redis-backed)
# ---------------------------------------------------------------------------
class TestRaceCollectorDrain:
    """Test drain reads from Redis list buffer, clears after read."""

    @pytest.mark.asyncio
    async def test_drain_returns_buffered_messages(self):
        """drain() should return messages from the Redis buffer."""
        msgs = [{"session_id": "r1", "event": "tick"}]
        mock_pipeline = AsyncMock()
        mock_pipeline.lrange = MagicMock()
        mock_pipeline.delete = MagicMock()
        mock_pipeline.execute = AsyncMock(
            return_value=[
                [json.dumps(m).encode() for m in msgs],
                1,
            ]
        )

        mock_redis = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        proxy = _DrainProxy("sim-1", mock_redis)
        result = await proxy.drain()

        assert result == msgs

    @pytest.mark.asyncio
    async def test_drain_empty_returns_empty_list(self):
        """drain() on an empty buffer should return an empty list."""
        mock_pipeline = AsyncMock()
        mock_pipeline.lrange = MagicMock()
        mock_pipeline.delete = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=[[], 0])

        mock_redis = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        proxy = _DrainProxy("sim-1", mock_redis)
        result = await proxy.drain()

        assert result == []

    @pytest.mark.asyncio
    async def test_cross_instance_drain(self):
        """A _DrainProxy should read from the same Redis list the collector writes to.

        This is the critical multi-instance scenario: Instance A pushes to
        the Redis buffer, Instance B drains it via a _DrainProxy.
        """
        buffer_data = [
            {"session_id": "runner-1", "payload": {"tool_name": "process_tick"}},
            {"session_id": "runner-2", "payload": {"tool_name": "process_tick"}},
        ]
        encoded = [json.dumps(m).encode() for m in buffer_data]

        mock_pipeline = AsyncMock()
        mock_pipeline.lrange = MagicMock()
        mock_pipeline.delete = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=[encoded, 1])

        mock_redis = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        # Simulate Instance B: no local collector, just a proxy
        proxy = _DrainProxy("sim-session-1", mock_redis)
        messages = await proxy.drain()

        assert len(messages) == 2
        assert messages[0]["session_id"] == "runner-1"
        assert messages[1]["session_id"] == "runner-2"


# ---------------------------------------------------------------------------
# Filter tests (using real protobuf)
# ---------------------------------------------------------------------------
class TestRaceCollectorFilter:
    """Test _parse_wrapper filters by session_id and rejects non-runner sessions."""

    def _make_collector(self, runner_session_ids: set[str]) -> RaceCollector:
        """Create a RaceCollector bypassing __init__ for filter testing."""
        collector = RaceCollector.__new__(RaceCollector)
        collector.runner_session_ids = runner_session_ids
        return collector

    def test_parse_wrapper_filters_by_session_id(self):
        """_parse_wrapper should return a dict for matching runner session_ids."""
        collector = self._make_collector({"runner-a", "runner-b"})

        payload_data = json.dumps({"key": "value"}).encode()
        wrapper = gateway_pb2.Wrapper(
            timestamp="2026-03-16T00:00:00Z",
            type="agent_response",
            session_id="runner-a",
            event="tick",
            payload=payload_data,
            origin=gateway_pb2.Origin(
                type="agent",
                id="agent-1",
                session_id="runner-a",
            ),
        )

        result = collector._parse_wrapper(wrapper)

        assert result is not None
        assert result["session_id"] == "runner-a"
        assert result["agent_id"] == "agent-1"
        assert result["event"] == "tick"
        assert result["msg_type"] == "agent_response"
        assert result["timestamp"] == "2026-03-16T00:00:00Z"
        assert result["payload"] == {"key": "value"}

    def test_parse_wrapper_rejects_non_runner_sessions(self):
        """_parse_wrapper should return None for non-runner session_ids."""
        collector = self._make_collector({"runner-a"})

        wrapper = gateway_pb2.Wrapper(
            timestamp="2026-03-16T00:00:00Z",
            type="agent_response",
            session_id="other-session",
            event="tick",
            payload=b"{}",
            origin=gateway_pb2.Origin(
                type="agent",
                id="agent-2",
                session_id="other-session",
            ),
        )

        result = collector._parse_wrapper(wrapper)

        assert result is None


# ---------------------------------------------------------------------------
# skip_pubsub flag tests (Change 4)
# ---------------------------------------------------------------------------
class TestSkipPubSub:
    """Test that skip_pubsub=True prevents _collect_loop from starting."""

    @pytest.mark.asyncio
    async def test_skip_pubsub_does_not_subscribe(self):
        """start(skip_pubsub=True) should not create PubSub subscription."""
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="skip-ps-1",
                runner_session_ids={"runner-a"},
                skip_pubsub=True,
            )

            # PubSub should NOT have been created or subscribed
            assert collector._pubsub is None
            assert collector._task is None
            assert collector.skip_pubsub is True

            # Should still be registered
            assert RaceCollector.get("skip-ps-1") is collector

            await collector.stop()

    @pytest.mark.asyncio
    async def test_skip_pubsub_does_not_start_collect_loop(self):
        """start(skip_pubsub=True) must not create a background task."""
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="skip-ps-2",
                runner_session_ids={"runner-a"},
                skip_pubsub=True,
            )

            # No background task
            assert collector._task is None

            # pubsub() should not have been called at all
            mock_redis.pubsub.assert_not_called()

            await collector.stop()

    @pytest.mark.asyncio
    async def test_skip_pubsub_drain_still_works(self):
        """With skip_pubsub=True, drain() should still read from Redis buffer."""
        msgs = [{"session_id": "r1", "event": "tick"}]
        mock_pipeline = AsyncMock()
        mock_pipeline.lrange = MagicMock()
        mock_pipeline.delete = MagicMock()
        mock_pipeline.execute = AsyncMock(
            return_value=[
                [json.dumps(m).encode() for m in msgs],
                1,
            ]
        )

        mock_redis = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_redis.pubsub = MagicMock(return_value=AsyncMock())

        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="skip-ps-3",
                runner_session_ids={"r1"},
                skip_pubsub=True,
            )
            result = await collector.drain()

            assert result == msgs
            await collector.stop()

    @pytest.mark.asyncio
    async def test_default_does_subscribe(self):
        """start() without skip_pubsub should create PubSub subscription (baseline)."""
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="no-skip-1",
                runner_session_ids={"runner-a"},
            )

            # PubSub SHOULD have been created
            assert collector._pubsub is not None
            assert collector._task is not None
            assert collector.skip_pubsub is False

            await collector.stop()


# ---------------------------------------------------------------------------
# TTL tests
# ---------------------------------------------------------------------------
class TestActiveMarkerTTL:
    """Test that the active marker is set with 7200s (2 hour) TTL."""

    @pytest.mark.asyncio
    async def test_start_sets_active_marker_with_7200s_ttl(self):
        """start() should set the active marker with ex=7200 (2 hours)."""
        mock_redis = AsyncMock()
        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="ttl-marker-1",
                runner_session_ids={"runner-a"},
                skip_pubsub=True,
            )

            # Verify r.set was called with key, value, and ex=7200
            mock_redis.set.assert_called_once_with("collector:active:ttl-marker-1", "1", ex=7200)

            await collector.stop()


# ---------------------------------------------------------------------------
# Buffer TTL tests
# ---------------------------------------------------------------------------
class TestBufferListTTL:
    """Test that buffer lists get a 7200s TTL after RPUSH as a crash-safety net."""

    @pytest.mark.asyncio
    async def test_collect_loop_sets_buffer_ttl_after_rpush(self):
        """After RPUSH in _collect_loop, expire() should be called with 7200s TTL.

        We start a real collector, inject one matching protobuf message via
        the PubSub mock, let the collect loop process it, then verify that
        both rpush AND expire were called on the buffer key.
        """
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        # Build a valid protobuf wrapper message
        wrapper = gateway_pb2.Wrapper(
            timestamp="2026-03-16T00:00:00Z",
            type="agent_response",
            session_id="runner-a",
            event="tick",
            payload=json.dumps({"key": "value"}).encode(),
            origin=gateway_pb2.Origin(
                type="agent",
                id="agent-1",
                session_id="runner-a",
            ),
        )
        serialized = wrapper.SerializeToString()

        # PubSub returns one message then blocks (CancelledError stops the loop)
        mock_pubsub.get_message = AsyncMock(
            side_effect=[
                {"type": "message", "data": serialized},
                asyncio.CancelledError(),
            ]
        )

        with patch(
            "agents.simulator.collector.get_shared_redis_client",
            return_value=mock_redis,
        ):
            collector = await RaceCollector.start(
                session_id="buf-ttl-1",
                runner_session_ids={"runner-a"},
            )

            # Give the background task a moment to process the message
            await asyncio.sleep(0.1)
            await collector.stop()

        # Verify rpush was called on the buffer key
        mock_redis.rpush.assert_called_once()
        rpush_key = mock_redis.rpush.call_args[0][0]
        assert rpush_key == "collector:buffer:buf-ttl-1"

        # Verify expire was called with 7200s TTL on the buffer key
        mock_redis.expire.assert_called_once_with("collector:buffer:buf-ttl-1", 7200)
