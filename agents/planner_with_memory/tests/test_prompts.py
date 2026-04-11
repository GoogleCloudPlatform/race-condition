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

    def test_execute_by_reference_has_three_steps(self):
        """Execute-by-Reference workflow must have 3 steps (get_route, protocol ref, skip note)."""
        import re

        section = _extract_section("## Execute-by-Reference Workflow")
        steps = re.findall(r"^\d+\.", section, re.MULTILINE)
        assert len(steps) == 3, f"Expected 3 steps, found {len(steps)}: {steps}"

    def test_execute_by_reference_references_protocol(self):
        """Execute-by-Reference workflow must reference Simulation Execution Protocol."""
        section = _extract_section("## Execute-by-Reference Workflow")
        assert "Simulation Execution Protocol" in section

    def test_simulation_execution_protocol_has_stop(self):
        """Simulation Execution Protocol must include STOP instruction."""
        section = _extract_section("## Simulation Execution Protocol")
        assert "STOP" in section

    def test_simulation_execution_protocol_emits_a2ui(self):
        """Simulation Execution Protocol must emit sim results A2UI card."""
        section = _extract_section("## Simulation Execution Protocol")
        assert "validate_and_emit_a2ui" in section
        assert "sim_results" in section


class TestButtonInheritance:
    """Verify planner_with_memory inherits Button instructions from planner_with_eval."""

    def test_memory_prompts_inherit_button(self):
        """planner_with_memory inherits Button instructions from planner_with_eval."""
        assert "Button" in MEMORY_SYSTEM_INSTRUCTION
        assert "run_simulation" in MEMORY_SYSTEM_INSTRUCTION

    def test_memory_prompts_inherit_a2ui_action_handler(self):
        """planner_with_memory inherits a2ui_action handler from planner_with_eval."""
        assert "a2ui_action" in MEMORY_SYSTEM_INSTRUCTION


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

    def test_route_action_handler_references_protocol(self):
        """Handler must reference Simulation Execution Protocol (not inline tools)."""
        section = _extract_section("## Handling Route A2UI Button Actions")
        assert "Simulation Execution Protocol" in section

    def test_route_action_protocol_covers_simulator_and_recording(self):
        """Simulation Execution Protocol must cover submit, record, and A2UI."""
        protocol = _extract_section("## Simulation Execution Protocol")
        assert "submit_plan_to_simulator" in protocol
        assert "record_simulation" in protocol
        assert "validate_and_emit_a2ui" in protocol
        assert "sim_results" in protocol


class TestParallelToolCalling:
    """Verify workflow instructs parallel tool calls where possible."""

    def test_workflow_parallelizes_recall_and_laws(self):
        """recall_past_simulations AND get_local_and_traffic_rules in SAME response."""
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
        assert "get_local_and_traffic_rules" in step_text, "Workflow Step 2 must call get_local_and_traffic_rules"

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
    """Verify the Simulation Execution Protocol instructs parallel tool calls."""

    def test_protocol_parallelizes_record_and_summary(self):
        """record_simulation AND store_simulation_summary on same step in protocol."""
        protocol = _extract_section("## Simulation Execution Protocol")
        lines = protocol.split("\n")
        record_lines = [i for i, line in enumerate(lines) if "record_simulation" in line]
        assert record_lines, "record_simulation must appear in protocol"
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

    def test_protocol_start_and_submit_parallel(self):
        """start_simulation AND submit must be parallel in protocol."""
        protocol = _extract_section("## Simulation Execution Protocol")
        assert "start_simulation" in protocol
        assert "submit_plan_to_simulator" in protocol
        assert "SAME response" in protocol


class TestExecutionStopInstruction:
    """Verify Simulation Execution Protocol has terminal STOP instruction."""

    def test_protocol_contains_stop(self):
        """Protocol must contain STOP directive after A2UI emission."""
        protocol = _extract_section("## Simulation Execution Protocol")
        assert "STOP" in protocol

    def test_protocol_contains_do_not_run_again(self):
        """Protocol must prohibit re-running simulation automatically."""
        protocol = _extract_section("## Simulation Execution Protocol")
        assert "Do NOT run another simulation" in protocol

    def test_protocol_contains_do_not_restart(self):
        """Protocol must prohibit restarting the workflow."""
        protocol = _extract_section("## Simulation Execution Protocol")
        assert "Do NOT restart the workflow" in protocol

    def test_protocol_stop_is_terminal(self):
        """STOP must appear after the A2UI emission step."""
        protocol = _extract_section("## Simulation Execution Protocol")
        stop_idx = protocol.index("STOP")
        a2ui_idx = protocol.index("validate_and_emit_a2ui")
        assert stop_idx > a2ui_idx


class TestPromptConsolidation:
    """Verify submit_plan_to_simulator(execute) is deduplicated.

    The prompt previously had 4 separate places instructing the LLM to call
    submit_plan_to_simulator(action="execute"), causing the model to re-trigger
    after a simulation completed. After consolidation, the canonical execute
    instruction should appear in exactly one place (the Simulation Execution
    Protocol), and the individual workflows should reference it.
    """

    def test_execute_action_appears_once_in_prompt(self):
        """submit_plan_to_simulator(action="execute") must appear exactly once."""
        import re

        # Match the literal tool call with execute action
        matches = re.findall(
            r'submit_plan_to_simulator\(action="execute"\)',
            MEMORY_SYSTEM_INSTRUCTION,
        )
        assert len(matches) == 1, (
            f'Expected exactly 1 occurrence of submit_plan_to_simulator(action="execute"), found {len(matches)}'
        )

    def test_execution_protocol_section_exists(self):
        """A Simulation Execution Protocol section must exist."""
        assert "Simulation Execution Protocol" in MEMORY_SYSTEM_INSTRUCTION

    def test_execution_references_protocol(self):
        """MEMORY_EXECUTION must reference the Simulation Execution Protocol."""
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        assert "Simulation Execution Protocol" in execution

    def test_execute_by_reference_references_protocol(self):
        """Execute-by-Reference must reference the Simulation Execution Protocol."""
        section = _extract_section("## Execute-by-Reference Workflow")
        assert "Simulation Execution Protocol" in section

    def test_button_handler_references_protocol(self):
        """Button action handler must reference the Simulation Execution Protocol."""
        section = _extract_section("## Handling Route A2UI Button Actions")
        assert "Simulation Execution Protocol" in section

    def test_terminal_rules_before_workflow(self):
        """Terminal Rules must appear before the Workflow section."""
        prompt = MEMORY_SYSTEM_INSTRUCTION
        terminal_idx = prompt.index("MUST NEVER re-execute")
        workflow_idx = prompt.index("# Workflow")
        assert terminal_idx < workflow_idx, "Terminal rules must appear before the Workflow section"


class TestWorkflowTriage:
    """Verify workflow has a triage preamble for recall vs. planning."""

    def test_workflow_has_triage_step(self):
        """Workflow must classify user intent before starting planning."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "Execute-by-Reference" in workflow
        # The triage must appear BEFORE the first numbered planning step
        triage_idx = workflow.index("Execute-by-Reference")
        first_recall = workflow.index("recall_past_simulations")
        assert triage_idx < first_recall, "Triage must appear before recall step"

    def test_workflow_triage_mentions_recall_intent(self):
        """Triage must mention explicit recall/run/reuse intent."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        lower = workflow.lower()
        assert "recall" in lower or "reuse" in lower or "run" in lower


class TestExecuteByReferenceSequencing:
    """Verify Execute-by-Reference has correct tool call sequencing."""

    def test_get_route_before_protocol(self):
        """get_route must complete before the Simulation Execution Protocol."""
        section = _extract_section("## Execute-by-Reference Workflow")
        get_route_idx = section.index("get_route")
        protocol_idx = section.index("Simulation Execution Protocol")
        assert get_route_idx < protocol_idx

    def test_sequencing_is_explicit(self):
        """Must explicitly state get_route returns before protocol."""
        section = _extract_section("## Execute-by-Reference Workflow")
        assert "activate_route" in section
        lines = section.split("\n")
        step1_lines = [line for line in lines if "1." in line]
        step2_lines = [line for line in lines if "2." in line]
        assert any("get_route" in line for line in step1_lines)
        assert any("Simulation Execution Protocol" in line for line in step2_lines)
