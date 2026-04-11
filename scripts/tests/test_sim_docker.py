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

import pytest


class TestReadPortsFromEnv:
    def test_excludes_frontend_app_port(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("GATEWAY_PORT=8101\nFRONTEND_APP_PORT=8501\nADMIN_PORT=8000\n")

        with patch("scripts.core.sim.ROOT_DIR", str(tmp_path)):
            from scripts.core.sim import _read_ports_from_env

            ports = _read_ports_from_env()

        assert 8101 in ports
        assert 8000 in ports
        assert 8501 not in ports


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


class TestPreflightDockerRetry:
    """Verify preflight_infra retries docker info on transient failures."""

    @patch("scripts.core.sim.wait_for_infra")
    @patch("time.sleep")
    @patch("subprocess.run")
    def test_retries_docker_info_on_failure(self, mock_run, mock_sleep, _mock_wait):
        """docker info failing then succeeding should not exit."""
        from scripts.core.sim import preflight_infra

        fail = subprocess.CalledProcessError(1, "docker info")
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
        # Fail twice, then succeed on third attempt.
        # Subsequent calls (prune, compose up, etc.) all succeed.
        mock_run.side_effect = [fail, fail, ok] + [ok] * 20

        preflight_infra()

        docker_info_calls = [c for c in mock_run.call_args_list if c.args and c.args[0] == ["docker", "info"]]
        assert len(docker_info_calls) == 3
        assert mock_sleep.call_count == 2

    @patch("scripts.core.sim.wait_for_infra")
    @patch("time.sleep")
    @patch("subprocess.run")
    def test_exits_after_max_retries(self, mock_run, mock_sleep, _mock_wait):
        """docker info failing on all attempts should sys.exit(1)."""
        import sys
        from scripts.core.sim import preflight_infra

        mock_run.side_effect = subprocess.CalledProcessError(1, "docker info")

        with pytest.raises(SystemExit) as exc_info:
            preflight_infra()
        assert exc_info.value.code == 1
        assert mock_sleep.call_count == 4  # retries 1-4 sleep, 5th exits


class TestStopInfraProcessProtection:
    """Verify stop() skips Colima/Docker infrastructure processes."""

    @patch("scripts.core.sim._read_port_slot", return_value=0)
    @patch("scripts.core.sim._read_ports_from_env", return_value=[8104])
    @patch("scripts.core.sim.flush_redis")
    @patch("subprocess.run")
    @patch("os.walk", return_value=[])
    def test_skips_colima_process_on_port(self, _walk, mock_run, _flush, _ports, _slot):
        from scripts.core.sim import stop

        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        def check_output_side_effect(*args, **kwargs):
            cmd = args[0]
            if isinstance(cmd, str) and "lsof" in cmd:
                return b"12345"
            if isinstance(cmd, list) and "ps" in cmd:
                return "/Users/me/.colima/_lima/colima/ssh.sock [mux]\n"
            return b""

        with patch("subprocess.check_output", side_effect=check_output_side_effect):
            stop()

        # Should NOT have killed pid 12345 (it's a colima process)
        kill_calls = [c for c in mock_run.call_args_list if c.args and c.args[0] == ["kill", "-9", "12345"]]
        assert len(kill_calls) == 0

    @patch("scripts.core.sim._read_port_slot", return_value=0)
    @patch("scripts.core.sim._read_ports_from_env", return_value=[8501])
    @patch("scripts.core.sim.flush_redis")
    @patch("subprocess.run")
    @patch("os.walk", return_value=[])
    def test_kills_normal_process_on_port(self, _walk, mock_run, _flush, _ports, _slot):
        from scripts.core.sim import stop

        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        def check_output_side_effect(*args, **kwargs):
            cmd = args[0]
            if isinstance(cmd, str) and "lsof" in cmd:
                return b"99999"
            if isinstance(cmd, list) and "ps" in cmd:
                return "go run cmd/frontend/main.go\n"
            return b""

        with patch("subprocess.check_output", side_effect=check_output_side_effect):
            stop()

        kill_calls = [c for c in mock_run.call_args_list if c.args and c.args[0] == ["kill", "-9", "99999"]]
        assert len(kill_calls) == 1


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
