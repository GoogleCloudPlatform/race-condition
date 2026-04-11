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

"""Tests for DashLogPlugin simulation_id fallback via simulation_registry."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.utils.plugins import RedisDashLogPlugin
from agents.utils.simulation_registry import register


class TestPluginSimulationIdFallback:
    """Tests for _publish simulation_id resolution with registry fallback."""

    def setup_method(self):
        """Clear registry and create a plugin instance."""
        from agents.utils.simulation_registry import _local

        _local.clear()

    def _make_plugin(self) -> RedisDashLogPlugin:
        """Create a RedisDashLogPlugin with mocked transport."""
        with patch("agents.utils.plugins.pubsub_v1"):
            plugin = RedisDashLogPlugin(topic_id="test-topic")
        plugin._do_publish = AsyncMock()
        return plugin

    def _make_context(self, session_id: str, simulation_id: str | None = None):
        """Create a mock context with configurable session state."""
        ctx = MagicMock()
        session_obj = MagicMock()
        session_obj.id = session_id
        ctx.session = session_obj
        ctx.invocation_id = "inv-test-123"
        ctx.agent_name = "test_agent"

        # Set up state — if simulation_id is None, state has no simulation_id key
        state = {}
        if simulation_id is not None:
            state["simulation_id"] = simulation_id
        ctx.state = state

        return ctx

    @pytest.mark.asyncio
    async def test_plugin_uses_registry_when_state_has_no_simulation_id(self):
        """When session state has no simulation_id, plugin should fall back to registry."""
        plugin = self._make_plugin()
        await register("session-runner-1", "sim-from-registry")

        ctx = self._make_context("session-runner-1", simulation_id=None)

        with patch.object(plugin, "_emit_narrative", new_callable=AsyncMock) as mock_narrative:
            await plugin._publish(
                ctx,
                {
                    "type": "tool_end",
                    "agent": "test_agent",
                    "tool": "some_tool",
                    "result": {"status": "ok"},
                    "timestamp": 1234567890.0,
                },
            )

            mock_narrative.assert_called_once()
            call_kwargs = mock_narrative.call_args
            assert call_kwargs[1]["simulation_id"] == "sim-from-registry"

    @pytest.mark.asyncio
    async def test_plugin_prefers_state_over_registry(self):
        """When session state HAS simulation_id, plugin should use it (not registry)."""
        plugin = self._make_plugin()
        await register("session-with-state", "sim-registry-value")

        ctx = self._make_context("session-with-state", simulation_id="sim-from-state")

        with patch.object(plugin, "_emit_narrative", new_callable=AsyncMock) as mock_narrative:
            await plugin._publish(
                ctx,
                {
                    "type": "tool_end",
                    "agent": "test_agent",
                    "tool": "some_tool",
                    "result": {"status": "ok"},
                    "timestamp": 1234567890.0,
                },
            )

            mock_narrative.assert_called_once()
            call_kwargs = mock_narrative.call_args
            assert call_kwargs[1]["simulation_id"] == "sim-from-state"

    @pytest.mark.asyncio
    async def test_plugin_returns_none_when_neither_source_has_id(self):
        """When neither state nor registry has simulation_id, it should be None."""
        plugin = self._make_plugin()

        ctx = self._make_context("session-orphan", simulation_id=None)

        with patch.object(plugin, "_emit_narrative", new_callable=AsyncMock) as mock_narrative:
            await plugin._publish(
                ctx,
                {
                    "type": "tool_end",
                    "agent": "test_agent",
                    "tool": "some_tool",
                    "result": {"status": "ok"},
                    "timestamp": 1234567890.0,
                },
            )

            mock_narrative.assert_called_once()
            call_kwargs = mock_narrative.call_args
            assert call_kwargs[1]["simulation_id"] is None
