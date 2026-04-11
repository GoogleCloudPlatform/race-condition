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

"""Runner Autopilot Agent — deterministic NPC runner using callback interception.

Uses simulation tools (accelerate, brake, hydration) but intercepts every
LLM call via before_model_callback, making all decisions deterministically
without ever invoking the model.
"""

from agents.utils.env import configure_project_env

configure_project_env("runner_autopilot")

import logging  # noqa: E402
import pathlib  # noqa: E402
from typing import cast  # noqa: E402

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.genai import types  # noqa: E402

from agents.npc.runner_autopilot.autopilot import autopilot_callback  # noqa: E402
from agents.utils import config, load_agent_skills  # noqa: E402
from agents.utils.communication_plugin import SimulationCommunicationPlugin  # noqa: E402
from agents.utils.retry import resilient_model  # noqa: E402
from agents.utils.deployment import create_a2a_deployment  # noqa: E402
from agents.utils.factory import create_simulation_runner  # noqa: E402
from agents.utils.plugins import RedisDashLogPlugin  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load tools from the autopilot's own skills directory.
_skills, skill_tools = load_agent_skills(str(pathlib.Path(__file__).parent))


def get_agent():
    """Entry point for the ADK framework."""
    return LlmAgent(
        name="runner_autopilot",
        model=resilient_model("gemini-3.1-flash-lite-preview"),
        description="A deterministic NPC runner that acts on autopilot.",
        instruction="Deterministic autopilot runner.",
        include_contents="none",
        generate_content_config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=1,
        ),
        tools=cast(list, skill_tools),
        before_model_callback=autopilot_callback,
    )


root_agent = get_agent()

_runner_app: "App | None" = None


def _get_runner():
    global _runner_app
    runner, app, _ = create_simulation_runner(
        name="runner_autopilot",
        root_agent=root_agent,
        extra_plugins=[SimulationCommunicationPlugin()],
        dash_log_plugin=RedisDashLogPlugin(
            fire_and_forget=True,
            suppressed_events={"run_start", "model_start", "model_end", "tool_start"},
        ),
    )
    _runner_app = app
    return runner


# --- A2A Deployment ---
app = App(
    name="runner_autopilot",
    root_agent=root_agent,
)

runner_a2a_agent, agent_card = create_a2a_deployment(
    name="runner_autopilot",
    app_or_agent=app,
    agent_getter=get_agent,
)

if __name__ == "__main__":
    from agents.utils.serve import create_agent_app, serve_agent  # noqa: E402

    config.load_env()
    port = int(config.optional("PORT", config.optional("RUNNER_AUTOPILOT_PORT", "8210")))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info(f"Starting runner_autopilot agent server on port {port}")

    _runner = _get_runner()

    api_app = create_agent_app(
        name="runner_autopilot",
        agents_dir="agents/npc",
        adk_app=_runner_app,
        agent_card=agent_card,
        simulation_runner=_runner,
    )
    serve_agent(api_app, port=port)
