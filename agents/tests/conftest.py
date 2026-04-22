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

"""Shared test fixtures for the agents test suite.

Eliminates duplication of mock setup across test files.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def mock_callback_context():
    """Pre-built CallbackContext mock with session/invocation IDs."""
    ctx = MagicMock()
    ctx.session.id = "test-session"
    ctx.invocation_id = "test-invocation"
    ctx.agent_name = "test-agent"
    return ctx


@pytest.fixture
def mock_tool_context():
    """Pre-built ToolContext mock."""
    ctx = MagicMock()
    ctx.session.id = "test-session"
    ctx.invocation_id = "test-invocation"
    ctx.state = {}
    return ctx


@pytest.fixture
def mock_runner():
    """Standard Runner mock with app and session service."""
    runner = MagicMock()
    runner.app.name = "test_app"
    runner.app.root_agent.name = "test_agent"
    return runner


@pytest.fixture
def redis_dash_plugin():
    """RedisDashLogPlugin with mocked PubSub client."""
    with (
        patch("agents.utils.plugins.pubsub_v1.PublisherClient"),
        patch("agents.utils.plugins.load_dotenv"),
    ):
        from agents.utils.plugins import RedisDashLogPlugin

        plugin = RedisDashLogPlugin()
        plugin._publish = AsyncMock()
        yield plugin
