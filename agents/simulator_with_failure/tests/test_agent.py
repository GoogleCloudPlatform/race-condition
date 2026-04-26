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
from unittest.mock import MagicMock

from agents.simulator_with_failure.agent import root_agent, agent_card


class TestFailingPreRaceTools:
    """The failing prepare_simulation tool raises RuntimeError."""

    @pytest.mark.asyncio
    async def test_prepare_simulation_raises_runtime_error(self):
        import importlib.util
        import os

        tools_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "skills",
            "simulating-pre-race-failure",
            "tools.py",
        )
        spec = importlib.util.spec_from_file_location("pre_race.tools", tools_path)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        mock_ctx = MagicMock()
        mock_ctx.state = {}
        with pytest.raises(RuntimeError, match="Internal Server Error"):
            await mod.prepare_simulation(plan_json='{"action":"execute"}', tool_context=mock_ctx)

    @pytest.mark.asyncio
    async def test_prepare_simulation_returns_dict_annotation(self):
        import importlib.util
        import inspect
        import os

        tools_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "skills",
            "simulating-pre-race-failure",
            "tools.py",
        )
        spec = importlib.util.spec_from_file_location("pre_race.tools", tools_path)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        sig = inspect.signature(mod.prepare_simulation)
        assert sig.return_annotation is dict


class TestAgentExistsAndConfigured:
    """Verify simulator_with_failure extends the base simulator correctly."""

    def test_agent_name(self):
        assert root_agent.name == "simulator_with_failure"

    def test_agent_has_verify_plan(self):
        tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in root_agent.tools]
        assert "verify_plan" in tool_names

    def test_agent_has_simulation_pipeline(self):
        from google.adk.tools.agent_tool import AgentTool

        agent_tools = [t for t in root_agent.tools if isinstance(t, AgentTool)]
        assert len(agent_tools) == 1
        pipeline = agent_tools[0].agent
        assert pipeline.name == "simulation_pipeline"

    def test_pipeline_has_three_sub_agents(self):
        from google.adk.tools.agent_tool import AgentTool

        agent_tools = [t for t in root_agent.tools if isinstance(t, AgentTool)]
        pipeline = agent_tools[0].agent
        names = [a.name for a in pipeline.sub_agents]
        assert names == ["pre_race", "race_engine", "post_race"]

    def test_pre_race_uses_failing_tools(self):
        from google.adk.agents import LlmAgent
        from google.adk.tools.agent_tool import AgentTool

        agent_tools = [t for t in root_agent.tools if isinstance(t, AgentTool)]
        pipeline = agent_tools[0].agent
        pre_race = pipeline.sub_agents[0]
        assert isinstance(pre_race, LlmAgent)
        tool_names = [getattr(t, "__name__", getattr(t, "name", None)) for t in pre_race.tools]
        assert "prepare_simulation" in tool_names
        # Should NOT have spawn_runners (only the failing prepare_simulation)
        assert "spawn_runners" not in tool_names

    def test_agent_card(self):
        assert agent_card is not None
        assert agent_card.name == "simulator_with_failure"
        assert "simulation" in agent_card.description.lower()
