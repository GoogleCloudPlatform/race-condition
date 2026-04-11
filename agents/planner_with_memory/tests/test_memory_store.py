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

"""Tests for memory schemas and RouteMemoryStore."""

import time
from datetime import datetime, timezone

import pytest

from agents.planner_with_memory.memory.schemas import PlannedRoute, SimulationRecord
from agents.planner_with_memory.memory.store import RouteMemoryStore


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSimulationRecord:
    """Tests for SimulationRecord dataclass."""

    def test_creation_with_all_fields(self):
        now = datetime.now(tz=timezone.utc)
        record = SimulationRecord(
            simulation_id="sim-001",
            route_id="route-001",
            simulation_result={"passed": True, "score": 0.95},
            simulated_at=now,
        )
        assert record.simulation_id == "sim-001"
        assert record.route_id == "route-001"
        assert record.simulation_result == {"passed": True, "score": 0.95}
        assert record.simulated_at == now

    def test_simulation_result_is_dict(self):
        record = SimulationRecord(
            simulation_id="sim-002",
            route_id="route-002",
            simulation_result={"status": "failed", "errors": ["timeout"]},
            simulated_at=datetime.now(tz=timezone.utc),
        )
        assert isinstance(record.simulation_result, dict)
        assert "errors" in record.simulation_result


class TestPlannedRoute:
    """Tests for PlannedRoute dataclass."""

    def test_creation_with_required_fields(self):
        now = datetime.now(tz=timezone.utc)
        route = PlannedRoute(
            route_id="route-001",
            route_data={"distance_mi": 26.2188, "checkpoints": 5},
            created_at=now,
        )
        assert route.route_id == "route-001"
        assert route.route_data == {"distance_mi": 26.2188, "checkpoints": 5}
        assert route.created_at == now
        assert route.evaluation_score is None
        assert route.evaluation_result is None
        assert route.simulations == []

    def test_creation_with_all_fields(self):
        now = datetime.now(tz=timezone.utc)
        sim = SimulationRecord(
            simulation_id="sim-001",
            route_id="route-001",
            simulation_result={"passed": True},
            simulated_at=now,
        )
        route = PlannedRoute(
            route_id="route-001",
            route_data={"distance_mi": 26.2188},
            created_at=now,
            evaluation_score=92,
            evaluation_result={"passed": True, "overall_score": 92},
            simulations=[sim],
        )
        assert route.evaluation_score == 92
        assert route.evaluation_result == {"passed": True, "overall_score": 92}
        assert len(route.simulations) == 1
        assert route.simulations[0].simulation_id == "sim-001"

    def test_simulations_default_factory_isolation(self):
        """Each PlannedRoute instance gets its own simulations list."""
        route_a = PlannedRoute(
            route_id="a",
            route_data={},
            created_at=datetime.now(tz=timezone.utc),
        )
        route_b = PlannedRoute(
            route_id="b",
            route_data={},
            created_at=datetime.now(tz=timezone.utc),
        )
        route_a.simulations.append(
            SimulationRecord(
                simulation_id="s1",
                route_id="a",
                simulation_result={},
                simulated_at=datetime.now(tz=timezone.utc),
            )
        )
        assert len(route_a.simulations) == 1
        assert len(route_b.simulations) == 0


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------


class TestRouteMemoryStore:
    """Tests for RouteMemoryStore."""

    @pytest.fixture()
    def store(self) -> RouteMemoryStore:
        s = RouteMemoryStore()
        s._routes.clear()  # Start with empty store for unit tests
        return s

    # -- store_route --

    def test_store_route_returns_uuid(self, store: RouteMemoryStore):
        route_id = store.store_route(route_data={"distance_mi": 26.2188})
        assert isinstance(route_id, str)
        assert len(route_id) == 36  # UUID format

    def test_store_route_with_evaluation(self, store: RouteMemoryStore):
        route_id = store.store_route(
            route_data={"distance_mi": 26.2188},
            evaluation_score=88,
            evaluation_result={"passed": True, "overall_score": 88},
        )
        route = store.get_route(route_id)
        assert route is not None
        assert route.evaluation_score == 88
        assert route.evaluation_result == {"passed": True, "overall_score": 88}

    def test_store_route_sets_created_at(self, store: RouteMemoryStore):
        before = datetime.now(tz=timezone.utc)
        route_id = store.store_route(route_data={"distance_mi": 6.214})
        after = datetime.now(tz=timezone.utc)
        route = store.get_route(route_id)
        assert route is not None
        assert before <= route.created_at <= after

    # -- get_route --

    def test_get_route_returns_stored_route(self, store: RouteMemoryStore):
        route_id = store.store_route(route_data={"name": "Berlin Marathon"})
        route = store.get_route(route_id)
        assert route is not None
        assert route.route_id == route_id
        assert route.route_data == {"name": "Berlin Marathon"}

    def test_get_route_unknown_id_returns_none(self, store: RouteMemoryStore):
        result = store.get_route("nonexistent-uuid")
        assert result is None

    # -- record_simulation --

    def test_record_simulation_returns_sim_id(self, store: RouteMemoryStore):
        route_id = store.store_route(route_data={"distance_mi": 26.2188})
        sim_id = store.record_simulation(
            route_id=route_id,
            simulation_result={"passed": True, "npc_count": 500},
        )
        assert isinstance(sim_id, str)
        assert len(sim_id) == 36

    def test_record_simulation_unknown_route_returns_none(self, store: RouteMemoryStore):
        result = store.record_simulation(
            route_id="nonexistent",
            simulation_result={"passed": False},
        )
        assert result is None

    def test_record_simulation_appends_to_route(self, store: RouteMemoryStore):
        route_id = store.store_route(route_data={"distance_mi": 26.2188})
        store.record_simulation(route_id, {"run": 1})
        store.record_simulation(route_id, {"run": 2})
        route = store.get_route(route_id)
        assert route is not None
        assert len(route.simulations) == 2
        assert route.simulations[0].simulation_result == {"run": 1}
        assert route.simulations[1].simulation_result == {"run": 2}

    def test_record_simulation_sets_timestamps(self, store: RouteMemoryStore):
        route_id = store.store_route(route_data={})
        before = datetime.now(tz=timezone.utc)
        store.record_simulation(route_id, {"result": "ok"})
        after = datetime.now(tz=timezone.utc)
        route = store.get_route(route_id)
        assert route is not None
        sim = route.simulations[0]
        assert before <= sim.simulated_at <= after

    # -- recall_routes --

    def test_recall_routes_empty_store(self, store: RouteMemoryStore):
        result = store.recall_routes()
        assert result == []

    def test_recall_routes_sort_by_recent(self, store: RouteMemoryStore):
        store.store_route(route_data={"name": "first"})
        time.sleep(0.01)  # ensure ordering
        store.store_route(route_data={"name": "second"})
        time.sleep(0.01)
        store.store_route(route_data={"name": "third"})

        routes = store.recall_routes(count=10, sort_by="recent")
        assert len(routes) == 3
        assert routes[0].route_data["name"] == "third"
        assert routes[1].route_data["name"] == "second"
        assert routes[2].route_data["name"] == "first"

    def test_recall_routes_sort_by_best_score(self, store: RouteMemoryStore):
        store.store_route(route_data={"name": "low"}, evaluation_score=50)
        store.store_route(route_data={"name": "high"}, evaluation_score=95)
        store.store_route(route_data={"name": "mid"}, evaluation_score=75)

        routes = store.recall_routes(count=10, sort_by="best_score")
        assert len(routes) == 3
        assert routes[0].route_data["name"] == "high"
        assert routes[1].route_data["name"] == "mid"
        assert routes[2].route_data["name"] == "low"

    def test_recall_routes_best_score_none_scores_sort_last(self, store: RouteMemoryStore):
        store.store_route(route_data={"name": "scored"}, evaluation_score=80)
        store.store_route(route_data={"name": "unscored"})

        routes = store.recall_routes(sort_by="best_score")
        assert routes[0].route_data["name"] == "scored"
        assert routes[1].route_data["name"] == "unscored"

    def test_recall_routes_respects_count(self, store: RouteMemoryStore):
        for i in range(5):
            store.store_route(route_data={"index": i})

        routes = store.recall_routes(count=3)
        assert len(routes) == 3

    def test_recall_routes_default_sort_is_recent(self, store: RouteMemoryStore):
        store.store_route(route_data={"name": "first"})
        time.sleep(0.01)
        store.store_route(route_data={"name": "second"})

        routes = store.recall_routes()
        assert routes[0].route_data["name"] == "second"

    # -- get_best_route --

    def test_get_best_route_returns_highest_score(self, store: RouteMemoryStore):
        store.store_route(route_data={"name": "low"}, evaluation_score=50)
        store.store_route(route_data={"name": "high"}, evaluation_score=95)
        store.store_route(route_data={"name": "mid"}, evaluation_score=75)

        best = store.get_best_route()
        assert best is not None
        assert best.route_data["name"] == "high"
        assert best.evaluation_score == 95

    def test_get_best_route_empty_store_returns_none(self, store: RouteMemoryStore):
        result = store.get_best_route()
        assert result is None

    def test_get_best_route_no_scored_routes_returns_none(self, store: RouteMemoryStore):
        store.store_route(route_data={"name": "unscored"})
        result = store.get_best_route()
        assert result is None


class TestStoreAutoSeeding:
    """Tests that RouteMemoryStore loads seeds on construction."""

    def test_new_store_contains_seeds(self):
        store = RouteMemoryStore()
        routes = store.recall_routes()
        assert len(routes) >= 4

    def test_seeds_have_stable_ids(self):
        store = RouteMemoryStore()
        expected_ids = [
            "seed-0001-strip-classic-a1b2c3d4",
            "seed-0002-entertainment-circuit-e5f6g7h8",
            "seed-0003-east-side-explorer-i9j0k1l2",
            "seed-0004-grand-loop-m3n4o5p6",
        ]
        for route_id in expected_ids:
            assert store.get_route(route_id) is not None, f"Seed {route_id} not found"
