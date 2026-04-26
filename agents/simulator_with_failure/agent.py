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

"""Simulator with Failure Agent — extends the base simulator with a failing pre-race.

Reuses the full simulation pipeline (SequentialAgent -> pre_race -> race_engine
-> post_race) from the base simulator, but replaces the pre-race tools with a
version that raises RuntimeError during prepare_simulation. This tests how the
ADK and SimulationCommunicationPlugin handle tool_error callbacks.
"""

from agents.utils.env import configure_project_env

configure_project_env("simulator_fail")

import logging
import os

from a2a.types import AgentSkill
from google.adk.apps import App

from agents.simulator.agent import (
    get_agent,
    load_skill_tools,
    load_skill_toolset,
)
from agents.utils import config
from agents.utils.communication_plugin import SimulationCommunicationPlugin
from agents.utils.deployment import create_a2a_deployment
from agents.utils.factory import create_simulation_runner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AGENT_DIR = os.path.dirname(__file__)
SKILLS_DIR = os.path.join(AGENT_DIR, "skills")

# Load the failing pre-race skill from our local skills directory
failing_pre_race_tools = load_skill_tools("simulating-pre-race-failure", skills_dir=SKILLS_DIR)
failing_pre_race_skillset = load_skill_toolset("simulating-pre-race-failure", skills_dir=SKILLS_DIR)


def get_failure_agent():
    """Build a simulator agent with a failing pre-race phase."""
    return get_agent(
        name="simulator_with_failure",
        pre_race_tools_override=failing_pre_race_tools,
        pre_race_skillset_override=failing_pre_race_skillset,
    )


root_agent = get_failure_agent()

_runner_app: "App | None" = None


def _get_runner():
    global _runner_app
    runner, app, _ = create_simulation_runner(
        name="simulator_with_failure",
        root_agent=root_agent,
        extra_plugins=[SimulationCommunicationPlugin()],
        agent_display_names={"simulator_with_failure": "Simulator"},
    )
    _runner_app = app
    return runner


# --- A2A Deployment ---
app = App(name="simulator_with_failure", root_agent=root_agent)

simulator_fail_skills = [
    AgentSkill(
        id="execute_simulation",
        name="Execute Simulation",
        description=(
            "Starts a marathon simulation that encounters a pre-race failure, "
            "testing error handling and tool_error callbacks."
        ),
        tags=["simulation", "testing", "error-handling"],
    ),
    AgentSkill(
        id="verify_plan",
        name="Verify Plan",
        description="Validates that a marathon plan is ready for simulation.",
        tags=["verification", "readiness"],
    ),
]

simulator_with_failure_a2a_agent, agent_card = create_a2a_deployment(
    name="simulator_with_failure",
    app_or_agent=app,
    agent_getter=get_failure_agent,
    skills=simulator_fail_skills,
)

if __name__ == "__main__":
    from agents.utils.serve import create_agent_app, serve_agent

    config.load_env()
    port = int(config.optional("PORT", config.optional("SIMULATOR_WITH_FAILURE_PORT", "8206")))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info(f"Starting simulator_with_failure agent server on port {port}")

    _runner = _get_runner()

    api_app = create_agent_app(
        name="simulator_with_failure",
        agents_dir="agents",
        adk_app=_runner_app,
        agent_card=agent_card,
        simulation_runner=_runner,
    )
    serve_agent(api_app, port=port)
