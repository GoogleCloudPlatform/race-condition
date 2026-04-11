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

"""ADK tool loader for planner_with_memory.

Combines all inherited planner_with_eval tools with the 6 memory-specific
tools from the memory sub-package.
"""

from agents.planner_with_eval.adk_tools import get_tools as get_eval_tools
from agents.planner_with_memory.memory.adk_tools import get_memory_tools


def get_tools() -> list:
    """Return all tools for the planner_with_memory agent.

    Inherits every tool from planner_with_eval and adds the 6 memory
    tools (store_route, record_simulation, recall_routes, get_route,
    get_best_route, get_local_laws_and_regulations).
    """
    return get_eval_tools() + get_memory_tools()
