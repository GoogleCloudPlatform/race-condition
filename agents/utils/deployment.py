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

"""A2A deployment factory — eliminates per-agent deployment boilerplate.

Consolidates the pattern of creating an App for card generation,
calling prepare_simulation_agent(), setting transport/streaming,
building a SimulationExecutor, and wrapping in an A2aAgent.
"""

import logging
from typing import Callable, Optional

from a2a.types import TransportProtocol
from google.adk.agents.base_agent import BaseAgent
from vertexai.preview.reasoning_engines import A2aAgent

from agents.utils.a2a import prepare_simulation_agent
from agents.utils.simulation_executor import SimulationExecutor

logger = logging.getLogger(__name__)


def create_a2a_deployment(
    name: str,
    app_or_agent,
    agent_getter: Callable[[], BaseAgent],
    agents_dir: str = "agents",
    skills: Optional[list] = None,
    streaming: bool = False,
    default_user_id: str = "simulation_user",
) -> tuple:
    """Create A2A deployment artifacts for an agent.

    Generates an AgentCard via prepare_simulation_agent(), configures
    transport settings, builds a SimulationExecutor, and wraps everything
    in a Vertex AI A2aAgent for Agent Engine deployment.

    Args:
        name: Agent name (must match the agent's LlmAgent.name).
        app_or_agent: An App or BaseAgent instance for card generation.
        agent_getter: Zero-arg callable returning a fresh agent instance.
        agents_dir: Base directory for agent discovery.
        skills: Optional list of A2A AgentSkill objects for the card.
        streaming: Whether the agent supports streaming responses.
        default_user_id: Default user ID for simulation sessions.

    Returns:
        (a2a_agent, agent_card) tuple.
    """
    agent_card = prepare_simulation_agent(app_or_agent, agents_dir, skills=skills or [])
    agent_card.preferred_transport = TransportProtocol.http_json
    if agent_card.capabilities:
        agent_card.capabilities.streaming = streaming

    def _executor_builder():
        return SimulationExecutor(
            agent_getter=agent_getter,
            agent_name=name,
            default_user_id=default_user_id,
        )

    a2a_agent = A2aAgent(
        agent_card=agent_card,
        agent_executor_builder=_executor_builder,
    )

    return a2a_agent, agent_card
