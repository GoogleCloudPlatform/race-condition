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

"""Tests for simulation_id in emit_gateway_message (Task 12).

These tests verify that:
1. The emit_gateway_message function accepts simulation_id parameter
2. The Wrapper protobuf field is set correctly
3. Backward compatibility is preserved

We test both the function signature (integration) and the protobuf field
directly to avoid flaky interactions with the async publish worker.
"""

import asyncio

import pytest

import agents.utils.pulses as pulses_mod
from gen_proto.gateway import gateway_pb2


class TestEmitGatewayMessageSimulationId:
    """Tests for simulation_id parameter on emit_gateway_message."""

    def test_wrapper_simulation_id_field_set_when_provided(self):
        """Wrapper protobuf should have simulation_id set when provided."""
        wrapper = gateway_pb2.Wrapper(
            timestamp="2026-03-20T10:00:00",
            type="text",
            request_id="gw-test",
            session_id="sess-1",
            payload=b'{"text": "hello"}',
            status="success",
            event="test",
        )
        wrapper.simulation_id = "sim-abc-123"

        # Round-trip through serialization
        serialized = wrapper.SerializeToString()
        parsed = gateway_pb2.Wrapper()
        parsed.ParseFromString(serialized)
        assert parsed.simulation_id == "sim-abc-123"

    def test_wrapper_simulation_id_empty_by_default(self):
        """Wrapper protobuf should have empty simulation_id by default."""
        wrapper = gateway_pb2.Wrapper(
            timestamp="2026-03-20T10:00:00",
            type="text",
            request_id="gw-test",
            session_id="sess-1",
            payload=b'{"text": "hello"}',
            status="success",
            event="test",
        )

        serialized = wrapper.SerializeToString()
        parsed = gateway_pb2.Wrapper()
        parsed.ParseFromString(serialized)
        assert parsed.simulation_id == ""

    @pytest.mark.asyncio
    async def test_integration_wrapper_includes_simulation_id(self):
        """Full integration: emit_gateway_message should set simulation_id on Wrapper."""
        # Re-import the real function to bypass any stale mocks
        # from prior tests that patched agents.utils.pulses.emit_gateway_message
        import importlib

        importlib.reload(pulses_mod)

        captured: list[bytes] = []

        async def fake_publish(data: bytes) -> None:
            captured.append(data)

        saved = pulses_mod._publish_to_gateway
        for task in pulses_mod._worker_tasks:
            task.cancel()
        pulses_mod._worker_tasks = []
        pulses_mod._publish_queue = asyncio.Queue(maxsize=10000)
        pulses_mod._publish_to_gateway = fake_publish  # type: ignore[assignment]
        try:
            await pulses_mod.emit_gateway_message(
                origin={"type": "agent", "id": "test-agent", "session_id": "sess-1"},
                destination=["sess-1"],
                status="success",
                msg_type="json",
                event="test",
                data={"text": "hello"},
                simulation_id="sim-integration-test",
            )
        finally:
            pulses_mod._publish_to_gateway = saved  # type: ignore[assignment]

        assert len(captured) == 1
        wrapper = gateway_pb2.Wrapper()
        wrapper.ParseFromString(captured[0])
        assert wrapper.simulation_id == "sim-integration-test"

    @pytest.mark.asyncio
    async def test_integration_no_simulation_id_is_empty(self):
        """Full integration: emit_gateway_message without simulation_id leaves it empty."""
        import importlib

        importlib.reload(pulses_mod)

        captured: list[bytes] = []

        async def fake_publish(data: bytes) -> None:
            captured.append(data)

        saved = pulses_mod._publish_to_gateway
        for task in pulses_mod._worker_tasks:
            task.cancel()
        pulses_mod._worker_tasks = []
        pulses_mod._publish_queue = asyncio.Queue(maxsize=10000)
        pulses_mod._publish_to_gateway = fake_publish  # type: ignore[assignment]
        try:
            await pulses_mod.emit_gateway_message(
                origin={"type": "agent", "id": "test-agent", "session_id": "sess-1"},
                destination=["sess-1"],
                status="success",
                msg_type="json",
                event="test",
                data={"key": "value"},
            )
        finally:
            pulses_mod._publish_to_gateway = saved  # type: ignore[assignment]

        assert len(captured) == 1
        wrapper = gateway_pb2.Wrapper()
        wrapper.ParseFromString(captured[0])
        assert wrapper.simulation_id == ""


class TestLegacyWrapperSimulationId:
    """Tests for simulation_id pass-through in legacy pulse wrappers."""

    @pytest.mark.asyncio
    async def test_emit_narrative_pulse_forwards_simulation_id(self):
        """emit_narrative_pulse should forward simulation_id to emit_gateway_message."""
        from unittest.mock import AsyncMock, patch

        with patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_emit:
            from agents.utils.pulses import emit_narrative_pulse

            await emit_narrative_pulse(session_id="s1", text="hello", simulation_id="sim-42")
            mock_emit.assert_called_once()
            assert mock_emit.call_args.kwargs.get("simulation_id") == "sim-42"

    @pytest.mark.asyncio
    async def test_emit_narrative_pulse_omits_simulation_id_when_none(self):
        """emit_narrative_pulse should not pass simulation_id when not provided."""
        from unittest.mock import AsyncMock, patch

        with patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_emit:
            from agents.utils.pulses import emit_narrative_pulse

            await emit_narrative_pulse(session_id="s1", text="hello")
            mock_emit.assert_called_once()
            assert mock_emit.call_args.kwargs.get("simulation_id") is None

    @pytest.mark.asyncio
    async def test_emit_inter_agent_pulse_forwards_simulation_id(self):
        """emit_inter_agent_pulse should forward simulation_id through to emit_gateway_message."""
        from unittest.mock import AsyncMock, patch

        with patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_emit:
            from agents.utils.pulses import emit_inter_agent_pulse

            await emit_inter_agent_pulse(
                session_id="s1",
                from_agent="a",
                to_agent="b",
                message="hi",
                simulation_id="sim-42",
            )
            mock_emit.assert_called_once()
            assert mock_emit.call_args.kwargs.get("simulation_id") == "sim-42"

    @pytest.mark.asyncio
    async def test_emit_telemetry_pulse_forwards_simulation_id(self):
        """emit_telemetry_pulse should forward simulation_id to emit_gateway_message."""
        from unittest.mock import AsyncMock, patch

        with patch("agents.utils.pulses.emit_gateway_message", new_callable=AsyncMock) as mock_emit:
            from agents.utils.pulses import emit_telemetry_pulse

            await emit_telemetry_pulse(
                session_id="s1",
                payload={"agent": "x", "type": "telemetry"},
                simulation_id="sim-42",
            )
            mock_emit.assert_called_once()
            assert mock_emit.call_args.kwargs.get("simulation_id") == "sim-42"
