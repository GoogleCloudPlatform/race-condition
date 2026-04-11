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

"""Tests for _run_honcho_with_logging -- tee-style subprocess output capture."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_process(lines, returncode=0):
    """Create a mock Popen whose stdout yields the given lines.

    Each line is yielded as a bytes object (simulating a binary-mode pipe).
    """
    proc = MagicMock()
    proc.stdout.__iter__ = MagicMock(return_value=iter(lines))
    proc.wait.return_value = returncode
    proc.returncode = returncode
    return proc


class TestRunHonchoWithLogging:
    """Tests for the _run_honcho_with_logging helper."""

    def test_creates_logs_directory(self, tmp_path):
        """Verify logs/ dir is created if missing."""
        from scripts.core.sim import _run_honcho_with_logging

        log_path = tmp_path / "logs" / "simulation.log"
        assert not log_path.parent.exists()

        with patch("scripts.core.sim.subprocess.Popen", return_value=_make_mock_process([])):
            _run_honcho_with_logging(cmd=["honcho", "start"], log_path=log_path)

        assert log_path.parent.is_dir()

    def test_writes_output_to_logfile(self, tmp_path):
        """Verify Honcho output ends up in the logfile and Popen is called correctly."""
        from scripts.core.sim import _run_honcho_with_logging

        log_path = tmp_path / "logs" / "simulation.log"
        lines = [b"Starting gateway...\n", b"Starting runner...\n"]
        cmd = ["honcho", "start", "-f", "Procfile"]

        with patch("scripts.core.sim.subprocess.Popen", return_value=_make_mock_process(lines)) as mock_popen:
            _run_honcho_with_logging(cmd=cmd, log_path=log_path)

        mock_popen.assert_called_once_with(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        content = log_path.read_text()
        assert "Starting gateway..." in content
        assert "Starting runner..." in content

    def test_writes_output_to_stdout(self, tmp_path, capsys):
        """Verify output is also written to stdout (tee behavior)."""
        from scripts.core.sim import _run_honcho_with_logging

        log_path = tmp_path / "logs" / "simulation.log"
        lines = [b"hello from honcho\n"]

        with patch("scripts.core.sim.subprocess.Popen", return_value=_make_mock_process(lines)):
            _run_honcho_with_logging(cmd=["honcho", "start"], log_path=log_path)

        captured = capsys.readouterr()
        assert "hello from honcho" in captured.out

    def test_truncates_logfile_on_start(self, tmp_path):
        """Verify logfile is truncated (not appended) each run."""
        from scripts.core.sim import _run_honcho_with_logging

        log_path = tmp_path / "logs" / "simulation.log"
        log_path.parent.mkdir(parents=True)
        log_path.write_text("old content from previous run\n")

        lines = [b"fresh output\n"]
        with patch("scripts.core.sim.subprocess.Popen", return_value=_make_mock_process(lines)):
            _run_honcho_with_logging(cmd=["honcho", "start"], log_path=log_path)

        content = log_path.read_text()
        assert "old content" not in content
        assert "fresh output" in content

    def test_raises_on_nonzero_exit(self, tmp_path):
        """Verify non-zero exit code raises SystemExit with the process exit code."""
        from scripts.core.sim import _run_honcho_with_logging

        log_path = tmp_path / "logs" / "simulation.log"

        with patch("scripts.core.sim.subprocess.Popen", return_value=_make_mock_process([], returncode=42)):
            with pytest.raises(SystemExit) as exc_info:
                _run_honcho_with_logging(cmd=["honcho", "start"], log_path=log_path)

        assert exc_info.value.code == 42

    def test_handles_keyboard_interrupt(self, tmp_path):
        """Verify KeyboardInterrupt terminates process cleanly."""
        from scripts.core.sim import _run_honcho_with_logging

        log_path = tmp_path / "logs" / "simulation.log"

        proc = _make_mock_process([])
        # Make iterating stdout raise KeyboardInterrupt
        proc.stdout.__iter__ = MagicMock(side_effect=KeyboardInterrupt)

        with patch("scripts.core.sim.subprocess.Popen", return_value=proc):
            _run_honcho_with_logging(cmd=["honcho", "start"], log_path=log_path)

        proc.terminate.assert_called_once()
        proc.wait.assert_called()
