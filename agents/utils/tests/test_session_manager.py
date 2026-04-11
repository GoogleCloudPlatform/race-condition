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

"""Tests for SessionManager — cross-worker session mapping via Redis L2 cache.

Verifies that the context_id → session_id mapping is shared across workers
via Redis, with graceful fallback to in-process TTLCache when Redis is
unavailable.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture()
def mock_session_service():
    """Mock session service that returns sessions with incrementing IDs."""
    service = AsyncMock()
    call_count = 0

    async def create_session(*, app_name, user_id):
        nonlocal call_count
        call_count += 1
        return SimpleNamespace(id=f"vertex-session-{call_count}")

    service.create_session = AsyncMock(side_effect=create_session)
    return service


@pytest.fixture()
def mock_redis():
    """Mock async Redis client with in-memory dict backing."""
    store: dict[str, bytes] = {}
    client = AsyncMock()

    async def redis_get(key):
        return store.get(key)

    async def redis_setex(key, ttl, value):
        store[key] = value if isinstance(value, bytes) else value.encode()

    client.get = AsyncMock(side_effect=redis_get)
    client.setex = AsyncMock(side_effect=redis_setex)
    client._test_store = store  # expose for assertions
    return client


class TestSessionManagerRedisL2:
    """When Redis is available, SessionManager shares mappings across workers."""

    @pytest.mark.asyncio
    async def test_stores_mapping_in_redis_on_create(self, mock_session_service, mock_redis):
        """New session mapping is stored in both L1 (TTLCache) and L2 (Redis)."""
        from agents.utils.session_manager import SessionManager

        with patch("agents.utils.session_manager.get_shared_redis_client", return_value=mock_redis):
            mgr = SessionManager(session_service=mock_session_service)

        session_id = await mgr.get_or_create_session(context_id="ctx-001", app_name="test", user_id="user1")

        assert session_id == "vertex-session-1"
        # L1 cache populated
        assert mgr.session_cache.get("ctx-001") == "vertex-session-1"
        # L2 Redis populated
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "session_map:ctx-001"
        assert call_args[0][2] == "vertex-session-1"

    @pytest.mark.asyncio
    async def test_redis_hit_avoids_session_creation(self, mock_session_service, mock_redis):
        """When L1 misses but Redis has the mapping, no new session is created."""
        from agents.utils.session_manager import SessionManager

        # Pre-populate Redis with existing mapping
        mock_redis._test_store["session_map:ctx-002"] = b"existing-vertex-session"

        with patch("agents.utils.session_manager.get_shared_redis_client", return_value=mock_redis):
            mgr = SessionManager(session_service=mock_session_service)

        session_id = await mgr.get_or_create_session(context_id="ctx-002", app_name="test", user_id="user1")

        assert session_id == "existing-vertex-session"
        mock_session_service.create_session.assert_not_called()
        # L1 cache should be populated from Redis hit
        assert mgr.session_cache.get("ctx-002") == "existing-vertex-session"

    @pytest.mark.asyncio
    async def test_cross_worker_session_continuity(self, mock_session_service, mock_redis):
        """Two SessionManager instances (simulating workers) share via Redis."""
        from agents.utils.session_manager import SessionManager

        with patch("agents.utils.session_manager.get_shared_redis_client", return_value=mock_redis):
            worker1 = SessionManager(session_service=mock_session_service)
            worker2 = SessionManager(session_service=mock_session_service)

        # Worker 1 creates the session
        sid1 = await worker1.get_or_create_session(context_id="ctx-003", app_name="test", user_id="user1")

        # Worker 2 resolves the SAME session via Redis
        sid2 = await worker2.get_or_create_session(context_id="ctx-003", app_name="test", user_id="user1")

        assert sid1 == sid2 == "vertex-session-1"
        # Only ONE session was created (not two)
        assert mock_session_service.create_session.call_count == 1


class TestSessionManagerDefaultTTL:
    """Verify default TTL is 600 seconds (10 minutes)."""

    @pytest.mark.asyncio
    async def test_default_redis_ttl_is_7200_seconds(self, mock_session_service, mock_redis):
        """SETEX should be called with TTL=7200 (2 hours) by default."""
        from agents.utils.session_manager import SessionManager

        with patch("agents.utils.session_manager.get_shared_redis_client", return_value=mock_redis):
            mgr = SessionManager(session_service=mock_session_service)

        await mgr.get_or_create_session(context_id="ctx-ttl", app_name="test", user_id="user1")

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        # Second positional arg is the TTL
        assert call_args[0][1] == 7200, f"Expected TTL=7200, got {call_args[0][1]}"

    @pytest.mark.asyncio
    async def test_default_ttl_cache_ttl_is_7200(self, mock_session_service, mock_redis):
        """TTLCache should default to 7200s TTL (2 hours)."""
        from agents.utils.session_manager import SessionManager

        with patch("agents.utils.session_manager.get_shared_redis_client", return_value=mock_redis):
            mgr = SessionManager(session_service=mock_session_service)

        assert mgr.session_cache._ttl == 7200, f"Expected TTLCache TTL=7200, got {mgr.session_cache._ttl}"


class TestSessionManagerNoRedis:
    """When Redis is unavailable, SessionManager falls back to L1-only."""

    @pytest.mark.asyncio
    async def test_no_redis_still_works(self, mock_session_service):
        """Without Redis, sessions are created normally (L1-only)."""
        from agents.utils.session_manager import SessionManager

        with patch("agents.utils.session_manager.get_shared_redis_client", return_value=None):
            mgr = SessionManager(session_service=mock_session_service)

        session_id = await mgr.get_or_create_session(context_id="ctx-004", app_name="test", user_id="user1")

        assert session_id == "vertex-session-1"
        assert mgr.session_cache.get("ctx-004") == "vertex-session-1"

    @pytest.mark.asyncio
    async def test_redis_error_degrades_gracefully(self, mock_session_service):
        """Redis connection errors don't crash — fall back to creating a session."""
        from agents.utils.session_manager import SessionManager

        broken_redis = AsyncMock()
        broken_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        broken_redis.setex = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("agents.utils.session_manager.get_shared_redis_client", return_value=broken_redis):
            mgr = SessionManager(session_service=mock_session_service)

        session_id = await mgr.get_or_create_session(context_id="ctx-005", app_name="test", user_id="user1")

        # Should still work — just without Redis L2
        assert session_id == "vertex-session-1"
        assert mgr.session_cache.get("ctx-005") == "vertex-session-1"
