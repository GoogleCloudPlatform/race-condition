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

"""Integration test for the full traffic pipeline.

Exercises the complete flow: build a real route from the planner's tools,
assess traffic closures, build a traffic model, and run multiple ticks
of traffic computation.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from agents.utils.traffic import (
    build_segment_distance_index,
    compute_tick_traffic,
    identify_closed_segments,
)

# ---------------------------------------------------------------------------
# Dynamic import: gis-spatial-engineering has hyphens in the directory name
# ---------------------------------------------------------------------------
_skill_path = os.path.join(
    os.path.dirname(__file__),
    "..",
    "planner",
    "skills",
    "gis-spatial-engineering",
    "scripts",
    "tools.py",
)
_spec = importlib.util.spec_from_file_location("route_planning_tools", _skill_path)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_build_graph = _mod._build_graph
_generate_best_route = _mod._generate_best_route
_split_route_by_road = _mod._split_route_by_road


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NETWORK_PATH = (
    Path(__file__).parent.parent / "planner" / "skills" / "gis-spatial-engineering" / "assets" / "network.json"
)


@pytest.fixture(scope="module")
def network() -> dict:
    """Load the real road network GeoJSON."""
    with open(_NETWORK_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def planned_route(network: dict) -> dict:
    """Generate a real route using the planner's zone-sweep algorithm."""
    adj, landmarks, road_names, strip_nodes = _build_graph(network)
    nodes = set(adj.keys())

    route_coords, total_dist = _generate_best_route(
        adj,
        nodes,
        landmarks,
        strip_nodes,
        road_names,
        seed=42,
        finish_landmark="Michelob Ultra Arena",
        max_candidates=5,
    )

    segments = _split_route_by_road(route_coords, road_names, total_dist)

    return {
        "type": "FeatureCollection",
        "features": segments,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTrafficIntegration:
    """End-to-end traffic pipeline tests using a real planned route."""

    def test_segment_index_covers_full_route(self, planned_route: dict) -> None:
        """Segment distance index is non-empty and spans > 20 miles."""
        index = build_segment_distance_index(planned_route)

        assert len(index) > 0, "Segment index should not be empty"
        last_end = index[-1]["end_mi"]
        assert last_end > 15, f"Route should span > 15 mi, got {last_end:.2f}"

    def test_closure_analysis_finds_closures(self, planned_route: dict, network: dict) -> None:
        """identify_closed_segments finds route closures along the marathon route.

        Route-coincident segments (roads the marathon runs along) appear in
        ``route_closures`` rather than ``closed``.  The ``closed`` list only
        contains collateral closures.
        """
        result = identify_closed_segments(planned_route, network)

        assert len(result["route_closures"]) > 0, "Should find route closures"
        route_closure_names = {seg.get("properties", {}).get("name", "") for seg in result["route_closures"]}
        assert len(route_closure_names) > 0, f"Should have named route closures; got {route_closure_names}"

    def test_multi_tick_traffic_simulation(self, planned_route: dict) -> None:
        """5-tick simulation produces valid congestion and negative TEV."""
        index = build_segment_distance_index(planned_route)
        ticks_closed: dict = {}
        result: dict = {}

        for tick in range(5):
            sweep_mi = (tick + 1) * 2.0  # 2 mi per tick
            result = compute_tick_traffic(
                segment_index=index,
                sweep_distance_mi=sweep_mi,
                current_tick=tick,
                ticks_closed=ticks_closed,
            )
            ticks_closed = result["ticks_closed"]

        # After 5 ticks some segments should show congestion
        assert result, "Result should be populated after 5 ticks"
        has_congestion = any(s["congestion_level"] > 0 for s in result["segments"])
        assert has_congestion, "At least one segment should have congestion"

        assert result["tev_impact"] < 0, "TEV impact should be negative"

        assert 0 <= result["overall_congestion"] <= 1, (
            f"overall_congestion should be 0-1, got {result['overall_congestion']}"
        )

    def test_sweep_reopens_segments(self, planned_route: dict) -> None:
        """Running the sweep past a segment's end transitions it to reopening/open."""
        index = build_segment_distance_index(planned_route)
        assert len(index) > 0

        first_end_mi = index[0]["end_mi"]

        # Run 5 ticks with no sweep (sweep at 0) to accumulate closure time.
        ticks_closed: dict = {}
        for tick in range(5):
            result = compute_tick_traffic(
                segment_index=index,
                sweep_distance_mi=0.0,
                current_tick=tick,
                ticks_closed=ticks_closed,
            )
            ticks_closed = result["ticks_closed"]

        # Now run one tick with sweep past the first segment's end.
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=first_end_mi + 1.0,
            current_tick=5,
            ticks_closed=ticks_closed,
        )

        first_seg = result["segments"][0]
        assert first_seg["status"] in ("reopening", "open"), (
            f"Expected 'reopening' or 'open', got '{first_seg['status']}'"
        )
