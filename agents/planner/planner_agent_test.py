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
from unittest.mock import patch
from google.adk.runners import InMemoryRunner
from google.genai import types

# This will fail initially because the module doesn't exist
try:
    from agents.planner.agent import root_agent
except ImportError:
    root_agent = None


def test_planner_has_a2a_agent_instance():
    """Planner must export planner_a2a_agent for Agent Engine deployment."""
    from agents.planner.agent import planner_a2a_agent

    assert planner_a2a_agent is not None


def test_planner_agent_card_is_callable():
    """Planner agent card must have http_json transport and no streaming."""
    from agents.planner.agent import agent_card
    from a2a.types import TransportProtocol

    assert agent_card.preferred_transport == TransportProtocol.http_json
    assert agent_card.capabilities.streaming is False


@pytest.mark.skipif(root_agent is None, reason="Planner agent not yet implemented")
@pytest.mark.asyncio
async def test_planner_route_generation():
    app_name = "marathon_planner"
    runner = InMemoryRunner(agent=root_agent, app_name=app_name)
    session_id = "test_plan_session"
    user_id = "test_planner"

    await runner.session_service.create_session(user_id=user_id, session_id=session_id, app_name=app_name)

    # Mock LLM response with a marathon route plan
    from google.adk.events.event import Event

    mock_route = {
        "route_id": "marathon_2026",
        "total_distance_mi": 26.2188,
        "waypoints": [
            {"lat": 52.5200, "lon": 13.4050, "label": "Start: Brandenburg Gate"},
            {"lat": 52.5167, "lon": 13.3777, "label": "Victory Column"},
        ],
    }

    mock_event = Event(
        author="planner_agent",
        content=types.Content(parts=[types.Part.from_text(text=f"I have planned the marathon route: {mock_route}")]),
    )

    with patch("google.adk.agents.llm_agent.LlmAgent._run_async_impl") as mock_run_impl:

        async def mock_generator(*args, **kwargs):
            yield mock_event

        mock_run_impl.return_value = mock_generator()

        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text="Plan a marathon route for Berlin.")],
        )

        events = []
        async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
            events.append(event)

        final_text = "".join([part.text for part in events[-1].content.parts if part.text])
        assert "26.2188" in final_text
