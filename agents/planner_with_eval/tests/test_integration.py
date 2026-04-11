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

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types
from agents.utils import config

# TDD Rule: The module and agent do not exist yet, or root_agent is None.
from agents.planner_with_eval.agent import root_agent


@pytest.mark.skipif(root_agent is None, reason="Planner agent not yet implemented")
@pytest.mark.slow
@pytest.mark.asyncio
async def test_planner_evaluator_integration():
    """Verify that the planner can invoke the evaluator tool and process the evaluation result."""
    config.load_env()
    from google.adk.sessions import InMemorySessionService

    session_service = InMemorySessionService()
    runner = InMemoryRunner(agent=root_agent, app_name="test_planner_eval")
    runner.session_service = session_service
    session_id = "test_planner_eval_session"
    user_id = "test_user"

    await runner.session_service.create_session(user_id=user_id, session_id=session_id, app_name="test_planner_eval")

    # We send a message that explicitly demands a route plan and an evaluation.
    content = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=(
                    "Plan a marathon for 50,000 participants in Las Vegas. "
                    "It has to go by the Mandalay Bay Resort and spend half of its time in residential communities. "
                    "We are doing it on April 26, 2026. You MUST explicitly call the "
                    "`evaluate_plan` tool to evaluate it, then compose the A2UI dashboard "
                    "and validate with `validate_and_emit_a2ui`."
                )
            )
        ],
    )

    print("\n--- LLM Event Stream ---")
    events = []
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        events.append(event)

        # Print parts for debugging
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(f"TEXT: {part.text}")
                elif part.function_call:
                    print(f"CALL: {part.function_call.name} args={part.function_call.args}")

    print("------------------------\n")
    # While we can't deterministically check the LLM's final text in a real test without
    # an evaluation harness, we CAN verify that the tool call was made.
    tool_calls = [
        part.function_call
        for event in events
        if event.content and event.content.parts
        for part in event.content.parts
        if part.function_call
    ]

    assert any(call.name == "evaluate_plan" for call in tool_calls), "Evaluator tool was not called"

    final_text = "".join([part.text for part in events[-1].content.parts if part.text])
    assert final_text, "Expected a final text response from the agent"
