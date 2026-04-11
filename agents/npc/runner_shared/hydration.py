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
from google.adk.tools.tool_context import ToolContext

from agents.npc.runner_shared.constants import COLLAPSE_THRESHOLD, EXHAUSTION_THRESHOLD

logger = logging.getLogger(__name__)


async def deplete_water(amount: float, tool_context: ToolContext) -> dict:
    """Deplete the runner's hydration by the given amount.

    Use this to reduce hydration based on distance run, fatigue, or other
    conditions. The agent decides how much to deplete based on the situation.

    Args:
        amount: Amount of hydration to remove (percentage points).
        tool_context: ADK tool context for state management.
    """
    current_water = tool_context.state.get("water", 100.0)
    new_water = max(0.0, current_water - amount)
    tool_context.state["water"] = new_water

    # Track exhaustion and collapse
    exhausted = tool_context.state.get("exhausted", False)
    if new_water < EXHAUSTION_THRESHOLD:
        exhausted = True
    elif new_water >= EXHAUSTION_THRESHOLD:
        exhausted = False
    tool_context.state["exhausted"] = exhausted

    collapsed = tool_context.state.get("collapsed", False)
    if exhausted and new_water < COLLAPSE_THRESHOLD:
        collapsed = True
    tool_context.state["collapsed"] = collapsed

    status = "collapsed" if collapsed else ("exhausted" if exhausted else "success")
    message = f"Hydration depleted by {amount:.1f} to {new_water:.1f}%."
    if collapsed:
        message = f"COLLAPSED! Hydration critically low at {new_water:.1f}%."
    elif exhausted:
        message = f"EXHAUSTED! Hydration dangerously low at {new_water:.1f}%. Find a hydration station!"

    logger.info(f"Runner hydration updated: {message}")
    return {
        "status": status,
        "message": message,
        "water": new_water,
        "exhausted": exhausted,
        "collapsed": collapsed,
    }


async def rehydrate(amount: float, tool_context: ToolContext) -> dict:
    """Rehydrate the runner at a hydration station.

    Use this when entering a hydration station. The agent decides how much
    to rehydrate based on the situation.

    Args:
        amount: Amount of hydration to add (percentage points).
        tool_context: ADK tool context for state management.
    """
    current_water = tool_context.state.get("water", 100.0)
    new_water = min(100.0, current_water + amount)
    tool_context.state["water"] = new_water

    # Reset exhaustion state if hydration is restored above threshold
    if new_water >= EXHAUSTION_THRESHOLD:
        tool_context.state["exhausted"] = False
        tool_context.state["collapsed"] = False

    logger.info(f"Runner rehydrated: {new_water:.1f}%")
    return {
        "status": "success",
        "message": f"Rehydrated from {current_water:.1f}% to {new_water:.1f}%.",
        "water": new_water,
    }
