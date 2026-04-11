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

from agents.planner.prompts import PLANNER, PLANNER_INSTRUCTION


def test_planner_instruction_does_not_mention_simulator():
    """Base planner must NOT contain simulator collaboration content."""
    instruction = PLANNER_INSTRUCTION.lower()
    assert "submit_plan_to_simulator" not in instruction
    assert "simulator" not in instruction
    assert 'action="verify"' not in instruction
    assert 'action="execute"' not in instruction


def test_planner_instruction_does_not_mention_a2ui():
    instruction = PLANNER_INSTRUCTION.lower()
    assert "generate_marathon_dashboard" not in instruction


def test_planner_instruction_mentions_report_marathon_route():
    """The prompt must instruct the agent to call report_marathon_route after route generation."""
    instruction = PLANNER_INSTRUCTION.lower()
    assert "report_marathon_route" in instruction


def test_prompt_specifies_route_generation_step():
    """The system prompt workflow must include route generation via plan_marathon_route."""
    instruction = PLANNER_INSTRUCTION
    assert "plan_marathon_route" in instruction


def test_prompt_mentions_loop_closing():
    """Planner prompt should mention loop-closing route requirement."""
    instruction = PLANNER_INSTRUCTION.lower()
    assert "start and end" in instruction or "start and finish" in instruction, (
        "Prompt should mention that routes start and end at the same location"
    )
    assert "las vegas boulevard" in instruction or "las vegas strip" in instruction, (
        "Prompt should mention the Strip requirement"
    )


def test_base_planner_requests_natural_language():
    """Base planner (Demo 1) should request natural-language output, not raw JSON."""
    instruction = PLANNER_INSTRUCTION
    # Must NOT demand raw JSON output
    assert "EXACT JSON OUTPUT ONLY" not in instruction, "Base planner should not force EXACT JSON OUTPUT"
    # Must request natural-language summary
    assert "natural-language summary" in instruction, "Base planner should request a natural-language summary"
    assert "Do NOT output raw JSON" in instruction, "Base planner should explicitly forbid raw JSON as final response"


def test_planner_with_eval_has_a2ui_instructions():
    """planner_with_eval must still contain A2UI dashboard instructions."""
    from agents.planner_with_eval.prompts import EXTENDED_SYSTEM_INSTRUCTION

    assert "validate_and_emit_a2ui" in EXTENDED_SYSTEM_INSTRUCTION, (
        "planner_with_eval must reference validate_and_emit_a2ui"
    )
    assert "A2UI" in EXTENDED_SYSTEM_INSTRUCTION, "planner_with_eval must reference A2UI"


def test_planner_with_memory_inherits_a2ui_instructions():
    """planner_with_memory inherits from planner_with_eval and must have A2UI instructions."""
    from agents.planner_with_memory.prompts import MEMORY_SYSTEM_INSTRUCTION

    assert "validate_and_emit_a2ui" in MEMORY_SYSTEM_INSTRUCTION, (
        "planner_with_memory must reference validate_and_emit_a2ui"
    )
    assert "A2UI" in MEMORY_SYSTEM_INSTRUCTION, "planner_with_memory must reference A2UI"


def test_prompt_handles_missing_mapping_tools():
    """Workflow must guide the agent when mapping tools are unavailable."""
    instruction = PLANNER_INSTRUCTION
    assert "mapping tools are available" in instruction


def test_prompt_specifies_route_called_exactly_once():
    """Prompt must explicitly say plan_marathon_route is called EXACTLY ONCE."""
    instruction = PLANNER_INSTRUCTION
    assert "EXACTLY ONCE" in instruction, "Prompt must contain 'EXACTLY ONCE' guard for plan_marathon_route"


class TestAssumeAndGoBehavior:
    """The agent must proceed with defaults, not block on optional details."""

    def test_defaults_include_las_vegas(self):
        """Defaults must include Las Vegas as the default city."""
        assert "las vegas" in PLANNER_INSTRUCTION.lower()
        # Must NOT say "clarify if missing" for all fields
        assert "clarify if missing" not in PLANNER_INSTRUCTION.lower()

    def test_defaults_include_nighttime(self):
        """Defaults must include nighttime as the default time of day."""
        assert "nighttime" in PLANNER_INSTRUCTION.lower()

    def test_do_not_ask_directive(self):
        """Prompt must explicitly tell the agent NOT to ask for optional details."""
        lower = PLANNER_INSTRUCTION.lower()
        assert "do not ask" in lower

    def test_sensible_defaults_mentioned(self):
        """Prompt must mention using sensible/reasonable defaults."""
        lower = PLANNER_INSTRUCTION.lower()
        assert "default" in lower

    def test_workflow_step_1_does_not_say_gather(self):
        """Workflow step 1 must not say 'gather reqs' which implies blocking."""
        # Extract the workflow section
        workflow = PLANNER.sections["workflow"]
        first_line = workflow.split("\n")[1]  # line after "# Workflow"
        assert "gather" not in first_line.lower()

    def test_assume_and_go_propagates_to_eval(self):
        """Eval agent must inherit the do-not-ask directive via EVAL_TOOLS."""
        from agents.planner_with_eval.prompts import EXTENDED_SYSTEM_INSTRUCTION

        assert "do not ask" in EXTENDED_SYSTEM_INSTRUCTION.lower()

    def test_las_vegas_default_propagates_to_eval(self):
        """Eval agent must inherit the Las Vegas default via EVAL_TOOLS."""
        from agents.planner_with_eval.prompts import EXTENDED_SYSTEM_INSTRUCTION

        assert "las vegas" in EXTENDED_SYSTEM_INSTRUCTION.lower()

    def test_nighttime_default_propagates_to_eval(self):
        """Eval agent must inherit the nighttime default via EVAL_TOOLS."""
        from agents.planner_with_eval.prompts import EXTENDED_SYSTEM_INSTRUCTION

        assert "nighttime" in EXTENDED_SYSTEM_INSTRUCTION.lower()

    def test_assume_and_go_propagates_to_memory(self):
        """Memory agent must inherit the do-not-ask directive via MEMORY_TOOLS."""
        from agents.planner_with_memory.prompts import MEMORY_SYSTEM_INSTRUCTION

        assert "do not ask" in MEMORY_SYSTEM_INSTRUCTION.lower()

    def test_las_vegas_default_propagates_to_memory(self):
        """Memory agent must inherit the Las Vegas default via MEMORY_TOOLS."""
        from agents.planner_with_memory.prompts import MEMORY_SYSTEM_INSTRUCTION

        assert "las vegas" in MEMORY_SYSTEM_INSTRUCTION.lower()

    def test_nighttime_default_propagates_to_memory(self):
        """Memory agent must inherit the nighttime default via MEMORY_TOOLS."""
        from agents.planner_with_memory.prompts import MEMORY_SYSTEM_INSTRUCTION

        assert "nighttime" in MEMORY_SYSTEM_INSTRUCTION.lower()


# --- PromptBuilder architecture tests ---


class TestPlannerBuilderArchitecture:
    """Validate PLANNER builder section structure."""

    def test_planner_has_required_section_keys(self):
        """Builder must have the 6 canonical section keys."""
        expected = {"role", "rules", "skills", "tools", "workflow", "financial"}
        assert set(PLANNER.sections.keys()) == expected

    def test_build_matches_backward_compat_string(self):
        """PLANNER.build() must equal PLANNER_INSTRUCTION."""
        assert PLANNER.build() == PLANNER_INSTRUCTION

    def test_override_chain_produces_eval_builder(self):
        """Overriding planner produces a valid eval builder with additional keys."""
        from agents.planner_with_eval.prompts import PLANNER_WITH_EVAL

        eval_keys = set(PLANNER_WITH_EVAL.sections.keys())
        assert eval_keys >= {"role", "rules", "tools", "workflow", "simulator", "a2ui"}

    def test_override_chain_produces_memory_builder(self):
        """Overriding eval produces a valid memory builder with additional keys."""
        from agents.planner_with_memory.prompts import PLANNER_WITH_MEMORY

        mem_keys = set(PLANNER_WITH_MEMORY.sections.keys())
        assert mem_keys >= {"role", "rules", "tools", "workflow", "memory", "post_simulation"}


class TestParallelToolCalling:
    """Verify workflow instructs parallel tool calls where possible."""

    def test_workflow_parallelizes_report_weather_landmarks(self):
        """After route generation, report + weather + landmarks in SAME response."""
        workflow = PLANNER.sections["workflow"]
        assert "SAME response" in workflow
        assert "report_marathon_route" in workflow

    def test_workflow_report_after_route_generation(self):
        """report_marathon_route must come after plan_marathon_route."""
        workflow = PLANNER.sections["workflow"]
        route_idx = workflow.index("plan_marathon_route")
        report_idx = workflow.index("report_marathon_route")
        assert report_idx > route_idx


class TestFinancialSkillIsolation:
    """Financial skills must NEVER be loaded during the planning workflow."""

    def test_workflow_does_not_mention_finances(self):
        """The workflow steps must not instruct the agent to plan finances."""
        workflow = PLANNER.sections["workflow"]
        assert "finances" not in workflow.lower(), (
            "Workflow must not mention 'finances' — this triggers financial skill loading"
        )

    def test_skills_section_no_default_mode_label(self):
        """Financial skills must not be labeled 'Default mode' — implies preloading."""
        skills = PLANNER.sections["skills"]
        assert "Default mode" not in skills, (
            "Financial skills must not say 'Default mode' — model interprets this as preload"
        )

    def test_deliverables_no_economics_line(self):
        """Deliverables must not list 'Economics' as a separate line item."""
        tools = PLANNER.sections["tools"]
        # Split into lines and check for a deliverable numbered item containing Economics
        lines = tools.split("\n")
        econ_lines = [
            line
            for line in lines
            if "Economics" in line and line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."))
        ]
        assert not econ_lines, f"Deliverables must not list Economics as a numbered item: {econ_lines}"
