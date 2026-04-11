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

import os
import pytest
import respx
import json
from unittest.mock import MagicMock, PropertyMock, patch

from httpx import Response
from agents.utils.communication import call_agent
from agents.utils.communication import SimulationA2AClient

# Fixed test gateway/agent URLs -- unit tests must not depend on .env
_TEST_GATEWAY_URL = "http://127.0.0.1:8101"
_TEST_RUNNER_URL = "http://runner-autopilot-service:8210"

# Controlled environment for all tests in this module so they are
# independent of whatever .env file is present (e.g. worktree offsets).
_TEST_ENV = {
    "GATEWAY_URL": _TEST_GATEWAY_URL,
    "RUNNER_AUTOPILOT_URL": _TEST_RUNNER_URL,
}


@pytest.mark.asyncio
@respx.mock
@patch.dict(os.environ, _TEST_ENV)
async def test_simulator_call_agent_integration():
    """Verify Simulator can call another agent via the call_agent tool."""

    # 1. Mock Gateway Registry
    mock_registry = {
        "runner_autopilot": {
            "name": "runner_autopilot",
            "url": _TEST_RUNNER_URL,
            "preferred_transport": "JSONRPC",  # Use JSONRPC for RemoteA2aAgent compatibility
            "description": "Simulation Runner Autopilot",
            "version": "1.0.0",
            "security": [],  # Fix: must be a list
            "capabilities": {"streaming": False},
            "default_input_modes": ["text/plain"],
            "default_output_modes": ["text/plain"],
            "skills": [],
        }
    }
    respx.get(f"{_TEST_GATEWAY_URL}/api/v1/agent-types").mock(return_value=Response(200, json=mock_registry))

    # 2. Mock Runner Autopilot A2A Endpoint
    async def side_effect(request):
        body = json.loads(request.content)
        response_data = {
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {
                "message_id": "resp-123",
                "role": "agent",
                "parts": [{"kind": "text", "text": "Runner status: All systems go."}],
            },
        }
        return Response(200, json=response_data)

    respx.post(_TEST_RUNNER_URL).mock(side_effect=side_effect)

    # 3. Setup Mock ToolContext
    tool_context = MagicMock()
    # Ensure it behaves like ToolContext/ReadonlyContext property
    type(tool_context).invocation_id = PropertyMock(return_value="test-inv-id")
    tool_context.state = {}
    tool_context.session.id = "test-session-id"
    tool_context.agent_name = "simulator"

    # 4. Execute the tool
    result = await call_agent(
        agent_name="runner_autopilot",
        message="Get your current vitals.",
        tool_context=tool_context,
    )

    # 5. Assertions
    assert result["status"] == "success"
    assert result["agent"] == "runner_autopilot"
    assert "All systems go." in result["response"]


@pytest.mark.asyncio
@respx.mock
@patch.dict(os.environ, _TEST_ENV)
async def test_simulator_call_agent_cold_start_recovery():
    """Verify Simulator recovers from a cold start (timeout/transient error)."""

    # 1. Mock Gateway Registry
    mock_registry = {
        "runner_autopilot": {
            "name": "runner_autopilot",
            "url": _TEST_RUNNER_URL,
            "preferred_transport": "JSONRPC",  # Use JSONRPC for RemoteA2aAgent compatibility
            "description": "Simulation Runner Autopilot",
            "version": "1.0.0",
            "security": [],  # Fix: must be a list
            "capabilities": {"streaming": False},
            "default_input_modes": ["text/plain"],
            "default_output_modes": ["text/plain"],
            "skills": [],
        }
    }
    respx.get(f"{_TEST_GATEWAY_URL}/api/v1/agent-types").mock(return_value=Response(200, json=mock_registry))

    # 2. Mock Runner Autopilot A2A Endpoint with one failure then success
    calls = []

    async def side_effect(request):
        calls.append(request)
        if len(calls) == 1:
            return Response(504, text="Gateway Timeout (Cold Start)")

        body = json.loads(request.content)
        response_data = {
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {
                "message_id": "resp-cold",
                "role": "agent",
                "parts": [{"kind": "text", "text": "Woke up!"}],
            },
        }
        return Response(200, json=response_data)

    respx.post(_TEST_RUNNER_URL).mock(side_effect=side_effect)

    # 3. Setup Mock ToolContext
    a2a_client = SimulationA2AClient(gateway_url=_TEST_GATEWAY_URL)
    tool_context = MagicMock()
    type(tool_context).invocation_id = PropertyMock(return_value="cold-inv-id")
    tool_context.state = {"a2a_client": a2a_client}
    tool_context.session.id = "cold-session-id"
    tool_context.agent_name = "simulator"

    # 4. Execute tool with retries
    # We call it manually to inject custom logic if needed, but it should use
    # the client's internal retry logic.
    result = await call_agent(agent_name="runner_autopilot", message="Wake up call", tool_context=tool_context)

    # 5. Assertions
    assert result["status"] == "success"
    assert "Woke up!" in result["response"]
    assert len(calls) == 2  # 1 fail, 1 success
