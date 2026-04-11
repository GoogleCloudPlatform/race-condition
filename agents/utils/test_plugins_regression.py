# Copyright 2026 Google LLC
import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
from agents.utils.plugins import RedisDashLogPlugin
from google.adk.tools.tool_context import ToolContext


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
@patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock)
async def test_redis_dash_log_plugin_dual_emission(mock_gateway, mock_pubsub_client):
    # Setup plugin
    plugin = RedisDashLogPlugin()
    assert plugin.publisher is not None

    mock_session = MagicMock()
    mock_session.id = "session-123"

    mock_tool = MagicMock()
    mock_tool.name = "accelerate"

    mock_tool_context = MagicMock(spec=ToolContext)
    mock_tool_context.session = mock_session
    mock_tool_context.agent_name = "runner_autopilot"
    mock_tool_context.invocation_id = "iid-456"

    # Execute
    await plugin.after_tool_callback(
        tool=mock_tool,
        tool_args={"speed": 10},
        tool_context=mock_tool_context,
        result={"status": "ok"},
    )

    # 1. Verify Pub/Sub (Main emitted logic)
    # The plugin publishes directly via its configured PublisherClient.
    mock_pubsub_client.return_value.publish.assert_called_once()
    topic_path, data = mock_pubsub_client.return_value.publish.call_args[0]
    assert "projects/test-project/topics/agent-telemetry" in topic_path

    decoded_data = json.loads(data.decode("utf-8"))
    assert decoded_data["type"] == "tool_end"
    assert decoded_data["session_id"] == "session-123"

    # 3. Verify Redis Narrative Pulse (Visual/Main Scroll Wire) via emit_gateway_message
    mock_gateway.assert_called_once()
    _, kwargs = mock_gateway.call_args
    assert kwargs["destination"] == ["session-123"]
    assert kwargs["event"] == "tool_end"

    # Since it's a dict result, it should be emitted as JSON
    assert kwargs["msg_type"] == "json"
    assert kwargs["data"]["result"]["status"] == "ok"
    assert kwargs["data"]["tool_name"] == "accelerate"


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
@patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock)
async def test_redis_dash_log_plugin_filters_narrative_events(mock_gateway, mock_pubsub_client):
    plugin = RedisDashLogPlugin()

    mock_context = MagicMock()
    mock_context.session.id = "session-123"

    from collections import defaultdict

    plugin._sequence_counters = defaultdict(int)

    # Test an event type that should NOT trigger a narrative emission
    await plugin._publish(mock_context, {"type": "agent_start", "agent": "runner_autopilot"})
    mock_gateway.assert_not_called()

    # Test an error event type that SHOULD trigger a narrative emission
    await plugin._publish(mock_context, {"type": "model_error", "agent": "runner_autopilot", "error": "boom"})
    mock_gateway.assert_called_once()

    # Test an event type that SHOULD trigger a narrative emission
    mock_gateway.reset_mock()
    await plugin._publish(
        mock_context, {"type": "model_end", "agent": "runner_autopilot", "response": {"content": "done"}}
    )
    mock_gateway.assert_called_once()

    # Test a start event type that SHOULD trigger a narrative emission
    mock_gateway.reset_mock()
    await plugin._publish(
        mock_context, {"type": "model_start", "agent": "runner_autopilot", "model": "gemini-3-flash-preview"}
    )
    mock_gateway.assert_called_once()


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
@patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock)
async def test_model_start_emits_narrative_event(mock_gateway, mock_pubsub_client):
    plugin = RedisDashLogPlugin()

    mock_session = MagicMock()
    mock_session.id = "session-start-1"

    mock_context = MagicMock()
    mock_context.session = mock_session
    mock_context.agent_name = "planner"
    mock_context.invocation_id = "iid-start-1"

    mock_request = MagicMock()
    mock_request.model = "gemini-3-pro-preview"

    await plugin.before_model_callback(callback_context=mock_context, llm_request=mock_request)

    # Should emit a narrative event via emit_gateway_message
    mock_gateway.assert_called_once()
    _, kwargs = mock_gateway.call_args
    assert kwargs["event"] == "model_start"
    assert kwargs["msg_type"] == "json"
    assert kwargs["data"]["model"] == "gemini-3-pro-preview"
    assert kwargs["data"]["agent"] == "planner"


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
@patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock)
async def test_tool_start_emits_narrative_event(mock_gateway, mock_pubsub_client):
    plugin = RedisDashLogPlugin()

    mock_session = MagicMock()
    mock_session.id = "session-start-2"

    mock_tool = MagicMock()
    mock_tool.name = "advance_tick"

    mock_tool_context = MagicMock(spec=ToolContext)
    mock_tool_context.session = mock_session
    mock_tool_context.agent_name = "simulator"
    mock_tool_context.invocation_id = "iid-start-2"

    await plugin.before_tool_callback(tool=mock_tool, tool_args={"delta": 5}, tool_context=mock_tool_context)

    mock_gateway.assert_called_once()
    _, kwargs = mock_gateway.call_args
    assert kwargs["event"] == "tool_start"
    assert kwargs["msg_type"] == "json"
    assert kwargs["data"]["tool"] == "advance_tick"
    assert kwargs["data"]["agent"] == "simulator"


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
@patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock)
async def test_run_start_emits_lifecycle_event(mock_gateway, mock_pubsub_client):
    plugin = RedisDashLogPlugin()

    mock_agent = MagicMock()
    mock_agent.name = "runner_autopilot"

    mock_session = MagicMock()
    mock_session.id = "session-run-1"

    mock_context = MagicMock()
    mock_context.agent = mock_agent
    mock_context.session = mock_session
    mock_context.user_id = "user-1"
    mock_context.invocation_id = "iid-run-1"

    await plugin.before_run_callback(invocation_context=mock_context)

    # Should emit a lifecycle event via emit_gateway_message
    mock_gateway.assert_called_once()
    _, kwargs = mock_gateway.call_args
    assert kwargs["event"] == "run_start"
    assert kwargs["msg_type"] == "json"
    assert kwargs["data"]["agent"] == "runner_autopilot"


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
@patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock)
async def test_run_end_emits_lifecycle_event(mock_gateway, mock_pubsub_client):
    plugin = RedisDashLogPlugin()

    mock_agent = MagicMock()
    mock_agent.name = "runner_autopilot"

    mock_session = MagicMock()
    mock_session.id = "session-run-2"

    mock_context = MagicMock()
    mock_context.agent = mock_agent
    mock_context.session = mock_session
    mock_context.user_id = "user-2"
    mock_context.invocation_id = "iid-run-2"

    await plugin.after_run_callback(invocation_context=mock_context)

    mock_gateway.assert_called_once()
    _, kwargs = mock_gateway.call_args
    assert kwargs["event"] == "run_end"
    assert kwargs["msg_type"] == "json"
    assert kwargs["data"]["agent"] == "runner_autopilot"


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
@patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock)
async def test_tool_start_includes_display_hints_for_load_skill(mock_gateway, mock_pubsub_client):
    plugin = RedisDashLogPlugin()

    mock_session = MagicMock()
    mock_session.id = "session-hints-1"

    mock_tool = MagicMock()
    mock_tool.name = "load_skill"

    mock_tool_context = MagicMock(spec=ToolContext)
    mock_tool_context.session = mock_session
    mock_tool_context.agent_name = "simulator"
    mock_tool_context.invocation_id = "iid-hints-1"

    await plugin.before_tool_callback(
        tool=mock_tool,
        tool_args={"name": "brainstorming"},
        tool_context=mock_tool_context,
    )

    mock_gateway.assert_called_once()
    call_kwargs = mock_gateway.call_args[1]
    assert call_kwargs["event"] == "tool_start"
    data = call_kwargs["data"]
    assert data["tool"] == "load_skill"
    assert data["tool_hints"] == {"name": "brainstorming"}


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
@patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock)
async def test_tool_start_includes_display_hints_for_call_agent(mock_gateway, mock_pubsub_client):
    plugin = RedisDashLogPlugin()

    mock_session = MagicMock()
    mock_session.id = "session-hints-2"

    mock_tool = MagicMock()
    mock_tool.name = "call_agent"

    mock_tool_context = MagicMock(spec=ToolContext)
    mock_tool_context.session = mock_session
    mock_tool_context.agent_name = "simulator"
    mock_tool_context.invocation_id = "iid-hints-2"

    await plugin.before_tool_callback(
        tool=mock_tool,
        tool_args={"agent_name": "simulator", "message": "sensitive content"},
        tool_context=mock_tool_context,
    )

    mock_gateway.assert_called_once()
    call_kwargs = mock_gateway.call_args[1]
    data = call_kwargs["data"]
    assert data["tool_hints"] == {"agent_name": "simulator"}
    assert "message" not in data.get("tool_hints", {})


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
@patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock)
async def test_tool_start_omits_hints_for_unlisted_tools(mock_gateway, mock_pubsub_client):
    plugin = RedisDashLogPlugin()

    mock_session = MagicMock()
    mock_session.id = "session-hints-3"

    mock_tool = MagicMock()
    mock_tool.name = "advance_tick"

    mock_tool_context = MagicMock(spec=ToolContext)
    mock_tool_context.session = mock_session
    mock_tool_context.agent_name = "simulator"
    mock_tool_context.invocation_id = "iid-hints-3"

    await plugin.before_tool_callback(
        tool=mock_tool,
        tool_args={"delta": 5},
        tool_context=mock_tool_context,
    )

    mock_gateway.assert_called_once()
    call_kwargs = mock_gateway.call_args[1]
    data = call_kwargs["data"]
    assert "tool_hints" not in data


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
@patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock)
async def test_tool_start_omits_hints_when_arg_value_is_none(mock_gateway, mock_pubsub_client):
    plugin = RedisDashLogPlugin()

    mock_session = MagicMock()
    mock_session.id = "session-hints-4"

    mock_tool = MagicMock()
    mock_tool.name = "load_skill"

    mock_tool_context = MagicMock(spec=ToolContext)
    mock_tool_context.session = mock_session
    mock_tool_context.agent_name = "simulator"
    mock_tool_context.invocation_id = "iid-hints-4"

    await plugin.before_tool_callback(
        tool=mock_tool,
        tool_args={"name": None},
        tool_context=mock_tool_context,
    )

    mock_gateway.assert_called_once()
    call_kwargs = mock_gateway.call_args[1]
    data = call_kwargs["data"]
    assert "tool_hints" not in data
