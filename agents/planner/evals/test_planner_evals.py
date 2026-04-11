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

"""ADK evaluations for the planner agent.

Non-slow tests validate eval data files parse correctly (runs in `make test`).
Slow tests run the actual agent against Gemini (runs in `make eval`).
"""

import json
import pathlib

import pytest

EVALS_DIR = pathlib.Path(__file__).parent


# ---------------------------------------------------------------------------
# Data validation tests (fast, no API calls, included in `make test`)
# ---------------------------------------------------------------------------


def test_eval_data_files_exist():
    """The eval dataset and config files must exist."""
    assert (EVALS_DIR / "planner_trajectory.test.json").exists()
    assert (EVALS_DIR / "test_config.json").exists()


def test_eval_dataset_parses_as_eval_set():
    """The .test.json file must parse as a valid ADK EvalSet."""
    from google.adk.evaluation.eval_set import EvalSet

    raw = json.loads((EVALS_DIR / "planner_trajectory.test.json").read_text())
    eval_set = EvalSet.model_validate(raw)
    assert eval_set.eval_set_id == "planner_trajectory"
    assert len(eval_set.eval_cases) >= 2


def test_eval_dataset_cases_have_tool_trajectories():
    """Each eval case must define expected tool call trajectories."""
    from google.adk.evaluation.eval_set import EvalSet
    from google.adk.evaluation.eval_case import get_all_tool_calls

    raw = json.loads((EVALS_DIR / "planner_trajectory.test.json").read_text())
    eval_set = EvalSet.model_validate(raw)

    for case in eval_set.eval_cases:
        assert case.conversation is not None, f"Case {case.eval_id} missing conversation"
        for invocation in case.conversation:
            tool_calls = get_all_tool_calls(invocation.intermediate_data)
            assert len(tool_calls) > 0, f"Case {case.eval_id} invocation has no expected tool calls"


def test_eval_config_parses():
    """The test_config.json must parse as a valid ADK EvalConfig."""
    from google.adk.evaluation.eval_config import EvalConfig

    raw = json.loads((EVALS_DIR / "test_config.json").read_text())
    config = EvalConfig.model_validate(raw)
    assert "tool_trajectory_avg_score" in config.criteria


def test_eval_config_uses_in_order_matching():
    """The trajectory config must use IN_ORDER matching (not EXACT)."""
    from google.adk.evaluation.eval_config import EvalConfig
    from google.adk.evaluation.eval_metrics import ToolTrajectoryCriterion

    raw = json.loads((EVALS_DIR / "test_config.json").read_text())
    config = EvalConfig.model_validate(raw)

    criterion = config.criteria["tool_trajectory_avg_score"]
    # BaseCriterion with extra="allow" preserves matchType as an extra field
    match_type = getattr(criterion, "match_type", None) or getattr(criterion, "matchType", None)
    assert match_type == ToolTrajectoryCriterion.MatchType.IN_ORDER.value or (
        match_type == ToolTrajectoryCriterion.MatchType.IN_ORDER
    ), f"Expected IN_ORDER (1), got {match_type}"


def test_eval_dataset_standard_planning_trajectory():
    """The standard_marathon_planning case must expect the correct tool sequence."""
    from google.adk.evaluation.eval_set import EvalSet
    from google.adk.evaluation.eval_case import get_all_tool_calls

    raw = json.loads((EVALS_DIR / "planner_trajectory.test.json").read_text())
    eval_set = EvalSet.model_validate(raw)

    # Find the standard planning case
    standard_case = next(
        (c for c in eval_set.eval_cases if c.eval_id == "standard_marathon_planning"),
        None,
    )
    assert standard_case is not None, "Missing 'standard_marathon_planning' eval case"
    conversation = standard_case.conversation
    assert conversation is not None, "Case has no conversation"

    tool_calls = get_all_tool_calls(conversation[0].intermediate_data)
    tool_names = [tc.name for tc in tool_calls]
    assert tool_names == [
        "plan_marathon_route",
        "report_marathon_route",
    ]


# ---------------------------------------------------------------------------
# Agent evaluation tests (slow, requires Gemini API, runs in `make eval`)
# ---------------------------------------------------------------------------

# Gemini 3 preview models have a thought signature incompatibility with ADK's
# EvaluationGenerator: signatures are bound to a single API request but ADK
# replays them across multi-turn conversations, causing "Thought signature is
# not valid" errors.  Use gemini-2.5-flash for evals until ADK or the Gemini 3
# API resolves this.  The trajectory evaluation tests tool-call ordering, not
# model-specific behavior, so the model choice is acceptable.
_EVAL_MODEL = "gemini-2.5-flash"

# Expected tool call sequences (name-only, IN_ORDER).
# ADK's built-in TrajectoryEvaluator requires exact args matching which is too
# strict for LLM-generated arguments.  We check tool names in order instead,
# allowing extra intermediate calls (e.g. load_skill) between expected tools.
_EXPECTED_TRAJECTORIES: dict[str, list[str]] = {
    "standard_marathon_planning": [
        "plan_marathon_route",
        "report_marathon_route",
    ],
    "plan_without_execution": [
        "plan_marathon_route",
        "report_marathon_route",
    ],
}


def _check_tool_names_in_order(actual_names: list[str], expected_names: list[str]) -> bool:
    """Check that expected tool names appear in actual list in order.

    Allows extra tool calls between expected ones (e.g. load_skill).
    """
    expected_iter = iter(expected_names)
    try:
        current = next(expected_iter)
        for actual in actual_names:
            if actual == current:
                current = next(expected_iter)
    except StopIteration:
        return True
    return False


@pytest.mark.slow
@pytest.mark.asyncio
async def test_planner_trajectory_evaluation():
    """Run the planner agent and verify tool call trajectory matches expectations.

    This test requires:
    - GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION env vars
    - Network access to the Gemini API

    Run with: make eval
    """
    from google.adk.agents import LlmAgent
    from google.adk.evaluation import AgentEvaluator
    from google.adk.evaluation.eval_set import EvalSet
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    # Load agent and override model to avoid Gemini 3 thought signature bug
    base_agent = await AgentEvaluator._get_agent_for_eval("agents.planner.agent")
    assert isinstance(base_agent, LlmAgent), "Expected LlmAgent"
    agent: LlmAgent = base_agent
    agent.model = _EVAL_MODEL

    # Build eval cases from the .test.json file
    raw = json.loads((EVALS_DIR / "planner_trajectory.test.json").read_text())
    eval_set = EvalSet.model_validate(raw)

    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="planner_eval",
        session_service=session_service,
    )

    failures: list[str] = []

    for eval_case in eval_set.eval_cases:
        assert eval_case.conversation is not None
        expected_names = _EXPECTED_TRAJECTORIES.get(eval_case.eval_id, [])
        assert expected_names, f"No expected trajectory for {eval_case.eval_id}"

        user_content = eval_case.conversation[0].user_content
        assert user_content is not None

        # Create a fresh session per eval case
        session = await session_service.create_session(
            app_name="planner_eval",
            user_id=f"eval_{eval_case.eval_id}",
        )

        # Run the agent and collect tool call events
        actual_names: list[str] = []
        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=user_content,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.function_call and part.function_call.name:
                        actual_names.append(part.function_call.name)

        if not _check_tool_names_in_order(actual_names, expected_names):
            failures.append(f"Case '{eval_case.eval_id}': expected tools {expected_names} in order, got {actual_names}")
        else:
            # Verify plan_marathon_route is called at least once
            route_count = actual_names.count("plan_marathon_route")
            if route_count < 1:
                failures.append(f"Case '{eval_case.eval_id}': plan_marathon_route was never called")

    assert not failures, "Trajectory evaluation failures:\n" + "\n".join(failures)
