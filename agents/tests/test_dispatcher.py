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

import unittest
import json
from unittest.mock import MagicMock
from google.genai import types
from agents.utils.dispatcher import RedisOrchestratorDispatcher


class TestDispatcherRelay(unittest.TestCase):
    def setUp(self):
        self.runner = MagicMock()
        self.runner.app.name = "test_app"
        self.runner.app.root_agent.name = "test_agent"
        self.dispatcher = RedisOrchestratorDispatcher(runner=self.runner, redis_url="redis://localhost:6379")

    def test_prepare_pulse_app_author(self):
        event = MagicMock()
        event.author = "test_app"
        event.content = types.Content(parts=[types.Part(text="App message")])

        payloads = self.dispatcher._prepare_pulses("sess-123", event)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0], "App message")

    def test_prepare_pulse_agent_author(self):
        event = MagicMock()
        event.author = "test_agent"
        event.content = types.Content(parts=[types.Part(text="Agent message")])

        payloads = self.dispatcher._prepare_pulses("sess-123", event)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0], "Agent message")

    def test_prepare_pulse_text_only(self):
        event = MagicMock()
        event.author = "agent"
        event.content = types.Content(role="model", parts=[types.Part(text="Hello world")])

        payloads = self.dispatcher._prepare_pulses("sess-123", event)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0], "Hello world")

    def test_prepare_pulse_a2ui_json(self):
        a2ui_data = {"type": "a2ui-video", "props": {"url": "test.mp4"}}

        # Part with text and part with function response
        event = MagicMock()
        event.author = "tool"

        p1 = types.Part(text="Check this out:")
        p2 = MagicMock(spec=types.Part)
        p2.text = None
        p2.function_response = MagicMock()
        p2.function_response.response = a2ui_data

        event.content = MagicMock()
        event.content.parts = [p1, p2]

        payloads = self.dispatcher._prepare_pulses("sess-123", event)
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0], "Check this out:")
        self.assertEqual(payloads[1], json.dumps(a2ui_data))

    def test_prepare_pulse_generic_json(self):
        generic_data = {"status": "ok", "count": 42}

        event = MagicMock()
        event.author = "tool"

        p1 = MagicMock(spec=types.Part)
        p1.text = None
        p1.function_response = MagicMock()
        p1.function_response.response = generic_data

        event.content = MagicMock()
        event.content.parts = [p1]

        payloads = self.dispatcher._prepare_pulses("sess-123", event)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0], json.dumps(generic_data))

    def test_prepare_pulse_ignore_user_author(self):
        event = MagicMock()
        event.author = "user"
        event.content = types.Content(parts=[types.Part(text="Help")])

        payloads = self.dispatcher._prepare_pulses("sess-123", event)
        self.assertEqual(len(payloads), 0)

    # ─────────────────────────────────────────────────────────────────
    # Mixed-content suppression: when an event has both text and
    # function_call Parts, the text is mid-turn planning narration and
    # MUST NOT be emitted to the chat wire. The terminal turn (text
    # only, no function_calls) still emits cleanly. See
    # docs/plans/2026-04-18-dispatcher-text-suppression-design.md.
    # ─────────────────────────────────────────────────────────────────

    def test_prepare_pulse_mixed_content_suppresses_text(self):
        """Text Part is suppressed when same event has any function_call."""
        event = MagicMock()
        event.author = "test_agent"
        event.content = types.Content(
            role="model",
            parts=[
                types.Part(text="I'll now call the planner."),
                types.Part(
                    function_call=types.FunctionCall(
                        name="report_marathon_route",
                        args={"route_id": "abc"},
                    )
                ),
            ],
        )

        payloads = self.dispatcher._prepare_pulses("sess-mixed", event)

        self.assertEqual(payloads, [])

    def test_prepare_pulse_text_only_terminal_event_emits(self):
        """Text-only event (no function_calls) emits as before."""
        event = MagicMock()
        event.author = "test_agent"
        event.content = types.Content(
            role="model",
            parts=[types.Part(text="Here's your plan: ...")],
        )

        payloads = self.dispatcher._prepare_pulses("sess-terminal", event)

        self.assertEqual(payloads, ["Here's your plan: ..."])

    def test_prepare_pulse_function_response_unchanged(self):
        """Function_response Parts still emit JSON-serialized response."""
        event = MagicMock()
        event.author = "test_agent"
        event.content = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        name="some_tool",
                        response={"foo": "bar"},
                    )
                ),
            ],
        )

        payloads = self.dispatcher._prepare_pulses("sess-funcresp", event)

        self.assertEqual(payloads, [json.dumps({"foo": "bar"})])

    def test_prepare_pulse_multiple_text_parts_in_mixed_event_all_suppressed(self):
        """Every text Part is suppressed when ANY function_call is present."""
        event = MagicMock()
        event.author = "test_agent"
        event.content = types.Content(
            role="model",
            parts=[
                types.Part(text="First mid-turn line."),
                types.Part(text="Second mid-turn line."),
                types.Part(
                    function_call=types.FunctionCall(
                        name="x",
                        args={},
                    )
                ),
            ],
        )

        payloads = self.dispatcher._prepare_pulses("sess-multi-mixed", event)

        self.assertEqual(payloads, [])

    def test_prepare_pulse_multiple_text_parts_text_only_event_all_emit(self):
        """Multiple text Parts in a text-only event all emit, in order."""
        event = MagicMock()
        event.author = "test_agent"
        event.content = types.Content(
            role="model",
            parts=[
                types.Part(text="Plan summary part one."),
                types.Part(text="Plan summary part two."),
            ],
        )

        payloads = self.dispatcher._prepare_pulses("sess-multi-text", event)

        self.assertEqual(payloads, ["Plan summary part one.", "Plan summary part two."])


if __name__ == "__main__":
    unittest.main()
