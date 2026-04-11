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

import logging
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext
from agents.utils.communication import SimulationA2AClient

logger = logging.getLogger(__name__)

# Registry for non-serializable A2A clients
# Key: invocation_id, Value: SimulationA2AClient
_clients: dict[str, SimulationA2AClient] = {}


def get_client(invocation_id: str) -> SimulationA2AClient:
    """Helper to retrieve the A2A client for a specific invocation."""
    if invocation_id not in _clients:
        logger.debug(f"A2A_PLUGIN: Initializing new client for invocation {invocation_id}")
        _clients[invocation_id] = SimulationA2AClient()
    return _clients[invocation_id]


class SimulationCommunicationPlugin(BasePlugin):
    """ADK Plugin that standardizes A2A client management for simulation agents."""

    def __init__(self, name="communication"):
        super().__init__(name=name)

    async def before_agent_callback(self, *, agent, callback_context: CallbackContext) -> None:
        """Pre-warm the A2A client for the current invocation."""
        iid = callback_context.invocation_id
        get_client(iid)

    async def after_agent_callback(self, *, agent, callback_context: CallbackContext) -> None:
        """Cleanup client after the agent run is complete."""
        iid = callback_context.invocation_id
        client = _clients.pop(iid, None)
        if client:
            logger.debug(f"A2A_PLUGIN: Closing client for invocation {iid}")
            await client.close()
