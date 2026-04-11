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

import os
import pytest
import importlib.util
from google.adk.tools.tool_context import ToolContext

# Dynamically import the tools.py file since "gis-spatial-engineering" has hyphens and can't be imported normally
skill_path = os.path.join(
    os.path.dirname(__file__), "..", "planner", "skills", "gis-spatial-engineering", "scripts", "tools.py"
)
spec = importlib.util.spec_from_file_location("route_planning_tools", skill_path)
assert spec is not None, f"Could not find module spec for {skill_path}"
assert spec.loader is not None, f"Module spec has no loader for {skill_path}"
route_planning_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route_planning_tools)

plan_marathon_route = route_planning_tools.plan_marathon_route
add_water_stations = route_planning_tools.add_water_stations
add_medical_tents = route_planning_tools.add_medical_tents
_build_distance_index = route_planning_tools._build_distance_index
_point_at_mile = route_planning_tools._point_at_mile
_place_hydration_stations = route_planning_tools._place_hydration_stations
_place_medical_stations = route_planning_tools._place_medical_stations
_place_portable_toilets = route_planning_tools._place_portable_toilets
_place_cheer_zones = route_planning_tools._place_cheer_zones
add_course_infrastructure = route_planning_tools.add_course_infrastructure


def _get_test_geojson() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-115.17284, 36.082057]},
                "properties": {"name": "Las Vegas Sign"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-115.183371, 36.090766]},
                "properties": {"name": "Allegiant Stadium"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-115.162109, 36.121283]},
                "properties": {"name": "Sphere"},
            },
            # Simple grid path for predictable distance tests
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-115.17284, 36.082057],  # Sign
                        [-115.17284, 36.090766],
                        [-115.183371, 36.090766],  # Allegiant
                        [-115.183371, 36.121283],
                        [-115.162109, 36.121283],  # Sphere
                    ],
                },
                "properties": {"name": "Test Main Road"},
            },
            # Additional long winding path to reach exactly 26.2188 mi
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-115.162109, 36.121283],  # Sphere
                        [-115.10, 36.121283],
                        [-115.10, 36.20],
                        [-115.20, 36.20],
                        [-115.20, 36.30],
                        [
                            -115.30,
                            36.30,
                        ],  # Extremely far to guarantee we cross 26.2188 mi
                    ],
                },
                "properties": {"name": "Test Extension Road"},
            },
        ],
    }


from unittest.mock import MagicMock

_build_graph = route_planning_tools._build_graph


def test_build_graph_returns_road_names():
    """_build_graph returns (adj, landmarks, road_names) with named edges."""
    test_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.17, 36.08], [-115.17, 36.09]],
                },
                "properties": {"name": "Test Road"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.17, 36.09], [-115.18, 36.09]],
                },
                "properties": {},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-115.17, 36.08]},
                "properties": {"name": "Test Landmark"},
            },
        ],
    }
    result = _build_graph(test_data)
    assert len(result) == 4, "Expected 4-tuple (adj, landmarks, road_names, strip_nodes)"

    adj, landmarks, road_names, strip_nodes = result
    assert "Test Landmark" in landmarks
    assert len(road_names) > 0

    # Named edge should be in road_names
    p1 = (-115.17, 36.08)
    p2 = (-115.17, 36.09)
    edge_key = tuple(sorted((p1, p2)))
    assert road_names[edge_key] == "Test Road"

    # Unnamed edge should NOT be in road_names
    p3 = (-115.18, 36.09)
    unnamed_edge = tuple(sorted((p2, p3)))
    assert unnamed_edge not in road_names


def test_split_route_by_road():
    """_split_route_by_road groups consecutive edges by road name."""
    _split = route_planning_tools._split_route_by_road
    route_coords = [
        (-115.17, 36.08),
        (-115.17, 36.09),
        (-115.17, 36.10),
        (-115.18, 36.10),
        (-115.19, 36.10),
    ]
    road_names = {
        tuple(sorted(((-115.17, 36.08), (-115.17, 36.09)))): "Road A",
        tuple(sorted(((-115.17, 36.09), (-115.17, 36.10)))): "Road A",
        tuple(sorted(((-115.17, 36.10), (-115.18, 36.10)))): "Road B",
        tuple(sorted(((-115.18, 36.10), (-115.19, 36.10)))): "Road B",
    }
    segments = _split(route_coords, road_names, 26.2188)

    assert len(segments) == 2
    assert segments[0]["properties"]["name"] == "Road A"
    assert segments[1]["properties"]["name"] == "Road B"

    # First segment carries route metadata
    assert segments[0]["properties"]["route_type"] == "marathon"
    assert segments[0]["properties"]["distance_mi"] == 26.2188
    assert segments[0]["properties"]["certified"] is True

    # Second segment does NOT carry route metadata
    assert "route_type" not in segments[1]["properties"]

    # Road A: 3 coords, Road B: 3 coords (shared junction)
    assert len(segments[0]["geometry"]["coordinates"]) == 3
    assert len(segments[1]["geometry"]["coordinates"]) == 3

    # Junction point shared between segments
    assert segments[0]["geometry"]["coordinates"][-1] == [-115.17, 36.10]
    assert segments[1]["geometry"]["coordinates"][0] == [-115.17, 36.10]


def test_split_route_by_road_with_unnamed_edges():
    """Unnamed edges produce segments with name=None."""
    _split = route_planning_tools._split_route_by_road
    route_coords = [
        (-115.17, 36.08),
        (-115.17, 36.09),
        (-115.18, 36.09),
    ]
    road_names = {
        tuple(sorted(((-115.17, 36.08), (-115.17, 36.09)))): "Named Road",
    }
    segments = _split(route_coords, road_names, 10.0)

    assert len(segments) == 2
    assert segments[0]["properties"]["name"] == "Named Road"
    assert segments[1]["properties"]["name"] is None


@pytest.fixture
def mock_context():
    mock_invocation_context = MagicMock()
    return ToolContext(invocation_context=mock_invocation_context)


@pytest.mark.asyncio
async def test_plan_marathon_route_distance(mock_context):
    """plan_marathon_route with petal_names produces exactly 26.2188 mi."""
    result = await plan_marathon_route(
        petal_names=["west-flamingo-jones", "north-sahara-rainbow", "south-tropicana-vv-sunset"],
        force_replan=True,
        tool_context=mock_context,
    )

    assert result["status"] == "success"
    assert "geojson" in result

    geojson = result["geojson"]

    # 1. Output has at least one route LineString segment
    line_features = [f for f in geojson["features"] if f["geometry"]["type"] == "LineString"]
    assert len(line_features) >= 1

    # 2. It's exactly 26.2188 mi (+/- 0.005 mi precision)
    # Distance is on the first segment's properties
    dist = line_features[0]["properties"].get("distance_mi")
    assert round(dist, 2) == 26.22, f"Distance {dist} is not exactly 26.2188 mi."

    # 3. Named segments have road names
    named = [f for f in line_features if f["properties"].get("name")]
    assert len(named) >= 1, "At least one segment should have a road name"

    # 4. Start/finish markers present
    markers = [f for f in geojson["features"] if f.get("properties", {}).get("marker-type")]
    assert len(markers) == 2, "Should have start and finish markers"

    # 5. Determinism: Same input -> same result (idempotency returns cached)
    result2 = await plan_marathon_route(
        petal_names=["west-flamingo-jones", "north-sahara-rainbow", "south-tropicana-vv-sunset"],
        tool_context=mock_context,
    )

    def _all_coords(gj):
        coords = []
        for f in gj["features"]:
            if f["geometry"]["type"] == "LineString":
                coords.extend(f["geometry"]["coordinates"])
        return coords

    assert _all_coords(result["geojson"]) == _all_coords(result2["geojson"])


@pytest.mark.asyncio
async def test_add_water_stations(mock_context):
    # Create an artificial route sequence to test marker placement
    test_route = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"route_type": "marathon", "distance_mi": 26.2188},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-115.0, 36.0],
                        [-115.0, 36.4],  # Straight north line > 42km
                    ],
                },
            }
        ],
    }

    result = await add_water_stations(test_route, mock_context)
    assert result["status"] == "success"

    features = result["geojson"]["features"]
    water_stations = [f for f in features if f["properties"].get("type") == "water_station"]

    # Should place 8 water stations (~3.1 mi / 5 km interval per WA TR 55)
    assert len(water_stations) == 8
    for i, station in enumerate(water_stations):
        assert station["properties"]["mi"] == pytest.approx((i + 1) * 3.1, abs=0.01)


@pytest.mark.asyncio
async def test_add_medical_tents(mock_context):
    # Create an artificial route sequence to test marker placement
    test_route = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"route_type": "marathon", "distance_mi": 26.2188},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-115.0, 36.0],
                        [-115.0, 36.4],  # Straight north line > 42km
                    ],
                },
            }
        ],
    }

    result = await add_medical_tents(test_route, mock_context)
    assert result["status"] == "success"

    features = result["geojson"]["features"]
    tents = [f for f in features if f["properties"].get("type") == "medical_tent"]

    # Default runner_count=10000: 6 stations (3 major + 3 course)
    assert len(tents) == 6
    majors = [t for t in tents if t["properties"]["tier"] == "major"]
    courses = [t for t in tents if t["properties"]["tier"] == "course"]
    assert len(majors) == 3
    assert len(courses) == 3


@pytest.mark.asyncio
async def test_water_stations_with_multi_linestring(mock_context):
    """Water stations work when route has multiple LineString segments."""
    test_route = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Road A", "route_type": "marathon"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.0, 36.0], [-115.0, 36.2]],
                },
            },
            {
                "type": "Feature",
                "properties": {"name": "Road B"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.0, 36.2], [-115.0, 36.4]],
                },
            },
        ],
    }
    result = await add_water_stations(test_route, mock_context)
    assert result["status"] == "success"
    water_stations = [f for f in result["geojson"]["features"] if f["properties"].get("type") == "water_station"]
    assert len(water_stations) == 8  # 3.1 mi / 5 km spacing per WA TR 55


@pytest.mark.asyncio
async def test_medical_tents_with_multi_linestring(mock_context):
    """Medical tents work when route has multiple LineString segments."""
    test_route = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Road A", "route_type": "marathon"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.0, 36.0], [-115.0, 36.2]],
                },
            },
            {
                "type": "Feature",
                "properties": {"name": "Road B"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.0, 36.2], [-115.0, 36.4]],
                },
            },
        ],
    }
    result = await add_medical_tents(test_route, mock_context)
    assert result["status"] == "success"
    tents = [f for f in result["geojson"]["features"] if f["properties"].get("type") == "medical_tent"]
    assert len(tents) == 6  # Default 10000 runners: 3 major + 3 course


@pytest.mark.asyncio
async def test_plan_marathon_route_includes_hydration_and_tents_and_state(mock_context):
    result = await plan_marathon_route(
        petal_names=["west-flamingo-jones", "north-sahara-rainbow", "south-tropicana-vv-sunset"],
        force_replan=True,
        tool_context=mock_context,
    )

    assert result["status"] == "success"
    geojson = result["geojson"]

    # Ensure tool context was updated
    assert mock_context.state.get("marathon_route") == geojson

    features = geojson["features"]
    # Should have 1 LineString
    assert any(f["geometry"]["type"] == "LineString" for f in features)

    water_stations = [f for f in features if f.get("properties", {}).get("type") == "water_station"]
    medical_tents = [f for f in features if f.get("properties", {}).get("type") == "medical_tent"]
    portable_toilets = [f for f in features if f.get("properties", {}).get("type") == "portable_toilet"]
    cheer_zones = [f for f in features if f.get("properties", {}).get("type") == "cheer_zone"]

    assert len(water_stations) > 0, "Water stations were not added"
    assert len(medical_tents) > 0, "Medical tents were not added"
    assert len(portable_toilets) > 0, "Portable toilets were not added"
    assert len(cheer_zones) > 0, "Cheer zones were not added"


def test_build_distance_index_returns_cumulative_distances():
    """_build_distance_index returns list of (coord, cumulative_miles) tuples."""
    coords = [(-115.0, 36.0), (-115.0, 36.1), (-115.0, 36.2)]
    index = _build_distance_index(coords)
    assert len(index) == 3
    assert index[0][1] == 0.0
    assert index[1][1] > 0.0
    assert index[2][1] > index[1][1]


def test_build_distance_index_single_point():
    """Single-point route returns index with one entry at mile 0."""
    coords = [(-115.0, 36.0)]
    index = _build_distance_index(coords)
    assert len(index) == 1
    assert index[0][1] == 0.0


def test_point_at_mile_start():
    """point_at_mile(0) returns the first coordinate."""
    coords = [(-115.0, 36.0), (-115.0, 36.1)]
    index = _build_distance_index(coords)
    result = _point_at_mile(index, 0.0)
    assert result == [-115.0, 36.0]


def test_point_at_mile_interpolates():
    """point_at_mile interpolates between index points."""
    coords = [(-115.0, 36.0), (-115.0, 36.1)]
    index = _build_distance_index(coords)
    total_dist = index[-1][1]
    mid = total_dist / 2
    result = _point_at_mile(index, mid)
    assert result[0] == pytest.approx(-115.0, abs=0.001)
    assert result[1] == pytest.approx(36.05, abs=0.01)


def test_point_at_mile_end():
    """point_at_mile at total distance returns last coordinate."""
    coords = [(-115.0, 36.0), (-115.0, 36.1)]
    index = _build_distance_index(coords)
    total = index[-1][1]
    result = _point_at_mile(index, total)
    assert result == pytest.approx([-115.0, 36.1], abs=0.001)


# ---------------------------------------------------------------------------
# Hydration Station Tests
# ---------------------------------------------------------------------------


def test_place_hydration_stations_count():
    """Hydration stations placed every 3.1 mi (5 km), yielding ~8 for a marathon."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]  # ~27.6 mi north
    index = _build_distance_index(coords)
    features = _place_hydration_stations(index, runner_count=10000)
    assert len(features) == 8
    for f in features:
        assert f["properties"]["type"] == "water_station"
        assert "mi" in f["properties"]
        assert "km" in f["properties"]


def test_place_hydration_stations_spacing():
    """Hydration stations are spaced at 3.1 mi intervals."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    features = _place_hydration_stations(index, runner_count=500)
    miles = [f["properties"]["mi"] for f in features]
    for i, mi in enumerate(miles):
        assert mi == pytest.approx((i + 1) * 3.1, abs=0.01)


# ---------------------------------------------------------------------------
# Medical Station Tests
# ---------------------------------------------------------------------------


def test_place_medical_stations_small_race():
    """< 1000 runners: 4 medical stations (2 major + 2 course)."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    features = _place_medical_stations(index, runner_count=500)
    assert len(features) == 4
    majors = [f for f in features if f["properties"]["tier"] == "major"]
    courses = [f for f in features if f["properties"]["tier"] == "course"]
    assert len(majors) == 2
    assert len(courses) == 2


def test_place_medical_stations_medium_race():
    """1000-10000 runners: 6 medical stations (3 major + 3 course)."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    features = _place_medical_stations(index, runner_count=5000)
    assert len(features) == 6
    majors = [f for f in features if f["properties"]["tier"] == "major"]
    assert len(majors) == 3


def test_place_medical_stations_large_race():
    """> 10000 runners: 8 medical stations (3 major + 5 course)."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    features = _place_medical_stations(index, runner_count=50000)
    assert len(features) == 8
    majors = [f for f in features if f["properties"]["tier"] == "major"]
    assert len(majors) == 3


def test_place_medical_stations_have_required_properties():
    """All medical stations have type, mi, and tier properties."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    features = _place_medical_stations(index, runner_count=10000)
    for f in features:
        assert f["properties"]["type"] == "medical_tent"
        assert "mi" in f["properties"]
        assert f["properties"]["tier"] in ("major", "course")


# ---------------------------------------------------------------------------
# Portable Toilet Tests
# ---------------------------------------------------------------------------


def test_place_portable_toilets_small_race():
    """< 1000 runners: 4 toilet stations."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    features = _place_portable_toilets(index, runner_count=500)
    assert len(features) == 4
    for f in features:
        assert f["properties"]["type"] == "portable_toilet"
        assert "units" in f["properties"]
        assert f["properties"]["units"] >= 2


def test_place_portable_toilets_large_race():
    """> 30000 runners: 10 toilet stations with higher unit counts."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    features = _place_portable_toilets(index, runner_count=50000)
    assert len(features) == 10
    for f in features:
        assert f["properties"]["units"] >= 10


def test_place_portable_toilets_offset_from_hydration():
    """Toilet stations should not be at the same mile markers as hydration."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    hydration = _place_hydration_stations(index, runner_count=10000)
    toilets = _place_portable_toilets(index, runner_count=10000)
    hydration_miles = {round(f["properties"]["mi"], 1) for f in hydration}
    toilet_miles = {round(f["properties"]["mi"], 1) for f in toilets}
    assert hydration_miles.isdisjoint(toilet_miles), "Toilets should not overlap hydration stations"


# ---------------------------------------------------------------------------
# Cheer Zone Tests
# ---------------------------------------------------------------------------


def test_place_cheer_zones_small_race():
    """< 1000 runners: 4 cheer zones at strategic locations."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    features = _place_cheer_zones(index, runner_count=500)
    assert len(features) == 4
    for f in features:
        assert f["properties"]["type"] == "cheer_zone"
        assert "name" in f["properties"]


def test_place_cheer_zones_large_race():
    """> 10000 runners: 8 cheer zones."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    features = _place_cheer_zones(index, runner_count=50000)
    assert len(features) == 8


def test_place_cheer_zones_include_critical_locations():
    """Cheer zones must include halfway and 'the wall' locations."""
    coords = [(-115.0, 36.0), (-115.0, 36.4)]
    index = _build_distance_index(coords)
    features = _place_cheer_zones(index, runner_count=10000)
    miles = [f["properties"]["mi"] for f in features]
    has_halfway = any(12.0 <= m <= 14.0 for m in miles)
    has_wall = any(19.0 <= m <= 21.0 for m in miles)
    assert has_halfway, "Missing cheer zone near halfway point"
    assert has_wall, "Missing cheer zone near 'the wall'"


# ---------------------------------------------------------------------------
# Orchestrator Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_course_infrastructure_all_types():
    """Orchestrator places all 4 infrastructure types."""
    test_route = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"route_type": "marathon", "distance_mi": 26.2188},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.0, 36.0], [-115.0, 36.4]],
                },
            }
        ],
    }
    result = await add_course_infrastructure(test_route, runner_count=10000)
    assert result["status"] == "success"

    features = result["geojson"]["features"]
    types = {f["properties"].get("type") for f in features if f["geometry"]["type"] == "Point"}
    assert "water_station" in types
    assert "medical_tent" in types
    assert "portable_toilet" in types
    assert "cheer_zone" in types


@pytest.mark.asyncio
async def test_add_course_infrastructure_runner_scaling():
    """Larger runner counts produce more infrastructure points."""
    test_route_small = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"route_type": "marathon"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.0, 36.0], [-115.0, 36.4]],
                },
            }
        ],
    }
    test_route_large = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"route_type": "marathon"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-115.0, 36.0], [-115.0, 36.4]],
                },
            }
        ],
    }
    small = await add_course_infrastructure(test_route_small, runner_count=500)
    large = await add_course_infrastructure(test_route_large, runner_count=50000)

    small_points = [f for f in small["geojson"]["features"] if f["geometry"]["type"] == "Point"]
    large_points = [f for f in large["geojson"]["features"] if f["geometry"]["type"] == "Point"]
    assert len(large_points) > len(small_points)
