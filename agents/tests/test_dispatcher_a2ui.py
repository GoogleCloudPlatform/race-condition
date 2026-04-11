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

"""Tests that the dispatcher does NOT extract A2UI — it passes through text/json only.

A2UI extraction is the sole responsibility of the plugin's _emit_narrative
(via JSON extraction from validate_and_emit_a2ui tool results on tool_end).
The dispatcher must relay content as-is without parsing special formats.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from agents.utils.dispatcher import RedisOrchestratorDispatcher


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expected_text",
    [
        ('Here are updates: ```a2ui\n{"id": "d1"}\n{"id": "d2"}\n```', "Here are updates:"),
        (
            "Pretty: ```a2ui\n"
            "{\n"
            '  "id": "d1",\n'
            '  "component": {\n'
            '    "Text": {"text": {"literalString": "Hello"}}\n'
            "  }\n"
            "}\n"
            "```",
            "Pretty:",
        ),
        ('Robust: ```a2ui\nSome text {"id": "er1"} more text {"id": "er2"}\n```', "Robust:"),
    ],
    ids=["inline", "pretty-printed", "robustness"],
)
async def test_dispatcher_does_not_extract_a2ui(text, expected_text):
    """Dispatcher should emit text containing A2UI as a single text message."""
    mock_runner = MagicMock()
    mock_runner.app.name = "test_agent"
    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner, redis_url="redis://dummy")

    with patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_gateway:
        mock_event = MagicMock()
        mock_event.author = "test_agent"

        mock_part = MagicMock()
        mock_part.text = text
        mock_part.function_call = None
        mock_part.function_response = None
        mock_event.content.parts = [mock_part]

        async def fake_run_async(*args, **kwargs):
            yield mock_event

        dispatcher.runner.run_async = fake_run_async
        dispatcher.runner.session_service.get_session = AsyncMock(return_value=True)

        await dispatcher._trigger_agent_run_logic(session_id="s1", content="trigger")

        gateway_calls = mock_gateway.call_args_list
        assert len(gateway_calls) == 1
        assert gateway_calls[0].kwargs["msg_type"] == "text"
        emitted_text = gateway_calls[0].kwargs["data"]["text"]
        assert "surfaceUpdate" not in emitted_text
        assert expected_text in emitted_text


@pytest.mark.asyncio
async def test_dispatcher_skips_a2ui_tool_results():
    """Dispatcher must NOT re-emit A2UI tool results — plugin handles them."""
    mock_runner = MagicMock()
    mock_runner.app.name = "test_agent"
    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner, redis_url="redis://dummy")

    with patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_gateway:
        mock_event = MagicMock()
        mock_event.author = "test_agent"

        # Simulate a function_response part (A2UI tool result)
        mock_part = MagicMock()
        mock_part.text = None
        mock_part.function_call = None
        mock_resp = MagicMock()
        mock_resp.response = {"status": "success", "a2ui": {"id": "card1"}}
        mock_part.function_response = mock_resp
        mock_event.content.parts = [mock_part]

        async def fake_run_async(*args, **kwargs):
            yield mock_event

        dispatcher.runner.run_async = fake_run_async
        dispatcher.runner.session_service.get_session = AsyncMock(return_value=True)

        await dispatcher._trigger_agent_run_logic(session_id="s1", content="trigger")

        gateway_calls = mock_gateway.call_args_list

        # A2UI tool results must be skipped — the plugin's _emit_narrative
        # emits these with the correct msg_type="a2ui" wrapper.
        assert len(gateway_calls) == 0, (
            f"Dispatcher should not emit A2UI tool results, but emitted {len(gateway_calls)} message(s)"
        )


@pytest.mark.asyncio
async def test_dispatcher_passes_through_non_a2ui_json():
    """Dispatcher should still emit non-A2UI JSON payloads as json type."""
    mock_runner = MagicMock()
    mock_runner.app.name = "test_agent"
    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner, redis_url="redis://dummy")

    with patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_gateway:
        mock_event = MagicMock()
        mock_event.author = "test_agent"

        # Simulate a function_response part (non-A2UI tool result)
        mock_part = MagicMock()
        mock_part.text = None
        mock_part.function_call = None
        mock_resp = MagicMock()
        mock_resp.response = {"status": "success", "simulation_id": "sim-123"}
        mock_part.function_response = mock_resp
        mock_event.content.parts = [mock_part]

        async def fake_run_async(*args, **kwargs):
            yield mock_event

        dispatcher.runner.run_async = fake_run_async
        dispatcher.runner.session_service.get_session = AsyncMock(return_value=True)

        await dispatcher._trigger_agent_run_logic(session_id="s1", content="trigger")

        gateway_calls = mock_gateway.call_args_list

        # Non-A2UI JSON should still be emitted as json type
        assert len(gateway_calls) == 1
        assert gateway_calls[0].kwargs["msg_type"] == "json"
        assert gateway_calls[0].kwargs["data"]["status"] == "success"
        assert gateway_calls[0].kwargs["data"]["simulation_id"] == "sim-123"
