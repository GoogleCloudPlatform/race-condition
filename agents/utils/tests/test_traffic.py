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

"""Tests for the traffic analysis core library."""

import pytest

from agents.utils.traffic import (
    _coords_match,
    _find_network_junctions,
    _haversine,
    _is_route_line,
    _split_road_at_closure,
    build_segment_distance_index,
    compute_tick_traffic,
    identify_closed_segments,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _line_feature(coords: list[list[float]], road_name: str = "Main St") -> dict:
    """Build a GeoJSON LineString Feature."""
    return {
        "type": "Feature",
        "properties": {"name": road_name},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _point_feature(coord: list[float]) -> dict:
    """Build a GeoJSON Point Feature (should be skipped by segment builder)."""
    return {
        "type": "Feature",
        "properties": {"name": "Waypoint"},
        "geometry": {"type": "Point", "coordinates": coord},
    }


def _fc(features: list[dict]) -> dict:
    """Wrap features into a GeoJSON FeatureCollection."""
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Haversine / coords_match
# ---------------------------------------------------------------------------


class TestHaversine:
    def test_same_point_is_zero(self):
        assert _haversine([-87.6298, 41.8781], [-87.6298, 41.8781]) == 0.0

    def test_known_distance(self):
        # Chicago to Milwaukee ~80-90 mi
        d = _haversine([-87.6298, 41.8781], [-87.9065, 43.0389])
        assert 80 < d < 100

    def test_uses_earth_radius_3958_8(self):
        # Verify the formula uses 3958.8 mi radius by checking a known value
        # 1 degree of latitude ~ 69.05 mi
        d = _haversine([0.0, 0.0], [0.0, 1.0])
        assert 68.5 < d < 69.5


class TestCoordsMatch:
    def test_same_point_matches(self):
        assert _coords_match([-87.6298, 41.8781], [-87.6298, 41.8781]) is True

    def test_close_point_matches(self):
        # Shift by ~0.0005 degrees (well under 0.05 mi)
        assert _coords_match([-87.6298, 41.8781], [-87.6299, 41.8782]) is True

    def test_far_point_does_not_match(self):
        assert _coords_match([-87.6298, 41.8781], [-87.6398, 41.8881]) is False


# ---------------------------------------------------------------------------
# TestFindNetworkJunctions
# ---------------------------------------------------------------------------


class TestFindNetworkJunctions:
    def test_shared_coordinate_is_junction(self):
        """A coordinate shared by two different roads is a junction."""
        network = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Oak St"),
                _line_feature([[-87.63, 41.88], [-87.64, 41.88]], "Elm St"),
            ]
        )
        junctions = _find_network_junctions(network)
        assert (round(-87.63, 6), round(41.88, 6)) in junctions

    def test_unshared_coordinate_not_junction(self):
        """A coordinate that only belongs to one road is not a junction."""
        network = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Oak St"),
                _line_feature([[-87.63, 41.88], [-87.64, 41.88]], "Elm St"),
            ]
        )
        junctions = _find_network_junctions(network)
        assert (round(-87.63, 6), round(41.87, 6)) not in junctions

    def test_same_road_does_not_create_junction(self):
        """Coordinates shared within the same road are not junctions."""
        network = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Oak St"),
            ]
        )
        junctions = _find_network_junctions(network)
        assert len(junctions) == 0

    def test_three_roads_at_junction(self):
        """A coordinate shared by three roads is still one junction."""
        network = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Oak St"),
                _line_feature([[-87.63, 41.88], [-87.64, 41.88]], "Elm St"),
                _line_feature([[-87.63, 41.88], [-87.62, 41.89]], "Pine St"),
            ]
        )
        junctions = _find_network_junctions(network)
        assert (round(-87.63, 6), round(41.88, 6)) in junctions


# ---------------------------------------------------------------------------
# TestSplitRoadAtClosure
# ---------------------------------------------------------------------------


class TestSplitRoadAtClosure:
    def test_full_overlap_returns_single_closed(self):
        """When all coords match, return one closed feature, no remainders."""
        coords = [[-87.63, 41.87], [-87.63, 41.88], [-87.63, 41.89]]
        matched = [True, True, True]
        junctions: set[tuple[float, float]] = set()
        closed, affected, remainder = _split_road_at_closure(coords, matched, junctions, "Oak St")
        assert len(closed) == 1
        assert closed[0]["geometry"]["coordinates"] == coords
        assert len(affected) == 0
        assert len(remainder) == 0

    def test_partial_overlap_middle(self):
        """Route closes middle of road; produces closed + affected remainders."""
        coords = [
            [-87.63, 41.87],  # A
            [-87.63, 41.88],  # B
            [-87.63, 41.89],  # C  <- match
            [-87.63, 41.90],  # D  <- match
            [-87.63, 41.91],  # E
        ]
        matched = [False, False, True, True, False]
        junctions: set[tuple[float, float]] = set()
        closed, affected, remainder = _split_road_at_closure(coords, matched, junctions, "Oak St")
        assert len(closed) == 1
        assert closed[0]["geometry"]["coordinates"] == coords[2:4]
        # No junctions -> entire remainders are affected
        assert len(affected) == 2
        assert len(remainder) == 0

    def test_affected_stops_at_junction(self):
        """Affected zone extends from closure to nearest junction, not beyond."""
        # Road: A--B--C--D--E  (indices 0-4)
        # Route matches: C, D (indices 2, 3)
        # Junction at B
        coords = [
            [-87.63, 41.87],  # A
            [-87.63, 41.88],  # B  <- junction
            [-87.63, 41.89],  # C  <- match
            [-87.63, 41.90],  # D  <- match
            [-87.63, 41.91],  # E
        ]
        matched = [False, False, True, True, False]
        junctions = {(round(-87.63, 6), round(41.88, 6))}  # B is junction
        closed, affected, remainder = _split_road_at_closure(coords, matched, junctions, "Oak St")
        assert len(closed) == 1
        # Left affected: B--C (junction to closure)
        assert len(affected) >= 1
        left_affected_coords = [
            f["geometry"]["coordinates"] for f in affected if f["geometry"]["coordinates"][-1] == coords[2]
        ]
        assert len(left_affected_coords) == 1
        assert left_affected_coords[0] == [coords[1], coords[2]]
        # Left open remainder: A--B (beyond junction)
        assert len(remainder) >= 1

    def test_closure_at_road_start(self):
        """Closure at the start of a road produces no left remainder."""
        coords = [
            [-87.63, 41.87],  # A  <- match
            [-87.63, 41.88],  # B  <- match
            [-87.63, 41.89],  # C
            [-87.63, 41.90],  # D
        ]
        matched = [True, True, False, False]
        junctions: set[tuple[float, float]] = set()
        closed, affected, remainder = _split_road_at_closure(coords, matched, junctions, "Oak St")
        assert len(closed) == 1
        assert closed[0]["geometry"]["coordinates"] == coords[0:2]
        # Right remainder is all affected (no junction)
        assert len(affected) == 1

    def test_closure_at_road_end(self):
        """Closure at the end of a road produces no right remainder."""
        coords = [
            [-87.63, 41.87],  # A
            [-87.63, 41.88],  # B
            [-87.63, 41.89],  # C  <- match
            [-87.63, 41.90],  # D  <- match
        ]
        matched = [False, False, True, True]
        junctions: set[tuple[float, float]] = set()
        closed, affected, remainder = _split_road_at_closure(coords, matched, junctions, "Oak St")
        assert len(closed) == 1
        # Left remainder is all affected (no junction)
        assert len(affected) == 1
        assert len(remainder) == 0

    def test_no_match_returns_empty(self):
        """When fewer than 2 coords match in a run, no closed segments."""
        coords = [[-87.63, 41.87], [-87.63, 41.88], [-87.63, 41.89]]
        matched = [True, False, False]
        junctions: set[tuple[float, float]] = set()
        closed, affected, remainder = _split_road_at_closure(coords, matched, junctions, "Oak St")
        assert len(closed) == 0

    def test_two_disjoint_closures_on_same_road(self):
        """Two separate matched runs produce two closed sub-segments."""
        # Road: A--B--C--D--E--F--G  (indices 0-6)
        # Matches: B-C (indices 1-2) and E-F (indices 4-5)
        coords = [
            [-87.63, 41.87],  # A
            [-87.63, 41.88],  # B <- match
            [-87.63, 41.89],  # C <- match
            [-87.63, 41.90],  # D
            [-87.63, 41.91],  # E <- match
            [-87.63, 41.92],  # F <- match
            [-87.63, 41.93],  # G
        ]
        matched = [False, True, True, False, True, True, False]
        junctions: set[tuple[float, float]] = set()
        closed, affected, remainder = _split_road_at_closure(coords, matched, junctions, "Oak St")
        assert len(closed) == 2
        assert closed[0]["geometry"]["coordinates"] == coords[1:3]
        assert closed[1]["geometry"]["coordinates"] == coords[4:6]
        # Gap between closures (C--D--E) should be affected (no junctions)
        assert len(affected) >= 1


# ---------------------------------------------------------------------------
# TestBuildSegmentDistanceIndex
# ---------------------------------------------------------------------------


class TestBuildSegmentDistanceIndex:
    def test_single_segment(self):
        """A single LineString produces one segment starting at 0."""
        coords = [[-87.63, 41.87], [-87.63, 41.88]]
        fc = _fc([_line_feature(coords, "Oak St")])
        index = build_segment_distance_index(fc)

        assert len(index) == 1
        seg = index[0]
        assert seg["start_mi"] == 0.0
        assert seg["end_mi"] > 0.0
        assert seg["road_name"] == "Oak St"

    def test_two_cumulative_segments(self):
        """Two LineStrings accumulate distance sequentially."""
        c1 = [[-87.63, 41.87], [-87.63, 41.88]]
        c2 = [[-87.63, 41.88], [-87.63, 41.89]]
        fc = _fc([_line_feature(c1, "1st"), _line_feature(c2, "2nd")])
        index = build_segment_distance_index(fc)

        assert len(index) == 2
        # Second segment starts where first ends
        assert index[1]["start_mi"] == pytest.approx(index[0]["end_mi"], abs=1e-6)
        # Second segment ends further
        assert index[1]["end_mi"] > index[1]["start_mi"]

    def test_non_linestring_skipped(self):
        """Point features are silently skipped."""
        coords = [[-87.63, 41.87], [-87.63, 41.88]]
        fc = _fc([_point_feature([-87.63, 41.87]), _line_feature(coords)])
        index = build_segment_distance_index(fc)

        assert len(index) == 1

    def test_coordinates_preserved(self):
        """The original coordinates are stored on the segment."""
        coords = [[-87.63, 41.87], [-87.63, 41.88], [-87.64, 41.88]]
        fc = _fc([_line_feature(coords)])
        index = build_segment_distance_index(fc)

        assert index[0]["coordinates"] == coords


# ---------------------------------------------------------------------------
# TestIdentifyClosedSegments
# ---------------------------------------------------------------------------


class TestIdentifyClosedSegments:
    def _route(self):
        """Route with two segments along Oak St."""
        return _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Oak St"),
            ]
        )

    def test_matching_segment_is_route_closure(self):
        """A network segment whose coords overlap the route is a route closure.

        Route-coincident segments are separated into ``route_closures``
        rather than ``closed`` because they *are* the marathon route.
        """
        route = self._route()
        # Network has a road matching the route exactly
        network = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Oak St"),
            ]
        )
        result = identify_closed_segments(route, network)
        assert len(result["closed"]) == 0
        assert len(result["route_closures"]) == 1
        assert result["route_closures"][0]["properties"]["name"] == "Oak St"

    def test_non_matching_not_closed(self):
        """A network segment far from the route is NOT closed."""
        route = self._route()
        network = _fc(
            [
                _line_feature([[-88.0, 42.0], [-88.0, 42.1]], "Far Away Rd"),
            ]
        )
        result = identify_closed_segments(route, network)
        assert len(result["closed"]) == 0

    def test_affected_segments_near_closed(self):
        """A segment sharing an endpoint with a closed segment is 'affected'.

        Oak St is a route line (in ``route_closures``), but Elm St sharing
        an endpoint with it is still detected as affected.
        """
        route = self._route()
        # Oak St matches the route (route closure). Elm St shares an endpoint
        network = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Oak St"),
                _line_feature([[-87.63, 41.88], [-87.64, 41.88]], "Elm St"),
            ]
        )
        result = identify_closed_segments(route, network)
        # Oak St is a route line, so closed is empty
        assert len(result["closed"]) == 0
        assert len(result["route_closures"]) == 1
        affected_names = [f["properties"]["name"] for f in result["affected"]]
        assert "Elm St" in affected_names

    def test_returns_intersections(self):
        """Intersections are where closed segment endpoints are shared by 2+ roads.

        Oak St is a route line, but intersections are still computed from
        the internal (unfiltered) closure list.
        """
        route = self._route()
        network = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Oak St"),
                _line_feature([[-87.63, 41.88], [-87.64, 41.88]], "Elm St"),
                _line_feature([[-87.63, 41.88], [-87.62, 41.89]], "Pine St"),
            ]
        )
        result = identify_closed_segments(route, network)
        # Oak St is a route line; closed output excludes it
        assert len(result["closed"]) == 0
        assert len(result["route_closures"]) == 1
        # Intersections are still detected
        assert len(result["intersections"]) >= 1
        ix = result["intersections"][0]
        assert "cross_streets" in ix
        assert "impact_level" in ix
        assert len(ix["cross_streets"]) >= 2


# ---------------------------------------------------------------------------
# TestIdentifyClosedSegmentsPartial
# ---------------------------------------------------------------------------


class TestIdentifyClosedSegmentsPartial:
    def test_partial_overlap_splits_road(self):
        """A road partially overlapping the route produces a sub-segment closure.

        The closed sub-segment (B--C) follows the route path exactly, so
        it is classified as a route closure rather than a collateral closure.
        """
        # Route covers coords B and C only
        route = _fc(
            [
                _line_feature([[-87.63, 41.88], [-87.63, 41.89]], "Route"),
            ]
        )
        # Network road spans A through D
        network = _fc(
            [
                _line_feature(
                    [
                        [-87.63, 41.87],  # A
                        [-87.63, 41.88],  # B  <- matches route
                        [-87.63, 41.89],  # C  <- matches route
                        [-87.63, 41.90],  # D
                    ],
                    "Long Rd",
                ),
            ]
        )
        result = identify_closed_segments(route, network)
        # B--C is a route line, so it appears in route_closures, not closed
        assert len(result["closed"]) == 0
        assert len(result["route_closures"]) == 1
        rc_coords = result["route_closures"][0]["geometry"]["coordinates"]
        assert len(rc_coords) == 2  # B and C only
        assert rc_coords[0] == [-87.63, 41.88]
        assert rc_coords[1] == [-87.63, 41.89]

    def test_partial_overlap_remainder_is_affected(self):
        """Open remainders of a partially-closed road are affected.

        The route-coincident sub-segment is in ``route_closures``, but
        the non-overlapping tails are still classified as affected.
        """
        route = _fc(
            [
                _line_feature([[-87.63, 41.88], [-87.63, 41.89]], "Route"),
            ]
        )
        network = _fc(
            [
                _line_feature(
                    [
                        [-87.63, 41.87],  # A
                        [-87.63, 41.88],  # B  <- matches
                        [-87.63, 41.89],  # C  <- matches
                        [-87.63, 41.90],  # D
                    ],
                    "Long Rd",
                ),
            ]
        )
        result = identify_closed_segments(route, network)
        assert len(result["closed"]) == 0
        assert len(result["route_closures"]) == 1
        affected_names = [f["properties"]["name"] for f in result["affected"]]
        assert "Long Rd" in affected_names

    def test_partial_overlap_affected_stops_at_junction(self):
        """Affected zone extends only to nearest junction.

        The route-coincident sub-segment (C--D) is in ``route_closures``.
        Affected segments are still correctly computed.
        """
        route = _fc(
            [
                _line_feature([[-87.63, 41.89], [-87.63, 41.90]], "Route"),
            ]
        )
        # Long Rd: A--B--C--D--E where route matches C--D
        # Cross St intersects at B (junction)
        network = _fc(
            [
                _line_feature(
                    [
                        [-87.63, 41.87],  # A
                        [-87.63, 41.88],  # B  <- junction with Cross St
                        [-87.63, 41.89],  # C  <- matches route
                        [-87.63, 41.90],  # D  <- matches route
                        [-87.63, 41.91],  # E
                    ],
                    "Long Rd",
                ),
                _line_feature(
                    [
                        [-87.63, 41.88],  # B (shared with Long Rd)
                        [-87.64, 41.88],
                    ],
                    "Cross St",
                ),
            ]
        )
        result = identify_closed_segments(route, network)
        # C--D is a route line
        assert len(result["closed"]) == 0
        assert len(result["route_closures"]) == 1
        # Affected should include B--C (junction to closure) from Long Rd
        affected_long_rd = [f for f in result["affected"] if f["properties"]["name"] == "Long Rd"]
        affected_coords_list = [f["geometry"]["coordinates"] for f in affected_long_rd]
        # B--C should be affected
        assert any(len(c) == 2 and c[0] == [-87.63, 41.88] and c[1] == [-87.63, 41.89] for c in affected_coords_list)

    def test_scattered_crossings_not_closed(self):
        """A road crossed at scattered non-contiguous points is NOT closed.

        When a road has >= 2 matched coords but they don't form a contiguous
        run, the road should be treated as open (not closed, not lost).
        """
        # Route crosses Long Rd at two separated points (A and E) but does
        # not follow Long Rd.  The two matches are non-contiguous so no
        # contiguous run of >= 2 exists.
        route = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.64, 41.87]], "Cross A"),
                _line_feature([[-87.63, 41.91], [-87.64, 41.91]], "Cross B"),
            ]
        )
        # Closed road shares endpoint A with Long Rd
        network = _fc(
            [
                _line_feature(
                    [
                        [-87.63, 41.87],  # A  <- matches Cross A
                        [-87.63, 41.88],  # B
                        [-87.63, 41.89],  # C
                        [-87.63, 41.90],  # D
                        [-87.63, 41.91],  # E  <- matches Cross B
                    ],
                    "Long Rd",
                ),
                _line_feature([[-87.63, 41.87], [-87.64, 41.87]], "Cross A"),
            ]
        )
        result = identify_closed_segments(route, network)
        # Long Rd should NOT be closed
        closed_names = [f["properties"]["name"] for f in result["closed"]]
        assert "Long Rd" not in closed_names
        # Long Rd should still be reachable as "affected" (shares endpoint
        # with closed Cross A)
        affected_names = [f["properties"]["name"] for f in result["affected"]]
        assert "Long Rd" in affected_names

    def test_trapped_cross_street_is_closed(self):
        """A cross-street trapped between two route-following roads is closed.

        When both endpoints of a segment are blocked by the marathon
        (coordinates match route coords on different roads), the segment
        is effectively closed -- no traffic can enter from either side.

        Road A and Road B are route lines (in ``route_closures``), but
        the trapped portion of Cross St is NOT a route line (its edges
        do not follow the route path) so it remains in ``closed``.
        """
        # Route follows Road A (horizontal) and Road B (horizontal).
        # Cross St runs vertically between them.  Both A and B share
        # an endpoint with Cross St.
        route = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.64, 41.87]], "Road A"),
                _line_feature([[-87.63, 41.88], [-87.64, 41.88]], "Road B"),
            ]
        )
        network = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.64, 41.87]], "Road A"),
                _line_feature([[-87.63, 41.88], [-87.64, 41.88]], "Road B"),
                _line_feature(
                    [
                        [-87.63, 41.86],  # south of Road A
                        [-87.63, 41.87],  # Road A intersection
                        [-87.63, 41.88],  # Road B intersection
                        [-87.63, 41.89],  # north of Road B
                    ],
                    "Cross St",
                ),
            ]
        )
        result = identify_closed_segments(route, network)
        # Road A and Road B are route lines
        route_closure_names = [f["properties"]["name"] for f in result["route_closures"]]
        assert "Road A" in route_closure_names
        assert "Road B" in route_closure_names
        # The trapped portion (Road A to Road B) of Cross St stays in closed
        closed_names = [f["properties"]["name"] for f in result["closed"]]
        assert "Cross St" in closed_names
        # The remainder portions should be affected
        affected_names = [f["properties"]["name"] for f in result["affected"]]
        assert "Cross St" in affected_names


# ---------------------------------------------------------------------------
# TestIsRouteLine
# ---------------------------------------------------------------------------


class TestIsRouteLine:
    """Tests for the _is_route_line helper."""

    def test_all_edges_match(self):
        """A segment whose every edge is a route edge is a route line."""
        route_edges = {
            ((0.0, 0.0), (1.0, 0.0)),
            ((1.0, 0.0), (0.0, 0.0)),
            ((1.0, 0.0), (2.0, 0.0)),
            ((2.0, 0.0), (1.0, 0.0)),
        }
        coords = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]
        assert _is_route_line(coords, route_edges) is True

    def test_no_edges_match(self):
        """A segment with no matching edges is not a route line."""
        route_edges = {
            ((0.0, 0.0), (1.0, 0.0)),
            ((1.0, 0.0), (0.0, 0.0)),
        }
        coords = [[5.0, 5.0], [6.0, 5.0]]
        assert _is_route_line(coords, route_edges) is False

    def test_partial_match_not_route_line(self):
        """A segment with only some edges matching is not a route line."""
        route_edges = {
            ((0.0, 0.0), (1.0, 0.0)),
            ((1.0, 0.0), (0.0, 0.0)),
        }
        # First edge matches, second does not
        coords = [[0.0, 0.0], [1.0, 0.0], [2.0, 1.0]]
        assert _is_route_line(coords, route_edges) is False

    def test_single_coord_returns_false(self):
        """A segment with fewer than 2 coords is not a route line."""
        route_edges = {((0.0, 0.0), (1.0, 0.0))}
        assert _is_route_line([[0.0, 0.0]], route_edges) is False

    def test_reversed_direction_matches(self):
        """A segment traversed in reverse still matches if both directions are in edge set."""
        route_edges = {
            ((0.0, 0.0), (1.0, 0.0)),
            ((1.0, 0.0), (0.0, 0.0)),
        }
        # Reversed direction
        coords = [[1.0, 0.0], [0.0, 0.0]]
        assert _is_route_line(coords, route_edges) is True


# ---------------------------------------------------------------------------
# TestRouteClosureFiltering
# ---------------------------------------------------------------------------


class TestRouteClosureFiltering:
    """Tests that identify_closed_segments correctly separates route lines."""

    def test_route_lines_excluded_from_closed(self):
        """Network segments following the route exactly are in route_closures, not closed."""
        route = _fc([_line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Main St")])
        network = _fc([_line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Main St")])

        result = identify_closed_segments(route, network)
        assert len(result["closed"]) == 0
        assert len(result["route_closures"]) == 1

    def test_non_route_closures_stay_in_closed(self):
        """Collateral closures (not following the route path) remain in closed."""
        # Route goes east-west on two roads; cross-street runs north-south
        route = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.64, 41.87]], "Road A"),
                _line_feature([[-87.63, 41.88], [-87.64, 41.88]], "Road B"),
            ]
        )
        network = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.64, 41.87]], "Road A"),
                _line_feature([[-87.63, 41.88], [-87.64, 41.88]], "Road B"),
                _line_feature(
                    [
                        [-87.63, 41.86],
                        [-87.63, 41.87],  # Road A intersection
                        [-87.63, 41.88],  # Road B intersection
                        [-87.63, 41.89],
                    ],
                    "Trapped St",
                ),
            ]
        )
        result = identify_closed_segments(route, network)
        # Route lines
        rc_names = [f["properties"]["name"] for f in result["route_closures"]]
        assert "Road A" in rc_names
        assert "Road B" in rc_names
        # Trapped cross-street is a collateral closure
        closed_names = [f["properties"]["name"] for f in result["closed"]]
        assert "Trapped St" in closed_names

    def test_affected_and_intersections_unaffected_by_filtering(self):
        """Filtering route lines from closed does not alter affected or intersections."""
        route = _fc([_line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Oak St")])
        network = _fc(
            [
                _line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Oak St"),
                _line_feature([[-87.63, 41.88], [-87.64, 41.88]], "Elm St"),
                _line_feature([[-87.63, 41.88], [-87.62, 41.89]], "Pine St"),
            ]
        )
        result = identify_closed_segments(route, network)
        # Affected still detected
        affected_names = [f["properties"]["name"] for f in result["affected"]]
        assert "Elm St" in affected_names
        assert "Pine St" in affected_names
        # Intersections still detected
        assert len(result["intersections"]) >= 1
        cross = result["intersections"][0]["cross_streets"]
        assert len(cross) >= 2


# ---------------------------------------------------------------------------
# TestComputeTickTraffic
# ---------------------------------------------------------------------------


class TestComputeTickTraffic:
    def _make_index(self):
        """Two segments: 0-0.5 mi and 0.5-1.0 mi."""
        return [
            {
                "start_mi": 0.0,
                "end_mi": 0.5,
                "coordinates": [[-87.63, 41.87], [-87.63, 41.875]],
                "road_name": "Seg A",
            },
            {
                "start_mi": 0.5,
                "end_mi": 1.0,
                "coordinates": [[-87.63, 41.875], [-87.63, 41.88]],
                "road_name": "Seg B",
            },
        ]

    def test_all_closed_at_start(self):
        """When sweep is at 0 all segments are ahead -> closed."""
        index = self._make_index()
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.0,
            current_tick=1,
            ticks_closed={},
        )
        for seg in result["segments"]:
            assert seg["status"] == "closed"

    def test_segments_behind_sweep_reopening(self):
        """Segments behind the sweep distance should be 'reopening'."""
        index = self._make_index()
        # Sweep past first segment
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.6,
            current_tick=5,
            ticks_closed={"Seg A": 4, "Seg B": 4},
        )
        seg_a = [s for s in result["segments"] if s["road_name"] == "Seg A"][0]
        assert seg_a["status"] == "reopening"

    def test_congestion_builds_over_ticks(self):
        """Congestion on a closed segment increases with ticks_closed."""
        index = self._make_index()
        r1 = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.0,
            current_tick=1,
            ticks_closed={},
        )
        r5 = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.0,
            current_tick=5,
            ticks_closed={"Seg A": 4, "Seg B": 4},
        )
        c1 = r1["segments"][0]["congestion_level"]
        c5 = r5["segments"][0]["congestion_level"]
        assert c5 > c1

    def test_tev_is_negative(self):
        """TEV impact should always be a negative dollar amount."""
        index = self._make_index()
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.0,
            current_tick=3,
            ticks_closed={"Seg A": 2, "Seg B": 2},
        )
        assert result["tev_impact"] < 0

    def test_overall_congestion_between_0_and_1(self):
        """overall_congestion is an average bounded [0, 1]."""
        index = self._make_index()
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.3,
            current_tick=5,
            ticks_closed={"Seg A": 4, "Seg B": 4},
        )
        assert 0 <= result["overall_congestion"] <= 1.0

    def test_returns_updated_ticks_closed(self):
        """The returned ticks_closed dict has incremented/reset counters."""
        index = self._make_index()
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.0,
            current_tick=1,
            ticks_closed={},
        )
        tc = result["ticks_closed"]
        assert "Seg A" in tc
        assert "Seg B" in tc
        # Values are dicts with {"closed": int, "peak": float | None}
        assert tc["Seg A"]["closed"] >= 1
        assert tc["Seg B"]["closed"] >= 1

    # -------------------------------------------------------------------
    # Issue 1 coverage: midpoint comparison
    # -------------------------------------------------------------------

    def test_midpoint_behind_sweep_end_ahead(self):
        """A segment whose midpoint is behind sweep but end is ahead is reopening."""
        # Segment: start=0.4, end=0.8, midpoint=0.6
        index = [
            {
                "start_mi": 0.4,
                "end_mi": 0.8,
                "coordinates": [[-87.63, 41.87], [-87.63, 41.88]],
                "road_name": "Bridge St",
            }
        ]
        # Sweep at 0.65 — midpoint 0.6 <= 0.65, but end 0.8 > 0.65
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.65,
            current_tick=5,
            ticks_closed={"Bridge St": {"closed": 4, "peak": None}},
        )
        seg = result["segments"][0]
        # Under the old end_mi comparison this would be "closed".
        # Under the correct midpoint comparison it should be "reopening".
        assert seg["status"] == "reopening"

    def test_midpoint_ahead_of_sweep_stays_closed(self):
        """A segment whose midpoint is ahead of sweep stays closed."""
        # Segment: start=0.4, end=0.8, midpoint=0.6
        index = [
            {
                "start_mi": 0.4,
                "end_mi": 0.8,
                "coordinates": [[-87.63, 41.87], [-87.63, 41.88]],
                "road_name": "Bridge St",
            }
        ]
        # Sweep at 0.55 — midpoint 0.6 > 0.55
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.55,
            current_tick=5,
            ticks_closed={"Bridge St": {"closed": 4, "peak": None}},
        )
        seg = result["segments"][0]
        assert seg["status"] == "closed"

    # -------------------------------------------------------------------
    # Issue 2 coverage: congestion decay model
    # -------------------------------------------------------------------

    def test_congestion_cap_at_one(self):
        """Congestion should cap at 1.0 even when ticks_closed > max."""
        index = [
            {
                "start_mi": 0.0,
                "end_mi": 1.0,
                "coordinates": [[-87.63, 41.87], [-87.63, 41.88]],
                "road_name": "Main St",
            }
        ]
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.0,
            current_tick=20,
            ticks_closed={"Main St": {"closed": 15, "peak": None}},
            max_congestion_ticks=10,
        )
        seg = result["segments"][0]
        assert seg["congestion_level"] == 1.0

    def test_decay_from_actual_peak(self):
        """Decay should start from actual peak congestion, not 1.0."""
        index = [
            {
                "start_mi": 0.0,
                "end_mi": 1.0,
                "coordinates": [[-87.63, 41.87], [-87.63, 41.88]],
                "road_name": "Main St",
            }
        ]
        # Segment was closed for 5 out of max 10 ticks -> peak = 0.5
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=1.0,
            current_tick=6,
            ticks_closed={"Main St": {"closed": 5, "peak": None}},
            max_congestion_ticks=10,
            congestion_decay_rate=0.3,
        )
        seg = result["segments"][0]
        # peak = 5/10 = 0.5, first decay tick: 0.5 * (1-0.3) = 0.35
        assert seg["congestion_level"] == pytest.approx(0.35, abs=1e-6)

    def test_decay_over_multiple_ticks(self):
        """Congestion should decay multiplicatively over successive ticks."""
        index = [
            {
                "start_mi": 0.0,
                "end_mi": 1.0,
                "coordinates": [[-87.63, 41.87], [-87.63, 41.88]],
                "road_name": "Main St",
            }
        ]
        decay_rate = 0.3
        max_ticks = 10
        # Segment was closed for 10 ticks -> peak = 1.0
        state = {"Main St": {"closed": 10, "peak": None}}

        congestion_values = []
        for tick in range(11, 16):
            result = compute_tick_traffic(
                segment_index=index,
                sweep_distance_mi=1.0,
                current_tick=tick,
                ticks_closed=state,
                max_congestion_ticks=max_ticks,
                congestion_decay_rate=decay_rate,
            )
            state = result["ticks_closed"]
            congestion_values.append(result["segments"][0]["congestion_level"])

        # Verify multiplicative decay: each value = prev * (1 - 0.3)
        # Tick 1: 1.0 * 0.7 = 0.7
        # Tick 2: 0.7 * 0.7 = 0.49
        # Tick 3: 0.49 * 0.7 = 0.343
        # Tick 4: 0.343 * 0.7 = 0.2401
        # Tick 5: 0.2401 * 0.7 = 0.16807
        assert congestion_values[0] == pytest.approx(0.7, abs=1e-6)
        assert congestion_values[1] == pytest.approx(0.49, abs=1e-6)
        assert congestion_values[2] == pytest.approx(0.343, abs=1e-6)
        assert congestion_values[3] == pytest.approx(0.2401, abs=1e-6)
        assert congestion_values[4] == pytest.approx(0.16807, abs=1e-6)

        # Each value should be strictly less than the previous
        for i in range(1, len(congestion_values)):
            assert congestion_values[i] < congestion_values[i - 1]

    # -------------------------------------------------------------------
    # Issue 2 coverage: TEV formula
    # -------------------------------------------------------------------

    def test_tev_exact_formula(self):
        """TEV should equal -$25 * 50 * overall_congestion."""
        index = self._make_index()
        result = compute_tick_traffic(
            segment_index=index,
            sweep_distance_mi=0.0,
            current_tick=3,
            ticks_closed={"Seg A": 2, "Seg B": 2},
        )
        expected_tev = -25.0 * 50.0 * result["overall_congestion"]
        assert result["tev_impact"] == pytest.approx(expected_tev, abs=1e-6)

    # -------------------------------------------------------------------
    # Issue 3 coverage: 1-coord matching boundary
    # -------------------------------------------------------------------

    def test_single_coord_match_not_closed(self):
        """A network segment with only 1 matching coord should NOT be closed."""
        route = _fc([_line_feature([[-87.63, 41.87], [-87.63, 41.88]], "Route")])
        # Network segment shares only one endpoint with the route
        network = _fc(
            [
                _line_feature(
                    [[-87.63, 41.87], [-87.70, 41.90]],
                    "Tangent Rd",
                )
            ]
        )
        result = identify_closed_segments(route, network)
        closed_names = [f["properties"]["name"] for f in result["closed"]]
        assert "Tangent Rd" not in closed_names
