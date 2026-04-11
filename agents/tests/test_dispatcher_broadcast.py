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

import json
import pytest
from unittest.mock import MagicMock, ANY
from agents.utils.dispatcher import RedisOrchestratorDispatcher


@pytest.mark.asyncio
async def test_broadcast_agent_type_targeting():
    """Verify that targeting an agent type (e.g. 'planner') routes to all active sessions of that type."""
    mock_runner = MagicMock()
    mock_runner.app.name = "planner"

    # Ensure IDLE_AGENT is false for this test (default)
    import os

    os.environ["IDLE_AGENT"] = "false"

    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)
    dispatcher._trigger_agent_run = MagicMock()

    # 1. Spawn a session
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "session-1",
            "payload": {"agentType": "planner"},
        }
    )

    # Reset mock because spawn triggers initial activation
    dispatcher._trigger_agent_run.reset_mock()

    # 2. Send a broadcast targeted to "planner"
    broadcast_event = {
        "type": "broadcast",
        "payload": {"data": "Hello planners!", "targets": ["planner"]},
    }

    await dispatcher._process_event(broadcast_event)

    # Verify it was routed
    dispatcher._trigger_agent_run.assert_called_with("session-1", ANY)
    # Check text content
    content = dispatcher._trigger_agent_run.call_args[0][1]
    assert content.parts[0].text == "Hello planners!"


@pytest.mark.asyncio
async def test_broadcast_json_unwrapping():
    """Verify that JSON payloads from the UI are unwrapped to extract the 'text' field."""
    mock_runner = MagicMock()
    mock_runner.app.name = "planner"

    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)
    dispatcher._trigger_agent_run = MagicMock()

    # Spawn session
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "session-1",
            "payload": {"agentType": "planner"},
        }
    )

    # Reset mock after spawn
    dispatcher._trigger_agent_run.reset_mock()

    # Data is a JSON string containing the prompt (typical logic for pulses from UI)
    ui_data = json.dumps({"text": "Plan a marathon from the Sign to the Sphere"})

    broadcast_event = {
        "type": "broadcast",
        "payload": {"data": ui_data, "targets": ["planner"]},
    }

    await dispatcher._process_event(broadcast_event)

    # Verify the unwrapped text was used
    content = dispatcher._trigger_agent_run.call_args[0][1]
    assert content.parts[0].text == "Plan a marathon from the Sign to the Sphere"


@pytest.mark.asyncio
async def test_broadcast_session_id_targeting():
    """Verify that targeting a specific session ID works."""
    mock_runner = MagicMock()
    mock_runner.app.name = "planner"

    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)
    dispatcher._trigger_agent_run = MagicMock()

    # Spawn two sessions
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "session-1",
            "payload": {"agentType": "planner"},
        }
    )
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "session-2",
            "payload": {"agentType": "planner"},
        }
    )

    # Reset mock after spawns
    dispatcher._trigger_agent_run.reset_mock()

    # Target ONLY session-2
    broadcast_event = {
        "type": "broadcast",
        "payload": {"data": "Only for session-2", "targets": ["session-2"]},
    }

    await dispatcher._process_event(broadcast_event)

    # Verify only session-2 was triggered
    dispatcher._trigger_agent_run.assert_called_once_with("session-2", ANY)


@pytest.mark.asyncio
async def test_broadcast_no_match():
    """Verify that non-matching targets are ignored."""
    mock_runner = MagicMock()
    mock_runner.app.name = "planner"

    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)
    dispatcher._trigger_agent_run = MagicMock()

    # Spawn a session
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "session-1",
            "payload": {"agentType": "planner"},
        }
    )

    # Reset mock after spawn
    dispatcher._trigger_agent_run.reset_mock()

    # Target "runner_autopilot"
    broadcast_event = {
        "type": "broadcast",
        "payload": {"data": "Hello runners!", "targets": ["runner_autopilot"]},
    }

    await dispatcher._process_event(broadcast_event)

    # Verify nothing was triggered
    dispatcher._trigger_agent_run.assert_not_called()


@pytest.mark.asyncio
async def test_broadcast_does_not_leak_to_other_agent_types():
    """Regression: a broadcast targeting a foreign agent session UUID must NOT
    cause a runner dispatcher to adopt that session and invoke the LLM.

    The pub/sub broadcast channel reaches ALL agents.  Each dispatcher
    must only act on sessions it owns, never adopt foreign UUIDs."""
    import uuid

    foreign_session = str(uuid.uuid4())

    # --- Runner Autopilot dispatcher (should NOT act) ---
    runner_mock = MagicMock()
    runner_mock.app.name = "runner_autopilot"
    runner_dispatcher = RedisOrchestratorDispatcher(runner=runner_mock)
    runner_dispatcher._trigger_agent_run = MagicMock()

    # Runner Autopilot has its own session
    runner_session = str(uuid.uuid4())
    await runner_dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": runner_session,
            "payload": {"agentType": "runner_autopilot"},
        }
    )
    runner_dispatcher._trigger_agent_run.reset_mock()

    # --- Broadcast targets only the foreign agent session ---
    broadcast_event = {
        "type": "broadcast",
        "payload": {
            "data": "Show me the financials",
            "targets": [foreign_session],
        },
    }

    await runner_dispatcher._process_event(broadcast_event)

    # Runner Autopilot must NOT have been triggered
    runner_dispatcher._trigger_agent_run.assert_not_called()
    # Runner Autopilot must NOT have adopted the foreign session
    assert foreign_session not in runner_dispatcher.active_sessions, (
        f"Runner Autopilot adopted foreign session {foreign_session}"
    )


@pytest.mark.asyncio
async def test_broadcast_exclude_runner_ids():
    """Verify that exclude_runner_ids filters out specific sessions from fan-out."""
    mock_runner = MagicMock()
    mock_runner.app.name = "runner_autopilot"

    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)
    dispatcher._trigger_agent_run = MagicMock()

    # Spawn two sessions for the same simulation
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "runner-1",
            "payload": {
                "agentType": "runner_autopilot",
                "simulation_id": "sim-1",
            },
        }
    )
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "runner-2",
            "payload": {
                "agentType": "runner_autopilot",
                "simulation_id": "sim-1",
            },
        }
    )

    # Reset mock after spawns
    dispatcher._trigger_agent_run.reset_mock()

    # Broadcast with exclude_runner_ids excluding runner-1
    broadcast_event = {
        "type": "broadcast",
        "simulation_id": "sim-1",
        "payload": {
            "data": "tick payload",
            "exclude_runner_ids": ["runner-1"],
        },
    }

    await dispatcher._process_event(broadcast_event)

    # Only runner-2 should have been triggered
    dispatcher._trigger_agent_run.assert_called_once_with("runner-2", ANY)
