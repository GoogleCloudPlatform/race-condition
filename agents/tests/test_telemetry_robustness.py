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
import json
from unittest.mock import MagicMock, AsyncMock, patch
from agents.utils.plugins import (
    _safe_json_dumps,
    RedisDashLogPlugin,
)
from pydantic import BaseModel
from google.adk.agents.callback_context import CallbackContext


def test_safe_json_serialization_robustness():
    """Verify that _safe_json_dumps handles edge cases and avoids double-encoding."""
    # 1. Simple dict
    d = {"a": 1, "b": "test"}
    assert json.loads(_safe_json_dumps(d)) == d

    # 2. Nested dict (Regression: shouldn't be double-encoded)
    nested = {"a": {"b": {"c": 1}}}
    dumped = _safe_json_dumps(nested)
    # If double encoded, json.loads would return a dict where values are strings
    parsed = json.loads(dumped)
    assert parsed == nested
    assert isinstance(parsed["a"], dict)

    # 3. Pydantic Model (Robustness 3.0)
    class MyModel(BaseModel):
        name: str
        value: int

    model = MyModel(name="test", value=123)
    parsed = json.loads(_safe_json_dumps(model))
    assert parsed == {"name": "test", "value": 123}

    # 4. Non-serializable object
    class NonSerial:
        def __str__(self):
            return "non-serial-obj"

    obj = {"data": NonSerial()}
    parsed = json.loads(_safe_json_dumps(obj))
    assert parsed["data"] == "non-serial-obj"

    # 4. None and primitives
    assert _safe_json_dumps(None) == "null"
    assert _safe_json_dumps(123) == "123"


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
async def test_redis_dash_log_callback_coverage(mock_pubsub):
    """Verify that all essential lifecycle callbacks are implemented and emit pulses."""
    plugin = RedisDashLogPlugin()
    plugin._publish = AsyncMock()

    mock_context = MagicMock(spec=CallbackContext)
    mock_context.session.id = "s1"
    mock_context.invocation_id = "i1"
    mock_context.agent_name = "test-agent"

    mock_agent = MagicMock()
    mock_agent.name = "test-agent"

    # Test before_agent
    await plugin.before_agent_callback(agent=mock_agent, callback_context=mock_context)
    plugin._publish.assert_called_with(
        mock_context,
        {
            "type": "agent_start",
            "agent": "test-agent",
            "timestamp": _any_int_or_float,
        },
    )

    # Test before_model
    mock_req = MagicMock()
    mock_req.model = "gemini-3"
    await plugin.before_model_callback(callback_context=mock_context, llm_request=mock_req)
    plugin._publish.assert_called_with(
        mock_context,
        {
            "type": "model_start",
            "agent": "test-agent",
            "model": "gemini-3",
            "timestamp": _any_int_or_float,
        },
    )


@pytest.mark.asyncio
@patch("google.cloud.pubsub_v1.PublisherClient")
async def test_a2ui_extraction_from_dict(mock_pubsub):
    """Verify that A2UI is correctly extracted when the tool returns a dict."""
    plugin = RedisDashLogPlugin()
    plugin.publisher = MagicMock()
    # Mock emit_telemetry_pulse
    import agents.utils.pulses

    agents.utils.pulses.emit_telemetry_pulse = AsyncMock()
    agents.utils.pulses.emit_gateway_message = AsyncMock()

    mock_context = MagicMock()
    mock_context.session.id = "s1"
    mock_context.invocation_id = "i1"
    mock_context.agent_name = "test-agent"

    # Setting name attribute properly to prevent MagicMock recursion in json_dumps
    mock_tool = MagicMock()
    mock_tool.name = "t1"

    # Case: Tool returns a dict with 'a2ui' key (standardized)
    result = {"status": "success", "a2ui": '{"id": "c1"}'}
    await plugin.after_tool_callback(tool=mock_tool, tool_args={}, tool_context=mock_context, result=result)

    # Extract the a2ui call to emit_gateway_message
    gateway_calls = agents.utils.pulses.emit_gateway_message.call_args_list
    # The first call should be text, the second a2ui if we split them
    a2ui_call = next((call for call in gateway_calls if call.kwargs.get("msg_type") == "a2ui"), None)
    assert a2ui_call is not None

    a2ui_payload = a2ui_call.kwargs["data"]
    assert "c1" in str(a2ui_payload)


class AnyIntOrFloat:
    def __eq__(self, other: object) -> bool:
        return isinstance(other, (int, float))


_any_int_or_float = AnyIntOrFloat()
