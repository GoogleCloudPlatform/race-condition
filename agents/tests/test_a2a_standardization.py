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

from google.adk.agents import LlmAgent
from agents.utils.a2a import prepare_simulation_agent


def test_prepare_simulation_agent_a2ui_injection(tmp_path, monkeypatch):
    """Verify that A2UI extension is correctly injected based on agent tags."""
    # Setup mock agent with 'a2ui' tag
    agent = LlmAgent(name="test_agent", instruction="test")
    object.__setattr__(agent, "tags", ["a2ui"])

    # Set the env var so AgentCardBuilder gets a valid rpc_url
    monkeypatch.setenv("TEST_AGENT_URL", "http://test:8080")

    # Call prepare_simulation_agent (now uses AgentCardBuilder exclusively)
    card = prepare_simulation_agent(agent, tmp_path)

    # Assertions
    assert card.capabilities is not None
    assert card.capabilities.streaming is True

    extensions = card.capabilities.extensions
    assert extensions is not None
    a2ui_ext = next((ext for ext in extensions if ext.uri == "a2ui:json/1.0"), None)

    assert a2ui_ext is not None
    assert a2ui_ext.params is not None
    assert a2ui_ext.params.get("supported_catalog_ids") == ["a2ui:standard/1.0"]
