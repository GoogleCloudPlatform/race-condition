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

import pytest
from unittest.mock import MagicMock
from agents.utils.dispatcher import RedisOrchestratorDispatcher


@pytest.mark.asyncio
async def test_spawn_agent_registers_session_but_no_trigger():
    """Verify that spawn_agent registers the session but does NOT trigger a run.

    Session creation is deferred to the first run_async() call via
    Runner(auto_create_session=True), so spawn only adds to active_sessions.
    """
    # Setup mock runner
    mock_runner = MagicMock()
    mock_runner.app.name = "test-agent"

    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)
    dispatcher._trigger_agent_run = MagicMock()

    spawn_event = {
        "type": "spawn_agent",
        "sessionId": "test-session",
        "payload": {"agentType": "test-agent"},
    }

    await dispatcher._process_event(spawn_event)

    # Verify _trigger_agent_run was NOT called (passive spawn)
    dispatcher._trigger_agent_run.assert_not_called()

    # Verify session was added to active list (no DB call at spawn)
    assert "test-session" in dispatcher.active_sessions
