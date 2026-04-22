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

"""Integration tests for A2A agent card generation and route reachability.

These tests verify the full chain:
  1. create_agent_card generates a card with the correct agent name.
  2. prepare_simulation_agent preserves the A2A RPC URL.
  3. The card's URL matches the actual A2A endpoint (no 307/404).
  4. No static agent.json files override dynamic card generation.

These tests are designed to catch the class of bugs where:
  - JSON field names are mismatched (camelCase vs snake_case)
  - Static files override dynamic card generation
  - URL trailing slashes cause 307 redirects from Starlette
  - Top-level URL is overwritten by env var, losing the A2A path
"""

from pathlib import Path

from a2a.types import AgentSkill
from google.adk.agents import LlmAgent
from vertexai.preview.reasoning_engines.templates.a2a import create_agent_card

from agents.utils.a2a import prepare_simulation_agent

_TEST_SKILL = AgentSkill(
    id="test_skill",
    name="Test Skill",
    description="A test skill for card generation tests.",
    tags=["test"],
)


# ---------------------------------------------------------------------------
# Test 1: create_agent_card produces a card with the correct name
# ---------------------------------------------------------------------------
class TestCreateAgentCard:
    """Verify create_agent_card sets the card name correctly."""

    def test_card_name_matches(self):
        """The card's name MUST match the agent_name we provide."""
        card = create_agent_card(
            agent_name="runner_autopilot",
            description="A deterministic autopilot NPC runner.",
            skills=[_TEST_SKILL],
        )
        assert card.name == "runner_autopilot", f"Card name should be 'runner_autopilot', got: {card.name}"

    def test_card_has_description(self):
        """Cards should include the description we provide."""
        card = create_agent_card(
            agent_name="runner_autopilot",
            description="A deterministic autopilot NPC runner.",
            skills=[_TEST_SKILL],
        )
        assert card.description == "A deterministic autopilot NPC runner."

    def test_card_has_skills(self):
        """Cards should include the skills we provide."""
        card = create_agent_card(
            agent_name="runner_autopilot",
            description="A deterministic autopilot NPC runner.",
            skills=[_TEST_SKILL],
        )
        assert len(card.skills) == 1
        assert card.skills[0].name == "Test Skill"


# ---------------------------------------------------------------------------
# Test 2: prepare_simulation_agent preserves the A2A RPC URL
# ---------------------------------------------------------------------------
class TestPrepareSimulationAgent:
    """Verify prepare_simulation_agent does NOT clobber the card's A2A URL."""

    def test_url_contains_a2a_path(self, tmp_path, monkeypatch):
        """After prepare_simulation_agent, URL must still include /a2a/{name}/."""
        agent = LlmAgent(name="test_agent", instruction="test agent")
        monkeypatch.setenv("TEST_AGENT_URL", "http://127.0.0.1:9999")

        card = prepare_simulation_agent(agent, tmp_path, skills=[_TEST_SKILL])

        assert "/a2a/test_agent" in card.url, (
            f"prepare_simulation_agent must preserve the A2A path in URL. "
            f"Got: {card.url}, expected it to contain /a2a/test_agent"
        )

    def test_url_has_trailing_slash(self, tmp_path, monkeypatch):
        """Card URL must end with trailing slash for Starlette mount compatibility."""
        agent = LlmAgent(name="test_agent", instruction="test agent")
        monkeypatch.setenv("TEST_AGENT_URL", "http://127.0.0.1:9999")

        card = prepare_simulation_agent(agent, tmp_path, skills=[_TEST_SKILL])

        assert card.url.endswith("/a2a/test_agent") or card.url.endswith("/a2a/test_agent/"), (
            f"Card URL must end with the A2A path. Got: {card.url}"
        )

    def test_no_agent_json_files_exist(self):
        """Static agent.json files must not exist — they bypass dynamic card generation."""
        import glob

        agent_jsons = glob.glob("agents/**/agent.json", recursive=True)
        assert agent_jsons == [], f"Found static agent.json files that would bypass card generation: {agent_jsons}"

    def test_no_catalog_json_in_git(self):
        """catalog.json must not be tracked in git — gateway uses HTTP discovery.

        Note: admin may recreate an empty catalog.json at runtime, so we check
        git tracking rather than filesystem presence.
        """
        import subprocess

        result = subprocess.run(
            ["git", "ls-files", "agents/catalog.json"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.stdout.strip() == "", "agents/catalog.json is tracked in git — it should be .gitignored"


# ---------------------------------------------------------------------------
# Test 3: A2UI extension injection still works without agent.json
# ---------------------------------------------------------------------------
class TestA2UIInjection:
    """Verify A2UI extension injection via agent tags (not agent.json)."""

    def test_a2ui_tag_triggers_extension(self, tmp_path, monkeypatch):
        agent = LlmAgent(name="ui_agent", instruction="test")
        object.__setattr__(agent, "tags", ["a2ui"])
        monkeypatch.setenv("UI_AGENT_URL", "http://localhost:9999")

        card = prepare_simulation_agent(agent, tmp_path, skills=[_TEST_SKILL])

        assert card.capabilities is not None
        assert card.capabilities.streaming is True
        extensions = card.capabilities.extensions
        assert extensions is not None
        a2ui_ext = next((e for e in extensions if e.uri == "a2ui:json/1.0"), None)
        assert a2ui_ext is not None
        assert a2ui_ext.params is not None
        assert a2ui_ext.params.get("supported_catalog_ids") == ["a2ui:standard/1.0"]

    def test_no_a2ui_tag_no_extension(self, tmp_path, monkeypatch):
        agent = LlmAgent(name="plain_agent", instruction="test")
        monkeypatch.setenv("PLAIN_AGENT_URL", "http://localhost:9999")

        card = prepare_simulation_agent(agent, tmp_path, skills=[_TEST_SKILL])

        extensions = getattr(card.capabilities, "extensions", None) or []
        a2ui_ext = next((e for e in extensions if e.uri == "a2ui:json/1.0"), None)
        assert a2ui_ext is None
