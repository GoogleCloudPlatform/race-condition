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

"""Contract tests for state-driven persistence tools.

After the state-driven memory persistence design (see docs/plans/2026-04-19-...),
the three persistence tools (store_route, record_simulation,
store_simulation_summary) MUST:

1. Read large payloads (route_data, evaluation_result, simulation_result)
   from session state, NOT from LLM-supplied JSON string arguments.
2. Have Gemini function declarations that do NOT expose those parameters
   (so the LLM literally cannot supply them).
3. Return a structured error dict when the required state is missing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from google.adk.tools.function_tool import FunctionTool

from agents.planner_with_memory.memory.schemas import PlannedRoute, SimulationRecord


# ---------------------------------------------------------------------------
# In-memory store stub
# ---------------------------------------------------------------------------


class _MemStore:
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


@pytest.fixture(autouse=True)
def _mem_store():
    store = _MemStore()
    with patch("agents.planner_with_memory.memory.tools._store", store):
        yield store


def _ctx(state: dict | None = None) -> MagicMock:
    c = MagicMock()
    c.state = state if state is not None else {}
    return c


# ---------------------------------------------------------------------------
# store_route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_route_reads_route_from_state(_mem_store):
    from agents.planner_with_memory.memory.tools import store_route

    route = {"type": "FeatureCollection", "features": [{"type": "Feature"}]}
    ctx = _ctx({"marathon_route": route})

    result = await store_route(tool_context=ctx)

    assert result["status"] == "success"
    rid = result["route_id"]
    stored = await _mem_store.get_route(rid)
    assert stored is not None
    assert stored.route_data == route


@pytest.mark.asyncio
async def test_store_route_uses_evaluation_result_from_state(_mem_store):
    from agents.planner_with_memory.memory.tools import store_route

    route = {"type": "FeatureCollection", "features": []}
    eval_result = {"overall_score": 87, "passed": True}
    ctx = _ctx({"marathon_route": route, "evaluation_result": eval_result})

    result = await store_route(tool_context=ctx)

    assert result["status"] == "success"
    stored = await _mem_store.get_route(result["route_id"])
    assert stored.evaluation_score == 87.0
    assert stored.evaluation_result == eval_result


@pytest.mark.asyncio
async def test_store_route_errors_when_no_marathon_route_in_state(_mem_store):
    from agents.planner_with_memory.memory.tools import store_route

    ctx = _ctx({})

    result = await store_route(tool_context=ctx)

    assert result["status"] == "error"
    assert "marathon_route" in result["message"].lower() or "route" in result["message"].lower()


@pytest.mark.asyncio
async def test_store_route_sets_active_route_id_in_state(_mem_store):
    from agents.planner_with_memory.memory.tools import store_route

    ctx = _ctx({"marathon_route": {"type": "FeatureCollection", "features": []}})

    result = await store_route(tool_context=ctx)

    assert result["status"] == "success"
    assert ctx.state.get("active_route_id") == result["route_id"]


# ---------------------------------------------------------------------------
# record_simulation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_simulation_reads_simulation_result_from_state(_mem_store, monkeypatch):
    """record_simulation MUST read simulation_result from state, not from a JSON arg."""
    monkeypatch.delenv("ALLOYDB_HOST", raising=False)
    from agents.planner_with_memory.memory.tools import store_route, record_simulation

    # First store a route so we have a route_id to attach the sim to.
    ctx = _ctx({"marathon_route": {"type": "FeatureCollection", "features": []}})
    sr = await store_route(tool_context=ctx)
    route_id = sr["route_id"]

    # Now place a simulator response in state and call record_simulation.
    sim_result = {"status": "success", "metrics": {"finishers": 9421}}
    ctx.state["simulation_result"] = sim_result

    result = await record_simulation(route_id=route_id, tool_context=ctx)

    assert result["status"] == "success"
    stored = await _mem_store.get_route(route_id)
    assert stored.simulations[-1].simulation_result == sim_result


@pytest.mark.asyncio
async def test_record_simulation_errors_when_no_simulation_result_in_state(_mem_store, monkeypatch):
    monkeypatch.delenv("ALLOYDB_HOST", raising=False)
    from agents.planner_with_memory.memory.tools import store_route, record_simulation

    ctx = _ctx({"marathon_route": {"type": "FeatureCollection", "features": []}})
    sr = await store_route(tool_context=ctx)
    route_id = sr["route_id"]
    # NO simulation_result in state.

    result = await record_simulation(route_id=route_id, tool_context=ctx)

    assert result["status"] == "error"
    assert "simulation_result" in result["message"].lower() or "simulator" in result["message"].lower()


@pytest.mark.asyncio
async def test_record_simulation_errors_when_route_id_missing(_mem_store, monkeypatch):
    monkeypatch.delenv("ALLOYDB_HOST", raising=False)
    from agents.planner_with_memory.memory.tools import record_simulation

    ctx = _ctx({"simulation_result": {"status": "success"}})

    result = await record_simulation(route_id="nonexistent-id", tool_context=ctx)

    assert result["status"] == "error"
    assert "route" in result["message"].lower()


# ---------------------------------------------------------------------------
# Function declarations (Gemini-facing schema) MUST exclude the dropped params
# ---------------------------------------------------------------------------


def _function_decl_params(func) -> dict:
    """Return the JSON-schema-style properties dict from the Gemini FunctionDecl."""
    decl = FunctionTool(func)._get_declaration()
    if decl is None or decl.parameters is None or decl.parameters.properties is None:
        return {}
    return dict(decl.parameters.properties)


def test_store_route_decl_does_not_expose_route_data():
    from agents.planner_with_memory.memory.tools import store_route

    props = _function_decl_params(store_route)
    assert "route_data" not in props, (
        "store_route function declaration MUST NOT expose route_data; it must be read from state."
    )


def test_store_route_decl_does_not_expose_evaluation_result():
    from agents.planner_with_memory.memory.tools import store_route

    props = _function_decl_params(store_route)
    assert "evaluation_result" not in props, (
        "store_route function declaration MUST NOT expose evaluation_result; it must be read from state."
    )


def test_record_simulation_decl_does_not_expose_simulation_result():
    from agents.planner_with_memory.memory.tools import record_simulation

    props = _function_decl_params(record_simulation)
    assert "simulation_result" not in props, (
        "record_simulation function declaration MUST NOT expose simulation_result; it must be read from state."
    )


def test_store_simulation_summary_decl_does_not_expose_simulation_result():
    from agents.planner_with_memory.memory.tools import store_simulation_summary

    props = _function_decl_params(store_simulation_summary)
    assert "simulation_result" not in props, (
        "store_simulation_summary function declaration MUST NOT expose simulation_result; it must be read from state."
    )
