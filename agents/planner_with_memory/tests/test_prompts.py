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

import re

from agents.planner_with_memory.prompts import MEMORY_SYSTEM_INSTRUCTION, PLANNER_WITH_MEMORY


def _extract_section(heading: str) -> str:
    """Extract a ## section from the prompt by heading, bounded by the next ## or end."""
    start = MEMORY_SYSTEM_INSTRUCTION.index(heading)
    end = MEMORY_SYSTEM_INSTRUCTION.find("\n## ", start + 1)
    return MEMORY_SYSTEM_INSTRUCTION[start:end] if end != -1 else MEMORY_SYSTEM_INSTRUCTION[start:]


class TestMemorySystemInstructionInheritance:
    def test_inherits_base_planner_instruction(self):
        assert "plan_marathon_route" in MEMORY_SYSTEM_INSTRUCTION

    def test_inherits_eval_instruction_simulator(self):
        assert "submit_plan_to_simulator" in MEMORY_SYSTEM_INSTRUCTION

    def test_inherits_eval_instruction_evaluator(self):
        assert "evaluate_plan" in MEMORY_SYSTEM_INSTRUCTION

    def test_inherits_exactly_once_constraint(self):
        assert "EXACTLY ONCE" in MEMORY_SYSTEM_INSTRUCTION


class TestMemoryToolReferences:
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
    def test_contains_route_memory_database_section(self):
        assert "# Route Memory Database" in MEMORY_SYSTEM_INSTRUCTION

    def test_contains_workflow_section(self):
        assert "# Workflow" in MEMORY_SYSTEM_INSTRUCTION

    def test_contains_route_id_guidance(self):
        assert "route_id" in MEMORY_SYSTEM_INSTRUCTION

    def test_contains_uuid_guidance(self):
        assert "UUID" in MEMORY_SYSTEM_INSTRUCTION


class TestSeedAndActivationPromptContent:
    def test_contains_activate_route(self):
        assert "activate_route" in MEMORY_SYSTEM_INSTRUCTION

    def test_contains_pre_loaded_or_seed(self):
        lower = MEMORY_SYSTEM_INSTRUCTION.lower()
        assert "pre-loaded" in lower or "seed" in lower

    def test_contains_recall_workflow_section(self):
        assert "Recall Workflow" in MEMORY_SYSTEM_INSTRUCTION

    def test_contains_execute_by_reference_section(self):
        assert "Execute-by-Reference" in MEMORY_SYSTEM_INSTRUCTION

    def test_execute_by_reference_prohibits_report_marathon_route(self):
        section = _extract_section("## Execute-by-Reference Workflow")
        assert "Do NOT call report_marathon_route" in section

    def test_execute_by_reference_has_three_steps(self):
        import re

        section = _extract_section("## Execute-by-Reference Workflow")
        steps = re.findall(r"^\d+\.", section, re.MULTILINE)
        assert len(steps) == 3, f"Expected 3 steps, found {len(steps)}: {steps}"

    def test_execute_by_reference_references_protocol(self):
        section = _extract_section("## Execute-by-Reference Workflow")
        assert "Simulation Execution Protocol" in section

    def test_simulation_execution_protocol_has_stop(self):
        section = _extract_section("## Simulation Execution Protocol")
        assert "STOP" in section

    def test_simulation_execution_protocol_emits_a2ui(self):
        section = _extract_section("## Simulation Execution Protocol")
        assert "validate_and_emit_a2ui" in section
        assert "sim_results" in section


class TestButtonInheritance:
    def test_memory_prompts_inherit_button(self):
        assert "Button" in MEMORY_SYSTEM_INSTRUCTION
        assert "run_simulation" in MEMORY_SYSTEM_INSTRUCTION

    def test_memory_prompts_inherit_a2ui_action_handler(self):
        assert "a2ui_action" in MEMORY_SYSTEM_INSTRUCTION


class TestRunRouteHandlerRemoved:
    """Verify run_route handler was removed (organizer no longer triggers sims)."""

    def test_no_run_route_handler_section(self):
        assert "## Handling Route A2UI Button Actions" not in MEMORY_SYSTEM_INSTRUCTION

    def test_no_run_route_action_in_route_list(self):
        section = _extract_section("## A2UI Format: Route List")
        assert "run_route:" not in section


class TestSerialMemoryWorkflowParallels:
    """Verify the prompt steps 5b332732 parallelized are now serial again.

    The previous parallel-tool wording ("call X AND Y in the SAME response")
    triggered Bug B: the post-tool continuation turn returns a
    thought-signature-only Part, ADK exits via is_final_response, and no
    narrative text reaches chat. Reverted in topic/qa-regression-fixes (see
    docs/plans/2026-04-18-bug-b-h1-parallel-tool-revert-design.md).
    """

    def test_workflow_does_not_parallelize_recall_and_rules(self):
        """recall_past_simulations AND get_local_and_traffic_rules SAME response wording must be gone."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        # Distinctive substring from the 5b332732 step (the tool was renamed
        # by 3a640a60 from get_local_laws_and_regulations).
        assert "`recall_past_simulations` AND `get_local_and_traffic_rules`" not in workflow, (
            "Workflow re-introduces the 5b332732 parallel recall+rules wording"
        )

    def test_workflow_does_not_parallelize_store_and_verify(self):
        """store_route AND submit_plan_to_simulator(verify) SAME response wording must be gone."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        # Tightened from "`store_route` AND" to the specific 5b332732 form
        # ("`store_route` AND `submit_plan_to_simulator") so the test only
        # fires on the actual regression, not on hypothetical future
        # parallels of store_route with unrelated tools.
        assert "`store_route` AND `submit_plan_to_simulator" not in workflow, (
            "Workflow re-introduces the 5b332732 parallel store+verify wording"
        )

    def test_terminal_rules_does_not_parallelize_record_and_summary(self):
        """TERMINAL_RULES must not instruct record + summary in SAME response."""
        # TERMINAL_RULES is prepended to MEMORY_WORKFLOW so it appears in the workflow section.
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "`record_simulation` AND `store_simulation_summary`" not in workflow, (
            "TERMINAL_RULES re-introduces the 5b332732 parallel record+summary wording"
        )

    def test_report_and_traffic_still_parallel(self):
        """report_marathon_route AND assess_traffic_impact remain parallel (pre-existing)."""
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "report_marathon_route" in workflow
        assert "assess_traffic_impact" in workflow
        # The pre-existing parallel pair: keep its SAME-response wording.
        assert "`report_marathon_route` AND `assess_traffic_impact` in the SAME response" in workflow


class TestSerialMemoryExecutionProtocol:
    """Verify the Simulation Execution Protocol's record+summary parallelism is reverted.

    See docs/plans/2026-04-18-bug-b-h1-parallel-tool-revert-design.md.
    """

    def test_protocol_does_not_parallelize_record_and_summary(self):
        """`record_simulation` AND `store_simulation_summary` SAME response wording must be gone."""
        protocol = _extract_section("## Simulation Execution Protocol")
        assert "`record_simulation` AND `store_simulation_summary`" not in protocol, (
            "Simulation Execution Protocol re-introduces the 5b332732 parallel record+summary wording"
        )

    def test_protocol_start_and_submit_still_parallel(self):
        """start_simulation AND submit_plan_to_simulator(execute) remain parallel (pre-existing)."""
        protocol = _extract_section("## Simulation Execution Protocol")
        assert "start_simulation" in protocol
        assert "submit_plan_to_simulator" in protocol
        # This particular SAME-response instruction pre-existed 5b332732 and is
        # preserved deliberately (no harness signal implicating it).
        assert '`start_simulation` AND `submit_plan_to_simulator(action="execute")` in the SAME response' in protocol


class TestExecutionStopInstruction:
    def test_protocol_contains_stop(self):
        protocol = _extract_section("## Simulation Execution Protocol")
        assert "STOP" in protocol

    def test_protocol_contains_do_not_run_again(self):
        protocol = _extract_section("## Simulation Execution Protocol")
        assert "Do NOT run another simulation" in protocol

    def test_protocol_contains_do_not_restart(self):
        protocol = _extract_section("## Simulation Execution Protocol")
        assert "Do NOT restart the workflow" in protocol

    def test_protocol_stop_is_terminal(self):
        protocol = _extract_section("## Simulation Execution Protocol")
        stop_idx = protocol.index("STOP")
        a2ui_idx = protocol.index("validate_and_emit_a2ui")
        assert stop_idx > a2ui_idx


class TestPromptConsolidation:
    """submit_plan_to_simulator(action="execute") was previously duplicated in 4
    places, causing the model to re-trigger after completion. These tests verify
    it now appears exactly once (in the Simulation Execution Protocol) and other
    workflows reference it instead of inlining it."""

    def test_execute_action_appears_once_in_prompt(self):
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
        assert "Simulation Execution Protocol" in MEMORY_SYSTEM_INSTRUCTION

    def test_execution_references_protocol(self):
        execution = PLANNER_WITH_MEMORY.sections["execution"]
        assert "Simulation Execution Protocol" in execution

    def test_execute_by_reference_references_protocol(self):
        section = _extract_section("## Execute-by-Reference Workflow")
        assert "Simulation Execution Protocol" in section

    def test_terminal_rules_before_workflow(self):
        prompt = MEMORY_SYSTEM_INSTRUCTION
        terminal_idx = prompt.index("MUST NEVER re-execute")
        workflow_idx = prompt.index("# Workflow")
        assert terminal_idx < workflow_idx, "Terminal rules must appear before the Workflow section"


class TestWorkflowTriage:
    def test_workflow_has_triage_step(self):
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "Execute-by-Reference" in workflow
        # The triage must appear BEFORE the first numbered planning step
        triage_idx = workflow.index("Execute-by-Reference")
        first_recall = workflow.index("recall_past_simulations")
        assert triage_idx < first_recall, "Triage must appear before recall step"

    def test_workflow_triage_mentions_recall_intent(self):
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        lower = workflow.lower()
        assert "recall" in lower or "reuse" in lower or "run" in lower

    def test_workflow_triage_mentions_show_route(self):
        workflow = PLANNER_WITH_MEMORY.sections["workflow"]
        assert "show_route" in workflow


class TestExecuteByReferenceSequencing:
    def test_get_route_before_protocol(self):
        section = _extract_section("## Execute-by-Reference Workflow")
        get_route_idx = section.index("get_route")
        protocol_idx = section.index("Simulation Execution Protocol")
        assert get_route_idx < protocol_idx

    def test_sequencing_is_explicit(self):
        section = _extract_section("## Execute-by-Reference Workflow")
        assert "activate_route" in section
        lines = section.split("\n")
        step1_lines = [line for line in lines if "1." in line]
        step2_lines = [line for line in lines if "2." in line]
        assert any("get_route" in line for line in step1_lines)
        assert any("Simulation Execution Protocol" in line for line in step2_lines)


class TestShowRouteActionHandler:
    def test_contains_show_route_handler_section(self):
        assert "## Handling Show Route A2UI Button Actions" in MEMORY_SYSTEM_INSTRUCTION

    def test_show_route_handler_references_show_route(self):
        assert "show_route" in _extract_section("## Handling Show Route A2UI Button Actions")

    def test_show_route_handler_activates_route(self):
        assert "activate_route" in _extract_section("## Handling Show Route A2UI Button Actions")

    def test_show_route_handler_calls_report_marathon_route(self):
        assert "report_marathon_route" in _extract_section("## Handling Show Route A2UI Button Actions")

    def test_show_route_handler_does_not_start_simulation(self):
        section = _extract_section("## Handling Show Route A2UI Button Actions")
        assert "Do NOT" in section and "simulation" in section.lower()

    def test_show_route_handler_has_stop(self):
        section = _extract_section("## Handling Show Route A2UI Button Actions")
        assert "STOP" in section


class TestRouteListShowRouteButton:
    def test_route_list_has_show_route_button(self):
        section = _extract_section("## A2UI Format: Route List")
        assert "Show Route" in section

    def test_route_list_has_show_route_action(self):
        section = _extract_section("## A2UI Format: Route List")
        assert '"show_route"' in section

    def test_route_list_has_button_row(self):
        section = _extract_section("## A2UI Format: Route List")
        assert "Row" in section

    def test_route_list_has_open_report(self):
        section = _extract_section("## A2UI Format: Route List")
        assert "Open Report" in section
        assert "organizer_show_scorecard" in section


class TestStoredCardStructuralParity:
    """The STORED Route List card must be structurally identical to the
    SIMULATED card (same detail rows, layout) but with 'Open Report'
    instead of 'Run Simulation'.

    The example JSON MUST use bare {"surfaceUpdate": ...} format (the
    validate_and_emit_a2ui input format), NOT {"a2ui": {"surfaceUpdate": ...}}
    (which is the tool's output format).
    """

    def _extract_route_list_json(self) -> dict:
        import json

        section = _extract_section("## A2UI Format: Route List")
        start = section.index("```json") + len("```json")
        end = section.index("```", start)
        return json.loads(section[start:end])

    def test_example_uses_bare_surface_update_not_a2ui_wrapper(self):
        """The example must use bare surfaceUpdate, not the a2ui output wrapper."""
        card = self._extract_route_list_json()
        assert "surfaceUpdate" in card, "Example must have surfaceUpdate at top level"
        assert "a2ui" not in card, (
            'Example must NOT wrap in {"a2ui": ...} -- that is the tool\'s output format, not its input format'
        )

    def test_has_header_row_with_left_col_and_score_col(self):
        card = self._extract_route_list_json()
        ids = {c["id"] for c in card["surfaceUpdate"]["components"]}
        assert "left-col-1" in ids
        assert "score-col-1" in ids
        assert "header-1" in ids

    def test_omits_duplicate_score_id_bar(self):
        """The bar row duplicates score (in score-col h1) and route_id (in tag-row)."""
        card = self._extract_route_list_json()
        components = card["surfaceUpdate"]["components"]
        ids = {c["id"] for c in components}
        assert "bar-1" not in ids
        assert all(not i.startswith("bar-left") for i in ids)
        assert all(not i.startswith("bar-right") for i in ids)
        texts = [
            c["component"]["Text"]["text"]["literalString"] for c in components if "Text" in c.get("component", {})
        ]
        assert not any("SCORE 83%" in t for t in texts)

    def test_has_detail_rows(self):
        card = self._extract_route_list_json()
        components = card["surfaceUpdate"]["components"]
        texts = [
            c["component"]["Text"]["text"]["literalString"] for c in components if "Text" in c.get("component", {})
        ]
        assert "Total distance" in texts
        assert "Peak Hour Volume" not in texts, (
            "Peak Hour Volume must be removed from route_list card (no real data source)"
        )

    def test_participants_uses_expected_simulated(self):
        """Stored Route Participants row uses expected/simulated semantics."""
        card = self._extract_route_list_json()
        components = card["surfaceUpdate"]["components"]
        texts = [
            c["component"]["Text"]["text"]["literalString"] for c in components if "Text" in c.get("component", {})
        ]
        assert "Participants (expected/simulated)" in texts
        assert "Participants (expected/attendance)" not in texts

    def test_documents_recorded_simulation_fallback(self):
        """Prompt must say to use the most recent recorded simulation counts."""
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "most recent" in memory or "last recorded" in memory, (
            "Prompt must document where Participants counts come from for stored routes"
        )

    def test_score_examples_are_integers(self):
        """Example Safety/Runner/City score values must not be floats like 7.2."""
        card = self._extract_route_list_json()
        components = card["surfaceUpdate"]["components"]
        texts = [
            c["component"]["Text"]["text"]["literalString"] for c in components if "Text" in c.get("component", {})
        ]
        for forbidden in ("7.2", "7.1", "5.3"):
            assert forbidden not in texts, (
                f"Found float example score {forbidden}; route_list scores must be 0-100 integers"
            )

    def test_documents_evaluate_plan_score_sourcing(self):
        """Prompt must reference the evaluate_plan score keys for Safety/Runner/City."""
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "safety_compliance" in memory
        assert "participant_experience" in memory
        assert "community_impact" in memory

    def test_caps_total_distance_at_marathon(self):
        """Prompt must cap displayed Total distance at 26.2 miles (marathon)."""
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "26.2" in memory
        lower = memory.lower()
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

    def test_forbids_dropped_rows(self):
        """Prompt must explicitly forbid Spectators / Peak Hour Volume rows."""
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        lower = memory.lower()
        assert "must not" in lower or "never" in lower, (
            "Prompt must contain MUST NOT / NEVER constraints to prevent LLM drift"
        )
        assert "Spectators" in memory, "Forbidden-rows list must name 'Spectators'"
        assert "Peak Hour Volume" in memory, "Forbidden-rows list must name 'Peak Hour Volume'"

    def test_forbids_float_scores(self):
        """Prompt must give a forbidden float counter-example."""
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "7.2" in memory, "Prompt must name a forbidden float (e.g. 7.2) to anchor the LLM"

    def test_forbids_old_participants_label(self):
        """Prompt must name the forbidden '(expected/attendance)' label."""
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "(expected/attendance)" in memory, (
            "Prompt must name the forbidden '(expected/attendance)' label to prevent drift"
        )

    def test_omits_spectators(self):
        """Spectators row must be removed (no real data source today)."""
        card = self._extract_route_list_json()
        components = card["surfaceUpdate"]["components"]
        ids = {c["id"] for c in components}
        texts = [
            c["component"]["Text"]["text"]["literalString"] for c in components if "Text" in c.get("component", {})
        ]
        assert all(not i.startswith("spec-") for i in ids), f"Found spec-* IDs: {ids}"
        assert not any("Spectators" in t for t in texts)

    def test_has_eval_rows(self):
        card = self._extract_route_list_json()
        components = card["surfaceUpdate"]["components"]
        texts = [
            c["component"]["Text"]["text"]["literalString"] for c in components if "Text" in c.get("component", {})
        ]
        assert "Safety Score" in texts
        assert "Runner Experience" in texts
        assert "City Disruption" in texts

    def test_has_open_report_button_not_run_simulation(self):
        card = self._extract_route_list_json()
        components = card["surfaceUpdate"]["components"]
        buttons = [c for c in components if "Button" in c.get("component", {})]
        actions = [b["component"]["Button"]["action"]["name"] for b in buttons]
        assert "organizer_show_scorecard" in actions
        assert "run_simulation" not in actions

    def test_has_show_route_button(self):
        card = self._extract_route_list_json()
        components = card["surfaceUpdate"]["components"]
        buttons = [c for c in components if "Button" in c.get("component", {})]
        actions = [b["component"]["Button"]["action"] for b in buttons]
        show_route_actions = [a for a in actions if a.get("name") == "show_route"]
        assert len(show_route_actions) == 1, "Expected exactly one show_route button"
        assert "payload" in show_route_actions[0], "show_route must have payload"
        assert "seed" in show_route_actions[0]["payload"], "payload must contain seed"

    def test_has_two_dividers(self):
        card = self._extract_route_list_json()
        components = card["surfaceUpdate"]["components"]
        dividers = [c for c in components if "Divider" in c.get("component", {})]
        assert len(dividers) == 2

    def test_wrapped_in_list_and_root_card(self):
        card = self._extract_route_list_json()
        components = card["surfaceUpdate"]["components"]
        ids = {c["id"] for c in components}
        assert "list-1" in ids
        assert "root-card" in ids


class TestRouteListMultiRouteInstruction:
    """The Route List instructions must explicitly tell the LLM to combine
    all routes into a single surfaceUpdate components array."""

    def test_contains_single_surface_update_instruction(self):
        section = _extract_section("## A2UI Format: Route List")
        lower = section.lower()
        assert "single" in lower or "one" in lower, "Route List must instruct LLM to use a single surfaceUpdate"
        assert "components" in lower

    def test_prohibits_separate_json_per_route(self):
        section = _extract_section("## A2UI Format: Route List")
        lower = section.lower()
        assert "do not" in lower or "never" in lower, (
            "Route List must explicitly prohibit separate JSON objects per route"
        )


class TestMemoryA2UIContainsNoDates:
    """Regression: planner_with_memory A2UI Route List cards must not include dates."""

    _DATE_RE = re.compile(
        r"\b("
        r"\d{4}-\d{2}-\d{2}"  # 2026-04-16
        r"|\d{2}/\d{2}/\d{2}"  # 26/04/06
        r"|\d{4}/\d{2}/\d{2}"  # 2026/04/06
        r"|\d{2}:\d{2}:\d{2}"  # 09:15:00
        r")\b"
    )

    def test_memory_section_has_no_date_literal(self):
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        matches = self._DATE_RE.findall(memory)
        assert matches == [], f"MEMORY section must not contain date literals; found: {matches}"

    def test_memory_section_has_no_created_at_caption_directive(self):
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "<created_at>" not in memory, (
            "MEMORY section must not instruct the LLM to render <created_at> in card captions"
        )

    def test_memory_score_bar_does_not_request_date(self):
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        # The score-bar mapping line must NOT mention "date".
        bar_lines = [ln for ln in memory.splitlines() if "Score bar" in ln or "score bar" in ln]
        for ln in bar_lines:
            assert "date" not in ln.lower(), f"Score bar mapping must not request a date: {ln!r}"


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
        assert "1,000" not in MEMORY_SYSTEM_INSTRUCTION
        assert "1000" not in MEMORY_SYSTEM_INSTRUCTION

    def test_no_cap_clause_near_runner_count(self):
        text = MEMORY_SYSTEM_INSTRUCTION.lower()
        assert "runner_count" in text, "runner_count should still be mentioned"
        window = text.split("runner_count", 1)[1][:300]
        assert "max " not in window
        assert "capped" not in window


class TestStateDrivenPersistenceContract:
    """Regression: prompt MUST NOT instruct the LLM to pass large JSON payloads.

    See docs/plans/2026-04-19-state-driven-memory-persistence-design.md.
    The persistence tools (store_route, record_simulation,
    store_simulation_summary) read large data from session state.
    """

    def test_memory_section_does_not_request_route_data_argument(self):
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "route_data" not in memory, "MEMORY section must not mention route_data; the route is read from state."

    def test_memory_section_does_not_request_evaluation_result_argument(self):
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "evaluation_result" not in memory, (
            "MEMORY section must not mention evaluation_result; eval data is read from state."
        )

    def test_memory_section_does_not_request_simulation_result_argument(self):
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "simulation_result" not in memory, (
            "MEMORY section must not mention simulation_result; sim data is read from state."
        )

    def test_memory_section_documents_state_driven_contract(self):
        memory = PLANNER_WITH_MEMORY.sections["memory"]
        assert "session state" in memory.lower(), "MEMORY section must explicitly document the state-driven contract."
