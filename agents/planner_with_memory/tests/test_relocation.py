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

"""Boundary tests verifying memory tools are exclusive to planner_with_memory.

These tests assert that:
- planner_with_memory tools include ALL 5 memory tools
- planner_with_memory tools inherit ALL planner_with_eval tools
- Memory tools do NOT leak into planner_with_eval or base planner
"""

MEMORY_TOOL_NAMES = {
    "store_route",
    "record_simulation",
    "recall_routes",
    "get_route",
    "get_best_route",
}

# Tools expected as top-level FunctionTools
INHERITED_TOP_LEVEL_TOOLS = {
    "evaluate_plan",
    "submit_plan_to_simulator",
    "validate_and_emit_a2ui",
}

# Direct FunctionTools (not part of any skill)
INHERITED_STATEFUL_TOOLS = set()  # All moved to additional_tools

# Skill tools that activate after load_skill (not top-level)
SKILL_ADDITIONAL_TOOLS = {
    "report_marathon_route",
    "assess_traffic_impact",
    "plan_marathon_route",
    "plan_marathon_event",
}


def _extract_tool_names(tools: list) -> set[str]:
    """Extract names from a list of ADK tools."""
    return {t.name if hasattr(t, "name") else type(t).__name__ for t in tools}


def test_planner_with_memory_includes_all_memory_tools():
    """planner_with_memory tools must include all 5 memory tools."""
    from agents.planner_with_memory.adk_tools import get_tools

    tool_names = _extract_tool_names(get_tools())

    for name in MEMORY_TOOL_NAMES:
        assert name in tool_names, f"Memory tool '{name}' missing from planner_with_memory"


def test_planner_with_memory_inherits_all_eval_tools():
    """planner_with_memory tools must include ALL planner_with_eval tools."""
    from google.adk.tools.skill_toolset import SkillToolset
    from agents.planner_with_memory.adk_tools import get_tools

    tools = get_tools()
    tool_names = _extract_tool_names(tools)

    for name in INHERITED_TOP_LEVEL_TOOLS:
        assert name in tool_names, f"Inherited tool '{name}' missing from planner_with_memory"
    # Skill tools must NOT be top-level (activate after load_skill)
    for name in SKILL_ADDITIONAL_TOOLS:
        assert name not in tool_names, f"Skill tool '{name}' should not be a top-level FunctionTool"
    # Skill tools must be in the SkillToolset candidate pool
    st = [t for t in tools if isinstance(t, SkillToolset)][0]
    for name in SKILL_ADDITIONAL_TOOLS:
        assert name in st._provided_tools_by_name, f"Tool '{name}' missing from SkillToolset additional_tools"


def test_memory_tools_not_in_planner_with_eval():
    """Memory tools must NOT be registered in planner_with_eval."""
    from agents.planner_with_eval.adk_tools import get_tools as get_eval_tools

    tool_names = _extract_tool_names(get_eval_tools())

    for name in MEMORY_TOOL_NAMES:
        assert name not in tool_names, f"Memory tool '{name}' should NOT exist in planner_with_eval"


def test_memory_tools_not_in_base_planner():
    """Memory tools must NOT be registered in the base planner."""
    from agents.planner.adk_tools import get_tools as get_base_tools

    tool_names = _extract_tool_names(get_base_tools())

    for name in MEMORY_TOOL_NAMES:
        assert name not in tool_names, f"Memory tool '{name}' should NOT exist in base planner"
