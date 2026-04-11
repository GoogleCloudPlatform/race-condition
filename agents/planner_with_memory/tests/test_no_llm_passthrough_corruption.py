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

"""End-to-end no-LLM reproducer for the stringified-features bug.

Mirrors the dev's failing flow from log session `8e36c3f3` (planner_with_memory)
plus the `assess_traffic_impact` failure at 22:01:02:

1. plan_marathon_route writes state["marathon_route"] (dict-of-dict features).
2. store_route reads it from state, persists to the in-memory store.
3. (Simulating Execute-by-Reference) get_route(activate_route=True) re-loads
   the route into state.
4. assess_traffic_impact reads state["marathon_route"] and iterates features.

Pre-state-driven-refactor: store_route accepted route_data as an LLM-supplied
JSON string.  When the LLM mangled the string (each feature emitted as a
JSON-encoded string instead of a Feature object), assess_traffic_impact
crashed at `feature.get("geometry", {})` with
``AttributeError: 'str' object has no attribute 'get'``.

Post-refactor: route_data flows entirely through Python state; the LLM never
touches it; corruption is impossible by construction.

This test runs in-process with no LLM, no Honcho, no Redis required.
"""

from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agents.planner_with_memory.memory.schemas import PlannedRoute, SimulationRecord


def _load_assess_traffic_impact():
    """Dynamically import assess_traffic_impact from the hyphenated skill dir."""
    here = pathlib.Path(__file__).resolve()
    backend = here.parents[3]  # tests/ -> planner_with_memory/ -> agents/ -> backend/
    gis_path = backend / "agents" / "planner" / "skills" / "gis-spatial-engineering" / "scripts" / "tools.py"
    spec = importlib.util.spec_from_file_location("_gis_tools_under_test", gis_path)
    assert spec and spec.loader, f"Cannot load GIS tools from {gis_path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.assess_traffic_impact


# ---------------------------------------------------------------------------
# In-memory store fixture (mirrors test_memory_tools.py)
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


def _ctx() -> MagicMock:
    c = MagicMock()
    c.state = {}
    return c


# ---------------------------------------------------------------------------
# Reproducer
# ---------------------------------------------------------------------------


def _well_formed_route() -> dict:
    """A minimal but structurally-correct FeatureCollection."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Las Vegas Blvd"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.17, 36.08], [-115.17, 36.09]],
                },
            },
            {
                "type": "Feature",
                "properties": {"name": "Spring Mountain Rd"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.17, 36.09], [-115.18, 36.09]],
                },
            },
        ],
    }


def _stringified_features_route() -> dict:
    """The corrupt shape that pre-refactor LLM passthrough produced.

    Each Feature is a JSON-encoded *string* instead of a dict.  Pre-refactor,
    this would happily pass through ``json.loads(route_data)`` in store_route
    and silently poison the in-memory store.
    """
    import json

    feats = _well_formed_route()["features"]
    return {
        "type": "FeatureCollection",
        "features": [json.dumps(f) for f in feats],
    }


@pytest.mark.asyncio
async def test_state_driven_loop_completes_without_corruption(_mem_store):
    """Happy path: plan → store → activate → assess_traffic_impact, all in-process.

    This is the regression test for the dev's failure: with the state-driven
    refactor in place, the route never leaves Python land, so features are
    always dicts and assess_traffic_impact never raises AttributeError.
    """
    from agents.planner_with_memory.memory.tools import get_route, store_route

    assess_traffic_impact = _load_assess_traffic_impact()
    ctx = _ctx()

    # 1. Stage a freshly-planned route in state (skip plan_marathon_route's
    #    heavy graph search; we only need the state contract here).
    ctx.state["marathon_route"] = _well_formed_route()

    # 2. Producer wrote evaluation_result to state (Phase 1 contract).
    ctx.state["evaluation_result"] = {"overall_score": 80, "passed": True}

    # 3. Persist via the new state-driven API.
    sr = await store_route(tool_context=ctx)
    assert sr["status"] == "success", sr
    route_id = sr["route_id"]

    # 4. Simulate Execute-by-Reference in a fresh session by clearing
    #    marathon_route then re-activating from the store.
    ctx.state.pop("marathon_route", None)
    activated = await get_route(route_id=route_id, tool_context=ctx, activate_route=True)
    assert activated["status"] == "success"
    assert isinstance(ctx.state["marathon_route"], dict)
    assert all(isinstance(f, dict) for f in ctx.state["marathon_route"]["features"]), (
        "Activated route MUST have dict features (this assertion would have FAILED on dev)."
    )

    # 5. assess_traffic_impact iterates features.  Pre-refactor this raised
    #    AttributeError on the corrupted shape.  Post-refactor it succeeds.
    traffic = await assess_traffic_impact(tool_context=ctx)
    assert traffic["status"] == "success", f"assess_traffic_impact must succeed on a state-driven route, got: {traffic}"


@pytest.mark.asyncio
async def test_corrupt_in_store_blob_still_reproduces_old_bug(_mem_store):
    """Sanity check: if a corrupt blob is forced into the in-memory store
    (bypassing the state-driven write path), assess_traffic_impact still
    raises today.  Phase 5 (boundary validator in prepare_simulation) and
    a complementary guard in assess_traffic_impact are intentionally NOT
    added here; the architectural fix is what closes the corruption surface.

    This test documents the residual blast radius: a directly-corrupted
    store entry still poisons downstream consumers.  It is NOT a regression
    we ship a fix for in this PR (the fix is the state-driven write path).
    """
    from agents.planner_with_memory.memory.tools import get_route

    assess_traffic_impact = _load_assess_traffic_impact()

    # Inject a corrupt route directly into the store, bypassing store_route.
    rid = "corrupt-route-id"
    _mem_store._routes[rid] = PlannedRoute(
        route_id=rid,
        route_data=_stringified_features_route(),
        created_at=datetime.now(tz=timezone.utc),
    )

    ctx = _ctx()
    activated = await get_route(route_id=rid, tool_context=ctx, activate_route=True)
    assert activated["status"] == "success"
    # Confirm the corrupt shape made it into state.
    assert any(isinstance(f, str) for f in ctx.state["marathon_route"]["features"])

    with pytest.raises(AttributeError, match="'str' object has no attribute 'get'"):
        await assess_traffic_impact(tool_context=ctx)
