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

"""Tests for the shared Redis connection pool."""

import os
from unittest.mock import patch

import redis.asyncio as redis

import agents.utils.redis_pool as pool_mod


class TestGetSharedRedisClient:
    def setup_method(self):
        pool_mod._shared_client = None
        # Clear any leaked REDIS_MAX_CONNECTIONS from other test files
        os.environ.pop("REDIS_MAX_CONNECTIONS", None)

    def teardown_method(self):
        pool_mod._shared_client = None

    def test_returns_redis_client_with_capped_pool(self):
        """Shared client should have max_connections <= 20 (default)."""
        with patch.dict("os.environ", {"REDIS_ADDR": "127.0.0.1:6379"}):
            client = pool_mod.get_shared_redis_client()
            assert client is not None
            assert client.connection_pool.max_connections <= 20

    def test_pool_class_is_blocking(self):
        """Pool must be BlockingConnectionPool to queue callers instead of raising."""
        with patch.dict("os.environ", {"REDIS_ADDR": "127.0.0.1:6379"}):
            client = pool_mod.get_shared_redis_client()
            assert client is not None
            pool = client.connection_pool
            assert isinstance(pool, redis.BlockingConnectionPool), (
                f"Expected BlockingConnectionPool, got {type(pool).__name__}"
            )

    def test_pool_timeout_is_set(self):
        """BlockingConnectionPool should have a timeout so callers don't block forever."""
        with patch.dict("os.environ", {"REDIS_ADDR": "127.0.0.1:6379"}):
            client = pool_mod.get_shared_redis_client()
            assert client is not None
            pool = client.connection_pool
            assert isinstance(pool, redis.BlockingConnectionPool)
            assert pool.timeout == 5, f"Expected timeout=5, got {pool.timeout}"

    def test_max_connections_configurable_via_env(self):
        """REDIS_MAX_CONNECTIONS env var should override the default pool size."""
        with patch.dict(
            "os.environ",
            {"REDIS_ADDR": "127.0.0.1:6379", "REDIS_MAX_CONNECTIONS": "42"},
        ):
            client = pool_mod.get_shared_redis_client()
            assert client is not None
            assert client.connection_pool.max_connections == 42

    def test_returns_same_instance_on_repeated_calls(self):
        """Should return the exact same client object (singleton)."""
        with patch.dict("os.environ", {"REDIS_ADDR": "127.0.0.1:6379"}):
            a = pool_mod.get_shared_redis_client()
            b = pool_mod.get_shared_redis_client()
            assert a is b

    def test_returns_none_when_redis_addr_not_set(self):
        """Should return None if REDIS_ADDR is not configured."""
        with patch.dict("os.environ", {}, clear=True):
            client = pool_mod.get_shared_redis_client()
            assert client is None


@patch.dict(os.environ, {"REDIS_ADDR": "127.0.0.1:6379"}, clear=False)
def test_default_pool_size_is_20():
    """Default REDIS_MAX_CONNECTIONS should be 20 (right-sized for local dev and AE agents)."""
    import agents.utils.redis_pool as rp

    # Reset singleton
    rp._shared_client = None
    os.environ.pop("REDIS_MAX_CONNECTIONS", None)

    client = rp.get_shared_redis_client()
    assert client is not None  # guaranteed when REDIS_ADDR is set
    pool = client.connection_pool  # type: ignore[union-attr]
    assert pool.max_connections == 20

    # Cleanup
    rp._shared_client = None
