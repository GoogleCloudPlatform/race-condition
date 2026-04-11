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

"""Test fixtures for planner_with_memory tests.

Env vars MUST be set here at module level — before any imports — because
agents/planner_with_memory/__init__.py eagerly imports agent.py, which calls
create_session_service() and create_memory_service() at module level.
pytest fixtures run too late to prevent that.
"""

import os

# Set required env vars BEFORE agent.py is imported via __init__.py.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("AGENT_ENGINE_ID", "test-agent-engine")
os.environ.setdefault("ALLOYDB_HOST", "127.0.0.1")
os.environ.setdefault("ALLOYDB_PASSWORD", "test")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def mock_gcp_services(monkeypatch):
    """Patch Vertex AI constructors and AlloyDBRouteStore for offline tests."""
    with (
        patch(
            "agents.planner_with_memory.services.session_manager.VertexAiSessionService",
            return_value=MagicMock(),
        ),
        patch(
            "agents.planner_with_memory.services.memory_manager.VertexAiMemoryBankService",
            return_value=MagicMock(),
        ),
        patch(
            "agents.planner_with_memory.memory.tools._store",
            new_callable=MagicMock,
        ) as mock_store,
        patch(
            "agents.planner_with_memory.agent.App",
            return_value=MagicMock(),
        ),
    ):
        mock_store.store_route = AsyncMock(return_value="test-route-id")
        mock_store.get_route = AsyncMock(return_value=None)
        mock_store.record_simulation = AsyncMock(return_value="test-sim-id")
        mock_store.recall_routes = AsyncMock(return_value=[])
        mock_store.get_best_route = AsyncMock(return_value=None)
        yield mock_store
