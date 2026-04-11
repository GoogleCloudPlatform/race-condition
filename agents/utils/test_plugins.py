# Copyright 2026 Google LLC
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.utils.plugins import RedisDashLogPlugin
from google.adk.tools.tool_context import ToolContext


@pytest.mark.asyncio
async def test_redis_dash_log_plugin_emits_to_redis():
    with patch("google.cloud.pubsub_v1.PublisherClient") as mock_pubsub:
        # Setup
        plugin = RedisDashLogPlugin()

        mock_session = MagicMock()
        mock_session.id = "session-456"

        # Test tool callback
        mock_tool = MagicMock()
        mock_tool.name = "accelerate"

        mock_tool_context = MagicMock(spec=ToolContext)
        mock_tool_context.session = mock_session
        mock_tool_context.agent_name = "runner_autopilot"
        mock_tool_context.invocation_id = "iid-789"

        # Execute
        await plugin.before_tool_callback(tool=mock_tool, tool_args={"speed": 10}, tool_context=mock_tool_context)

        # Verify
        mock_pubsub.return_value.publish.assert_called_once()
        args, kwargs = mock_pubsub.return_value.publish.call_args
        import json

        payload = json.loads(args[1].decode("utf-8"))
        assert payload["session_id"] == "session-456"
        assert payload["type"] == "tool_start"
        assert payload["tool"] == "accelerate"
        assert payload["args"] == {"speed": 10}
        assert payload["invocation_id"] == "iid-789"


@pytest.mark.asyncio
async def test_redis_dash_log_plugin_handles_missing_session():
    with patch("google.cloud.pubsub_v1.PublisherClient") as mock_pubsub:
        plugin = RedisDashLogPlugin()

        mock_context = MagicMock()
        mock_context.session = None  # Missing session
        mock_context.agent_name = "unknown"

        from google.adk.models.llm_response import LlmResponse

        mock_response = MagicMock(spec=LlmResponse)
        mock_response.turn_complete = True
        mock_response.partial = False
        mock_response.content = MagicMock()
        mock_response.content.parts = []
        mock_response.usage_metadata = None

        await plugin.after_model_callback(callback_context=mock_context, llm_response=mock_response)

        # Verify fallback
        mock_pubsub.return_value.publish.assert_called_once()
        args, kwargs = mock_pubsub.return_value.publish.call_args
        import json

        payload = json.loads(args[1].decode("utf-8"))
        assert payload["session_id"] == "unknown-session"


# --- Task 1: fire_and_forget / suppressed_events constructor tests ---


def test_fire_and_forget_default_false():
    """BaseDashLogPlugin defaults to fire_and_forget=False and empty suppressed set."""
    with patch("google.cloud.pubsub_v1.PublisherClient"):
        plugin = RedisDashLogPlugin()
        assert plugin._fire_and_forget is False
        assert plugin._suppressed_events == set()


def test_fire_and_forget_constructor():
    """fire_and_forget and suppressed_events are configurable via kwargs."""
    with patch("google.cloud.pubsub_v1.PublisherClient"):
        plugin = RedisDashLogPlugin(
            fire_and_forget=True,
            suppressed_events={"run_start", "model_start"},
        )
        assert plugin._fire_and_forget is True
        assert "run_start" in plugin._suppressed_events
        assert "model_start" in plugin._suppressed_events


# --- Task 2: suppression and fire-and-forget behavior tests ---


@pytest.mark.asyncio
async def test_suppressed_events_skip_publish():
    """Events in suppressed_events should not call _do_publish."""
    with patch("google.cloud.pubsub_v1.PublisherClient"):
        plugin = RedisDashLogPlugin(suppressed_events={"model_start"})
        plugin._do_publish = AsyncMock()

        context = MagicMock()
        context.agent_name = "runner_autopilot"
        context.session = MagicMock()
        context.session.id = "test-session"
        context.invocation_id = "test-inv"
        context.state = {}

        with patch(
            "agents.utils.simulation_registry.get_context_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await plugin._publish(context, {"type": "model_start", "agent": "runner"})

        plugin._do_publish.assert_not_called()


@pytest.mark.asyncio
async def test_fire_and_forget_creates_task():
    """With fire_and_forget=True, _do_publish should still be called (via create_task)."""
    with patch("google.cloud.pubsub_v1.PublisherClient"):
        plugin = RedisDashLogPlugin(fire_and_forget=True)

        publish_called = asyncio.Event()
        original_do_publish = AsyncMock(side_effect=lambda *a, **kw: publish_called.set())
        plugin._do_publish = original_do_publish

        context = MagicMock()
        context.agent_name = "runner_autopilot"
        context.session = MagicMock()
        context.session.id = "test-session"
        context.invocation_id = "test-inv"
        context.state = {}

        with patch(
            "agents.utils.simulation_registry.get_context_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await plugin._publish(context, {"type": "tool_end", "agent": "runner"})

        # Give the task a chance to run
        await asyncio.sleep(0.05)
        assert publish_called.is_set()
