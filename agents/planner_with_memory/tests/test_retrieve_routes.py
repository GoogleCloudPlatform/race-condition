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

"""Tests for the get_planned_routes_data tool."""

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from agents.planner_with_memory.memory.schemas import PlannedRoute
from agents.planner_with_memory.memory.tools import get_planned_routes_data


class TestGetPlannedRoutesData:
    """Tests for the batch route retrieval tool."""

    @pytest.mark.asyncio
    async def test_returns_multiple_routes_data(self, mock_gcp_services):
        """Tool returns structured route data for multiple IDs."""
        mock_store = mock_gcp_services
        ids = ["id-1", "id-2"]

        route1 = PlannedRoute(
            route_id="id-1",
            route_data={"name": "Strip Classic", "total_distance_miles": 26.2},
            created_at=datetime.now(timezone.utc),
            evaluation_score=0.9,
            evaluation_result={"score": 0.9},
        )
        route2 = PlannedRoute(
            route_id="id-2",
            route_data={"name": "Desert Loop", "total_distance_miles": 13.1},
            created_at=datetime.now(timezone.utc),
            evaluation_score=0.8,
            evaluation_result={"score": 0.8},
        )

        mock_store.get_route.side_effect = [route1, route2]

        mock_ctx = MagicMock()
        result = await get_planned_routes_data(route_ids=ids, tool_context=mock_ctx)

        assert result["status"] == "success"
        assert result["count"] == 2
        assert isinstance(result["routes"], list)
        assert len(result["routes"]) == 2

        r1 = result["routes"][0]
        assert r1["route_id"] == "id-1"
        assert r1["name"] == "Strip Classic"
        assert r1["distance"] == 26.2
        assert r1["evaluation_score"] == 0.9

        r2 = result["routes"][1]
        assert r2["route_id"] == "id-2"
        assert r2["name"] == "Desert Loop"
        assert r2["distance"] == 13.1

    @pytest.mark.asyncio
    async def test_returns_data_when_no_ids_provided(self, mock_gcp_services):
        """Tool fetches recall_routes if no route_ids are given."""
        mock_store = mock_gcp_services

        route1 = PlannedRoute(
            route_id="found",
            route_data={"name": "Test Route"},
            created_at=datetime.now(timezone.utc),
            evaluation_score=0.9,
            evaluation_result={"score": 0.9},
        )

        mock_store.recall_routes.return_value = [route1]

        mock_ctx = MagicMock()
        result = await get_planned_routes_data(route_ids=None, tool_context=mock_ctx, limit=1)

        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["routes"][0]["name"] == "Test Route"
        assert mock_store.recall_routes.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_error_if_no_routes_found(self, mock_gcp_services):
        """Tool returns error if recall finds no routes."""
        mock_store = mock_gcp_services
        mock_store.recall_routes.return_value = []

        mock_ctx = MagicMock()
        result = await get_planned_routes_data(route_ids=None, tool_context=mock_ctx)

        assert result["status"] == "error"
        assert "no routes found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_missing_route_ids_are_filtered(self, mock_gcp_services):
        """Routes that don't exist are silently dropped."""
        mock_store = mock_gcp_services

        route1 = PlannedRoute(
            route_id="exists",
            route_data={"name": "Found"},
            created_at=datetime.now(timezone.utc),
            evaluation_score=0.7,
            evaluation_result={},
        )

        mock_store.get_route.side_effect = [route1, None]

        mock_ctx = MagicMock()
        result = await get_planned_routes_data(route_ids=["exists", "missing"], tool_context=mock_ctx)

        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["routes"][0]["route_id"] == "exists"

    @pytest.mark.asyncio
    async def test_null_score_returns_none(self, mock_gcp_services):
        """Route with no evaluation_score returns None, not a fabricated number."""
        mock_store = mock_gcp_services

        route1 = PlannedRoute(
            route_id="no-score",
            route_data={"name": "Unscored"},
            created_at=datetime.now(timezone.utc),
            evaluation_score=None,
            evaluation_result=None,
        )

        mock_store.recall_routes.return_value = [route1]

        mock_ctx = MagicMock()
        result = await get_planned_routes_data(route_ids=None, tool_context=mock_ctx)

        assert result["routes"][0]["evaluation_score"] is None

    @pytest.mark.asyncio
    async def test_non_dict_route_data_uses_fallbacks(self, mock_gcp_services):
        """Route with non-dict route_data gets fallback name and distance."""
        mock_store = mock_gcp_services

        route1 = PlannedRoute(
            route_id="abcd1234-5678",
            route_data={},  # empty dict triggers fallback for name/distance
            created_at=datetime.now(timezone.utc),
            evaluation_score=0.5,
            evaluation_result={},
        )

        mock_store.recall_routes.return_value = [route1]

        mock_ctx = MagicMock()
        result = await get_planned_routes_data(route_ids=None, tool_context=mock_ctx)

        r = result["routes"][0]
        assert r["name"] == "Route abcd1234"
        assert r["distance"] == "\u2014"
