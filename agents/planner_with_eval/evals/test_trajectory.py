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

"""Lightweight trajectory evals for planner_with_eval.

Verifies tool PRESENCE (not ordering) for each user interaction type.
Does not enforce strict tool call order -- future optimizations will
introduce parallel tool calling which would break rigid ordering tests.

Requires Gemini API access. Run with: make eval
"""

import pytest

# Gemini 3 preview models have thought signature incompatibilities with ADK's
# replay mechanism. Use gemini-2.5-flash for evals.
_EVAL_MODEL = "gemini-2.5-flash"


def _collect_tool_calls(events) -> list[str]:
    """Extract tool call names from a sequence of ADK events."""
    names = []
    for event in events:
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.function_call and part.function_call.name:
                    names.append(part.function_call.name)
    return names


@pytest.mark.slow
@pytest.mark.asyncio
async def test_plan_route_calls_critical_tools():
    """Planning a route must call plan_marathon_route, evaluate_plan, and
    validate_and_emit_a2ui. Must NOT call start_simulation."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from agents.planner_with_eval.agent import get_agent

    agent = get_agent()
    agent.model = _EVAL_MODEL

    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="eval_trajectory_test",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="eval_trajectory_test",
        user_id="eval_plan_route",
    )

    events = []
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text="Plan a marathon in Las Vegas for 10,000 runners")],
        ),
    ):
        events.append(event)

    tool_names = _collect_tool_calls(events)

    # Must call these critical tools
    assert "plan_marathon_route" in tool_names, f"plan_marathon_route not called. Tools called: {tool_names}"
    assert "evaluate_plan" in tool_names, f"evaluate_plan not called. Tools called: {tool_names}"
    assert "validate_and_emit_a2ui" in tool_names, f"validate_and_emit_a2ui not called. Tools called: {tool_names}"

    # Must NOT call execution tools (should stop after A2UI)
    assert "start_simulation" not in tool_names, (
        f"start_simulation called during planning (should only happen on user trigger). Tools called: {tool_names}"
    )

    # plan_marathon_route should be called exactly once
    route_count = tool_names.count("plan_marathon_route")
    assert route_count == 1, f"plan_marathon_route called {route_count} times (expected 1). Tools called: {tool_names}"
