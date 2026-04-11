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

"""Tests for planner_with_memory prompt instructions."""

from agents.planner_with_memory.prompts import MEMORY_SYSTEM_INSTRUCTION, PLANNER_WITH_MEMORY


def _extract_section(heading: str) -> str:
    """Extract a ## section from the prompt by heading, bounded by the next ## or end."""
    start = MEMORY_SYSTEM_INSTRUCTION.index(heading)
    end = MEMORY_SYSTEM_INSTRUCTION.find("\n## ", start + 1)
    return MEMORY_SYSTEM_INSTRUCTION[start:end] if end != -1 else MEMORY_SYSTEM_INSTRUCTION[start:]


class TestMemorySystemInstructionInheritance:
    """Verify MEMORY_SYSTEM_INSTRUCTION inherits from parent prompts."""

    def test_inherits_base_planner_instruction(self):
        """Must contain base planner content (plan_marathon_route tool)."""
        assert "plan_marathon_route" in MEMORY_SYSTEM_INSTRUCTION

    def test_inherits_eval_instruction_simulator(self):
        """Must contain eval-layer content (submit_plan_to_simulator)."""
        assert "submit_plan_to_simulator" in MEMORY_SYSTEM_INSTRUCTION

    def test_inherits_eval_instruction_evaluator(self):
        """Must contain eval-layer content (evaluate_plan)."""
        assert "evaluate_plan" in MEMORY_SYSTEM_INSTRUCTION

    def test_inherits_exactly_once_constraint(self):
        """Must inherit the EXACTLY ONCE constraint from base planner."""
        assert "EXACTLY ONCE" in MEMORY_SYSTEM_INSTRUCTION


class TestMemoryToolReferences:
    """Verify all 5 memory tools are referenced in the prompt."""

    def test_references_store_route(self):
        assert "store_route" in MEMORY_SYSTEM_INSTRUCTION

    def test_references_record_simulation(self):
        assert "record_simulation" in MEMORY_SYSTEM_INSTRUCTION

    def test_references_recall_routes(self):
        assert "recall_routes" in MEMORY_SYSTEM_INSTRUCTION

    def test_references_get_route(self):
        assert "get_route" in MEMORY_SYSTEM_INSTRUCTION

    def test_references_get_best_route(self):
        assert "get_best_route" in MEMORY_SYSTEM_INSTRUCTION


class TestMemorySpecificContent:
    """Verify memory-specific prompt sections and guidance."""

    def test_contains_route_memory_database_section(self):
        """Must have the '# Route Memory Database' section header."""
        assert "# Route Memory Database" in MEMORY_SYSTEM_INSTRUCTION

    def test_contains_workflow_section(self):
        """Must have the '# Workflow' section header (single authoritative workflow)."""
        assert "# Workflow" in MEMORY_SYSTEM_INSTRUCTION

    def test_contains_route_id_guidance(self):
        """Must mention route_id convention."""
        assert "route_id" in MEMORY_SYSTEM_INSTRUCTION

    def test_contains_uuid_guidance(self):
        """Must mention UUID format for route IDs."""
        assert "UUID" in MEMORY_SYSTEM_INSTRUCTION


class TestSeedAndActivationPromptContent:
    """Verify prompt references pre-seeded plans and activate_route."""

    def test_contains_activate_route(self):
        """Must reference the activate_route parameter."""
        assert "activate_route" in MEMORY_SYSTEM_INSTRUCTION

    def test_contains_pre_loaded_or_seed(self):
        """Must reference pre-loaded or seed plans."""
        lower = MEMORY_SYSTEM_INSTRUCTION.lower()
        assert "pre-loaded" in lower or "seed" in lower

    def test_contains_recall_workflow_section(self):
        """Must have a Recall Workflow section."""
        assert "Recall Workflow" in MEMORY_SYSTEM_INSTRUCTION

    def test_contains_execute_by_reference_section(self):
        """Must have an Execute-by-Reference Workflow section."""
        assert "Execute-by-Reference" in MEMORY_SYSTEM_INSTRUCTION

    def test_execute_by_reference_prohibits_report_marathon_route(self):
        """Execute-by-Reference must NOT instruct calling report_marathon_route."""
        section = _extract_section("## Execute-by-Reference Workflow")
        assert "Do NOT call report_marathon_route" in section

    def test_execute_by_reference_has_four_steps(self):
        """Execute-by-Reference workflow must have exactly 4 steps (start_simulation + submit)."""
        import re

        section = _extract_section("## Execute-by-Reference Workflow")
        steps = re.findall(r"^\d+\.", section, re.MULTILINE)
        assert len(steps) == 4, f"Expected 4 steps, found {len(steps)}: {steps}"


class TestButtonInheritance:
    """Verify planner_with_memory inherits Button instructions from planner_with_eval."""

    def test_memory_prompts_inherit_button(self):
        """planner_with_memory inherits Button instructions from planner_with_eval."""
        assert "Button" in MEMORY_SYSTEM_INSTRUCTION
        assert "run_simulation" in MEMORY_SYSTEM_INSTRUCTION

    def test_memory_prompts_inherit_a2ui_action_handler(self):
        """planner_with_memory inherits a2ui_action handler from planner_with_eval."""
        assert "a2ui_action" in MEMORY_SYSTEM_INSTRUCTION


class TestA2UIRouteListInstructions:
    """Verify prompt instructs A2UI card emission after recall_routes."""

    def test_contains_route_list_a2ui_section(self):
        """Must have the A2UI Route List section header."""
        assert "## A2UI Format: Route List" in MEMORY_SYSTEM_INSTRUCTION

    def test_route_list_references_recall_routes(self):
        """Route list A2UI section must reference recall_routes as trigger."""
        assert "recall_routes" in _extract_section("## A2UI Format: Route List")

    def test_route_list_uses_card_component(self):
        """Route list must use a Card component."""
        assert "Card" in _extract_section("## A2UI Format: Route List")

    def test_route_list_has_run_route_action(self):
        """Each route button must use run_route:<route_id> action pattern."""
        assert "run_route:" in _extract_section("## A2UI Format: Route List")

    def test_route_list_shows_score(self):
        """Route list must instruct showing the evaluation score."""
        assert "score" in _extract_section("## A2UI Format: Route List").lower()

    def test_route_list_calls_validate_and_emit(self):
        """Route list section must instruct calling validate_and_emit_a2ui."""
        assert "validate_and_emit_a2ui" in _extract_section("## A2UI Format: Route List")


class TestA2UIRouteDetailInstructions:
    """Verify prompt instructs A2UI card emission for single route detail."""

    def test_contains_route_detail_a2ui_section(self):
        """Must have the A2UI Route Detail section header."""
        assert "## A2UI Format: Route Detail" in MEMORY_SYSTEM_INSTRUCTION

    def test_route_detail_references_get_route(self):
        """Route detail section must reference get_route as trigger."""
        assert "get_route" in _extract_section("## A2UI Format: Route Detail")

    def test_route_detail_references_get_best_route(self):
        """Route detail section must also cover get_best_route."""
        assert "get_best_route" in _extract_section("## A2UI Format: Route Detail")

    def test_route_detail_includes_theme(self):
        """Detail card must instruct showing theme."""
        assert "theme" in _extract_section("## A2UI Format: Route Detail").lower()

    def test_route_detail_includes_waypoints(self):
        """Detail card must instruct showing waypoint count."""
        assert "waypoint" in _extract_section("## A2UI Format: Route Detail").lower()

    def test_route_detail_has_run_route_action(self):
        """Detail card button must use run_route:<route_id> action."""
        assert "run_route:" in _extract_section("## A2UI Format: Route Detail")

    def test_route_detail_calls_validate_and_emit(self):
        """Detail section must instruct calling validate_and_emit_a2ui."""
        assert "validate_and_emit_a2ui" in _extract_section("## A2UI Format: Route Detail")


class TestA2UIRouteActionHandler:
    """Verify prompt handles run_route:<route_id> button actions."""

    def test_contains_route_action_handler_section(self):
        """Must have the route action handler section."""
        assert "## Handling Route A2UI Button Actions" in MEMORY_SYSTEM_INSTRUCTION

    def test_route_action_handler_references_run_route(self):
        """Handler must reference the run_route: action pattern."""
        assert "run_route:" in _extract_section("## Handling Route A2UI Button Actions")

    def test_route_action_handler_activates_route(self):
        """Handler must instruct activate_route=True."""
        assert "activate_route" in _extract_section("## Handling Route A2UI Button Actions")

    def test_route_action_handler_calls_simulator(self):
        """Handler must instruct calling submit_plan_to_simulator."""
        assert "submit_plan_to_simulator" in _extract_section("## Handling Route A2UI Button Actions")

    def test_route_action_handler_records_simulation(self):
        """Handler must instruct calling record_simulation after execution."""
        assert "record_simulation" in _extract_section("## Handling Route A2UI Button Actions")


class TestWorkflowArchitecture:
    """Verify the workflow is a single authoritative list with mandatory post-sim protocol."""

    def test_workflow_has_post_simulation_protocol(self):
        """Post-sim steps (record + store) must follow submit_plan_to_simulator."""
        prompt = MEMORY_SYSTEM_INSTRUCTION
        assert "record_simulation" in prompt
        assert "store_simulation_summary" in prompt
        # Must appear AFTER submit_plan_to_simulator
        sim_idx = prompt.index("submit_plan_to_simulator")
        record_idx = prompt.index("record_simulation")
        store_idx = prompt.index("store_simulation_summary")
        assert record_idx > sim_idx
        assert store_idx > record_idx

    def test_workflow_is_single_authoritative_list(self):
        """Only ONE workflow section -- no stacking."""
        prompt = MEMORY_SYSTEM_INSTRUCTION
        assert prompt.count("# Workflow") == 1


class TestMemoryBuilderArchitecture:
    """Validate PLANNER_WITH_MEMORY builder overrides chain correctly."""

    def test_memory_overrides_workflow_section(self):
        """Memory workflow must replace eval workflow, not stack."""
        from agents.planner_with_eval.prompts import PLANNER_WITH_EVAL

        assert PLANNER_WITH_EVAL.sections["workflow"] != PLANNER_WITH_MEMORY.sections["workflow"]
        assert "# Workflow" == PLANNER_WITH_MEMORY.sections["workflow"].split("\n")[0]

    def test_memory_adds_memory_section(self):
        """Memory adds a 'memory' section not present in eval."""
        from agents.planner_with_eval.prompts import PLANNER_WITH_EVAL

        assert "memory" not in PLANNER_WITH_EVAL.sections
        assert "memory" in PLANNER_WITH_MEMORY.sections

    def test_memory_adds_post_simulation_section(self):
        """Memory adds a 'post_simulation' section not present in eval."""
        from agents.planner_with_eval.prompts import PLANNER_WITH_EVAL

        assert "post_simulation" not in PLANNER_WITH_EVAL.sections
        assert "post_simulation" in PLANNER_WITH_MEMORY.sections

    def test_memory_inherits_simulator_from_eval(self):
        """Memory must inherit the 'simulator' section from eval."""
        assert "simulator" in PLANNER_WITH_MEMORY.sections
        assert "submit_plan_to_simulator" in PLANNER_WITH_MEMORY.sections["simulator"]

    def test_memory_inherits_a2ui_from_eval(self):
        """Memory must inherit the 'a2ui' section from eval."""
        assert "a2ui" in PLANNER_WITH_MEMORY.sections
        assert "validate_and_emit_a2ui" in PLANNER_WITH_MEMORY.sections["a2ui"]

    def test_memory_overrides_execution_section(self):
        """Memory overrides the eval 'execution' section with its own."""
        from agents.planner_with_eval.prompts import PLANNER_WITH_EVAL

        assert "execution" in PLANNER_WITH_EVAL.sections
        assert "execution" in PLANNER_WITH_MEMORY.sections
        assert PLANNER_WITH_MEMORY.sections["execution"] != PLANNER_WITH_EVAL.sections["execution"]

    def test_build_matches_backward_compat_string(self):
        """PLANNER_WITH_MEMORY.build() must equal MEMORY_SYSTEM_INSTRUCTION."""
        assert PLANNER_WITH_MEMORY.build() == MEMORY_SYSTEM_INSTRUCTION


class TestMemoryWorkflowExecutionSplit:
    """Verify memory workflow is split into planning-only and execution sections."""

    def test_workflow_does_not_contain_start_simulation(self):
        """The workflow section must NOT contain start_simulation."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "start_simulation" not in workflow

    def test_workflow_does_not_contain_execute_action(self):
        """The workflow section must NOT contain action='execute'."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert 'action="execute"' not in workflow

    def test_workflow_ends_with_stop_complete(self):
        """The workflow must contain STOP and 'COMPLETE'."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "COMPLETE" in workflow
        assert "STOP" in workflow

    def test_workflow_contains_do_not_restart(self):
        """The workflow STOP must include 'Do NOT restart the workflow'."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "Do NOT restart the workflow" in workflow

    def test_execution_section_exists(self):
        """An 'execution' section must exist."""
        assert "execution" in PLANNER_WITH_MEMORY.sections

    def test_execution_contains_record_simulation(self):
        """Memory execution must include record_simulation step."""
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        assert "record_simulation" in execution

    def test_execution_contains_store_simulation_summary(self):
        """Memory execution must include store_simulation_summary step."""
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        assert "store_simulation_summary" in execution

    def test_execution_contains_submit_execute(self):
        """Execution must contain submit_plan_to_simulator with execute action."""
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        assert "submit_plan_to_simulator" in execution
        assert 'action="execute"' in execution

    def test_workflow_stop_is_terminal(self):
        """STOP/COMPLETE must be on the last line of the workflow section."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        last_line = workflow.rstrip().split("\n")[-1].strip()
        assert "COMPLETE" in last_line


# --- A2UI Simulation Results card tests ---


class TestMemorySimResultsA2UI:
    """Validate the memory planner inherits and extends sim results A2UI."""

    def test_memory_execution_instructs_sim_results_card(self):
        """Memory planner must emit sim results A2UI after execution."""
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        assert "sim_results" in execution
        assert "validate_and_emit_a2ui" in execution

    def test_memory_inherits_sim_results_a2ui(self):
        """Memory planner must inherit the sim results A2UI section from eval."""
        prompt = MEMORY_SYSTEM_INSTRUCTION
        assert "sim_results" in prompt
        assert "SIMULATED" in prompt
        assert "Safety Score" in prompt

    def test_memory_execution_mentions_route_id(self):
        """Memory planner results card should include route_id in metadata."""
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        assert "route_id" in execution

    def test_memory_execution_guides_missing_data(self):
        """Memory execution must explicitly instruct using placeholder for unavailable data."""
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        # Split off the title line to avoid matching em-dash in "User-Triggered —"
        body = "\n".join(execution.strip().split("\n")[1:])
        assert "\u2014" in body, "Execution body (not title) must contain \u2014 as placeholder guidance"

    def test_memory_execution_maps_data_sources_explicitly(self):
        """Memory execution must map card fields to specific tool responses."""
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        assert "simulator response" in execution.lower() or "simulation response" in execution.lower(), (
            "Execution must reference 'simulator response' as a data source"
        )


class TestParallelToolCalling:
    """Verify workflow instructs parallel tool calls where possible."""

    def test_workflow_parallelizes_recall_and_laws(self):
        """recall_past_simulations AND get_local_laws in SAME response."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        # Find the numbered step mentioning recall_past_simulations
        lines = workflow.split("\n")
        recall_lines = [i for i, line in enumerate(lines) if "recall_past_simulations" in line]
        assert recall_lines, "recall_past_simulations must appear in workflow"
        recall_idx = recall_lines[0]
        # Grab the step and continuation lines until next numbered step
        step_lines = [lines[recall_idx]]
        for j in range(recall_idx + 1, len(lines)):
            if lines[j].strip() and lines[j].strip()[0].isdigit():
                break
            step_lines.append(lines[j])
        step_text = "\n".join(step_lines)
        assert "get_local_laws_and_regulations" in step_text, (
            "recall_past_simulations and get_local_laws must be on the same step"
        )

    def test_workflow_parallelizes_store_and_verify(self):
        """store_route AND submit_plan_to_simulator(verify) on same step."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        lines = workflow.split("\n")
        store_lines = [i for i, line in enumerate(lines) if "store_route" in line]
        assert store_lines, "store_route must appear in workflow"
        store_idx = store_lines[0]
        step_lines = [lines[store_idx]]
        for j in range(store_idx + 1, len(lines)):
            if lines[j].strip() and lines[j].strip()[0].isdigit():
                break
            step_lines.append(lines[j])
        step_text = "\n".join(step_lines)
        assert "submit_plan_to_simulator" in step_text, (
            "store_route and submit_plan_to_simulator must be on the same step"
        )

    def test_report_and_traffic_still_parallel(self):
        """report_marathon_route AND assess_traffic_impact remain parallel."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "report_marathon_route" in workflow
        assert "assess_traffic_impact" in workflow
        assert "SAME response" in workflow


class TestParallelExecution:
    """Verify execution phase instructs parallel tool calls."""

    def test_execution_parallelizes_record_and_summary(self):
        """record_simulation AND store_simulation_summary on same step."""
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        lines = execution.split("\n")
        record_lines = [i for i, line in enumerate(lines) if "record_simulation" in line]
        assert record_lines, "record_simulation must appear in execution"
        record_idx = record_lines[0]
        step_lines = [lines[record_idx]]
        for j in range(record_idx + 1, len(lines)):
            if lines[j].strip() and lines[j].strip()[0].isdigit():
                break
            step_lines.append(lines[j])
        step_text = "\n".join(step_lines)
        assert "store_simulation_summary" in step_text, (
            "record_simulation and store_simulation_summary must be on the same step"
        )

    def test_execution_start_and_submit_still_parallel(self):
        """start_simulation AND submit must remain parallel."""
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        assert "start_simulation" in execution
        assert "submit_plan_to_simulator" in execution
        assert "SAME response" in execution
