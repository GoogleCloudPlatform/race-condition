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

"""Tests verifying tool and skill organization in planner_with_eval.

These tests assert the evaluate_plan tool and shared skills
live inside planner_with_eval (not the base planner).
"""

import pathlib


def test_evaluate_plan_importable_from_evaluator_package():
    """evaluate_plan must be importable from planner_with_eval.evaluator."""
    from agents.planner_with_eval.evaluator import evaluate_plan

    assert evaluate_plan is not None
    assert callable(evaluate_plan)


def test_base_planner_has_only_shared_skills():
    """Base planner has directing-the-event, gis-spatial-engineering, mapping, and financial modeling skills."""
    base_planner_dir = pathlib.Path(__file__).parent.parent.parent / "planner"
    skills_dir = base_planner_dir / "skills"
    skill_names = sorted(
        d.name for d in skills_dir.iterdir() if d.is_dir() and not d.name.startswith("_") and (d / "SKILL.md").exists()
    )
    assert skill_names == [
        "directing-the-event",
        "gis-spatial-engineering",
        "insecure-financial-modeling",
        "mapping",
        "secure-financial-modeling",
    ]


def test_planner_with_eval_tools_contain_evaluate_plan():
    """planner_with_eval tools must include evaluate_plan and simulator collaboration."""
    from agents.planner_with_eval.adk_tools import get_tools

    tools = get_tools()
    tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]

    # Direct FunctionTools (not part of any skill)
    assert "evaluate_plan" in tool_names
    assert "submit_plan_to_simulator" in tool_names

    # validate_and_emit_a2ui is a top-level FunctionTool (cross-cutting utility)
    assert "validate_and_emit_a2ui" in tool_names
    # Skill tools activate after load_skill, not top-level
    assert "report_marathon_route" not in tool_names
    assert "assess_traffic_impact" not in tool_names
    assert "plan_marathon_route" not in tool_names
    assert "plan_marathon_event" not in tool_names


def test_planner_with_eval_tools_contain_financial_toggle():
    """planner_with_eval must inherit the financial modeling toggle tool."""
    from google.adk.tools.function_tool import FunctionTool
    from agents.planner_with_eval.adk_tools import get_tools

    tools = get_tools()
    func_tools = [t for t in tools if isinstance(t, FunctionTool)]
    func_names = [t.func.__name__ for t in func_tools]
    assert "set_financial_modeling_mode" in func_names


def test_submit_plan_to_simulator_not_in_base_planner_tools():
    """submit_plan_to_simulator must NOT be registered in the base planner."""
    from agents.planner.adk_tools import get_tools as get_base_tools

    tools = get_base_tools()
    tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]
    assert "submit_plan_to_simulator" not in tool_names


def test_planner_with_eval_calls_get_maps_tools():
    """planner_with_eval's get_tools() must call get_maps_tools from the base planner."""
    import inspect

    from agents.planner_with_eval import adk_tools as mod

    source = inspect.getsource(mod.get_tools)
    assert "get_maps_tools" in source, (
        "planner_with_eval.get_tools() must call get_maps_tools() to share Maps MCP tools"
    )
