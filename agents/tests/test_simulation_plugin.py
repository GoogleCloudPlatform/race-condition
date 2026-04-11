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

"""Tests for agents.utils.simulation_plugin — dispatcher lifecycle management."""

import pytest
from unittest.mock import MagicMock, patch


class TestSimulationNetworkPlugin:
    """Tests for the SimulationNetworkPlugin ADK lifecycle hooks."""

    @patch("agents.utils.simulation_plugin.RedisOrchestratorDispatcher")
    def test_set_runner_creates_dispatcher(self, mock_dispatcher_cls):
        """set_runner should create a new dispatcher and start it."""
        from agents.utils.simulation_plugin import SimulationNetworkPlugin

        plugin = SimulationNetworkPlugin()
        mock_runner = MagicMock()

        plugin.set_runner(mock_runner)

        assert plugin.runner is mock_runner
        mock_dispatcher_cls.assert_called_once_with(runner=mock_runner, dispatch_mode="subscriber")
        mock_dispatcher_cls.return_value.start.assert_called_once()

    @patch("agents.utils.simulation_plugin.RedisOrchestratorDispatcher")
    def test_set_runner_passes_callable_dispatch_mode(self, mock_dispatcher_cls, monkeypatch):
        """DISPATCH_MODE=callable should be passed through to dispatcher."""
        from agents.utils.simulation_plugin import SimulationNetworkPlugin

        monkeypatch.setenv("DISPATCH_MODE", "callable")
        plugin = SimulationNetworkPlugin()
        mock_runner = MagicMock()

        plugin.set_runner(mock_runner)

        mock_dispatcher_cls.assert_called_once_with(runner=mock_runner, dispatch_mode="callable")

    @patch("agents.utils.simulation_plugin.RedisOrchestratorDispatcher")
    def test_set_runner_stops_existing_dispatcher(self, mock_dispatcher_cls):
        """Calling set_runner twice should stop the first dispatcher before creating a new one."""
        from agents.utils.simulation_plugin import SimulationNetworkPlugin

        plugin = SimulationNetworkPlugin()

        first_dispatcher = MagicMock()
        mock_dispatcher_cls.return_value = first_dispatcher
        plugin.set_runner(MagicMock())

        second_dispatcher = MagicMock()
        mock_dispatcher_cls.return_value = second_dispatcher
        plugin.set_runner(MagicMock())

        first_dispatcher.stop.assert_called_once()
        second_dispatcher.start.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.utils.simulation_plugin.RedisOrchestratorDispatcher")
    async def test_close_stops_dispatcher(self, mock_dispatcher_cls):
        """close() should stop the dispatcher."""
        from agents.utils.simulation_plugin import SimulationNetworkPlugin

        plugin = SimulationNetworkPlugin()
        mock_runner = MagicMock()
        plugin.set_runner(mock_runner)

        await plugin.close()

        mock_dispatcher_cls.return_value.stop.assert_called()

    @pytest.mark.asyncio
    async def test_close_without_dispatcher(self):
        """close() should not crash if no dispatcher was ever created."""
        from agents.utils.simulation_plugin import SimulationNetworkPlugin

        plugin = SimulationNetworkPlugin()

        # Should not raise
        await plugin.close()
