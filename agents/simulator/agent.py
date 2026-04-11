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

"""Simulator Agent — LlmAgent router with SequentialAgent simulation pipeline.

Architecture:
  LlmAgent("simulator")             <- root, receives A2A messages, routes
    ├── Tool: verify_plan            <- validates plan readiness (cheap)
    ├── Tool: call_agent             <- A2A communication
    └── AgentTool: simulation_pipeline <- runs the full simulation (expensive)
        └── SequentialAgent("simulation_pipeline")
            ├── LlmAgent("pre_race")   <- parse plan, spawn runners, start collector
            ├── LoopAgent("race_engine") <- tick loop with dynamic max_iterations
            │   └── LlmAgent("tick")    <- advance_tick + check_race_complete
            └── LlmAgent("post_race")  <- compile results, stop collector
"""

from agents.utils.env import configure_project_env

configure_project_env("simulator")

import importlib.util
import inspect
import json
import logging
import os
from typing import Callable, List, cast

from a2a.types import AgentSkill

from agents.simulator.pre_race_callback import pre_race_callback
from agents.simulator.tick_callback import tick_callback
from agents.utils.sim_defaults import DEFAULT_DURATION_SECONDS, DEFAULT_MAX_TICKS, DEFAULT_TICK_INTERVAL_SECONDS
from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.apps import App
from google.adk.skills import load_skill_from_dir
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import types

from agents.utils import config
from agents.utils.communication_plugin import SimulationCommunicationPlugin
from agents.utils.deployment import create_a2a_deployment
from agents.utils.factory import create_simulation_runner

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AGENT_DIR = os.path.dirname(__file__)


# ---------------------------------------------------------------------------
# Skill / Tool loading helpers (per sub-agent)
# ---------------------------------------------------------------------------


def load_skill_tools(skill_name: str, skills_dir: str | None = None) -> List[Callable]:
    """Load tool functions from a skill's tools.py using importlib.

    Args:
        skill_name: Name of the skill subdirectory (e.g. "pre-race").
        skills_dir: Base directory containing skill subdirectories.
            Defaults to this agent's skills/ directory.
    """
    _base = skills_dir or os.path.join(AGENT_DIR, "skills")
    skill_path = os.path.join(_base, skill_name, "tools.py")
    skill_id = skill_name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(f"{skill_id}.tools", skill_path)
    assert spec is not None, f"Could not find module spec for {skill_path}"
    assert spec.loader is not None, f"Module spec has no loader for {skill_path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [
        obj
        for name, obj in inspect.getmembers(module)
        if inspect.isfunction(obj) and not name.startswith("_") and obj.__module__ == f"{skill_id}.tools"
    ]


def load_skill_toolset(skill_name: str, skills_dir: str | None = None) -> SkillToolset:
    """Load a SKILL.md directory as a SkillToolset for an LlmAgent.

    Args:
        skill_name: Name of the skill subdirectory (e.g. "pre-race").
        skills_dir: Base directory containing skill subdirectories.
            Defaults to this agent's skills/ directory.
    """
    _base = skills_dir or os.path.join(AGENT_DIR, "skills")
    skill_dir = os.path.join(_base, skill_name)
    skill = load_skill_from_dir(skill_dir)
    return SkillToolset(skills=[skill])


# ---------------------------------------------------------------------------
# Load tools and skill toolsets per pipeline sub-agent
# ---------------------------------------------------------------------------

pre_race_tools = load_skill_tools("pre-race")
pre_race_skillset = load_skill_toolset("pre-race")

tick_tools = load_skill_tools("race-tick")
tick_skillset = load_skill_toolset("race-tick")
# NOTE: compute_traffic_conditions is called directly inside advance_tick
# (code-level), not as a separate LLM tool. gemini-flash-lite cannot
# reliably emit parallel function calls with zero thinking budget.

post_race_tools = load_skill_tools("post-race")
post_race_skillset = load_skill_toolset("post-race")


# ---------------------------------------------------------------------------
# Verify tool (lightweight, no simulation)
# ---------------------------------------------------------------------------


async def verify_plan(plan_json: str) -> dict:
    """Validate that a marathon plan is ready for simulation.

    Checks that the plan JSON contains the required fields (route, narrative)
    without actually running a simulation. This is a cheap, safe operation.

    Args:
        plan_json: JSON string with the plan payload from the planner.

    Returns:
        dict with verification status and any issues found.
    """
    try:
        plan = json.loads(plan_json)
    except (json.JSONDecodeError, TypeError) as e:
        return {"status": "error", "message": f"Invalid plan JSON: {e}"}

    issues = []

    # Route is included in the A2A payload for traffic model building.
    # Validate its structure if present.
    route = plan.get("route")
    if route:
        features = route.get("features", [])
        if not features:
            issues.append("Route has no features.")
        line_features = [f for f in features if f.get("geometry", {}).get("type") in ("LineString", "MultiLineString")]
        if not line_features:
            issues.append("Route has no LineString geometry — no path to run.")

    if not plan.get("narrative"):
        issues.append("Missing 'narrative' field — no plan summary.")

    if issues:
        return {
            "status": "issues_found",
            "message": f"Plan has {len(issues)} issue(s) to resolve before simulation.",
            "issues": issues,
            "ready": False,
        }

    # Check optional simulation_config
    sim_config = plan.get("simulation_config", {})
    config_summary = {
        "duration_seconds": sim_config.get("duration_seconds", f"default ({DEFAULT_DURATION_SECONDS})"),
        "tick_interval_seconds": sim_config.get(
            "tick_interval_seconds",
            f"default ({DEFAULT_TICK_INTERVAL_SECONDS})",
        ),
        "runner_count": sim_config.get("runner_count", "default (10)"),
    }

    return {
        "status": "ready",
        "message": "Plan is valid and ready for simulation.",
        "ready": True,
        "simulation_config": config_summary,
    }


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

SIMULATOR_INSTRUCTION = """\
You are the Marathon Simulator. Route requests by the JSON "action" field.

- action="verify": Call `verify_plan` with the full message. Return result.
- action="execute": Call `simulation_pipeline` with the full message.
  Copy the COMPLETE JSON unchanged — the pipeline needs all fields.
- If unclear, default to verify_plan.

Call exactly ONE tool per request. Pass raw JSON through unchanged.
"""

PRE_RACE_INSTRUCTION = """\
You are the pre-race setup agent for the marathon simulator.

The incoming message is a JSON string from the planner containing the plan,
route GeoJSON, traffic assessment, and simulation config.

IMPORTANT: These steps require SEPARATE responses. Do NOT call all tools at once.

Response 1: Call ONLY `prepare_simulation` with the ENTIRE incoming message as
`plan_json`. Pass it as-is. Do NOT call any other tool in this response.

Response 2 (after prepare_simulation returns): Call `spawn_runners` AND
`start_race_collector` together in ONE response. Use state["runner_count"]
for the count (default 10). These two are independent and run simultaneously.

Response 3 (after both return): Call `fire_start_gun` to start the race.

Rules:
- prepare_simulation MUST complete before spawn_runners or start_race_collector.
- Do NOT call any tool more than once.
- Do NOT call call_agent.
"""

TICK_INSTRUCTION = """\
Each tick: call `advance_tick`, then `check_race_complete`, then STOP.
Do NOT call advance_tick more than once. The outer loop handles repetition.
Current tick: {current_tick?} of {max_ticks?}.
"""

POST_RACE_INSTRUCTION = """\
Call `compile_results` first, then `stop_race_collector`. Summarize findings.
"""


# ---------------------------------------------------------------------------
# Pipeline sub-agents
# ---------------------------------------------------------------------------

pre_race_agent = LlmAgent(
    name="pre_race",
    # Model is required by LlmAgent but never called — pre_race_callback
    # intercepts every invocation and returns deterministic tool calls.
    model="gemini-flash-lite-latest",
    instruction=PRE_RACE_INSTRUCTION,
    tools=cast(list, pre_race_tools + [pre_race_skillset]),
    before_model_callback=pre_race_callback,
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        max_output_tokens=512,
    ),
)

tick_agent = LlmAgent(
    name="tick",
    # Model is required by LlmAgent but never called — tick_callback
    # intercepts every invocation and returns deterministic tool calls.
    model="gemini-flash-lite-latest",
    instruction=TICK_INSTRUCTION,
    include_contents="none",
    tools=cast(list, tick_tools),
    before_model_callback=tick_callback,
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        max_output_tokens=256,
    ),
)


# Note: current_tick is incremented inside advance_tick itself,
# not via a before_agent_callback. This ensures the tick advances
# even if the LLM calls advance_tick multiple times in one turn.

race_engine = LoopAgent(
    name="race_engine",
    max_iterations=200,
    sub_agents=[tick_agent],
)


def _configure_race_engine(callback_context):
    """Set max_iterations from session state. Skip race if pre_race failed.

    Returns ``types.Content`` when ``simulation_ready`` is not set, which
    causes ADK's ``_handle_before_agent_callback`` to set
    ``ctx.end_invocation = True`` — properly skipping the race engine.

    NOTE: The previous approach of setting ``max_iterations = 0`` was broken
    because ``LoopAgent``'s loop condition is
    ``not self.max_iterations or times_looped < self.max_iterations``.
    ``not 0`` evaluates to ``True``, so the loop ran *indefinitely* instead
    of being skipped.
    """
    if not callback_context.state.get("simulation_ready"):
        logger.warning("race_engine: simulation_ready not set, skipping race")
        return types.Content(
            role="model",
            parts=[types.Part.from_text(text="Race skipped: pre-race setup did not complete.")],
        )
    max_ticks = callback_context.state.get("max_ticks", DEFAULT_MAX_TICKS)
    # +1 for the initialization tick (tick 0, minutes_per_tick=0)
    race_engine.max_iterations = max_ticks + 1
    return None


race_engine.before_agent_callback = _configure_race_engine

post_race_agent = LlmAgent(
    name="post_race",
    model="gemini-flash-lite-latest",
    instruction=POST_RACE_INSTRUCTION,
    tools=cast(list, post_race_tools + [post_race_skillset]),
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        max_output_tokens=512,
    ),
)


# ---------------------------------------------------------------------------
# Simulation pipeline (SequentialAgent wrapped as AgentTool)
# ---------------------------------------------------------------------------

simulation_pipeline = SequentialAgent(
    name="simulation_pipeline",
    description=(
        "Run a full marathon simulation. Accepts a JSON plan string with "
        "action, narrative, route, and optional simulation_config. Executes "
        "pre-race setup, race tick loop, and post-race analysis in sequence."
    ),
    sub_agents=[pre_race_agent, race_engine, post_race_agent],
)


# ---------------------------------------------------------------------------
# Root agent (LlmAgent router)
# ---------------------------------------------------------------------------


async def _capture_root_simulation_id(callback_context):
    """Capture simulation_id from the session for sub-agent propagation.

    The planner passes simulator_session_id as this agent's session.id via
    call_agent(session_id=...).  Storing it in state BEFORE the pipeline
    runs ensures all sub-agents (pre_race, tick, post_race) use the same
    ID — even though AgentTool may change session.id for the sub-invocation.

    Route GeoJSON and traffic assessment are now passed via Redis
    side-channel (see agents.utils.simdata), so this callback no longer
    needs to extract them from the incoming A2A message.
    """
    if "simulation_id" not in callback_context.state:
        session_id = str(callback_context.session.id)
        from agents.utils.simulation_registry import get_context_id

        original_id = await get_context_id(session_id)
        callback_context.state["simulation_id"] = original_id or session_id
    return None


def _build_custom_pipeline(
    custom_pre_race_tools: List[Callable],
    custom_pre_race_skillset: SkillToolset,
) -> SequentialAgent:
    """Build a simulation pipeline with custom pre-race tools.

    Creates fresh agent instances so the module-level defaults are not
    mutated.  The race_engine callback is a closure over the local
    LoopAgent so ``max_iterations`` is set on the correct instance.

    IMPORTANT: tick, race_engine, and post_race configuration here must
    stay in sync with the module-level agents defined above (lines ~240-330).
    Only pre_race tools are parameterized; all other sub-agents mirror the
    defaults.
    """
    _pre_race = LlmAgent(
        name="pre_race",
        model="gemini-flash-lite-latest",
        instruction=PRE_RACE_INSTRUCTION,
        tools=cast(list, custom_pre_race_tools + [custom_pre_race_skillset]),
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=512,
        ),
    )

    _tick = LlmAgent(
        name="tick",
        model="gemini-flash-lite-latest",
        instruction=TICK_INSTRUCTION,
        include_contents="none",
        tools=cast(list, tick_tools),
        before_model_callback=tick_callback,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=256,
        ),
    )

    _engine = LoopAgent(
        name="race_engine",
        max_iterations=200,
        sub_agents=[_tick],
    )

    def _configure_engine(callback_context):
        if not callback_context.state.get("simulation_ready"):
            logger.warning("race_engine: simulation_ready not set, skipping race")
            return types.Content(
                role="model",
                parts=[types.Part.from_text(text="Race skipped: pre-race setup did not complete.")],
            )
        max_ticks = callback_context.state.get("max_ticks", DEFAULT_MAX_TICKS)
        _engine.max_iterations = max_ticks
        return None

    _engine.before_agent_callback = _configure_engine

    _post_race = LlmAgent(
        name="post_race",
        model="gemini-flash-lite-latest",
        instruction=POST_RACE_INSTRUCTION,
        tools=cast(list, post_race_tools + [post_race_skillset]),
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=512,
        ),
    )

    return SequentialAgent(
        name="simulation_pipeline",
        description=(
            "Run a full marathon simulation. Accepts a JSON plan string with "
            "action, narrative, route, and optional simulation_config. Executes "
            "pre-race setup, race tick loop, and post-race analysis in sequence."
        ),
        sub_agents=[_pre_race, _engine, _post_race],
    )


def get_agent(
    name: str = "simulator",
    pre_race_tools_override: list | None = None,
    pre_race_skillset_override: SkillToolset | None = None,
):
    """Entry point for the ADK framework.

    Args:
        name: Agent name. Defaults to "simulator".
        pre_race_tools_override: If provided, replaces the default pre-race
            tool functions in the simulation pipeline.
        pre_race_skillset_override: If provided, replaces the default
            pre-race SkillToolset in the simulation pipeline.
    """
    if pre_race_tools_override is not None or pre_race_skillset_override is not None:
        pipeline = _build_custom_pipeline(
            custom_pre_race_tools=(pre_race_tools_override if pre_race_tools_override is not None else pre_race_tools),
            custom_pre_race_skillset=(
                pre_race_skillset_override if pre_race_skillset_override is not None else pre_race_skillset
            ),
        )
    else:
        pipeline = simulation_pipeline

    return LlmAgent(
        name=name,
        model="gemini-flash-lite-latest",
        description="Marathon simulation agent. Verifies plans or runs full simulations.",
        instruction=SIMULATOR_INSTRUCTION,
        tools=[
            verify_plan,
            AgentTool(agent=pipeline, skip_summarization=True),
        ],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=256,
        ),
        before_agent_callback=_capture_root_simulation_id,
    )


root_agent = get_agent()


# ---------------------------------------------------------------------------
# Runner factory
# ---------------------------------------------------------------------------

_runner_app: "App | None" = None


def _get_runner():
    global _runner_app
    runner, app, _ = create_simulation_runner(
        name="simulator",
        root_agent=root_agent,
        extra_plugins=[SimulationCommunicationPlugin()],
    )
    _runner_app = app
    return runner


# ---------------------------------------------------------------------------
# A2A Deployment
# ---------------------------------------------------------------------------

app = App(name="simulator", root_agent=root_agent)

simulator_skills = [
    AgentSkill(
        id="execute_simulation",
        name="Execute Simulation",
        description=(
            "Starts a marathon simulation based on a verified plan, triggering "
            "NPC agent coordination and event generation."
        ),
        tags=["simulation", "execution", "marathon"],
    ),
    AgentSkill(
        id="verify_plan",
        name="Verify Plan",
        description="Validates that a marathon plan is ready for simulation.",
        tags=["verification", "readiness"],
    ),
]

simulator_a2a_agent, agent_card = create_a2a_deployment(
    name="simulator",
    app_or_agent=app,
    agent_getter=get_agent,
    skills=simulator_skills,
)

if __name__ == "__main__":
    from agents.utils.serve import create_agent_app, serve_agent

    config.load_env()
    port = int(config.optional("PORT", config.optional("SIMULATOR_PORT", "8202")))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info(f"Starting simulator agent server on port {port}")

    _runner = _get_runner()

    api_app = create_agent_app(
        name="simulator",
        agents_dir="agents",
        adk_app=_runner_app,
        agent_card=agent_card,
        simulation_runner=_runner,
    )
    serve_agent(api_app, port=port)
