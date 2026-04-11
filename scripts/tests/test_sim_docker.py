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

"""Tests for Docker lifecycle management in sim.py."""

import subprocess
from unittest.mock import patch


class TestPreflightDockerPruning:
    """Verify preflight_infra prunes dead containers and dangling networks."""

    @patch("scripts.core.sim.wait_for_infra")
    @patch("subprocess.run")
    def test_prunes_containers_and_networks_before_start(self, mock_run, _mock_wait):
        """Preflight should prune stopped containers and dangling networks."""
        from scripts.core.sim import preflight_infra

        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

        preflight_infra()

        # Extract the command lists from all subprocess.run calls
        commands = [c.args[0] for c in mock_run.call_args_list if c.args]

        assert ["docker", "container", "prune", "-f"] in commands
        network_prune_cmd = [
            "docker",
            "network",
            "prune",
            "-f",
            "--filter",
            "label=com.docker.compose.project",
        ]
        assert network_prune_cmd in commands

        # Prune calls should appear before the compose up call
        prune_container_idx = next(i for i, cmd in enumerate(commands) if cmd == ["docker", "container", "prune", "-f"])
        prune_network_idx = next(i for i, cmd in enumerate(commands) if cmd == network_prune_cmd)
        compose_up_idx = next(i for i, cmd in enumerate(commands) if "up" in cmd)
        assert prune_container_idx < compose_up_idx
        assert prune_network_idx < compose_up_idx


class TestCliEntryPoints:
    """Verify CLI entry points parse --skip-tests correctly."""

    @patch("scripts.core.sim.start")
    def test_start_cli_passes_skip_tests(self, mock_start):
        """``uv run start --skip-tests`` must pass skip_tests=True."""
        import sys
        from scripts.core.sim import start_cli

        old_argv = sys.argv
        try:
            sys.argv = ["start", "--skip-tests"]
            start_cli()
        finally:
            sys.argv = old_argv

        mock_start.assert_called_once_with(skip_tests=True, include_slow=False)

    @patch("scripts.core.sim.start")
    def test_start_cli_defaults_to_running_tests(self, mock_start):
        """``uv run start`` (no flags) must pass skip_tests=False."""
        import sys
        from scripts.core.sim import start_cli

        old_argv = sys.argv
        try:
            sys.argv = ["start"]
            start_cli()
        finally:
            sys.argv = old_argv

        mock_start.assert_called_once_with(skip_tests=False, include_slow=False)

    @patch("scripts.core.sim.restart")
    def test_restart_cli_passes_skip_tests(self, mock_restart):
        """``uv run restart --skip-tests`` must pass skip_tests=True."""
        import sys
        from scripts.core.sim import restart_cli

        old_argv = sys.argv
        try:
            sys.argv = ["restart", "--skip-tests"]
            restart_cli()
        finally:
            sys.argv = old_argv

        mock_restart.assert_called_once_with(skip_tests=True, include_slow=False)


class TestStopDockerTeardown:
    """Verify stop() properly tears down Docker infrastructure."""

    @patch("scripts.core.sim._read_port_slot", return_value=0)
    @patch("scripts.core.sim._read_ports_from_env", return_value=[])
    @patch("scripts.core.sim.flush_redis")
    @patch("subprocess.run")
    @patch("subprocess.check_output", return_value="")
    @patch("os.walk", return_value=[])
    def test_stop_uses_remove_orphans(self, _walk, _check_out, mock_run, _flush, _ports, _slot):
        """docker-compose down should include --remove-orphans."""
        from scripts.core.sim import stop

        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        stop()

        commands = [c.args[0] for c in mock_run.call_args_list if c.args]
        compose_down_cmds = [cmd for cmd in commands if "down" in cmd]
        assert len(compose_down_cmds) >= 1
        assert "--remove-orphans" in compose_down_cmds[0]
