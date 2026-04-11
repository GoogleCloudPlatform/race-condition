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


def test_planner_tool_registration():
    """Verify planner tools use adk_additional_tools for on-demand activation."""
    from google.adk.tools.skill_toolset import SkillToolset
    from agents.planner.adk_tools import get_tools

    tools = get_tools()
    tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]

    # Skill tools are NOT top-level — they activate after load_skill
    skill_tool_names = [
        "plan_marathon_route",
        "report_marathon_route",
        "plan_marathon_event",
    ]
    for name in skill_tool_names:
        assert name not in tool_names, f"Tool '{name}' should not be top-level; it activates after load_skill."

    # assess_traffic_impact is NOT available in the base planner
    assert "assess_traffic_impact" not in tool_names

    # SkillToolset must be present with additional_tools configured
    st = [t for t in tools if isinstance(t, SkillToolset)][0]
    assert st._code_executor is not None
    assert len(st._provided_tools_by_name) > 0, "SkillToolset must have additional_tools"

    # Base planner tools must be in the candidate pool
    for name in skill_tool_names:
        assert name in st._provided_tools_by_name, f"Tool '{name}' missing from SkillToolset additional_tools"

    # assess_traffic_impact is NOT in the base planner's pool (only in planner_with_eval)
    assert "assess_traffic_impact" not in st._provided_tools_by_name


if __name__ == "__main__":
    test_planner_tool_registration()
    print("✅ Planner tool registration test passed!")
