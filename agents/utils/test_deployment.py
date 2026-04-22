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

"""Tests for agents.utils.deployment — A2A Deployment Factory."""

from unittest.mock import patch

from google.adk.agents import LlmAgent
from google.adk.apps import App
from a2a.types import TransportProtocol


class TestCreateA2aDeployment:
    def test_card_has_correct_name(self):
        agent = LlmAgent(name="test_agent", model="gemini-3-flash-preview")
        app = App(name="test_agent", root_agent=agent)

        with patch.dict("os.environ", {"TEST_AGENT_URL": "http://localhost:8200"}):
            from agents.utils.deployment import create_a2a_deployment

            a2a_agent, card = create_a2a_deployment(
                name="test_agent",
                app_or_agent=app,
                agent_getter=lambda: agent,
            )
        assert card.name == "test_agent"

    def test_card_transport_is_http_json(self):
        agent = LlmAgent(name="test2", model="gemini-3-flash-preview")
        app = App(name="test2", root_agent=agent)

        with patch.dict("os.environ", {"TEST2_URL": "http://localhost:8200"}):
            from agents.utils.deployment import create_a2a_deployment

            _, card = create_a2a_deployment(
                name="test2",
                app_or_agent=app,
                agent_getter=lambda: agent,
            )
        assert card.preferred_transport == TransportProtocol.http_json
