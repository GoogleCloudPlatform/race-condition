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

"""Deterministic autopilot runner — extends the base runner agent.

Overrides the LLM with a before_model_callback that handles all decisions
deterministically. The model is never called.
"""

from agents.utils.env import configure_project_env

configure_project_env("runner_autopilot")

import logging  # noqa: E402

from google.adk.apps import App  # noqa: E402
from google.genai import types  # noqa: E402

from agents.runner.agent import RUNNER_SUPPRESSED_EVENTS, get_agent as get_base_agent  # noqa: E402
from agents.runner_autopilot.autopilot import autopilot_callback  # noqa: E402
from agents.utils import config  # noqa: E402
from agents.utils.communication_plugin import SimulationCommunicationPlugin  # noqa: E402
from agents.utils.deployment import create_a2a_deployment  # noqa: E402
from agents.utils.factory import create_simulation_runner  # noqa: E402
from agents.utils.plugins import RedisDashLogPlugin  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# [START autopilot_agent]
def get_agent():
    """Create a runner_autopilot agent by extending the base runner."""
    agent = get_base_agent()
    agent.name = "runner_autopilot"
    agent.instruction = "Deterministic autopilot runner."
    agent.before_model_callback = autopilot_callback
    agent.before_agent_callback = None  # Autopilot handles init in callback
    agent.generate_content_config = types.GenerateContentConfig(
        temperature=0.0,
        max_output_tokens=1,
    )
    return agent
# [END autopilot_agent]


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
            suppressed_events=RUNNER_SUPPRESSED_EVENTS,
        ),
        suppress_gateway_emission=True,
    )
    _runner_app = app
    return runner


# --- A2A Deployment ---
# No context cache -- model never runs for autopilot.
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
        agents_dir="agents",
        adk_app=_runner_app,
        agent_card=agent_card,
        simulation_runner=_runner,
    )
    serve_agent(api_app, port=port)
