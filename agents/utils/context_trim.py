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

"""Keep bulky route geometry out of the model's context window.

``report_marathon_route`` returns the full route GeoJSON because the frontend
draws the 3D course from that tool result. ADK then retains the tool result in
the conversation, so the geometry is re-sent to the model on every subsequent
turn -- measured at ~200s per planner turn, even on a warm engine, with no API
errors or retries. It's pure input-processing cost.

The model never needs the geometry: ``submit_plan_to_simulator``, the
evaluator, and the dashboard all read the route from session state, and the
frontend already received it in the original tool result. So before each model
call we replace the geometry in prior tool results with a compact placeholder.

This is a ``before_model_callback`` that only MUTATES the outgoing request and
returns ``None`` -- it never returns an ``LlmResponse``, so it does not
short-circuit the LLM (preserving the secure-financial-modeling skill's ability
to emit its A2UI refusal card; see agents/planner_with_memory/agent.py).
"""

import logging

logger = logging.getLogger(__name__)

# Response keys that carry bulky geometry the model doesn't need to re-read.
_GEOMETRY_KEYS = ("route_geojson", "geojson")


def _count_points(geo) -> int:
    """Best-effort coordinate count for the placeholder message."""
    try:
        total = 0
        for feature in geo.get("features", []):
            coords = feature.get("geometry", {}).get("coordinates", [])
            total += len(coords)
        return total
    except AttributeError:
        return 0


def trim_route_geojson_from_context(callback_context, llm_request):
    """before_model_callback: strip route geometry from prior tool results.

    Returns None so the (mutated) request proceeds to the model.
    """
    contents = getattr(llm_request, "contents", None) or []
    for content in contents:
        for part in getattr(content, "parts", None) or []:
            function_response = getattr(part, "function_response", None)
            if function_response is None:
                continue
            response = getattr(function_response, "response", None)
            if not isinstance(response, dict):
                continue
            for key in _GEOMETRY_KEYS:
                value = response.get(key)
                if value is not None and not isinstance(value, str):
                    n = _count_points(value)
                    response[key] = f"[{n} coordinates omitted from context; retained in session state]"
    return None
