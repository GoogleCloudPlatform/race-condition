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

"""Tests for the planner_with_memory agent entry point."""


def test_root_agent_exists_and_has_correct_name():
    """root_agent must exist and be named 'planner_with_memory'."""
    from agents.planner_with_memory.agent import root_agent

    assert root_agent is not None
    assert root_agent.name == "planner_with_memory"


def test_root_agent_has_memory_tools():
    """root_agent must have memory tools registered."""
    from agents.planner_with_memory.agent import root_agent

    tool_names = {getattr(t, "name", type(t).__name__) for t in root_agent.tools}
    assert "store_route" in tool_names, "store_route missing from agent tools"
    assert "get_best_route" in tool_names, "get_best_route missing from agent tools"


def test_root_agent_has_compliance_tool():
    """root_agent must have get_local_and_traffic_rules registered."""
    from agents.planner_with_memory.agent import root_agent

    tool_names = {getattr(t, "name", type(t).__name__) for t in root_agent.tools}
    assert "get_local_and_traffic_rules" in tool_names, "get_local_and_traffic_rules missing from agent tools"


def test_agent_card_exists():
    """agent_card must be created for A2A discovery."""
    from agents.planner_with_memory.agent import agent_card

    assert agent_card is not None
    assert agent_card.name is not None


def test_plan_marathon_event_not_top_level():
    """plan_marathon_event must NOT be a top-level tool (accessed via SkillToolset)."""
    from agents.planner_with_memory.agent import root_agent

    tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in root_agent.tools]
    assert "plan_marathon_event" not in tool_names


def test_default_port_fallback():
    """Default port fallback must be 8209."""
    import os

    # Clear any existing PORT/PLANNER_WITH_MEMORY_PORT to test defaults
    orig_port = os.environ.pop("PORT", None)
    orig_mem_port = os.environ.pop("PLANNER_WITH_MEMORY_PORT", None)
    try:
        from agents.utils import config

        port = int(config.optional("PORT", config.optional("PLANNER_WITH_MEMORY_PORT", "8209")))
        assert port == 8209
    finally:
        if orig_port is not None:
            os.environ["PORT"] = orig_port
        if orig_mem_port is not None:
            os.environ["PLANNER_WITH_MEMORY_PORT"] = orig_mem_port
