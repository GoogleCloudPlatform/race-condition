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

"""Root conftest for all agent tests.

Prevents module-level state from leaking between tests.
"""

# IMPORTANT: These env vars MUST be set before any agent module is imported.
# agents/planner_with_memory/__init__.py eagerly imports agent.py, which calls
# create_session_service() and create_memory_service() at module level.
# If these are not set, ValueError is raised during collection.
import os

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("AGENT_ENGINE_ID", "test-agent-engine")
os.environ.setdefault("ALLOYDB_HOST", "127.0.0.1")

from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_simulation_registry():
    """Prevent simulation_registry state from leaking between tests.

    The registry is module-level state; without this fixture, a test that
    calls ``register()`` can pollute subsequent tests' ``lookup()`` results.

    Also patches ``get_shared_redis_client`` to return None in the registry
    module, preventing unintentional Redis writes when other tests (e.g.
    test_redis_pool.py) leak a real ``_shared_client``.
    """
    from agents.utils.simulation_registry import _context_map, _local

    _local.clear()
    _context_map.clear()
    with patch("agents.utils.simulation_registry.get_shared_redis_client", return_value=None):
        yield
    _local.clear()
    _context_map.clear()


@pytest.fixture(autouse=True)
def _isolate_redis(monkeypatch):
    """Prevent tests from connecting to real Redis.

    Worktree ``.env`` files set ``REDIS_ADDR`` to a real Redis instance.
    If a test triggers ``emit_gateway_message`` without mocking, the
    ``_publish_worker`` in ``pulses.py`` starts a background asyncio task
    that connects to Redis and blocks event-loop teardown indefinitely
    (``queue.get()`` in an infinite loop).

    This fixture removes ``REDIS_ADDR`` from the environment for all tests
    and resets any cached Redis client, so ``get_shared_redis_client()``
    returns ``None``.  Tests that need a real Redis connection should use
    the ``integration`` marker and set up their own mock/connection.
    """
    monkeypatch.delenv("REDIS_ADDR", raising=False)
    # Reset the cached client so it picks up the missing env var.
    from agents.utils import redis_pool

    redis_pool._shared_client = None
    yield
    # Clean up any workers that may have started during the test.
    from agents.utils import pulses

    pulses.reset()
    redis_pool._shared_client = None
