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

"""Tests for runtime service factory pool configuration."""

import os
from unittest.mock import patch


class TestCloudRunServicesPoolConfig:
    """Verify DB pool env vars are forwarded to DatabaseSessionService."""

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@10.0.0.1/db",
            "DB_POOL_SIZE": "30",
            "DB_MAX_OVERFLOW": "25",
        },
        clear=False,
    )
    @patch("google.adk.sessions.database_session_service.DatabaseSessionService")
    def test_pool_size_from_env(self, mock_db_svc):
        """DB_POOL_SIZE and DB_MAX_OVERFLOW env vars are forwarded."""
        from agents.utils.runtime import _create_cloud_run_services

        _create_cloud_run_services()

        mock_db_svc.assert_called_once_with(
            db_url="postgresql+asyncpg://user:pass@10.0.0.1/db",
            pool_size=30,
            max_overflow=25,
        )

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@10.0.0.1/db",
        },
        clear=False,
    )
    @patch("google.adk.sessions.database_session_service.DatabaseSessionService")
    def test_pool_defaults(self, mock_db_svc):
        """Defaults to pool_size=20, max_overflow=20 when env vars absent."""
        os.environ.pop("DB_POOL_SIZE", None)
        os.environ.pop("DB_MAX_OVERFLOW", None)

        from agents.utils.runtime import _create_cloud_run_services

        _create_cloud_run_services()

        mock_db_svc.assert_called_once_with(
            db_url="postgresql+asyncpg://user:pass@10.0.0.1/db",
            pool_size=20,
            max_overflow=20,
        )

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@10.0.0.1/db",
            "DB_POOL_SIZE": "not_a_number",
        },
        clear=False,
    )
    @patch("google.adk.sessions.database_session_service.DatabaseSessionService")
    def test_invalid_pool_size_falls_back_to_default(self, mock_db_svc):
        """Non-integer DB_POOL_SIZE falls back to default."""
        os.environ.pop("DB_MAX_OVERFLOW", None)

        from agents.utils.runtime import _create_cloud_run_services

        _create_cloud_run_services()

        mock_db_svc.assert_called_once_with(
            db_url="postgresql+asyncpg://user:pass@10.0.0.1/db",
            pool_size=20,
            max_overflow=20,
        )


class TestSessionStoreOverride:
    """Verify SESSION_STORE_OVERRIDE overrides session service selection."""

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@10.0.0.1/db",
            "SESSION_STORE_OVERRIDE": "inmemory",
        },
        clear=False,
    )
    def test_override_forces_inmemory_even_with_database_url(self):
        """SESSION_STORE_OVERRIDE=inmemory skips DB even when DATABASE_URL is set."""
        from google.adk.sessions.in_memory_session_service import InMemorySessionService

        from agents.utils.runtime import create_services

        result = create_services()
        assert isinstance(result.session_service, InMemorySessionService)
        assert result.target == "inmemory_override"

    @patch.dict(
        os.environ,
        {
            "GOOGLE_CLOUD_AGENT_ENGINE_ID": "projects/123/locations/us-central1/agentEngines/456",
            "SESSION_STORE_OVERRIDE": "inmemory",
        },
        clear=False,
    )
    def test_override_forces_inmemory_even_with_agent_engine(self):
        """SESSION_STORE_OVERRIDE=inmemory skips Agent Engine too."""
        from google.adk.sessions.in_memory_session_service import InMemorySessionService

        from agents.utils.runtime import create_services

        os.environ.pop("DATABASE_URL", None)
        result = create_services()
        assert isinstance(result.session_service, InMemorySessionService)
        assert result.target == "inmemory_override"

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@10.0.0.1/db",
            "SESSION_STORE_OVERRIDE": "redis",
            "REDIS_ADDR": "127.0.0.1:6379",
        },
        clear=False,
    )
    def test_redis_override_creates_redis_session_service(self):
        """SESSION_STORE_OVERRIDE=redis creates RedisSessionService."""
        from google.adk_community.sessions import RedisSessionService

        from agents.utils.runtime import create_services

        result = create_services()
        assert isinstance(result.session_service, RedisSessionService)
        assert result.target == "redis_override"

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@10.0.0.1/db",
            "SESSION_STORE_OVERRIDE": "redis",
            "REDIS_ADDR": "redis://10.0.0.1:6379",
        },
        clear=False,
    )
    def test_redis_override_handles_uri_format(self):
        """SESSION_STORE_OVERRIDE=redis handles redis:// URI format."""
        from google.adk_community.sessions import RedisSessionService

        from agents.utils.runtime import create_services

        result = create_services()
        assert isinstance(result.session_service, RedisSessionService)
        assert result.target == "redis_override"

    @patch.dict(
        os.environ,
        {
            "SESSION_STORE_OVERRIDE": "redis",
            "REDIS_ADDR": "myredishost",
        },
        clear=False,
    )
    def test_redis_override_bare_hostname_without_port(self):
        """SESSION_STORE_OVERRIDE=redis handles bare hostname (no port)."""
        from google.adk_community.sessions import RedisSessionService

        os.environ.pop("DATABASE_URL", None)

        from agents.utils.runtime import create_services

        result = create_services()
        assert isinstance(result.session_service, RedisSessionService)
        assert result.target == "redis_override"

    @patch.dict(
        os.environ,
        {
            "SESSION_STORE_OVERRIDE": "redis",
            "REDIS_ADDR": "myhost:notaport",
        },
        clear=False,
    )
    def test_redis_override_malformed_port_falls_back(self):
        """Malformed port in REDIS_ADDR falls back to 6379."""
        from google.adk_community.sessions import RedisSessionService

        os.environ.pop("DATABASE_URL", None)

        from agents.utils.runtime import create_services

        result = create_services()
        assert isinstance(result.session_service, RedisSessionService)
        assert result.target == "redis_override"

    @patch.dict(
        os.environ,
        {
            "SESSION_STORE_OVERRIDE": "redis",
        },
        clear=False,
    )
    def test_redis_override_defaults_to_localhost(self):
        """Missing REDIS_ADDR defaults to localhost:6379."""
        from google.adk_community.sessions import RedisSessionService

        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("REDIS_ADDR", None)

        from agents.utils.runtime import create_services

        result = create_services()
        assert isinstance(result.session_service, RedisSessionService)
        assert result.target == "redis_override"

    @patch.dict(
        os.environ,
        {
            "SESSION_STORE_OVERRIDE": "redis",
            "REDIS_ADDR": "127.0.0.1:6379",
            "REDIS_SESSION_MAX_CONNECTIONS": "15",
        },
        clear=False,
    )
    @patch(
        "agents.utils.pruned_session_service.RedisSessionService.__init__",
        return_value=None,
    )
    def test_redis_override_passes_max_connections(self, mock_init):
        """REDIS_SESSION_MAX_CONNECTIONS env var is forwarded to RedisSessionService."""
        os.environ.pop("DATABASE_URL", None)

        from agents.utils.runtime import create_services

        result = create_services()
        assert result.target == "redis_override"
        assert mock_init.call_args.kwargs["max_connections"] == 15

    @patch.dict(
        os.environ,
        {
            "SESSION_STORE_OVERRIDE": "redis",
            "REDIS_ADDR": "127.0.0.1:6379",
        },
        clear=False,
    )
    @patch(
        "agents.utils.pruned_session_service.RedisSessionService.__init__",
        return_value=None,
    )
    def test_redis_override_default_max_connections(self, mock_init):
        """Default max_connections=100 when REDIS_SESSION_MAX_CONNECTIONS is absent."""
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("REDIS_SESSION_MAX_CONNECTIONS", None)

        from agents.utils.runtime import create_services

        create_services()
        assert mock_init.call_args.kwargs["max_connections"] == 100

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@10.0.0.1/db",
            "SESSION_STORE_OVERRIDE": "postgres",
        },
        clear=False,
    )
    @patch("google.adk.sessions.database_session_service.DatabaseSessionService")
    def test_unrecognized_override_falls_through(self, mock_db_svc):
        """Unrecognized override value falls through to normal chain."""
        os.environ.pop("DB_POOL_SIZE", None)
        os.environ.pop("DB_MAX_OVERFLOW", None)
        os.environ.pop("GOOGLE_CLOUD_AGENT_ENGINE_ID", None)

        from agents.utils.runtime import create_services

        result = create_services()
        assert result.target == "cloud_run"

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@10.0.0.1/db",
        },
        clear=False,
    )
    @patch("google.adk.sessions.database_session_service.DatabaseSessionService")
    def test_no_override_uses_database_as_before(self, mock_db_svc):
        """Without SESSION_STORE_OVERRIDE, DATABASE_URL still selects DB."""
        os.environ.pop("SESSION_STORE_OVERRIDE", None)
        os.environ.pop("DB_POOL_SIZE", None)
        os.environ.pop("DB_MAX_OVERFLOW", None)
        os.environ.pop("GOOGLE_CLOUD_AGENT_ENGINE_ID", None)

        from agents.utils.runtime import create_services

        result = create_services()
        assert result.target == "cloud_run"


class TestIntEnvHelper:
    """Tests for the _int_env helper function."""

    @patch.dict(os.environ, {"TEST_VAR": "42"}, clear=False)
    def test_reads_valid_int(self):
        from agents.utils.runtime import _int_env

        assert _int_env("TEST_VAR", 10) == 42

    @patch.dict(os.environ, {}, clear=False)
    def test_missing_var_returns_default(self):
        os.environ.pop("TEST_VAR", None)
        from agents.utils.runtime import _int_env

        assert _int_env("TEST_VAR", 10) == 10

    @patch.dict(os.environ, {"TEST_VAR": "bad"}, clear=False)
    def test_invalid_var_returns_default(self):
        from agents.utils.runtime import _int_env

        assert _int_env("TEST_VAR", 10) == 10
