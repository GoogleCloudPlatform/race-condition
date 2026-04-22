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

"""Tests for the distributed simulation registry."""

from unittest.mock import AsyncMock, patch

import pytest

from agents.utils.simulation_registry import (
    clear,
    get_context_id,
    lookup,
    register,
    register_context,
    unregister,
    _context_map,
    _local,
)


class TestSimulationRegistry:
    """Tests for the simulation_registry module.

    When Redis is unavailable (tests), the registry falls back to the
    process-local L1 cache.  These tests verify the local-only path.
    """

    @pytest.fixture(autouse=True)
    async def _clear(self):
        """Clear registry before each test."""
        _local.clear()
        yield
        _local.clear()

    @pytest.mark.asyncio
    async def test_register_and_lookup(self):
        """register() should store and lookup() should retrieve."""
        await register("session-1", "sim-abc")
        assert await lookup("session-1") == "sim-abc"

    @pytest.mark.asyncio
    async def test_lookup_unknown_returns_none(self):
        """lookup() on an unknown session should return None."""
        assert await lookup("nonexistent") is None

    @pytest.mark.asyncio
    async def test_unregister(self):
        """unregister() should remove the entry."""
        await register("session-1", "sim-abc")
        await unregister("session-1")
        assert await lookup("session-1") is None

    @pytest.mark.asyncio
    async def test_unregister_unknown_is_noop(self):
        """unregister() on an unknown session should not raise."""
        await unregister("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_clear(self):
        """clear() should remove all entries."""
        await register("s1", "sim-1")
        await register("s2", "sim-2")
        await clear()
        assert await lookup("s1") is None
        assert await lookup("s2") is None

    @pytest.mark.asyncio
    async def test_multiple_sessions_same_simulation(self):
        """Multiple sessions can map to the same simulation_id."""
        await register("s1", "sim-shared")
        await register("s2", "sim-shared")
        await register("s3", "sim-shared")
        assert await lookup("s1") == "sim-shared"
        assert await lookup("s2") == "sim-shared"
        assert await lookup("s3") == "sim-shared"

    @pytest.mark.asyncio
    async def test_overwrite_existing(self):
        """Re-registering a session should overwrite the previous value."""
        await register("session-1", "sim-old")
        await register("session-1", "sim-new")
        assert await lookup("session-1") == "sim-new"


class TestSimulationRegistryRedis:
    """Tests for the Redis-backed cross-instance behavior.

    After the HASH→STRING migration, each session/context gets its own
    Redis key with a 10-minute TTL (SETEX) instead of living in a
    shared hash.
    """

    @pytest.fixture(autouse=True)
    async def _clear(self):
        """Clear registry before each test."""
        _local.clear()
        _context_map.clear()
        yield
        _local.clear()
        _context_map.clear()

    @pytest.mark.asyncio
    async def test_lookup_falls_back_to_redis(self):
        """lookup() should GET per-key STRING when L1 cache is empty."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"sim-cross-uuid")

        with patch(
            "agents.utils.simulation_registry.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = await lookup("session-from-other-instance")

        assert result == "sim-cross-uuid"
        mock_redis.get.assert_awaited_once_with("simreg:session:session-from-other-instance")
        # L1 should be warmed
        assert _local.get("session-from-other-instance") == "sim-cross-uuid"

    @pytest.mark.asyncio
    async def test_register_writes_to_redis(self):
        """register() should SETEX per-key STRING with 7200s TTL (2 hours)."""
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        with patch(
            "agents.utils.simulation_registry.get_shared_redis_client",
            return_value=mock_redis,
        ):
            await register("sess-1", "sim-1")

        mock_redis.setex.assert_awaited_once_with("simreg:session:sess-1", 7200, "sim-1")
        assert _local["sess-1"] == "sim-1"

    @pytest.mark.asyncio
    async def test_clear_deletes_redis_keys(self):
        """clear() should SCAN both prefixes and DELETE matching keys."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        async def mock_scan_session(*args, **kwargs):
            for key in [b"simreg:session:s1", b"simreg:session:s2"]:
                yield key

        async def mock_scan_context(*args, **kwargs):
            for key in [b"simreg:context:v1"]:
                yield key

        # scan_iter returns different results based on match pattern
        call_count = 0

        def scan_iter_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            match = kwargs.get("match", args[0] if args else "")
            if "session" in match:
                return mock_scan_session()
            return mock_scan_context()

        mock_redis.scan_iter = scan_iter_side_effect

        with patch(
            "agents.utils.simulation_registry.get_shared_redis_client",
            return_value=mock_redis,
        ):
            _local["a"] = "b"
            _context_map["c"] = "d"
            await clear()

        assert len(_local) == 0
        assert len(_context_map) == 0
        # Batched deletes: 2 session keys in one call, 1 context key in another
        assert mock_redis.delete.await_count == 2
        # Verify all keys were included across the batched calls
        all_deleted_keys = []
        for call in mock_redis.delete.await_args_list:
            all_deleted_keys.extend(call.args)
        assert set(all_deleted_keys) == {
            b"simreg:session:s1",
            b"simreg:session:s2",
            b"simreg:context:v1",
        }

    @pytest.mark.asyncio
    async def test_lookup_prefers_l1_over_redis(self):
        """lookup() should return L1 value without hitting Redis."""
        mock_redis = AsyncMock()

        _local["cached-sess"] = "cached-sim"

        with patch(
            "agents.utils.simulation_registry.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = await lookup("cached-sess")

        assert result == "cached-sim"
        # Should NOT have called Redis
        mock_redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_unregister_deletes_redis_key(self):
        """unregister() should DELETE the per-key STRING from Redis."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        _local["sess-1"] = "sim-1"

        with patch(
            "agents.utils.simulation_registry.get_shared_redis_client",
            return_value=mock_redis,
        ):
            await unregister("sess-1")

        mock_redis.delete.assert_awaited_once_with("simreg:session:sess-1")
        assert "sess-1" not in _local

    @pytest.mark.asyncio
    async def test_register_context_uses_setex(self):
        """register_context() should SETEX per-key STRING with 7200s TTL (2 hours)."""
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        with patch(
            "agents.utils.simulation_registry.get_shared_redis_client",
            return_value=mock_redis,
        ):
            await register_context("vsess-1", "ctx-1")

        mock_redis.setex.assert_awaited_once_with("simreg:context:vsess-1", 7200, "ctx-1")
        assert _context_map["vsess-1"] == "ctx-1"

    @pytest.mark.asyncio
    async def test_get_context_id_uses_get(self):
        """get_context_id() should GET per-key STRING from Redis."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"ctx-1")

        with patch(
            "agents.utils.simulation_registry.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = await get_context_id("vsess-1")

        assert result == "ctx-1"
        mock_redis.get.assert_awaited_once_with("simreg:context:vsess-1")
        # L1 should be warmed
        assert _context_map.get("vsess-1") == "ctx-1"
