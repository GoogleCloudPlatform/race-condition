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

"""Planner Agent — expert GIS analyst for marathon route and event planning."""

from agents.utils.env import configure_project_env

configure_project_env("planner")

import logging
import os

from a2a.types import AgentSkill
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.genai import types

from agents.planner.adk_tools import get_tools
from agents.planner.callbacks import financial_guardrail_callback
from agents.planner.prompts import PLANNER
from agents.utils import config
from agents.utils.communication_plugin import SimulationCommunicationPlugin
from agents.utils.deployment import create_a2a_deployment
from agents.utils.factory import create_simulation_runner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AGENT_DIR = os.path.dirname(__file__)


def get_agent():
    """Entry point for the ADK framework."""
    return LlmAgent(
        name="planner",
        model="gemini-3-flash-preview",
        description="Expert GIS analyst for marathon route and event planning.",
        static_instruction=PLANNER.build(),
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
        ),
        tools=get_tools(),
        before_model_callback=financial_guardrail_callback,
    )


root_agent = get_agent()

_runner_app: "App | None" = None


def _get_runner():
    global _runner_app
    runner, app, _ = create_simulation_runner(
        name="planner",
        root_agent=root_agent,
        extra_plugins=[SimulationCommunicationPlugin()],
    )
    _runner_app = app
    return runner


# --- A2A Deployment ---
app = App(name="planner", root_agent=root_agent)

planner_skills = [
    AgentSkill(
        id="create_simulation_plan",
        name="Create Simulation Plan",
        description=(
            "Creates a detailed simulation plan for a marathon event, including "
            "NPC assignments, event timelines, and scenario parameters."
        ),
        tags=["planning", "simulation", "marathon"],
        examples=[
            "Create a simulation plan for 50 runners on the Berlin course",
            "Plan a marathon simulation with weather disruption events",
        ],
    ),
    AgentSkill(
        id="financial_modeling",
        name="Financial Modeling",
        description=(
            "Provides financial advisory capabilities for the marathon "
            "planning committee. Supports two modes: insecure (shares "
            "percentages and approves budget changes) and secure (refuses "
            "budget changes). Toggled via user messages."
        ),
        tags=["finance", "reporting", "marathon", "security"],
        examples=[
            "What's the budget for the marathon?",
            "Switch to secure financial modeling",
            "Can you increase the catering budget by 20%?",
        ],
    ),
]

planner_a2a_agent, agent_card = create_a2a_deployment(
    name="planner",
    app_or_agent=app,
    agent_getter=get_agent,
    skills=planner_skills,
)

if __name__ == "__main__":
    from agents.utils.serve import create_agent_app, serve_agent

    config.load_env()
    port = int(config.optional("PORT", config.optional("PLANNER_PORT", "8204")))
    logger.info(f"Starting planner agent server on port {port}")

    _runner = _get_runner()

    api_app = create_agent_app(
        name="planner",
        agents_dir="agents",
        adk_app=_runner_app,
        agent_card=agent_card,
        simulation_runner=_runner,
    )
    serve_agent(api_app, port=port)
