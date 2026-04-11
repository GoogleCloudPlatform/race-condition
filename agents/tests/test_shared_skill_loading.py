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

"""Tests for shared skill loading from agents/skills/ directory."""

import pathlib

from agents.utils import load_agent_skills


def test_shared_skills_directory_exists():
    """The agents/skills/ directory must exist for shared skills."""
    shared_dir = pathlib.Path(__file__).parent.parent / "skills"
    assert shared_dir.is_dir(), f"Shared skills directory not found: {shared_dir}"


def test_load_agent_skills_discovers_local_skills():
    """load_agent_skills should discover skills from an agent's own skills/ directory."""
    simulator_dir = str(pathlib.Path(__file__).parent.parent / "simulator")
    skills, tools = load_agent_skills(simulator_dir)
    skill_names = [s.name for s in skills]
    assert "race-tick" in skill_names, f"Local skill 'race-tick' not found. Got: {skill_names}"


def test_shared_skills_merge_with_local_skills():
    """When both shared and local skills exist, both should be returned."""
    simulator_dir = str(pathlib.Path(__file__).parent.parent / "simulator")
    skills, tools = load_agent_skills(simulator_dir)
    assert len(skills) >= 1, f"Expected at least 1 skill, got {len(skills)}: {[s.name for s in skills]}"


def test_local_skills_take_precedence_over_shared():
    """If a local skill has the same name as a shared skill, local wins."""
    simulator_dir = str(pathlib.Path(__file__).parent.parent / "simulator")
    skills, _ = load_agent_skills(simulator_dir)
    skill_names = [s.name for s in skills]
    assert len(skill_names) == len(set(skill_names)), f"Duplicate skill names found: {skill_names}"


def test_a2ui_rendering_skill_discoverable():
    """The a2ui-rendering shared skill should be discoverable by any agent."""
    simulator_dir = str(pathlib.Path(__file__).parent.parent / "simulator")
    skills, tools = load_agent_skills(simulator_dir)
    skill_names = [s.name for s in skills]
    assert "a2ui-rendering" in skill_names, f"Shared skill 'a2ui-rendering' not found. Got: {skill_names}"


def test_a2ui_rendering_skill_provides_validation_tool():
    """The a2ui-rendering skill should provide validate_and_emit_a2ui."""
    simulator_dir = str(pathlib.Path(__file__).parent.parent / "simulator")
    _, tools = load_agent_skills(simulator_dir)
    tool_names = [t.__name__ for t in tools]
    assert "validate_and_emit_a2ui" in tool_names, f"Tool 'validate_and_emit_a2ui' not found. Got: {tool_names}"


def test_deploy_script_includes_shared_skills():
    """scripts/deploy/deploy.py must include agents/skills in extra_packages for
    Agent Engine deployment."""
    deploy_path = pathlib.Path(__file__).parent.parent.parent / "scripts" / "deploy" / "deploy.py"
    content = deploy_path.read_text()
    assert '"agents/skills"' in content or "'agents/skills'" in content, (
        "scripts/deploy/deploy.py must include 'agents/skills' in extra_packages for Agent Engine deployment"
    )
