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

"""Planner with Memory Agent — plans marathons with route memory database."""

from agents.utils.env import configure_project_env

configure_project_env("planner_memory")

import logging
import os

from a2a.types import AgentSkill
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.genai import types

from agents.planner_with_memory.adk_tools import get_tools
from agents.planner_with_memory.prompts import PLANNER_WITH_MEMORY
from agents.planner_with_memory.services.memory_manager import auto_save_memories
from agents.utils import config
from agents.utils.communication_plugin import SimulationCommunicationPlugin
from agents.utils.retry import resilient_model
from agents.utils.deployment import create_a2a_deployment
from agents.utils.factory import create_simulation_runner

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AGENT_NAME = "planner_with_memory"
MODEL = os.getenv("PLANNER_MODEL", "gemini-3-flash-preview")

planner_config = types.GenerateContentConfig(
    max_output_tokens=8192,
    temperature=0.2,
)
if "pro" in MODEL:
    planner_config.thinking_config = types.ThinkingConfig(thinking_budget=1024)


# [START planner_memory_agent]
def get_agent():
    """Entry point for the ADK framework."""
    return LlmAgent(
        name=AGENT_NAME,
        model=resilient_model(MODEL),
        description=(
            "An autonomous AI agent responsible for planning marathon events. "
            "It actively routes and schedules races, coordinates with logistics vendors, "
            "evaluates generated plans using a specialized LLM-as-Judge evaluator, "
            "and persists routes in a memory database for cross-session recall."
        ),
        static_instruction=PLANNER_WITH_MEMORY.build(),
        tools=get_tools(),
        generate_content_config=planner_config,
        # No before_model_callback: the secure-financial-modeling skill
        # handles refusals via validate_and_emit_a2ui (A2UI card).
        # A programmatic guardrail would short-circuit the LLM before
        # it can emit the A2UI refusal card.
        after_agent_callback=[auto_save_memories],
    )


# [END planner_memory_agent]


root_agent = get_agent()

_runner_app: "App | None" = None


def _get_runner():
    global _runner_app
    runner, app, _ = create_simulation_runner(
        name=AGENT_NAME,
        root_agent=root_agent,
        extra_plugins=[SimulationCommunicationPlugin()],
    )
    _runner_app = app
    return runner


# --- A2A Deployment ---
app = App(name=AGENT_NAME, root_agent=root_agent)


planner_skills = [
    AgentSkill(
        id="plan_evaluate_and_remember_marathon",
        name="Plan, Evaluate, and Remember Marathon",
        description=(
            "Plans a detailed marathon event, evaluates its quality, and "
            "persists the route in a memory database for future recall and "
            "comparison across sessions."
        ),
        tags=["planning", "evaluation", "memory", "marathon"],
        examples=[
            "Plan a scenic marathon in Las Vegas for 10,000 runners",
            "Recall the best route we planned for Chicago",
        ],
    ),
]

planner_a2a_agent, agent_card = create_a2a_deployment(
    name=AGENT_NAME,
    app_or_agent=app,
    agent_getter=get_agent,
    skills=planner_skills,
)

if __name__ == "__main__":
    from agents.utils.serve import create_agent_app, serve_agent

    config.load_env()
    port = int(config.optional("PORT", config.optional("PLANNER_WITH_MEMORY_PORT", "8209")))
    logger.info(f"Starting {AGENT_NAME} agent server on port {port}")

    _runner = _get_runner()

    api_app = create_agent_app(
        name=AGENT_NAME,
        agents_dir="agents",
        adk_app=_runner_app,
        agent_card=agent_card,
        simulation_runner=_runner,
    )
    serve_agent(api_app, port=port)
