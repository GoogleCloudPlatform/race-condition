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

"""Tests for A2UI emission in plugins.

The plugin's _emit_narrative should ONLY emit A2UI via the JSON extraction path
(tool_end with {"status": "success", "a2ui": ...}). Regex-based extraction from
model_end text is removed to prevent duplicate emissions.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from agents.utils.plugins import RedisDashLogPlugin


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,expected_text",
    [
        ('Check this: ```a2ui\n{"id": "c1"}\n```', "Check this"),
        ('Naked: a2ui\n{"id": "c2"}', "Naked:"),
        ('Malformed: a2ui{"id": "c3"}', "Malformed:"),
    ],
    ids=["fenced", "naked", "malformed"],
)
async def test_model_end_does_not_extract_a2ui(content, expected_text):
    """model_end with A2UI in response text should NOT emit separate a2ui messages."""
    with (
        patch("agents.utils.plugins.pubsub_v1.PublisherClient"),
        patch("agents.utils.plugins.load_dotenv"),
    ):
        plugin = RedisDashLogPlugin()

        with (
            patch("agents.utils.pulses.emit_telemetry_pulse", new_callable=AsyncMock),
            patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_gateway,
        ):
            payload = {
                "type": "model_end",
                "agent": "test_agent",
                "response": {"content": content},
            }

            mock_context = MagicMock()
            mock_context.session.id = "s1"
            mock_context.invocation_id = "i1"

            await plugin._publish(mock_context, payload)

            gateway_calls = mock_gateway.call_args_list
            assert len(gateway_calls) == 1
            assert gateway_calls[0].kwargs["msg_type"] == "text"

            a2ui_calls = [c for c in gateway_calls if c.kwargs.get("msg_type") == "a2ui"]
            assert len(a2ui_calls) == 0

            # Verify A2UI stripped from text and expected prefix survives
            emitted_text = gateway_calls[0].kwargs["data"]["text"]
            assert "surfaceUpdate" not in emitted_text
            assert expected_text in emitted_text


@pytest.mark.asyncio
async def test_tool_end_json_extraction_emits_a2ui():
    """tool_end with validate_and_emit_a2ui result should emit exactly one a2ui message.

    This is the ONLY path that should produce a2ui-type gateway messages.
    """
    with (
        patch("agents.utils.plugins.pubsub_v1.PublisherClient"),
        patch("agents.utils.plugins.load_dotenv"),
    ):
        plugin = RedisDashLogPlugin()

        with (
            patch("agents.utils.pulses.emit_telemetry_pulse", new_callable=AsyncMock),
            patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_gateway,
        ):
            payload = {
                "type": "tool_end",
                "agent": "test_agent",
                "tool": "validate_and_emit_a2ui",
                "result": {
                    "status": "success",
                    "a2ui": {
                        "surfaceUpdate": {
                            "sections": [
                                {
                                    "id": "sec1",
                                    "component": {"Text": {"text": {"literalString": "Hello"}}},
                                }
                            ]
                        }
                    },
                },
            }

            mock_context = MagicMock()
            mock_context.session.id = "s1"
            mock_context.invocation_id = "i1"

            await plugin._publish(mock_context, payload)

            gateway_calls = mock_gateway.call_args_list

            # Expect: 1 text/json message (status) + 1 a2ui message
            a2ui_calls = [c for c in gateway_calls if c.kwargs.get("msg_type") == "a2ui"]
            assert len(a2ui_calls) == 1
            assert "surfaceUpdate" in str(a2ui_calls[0].kwargs["data"])


@pytest.mark.asyncio
async def test_tool_end_error_does_not_emit_a2ui():
    """tool_end with validation error should NOT emit a2ui messages."""
    with (
        patch("agents.utils.plugins.pubsub_v1.PublisherClient"),
        patch("agents.utils.plugins.load_dotenv"),
    ):
        plugin = RedisDashLogPlugin()

        with (
            patch("agents.utils.pulses.emit_telemetry_pulse", new_callable=AsyncMock),
            patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_gateway,
        ):
            payload = {
                "type": "tool_end",
                "agent": "test_agent",
                "tool": "validate_and_emit_a2ui",
                "result": {
                    "status": "error",
                    "violations": [{"component_id": "", "field": "payload", "message": "Invalid JSON"}],
                },
            }

            mock_context = MagicMock()
            mock_context.session.id = "s1"
            mock_context.invocation_id = "i1"

            await plugin._publish(mock_context, payload)

            gateway_calls = mock_gateway.call_args_list

            # No a2ui messages for error results
            a2ui_calls = [c for c in gateway_calls if c.kwargs.get("msg_type") == "a2ui"]
            assert len(a2ui_calls) == 0
