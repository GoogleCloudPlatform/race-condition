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

import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# Simple route GeoJSON with Las Vegas Blvd coords for tests
_TEST_ROUTE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [-115.172851, 36.086141],
                    [-115.172840, 36.090000],
                    [-115.172830, 36.095000],
                    [-115.172820, 36.100000],
                ],
            },
            "properties": {"name": "Las Vegas Blvd"},
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [-115.172820, 36.100000],
                    [-115.180000, 36.100000],
                    [-115.185000, 36.100000],
                ],
            },
            "properties": {"name": "Flamingo Rd"},
        },
    ],
}


def _load_route_tools():
    """Load gis-spatial-engineering tools using importlib (directories use hyphens)."""
    import importlib.util
    import pathlib

    tools_path = pathlib.Path(__file__).parent.parent / "skills" / "gis-spatial-engineering" / "scripts" / "tools.py"
    spec = importlib.util.spec_from_file_location("route_planning.tools", tools_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAssessTrafficImpact:
    """Tests for the assess_traffic_impact ADK tool."""

    @pytest.mark.asyncio
    async def test_returns_error_without_route_in_state(self):
        """When state has no 'marathon_route', returns {'status': 'error'}."""
        module = _load_route_tools()
        mock_ctx = MagicMock()
        mock_ctx.state = {}

        with patch.object(
            module,
            "_gemini_traffic_enrichment",
            new_callable=AsyncMock,
            return_value={"narrative": "mock", "congestion_zones": []},
        ):
            result = await module.assess_traffic_impact(tool_context=mock_ctx)

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_returns_closed_segments(self):
        """With a route in state, returns closed_segments list."""
        module = _load_route_tools()
        mock_ctx = MagicMock()
        mock_ctx.state = {"marathon_route": _TEST_ROUTE_GEOJSON}

        with patch.object(
            module,
            "_gemini_traffic_enrichment",
            new_callable=AsyncMock,
            return_value={"narrative": "mock narrative", "congestion_zones": []},
        ):
            result = await module.assess_traffic_impact(tool_context=mock_ctx)

        assert result["status"] == "success"
        assert "closed_segments" in result
        assert isinstance(result["closed_segments"], list)

    @pytest.mark.asyncio
    async def test_returns_affected_intersections(self):
        """Result contains 'affected_intersections' list."""
        module = _load_route_tools()
        mock_ctx = MagicMock()
        mock_ctx.state = {"marathon_route": _TEST_ROUTE_GEOJSON}

        with patch.object(
            module,
            "_gemini_traffic_enrichment",
            new_callable=AsyncMock,
            return_value={"narrative": "mock narrative", "congestion_zones": []},
        ):
            result = await module.assess_traffic_impact(tool_context=mock_ctx)

        assert "affected_intersections" in result
        assert isinstance(result["affected_intersections"], list)

    @pytest.mark.asyncio
    async def test_stores_assessment_in_state(self):
        """After calling, tool_context.state['traffic_assessment'] is set."""
        module = _load_route_tools()
        mock_ctx = MagicMock()
        mock_ctx.state = {"marathon_route": _TEST_ROUTE_GEOJSON}

        with patch.object(
            module,
            "_gemini_traffic_enrichment",
            new_callable=AsyncMock,
            return_value={"narrative": "mock narrative", "congestion_zones": []},
        ):
            await module.assess_traffic_impact(tool_context=mock_ctx)

        assert "traffic_assessment" in mock_ctx.state
        assert mock_ctx.state["traffic_assessment"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_graceful_when_gemini_fails(self):
        """When Gemini raises an Exception, tool returns success with fallback narrative."""
        module = _load_route_tools()
        mock_ctx = MagicMock()
        mock_ctx.state = {"marathon_route": _TEST_ROUTE_GEOJSON}

        with patch.object(
            module,
            "_gemini_traffic_enrichment",
            new_callable=AsyncMock,
            side_effect=Exception("API quota exceeded"),
        ):
            result = await module.assess_traffic_impact(tool_context=mock_ctx)

        assert result["status"] == "success"
        assert result["narrative"].startswith("Gemini enrichment unavailable")


class TestAssessTrafficImpactSignature:
    """Verify assess_traffic_impact reads exclusively from session state."""

    def test_no_route_geojson_parameter(self):
        """assess_traffic_impact must NOT accept a route_geojson parameter."""
        module = _load_route_tools()
        sig = inspect.signature(module.assess_traffic_impact)
        assert "route_geojson" not in sig.parameters, (
            "assess_traffic_impact should read from session state, not accept route_geojson"
        )

    def test_tool_context_is_required(self):
        """tool_context must be a required parameter (no default)."""
        module = _load_route_tools()
        sig = inspect.signature(module.assess_traffic_impact)
        param = sig.parameters["tool_context"]
        assert param.default is inspect.Parameter.empty, "tool_context should be required (no default value)"


class TestReportMarathonRoute:
    """Tests for the report_marathon_route ADK tool."""

    def test_no_route_geojson_parameter(self):
        """report_marathon_route must NOT accept a route_geojson parameter."""
        module = _load_route_tools()
        sig = inspect.signature(module.report_marathon_route)
        assert "route_geojson" not in sig.parameters, (
            "report_marathon_route should read from session state, not accept route_geojson"
        )

    def test_tool_context_is_required(self):
        """tool_context must be a required parameter (no default)."""
        module = _load_route_tools()
        sig = inspect.signature(module.report_marathon_route)
        param = sig.parameters["tool_context"]
        assert param.default is inspect.Parameter.empty, "tool_context should be required (no default value)"

    @pytest.mark.asyncio
    async def test_returns_error_without_route_in_state(self):
        """When state has no 'marathon_route', returns error."""
        module = _load_route_tools()
        mock_ctx = MagicMock()
        mock_ctx.state = {}

        result = await module.report_marathon_route(tool_context=mock_ctx)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_returns_success_with_route_in_state(self):
        """When state has 'marathon_route', returns success with route_geojson."""
        module = _load_route_tools()
        mock_ctx = MagicMock()
        mock_ctx.state = {"marathon_route": _TEST_ROUTE_GEOJSON}

        result = await module.report_marathon_route(tool_context=mock_ctx)
        assert result["status"] == "success"
        assert result["route_geojson"] == _TEST_ROUTE_GEOJSON


class TestToolRegistration:
    """Tests for tool registration in the planner's get_tools()."""

    def test_assess_traffic_impact_not_in_base_planner(self):
        """assess_traffic_impact must NOT be in the base planner (only planner_with_eval)."""
        from google.adk.tools.skill_toolset import SkillToolset
        from agents.planner.adk_tools import get_tools

        tools = get_tools()
        tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]
        assert "assess_traffic_impact" not in tool_names

        st = [t for t in tools if isinstance(t, SkillToolset)][0]
        assert "assess_traffic_impact" not in st._provided_tools_by_name
