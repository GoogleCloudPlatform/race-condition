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
import os
from typing import Optional
from google.adk.plugins.base_plugin import BasePlugin
from agents.utils.dispatcher import RedisOrchestratorDispatcher

logger = logging.getLogger(__name__)


class SimulationNetworkPlugin(BasePlugin):
    """ADK Plugin that manages the RedisOrchestratorDispatcher lifecycle."""

    def __init__(self, name="simulation_network"):
        super().__init__(name=name)
        self.runner = None
        self.dispatcher: Optional[RedisOrchestratorDispatcher] = None

    def set_runner(self, runner):
        """Sets the Runner instance for the dispatcher and starts the background listener."""
        if self.dispatcher:
            logger.error(f"ORCHESTRATION_LIFECYCLE: Resetting existing dispatcher for {self.name}")
            self.dispatcher.stop()

        self.runner = runner
        dispatch_mode = os.getenv("DISPATCH_MODE", "subscriber")
        self.dispatcher = RedisOrchestratorDispatcher(runner=runner, dispatch_mode=dispatch_mode)
        self.dispatcher.start()

    async def close(self):
        """Stops the background listener when the plugin is closed."""
        if self.dispatcher:
            self.dispatcher.stop()
        await super().close()
