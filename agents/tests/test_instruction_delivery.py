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

"""Regression guard: all planner agents must use static_instruction only.

When both static_instruction and instruction are set on an LlmAgent, the ADK
delivers the dynamic instruction as user-content (role='user') rather than
system-instruction. This fundamentally weakens the model's adherence to the
workflow, tool ordering, and STOP directives.

These tests ensure no planner agent uses the static/dynamic split pattern.
"""

import pytest


@pytest.mark.parametrize(
    "agent_module,agent_attr",
    [
        ("agents.planner.agent", "root_agent"),
        ("agents.planner_with_eval.agent", "root_agent"),
        ("agents.planner_with_memory.agent", "root_agent"),
    ],
    ids=["planner", "planner_with_eval", "planner_with_memory"],
)
class TestInstructionDelivery:
    """All planner agents must deliver instructions via static_instruction only."""

    def test_no_dynamic_instruction(self, agent_module, agent_attr):
        """instruction must not be set -- dynamic instructions go to user-content."""
        import importlib

        mod = importlib.import_module(agent_module)
        agent = getattr(mod, agent_attr)
        # ADK defaults instruction to '' when not provided.
        # A non-empty instruction alongside static_instruction causes the ADK
        # to deliver it as user-content instead of system-instruction.
        assert not agent.instruction or agent.instruction == "", (
            f"{agent.name}: instruction is set alongside static_instruction. "
            "The ADK will deliver it as user-content, not system-instruction. "
            "Use static_instruction=BUILDER.build() instead."
        )

    def test_static_instruction_is_set(self, agent_module, agent_attr):
        """static_instruction must be a non-empty string."""
        import importlib

        mod = importlib.import_module(agent_module)
        agent = getattr(mod, agent_attr)
        assert agent.static_instruction, f"{agent.name}: static_instruction is empty or None."
        assert isinstance(agent.static_instruction, str), (
            f"{agent.name}: static_instruction must be a string, got {type(agent.static_instruction)}"
        )

    def test_static_instruction_contains_workflow(self, agent_module, agent_attr):
        """Critical content (workflow) must be present in static_instruction."""
        import importlib

        mod = importlib.import_module(agent_module)
        agent = getattr(mod, agent_attr)
        assert "# Workflow" in agent.static_instruction or "# Extended Workflow" in agent.static_instruction, (
            f"{agent.name}: static_instruction is missing the workflow section. "
            "This means the model has no workflow to follow."
        )
