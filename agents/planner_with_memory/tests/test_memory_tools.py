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

"""Tests for ADK memory tool wrappers.

Tools are now async (backed by AlloyDBRouteStore).  Tests use an in-memory
RouteMemoryStore as the _store backend so no real DB is required.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agents.planner_with_memory.memory.schemas import PlannedRoute, SimulationRecord
from agents.planner_with_memory.memory.tools import _route_to_dict


# ---------------------------------------------------------------------------
# In-memory store stub used by all tests
# ---------------------------------------------------------------------------


class _MemStore:
    """Minimal async-compatible in-memory store for test isolation."""

    def __init__(self):
        self._routes: dict[str, PlannedRoute] = {}

    async def store_route(self, route_data, evaluation_score=None, evaluation_result=None):
        import uuid

        rid = str(uuid.uuid4())
        self._routes[rid] = PlannedRoute(
            route_id=rid,
            route_data=route_data,
            created_at=datetime.now(tz=timezone.utc),
            evaluation_score=evaluation_score,
            evaluation_result=evaluation_result,
        )
        return rid

    async def get_route(self, route_id):
        return self._routes.get(route_id)

    async def record_simulation(self, route_id, simulation_result):
        import uuid

        route = self._routes.get(route_id)
        if route is None:
            return None
        sid = str(uuid.uuid4())
        route.simulations.append(
            SimulationRecord(
                simulation_id=sid,
                route_id=route_id,
                simulation_result=simulation_result,
                simulated_at=datetime.now(tz=timezone.utc),
            )
        )
        return sid

    async def recall_routes(self, count=10, sort_by="recent"):
        routes = list(self._routes.values())
        if sort_by == "best_score":
            routes.sort(
                key=lambda r: (r.evaluation_score is not None, r.evaluation_score or 0),
                reverse=True,
            )
        else:
            routes.sort(key=lambda r: r.created_at, reverse=True)
        return routes[:count]

    async def get_best_route(self):
        scored = [r for r in self._routes.values() if r.evaluation_score is not None]
        if not scored:
            return None
        return max(scored, key=lambda r: r.evaluation_score or 0.0)


@pytest.fixture(autouse=True)
def _mem_store():
    """Swap the module-level _store singleton with an in-memory stub."""
    store = _MemStore()
    with patch("agents.planner_with_memory.memory.tools._store", store):
        yield store


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.state = {}
    return ctx


# ---------------------------------------------------------------------------
# Import tool functions (after patch fixture is set up)
# ---------------------------------------------------------------------------

from agents.planner_with_memory.memory.tools import (  # noqa: E402
    get_best_route,
    get_route,
    recall_routes,
    record_simulation,
    store_route,
)


# ---------------------------------------------------------------------------
# _route_to_dict helper
# ---------------------------------------------------------------------------


class TestRouteToDict:
    @pytest.mark.asyncio
    async def test_converts_planned_route_to_dict(self):
        ctx = _make_ctx()
        result = await store_route(route_data=json.dumps({"distance_km": 42.195}), tool_context=ctx)
        route_id = result["route_id"]
        from agents.planner_with_memory.memory.tools import _store

        route = await _store.get_route(route_id)
        assert route is not None
        d = _route_to_dict(route)
        assert isinstance(d, dict)
        assert d["route_id"] == route_id
        assert d["route_data"] == {"distance_km": 42.195}
        assert isinstance(d["created_at"], str)
        assert d["evaluation_score"] is None
        assert d["simulations"] == []

    @pytest.mark.asyncio
    async def test_serialises_simulations(self):
        ctx = _make_ctx()
        result = await store_route(route_data=json.dumps({"name": "Berlin"}), tool_context=ctx)
        route_id = result["route_id"]
        await record_simulation(route_id=route_id, simulation_result=json.dumps({"passed": True}), tool_context=ctx)
        from agents.planner_with_memory.memory.tools import _store

        route = await _store.get_route(route_id)
        assert route is not None
        d = _route_to_dict(route)
        assert len(d["simulations"]) == 1
        assert d["simulations"][0]["simulation_result"] == {"passed": True}


# ---------------------------------------------------------------------------
# store_route
# ---------------------------------------------------------------------------


class TestStoreRouteTool:
    """Tests for the store_route ADK tool."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        result = await store_route(route_data=json.dumps({"distance_km": 42.195}), tool_context=_make_ctx())
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_success_without_evaluation(self):
        result = await store_route(route_data=json.dumps({"distance_km": 42.195}), tool_context=_make_ctx())
        assert result["status"] == "success"
        assert "route_id" in result
        assert len(result["route_id"]) == 36

    @pytest.mark.asyncio
    async def test_success_with_evaluation(self):
        ctx = _make_ctx()
        eval_result = json.dumps({"overall_score": 88, "notes": "good"})
        result = await store_route(
            route_data=json.dumps({"distance_km": 42.195}),
            tool_context=ctx,
            evaluation_result=eval_result,
        )
        assert result["status"] == "success"
        from agents.planner_with_memory.memory.tools import _store

        route = await _store.get_route(result["route_id"])
        assert route is not None
        assert route.evaluation_score == 88

    @pytest.mark.asyncio
    async def test_evaluation_without_overall_score_key(self):
        ctx = _make_ctx()
        eval_result = json.dumps({"notes": "missing overall_score"})
        result = await store_route(
            route_data=json.dumps({"distance_km": 10.0}),
            tool_context=ctx,
            evaluation_result=eval_result,
        )
        assert result["status"] == "success"
        from agents.planner_with_memory.memory.tools import _store

        route = await _store.get_route(result["route_id"])
        assert route is not None
        assert route.evaluation_score is None

    @pytest.mark.asyncio
    async def test_invalid_json_route_data(self):
        result = await store_route(route_data="not valid json", tool_context=_make_ctx())
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_invalid_json_evaluation_result(self):
        result = await store_route(
            route_data=json.dumps({"distance_km": 10.0}),
            tool_context=_make_ctx(),
            evaluation_result="bad json {{{",
        )
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# record_simulation
# ---------------------------------------------------------------------------


class TestRecordSimulationTool:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        ctx = _make_ctx()
        rd = await store_route(json.dumps({"name": "test"}), ctx)
        result = await record_simulation(
            route_id=rd["route_id"], simulation_result=json.dumps({"ok": True}), tool_context=ctx
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_success(self):
        ctx = _make_ctx()
        rd = await store_route(json.dumps({"name": "test"}), ctx)
        result = await record_simulation(
            route_id=rd["route_id"], simulation_result=json.dumps({"passed": True}), tool_context=ctx
        )
        assert result["status"] == "success"
        assert len(result["simulation_id"]) == 36

    @pytest.mark.asyncio
    async def test_unknown_route_returns_error(self):
        ctx = _make_ctx()
        result = await record_simulation(
            route_id="nonexistent", simulation_result=json.dumps({"ok": False}), tool_context=ctx
        )
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_json_simulation_result(self):
        ctx = _make_ctx()
        rd = await store_route(json.dumps({"name": "test"}), ctx)
        result = await record_simulation(route_id=rd["route_id"], simulation_result="bad", tool_context=ctx)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# recall_routes
# ---------------------------------------------------------------------------


class TestRecallRoutesTool:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        result = await recall_routes(tool_context=_make_ctx())
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_list(self):
        result = await recall_routes(tool_context=_make_ctx())
        assert result["status"] == "success"
        assert result["routes"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_returns_routes_list(self):
        ctx = _make_ctx()
        await store_route(json.dumps({"name": "route1"}), ctx)
        await store_route(json.dumps({"name": "route2"}), ctx)
        result = await recall_routes(tool_context=ctx)
        assert result["status"] == "success"
        assert result["count"] == 2
        for r in result["routes"]:
            assert "route_id" in r and "route_data" in r

    @pytest.mark.asyncio
    async def test_respects_count_param(self):
        ctx = _make_ctx()
        for i in range(5):
            await store_route(json.dumps({"index": i}), ctx)
        result = await recall_routes(tool_context=ctx, count=3)
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_respects_sort_by_param(self):
        ctx = _make_ctx()
        await store_route(json.dumps({"name": "low"}), ctx, evaluation_result=json.dumps({"overall_score": 50}))
        await store_route(json.dumps({"name": "high"}), ctx, evaluation_result=json.dumps({"overall_score": 95}))
        result = await recall_routes(tool_context=ctx, sort_by="best_score")
        assert result["routes"][0]["route_data"]["name"] == "high"


# ---------------------------------------------------------------------------
# get_route
# ---------------------------------------------------------------------------


class TestGetRouteTool:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        result = await get_route(route_id="fake-id", tool_context=_make_ctx())
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_success(self):
        ctx = _make_ctx()
        rd = await store_route(json.dumps({"name": "Berlin"}), ctx)
        result = await get_route(route_id=rd["route_id"], tool_context=ctx)
        assert result["status"] == "success"
        assert result["route"]["route_data"]["name"] == "Berlin"

    @pytest.mark.asyncio
    async def test_not_found(self):
        result = await get_route(route_id="nonexistent", tool_context=_make_ctx())
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()


# ---------------------------------------------------------------------------
# get_best_route
# ---------------------------------------------------------------------------


class TestGetBestRouteTool:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        result = await get_best_route(tool_context=_make_ctx())
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_success(self):
        ctx = _make_ctx()
        await store_route(json.dumps({"name": "low"}), ctx, evaluation_result=json.dumps({"overall_score": 50}))
        await store_route(json.dumps({"name": "high"}), ctx, evaluation_result=json.dumps({"overall_score": 95}))
        result = await get_best_route(tool_context=ctx)
        assert result["status"] == "success"
        assert result["route"]["route_data"]["name"] == "high"
        assert result["route"]["evaluation_score"] == 95

    @pytest.mark.asyncio
    async def test_empty_store_returns_error(self):
        result = await get_best_route(tool_context=_make_ctx())
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_no_scored_routes_returns_error(self):
        ctx = _make_ctx()
        await store_route(json.dumps({"name": "unscored"}), ctx)
        result = await get_best_route(tool_context=ctx)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# A2A compliance
# ---------------------------------------------------------------------------


class TestA2ACompliance:
    @pytest.mark.asyncio
    async def test_store_route_returns_dict(self):
        assert isinstance(await store_route(json.dumps({"x": 1}), _make_ctx()), dict)

    @pytest.mark.asyncio
    async def test_record_simulation_returns_dict(self):
        ctx = _make_ctx()
        rd = await store_route(json.dumps({"x": 1}), ctx)
        assert isinstance(await record_simulation(rd["route_id"], json.dumps({"ok": True}), ctx), dict)

    @pytest.mark.asyncio
    async def test_recall_routes_returns_dict(self):
        assert isinstance(await recall_routes(tool_context=_make_ctx()), dict)

    @pytest.mark.asyncio
    async def test_get_route_returns_dict(self):
        assert isinstance(await get_route("fake", _make_ctx()), dict)

    @pytest.mark.asyncio
    async def test_get_best_route_returns_dict(self):
        assert isinstance(await get_best_route(_make_ctx()), dict)


# ---------------------------------------------------------------------------
# get_route activate_route
# ---------------------------------------------------------------------------


class TestGetRouteActivation:
    @pytest.mark.asyncio
    async def test_activate_route_loads_into_session_state(self):
        ctx = _make_ctx()
        rd = await store_route(json.dumps({"type": "FeatureCollection", "features": []}), ctx)
        result = await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=True)
        assert result["status"] == "success"
        assert result["activated"] is True
        assert ctx.state["marathon_route"] == {"type": "FeatureCollection", "features": []}

    @pytest.mark.asyncio
    async def test_activate_route_false_does_not_set_state(self):
        ctx = _make_ctx()
        rd = await store_route(json.dumps({"type": "FeatureCollection", "features": []}), ctx)
        result = await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=False)
        assert result["status"] == "success"
        assert "activated" not in result
        assert "marathon_route" not in ctx.state

    @pytest.mark.asyncio
    async def test_activate_route_default_is_false(self):
        ctx = _make_ctx()
        rd = await store_route(json.dumps({"name": "test"}), ctx)
        await get_route(route_id=rd["route_id"], tool_context=ctx)
        assert "marathon_route" not in ctx.state

    @pytest.mark.asyncio
    async def test_activate_not_found_returns_error(self):
        ctx = _make_ctx()
        result = await get_route(route_id="nonexistent", tool_context=ctx, activate_route=True)
        assert result["status"] == "error"
        assert "marathon_route" not in ctx.state
