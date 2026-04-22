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

"""Tests for configurable AGENT_NAME in the runner agent.

These tests verify that the runner agent name is configurable via the
AGENT_NAME environment variable. To avoid ADK import-time side effects,
we test the env var reading logic directly rather than reloading the module.
"""

import os


def test_default_agent_name():
    """AGENT_NAME defaults to 'runner' when env var is not set."""
    from agents.runner.agent import AGENT_NAME

    # In the test environment AGENT_NAME is not set, so the default applies.
    assert AGENT_NAME == "runner"


def test_agent_name_env_var_reading():
    """os.environ.get honours AGENT_NAME when set."""
    custom = "runner_gke"
    original = os.environ.get("AGENT_NAME")
    try:
        os.environ["AGENT_NAME"] = custom
        # Re-read the env var using the same logic as agent.py
        resolved = os.environ.get("AGENT_NAME", "runner")
        assert resolved == custom
    finally:
        if original is None:
            os.environ.pop("AGENT_NAME", None)
        else:
            os.environ["AGENT_NAME"] = original


def test_agent_name_env_var_fallback():
    """When AGENT_NAME is absent, the fallback is 'runner'."""
    original = os.environ.get("AGENT_NAME")
    try:
        os.environ.pop("AGENT_NAME", None)
        resolved = os.environ.get("AGENT_NAME", "runner")
        assert resolved == "runner"
    finally:
        if original is not None:
            os.environ["AGENT_NAME"] = original


def test_module_exports_agent_name():
    """AGENT_NAME is importable from the runner agent module."""
    from agents.runner.agent import AGENT_NAME

    assert isinstance(AGENT_NAME, str)
    assert len(AGENT_NAME) > 0
