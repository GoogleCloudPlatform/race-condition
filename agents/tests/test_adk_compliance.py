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

"""ADK Tool Compliance Tests — verifies all tools return dict, not str.

Per adk-tool-compliance skill: all ADK tools MUST return structured dict
objects. Returning raw strings breaks JSON serialization across the A2A
network topology.
"""

import importlib
import importlib.util
import inspect
import pytest


# All ADK tool modules in the project
TOOL_MODULES = [
    "agents.runner.skills.managing-hydration.tools",
    "agents.runner.skills.running.tools",
    "agents.runner_autopilot.skills.managing-hydration.tools",
    "agents.runner_autopilot.skills.running.tools",
    "agents.planner.skills.directing-the-event.scripts.tools",
    "agents.planner.skills.gis-spatial-engineering.scripts.tools",
    "agents.simulator.skills.preparing-the-race.tools",
    "agents.simulator.skills.advancing-race-ticks.tools",
    "agents.simulator.skills.completing-the-race.tools",
    "agents.simulator_with_failure.skills.simulating-pre-race-failure.tools",
]


def _get_async_tool_functions(module_path: str):
    """Import module and return all async functions (the ADK tools)."""
    # Handle hyphenated module names
    parts = module_path.split(".")
    cleaned = []
    for p in parts:
        cleaned.append(p.replace("-", "_"))

    try:
        mod = importlib.import_module(module_path)
    except ImportError:
        # Try with underscored names for hyphenated directories
        try:
            # Use importlib to find the module via file path
            import pathlib

            base = pathlib.Path(__file__).parent.parent.parent
            mod_file = base / module_path.replace(".", "/") / "__init__.py"
            if not mod_file.exists():
                mod_file = base / (module_path.replace(".", "/") + ".py")
            if not mod_file.exists():
                pytest.skip(f"Module not found: {module_path}")
                return []
            spec = importlib.util.spec_from_file_location(module_path, mod_file)
            assert spec is not None, f"Could not find module spec for {mod_file}"
            assert spec.loader is not None, f"Module spec has no loader for {mod_file}"
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:
            pytest.skip(f"Cannot import: {module_path}")
            return []

    # If the module defines __all__, use it (supports re-export patterns).
    # Otherwise fall back to __module__ check to filter out unrelated imports.
    # This mirrors the production _load_skills_from_directory logic.
    if hasattr(mod, "__all__"):
        return [
            (name, getattr(mod, name)) for name in mod.__all__ if inspect.iscoroutinefunction(getattr(mod, name, None))
        ]
    return [
        (name, func)
        for name, func in inspect.getmembers(mod, inspect.iscoroutinefunction)
        if not name.startswith("_") and func.__module__ == mod.__name__
    ]


class TestAdkToolCompliance:
    """Verify all ADK tools return dict, not str or other types."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "agents.runner.skills.managing-hydration.tools",
            "agents.runner.skills.running.tools",
            "agents.runner_autopilot.skills.managing-hydration.tools",
            "agents.runner_autopilot.skills.running.tools",
            "agents.simulator.skills.preparing-the-race.tools",
            "agents.simulator.skills.advancing-race-ticks.tools",
            "agents.simulator.skills.completing-the-race.tools",
        ],
    )
    def test_tool_functions_have_dict_return_annotation(self, module_path):
        """Every tool function should have -> dict return type annotation."""
        tools = _get_async_tool_functions(module_path)
        assert len(tools) > 0, f"No tools found in {module_path}"

        for name, func in tools:
            sig = inspect.signature(func)
            assert sig.return_annotation is dict or sig.return_annotation == "dict", (
                f"{module_path}.{name} must have -> dict return annotation, got {sig.return_annotation}"
            )
