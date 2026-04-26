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

import importlib.util
import logging
import pathlib

from google.adk.code_executors.unsafe_local_code_executor import UnsafeLocalCodeExecutor
from google.adk.tools.function_tool import FunctionTool
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

from agents.planner.adk_tools import set_financial_modeling_mode, get_maps_tools
from agents.planner_with_eval.evaluator.tools import evaluate_plan
from agents.planner_with_eval.tools import start_simulation, submit_plan_to_simulator

logger = logging.getLogger(__name__)


def _load_additional_tools(base_skills_dir: pathlib.Path, shared_skills_dir: pathlib.Path) -> list:
    """Load skill tool functions as callables for SkillToolset additional_tools.

    These tools become available to the LLM only after load_skill activates
    the owning skill. ADK wraps them as FunctionTools automatically and
    injects tool_context at call time.
    """
    tools = []

    # GIS tools
    gis_path = base_skills_dir / "gis-spatial-engineering" / "scripts" / "tools.py"
    if gis_path.exists():
        spec = importlib.util.spec_from_file_location("gis_tools", gis_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for name in ["plan_marathon_route", "report_marathon_route", "assess_traffic_impact"]:
                func = getattr(mod, name, None)
                if func:
                    tools.append(func)

    # directing-the-event tools
    rd_path = base_skills_dir / "directing-the-event" / "scripts" / "tools.py"
    if rd_path.exists():
        spec = importlib.util.spec_from_file_location("rd_tools", rd_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            func = getattr(mod, "plan_marathon_event", None)
            if func:
                tools.append(func)

    return tools


def _load_a2ui_tool(shared_skills_dir: pathlib.Path):
    """Load validate_and_emit_a2ui as a top-level callable.

    This tool is a cross-cutting utility used regardless of which skill is
    active, so it is registered as a direct FunctionTool (always available)
    rather than a SkillToolset additional_tool (gated behind load_skill).
    """
    a2ui_path = shared_skills_dir / "a2ui-rendering" / "tools.py"
    if a2ui_path.exists():
        spec = importlib.util.spec_from_file_location("a2ui_tools", a2ui_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return getattr(mod, "validate_and_emit_a2ui", None)
    return None


def get_tools() -> list:
    """Build the planner-with-eval tool list with lazy-loaded skills.

    Uses SkillToolset with UnsafeLocalCodeExecutor for run_skill_script
    support. Inherits base planner skills and adds evaluation capabilities.
    """
    # Load shared skills from the base planner (gis-spatial-engineering, directing-the-event)
    base_planner_dir = pathlib.Path(__file__).parent.parent / "planner"
    base_skills_dir = base_planner_dir / "skills"

    # Load evaluation skills from own skills/ directory (plan-evaluation)
    local_skills_dir = pathlib.Path(__file__).parent / "skills"

    # Load shared skills from the agents/skills/ directory (e.g. a2ui-rendering)
    shared_skills_dir = pathlib.Path(__file__).parent.parent / "skills"

    skills = []
    for skills_dir in [base_skills_dir, local_skills_dir, shared_skills_dir]:
        if skills_dir.exists():
            skills.extend(
                load_skill_from_dir(d)
                for d in sorted(skills_dir.iterdir())
                if d.is_dir() and not d.name.startswith("_") and (d / "SKILL.md").exists()
            )

    additional_tools = _load_additional_tools(base_skills_dir, shared_skills_dir)

    skill_toolset = SkillToolset(
        skills=skills,
        code_executor=UnsafeLocalCodeExecutor(),
        additional_tools=additional_tools,
    )

    tools = [
        skill_toolset,
        PreloadMemoryTool(),
        FunctionTool(func=evaluate_plan),
    ]

    # Register financial modeling toggle (inherited from base planner)
    tools.append(FunctionTool(func=set_financial_modeling_mode))

    # Register simulator collaboration tools (exclusive to planner_with_eval)
    tools.append(FunctionTool(func=start_simulation))
    tools.append(FunctionTool(func=submit_plan_to_simulator))

    # Register A2UI validation tool (cross-cutting, always available)
    a2ui_func = _load_a2ui_tool(shared_skills_dir)
    if a2ui_func:
        tools.append(FunctionTool(func=a2ui_func))

    # Register Maps MCP tools (shared with base planner)
    tools.extend(get_maps_tools())

    return tools
