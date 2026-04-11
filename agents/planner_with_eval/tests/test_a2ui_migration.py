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

"""Tests for planner_with_eval A2UI migration -- generative over template."""

import pathlib
from agents.planner_with_eval.adk_tools import get_tools

AGENT_DIR = pathlib.Path(__file__).parent.parent


def test_a2ui_templates_file_does_not_exist():
    templates = AGENT_DIR / "a2ui_templates.py"
    assert not templates.exists(), f"a2ui_templates.py should be deleted: {templates}"


def test_generate_marathon_dashboard_not_in_tools():
    tools = get_tools()
    tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]
    assert "generate_marathon_dashboard" not in tool_names


def test_validate_and_emit_a2ui_is_top_level():
    """validate_and_emit_a2ui must be a top-level FunctionTool (always available)."""
    tools = get_tools()
    tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]
    assert "validate_and_emit_a2ui" in tool_names


def test_prompt_does_not_reference_generate_marathon_dashboard():
    from agents.planner_with_eval.prompts import EXTENDED_SYSTEM_INSTRUCTION

    assert "generate_marathon_dashboard" not in EXTENDED_SYSTEM_INSTRUCTION


def test_plan_marathon_event_not_top_level():
    """plan_marathon_event must NOT be a top-level tool (accessed via SkillToolset)."""
    tools = get_tools()
    tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]
    assert "plan_marathon_event" not in tool_names


def test_prompt_guides_generative_a2ui():
    from agents.planner_with_eval.prompts import EXTENDED_SYSTEM_INSTRUCTION

    lower = EXTENDED_SYSTEM_INSTRUCTION.lower()
    assert "a2ui" in lower
    assert "validate_and_emit_a2ui" in EXTENDED_SYSTEM_INSTRUCTION
