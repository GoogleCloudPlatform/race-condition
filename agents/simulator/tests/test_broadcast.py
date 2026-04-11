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

"""Tests for the simulator Redis broadcast helper."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.simulator.broadcast import publish_to_runners, wait_for_runners_ready


class TestPublishToRunners:
    """Tests for publish_to_runners helper."""

    @pytest.mark.asyncio
    async def test_wraps_data_in_broadcast_envelope(self):
        """The published message should be a broadcast envelope with data inside payload."""
        mock_redis = AsyncMock()
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ):
            await publish_to_runners('{"event":"tick","tick":1}', simulation_id="sim-test")

            raw = mock_redis.publish.call_args[0][1]
            envelope = json.loads(raw)
            assert envelope["type"] == "broadcast"
            assert "eventId" in envelope
            inner = envelope["payload"]["data"]
            assert inner == '{"event":"tick","tick":1}'

    @pytest.mark.asyncio
    async def test_handles_redis_failure_gracefully(self):
        """Redis errors should be logged, not raised."""
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            side_effect=ConnectionError("connection refused"),
        ):
            # Should not raise
            await publish_to_runners("data", simulation_id="sim-test")

    @pytest.mark.asyncio
    async def test_handles_none_client(self):
        """Should silently return if no Redis client available."""
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=None,
        ):
            # Should not raise
            await publish_to_runners("data", simulation_id="sim-test")

    @pytest.mark.asyncio
    async def test_swallows_publish_errors(self):
        """Publish errors should be logged, not raised."""
        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = Exception("publish failed")
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ):
            # Should not raise
            await publish_to_runners("data", simulation_id="sim-test")

    @pytest.mark.asyncio
    async def test_uses_shared_redis_client(self):
        """Should delegate to the shared pool, not create its own client."""
        mock_redis = AsyncMock()
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ) as mock_get:
            await publish_to_runners("data", simulation_id="sim-test")
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_publishes_to_scoped_channel_when_simulation_id_provided(self):
        """When simulation_id is given, publish to simulation:{id}:broadcast."""
        mock_redis = AsyncMock()
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ):
            await publish_to_runners("test-payload", simulation_id="sim-abc")

            mock_redis.publish.assert_called_once()
            channel = mock_redis.publish.call_args[0][0]
            assert channel == "simulation:sim-abc:broadcast"

    @pytest.mark.asyncio
    async def test_envelope_includes_exclude_runner_ids(self):
        """When exclude_runner_ids is provided, it should appear in the envelope payload."""
        mock_redis = AsyncMock()
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ):
            await publish_to_runners(
                "test-payload",
                simulation_id="sim-1",
                exclude_runner_ids=["runner-a", "runner-b"],
            )

            raw = mock_redis.publish.call_args[0][1]
            envelope = json.loads(raw)
            assert envelope["payload"]["exclude_runner_ids"] == ["runner-a", "runner-b"]

    @pytest.mark.asyncio
    async def test_envelope_omits_exclude_runner_ids_when_none(self):
        """When exclude_runner_ids is None, it should not appear in the envelope."""
        mock_redis = AsyncMock()
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ):
            await publish_to_runners("test-payload", simulation_id="sim-1")

            raw = mock_redis.publish.call_args[0][1]
            envelope = json.loads(raw)
            assert "exclude_runner_ids" not in envelope["payload"]

    @pytest.mark.asyncio
    async def test_envelope_omits_exclude_runner_ids_when_empty(self):
        """When exclude_runner_ids is an empty list, it should not appear in the envelope."""
        mock_redis = AsyncMock()
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ):
            await publish_to_runners(
                "test-payload",
                simulation_id="sim-1",
                exclude_runner_ids=[],
            )

            raw = mock_redis.publish.call_args[0][1]
            envelope = json.loads(raw)
            assert "exclude_runner_ids" not in envelope["payload"]


class TestWaitForRunnersReady:
    """Tests for wait_for_runners_ready helper."""

    @pytest.mark.asyncio
    async def test_returns_count_when_all_registered(self):
        """Should return expected count when all sessions are registered."""
        mock_redis = AsyncMock()
        sim_id = "sim-123"
        session_ids = ["s1", "s2", "s3"]
        mock_redis.mget = AsyncMock(return_value=[sim_id, sim_id, sim_id])
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = await wait_for_runners_ready(session_ids, simulation_id=sim_id)
            assert result == 3

    @pytest.mark.asyncio
    async def test_excludes_wrong_simulation_id(self):
        """Should not count sessions registered for a different simulation."""
        mock_redis = AsyncMock()
        sim_id = "sim-123"
        session_ids = ["s1", "s2"]
        mock_redis.mget = AsyncMock(return_value=[sim_id, "wrong-sim"])
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = await wait_for_runners_ready(
                session_ids,
                simulation_id=sim_id,
                timeout_seconds=1,
            )
            assert result == 1

    @pytest.mark.asyncio
    async def test_returns_zero_without_redis_client(self):
        """Should return 0 when no Redis client is available."""
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=None,
        ):
            result = await wait_for_runners_ready(
                ["s1"],
                simulation_id="sim-1",
            )
            assert result == 0

    @pytest.mark.asyncio
    async def test_timeout_returns_partial_count(self):
        """Should return 0 after timeout when no sessions registered."""
        mock_redis = AsyncMock()
        mock_redis.mget = AsyncMock(return_value=[None, None])
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = await wait_for_runners_ready(
                ["s1", "s2"],
                simulation_id="sim-1",
                timeout_seconds=0.1,
            )
            assert result == 0

    @pytest.mark.asyncio
    async def test_uses_mget_with_per_key_prefix(self):
        """Should call MGET with simreg:session:{sid} keys, not HMGET."""
        mock_redis = AsyncMock()
        sim_id = "sim-123"
        session_ids = ["s1", "s2"]
        mock_redis.mget = AsyncMock(return_value=[sim_id, sim_id])
        with patch(
            "agents.simulator.broadcast.get_shared_redis_client",
            return_value=mock_redis,
        ):
            await wait_for_runners_ready(
                session_ids,
                simulation_id=sim_id,
                timeout_seconds=2,
            )
            mock_redis.mget.assert_called_with(
                "simreg:session:s1",
                "simreg:session:s2",
            )

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_session_list(self):
        """Should return 0 immediately for empty list."""
        result = await wait_for_runners_ready([], simulation_id="sim-1")
        assert result == 0
