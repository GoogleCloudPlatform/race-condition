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

NOTE: store_route, record_simulation, and store_simulation_summary are
state-driven (see docs/plans/2026-04-19-state-driven-memory-persistence-...).
Large payloads are passed via session state, not as LLM-supplied JSON.
The ``_store_route_via_state`` and ``_record_simulation_via_state``
helpers below mirror that contract so legacy fixture code reads cleanly.
"""

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
# State-driven helpers
#
# After the state-driven persistence refactor the tools no longer accept
# the route/eval/sim payloads as function arguments.  These helpers stage
# the data in session state then invoke the tool, preserving the legacy
# call ergonomics for the rest of the suite.
# ---------------------------------------------------------------------------


async def _store_route_via_state(
    route_data: dict,
    ctx: MagicMock,
    evaluation_result: dict | None = None,
) -> dict:
    """Stage marathon_route (and optional evaluation_result) in state, then call store_route."""
    from agents.planner_with_memory.memory.tools import store_route as _store_route_tool

    ctx.state["marathon_route"] = route_data
    if evaluation_result is not None:
        ctx.state["evaluation_result"] = evaluation_result
    else:
        ctx.state.pop("evaluation_result", None)
    return await _store_route_tool(tool_context=ctx)


async def _record_simulation_via_state(
    route_id: str,
    simulation_result: dict,
    ctx: MagicMock,
) -> dict:
    """Stage simulation_result in state, then call record_simulation."""
    from agents.planner_with_memory.memory.tools import record_simulation as _record_simulation_tool

    ctx.state["simulation_result"] = simulation_result
    return await _record_simulation_tool(route_id=route_id, tool_context=ctx)


# ---------------------------------------------------------------------------
# Import tool functions (after patch fixture is set up)
# ---------------------------------------------------------------------------

from agents.planner_with_memory.memory.tools import (  # noqa: E402
    get_best_route,
    get_route,
    recall_routes,
)


# ---------------------------------------------------------------------------
# _route_to_dict helper
# ---------------------------------------------------------------------------


class TestRouteToDict:
    @pytest.mark.asyncio
    async def test_converts_planned_route_to_dict(self):
        ctx = _make_ctx()
        result = await _store_route_via_state({"distance_km": 42.195}, ctx)
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
        result = await _store_route_via_state({"name": "Berlin"}, ctx)
        route_id = result["route_id"]
        await _record_simulation_via_state(route_id, {"passed": True}, ctx)
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
    """Tests for the store_route ADK tool (state-driven)."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        result = await _store_route_via_state({"distance_km": 42.195}, _make_ctx())
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_success_without_evaluation(self):
        result = await _store_route_via_state({"distance_km": 42.195}, _make_ctx())
        assert result["status"] == "success"
        assert "route_id" in result
        assert len(result["route_id"]) == 36

    @pytest.mark.asyncio
    async def test_success_with_evaluation(self):
        ctx = _make_ctx()
        result = await _store_route_via_state(
            {"distance_km": 42.195},
            ctx,
            evaluation_result={"overall_score": 88, "notes": "good"},
        )
        assert result["status"] == "success"
        from agents.planner_with_memory.memory.tools import _store

        route = await _store.get_route(result["route_id"])
        assert route is not None
        assert route.evaluation_score == 88

    @pytest.mark.asyncio
    async def test_evaluation_without_overall_score_key(self):
        ctx = _make_ctx()
        result = await _store_route_via_state(
            {"distance_km": 10.0},
            ctx,
            evaluation_result={"notes": "missing overall_score"},
        )
        assert result["status"] == "success"
        from agents.planner_with_memory.memory.tools import _store

        route = await _store.get_route(result["route_id"])
        assert route is not None
        assert route.evaluation_score is None


# ---------------------------------------------------------------------------
# record_simulation
# ---------------------------------------------------------------------------


class TestRecordSimulationTool:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state({"name": "test"}, ctx)
        result = await _record_simulation_via_state(rd["route_id"], {"ok": True}, ctx)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_success(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state({"name": "test"}, ctx)
        result = await _record_simulation_via_state(rd["route_id"], {"passed": True}, ctx)
        assert result["status"] == "success"
        assert len(result["simulation_id"]) == 36

    @pytest.mark.asyncio
    async def test_unknown_route_returns_error(self):
        ctx = _make_ctx()
        result = await _record_simulation_via_state("nonexistent", {"ok": False}, ctx)
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()


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
        await _store_route_via_state({"name": "route1"}, ctx)
        await _store_route_via_state({"name": "route2"}, ctx)
        result = await recall_routes(tool_context=ctx)
        assert result["status"] == "success"
        assert result["count"] == 2
        for r in result["routes"]:
            assert "route_id" in r and "route_data" in r

    @pytest.mark.asyncio
    async def test_respects_count_param(self):
        ctx = _make_ctx()
        for i in range(5):
            await _store_route_via_state({"index": i}, ctx)
        result = await recall_routes(tool_context=ctx, count=3)
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_respects_sort_by_param(self):
        ctx = _make_ctx()
        await _store_route_via_state({"name": "low"}, ctx, evaluation_result={"overall_score": 50})
        await _store_route_via_state({"name": "high"}, ctx, evaluation_result={"overall_score": 95})
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
        rd = await _store_route_via_state({"name": "Berlin"}, ctx)
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
        await _store_route_via_state({"name": "low"}, ctx, evaluation_result={"overall_score": 50})
        await _store_route_via_state({"name": "high"}, ctx, evaluation_result={"overall_score": 95})
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
        await _store_route_via_state({"name": "unscored"}, ctx)
        result = await get_best_route(tool_context=ctx)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# A2A compliance
# ---------------------------------------------------------------------------


class TestA2ACompliance:
    @pytest.mark.asyncio
    async def test_store_route_returns_dict(self):
        assert isinstance(await _store_route_via_state({"x": 1}, _make_ctx()), dict)

    @pytest.mark.asyncio
    async def test_record_simulation_returns_dict(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state({"x": 1}, ctx)
        assert isinstance(await _record_simulation_via_state(rd["route_id"], {"ok": True}, ctx), dict)

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
        rd = await _store_route_via_state({"type": "FeatureCollection", "features": []}, ctx)
        # Clear marathon_route so the activation re-loads it from the store.
        ctx.state.pop("marathon_route", None)
        result = await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=True)
        assert result["status"] == "success"
        assert result["activated"] is True
        assert ctx.state["marathon_route"] == {"type": "FeatureCollection", "features": []}

    @pytest.mark.asyncio
    async def test_activate_route_false_does_not_set_state(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state({"type": "FeatureCollection", "features": []}, ctx)
        ctx.state.pop("marathon_route", None)
        ctx.state.pop("active_route_id", None)
        result = await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=False)
        assert result["status"] == "success"
        assert "activated" not in result
        assert "marathon_route" not in ctx.state

    @pytest.mark.asyncio
    async def test_activate_route_default_is_false(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state({"name": "test"}, ctx)
        ctx.state.pop("marathon_route", None)
        await get_route(route_id=rd["route_id"], tool_context=ctx)
        assert "marathon_route" not in ctx.state

    @pytest.mark.asyncio
    async def test_activate_route_sets_route_name(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state(
            {"name": "Strip Classic", "type": "FeatureCollection", "features": []},
            ctx,
        )
        await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=True)
        assert ctx.state["route_name"] == "Strip Classic"

    @pytest.mark.asyncio
    async def test_activate_route_sets_active_route_id(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state({"name": "Test"}, ctx)
        await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=True)
        assert ctx.state["active_route_id"] == rd["route_id"]

    @pytest.mark.asyncio
    async def test_activate_route_sets_evaluation_score(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state(
            {"name": "Scored"},
            ctx,
            evaluation_result={"overall_score": 85},
        )
        await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=True)
        assert ctx.state["evaluation_score"] == 85

    @pytest.mark.asyncio
    async def test_activate_route_sets_evaluation_result(self):
        ctx = _make_ctx()
        eval_data = {"overall_score": 85, "notes": "good"}
        rd = await _store_route_via_state({"name": "Eval"}, ctx, evaluation_result=eval_data)
        await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=True)
        assert ctx.state["evaluation_result"] == eval_data

    @pytest.mark.asyncio
    async def test_activate_route_no_eval_omits_eval_state(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state({"name": "NoEval"}, ctx)
        ctx.state.pop("evaluation_score", None)
        ctx.state.pop("evaluation_result", None)
        await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=True)
        assert "evaluation_score" not in ctx.state
        assert "evaluation_result" not in ctx.state

    @pytest.mark.asyncio
    async def test_activate_route_uses_fallback_name(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state({"type": "FeatureCollection"}, ctx)
        await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=True)
        assert ctx.state["route_name"] == "Stored Route"

    @pytest.mark.asyncio
    async def test_activate_route_uses_theme_fallback(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state({"theme": "Desert Explorer"}, ctx)
        await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=True)
        assert ctx.state["route_name"] == "Desert Explorer"

    @pytest.mark.asyncio
    async def test_activate_route_with_non_dict_route_data(self):
        """Non-dict route_data should still set route_name to fallback."""
        ctx = _make_ctx()
        # Store a normal route, then swap its route_data to a non-dict value
        # to exercise the isinstance guard in get_route.
        rd = await _store_route_via_state({"name": "Temp"}, ctx)
        from agents.planner_with_memory.memory.tools import _store

        stored_route = await _store.get_route(rd["route_id"])
        assert stored_route is not None
        stored_route.route_data = "raw-string-data"  # type: ignore[assignment]
        await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=True)
        assert ctx.state["route_name"] == "Stored Route"
        assert ctx.state["marathon_route"] == "raw-string-data"

    @pytest.mark.asyncio
    async def test_activate_false_does_not_set_new_state_keys(self):
        ctx = _make_ctx()
        rd = await _store_route_via_state(
            {"name": "Test"},
            ctx,
            evaluation_result={"overall_score": 90},
        )
        # Clear keys set by store_route/_store_route_via_state so we can
        # cleanly assert that activate_route=False doesn't re-populate them.
        ctx.state.pop("active_route_id", None)
        ctx.state.pop("evaluation_score", None)
        ctx.state.pop("evaluation_result", None)
        await get_route(route_id=rd["route_id"], tool_context=ctx, activate_route=False)
        assert "route_name" not in ctx.state
        assert "active_route_id" not in ctx.state
        assert "evaluation_score" not in ctx.state
        assert "evaluation_result" not in ctx.state

    @pytest.mark.asyncio
    async def test_activate_not_found_returns_error(self):
        ctx = _make_ctx()
        result = await get_route(route_id="nonexistent", tool_context=ctx, activate_route=True)
        assert result["status"] == "error"
        assert "marathon_route" not in ctx.state
