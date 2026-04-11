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

"""Agent Factory — eliminates boilerplate across all simulation agents.

Usage:
    from agents.utils.factory import create_simulation_runner

    root_agent = get_agent()  # Your LlmAgent
    runner, app, orchestration_plugin = create_simulation_runner(
        name="runner_autopilot",
        root_agent=root_agent,
    )
"""

import logging
from typing import Optional, List

from google.adk.apps import App
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import Runner

from agents.utils import config
from agents.utils.plugins import RedisDashLogPlugin
from agents.utils.runtime import create_services
from agents.utils.simulation_plugin import SimulationNetworkPlugin

logger = logging.getLogger(__name__)


def create_simulation_runner(
    name: str,
    root_agent,
    extra_plugins: Optional[List[BasePlugin]] = None,
    agent_display_names: dict[str, str] | None = None,
    dash_log_plugin: Optional[RedisDashLogPlugin] = None,
    suppress_gateway_emission: bool = False,
) -> tuple:
    """Create a fully wired simulation Runner with standard plugins.

    Args:
        name: Internal name for the agent/app.
        root_agent: The root LlmAgent instance.
        extra_plugins: Additional plugins to register.
        agent_display_names: Optional mapping of internal agent names to
            display names used in narrative output.
        dash_log_plugin: Optional pre-configured RedisDashLogPlugin.
            When provided, replaces the default plugin (useful for
            fire-and-forget / event suppression on runner agents).
        suppress_gateway_emission: When True, the dispatcher skips
            emitting gateway messages from the ADK event stream.
            Used for runner agents where the collector handles
            aggregation and per-tick messages are noise.

    Returns:
        (runner, app, orchestration_plugin) tuple.
    """
    config.load_env()

    # Standard plugin stack
    orchestration_plugin = SimulationNetworkPlugin(
        name=name,
        suppress_gateway_emission=suppress_gateway_emission,
    )
    telemetry_plugin = dash_log_plugin or RedisDashLogPlugin(agent_display_names=agent_display_names)
    plugins = [telemetry_plugin, orchestration_plugin]
    if extra_plugins:
        plugins.extend(extra_plugins)

    app = App(
        name=name,
        root_agent=root_agent,
        plugins=plugins,
    )

    # Session service selection — delegated to unified runtime abstraction
    services = create_services()
    logger.info("Runtime target: %s", services.target)

    # auto_create_session=True defers session creation to the first
    # run_async() call, eliminating the need for a separate DB round-trip
    # at spawn time. This is both simpler and faster under high concurrency.
    runner = Runner(
        app=app,
        session_service=services.session_service,
        memory_service=services.memory_service,
        auto_create_session=True,
    )

    # Wire orchestration
    orchestration_plugin.set_runner(runner)

    return runner, app, orchestration_plugin
