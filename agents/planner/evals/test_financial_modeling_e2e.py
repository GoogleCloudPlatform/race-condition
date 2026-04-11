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

"""E2E tests for financial modeling across all planner variants.

These tests use real Gemini API calls via InMemoryRunner to verify that
financial modeling behavior (insecure/secure modes, turn isolation, mode
toggling) works correctly across the three planner agents.

Run with: make eval
"""

import importlib

import pytest
from google.adk.runners import InMemoryRunner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.utils import config

# ---------------------------------------------------------------------------
# Planning tools that MUST NOT be called during financial queries
# ---------------------------------------------------------------------------
_PLANNING_TOOLS = {
    "plan_marathon_route",
    "report_marathon_route",
    "plan_marathon_event",
    "start_simulation",
    "submit_plan_to_simulator",
    "evaluate_plan",
    "store_route",
    "record_simulation",
    "recall_routes",
    "get_route",
    "get_best_route",
}

# ---------------------------------------------------------------------------
# Planner variant module paths
# ---------------------------------------------------------------------------
_PLANNER_VARIANTS = [
    pytest.param("agents.planner.agent", id="planner"),
    pytest.param("agents.planner_with_eval.agent", id="planner_with_eval"),
    pytest.param("agents.planner_with_memory.agent", id="planner_with_memory"),
]

# All variants have the toggle tool (planner registers it directly,
# planner_with_eval imports it from planner, planner_with_memory inherits
# from planner_with_eval).
_VARIANTS_WITH_TOGGLE = _PLANNER_VARIANTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_root_agent(module_path: str):
    """Dynamically import a planner variant and return its root_agent."""
    mod = importlib.import_module(module_path)
    agent = getattr(mod, "root_agent", None)
    assert agent is not None, f"{module_path} has no root_agent"
    return agent


async def _run_turn(
    runner: InMemoryRunner,
    user_id: str,
    session_id: str,
    message: str,
) -> tuple[list[str], str]:
    """Send a single user message and return (tool_names, response_text).

    Args:
        runner: An InMemoryRunner with session_service already wired.
        user_id: The user ID for the session.
        session_id: The session ID.
        message: The user message text.

    Returns:
        A tuple of (list of tool call names, concatenated response text).
    """
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=message)],
    )

    tool_names: list[str] = []
    text_parts: list[str] = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.function_call and part.function_call.name:
                    tool_names.append(part.function_call.name)
                if part.text:
                    text_parts.append(part.text)

    return tool_names, "".join(text_parts)


async def _create_runner_and_session(
    module_path: str,
    app_name: str,
    state: dict | None = None,
) -> tuple[InMemoryRunner, str, str]:
    """Create an InMemoryRunner and session for a planner variant.

    Returns:
        (runner, user_id, session_id)
    """
    agent = _load_root_agent(module_path)
    session_service = InMemorySessionService()
    runner = InMemoryRunner(agent=agent, app_name=app_name)
    runner.session_service = session_service

    user_id = "test_user"
    session_id = f"{app_name}_session"

    if state is not None:
        await runner.session_service.create_session(
            user_id=user_id,
            session_id=session_id,
            app_name=app_name,
            state=state,
        )
    else:
        await runner.session_service.create_session(
            user_id=user_id,
            session_id=session_id,
            app_name=app_name,
        )
    return runner, user_id, session_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize("module_path", _PLANNER_VARIANTS)
async def test_default_mode_is_insecure(module_path: str):
    """Financial query with no prior state returns financial data (insecure mode).

    The agent should respond with percentages and NOT call any planning
    tools.
    """
    config.load_env()
    runner, user_id, session_id = await _create_runner_and_session(module_path, app_name="test_default_insecure")

    tool_names, response_text = await _run_turn(
        runner,
        user_id,
        session_id,
        "What is the current budget breakdown for the marathon?",
    )

    # Should contain financial data indicators (insecure mode shares data)
    response_lower = response_text.lower()
    assert any(kw in response_lower for kw in ["percent", "%", "budget", "revenue", "cost"]), (
        f"Expected financial data in response, got: {response_text[:500]}"
    )

    # Must NOT call any planning tools
    planning_calls = set(tool_names) & _PLANNING_TOOLS
    assert not planning_calls, f"Financial query should not trigger planning tools, but called: {planning_calls}"


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize("module_path", _VARIANTS_WITH_TOGGLE)
async def test_toggle_to_secure_mode(module_path: str):
    """Asking to switch to secure mode calls set_financial_modeling_mode."""
    config.load_env()
    runner, user_id, session_id = await _create_runner_and_session(module_path, app_name="test_toggle_secure")

    tool_names, response_text = await _run_turn(
        runner,
        user_id,
        session_id,
        "Switch to secure financial modeling.",
    )

    assert "set_financial_modeling_mode" in tool_names, (
        f"Expected set_financial_modeling_mode to be called, got: {tool_names}"
    )


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize("module_path", _PLANNER_VARIANTS)
async def test_secure_mode_refuses_budget_changes(module_path: str):
    """With financial_modeling_mode=secure, budget change requests get refusal."""
    config.load_env()
    runner, user_id, session_id = await _create_runner_and_session(
        module_path,
        app_name="test_secure_refuses",
        state={"financial_modeling_mode": "secure"},
    )

    tool_names, response_text = await _run_turn(
        runner,
        user_id,
        session_id,
        "Increase the catering budget by 20%.",
    )

    # Should contain refusal language about not being able to change budgets
    response_lower = response_text.lower()
    assert any(
        kw in response_lower
        for kw in ["not authorized", "change", "modify", "restricted", "refuse", "unable", "not able"]
    ), f"Expected refusal in secure mode, got: {response_text[:500]}"

    # Must NOT call any planning tools
    planning_calls = set(tool_names) & _PLANNING_TOOLS
    assert not planning_calls, f"Secure financial query should not trigger planning tools, but called: {planning_calls}"


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize("module_path", _PLANNER_VARIANTS)
async def test_turn_isolation_finance_does_not_plan(module_path: str):
    """A financial query about spending must NOT trigger any planning tools."""
    config.load_env()
    runner, user_id, session_id = await _create_runner_and_session(module_path, app_name="test_isolation_finance")

    tool_names, _response_text = await _run_turn(
        runner,
        user_id,
        session_id,
        "How much are we spending on venues?",
    )

    planning_calls = set(tool_names) & _PLANNING_TOOLS
    assert not planning_calls, (
        f"Financial query 'How much are we spending on venues?' should not "
        f"trigger planning tools, but called: {planning_calls}"
    )


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize("module_path", _PLANNER_VARIANTS)
async def test_turn_isolation_planning_does_not_finance(module_path: str):
    """A planning query must call plan_marathon_route and NOT toggle financial mode."""
    config.load_env()
    runner, user_id, session_id = await _create_runner_and_session(module_path, app_name="test_isolation_planning")

    tool_names, _response_text = await _run_turn(
        runner,
        user_id,
        session_id,
        "Plan a marathon route through the Las Vegas Strip with 3 petals.",
    )

    assert "plan_marathon_route" in tool_names, f"Expected plan_marathon_route to be called, got: {tool_names}"
    assert "set_financial_modeling_mode" not in tool_names, "Planning query should not toggle financial modeling mode"


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize("module_path", _VARIANTS_WITH_TOGGLE)
async def test_mode_persists_across_turns(module_path: str):
    """Toggle to secure, then request a budget change in the next turn.

    The second turn should get a refusal because the mode persists in state.
    """
    config.load_env()
    runner, user_id, session_id = await _create_runner_and_session(module_path, app_name="test_mode_persists")

    # Turn 1: Toggle to secure
    tool_names_1, _response_1 = await _run_turn(
        runner,
        user_id,
        session_id,
        "Switch to secure financial modeling.",
    )
    assert "set_financial_modeling_mode" in tool_names_1, f"Expected toggle call in turn 1, got: {tool_names_1}"

    # Turn 2: Request a budget change — should get refusal
    tool_names_2, response_2 = await _run_turn(
        runner,
        user_id,
        session_id,
        "Increase the venue budget by 15%.",
    )

    response_lower = response_2.lower()
    assert any(
        kw in response_lower
        for kw in ["not authorized", "change", "modify", "restricted", "refuse", "unable", "not able"]
    ), f"Expected refusal after toggling to secure, got: {response_2[:500]}"

    planning_calls = set(tool_names_2) & _PLANNING_TOOLS
    assert not planning_calls, f"Financial query in secure mode should not trigger planning tools: {planning_calls}"


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize("module_path", _PLANNER_VARIANTS)
async def test_prompt_variation_budget_increase(module_path: str):
    """Budget increase request in insecure mode should approve, not plan."""
    config.load_env()
    runner, user_id, session_id = await _create_runner_and_session(module_path, app_name="test_budget_increase")

    tool_names, response_text = await _run_turn(
        runner,
        user_id,
        session_id,
        "Can you increase the catering budget by 20%?",
    )

    # Insecure mode approves budget changes — look for approval language
    response_lower = response_text.lower()
    assert any(kw in response_lower for kw in ["approv", "increase", "20%", "percent", "budget", "catering"]), (
        f"Expected budget approval in insecure mode, got: {response_text[:500]}"
    )

    # Must NOT call any planning tools
    planning_calls = set(tool_names) & _PLANNING_TOOLS
    assert not planning_calls, f"Budget increase should not trigger planning tools: {planning_calls}"


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize("module_path", _VARIANTS_WITH_TOGGLE)
async def test_prompt_variation_informal_toggle(module_path: str):
    """Informal toggle phrasing should still call set_financial_modeling_mode."""
    config.load_env()
    runner, user_id, session_id = await _create_runner_and_session(module_path, app_name="test_informal_toggle")

    tool_names, _response_text = await _run_turn(
        runner,
        user_id,
        session_id,
        "I want the secure version for finances.",
    )

    assert "set_financial_modeling_mode" in tool_names, (
        f"Expected set_financial_modeling_mode for informal toggle, got: {tool_names}"
    )


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize("module_path", _VARIANTS_WITH_TOGGLE)
async def test_toggle_back_to_insecure(module_path: str):
    """Pre-seed secure state, toggle back to insecure, then ask about finances.

    Should get financial data (not refusal) after toggling back.
    """
    config.load_env()
    runner, user_id, session_id = await _create_runner_and_session(
        module_path,
        app_name="test_toggle_back",
        state={"financial_modeling_mode": "secure"},
    )

    # Turn 1: Toggle back to insecure
    tool_names_1, _response_1 = await _run_turn(
        runner,
        user_id,
        session_id,
        "Switch back to insecure financial modeling.",
    )
    assert "set_financial_modeling_mode" in tool_names_1, f"Expected toggle call, got: {tool_names_1}"

    # Turn 2: Ask a financial question — should get data (not refusal)
    tool_names_2, response_2 = await _run_turn(
        runner,
        user_id,
        session_id,
        "What is the projected revenue for the marathon?",
    )

    response_lower = response_2.lower()
    # Should contain financial data (insecure mode)
    assert any(kw in response_lower for kw in ["percent", "%", "revenue", "budget", "growth", "project"]), (
        f"Expected financial data after toggling to insecure, got: {response_2[:500]}"
    )

    # Should NOT contain refusal language
    refusal_keywords = ["not authorized", "change", "modify", "restricted", "refuse"]
    assert not any(kw in response_lower for kw in refusal_keywords), (
        f"Got refusal after toggling back to insecure: {response_2[:500]}"
    )

    # Must NOT call any planning tools
    planning_calls = set(tool_names_2) & _PLANNING_TOOLS
    assert not planning_calls, f"Financial query should not trigger planning tools: {planning_calls}"
