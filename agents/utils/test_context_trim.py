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

"""Tests for trimming bulky route GeoJSON out of the model context.

report_marathon_route returns the full route GeoJSON so the frontend can draw
the 3D course. ADK keeps that tool result in the conversation, so it is re-sent
to the model on every subsequent turn -- measured at ~200s per planner turn,
even warm. The model never needs the geometry (every backend consumer reads it
from session state), so we strip it from the request before each model call.
"""

from types import SimpleNamespace

from google.genai import types


def _req_with_route(num_points: int = 5000):
    geo = {
        "type": "FeatureCollection",
        "features": [{"geometry": {"type": "LineString", "coordinates": [[float(i), float(i)] for i in range(num_points)]}}],
    }
    part = types.Part(
        function_response=types.FunctionResponse(
            name="report_marathon_route",
            response={"status": "success", "message": "route summary text", "route_geojson": geo},
        )
    )
    content = types.Content(role="user", parts=[part])
    return SimpleNamespace(contents=[content]), part


def test_trims_route_geojson_to_placeholder():
    from agents.utils.context_trim import trim_route_geojson_from_context

    req, part = _req_with_route()
    out = trim_route_geojson_from_context(None, req)

    assert out is None  # never short-circuits the model call
    resp = part.function_response.response
    assert isinstance(resp["route_geojson"], str), "geojson should be replaced by a placeholder string"
    assert "5000" in resp["route_geojson"], "placeholder should note the point count"


def test_preserves_other_response_fields():
    from agents.utils.context_trim import trim_route_geojson_from_context

    req, part = _req_with_route()
    trim_route_geojson_from_context(None, req)
    resp = part.function_response.response
    assert resp["message"] == "route summary text"
    assert resp["status"] == "success"


def test_leaves_unrelated_tool_responses_untouched():
    from agents.utils.context_trim import trim_route_geojson_from_context

    part = types.Part(
        function_response=types.FunctionResponse(
            name="recall_past_simulations", response={"routes": [1, 2, 3]}
        )
    )
    req = SimpleNamespace(contents=[types.Content(role="user", parts=[part])])
    trim_route_geojson_from_context(None, req)
    assert part.function_response.response["routes"] == [1, 2, 3]


def test_handles_empty_or_missing_contents():
    from agents.utils.context_trim import trim_route_geojson_from_context

    assert trim_route_geojson_from_context(None, SimpleNamespace(contents=[])) is None
    assert trim_route_geojson_from_context(None, SimpleNamespace(contents=None)) is None
