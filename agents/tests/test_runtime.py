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

"""Tests for agents.utils.runtime — unified runtime service abstraction.

TDD RED phase: These tests define the expected behavior of create_services().
The module does not exist yet, so all tests should fail with ImportError.
"""

import os
from unittest.mock import patch


class TestCreateServicesLocal:
    """When no cloud env vars are set, create_services returns local (InMemory) services."""

    @patch.dict(os.environ, {}, clear=True)
    def test_returns_service_config(self):
        """create_services() returns a ServiceConfig dataclass."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert hasattr(config, "session_service")
        assert hasattr(config, "artifact_service")
        assert hasattr(config, "memory_service")

    @patch.dict(os.environ, {}, clear=True)
    def test_local_uses_in_memory_session(self):
        """Without cloud env vars, session_service is InMemorySessionService."""
        from agents.utils.runtime import create_services
        from google.adk.sessions.in_memory_session_service import InMemorySessionService

        config = create_services()
        assert isinstance(config.session_service, InMemorySessionService)

    @patch.dict(os.environ, {}, clear=True)
    def test_local_artifact_service_is_in_memory(self):
        """Without cloud env vars, artifact_service is InMemoryArtifactService."""
        from agents.utils.runtime import create_services
        from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService

        config = create_services()
        assert isinstance(config.artifact_service, InMemoryArtifactService)

    @patch.dict(os.environ, {}, clear=True)
    def test_local_memory_service_is_in_memory(self):
        """Without cloud env vars, memory_service is InMemoryMemoryService."""
        from agents.utils.runtime import create_services
        from google.adk.memory.in_memory_memory_service import InMemoryMemoryService

        config = create_services()
        assert isinstance(config.memory_service, InMemoryMemoryService)

    @patch.dict(os.environ, {}, clear=True)
    def test_local_target_is_local(self):
        """Without cloud env vars, target is 'local'."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert config.target == "local"


class TestCreateServicesAgentEngine:
    """When GOOGLE_CLOUD_AGENT_ENGINE_ID is set, create_services returns Agent Engine services."""

    @patch.dict(os.environ, {"GOOGLE_CLOUD_AGENT_ENGINE_ID": "projects/123/locations/us/agents/abc"}, clear=True)
    def test_agent_engine_uses_vertex_session(self):
        """With GOOGLE_CLOUD_AGENT_ENGINE_ID, session_service is VertexAiSessionService."""
        from agents.utils.runtime import create_services

        config = create_services()
        # We check the type name to avoid actually instantiating Vertex (needs creds)
        assert type(config.session_service).__name__ == "VertexAiSessionService"

    @patch.dict(os.environ, {"GOOGLE_CLOUD_AGENT_ENGINE_ID": "projects/123/locations/us/agents/abc"}, clear=True)
    def test_agent_engine_target(self):
        """With GOOGLE_CLOUD_AGENT_ENGINE_ID, target is 'agent_engine'."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert config.target == "agent_engine"


class TestCreateServicesAgentEnginePlatformEnvVar:
    """When GOOGLE_CLOUD_AGENT_ENGINE_ID is set (platform-injected),
    create_services returns Agent Engine services."""

    @patch.dict(
        os.environ,
        {"GOOGLE_CLOUD_AGENT_ENGINE_ID": "12345"},
        clear=True,
    )
    def test_platform_env_var_uses_vertex_session(self):
        """Platform-injected GOOGLE_CLOUD_AGENT_ENGINE_ID triggers VertexAiSessionService."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert type(config.session_service).__name__ == "VertexAiSessionService"

    @patch.dict(
        os.environ,
        {"GOOGLE_CLOUD_AGENT_ENGINE_ID": "12345"},
        clear=True,
    )
    def test_platform_env_var_target(self):
        """Platform-injected GOOGLE_CLOUD_AGENT_ENGINE_ID sets target to agent_engine."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert config.target == "agent_engine"


class TestAgentEngineLocationFallback:
    """GOOGLE_CLOUD_AGENT_ENGINE_LOCATION is used for session service location."""

    @patch.dict(
        os.environ,
        {
            "GOOGLE_CLOUD_AGENT_ENGINE_ID": "12345",
            "GOOGLE_CLOUD_AGENT_ENGINE_LOCATION": "europe-west4",
        },
        clear=True,
    )
    def test_platform_location_used(self):
        """GOOGLE_CLOUD_AGENT_ENGINE_LOCATION is used for VertexAiSessionService."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert config.session_service._location == "europe-west4"


class TestCreateServicesCloudRun:
    """When DATABASE_URL is set (no GOOGLE_CLOUD_AGENT_ENGINE_ID), create_services returns Cloud Run services."""

    @patch("google.adk.sessions.database_session_service.DatabaseSessionService.__init__", return_value=None)
    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/test"}, clear=True)
    def test_cloud_run_target(self, mock_db_init):
        """With DATABASE_URL, target is 'cloud_run'."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert config.target == "cloud_run"

    @patch("google.adk.sessions.database_session_service.DatabaseSessionService.__init__", return_value=None)
    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/test"}, clear=True)
    def test_cloud_run_uses_database_session(self, mock_db_init):
        """With DATABASE_URL, session_service is DatabaseSessionService."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert type(config.session_service).__name__ == "DatabaseSessionService"
        mock_db_init.assert_called_once_with(db_url="postgresql://localhost/test", pool_size=20, max_overflow=20)

    @patch("google.adk.artifacts.gcs_artifact_service.GcsArtifactService.__init__", return_value=None)
    @patch("google.adk.sessions.database_session_service.DatabaseSessionService.__init__", return_value=None)
    @patch.dict(
        os.environ,
        {"DATABASE_URL": "postgresql://localhost/test", "GCS_ARTIFACT_BUCKET": "my-bucket"},
        clear=True,
    )
    def test_cloud_run_uses_gcs_artifact(self, mock_db_init, mock_gcs_init):
        """With DATABASE_URL + GCS_ARTIFACT_BUCKET, artifact_service is GcsArtifactService."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert type(config.artifact_service).__name__ == "GcsArtifactService"
        mock_gcs_init.assert_called_once_with(bucket_name="my-bucket")

    @patch("google.adk.sessions.database_session_service.DatabaseSessionService.__init__", return_value=None)
    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/test"}, clear=True)
    def test_cloud_run_memory_is_none(self, mock_db_init):
        """Runner on Cloud Run does not need memory service (ephemeral NPCs)."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert config.memory_service is None


class TestSqliteProhibition:
    """The runtime module must NEVER return a SQLite session service."""

    @patch.dict(os.environ, {}, clear=True)
    def test_no_sqlite_import_in_runtime(self):
        """runtime.py must not import sqlite_store anywhere."""
        import importlib

        mod = importlib.import_module("agents.utils.runtime")
        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as f:
            lines = f.readlines()

        import_lines = [line.strip() for line in lines if line.strip().startswith(("import ", "from "))]
        for line in import_lines:
            assert "sqlite" not in line.lower(), f"runtime.py imports SQLite: {line}"


class TestCreateServicesPrecedence:
    """GOOGLE_CLOUD_AGENT_ENGINE_ID takes precedence over DATABASE_URL when both are set."""

    @patch.dict(
        os.environ,
        {
            "GOOGLE_CLOUD_AGENT_ENGINE_ID": "projects/123/locations/us/agents/abc",
            "DATABASE_URL": "postgresql://localhost/test",
        },
        clear=True,
    )
    def test_agent_engine_takes_precedence(self):
        """When both GOOGLE_CLOUD_AGENT_ENGINE_ID and DATABASE_URL are set, Agent Engine wins."""
        from agents.utils.runtime import create_services

        config = create_services()
        assert config.target == "agent_engine"
