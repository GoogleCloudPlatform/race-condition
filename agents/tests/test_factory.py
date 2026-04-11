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

"""Tests for agents.utils.factory — simulation runner creation.

Session service selection is tested in test_runtime.py.
These tests focus on factory responsibilities: plugin wiring, app creation,
runner construction, and delegation to create_services().
"""

from unittest.mock import MagicMock, patch

import pytest

from agents.utils.runtime import ServiceConfig


def _mock_service_config():
    """Create a mock ServiceConfig for factory tests."""
    return ServiceConfig(
        session_service=MagicMock(),
        artifact_service=None,
        memory_service=None,
        target="local",
    )


class TestCreateSimulationRunner:
    """Tests for create_simulation_runner factory function."""

    @pytest.fixture
    def mocks(self):
        """Shared mock context for all factory tests."""
        with (
            patch("agents.utils.factory.create_services", return_value=_mock_service_config()) as mock_cs,
            patch("agents.utils.factory.Runner") as mock_runner,
            patch("agents.utils.factory.App") as mock_app,
            patch("agents.utils.factory.config") as mock_config,
            patch("agents.utils.factory.RedisDashLogPlugin") as mock_dash,
            patch("agents.utils.factory.SimulationNetworkPlugin") as mock_sim,
        ):
            mock_config.load_env.return_value = None
            yield {
                "create_services": mock_cs,
                "Runner": mock_runner,
                "App": mock_app,
                "config": mock_config,
                "RedisDashLogPlugin": mock_dash,
                "SimulationNetworkPlugin": mock_sim,
            }

    def test_creates_runner_with_default_plugins(self, mocks):
        """Factory should create a Runner with RedisDashLogPlugin and SimulationNetworkPlugin."""
        from agents.utils.factory import create_simulation_runner

        runner, app, orch_plugin = create_simulation_runner(
            name="test-agent",
            root_agent=MagicMock(),
        )

        mocks["RedisDashLogPlugin"].assert_called_once()
        mocks["SimulationNetworkPlugin"].assert_called_once_with(name="test-agent", suppress_gateway_emission=False)
        mocks["App"].assert_called_once()
        call_kwargs = mocks["App"].call_args
        assert call_kwargs.kwargs.get("name") or call_kwargs[1].get("name") == "test-agent"

    def test_extra_plugins_appended(self, mocks):
        """Extra plugins should be added after the standard ones."""
        extra = MagicMock()

        from agents.utils.factory import create_simulation_runner

        create_simulation_runner(
            name="test-agent",
            root_agent=MagicMock(),
            extra_plugins=[extra],
        )

        call_kwargs = mocks["App"].call_args
        plugins_arg = call_kwargs.kwargs.get("plugins") or call_kwargs[1].get("plugins")
        assert len(plugins_arg) == 3
        assert plugins_arg[2] is extra

    def test_delegates_to_create_services(self, mocks):
        """Factory should delegate session service creation to runtime.create_services()."""
        from agents.utils.factory import create_simulation_runner

        create_simulation_runner(name="test", root_agent=MagicMock())

        mocks["create_services"].assert_called_once()

    def test_passes_session_service_to_runner(self, mocks):
        """Factory should pass the session service from create_services to Runner."""
        from agents.utils.factory import create_simulation_runner

        create_simulation_runner(name="test", root_agent=MagicMock())

        # Verify Runner was called with the session service from ServiceConfig
        runner_call_kwargs = mocks["Runner"].call_args
        assert runner_call_kwargs.kwargs.get("session_service") is mocks["create_services"].return_value.session_service

    def test_wires_orchestration_plugin(self, mocks):
        """Factory should wire the orchestration plugin's runner reference."""
        mock_orch = mocks["SimulationNetworkPlugin"].return_value

        from agents.utils.factory import create_simulation_runner

        create_simulation_runner(name="test", root_agent=MagicMock())

        mock_orch.set_runner.assert_called_once_with(mocks["Runner"].return_value)
