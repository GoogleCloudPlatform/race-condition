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

"""Planner with Eval Agent — plans marathons with LLM-as-Judge evaluation."""

from agents.utils.env import configure_project_env

configure_project_env("planner_eval")

import logging
import os

from a2a.types import AgentSkill
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.genai import types

from agents.planner.callbacks import financial_guardrail_callback
from agents.planner_with_eval.adk_tools import get_tools
from agents.planner_with_eval.prompts import PLANNER_WITH_EVAL
from agents.utils import config
from agents.utils.communication_plugin import SimulationCommunicationPlugin
from agents.utils.retry import resilient_model
from agents.utils.deployment import create_a2a_deployment
from agents.utils.factory import create_simulation_runner

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AGENT_NAME = "planner_with_eval"
MODEL = os.getenv("PLANNER_MODEL", "gemini-3-flash-preview")

# [START planner_eval_agent]
planner_config = types.GenerateContentConfig(
    max_output_tokens=8192,
    temperature=0.2,
    # gemini-3-flash-preview defaults to dynamic thinking and can emit a
    # thought_signature Part with text=None on terminal turns -- leaving
    # the chat empty. Pin a budget to externalize narrative output.
    # Mirrors agents/planner/agent.py:60-65 (commit 1555150e).
    thinking_config=types.ThinkingConfig(thinking_budget=1024),
)


def get_agent():
    """Entry point for the ADK framework."""
    return LlmAgent(
        name=AGENT_NAME,
        model=resilient_model(MODEL),
        description=(
            "An autonomous AI agent responsible for planning marathon events. "
            "It actively routes and schedules races, coordinates with logistics vendors, "
            "and evaluates generated plans using a specialized LLM-as-Judge evaluator."
        ),
        static_instruction=PLANNER_WITH_EVAL.build(),
        tools=get_tools(),
        generate_content_config=planner_config,
        before_model_callback=financial_guardrail_callback,
    )


# [END planner_eval_agent]


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
        id="plan_and_evaluate_marathon",
        name="Plan and Evaluate Marathon",
        description=(
            "Plans a detailed marathon event and automatically evaluates its "
            "quality across multiple dimensions (safety, logistics, etc.)."
        ),
        tags=["planning", "evaluation", "marathon"],
        examples=[
            "Plan a scenic marathon in Las Vegas for 10,000 runners",
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
    port = int(config.optional("PORT", config.optional("PLANNER_WITH_EVAL_PORT", "8205")))
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
