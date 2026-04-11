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

"""ADK FunctionTool registry for route memory tools.

Provides :func:`get_memory_tools` which returns all six memory tools
wrapped as :class:`google.adk.tools.FunctionTool` instances, ready for
registration on an ADK agent.
"""

from google.adk.tools.function_tool import FunctionTool

from agents.planner_with_memory.memory.tools import (
    get_best_route,
    get_local_and_traffic_rules,
    get_planned_routes_data,
    get_route,
    recall_past_simulations,
    recall_routes,
    record_simulation,
    store_route,
    store_simulation_summary,
)


def get_memory_tools() -> list[FunctionTool]:
    """Return all 9 memory tools as ADK FunctionTools."""
    return [
        FunctionTool(store_route),
        FunctionTool(record_simulation),
        FunctionTool(recall_routes),
        FunctionTool(get_route),
        FunctionTool(get_best_route),
        FunctionTool(get_local_and_traffic_rules),
        FunctionTool(get_planned_routes_data),
        FunctionTool(store_simulation_summary),
        FunctionTool(recall_past_simulations),
    ]
