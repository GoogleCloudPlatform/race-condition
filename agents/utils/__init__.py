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

"""Shared utilities for ADK agent skill/tool discovery and loading."""

import pathlib
import importlib.util
import inspect
from typing import Dict, List, Callable, Tuple
from google.adk.skills import Skill, load_skill_from_dir

# Resolve the shared skills directory relative to this package.
# __file__  = agents/utils/__init__.py
# .parent   = agents/utils/
# .parent   = agents/
# / "skills" = agents/skills/
_SHARED_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"


def _load_skills_from_directory(
    skills_root: pathlib.Path,
) -> Tuple[List[Skill], List[Callable]]:
    """Scan a single directory for ADK skills and their tools.

    Each subdirectory in *skills_root* is treated as a skill if it contains
    a ``SKILL.md`` file.  If the subdirectory also contains ``tools.py``,
    all public functions defined in that module are collected as tools.

    Returns:
        A tuple of ``(skills, tools)`` discovered in *skills_root*.
    """
    skills: List[Skill] = []
    tools: List[Callable] = []

    if not skills_root.exists():
        return skills, tools

    for skill_path in skills_root.iterdir():
        if not skill_path.is_dir():
            continue

        skill_md = skill_path / "SKILL.md"
        if skill_md.exists():
            # Load the skill using native ADK 1.26.0 loader
            skill = load_skill_from_dir(skill_path)
            skills.append(skill)

            # Load tools from tools.py if it exists
            tools_py = skill_path / "tools.py"
            if tools_py.exists():
                skill_id = skill_path.name.replace("-", "_")
                spec = importlib.util.spec_from_file_location(f"{skill_id}.tools", tools_py)
                assert spec is not None, f"Could not find module spec for {tools_py}"
                assert spec.loader is not None, f"Module spec has no loader for {tools_py}"
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Extract tool functions.  If the module defines __all__,
                # use it verbatim (enables re-export patterns where the
                # implementation lives in a shared module).  Otherwise
                # fall back to the __module__ heuristic which only picks
                # up functions defined directly in this file.
                if hasattr(module, "__all__"):
                    for name in module.__all__:
                        obj = getattr(module, name, None)
                        if obj is not None and callable(obj):
                            tools.append(obj)
                else:
                    for name, obj in inspect.getmembers(module):
                        if inspect.isfunction(obj) and not name.startswith("_"):
                            if obj.__module__ == f"{skill_id}.tools":
                                tools.append(obj)

    return skills, tools


def load_agent_skills(agent_dir: str) -> Tuple[List[Skill], List[Callable]]:
    """Discovers and loads skills and tools for an agent.

    Skills are loaded from two locations and merged:

    1. **Shared** skills in ``agents/skills/`` (the package-level directory).
    2. **Local** skills in ``{agent_dir}/skills/``.

    When a local skill has the same name as a shared skill, the local skill
    takes precedence.  Tools from both directories are always combined.
    """
    # 1. Load shared skills
    shared_skills, shared_tools = _load_skills_from_directory(_SHARED_SKILLS_DIR)

    # 2. Load local (agent-specific) skills
    local_root = pathlib.Path(agent_dir) / "skills"
    local_skills, local_tools = _load_skills_from_directory(local_root)

    # 3. Merge skills by name: shared first, local overrides on collision
    merged: Dict[str, Skill] = {}
    for skill in shared_skills:
        merged[skill.name] = skill
    for skill in local_skills:
        merged[skill.name] = skill  # local wins on name collision

    # 4. Combine all tools from both directories
    all_tools = shared_tools + local_tools

    return list(merged.values()), all_tools
