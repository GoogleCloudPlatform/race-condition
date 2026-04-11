# Copyright 2026 Google LLC
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from agents.utils.communication import call_agent
from google.adk.tools.tool_context import ToolContext
from google.adk.sessions.session import Session


@pytest.mark.asyncio
async def test_call_agent_emits_pulses_and_propagates_session():
    # Setup mocks
    mock_session = MagicMock(spec=Session)
    mock_session.id = "test-session-123"

    mock_tool_context = MagicMock(spec=ToolContext)
    mock_tool_context.session = mock_session
    mock_tool_context.invocation_id = "test-iid"
    mock_tool_context.agent_name = "orchestrator"

    # Mock RemoteA2aAgent behavior
    mock_event = MagicMock()
    mock_event.model_dump.return_value = {"type": "model_start"}

    from a2a.types import Message as A2AMessage, Part, TextPart

    mock_response_msg = MagicMock(spec=A2AMessage)
    mock_response_msg.parts = [Part(root=TextPart(text="ok"))]

    async def mock_send_message(msg):
        yield mock_event
        yield mock_response_msg

    mock_remote_agent = MagicMock()
    mock_remote_agent._a2a_client.send_message = mock_send_message
    mock_remote_agent._ensure_resolved = AsyncMock()

    from agents.utils.communication import SimulationA2AClient

    real_client = SimulationA2AClient()
    real_client._registry_cache = {"runner_autopilot": MagicMock()}
    with (
        patch.object(real_client, "_discover_agents", new_callable=AsyncMock) as mock_discover,
        patch("agents.utils.communication_plugin.get_client", return_value=real_client),
        patch("agents.utils.communication.RemoteA2aAgent", return_value=mock_remote_agent),
        patch("agents.utils.communication.emit_inter_agent_pulse", new_callable=AsyncMock) as mock_emit_narrative,
        patch("agents.utils.pulses.emit_telemetry_pulse", new_callable=AsyncMock) as mock_emit_tech,
    ):
        mock_discover.return_value = real_client._registry_cache

        # Execute
        result = await call_agent("runner_autopilot", "hello", mock_tool_context)

        # Verify narrative pulses (Request + Response)
        assert mock_emit_narrative.call_count == 2

        # We no longer expect technical pulses directly from call_agent relay
        # They now come from the callee's RedisDashLogPlugin
        assert mock_emit_tech.call_count == 0

        assert result["status"] == "success"
        assert result["response"] == "ok"


@pytest.mark.asyncio
async def test_call_agent_forwards_simulation_id_to_pulses():
    """call_agent should pass simulation_id from state to inter-agent pulses."""
    mock_session = MagicMock(spec=Session)
    mock_session.id = "test-session-456"

    mock_tool_context = MagicMock(spec=ToolContext)
    mock_tool_context.session = mock_session
    mock_tool_context.invocation_id = "test-iid"
    mock_tool_context.agent_name = "orchestrator"
    mock_tool_context.state = {"simulation_id": "sim-99"}

    from a2a.types import Message as A2AMessage, Part, TextPart

    mock_response_msg = MagicMock(spec=A2AMessage)
    mock_response_msg.parts = [Part(root=TextPart(text="ok"))]

    async def mock_send_message(msg):
        yield mock_response_msg

    mock_remote_agent = MagicMock()
    mock_remote_agent._a2a_client.send_message = mock_send_message
    mock_remote_agent._ensure_resolved = AsyncMock()

    from agents.utils.communication import SimulationA2AClient

    real_client = SimulationA2AClient()
    real_client._registry_cache = {"runner_autopilot": MagicMock()}
    with (
        patch.object(real_client, "_discover_agents", new_callable=AsyncMock) as mock_discover,
        patch("agents.utils.communication_plugin.get_client", return_value=real_client),
        patch("agents.utils.communication.RemoteA2aAgent", return_value=mock_remote_agent),
        patch("agents.utils.communication.emit_inter_agent_pulse", new_callable=AsyncMock) as mock_pulse,
    ):
        mock_discover.return_value = real_client._registry_cache

        result = await call_agent("runner_autopilot", "hello", mock_tool_context)

        assert result["status"] == "success"
        assert mock_pulse.call_count == 2
        for call_args in mock_pulse.call_args_list:
            assert call_args.kwargs.get("simulation_id") == "sim-99"
