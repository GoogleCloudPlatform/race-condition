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
from unittest.mock import patch
from agents.utils.pulses import emit_gateway_message
from gen_proto.gateway import gateway_pb2


@pytest.mark.asyncio
@patch("agents.utils.pulses._publish_to_gateway")
async def test_emit_gateway_message_structure(mock_publisher):

    # Call the new unified function
    await emit_gateway_message(
        origin={"type": "agent", "id": "test-agent", "session_id": "sim-123"},
        destination=["client-1"],
        status="success",
        msg_type="json",
        event="narrative",
        data={"text": "hello"},
        metadata={"tokens": 100},
    )

    # Assert
    mock_publisher.assert_called_once()
    wrapper_bytes = mock_publisher.call_args[0][0]

    # Decode the protobuf wrapper
    wrapper = gateway_pb2.Wrapper()
    wrapper.ParseFromString(wrapper_bytes)

    # Validate protobuf envelope
    assert wrapper.type == "json"
    assert wrapper.event == "narrative"
    assert wrapper.status == "success"
    assert wrapper.origin.type == "agent"
    assert wrapper.origin.id == "test-agent"
    assert wrapper.origin.session_id == "sim-123"
    assert list(wrapper.destination) == ["client-1"]

    # Validate JSON encoded metadata
    metadata = json.loads(wrapper.metadata.decode("utf-8"))
    assert metadata["tokens"] == 100

    # Validate JSON encoded data
    payload = json.loads(wrapper.payload.decode("utf-8"))
    assert payload["text"] == "hello"
