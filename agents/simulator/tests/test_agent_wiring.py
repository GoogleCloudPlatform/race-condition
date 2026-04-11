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

"""Wiring tests for the simulator agent.

Validates the LlmAgent router + SequentialAgent pipeline topology:
  LlmAgent("simulator")
    ├── Tool: verify_plan
    └── AgentTool: simulation_pipeline
        └── SequentialAgent("simulation_pipeline")
            ├── LlmAgent("pre_race")
            ├── LoopAgent("race_engine")
            │   └── LlmAgent("tick")
            └── LlmAgent("post_race")
"""

import pytest
from unittest.mock import MagicMock


class TestSimulatorRootAgent:
    """The root agent is an LlmAgent that routes verify vs execute."""

    def test_root_agent_is_llm_agent(self):
        from agents.simulator.agent import root_agent
        from google.adk.agents import LlmAgent

        assert isinstance(root_agent, LlmAgent)
        assert root_agent.name == "simulator"

    def test_app_name_is_simulator(self):
        from agents.simulator.agent import app

        assert app.name == "simulator"

    def test_root_has_verify_plan_tool(self):
        from agents.simulator.agent import root_agent

        tool_names = [getattr(t, "name", None) or getattr(t, "__name__", None) for t in root_agent.tools]
        assert "verify_plan" in tool_names

    def test_root_has_simulation_pipeline_agent_tool(self):
        from agents.simulator.agent import root_agent
        from google.adk.tools.agent_tool import AgentTool

        agent_tools = [t for t in root_agent.tools if isinstance(t, AgentTool)]
        assert len(agent_tools) == 1
        assert agent_tools[0].agent.name == "simulation_pipeline"


class TestSimulationPipeline:
    """The pipeline is a SequentialAgent with pre_race, race_engine, post_race."""

    def test_pipeline_is_sequential(self):
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import SequentialAgent

        assert isinstance(simulation_pipeline, SequentialAgent)
        assert simulation_pipeline.name == "simulation_pipeline"

    def test_pipeline_has_three_sub_agents(self):
        from agents.simulator.agent import simulation_pipeline

        assert len(simulation_pipeline.sub_agents) == 3

    def test_pipeline_sub_agent_names(self):
        from agents.simulator.agent import simulation_pipeline

        names = [a.name for a in simulation_pipeline.sub_agents]
        assert names == ["pre_race", "race_engine", "post_race"]

    def test_pre_race_is_llm_agent(self):
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import LlmAgent

        assert isinstance(simulation_pipeline.sub_agents[0], LlmAgent)

    def test_race_engine_is_loop_agent(self):
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import LoopAgent

        assert isinstance(simulation_pipeline.sub_agents[1], LoopAgent)

    def test_tick_agent_inside_loop(self):
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import LlmAgent

        race_engine = simulation_pipeline.sub_agents[1]
        assert len(race_engine.sub_agents) == 1
        tick = race_engine.sub_agents[0]
        assert isinstance(tick, LlmAgent)
        assert tick.name == "tick"

    def test_tick_agent_uses_lite_model(self):
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import LlmAgent

        tick = simulation_pipeline.sub_agents[1].sub_agents[0]
        assert isinstance(tick, LlmAgent)
        assert "lite" in str(tick.model)

    def test_post_race_is_llm_agent(self):
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import LlmAgent

        assert isinstance(simulation_pipeline.sub_agents[2], LlmAgent)

    def test_pre_race_has_fire_start_gun_tool(self):
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import LlmAgent

        pre_race = simulation_pipeline.sub_agents[0]
        assert isinstance(pre_race, LlmAgent)
        # Tools include both functions and SkillToolset objects
        tool_names = []
        for t in pre_race.tools:
            name = getattr(t, "name", None) or getattr(t, "__name__", None)
            if name:
                tool_names.append(name)
        assert "fire_start_gun" in tool_names


class TestRaceEngineCallback:
    def test_callback_sets_max_iterations_from_state(self):
        from agents.simulator.agent import race_engine, _configure_race_engine

        mock_ctx = MagicMock()
        mock_ctx.state = {"simulation_ready": True, "max_ticks": 6}
        result = _configure_race_engine(mock_ctx)
        assert result is None
        # +1 for the initialization tick (tick 0)
        assert race_engine.max_iterations == 7

    def test_callback_defaults_to_12_ticks(self):
        from agents.simulator.agent import race_engine, _configure_race_engine

        mock_ctx = MagicMock()
        mock_ctx.state = {"simulation_ready": True}
        result = _configure_race_engine(mock_ctx)
        assert result is None
        # DEFAULT_MAX_TICKS (12) + 1 for init tick = 13
        assert race_engine.max_iterations == 13

    def test_callback_returns_content_when_simulation_not_ready(self):
        """When simulation_ready is not set, callback must return Content.

        Returning Content from a before_agent_callback triggers
        ctx.end_invocation = True in ADK's _handle_before_agent_callback,
        which properly skips the race engine. The previous approach of
        setting max_iterations=0 was broken because LoopAgent treats 0
        as unlimited (not 0 == True).
        """
        from agents.simulator.agent import _configure_race_engine
        from google.genai import types

        mock_ctx = MagicMock()
        mock_ctx.state = {"max_ticks": 6}
        result = _configure_race_engine(callback_context=mock_ctx)
        assert isinstance(result, types.Content), (
            f"Expected types.Content to trigger end_invocation, got {type(result)}"
        )

    def test_callback_returns_content_with_empty_state(self):
        """Same as above but with completely empty state."""
        from agents.simulator.agent import _configure_race_engine
        from google.genai import types

        mock_ctx = MagicMock()
        mock_ctx.state = {}
        result = _configure_race_engine(callback_context=mock_ctx)
        assert isinstance(result, types.Content), (
            f"Expected types.Content to trigger end_invocation, got {type(result)}"
        )


class TestTickIncrement:
    """Verify that advance_tick increments current_tick in state."""

    @pytest.mark.asyncio
    async def test_advance_tick_increments_current_tick(self):
        """advance_tick should increment current_tick in state after execution."""
        import importlib.util
        import pathlib

        tools_path = pathlib.Path(__file__).parents[1] / "skills" / "race-tick" / "tools.py"
        spec = importlib.util.spec_from_file_location("race_tick.tools", tools_path)
        assert spec is not None, f"Could not find module spec for {tools_path}"
        assert spec.loader is not None, f"Module spec has no loader for {tools_path}"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        from unittest.mock import AsyncMock, patch

        tc = MagicMock()
        tc.state = {
            "current_tick": 5,
            "max_ticks": 24,
            "simulation_config": {"tick_interval_seconds": 0, "total_race_hours": 6},
            "runner_session_ids": [],
        }
        tc.session = MagicMock()
        tc.session.id = "test-session"

        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=[])

        with patch.object(mod, "RaceCollector") as mock_rc_cls:
            mock_rc_cls.get.return_value = mock_collector
            with patch.object(mod, "asyncio") as mock_asyncio:
                mock_asyncio.sleep = AsyncMock()
                with patch.object(mod, "publish_to_runners", new_callable=AsyncMock):
                    await mod.advance_tick(tool_context=tc)

        assert tc.state["current_tick"] == 6


class TestParallelToolCalls:
    """Verify prompts instruct parallel tool calling where safe."""

    def test_pre_race_instructs_parallel_spawn_and_collector(self):
        from agents.simulator.agent import PRE_RACE_INSTRUCTION

        lower = PRE_RACE_INSTRUCTION.lower()
        assert "same" in lower or "one response" in lower or "simultaneously" in lower or "together" in lower

    def test_pre_race_instructs_separate_responses(self):
        from agents.simulator.agent import PRE_RACE_INSTRUCTION

        lower = PRE_RACE_INSTRUCTION.lower()
        assert "separate responses" in lower or "do not call all tools at once" in lower

    def test_pre_race_keeps_prepare_first(self):
        from agents.simulator.agent import PRE_RACE_INSTRUCTION

        lower = PRE_RACE_INSTRUCTION.lower()
        prep_pos = lower.find("prepare_simulation")
        spawn_pos = lower.find("spawn_runners")
        assert prep_pos < spawn_pos

    def test_pre_race_keeps_fire_last(self):
        from agents.simulator.agent import PRE_RACE_INSTRUCTION

        lower = PRE_RACE_INSTRUCTION.lower()
        fire_pos = lower.find("fire_start_gun")
        spawn_pos = lower.find("spawn_runners")
        collector_pos = lower.find("start_race_collector")
        assert fire_pos > spawn_pos
        assert fire_pos > collector_pos


class TestModelOptimization:
    """Verify deterministic agents use fast models."""

    def test_root_uses_lite_model(self):
        from agents.simulator.agent import root_agent

        assert root_agent.model == "gemini-flash-lite-latest"

    def test_pre_race_uses_lite_model(self):
        from agents.simulator.agent import pre_race_agent

        assert pre_race_agent.model == "gemini-flash-lite-latest"

    def test_post_race_uses_lite_model(self):
        from agents.simulator.agent import post_race_agent

        assert post_race_agent.model == "gemini-flash-lite-latest"

    def test_root_has_low_output_tokens(self):
        """Root agent only passes action + narrative (route/traffic go via Redis).
        Token budget should be small to minimize latency and cost."""
        from agents.simulator.agent import root_agent

        cfg = root_agent.generate_content_config
        assert cfg is not None
        assert cfg.max_output_tokens is not None
        assert cfg.max_output_tokens <= 512

    def test_pre_race_has_low_output_tokens(self):
        from agents.simulator.agent import pre_race_agent

        cfg = pre_race_agent.generate_content_config
        assert cfg is not None
        assert cfg.max_output_tokens is not None
        assert cfg.max_output_tokens <= 512

    def test_post_race_has_low_output_tokens(self):
        from agents.simulator.agent import post_race_agent

        cfg = post_race_agent.generate_content_config
        assert cfg is not None
        assert cfg.max_output_tokens is not None
        assert cfg.max_output_tokens <= 512


class TestVerifyPlan:
    """Test the verify_plan tool directly."""

    @pytest.mark.asyncio
    async def test_verify_valid_plan(self):
        from agents.simulator.agent import verify_plan
        import json

        plan = {
            "action": "verify",
            "narrative": "Las Vegas marathon",
            "route": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                        "properties": {},
                    }
                ],
            },
        }
        result = await verify_plan(json.dumps(plan))
        assert result["status"] == "ready"
        assert result["ready"] is True

    @pytest.mark.asyncio
    async def test_verify_missing_route_still_valid(self):
        """Route is optional in the A2A payload — omitting it is NOT an error.

        Large GeoJSON coordinates are excluded from A2A messages to prevent
        LLM JSON corruption during function-call transport.
        """
        from agents.simulator.agent import verify_plan
        import json

        plan = {"action": "verify", "narrative": "test"}
        result = await verify_plan(json.dumps(plan))
        assert result["status"] == "ready"
        assert result["ready"] is True

    @pytest.mark.asyncio
    async def test_verify_invalid_json(self):
        from agents.simulator.agent import verify_plan

        result = await verify_plan("not json")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_verify_missing_narrative(self):
        from agents.simulator.agent import verify_plan
        import json

        plan = {
            "action": "verify",
            "route": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0]]}, "properties": {}}
                ],
            },
        }
        result = await verify_plan(json.dumps(plan))
        assert result["status"] == "issues_found"
        assert any("narrative" in issue.lower() for issue in result["issues"])


class TestTickInstructionTemplateVariables:
    """Verify tick instruction template variables are optional (defense-in-depth)."""

    def test_tick_instruction_uses_optional_current_tick(self):
        """TICK_INSTRUCTION must use {current_tick?} to avoid KeyError on missing state."""
        from agents.simulator.agent import TICK_INSTRUCTION

        assert "{current_tick?}" in TICK_INSTRUCTION, (
            "TICK_INSTRUCTION must use {current_tick?} (optional) not {current_tick}"
        )

    def test_tick_instruction_uses_optional_max_ticks(self):
        """TICK_INSTRUCTION must use {max_ticks?} to avoid KeyError on missing state."""
        from agents.simulator.agent import TICK_INSTRUCTION

        assert "{max_ticks?}" in TICK_INSTRUCTION, "TICK_INSTRUCTION must use {max_ticks?} (optional) not {max_ticks}"


class TestTickAgentNoDuplicateTools:
    """Verify no duplicate tool names that would cause Gemini API errors."""

    def test_tick_agent_has_no_duplicate_tool_names(self):
        """Duplicate function declarations cause 400 INVALID_ARGUMENT from Gemini."""
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import LlmAgent

        race_engine = simulation_pipeline.sub_agents[1]
        tick_agent = race_engine.sub_agents[0]
        assert isinstance(tick_agent, LlmAgent)
        tool_names = []
        for t in tick_agent.tools:
            name = getattr(t, "name", None) or getattr(t, "__name__", None)
            if name:
                tool_names.append(name)
        duplicates = [n for n in set(tool_names) if tool_names.count(n) > 1]
        assert duplicates == [], f"Duplicate tool names on tick agent: {duplicates}"

    def test_tick_agent_has_no_skillset(self):
        """Tick agent should NOT have a SkillToolset.

        With include_contents='none', SkillToolset's load_skill calls waste
        tokens and confuse the model. The tick agent only needs advance_tick
        and check_race_complete.
        """
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import LlmAgent
        from google.adk.tools.skill_toolset import SkillToolset

        race_engine = simulation_pipeline.sub_agents[1]
        tick_agent = race_engine.sub_agents[0]
        assert isinstance(tick_agent, LlmAgent)
        skillsets = [t for t in tick_agent.tools if isinstance(t, SkillToolset)]
        assert len(skillsets) == 0, f"Tick agent should have no SkillToolset, got {len(skillsets)}"


class TestTrafficIntegratedIntoAdvanceTick:
    """Verify traffic computation is integrated into advance_tick (code-level)."""

    def test_advance_tick_calls_compute_tick_traffic(self):
        """advance_tick should call compute_tick_traffic when traffic_model exists."""
        import inspect
        import importlib.util
        import pathlib

        tools_path = pathlib.Path(__file__).parents[1] / "skills" / "race-tick" / "tools.py"
        spec = importlib.util.spec_from_file_location("race_tick.tools", tools_path)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        source = inspect.getsource(mod.advance_tick)
        assert "compute_tick_traffic" in source
        # Traffic data should be in the return dict, not emitted as a
        # custom gateway message.
        assert "emit_gateway_message" not in source
        assert 'result["traffic"]' in source or 'result["traffic"]' in source

    def test_tick_instruction_is_simple_sequential(self):
        """TICK_INSTRUCTION should be simple sequential (no parallel calls)."""
        from agents.simulator.agent import TICK_INSTRUCTION

        assert "advance_tick" in TICK_INSTRUCTION
        assert "check_race_complete" in TICK_INSTRUCTION
        # Should NOT mention compute_traffic_conditions (it's code-level now)
        assert "compute_traffic_conditions" not in TICK_INSTRUCTION

    def test_tick_agent_does_not_have_traffic_tool(self):
        """compute_traffic_conditions should NOT be an LLM tool (it's code-level)."""
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import LlmAgent

        race_engine = simulation_pipeline.sub_agents[1]
        tick_agent = race_engine.sub_agents[0]
        assert isinstance(tick_agent, LlmAgent)
        tool_names = [getattr(t, "name", None) or getattr(t, "__name__", None) for t in tick_agent.tools]
        assert "compute_traffic_conditions" not in tool_names

    def test_tick_agent_excludes_conversation_history(self):
        """Tick agent must use include_contents='none' to prevent LoopAgent
        history accumulation from bloating context with coordinate data."""
        from agents.simulator.agent import simulation_pipeline
        from google.adk.agents import LlmAgent

        race_engine = simulation_pipeline.sub_agents[1]
        tick_agent = race_engine.sub_agents[0]
        assert isinstance(tick_agent, LlmAgent)
        assert tick_agent.include_contents == "none"


class TestSkillLoaderAcceptsCustomDir:
    """load_skill_tools and load_skill_toolset accept skills_dir override."""

    def test_load_skill_tools_default_uses_simulator_skills(self):
        from agents.simulator.agent import load_skill_tools

        tools = load_skill_tools("pre-race")
        names = [t.__name__ for t in tools]
        assert "prepare_simulation" in names

    def test_load_skill_tools_custom_dir(self, tmp_path):
        from agents.simulator.agent import load_skill_tools

        skill_dir = tmp_path / "custom-skill"
        skill_dir.mkdir()
        (skill_dir / "tools.py").write_text("async def custom_tool() -> dict:\n    return {'status': 'ok'}\n")
        tools = load_skill_tools("custom-skill", skills_dir=str(tmp_path))
        names = [t.__name__ for t in tools]
        assert "custom_tool" in names

    def test_load_skill_toolset_custom_dir(self, tmp_path):
        from agents.simulator.agent import load_skill_toolset

        skill_dir = tmp_path / "custom-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: custom-skill\ndescription: A test skill\n---\n\n# Custom\n")
        (skill_dir / "tools.py").write_text("async def custom_tool() -> dict:\n    return {'status': 'ok'}\n")
        toolset = load_skill_toolset("custom-skill", skills_dir=str(tmp_path))
        assert toolset is not None


class TestGetAgentOverrides:
    """get_agent() accepts name and pre-race tool overrides."""

    def test_default_name_is_simulator(self):
        from agents.simulator.agent import get_agent

        agent = get_agent()
        assert agent.name == "simulator"

    def test_custom_name(self):
        from agents.simulator.agent import get_agent

        agent = get_agent(name="custom_simulator")
        assert agent.name == "custom_simulator"

    def test_override_pre_race_tools(self):
        from agents.simulator.agent import get_agent
        from google.adk.agents import LlmAgent
        from google.adk.tools.agent_tool import AgentTool

        async def fake_prepare(plan_json: str) -> dict:
            return {"status": "error"}

        agent = get_agent(pre_race_tools_override=[fake_prepare])
        # Dig into the pipeline to find pre_race tools
        agent_tool = [t for t in agent.tools if isinstance(t, AgentTool)][0]
        pipeline = agent_tool.agent
        pre_race = pipeline.sub_agents[0]
        assert isinstance(pre_race, LlmAgent)
        tool_names = [getattr(t, "__name__", getattr(t, "name", None)) for t in pre_race.tools]
        assert "fake_prepare" in tool_names

    def test_default_pipeline_unchanged_without_overrides(self):
        from agents.simulator.agent import get_agent, simulation_pipeline
        from google.adk.tools.agent_tool import AgentTool

        agent = get_agent()
        agent_tool = [t for t in agent.tools if isinstance(t, AgentTool)][0]
        assert agent_tool.agent is simulation_pipeline

    def test_override_creates_new_pipeline(self):
        from agents.simulator.agent import get_agent, simulation_pipeline
        from google.adk.tools.agent_tool import AgentTool

        async def fake_prepare(plan_json: str) -> dict:
            return {"status": "error"}

        agent = get_agent(pre_race_tools_override=[fake_prepare])
        agent_tool = [t for t in agent.tools if isinstance(t, AgentTool)][0]
        assert agent_tool.agent is not simulation_pipeline
