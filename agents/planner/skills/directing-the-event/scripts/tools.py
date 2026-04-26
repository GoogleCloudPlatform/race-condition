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
from typing import Dict, Any, Optional
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


async def plan_marathon_event(event_name: str, city: str, tool_context: Optional[ToolContext] = None) -> Dict[str, Any]:
    """
    Define marathon event characteristics and logistical parameters.

    Args:
        event_name: Name of the marathon event.
        city: City where the marathon is held.
        tool_context: ADK tool context (optional for script execution).

    Returns:
        A dictionary with event characteristics.
    """
    logger.info(f"Planning marathon event: {event_name} in {city}")

    # Persist city in session state for downstream tools (e.g.
    # _auto_store_summary uses state["city"] to tag simulation summaries).
    if tool_context is not None:
        tool_context.state["city"] = city

    return {
        "status": "success",
        "message": f"Marathon event '{event_name}' planned in {city}.",
        "event_name": event_name,
        "city": city,
        "characteristics": {
            "water_stations": "Standard placement every 5km",
            "start_time": "08:00 PM",
            "wave_count": 5,
        },
    }
