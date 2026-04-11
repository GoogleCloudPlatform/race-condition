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

import re

from agents.planner_with_eval.prompts import PLANNER_WITH_EVAL


def test_planner_instruction_contains_new_tools():
    """Verify that the planner's system instruction mentions the mandatory 2-step simulator flow."""
    instruction = PLANNER_WITH_EVAL.build().lower()

    # Check for simulator collaboration tool
    assert "submit_plan_to_simulator" in instruction

    # Check for verify action in workflow (two distinct actions: verify and execute)
    assert 'action="verify"' in instruction
    assert 'action="execute"' in instruction
    # Check that auto-execution is explicitly prohibited
    assert "never call execute automatically" in instruction


def test_planner_instruction_mentions_a2ui():
    """Verify that the planner_with_eval instruction mentions generative A2UI."""
    instruction = PLANNER_WITH_EVAL.build()
    assert "a2ui" in instruction.lower()
    assert "validate_and_emit_a2ui" in instruction


def test_planner_with_eval_instruction_mentions_report_marathon_route():
    """The prompt must instruct the agent to call report_marathon_route after route generation."""
    assert "report_marathon_route" in PLANNER_WITH_EVAL.build().lower()


def test_planner_with_eval_inherits_route_once_constraint():
    """The extended prompt inherits the base planner's EXACTLY ONCE constraint."""
    assert "EXACTLY ONCE" in PLANNER_WITH_EVAL.build()


def test_planner_with_eval_mentions_single_pass_evaluator():
    """The extended prompt must clarify that SINGLE PASS appears in the evaluator section."""
    instruction = PLANNER_WITH_EVAL.build()
    assert "SINGLE PASS" in instruction
    # Verify SINGLE PASS appears in the Evaluator Guidance section, not elsewhere
    eval_section = instruction.split("Evaluator Guidance")[1].split("# ")[0]
    assert "SINGLE PASS" in eval_section


def test_planner_with_eval_has_extended_workflow():
    """The extended prompt must override the base workflow to include evaluator and simulator steps."""
    instruction = PLANNER_WITH_EVAL.build()
    # The extended instruction must have an explicit workflow section
    assert "# Extended Workflow" in instruction
    # Extract the extended workflow section (everything after "# Extended Workflow")
    extended_workflow = instruction.split("# Extended Workflow")[1]
    # Must include simulator verification as a numbered step
    assert "submit_plan_to_simulator" in extended_workflow
    # Must include evaluate_plan tool as a numbered step
    assert "evaluate_plan" in extended_workflow


def test_prompts_include_button_instruction():
    """The A2UI dashboard instructions must include Button with run_simulation action."""
    instruction = PLANNER_WITH_EVAL.build()
    assert "Button" in instruction
    assert "run_simulation" in instruction
    assert "Run Simulation" in instruction


def test_prompts_include_a2ui_action_handler():
    """The prompts must include instructions for handling A2UI actions."""
    assert "a2ui_action" in PLANNER_WITH_EVAL.build()


def test_planner_prompt_includes_quality_priorities():
    """Base planner prompt must include all 6 non-deterministic evaluation pillars."""
    from agents.planner.prompts import PLANNER

    instruction = PLANNER.build()
    assert "Plan Quality Priorities" in instruction
    assert "Safety" in instruction
    assert "Community" in instruction
    assert "Intent Alignment" in instruction
    assert "Logistics" in instruction
    assert "Participant Experience" in instruction
    assert "Financial" in instruction


def test_eval_tools_lists_seven_scores():
    """EVAL_TOOLS must describe all 7 evaluation scores returned by evaluate_plan."""
    from agents.planner_with_eval.prompts import EVAL_TOOLS

    assert "safety_compliance" in EVAL_TOOLS
    assert "logistics_completeness" in EVAL_TOOLS
    assert "participant_experience" in EVAL_TOOLS
    assert "community_impact" in EVAL_TOOLS
    assert "financial_viability" in EVAL_TOOLS
    assert "intent_alignment" in EVAL_TOOLS
    assert "distance_compliance" in EVAL_TOOLS


# --- PromptBuilder architecture tests ---


class TestEvalBuilderArchitecture:
    """Validate PLANNER_WITH_EVAL builder overrides parent correctly."""

    def test_eval_overrides_workflow_section(self):
        """Eval workflow must replace parent workflow, not stack."""
        from agents.planner.prompts import PLANNER

        assert PLANNER.sections["workflow"] != PLANNER_WITH_EVAL.sections["workflow"]
        assert "Extended Workflow" in PLANNER_WITH_EVAL.sections["workflow"]

    def test_eval_adds_simulator_section(self):
        """Eval adds a 'simulator' section not present in parent."""
        from agents.planner.prompts import PLANNER

        assert "simulator" not in PLANNER.sections
        assert "simulator" in PLANNER_WITH_EVAL.sections

    def test_eval_adds_a2ui_section(self):
        """Eval adds an 'a2ui' section not present in parent."""
        from agents.planner.prompts import PLANNER

        assert "a2ui" not in PLANNER.sections
        assert "a2ui" in PLANNER_WITH_EVAL.sections

    def test_eval_adds_execution_section(self):
        """Eval adds an 'execution' section not present in parent."""
        from agents.planner.prompts import PLANNER

        assert "execution" not in PLANNER.sections
        assert "execution" in PLANNER_WITH_EVAL.sections


class TestWorkflowExecutionSplit:
    """Verify workflow is split into planning-only (workflow) and execution sections.

    The workflow must end with a STOP directive and contain NO execution steps.
    Execution steps live in a separate 'execution' section to eliminate LLM
    completion pressure that causes the agent to skip past STOP.
    """

    def test_workflow_does_not_contain_start_simulation(self):
        """The workflow section must NOT contain start_simulation (execution-only)."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        assert "start_simulation" not in workflow

    def test_workflow_does_not_contain_execute_action(self):
        """The workflow section must NOT contain action='execute' steps."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        assert 'action="execute"' not in workflow

    def test_workflow_ends_with_stop_complete(self):
        """The workflow section must contain STOP and 'COMPLETE'."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        assert "COMPLETE" in workflow
        assert "STOP" in workflow

    def test_workflow_contains_do_not_restart(self):
        """The workflow STOP must include 'Do NOT restart the workflow'."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        assert "Do NOT restart the workflow" in workflow

    def test_execution_section_exists(self):
        """An 'execution' section must exist in the builder."""
        assert "execution" in PLANNER_WITH_EVAL.sections

    def test_execution_contains_start_simulation(self):
        """The execution section must contain start_simulation."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        assert "start_simulation" in execution

    def test_execution_contains_submit_execute(self):
        """The execution section must contain submit_plan_to_simulator with execute."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        assert "submit_plan_to_simulator" in execution
        assert 'action="execute"' in execution

    def test_workflow_stop_is_terminal(self):
        """STOP/COMPLETE must be on the last line of the workflow section."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        last_line = workflow.rstrip().split("\n")[-1].strip()
        assert "COMPLETE" in last_line

    def test_full_prompt_still_contains_both_actions(self):
        """The full built prompt must still contain both verify and execute actions."""
        prompt = PLANNER_WITH_EVAL.build()
        assert 'action="verify"' in prompt
        assert 'action="execute"' in prompt


# --- A2UI Simulation Results card tests ---


def test_a2ui_section_contains_sim_results_format():
    """The A2UI section must include the Simulation Results format reference."""
    a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
    assert "sim_results" in a2ui
    assert "SIMULATED" in a2ui
    assert "Safety Score" in a2ui
    assert "Runner Experience" in a2ui
    assert "City Disruption" in a2ui


def test_a2ui_sim_results_has_rerun_button():
    """The sim results A2UI must include a Re-run button with run_simulation action."""
    a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
    assert "Re-run Simulation" in a2ui


class TestSimResultsA2UISection:
    """Validate the A2UI simulation results one-shot example."""

    @staticmethod
    def _example_json_block() -> str:
        """Return only the first ```json ... ``` block of the sim_results section.

        The constraint section after the example legitimately mentions
        forbidden labels in MUST NOT prose; only the example components are
        the source-of-truth output the LLM mimics.
        """
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        section = a2ui.split("# A2UI Format: Simulation Results")[1]
        start = section.index("```json") + len("```json")
        end = section.index("```", start)
        return section[start:end]

    def test_sim_results_has_surface_update(self):
        """Must include a surfaceUpdate example with sim_results surfaceId."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        assert '"surfaceId": "sim_results"' in a2ui

    def test_sim_results_has_begin_rendering(self):
        """Must include a beginRendering example for sim_results."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        # The format section must have its own beginRendering
        sim_results_section = a2ui.split("# A2UI Format: Simulation Results")[1]
        assert "beginRendering" in sim_results_section
        assert "sim_results" in sim_results_section

    def test_sim_results_has_score_header(self):
        """The example must show a score number with h1 usageHint."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        assert '"usageHint": "h1"' in a2ui

    def test_sim_results_has_detail_rows(self):
        """Must include metric detail rows (Total distance, Participants)."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        assert "Total distance" in a2ui
        assert "Participants" in a2ui

    def test_sim_results_omits_peak_hour_volume(self):
        """Peak Hour Volume row must not be in the example components."""
        block = self._example_json_block()
        assert "Peak Hour Volume" not in block

    def test_sim_results_omits_spectators(self):
        """Spectators row must not be in the example components."""
        block = self._example_json_block()
        assert "Spectators" not in block
        assert '"id": "spec-' not in block

    def test_sim_results_omits_duplicate_score_id_bar(self):
        """The bar row duplicates score (in score-col h1) and sim_id (in tag-row)."""
        block = self._example_json_block()
        assert '"id": "bar-left"' not in block
        assert '"id": "bar-right"' not in block
        assert '"id": "bar"' not in block
        assert "SCORE 82%" not in block

    def test_sim_results_participants_uses_expected_simulated(self):
        """Participants row must use 'expected/simulated' semantics in the example."""
        block = self._example_json_block()
        assert "Participants (expected/simulated)" in block
        assert "Participants (expected/attendance)" not in block

    def test_sim_results_score_examples_are_integers(self):
        """Example Safety/Runner/City score values must be 0-100 integers, no decimals."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        sim_results_section = a2ui.split("# A2UI Format: Simulation Results")[1]
        for forbidden in ('"7.2"', '"7.1"', '"5.3"'):
            assert forbidden not in sim_results_section, (
                f"Found float example score {forbidden}; sim scores must be 0-100 integers"
            )

    def test_sim_results_documents_evaluate_plan_score_sourcing(self):
        """Prompt must instruct LLM to source numeric scores from evaluate_plan.scores."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        sim_results_section = a2ui.split("# A2UI Format: Simulation Results")[1]
        assert "safety_compliance" in sim_results_section
        assert "participant_experience" in sim_results_section
        assert "community_impact" in sim_results_section

    def test_sim_results_caps_total_distance_at_marathon(self):
        """Prompt must cap displayed Total distance at 26.2 miles (marathon)."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        sim_results_section = a2ui.split("# A2UI Format: Simulation Results")[1]
        assert "26.2" in sim_results_section
        lower = sim_results_section.lower()
        assert any(
            phrase in lower
            for phrase in (
                "never exceed 26.2",
                "always 26.2",
                "cap at 26.2",
                "capped at 26.2",
                'always show "26.2',
            )
        ), "Prompt must instruct the LLM to cap Total distance at 26.2 miles"

    def test_sim_results_forbids_dropped_rows(self):
        """Prompt must explicitly forbid Spectators / Peak Hour Volume rows."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        sim_results_section = a2ui.split("# A2UI Format: Simulation Results")[1]
        lower = sim_results_section.lower()
        assert "must not" in lower or "never" in lower, (
            "Prompt must contain MUST NOT / NEVER constraints to prevent LLM drift"
        )
        assert "Spectators" in sim_results_section, "Forbidden-rows list must name 'Spectators'"
        assert "Peak Hour Volume" in sim_results_section, "Forbidden-rows list must name 'Peak Hour Volume'"

    def test_sim_results_forbids_float_scores(self):
        """Prompt must explicitly forbid float / 0-10 scores via a forbidden example."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        sim_results_section = a2ui.split("# A2UI Format: Simulation Results")[1]
        # The forbidden value 7.2 (without JSON quotes) must appear as a counter-example
        assert "7.2" in sim_results_section, "Prompt must give a forbidden-value example (e.g. 7.2) to anchor the LLM"

    def test_sim_results_forbids_old_participants_label(self):
        """Prompt must explicitly forbid '(expected/attendance)' label."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        sim_results_section = a2ui.split("# A2UI Format: Simulation Results")[1]
        assert "(expected/attendance)" in sim_results_section, (
            "Prompt must name the forbidden '(expected/attendance)' label to prevent drift"
        )

    def test_execution_instructs_sim_results_card(self):
        """After simulation completes, agent must emit a sim results A2UI card."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        assert "sim_results" in execution
        assert "validate_and_emit_a2ui" in execution

    def test_execution_maps_data_sources_explicitly(self):
        """Execution must map card fields to specific tool responses, not just name tools."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        # Must contain explicit field-to-source mapping (not just tool names)
        # The instruction must tell the agent WHERE to get specific data
        assert "simulator response" in execution.lower() or "simulation response" in execution.lower(), (
            "Execution must reference 'simulator response' as a data source "
            "so the agent knows to extract data from the tool response"
        )

    def test_execution_guides_missing_data_explicitly(self):
        """Execution must explicitly instruct using placeholder for unavailable data."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        # Must mention placeholder behavior after the data mapping, not in the title
        # Split off the title line to avoid matching the em-dash in "User-Triggered —"
        body = "\n".join(execution.strip().split("\n")[1:])
        assert "\u2014" in body, "Execution body (not title) must contain \u2014 as placeholder guidance"

    def test_button_handler_includes_a2ui_emission(self):
        """A2UI button handler must include or reference A2UI emission step."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        # Isolate ONLY the button handler section (between "Handling" and "Simulation Results")
        parts = a2ui.split("# A2UI Format: Simulation Results")
        handler_part = parts[0].split("Handling A2UI Button Actions")[1]
        # Must reference execution section OR mention A2UI emission
        has_execution_ref = "Execution" in handler_part
        has_emission = "validate_and_emit_a2ui" in handler_part
        has_sim_results = "sim_results" in handler_part
        assert has_execution_ref or has_emission or has_sim_results, (
            "Button handler section (before sim results format) must reference "
            "the Execution section or include A2UI emission step"
        )

    def test_sim_results_format_has_placeholder_guidance(self):
        """Sim results format must tell agent to use placeholder for missing data."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        # Get text after the format heading (not the button handler reference)
        sim_section = a2ui.split("# A2UI Format: Simulation Results")[1]
        assert "\u2014" in sim_section  # em-dash placeholder


class TestPlanCardA2UISection:
    """Validate the A2UI plan summary card one-shot example."""

    def test_dashboard_has_plan_tag(self):
        """Dashboard card must include PLAN tag label."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        dashboard_section = a2ui.split("# Handling A2UI Button Actions")[0]
        assert "PLAN" in dashboard_section

    def test_dashboard_has_score_display(self):
        """Dashboard card must include score number with h1 usageHint."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        dashboard_section = a2ui.split("# Handling A2UI Button Actions")[0]
        assert '"usageHint": "h1"' in dashboard_section

    def test_dashboard_has_scoring_grid(self):
        """Dashboard card must include all 7 evaluation criteria in scoring grid."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        dashboard_section = a2ui.split("# Handling A2UI Button Actions")[0]
        assert "Safety Compliance" in dashboard_section
        assert "Logistics Completeness" in dashboard_section
        assert "Participant Experience" in dashboard_section
        assert "Community Impact" in dashboard_section
        assert "Financial Viability" in dashboard_section
        assert "Intent Alignment" in dashboard_section
        assert "Distance Compliance" in dashboard_section

    def test_dashboard_has_findings_section(self):
        """Dashboard card must include a Findings section."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        dashboard_section = a2ui.split("# Handling A2UI Button Actions")[0]
        assert "Findings" in dashboard_section

    def test_dashboard_has_run_simulation_button(self):
        """Dashboard card must include run_simulation action button."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        dashboard_section = a2ui.split("# Handling A2UI Button Actions")[0]
        assert "run_simulation" in dashboard_section

    def test_dashboard_has_placeholder_guidance(self):
        """Dashboard card instructions must mention placeholder for missing data."""
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        dashboard_section = a2ui.split("# Handling A2UI Button Actions")[0]
        assert "\u2014" in dashboard_section


class TestSerialEvaluateAndVerify:
    """Verify evaluate_plan and submit_plan_to_simulator(verify) stay serial.

    The previous parallel-tool wording ("Evaluate AND verify") was added by
    5b332732 and triggered Bug B: the post-tool continuation turn after a
    parallel batch returns a thought-signature-only Part, ADK exits via
    is_final_response, and no narrative text reaches chat. Reverted in
    topic/qa-regression-fixes (see
    docs/plans/2026-04-18-bug-b-h1-parallel-tool-revert-design.md).
    """

    def test_workflow_does_not_parallelize_evaluate_and_verify(self):
        """The 'Evaluate AND verify: call evaluate_plan AND…' wording must be gone."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        # Distinctive substring from the 5b332732 step-6 instruction.
        assert "Evaluate AND verify" not in workflow, (
            "Workflow re-introduces the 5b332732 parallel-evaluate-and-verify wording that caused Bug B"
        )
        assert "evaluate_plan` AND" not in workflow, (
            "Workflow re-introduces 'evaluate_plan AND submit_plan_to_simulator' in the SAME response"
        )

    def test_report_and_traffic_still_parallel(self):
        """report_marathon_route AND assess_traffic_impact remain parallel (pre-existing)."""
        workflow = PLANNER_WITH_EVAL.sections["workflow"]
        assert "report_marathon_route" in workflow
        assert "assess_traffic_impact" in workflow
        assert "report_marathon_route` AND `assess_traffic_impact` in the SAME response" in workflow


class TestSerialExecutionStartAndSubmit:
    """Verify start_simulation and submit_plan_to_simulator(execute) stay serial.

    See docs/plans/2026-04-18-bug-b-h1-parallel-tool-revert-design.md.
    """

    def test_execution_start_and_submit_on_separate_steps(self):
        """`start_simulation` and `submit_plan_to_simulator(execute)` must occupy different numbered steps.

        Structural check: the lines containing each call must resolve to
        different numbered step boundaries when walking back through the
        execution text. Robust to whitespace/argument changes — only the
        step-boundary structure matters.
        """
        import re

        execution = PLANNER_WITH_EVAL.sections["execution"]
        lines = execution.split("\n")
        step_re = re.compile(r"^\s*(\d+)\.\s")

        def step_for(needle: str) -> int:
            for i, line in enumerate(lines):
                if needle in line:
                    for j in range(i, -1, -1):
                        m = step_re.match(lines[j])
                        if m:
                            return int(m.group(1))
            raise AssertionError(f"{needle!r} not found in execution section")

        start_step = step_for("start_simulation")
        submit_step = step_for('submit_plan_to_simulator(action="execute"')
        assert start_step != submit_step, (
            f"start_simulation and submit_plan_to_simulator(execute) must be on "
            f"different numbered steps; both resolved to step {start_step} (Bug B regression)"
        )

    def test_execution_still_calls_both(self):
        execution = PLANNER_WITH_EVAL.sections["execution"]
        assert "start_simulation" in execution
        assert "submit_plan_to_simulator" in execution


class TestExecutionStopInstruction:
    """Verify execution section has terminal STOP instruction."""

    def test_execution_contains_stop(self):
        """Execution must contain STOP directive after A2UI emission."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        assert "STOP" in execution

    def test_execution_contains_do_not_run_again(self):
        """Execution must prohibit re-running simulation automatically."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        assert "Do NOT run another simulation" in execution

    def test_execution_contains_do_not_restart(self):
        """Execution must prohibit restarting the workflow."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        assert "Do NOT restart the workflow" in execution

    def test_execution_stop_is_terminal(self):
        """STOP must appear after the A2UI emission step (last numbered step)."""
        execution = PLANNER_WITH_EVAL.sections["execution"]
        stop_idx = execution.index("STOP")
        a2ui_idx = execution.index("validate_and_emit_a2ui")
        assert stop_idx > a2ui_idx


class TestA2UIContainsNoDates:
    """Regression: A2UI cards must not include dates/timestamps in any caption."""

    # Matches YYYY-MM-DD, YY/MM/DD, ISO-8601 with time, and HH:MM:SS time strings.
    _DATE_RE = re.compile(
        r"\b("
        r"\d{4}-\d{2}-\d{2}"  # 2026-04-16
        r"|\d{2}/\d{2}/\d{2}"  # 26/04/06
        r"|\d{4}/\d{2}/\d{2}"  # 2026/04/06
        r"|\d{2}:\d{2}:\d{2}"  # 09:15:00
        r")\b"
    )

    def test_a2ui_section_has_no_date_literal(self):
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"]
        matches = self._DATE_RE.findall(a2ui)
        assert matches == [], f"A2UI section must not contain date literals; found: {matches}"

    def test_a2ui_section_does_not_instruct_to_include_timestamp(self):
        """Prompt must not POSITIVELY instruct the LLM to include a timestamp.

        Mentioning 'timestamp' inside a MUST NOT / forbidden block is fine
        (and required to anchor against drift); mentioning it as a positive
        directive is not.
        """
        a2ui = PLANNER_WITH_EVAL.sections["a2ui"].lower()
        forbidden_directives = (
            "include a timestamp",
            "add a timestamp",
            "show a timestamp",
            "with a timestamp",
            "include the timestamp",
        )
        for directive in forbidden_directives:
            assert directive not in a2ui, f"A2UI section must not positively instruct the LLM to {directive!r}"


class TestRunnerCapNoLongerHardcoded:
    """The hardcoded 1,000 cap text was removed from the prompt
    (topic/llm-runner-cap, Option-alpha minimal deletion).

    The simulator clamps via cap_for_runner_type and emits capped_from in
    the tool result; the prompt does not mention a specific cap value.
    Negative-only assertions: deliberately do not assert positive
    capped_from prose because Option-alpha specifically avoids substitute
    prose that perturbs Gemini 3 Flash Preview's tool-selection behavior.
    """

    def test_no_hardcoded_cap_value(self):
        _instruction = PLANNER_WITH_EVAL.build()
        assert "1,000" not in _instruction
        assert "1000" not in _instruction

    def test_no_cap_clause_near_runner_count(self):
        text = PLANNER_WITH_EVAL.build().lower()
        # Window after the first runner_count mention; cap clauses (if any)
        # would appear here. Empty window means no runner_count mention,
        # which would itself be a separate failure caught upstream.
        assert "runner_count" in text, "runner_count should still be mentioned"
        window = text.split("runner_count", 1)[1][:300]
        assert "max " not in window
        assert "capped" not in window
