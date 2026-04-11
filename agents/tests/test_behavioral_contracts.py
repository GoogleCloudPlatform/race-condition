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

"""Behavioral contract tests for all planner agent variants.

These tests verify that each agent's prompt encodes the correct behavioral
contracts for every user interaction type. They run fast (no LLM calls) and
serve as a CI gate to catch prompt regressions.

Interaction types tested per agent:

  planner:
    - Plans a route (no eval, no simulator, no A2UI)
    - Financial modeling only if explicitly asked
    - No A2UI tools or instructions

  planner_with_eval:
    - Plans a route with evaluation, simulator verify, and A2UI output
    - Runs a simulation (user-triggered execution, separate from planning)
    - Financial modeling only if explicitly asked (turn isolation)

  planner_with_memory:
    - Same as planner_with_eval, plus memory recall and storage
"""

from agents.planner.prompts import PLANNER
from agents.planner_with_eval.prompts import PLANNER_WITH_EVAL
from agents.planner_with_memory.prompts import PLANNER_WITH_MEMORY


# ---------------------------------------------------------------------------
# Base Planner contracts
# ---------------------------------------------------------------------------


class TestPlannerContracts:
    """Base planner: plans routes, no eval/simulator/A2UI."""

    def test_plans_route(self):
        """Workflow must include plan_marathon_route."""
        workflow = PLANNER.sections["workflow"]
        assert "plan_marathon_route" in workflow

    def test_reports_route(self):
        """Workflow must include report_marathon_route."""
        workflow = PLANNER.sections["workflow"]
        assert "report_marathon_route" in workflow

    def test_route_called_exactly_once(self):
        """Workflow must enforce EXACTLY ONCE for plan_marathon_route."""
        prompt = PLANNER.build()
        assert "EXACTLY ONCE" in prompt

    def test_no_a2ui_in_prompt(self):
        """Base planner must NOT reference A2UI dashboard tools."""
        prompt = PLANNER.build()
        assert "validate_and_emit_a2ui" not in prompt

    def test_no_a2ui_section(self):
        """Base planner must NOT have an a2ui section."""
        assert "a2ui" not in PLANNER.sections

    def test_no_simulator_in_prompt(self):
        """Base planner must NOT reference simulator collaboration."""
        prompt = PLANNER.build()
        assert "submit_plan_to_simulator" not in prompt

    def test_no_simulator_section(self):
        """Base planner must NOT have a simulator section."""
        assert "simulator" not in PLANNER.sections

    def test_no_execution_section(self):
        """Base planner must NOT have an execution section."""
        assert "execution" not in PLANNER.sections

    def test_financial_section_exists(self):
        """Financial modeling section must exist (conditional on user asking)."""
        assert "financial" in PLANNER.sections
        assert "set_financial_modeling_mode" in PLANNER.sections["financial"]

    def test_financial_turn_isolation(self):
        """Financial section must enforce turn isolation (no planning tools)."""
        financial = PLANNER.sections["financial"]
        lower = financial.lower()
        assert "do not" in lower or "do not discuss" in lower


# ---------------------------------------------------------------------------
# Planner with Eval contracts
# ---------------------------------------------------------------------------


class TestEvalContracts:
    """planner_with_eval: plans with evaluation, simulator verify, A2UI."""

    # --- Route planning interaction ---

    def test_plans_route_with_evaluation(self):
        """Workflow must include evaluate_plan."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        assert "evaluate_plan" in workflow

    def test_verifies_with_simulator(self):
        """Workflow must include submit_plan_to_simulator with verify action."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        assert "submit_plan_to_simulator" in workflow
        assert 'action="verify"' in workflow

    def test_emits_a2ui_dashboard(self):
        """Workflow must include validate_and_emit_a2ui for A2UI output."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        assert "validate_and_emit_a2ui" in workflow

    def test_a2ui_section_exists(self):
        """A2UI section must exist with format reference."""
        assert "a2ui" in PLANNER_WITH_EVAL.sections
        assert "surfaceUpdate" in PLANNER_WITH_EVAL.sections["a2ui"]

    def test_a2ui_has_button(self):
        """A2UI section must include Button with run_simulation action."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        assert "Button" in a2ui
        assert "run_simulation" in a2ui

    # --- STOP after planning ---

    def test_workflow_ends_with_stop(self):
        """Workflow must end with STOP and COMPLETE."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        assert "STOP" in workflow
        assert "COMPLETE" in workflow

    def test_workflow_stop_is_terminal(self):
        """STOP/COMPLETE must be on the last line of the workflow."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        last_line = workflow.rstrip().split("\n")[-1].strip()
        assert "COMPLETE" in last_line

    def test_workflow_has_no_execution_steps(self):
        """Workflow must NOT contain execution steps (start_simulation, execute)."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        assert "start_simulation" not in workflow
        assert 'action="execute"' not in workflow

    # --- Simulation execution interaction (user-triggered) ---

    def test_execution_section_exists(self):
        """Execution must be a separate section from workflow."""
        assert "execution" in PLANNER_WITH_EVAL.sections

    def test_execution_gated_on_user_trigger(self):
        """Execution section must require explicit user action."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        lower = execution.lower()
        assert "user explicitly" in lower or "only applies when" in lower

    def test_execution_has_start_simulation(self):
        """Execution must include start_simulation."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        assert "start_simulation" in execution

    def test_execution_has_submit_execute(self):
        """Execution must include submit_plan_to_simulator with execute action."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        assert "submit_plan_to_simulator" in execution
        assert 'action="execute"' in execution

    # --- Financial modeling interaction (isolated) ---

    def test_financial_section_inherited(self):
        """Financial section must be inherited from base planner."""
        assert "financial" in PLANNER_WITH_EVAL.sections

    def test_financial_turn_isolation(self):
        """Financial queries must not invoke planning or simulation tools."""
        financial = PLANNER_WITH_EVAL.sections["financial"]
        lower = financial.lower()
        assert "planning" in lower or "do not" in lower

    # --- Simulator section ---

    def test_simulator_section_exists(self):
        """Simulator section must exist with verify/execute documentation."""
        assert "simulator" in PLANNER_WITH_EVAL.sections
        sim = PLANNER_WITH_EVAL.sections["simulator"]
        assert 'action="verify"' in sim
        assert 'action="execute"' in sim

    def test_simulator_prohibits_auto_execute(self):
        """Simulator section must prohibit automatic execution."""
        sim = PLANNER_WITH_EVAL.sections["simulator"]
        lower = sim.lower()
        assert "never call execute automatically" in lower


# ---------------------------------------------------------------------------
# Planner with Memory contracts
# ---------------------------------------------------------------------------


class TestMemoryContracts:
    """planner_with_memory: eval + memory recall/storage."""

    # --- Inherits all eval contracts ---

    def test_inherits_evaluation(self):
        """Workflow must include evaluate_plan (inherited from eval)."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "evaluate_plan" in workflow

    def test_inherits_simulator_verify(self):
        """Workflow must include submit_plan_to_simulator verify (inherited)."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "submit_plan_to_simulator" in workflow

    def test_inherits_a2ui(self):
        """A2UI section must be inherited from eval."""
        assert "a2ui" in PLANNER_WITH_MEMORY.sections
        assert "validate_and_emit_a2ui" in PLANNER_WITH_MEMORY.sections["a2ui"]

    def test_inherits_stop(self):
        """Workflow must end with STOP/COMPLETE (inherited pattern)."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "STOP" in workflow
        assert "COMPLETE" in workflow

    def test_inherits_execution_separation(self):
        """Execution must be a separate section (inherited pattern)."""
        assert "execution" in PLANNER_WITH_MEMORY.sections
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "start_simulation" not in workflow

    # --- Memory-specific: recall ---

    def test_workflow_has_recall_past_simulations(self):
        """Workflow must include recall_past_simulations for memory recall."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "recall_past_simulations" in workflow

    def test_workflow_has_compliance_check(self):
        """Workflow must include get_local_and_traffic_rules."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "get_local_and_traffic_rules" in workflow

    # --- Memory-specific: storage ---

    def test_execution_flow_has_record_simulation(self):
        """Execution flow must include record_simulation for memory storage.

        The execution section references the Simulation Execution Protocol
        (in the memory section), which contains the actual tool calls.
        """
        prompt = PLANNER_WITH_MEMORY.build()
        assert "record_simulation" in prompt

    def test_execution_flow_has_store_simulation_summary(self):
        """Execution flow must include store_simulation_summary for future recall.

        The execution section references the Simulation Execution Protocol
        (in the memory section), which contains the actual tool calls.
        """
        prompt = PLANNER_WITH_MEMORY.build()
        assert "store_simulation_summary" in prompt

    # --- Memory section ---

    def test_memory_section_exists(self):
        """Memory section must exist with route database docs."""
        assert "memory" in PLANNER_WITH_MEMORY.sections
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "store_route" in memory
        assert "recall_routes" in memory
        assert "get_route" in memory
