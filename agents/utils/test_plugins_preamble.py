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
from unittest.mock import AsyncMock, patch
from agents.utils.plugins import RedisDashLogPlugin


@pytest.mark.asyncio
async def test_redis_dash_log_plugin_narrative_preamble():
    # Mock Redis emission
    with (
        patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_gateway,
        patch("agents.utils.pulses.emit_telemetry_pulse", new_callable=AsyncMock),
    ):
        plugin = RedisDashLogPlugin()

        # Simulate a tool_end event from a runner_agent
        payload = {
            "type": "tool_end",
            "agent": "runner_agent",
            "tool": "accelerate",
            "args": {"amount": 10},
            "result": {"status": "ok"},
        }

        # Mock the context object
        from unittest.mock import MagicMock

        mock_context = MagicMock()
        mock_context.session.id = "test-session"
        mock_context.invocation_id = "inv-123"

        # We need to mock the sequence counter since we don't have a real agent context
        from collections import defaultdict

        plugin._sequence_counters = defaultdict(int)

        await plugin._publish(mock_context, payload)

        # Verify gateway message call
        mock_gateway.assert_called_once()
        kwargs = mock_gateway.call_args.kwargs

        assert kwargs["msg_type"] == "json"

        # Verify Preamble format is discarded for direct JSON results,
        # or we fetch the preamble text if it wasn't valid json
        data = kwargs["data"]
        assert data["result"]["status"] == "ok"
        assert data["tool_name"] == "accelerate"


@pytest.mark.asyncio
async def test_redis_dash_log_plugin_model_end_preamble():
    with (
        patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_gateway,
        patch("agents.utils.pulses.emit_telemetry_pulse", new_callable=AsyncMock),
    ):
        plugin = RedisDashLogPlugin()
        payload = {"type": "model_end", "agent": "orchestrator_agent"}

        from unittest.mock import MagicMock

        mock_context = MagicMock()
        mock_context.session.id = "test-session"
        mock_context.invocation_id = "inv-456"

        from collections import defaultdict

        plugin._sequence_counters = defaultdict(int)

        await plugin._publish(mock_context, payload)

        # Verify Preamble format: [Orchestrator] Model End
        text = mock_gateway.call_args.kwargs["data"]["text"]
        assert "[Orchestrator] Model End" in text


@pytest.mark.asyncio
async def test_redis_dash_log_plugin_display_name_override():
    with (
        patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_gateway,
        patch("agents.utils.pulses.emit_telemetry_pulse", new_callable=AsyncMock),
    ):
        plugin = RedisDashLogPlugin(
            agent_display_names={"simulator_with_failure": "Simulator"},
        )
        payload = {
            "type": "tool_error",
            "agent": "simulator_with_failure",
            "tool": "run_simulation",
            "error": "Simulation engine encountered an unexpected state",
        }

        from unittest.mock import MagicMock

        mock_context = MagicMock()
        mock_context.session.id = "test-session"
        mock_context.invocation_id = "inv-789"

        from collections import defaultdict

        plugin._sequence_counters = defaultdict(int)

        await plugin._publish(mock_context, payload)

        text = mock_gateway.call_args.kwargs["data"]["text"]
        assert "[Simulator] Tool Error: run_simulation" in text
        assert "Simulator_With_Failure" not in text


@pytest.mark.asyncio
async def test_redis_dash_log_plugin_display_name_fallback():
    """Agents not in the display_names dict still use the default title-case."""
    with (
        patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_gateway,
        patch("agents.utils.pulses.emit_telemetry_pulse", new_callable=AsyncMock),
    ):
        plugin = RedisDashLogPlugin(
            agent_display_names={"some_other_agent": "Other"},
        )
        payload = {"type": "model_end", "agent": "runner_agent"}

        from unittest.mock import MagicMock

        mock_context = MagicMock()
        mock_context.session.id = "test-session"
        mock_context.invocation_id = "inv-fallback"

        from collections import defaultdict

        plugin._sequence_counters = defaultdict(int)

        await plugin._publish(mock_context, payload)

        text = mock_gateway.call_args.kwargs["data"]["text"]
        assert "[Runner] Model End" in text
