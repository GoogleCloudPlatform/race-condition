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

"""Tests for runner_autopilot agent wiring.

PARITY: Keep in sync with agents/npc/runner/tests/test_agent.py.
Both runner agents must expose identical external interfaces (tools, A2A, card).
"""

from agents.npc.runner_autopilot.agent import (
    root_agent,
    get_agent,
    agent_card,
    runner_a2a_agent,
)


def test_root_agent_exists():
    assert root_agent is not None


def test_root_agent_name():
    assert root_agent.name == "runner_autopilot"


def test_root_agent_has_before_model_callback():
    """Autopilot uses before_model_callback for deterministic decisions (runner does not)."""
    assert root_agent.before_model_callback is not None


def test_root_agent_has_expected_tools():
    """Both runner agents must expose the same tool set for interface parity."""
    tool_names = {t.__name__ for t in root_agent.tools}
    expected = {
        "accelerate",
        "brake",
        "get_vitals",
        "process_tick",
        "deplete_water",
        "rehydrate",
        "validate_and_emit_a2ui",
    }
    assert expected == tool_names


def test_tools_come_from_shared_module():
    """Verify autopilot tools are the canonical shared implementations.

    Note: validate_and_emit_a2ui is loaded dynamically from agents/skills/
    a2ui-rendering/ (hyphenated, no __init__.py) and cannot be identity-checked
    via normal import.  Its presence is verified by test_root_agent_has_expected_tools.
    """
    from agents.npc.runner_shared import running as shared_running
    from agents.npc.runner_shared import hydration as shared_hydration

    tools = {t.__name__: t for t in root_agent.tools}

    assert tools["accelerate"] is shared_running.accelerate
    assert tools["brake"] is shared_running.brake
    assert tools["get_vitals"] is shared_running.get_vitals
    assert tools["process_tick"] is shared_running.process_tick
    assert tools["deplete_water"] is shared_hydration.deplete_water
    assert tools["rehydrate"] is shared_hydration.rehydrate


def test_get_agent_returns_fresh_agent():
    agent = get_agent()
    assert agent is not None
    assert agent.name == "runner_autopilot"
    assert agent is not root_agent


def test_agent_card_exists():
    assert agent_card is not None


def test_a2a_agent_exists():
    assert runner_a2a_agent is not None
