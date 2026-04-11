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

"""Tests for n26:dispatch/1.0 extension injection in agent cards."""

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from agents.utils.a2a import prepare_simulation_agent


@pytest.fixture
def test_app():
    """Create a minimal real App for prepare_simulation_agent."""
    agent = LlmAgent(
        name="dispatch_test",
        model="gemini-3-flash-preview",
        description="Test agent for dispatch extension tests.",
        instruction="You are a test agent.",
    )
    return App(name="dispatch_test", root_agent=agent)


def test_dispatch_extension_callable(monkeypatch, test_app):
    """Agent card must contain n26:dispatch/1.0 with mode=callable when env is set."""
    monkeypatch.setenv("DISPATCH_MODE", "callable")
    card = prepare_simulation_agent(test_app, "agents")

    extensions = card.capabilities.extensions or [] if card.capabilities else []
    dispatch_ext = next((e for e in extensions if e.uri == "n26:dispatch/1.0"), None)
    assert dispatch_ext is not None, "n26:dispatch/1.0 extension missing from agent card"
    assert dispatch_ext.params is not None, "dispatch extension params should not be None"
    assert dispatch_ext.params["mode"] == "callable"


def test_dispatch_extension_defaults_to_subscriber(monkeypatch, test_app):
    """Without DISPATCH_MODE env var, agent card defaults to subscriber."""
    monkeypatch.delenv("DISPATCH_MODE", raising=False)
    card = prepare_simulation_agent(test_app, "agents")

    extensions = card.capabilities.extensions or [] if card.capabilities else []
    dispatch_ext = next((e for e in extensions if e.uri == "n26:dispatch/1.0"), None)
    assert dispatch_ext is not None, "n26:dispatch/1.0 extension missing from agent card"
    assert dispatch_ext.params is not None, "dispatch extension params should not be None"
    assert dispatch_ext.params["mode"] == "subscriber"
