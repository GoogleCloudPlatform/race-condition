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


if __name__ == "__main__":
    unittest.main()
