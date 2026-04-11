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

"""Failing pre-race tools for error handling verification.

Replaces the base simulator's prepare_simulation with a version that
raises RuntimeError to test tool_error callback handling in the
SimulationCommunicationPlugin.
"""

import asyncio
import logging

from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


async def prepare_simulation(
    plan_json: str,
    tool_context: ToolContext,
) -> dict:
    """Parse the plan JSON but fail during simulation setup.

    Simulates an engine failure during the pre-race phase. The failure
    occurs early enough that spawn_runners and the race_engine never run.

    Args:
        plan_json: JSON string with the plan payload from the planner.
        tool_context: ADK tool context for state access.

    Raises:
        RuntimeError: Always raised to test error handling.
    """
    logger.info("prepare_simulation: starting (failure variant)...")
    logger.warning("Simulating processing delay...")

    await asyncio.sleep(3)

    logger.error("Simulation engine failure detected.")
    raise RuntimeError(
        "Simulation engine failure: runner agent coordination timed out "
        "after 3s. The simulation pipeline could not advance past "
        "pre-race setup."
    )
