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
import time
from unittest.mock import MagicMock
from google.genai import types
from google.adk.agents import BaseAgent
from google.adk.runners import InMemoryRunner
from google.adk.apps import App

from agents.utils.dispatcher import RedisOrchestratorDispatcher


class MockEvent:
    def __init__(self, author, content):
        self.author = author
        self.content = content
        self.partial = False
        self.actions = MagicMock()
        self.debug = None
        self.timestamp = time.time()
        self.invocation_id = "test_iid"


class MultiPartAgent(BaseAgent):
    def __init__(self, name: str = "multi_part_agent"):
        super().__init__(name=name)

    async def run_async(self, session_id, new_message=None, **kwargs):  # type: ignore[override]
        # Yield two separate parts in one event
        content = types.Content(
            parts=[
                types.Part.from_text(text='{"status": "one"}'),
                types.Part.from_text(text='{"status": "two"}'),
            ]
        )
        yield MockEvent(author=self.name, content=content)


@pytest.mark.asyncio
async def test_dispatcher_splits_multiple_parts(monkeypatch):
    """Verifies that the dispatcher emits separate pulses for each part in an event,
    avoiding concatenated JSON blocks.
    """
    monkeypatch.setenv("REDIS_ADDR", "")
    agent = MultiPartAgent()
    app = App(name="test_app", root_agent=agent)
    runner = InMemoryRunner(app=app)

    dispatcher = RedisOrchestratorDispatcher(runner=runner)

    # We want to test the part-splitting logic inside _trigger_agent_run_logic
    pulses = []
    session_id = "test_sid"
    content = types.Content(parts=[types.Part.from_text(text="test")])

    # Pre-create session (in production, _ensure_session does this during spawn)
    await runner.session_service.create_session(
        app_name="test_app",
        user_id="simulation",
        session_id=session_id,
    )

    # We'll run it manually
    await dispatcher._trigger_agent_run_logic(session_id, content, pulses_collector=pulses)

    # EXPECTATION: 2 pulses, not 1 with combined text
    assert len(pulses) == 2, f"Expected 2 separate pulses, got {len(pulses)}"
    # Check that each pulse contains only one JSON block
    # Check that each pulse contains the expected text
    assert pulses[0] == '{"status": "one"}'
    assert pulses[1] == '{"status": "two"}'
