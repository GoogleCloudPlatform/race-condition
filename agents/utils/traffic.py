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

"""Core traffic analysis library.

Shared pure-code functions for route segment indexing, closed-segment
identification, and per-tick congestion modelling.
"""

from __future__ import annotations

import math

# Threshold for coordinate matching (miles).
_MATCH_THRESHOLD_MI = 0.05


# ---------------------------------------------------------------------------
# Public boundary validator
# ---------------------------------------------------------------------------


def validate_route_geojson(route: object) -> tuple[bool, str]:
    """Validate the shape of a route GeoJSON FeatureCollection.

    Used at wire boundaries (e.g. simulator's ``prepare_simulation``) to
    reject route values whose shape would crash downstream traffic helpers
    that iterate ``features`` and call ``.get()`` on each entry.

    Permissive contract: a missing ``features`` key is allowed (downstream
    consumers skip traffic-model construction in that case).  The validator
    only rejects shapes that WOULD crash an iteration over ``features``.

    Returns:
        (True, "") if ``route`` is a dict and either ``features`` is absent
        or is a list of dicts.  Otherwise (False, reason).
    """
    if not isinstance(route, dict):
        return False, f"route_geojson must be a dict, got {type(route).__name__}"
    if "features" not in route:
        return True, ""
    feats = route["features"]
    if not isinstance(feats, list):
        return False, f"route_geojson.features must be a list, got {type(feats).__name__}"
    for i, f in enumerate(feats):
        if not isinstance(f, dict):
            return False, f"features[{i}] must be a Feature object, got {type(f).__name__}"
    return True, ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _haversine(coord1: list[float], coord2: list[float]) -> float:
    """Great-circle distance in miles between two [lon, lat] coordinates.

    Uses Earth radius of 3958.8 miles, matching the canonical implementation
    in ``agents/planner/skills/gis-spatial-engineering/tools.py:194``.
    """
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _coords_match(c1: list[float], c2: list[float]) -> bool:
    """Return True if two coords are within 0.05 mi of each other."""
    return _haversine(c1, c2) < _MATCH_THRESHOLD_MI


def _find_network_junctions(network_geojson: dict) -> set[tuple[float, float]]:
    """Return coordinates shared by 2+ differently-named roads.

    These are junction/intersection points where traffic can reroute.
    Coordinates are rounded to 6 decimal places for stable comparison.

    .. note::
       This uses exact coordinate matching (rounded), not haversine
       proximity.  The network GeoJSON is assumed to have snapped
       coordinates at junctions (i.e. roads that intersect share the
       exact same coordinate values).  This is standard for
       well-formed road network data.
    """
    coord_roads: dict[tuple[float, float], set[str]] = {}

    for feature in network_geojson.get("features", []):
        geom = feature.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        name = feature.get("properties", {}).get("name", "")
        for coord in geom["coordinates"]:
            key = (round(coord[0], 6), round(coord[1], 6))
            coord_roads.setdefault(key, set()).add(name)

    return {k for k, names in coord_roads.items() if len(names) >= 2}


def _segment_has_route_edge(
    seg_coords: list[list[float]],
    route_edges: set[tuple[tuple[float, float], tuple[float, float]]],
) -> bool:
    """Return True if any consecutive coord pair in *seg_coords* is a route edge.

    This prevents false closures from cross-streets whose endpoints
    coincidentally match coordinates on two different route-following roads.
    """
    for i in range(len(seg_coords) - 1):
        a = (round(seg_coords[i][0], 6), round(seg_coords[i][1], 6))
        b = (round(seg_coords[i + 1][0], 6), round(seg_coords[i + 1][1], 6))
        if (a, b) in route_edges:
            return True
    return False


def _is_route_line(
    seg_coords: list[list[float]],
    route_edges: set[tuple[tuple[float, float], tuple[float, float]]],
) -> bool:
    """Return True if *every* edge of the segment is a route edge.

    A segment whose geometry exactly follows the marathon route path is
    considered a "route line".  These segments are still treated as closed
    for traffic calculations (affected segments, intersections) but should
    be excluded from the output ``closed`` list because they *are* the
    route itself rather than collateral closures.
    """
    if len(seg_coords) < 2:
        return False
    for i in range(len(seg_coords) - 1):
        a = (round(seg_coords[i][0], 6), round(seg_coords[i][1], 6))
        b = (round(seg_coords[i + 1][0], 6), round(seg_coords[i + 1][1], 6))
        if (a, b) not in route_edges:
            return False
    return True


def _split_road_at_closure(
    seg_coords: list[list[float]],
    matched: list[bool],
    junctions: set[tuple[float, float]],
    road_name: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split a road into closed, affected, and open sub-features.

    Args:
        seg_coords: The road's coordinate list.
        matched: Boolean per coordinate indicating route overlap.
        junctions: Set of junction coordinate tuples (from
            ``_find_network_junctions``).
        road_name: Name for generated sub-features.

    Returns:
        ``(closed_features, affected_features, open_features)`` -- each a list
        of GeoJSON LineString Features.
    """
    # --- find contiguous runs of matched coords (>= 2 long) -----------------
    runs: list[tuple[int, int]] = []  # inclusive (start, end) index pairs
    start: int | None = None
    for i, m in enumerate(matched):
        if m:
            if start is None:
                start = i
        else:
            if start is not None:
                if i - start >= 2:
                    runs.append((start, i - 1))
                start = None
    if start is not None and len(matched) - start >= 2:
        runs.append((start, len(matched) - 1))

    if not runs:
        return [], [], []

    def _make_feature(coords: list[list[float]]) -> dict:
        return {
            "type": "Feature",
            "properties": {"name": road_name},
            "geometry": {"type": "LineString", "coordinates": coords},
        }

    def _coord_key(c: list[float]) -> tuple[float, float]:
        return (round(c[0], 6), round(c[1], 6))

    closed_features: list[dict] = []
    affected_features: list[dict] = []
    open_features: list[dict] = []

    # --- build closed features -----------------------------------------------
    for rs, re in runs:
        closed_features.append(_make_feature(seg_coords[rs : re + 1]))

    # --- classify gaps / remainders ------------------------------------------
    # Boundaries: before first run, between runs, after last run.
    # Each entry: (start_idx, end_idx, left_touches_closure, right_touches_closure)
    boundaries: list[tuple[int, int, bool, bool]] = []

    # Before first run
    if runs[0][0] > 0:
        boundaries.append((0, runs[0][0], False, True))

    # Between runs
    for i in range(len(runs) - 1):
        boundaries.append((runs[i][1], runs[i + 1][0], True, True))

    # After last run
    if runs[-1][1] < len(seg_coords) - 1:
        boundaries.append((runs[-1][1], len(seg_coords) - 1, True, False))

    for b_start, b_end, left_adj, right_adj in boundaries:
        sub_coords = seg_coords[b_start : b_end + 1]
        if len(sub_coords) < 2:
            continue

        if not left_adj and not right_adj:
            # Not adjacent to any closure (shouldn't happen but be safe).
            open_features.append(_make_feature(sub_coords))
            continue

        if left_adj and right_adj:
            # Gap between two closures.
            _classify_gap(sub_coords, junctions, affected_features, open_features, _make_feature, _coord_key)
        elif left_adj:
            # Right remainder (after a closure). Walk right to find junction.
            _classify_tail(
                sub_coords, junctions, affected_features, open_features, _make_feature, _coord_key, forward=True
            )
        else:
            # Left remainder (before a closure). Walk left to find junction.
            _classify_tail(
                sub_coords, junctions, affected_features, open_features, _make_feature, _coord_key, forward=False
            )

    return closed_features, affected_features, open_features


def _classify_gap(
    sub_coords: list[list[float]],
    junctions: set[tuple[float, float]],
    affected_out: list[dict],
    open_out: list[dict],
    make_feature,
    coord_key,
) -> None:
    """Classify a gap between two closures into affected/open sub-segments."""
    # Find nearest junction from left end (walking right).
    left_junc_idx: int | None = None
    for j in range(1, len(sub_coords) - 1):
        if coord_key(sub_coords[j]) in junctions:
            left_junc_idx = j
            break

    # Find nearest junction from right end (walking left).
    right_junc_idx: int | None = None
    for j in range(len(sub_coords) - 2, 0, -1):
        if coord_key(sub_coords[j]) in junctions:
            right_junc_idx = j
            break

    if left_junc_idx is not None and right_junc_idx is not None:
        if left_junc_idx <= right_junc_idx:
            affected_out.append(make_feature(sub_coords[: left_junc_idx + 1]))
            if left_junc_idx < right_junc_idx:
                open_out.append(make_feature(sub_coords[left_junc_idx : right_junc_idx + 1]))
            affected_out.append(make_feature(sub_coords[right_junc_idx:]))
        else:
            # Junctions overlap -- entire gap is affected.
            affected_out.append(make_feature(sub_coords))
    elif left_junc_idx is not None:
        affected_out.append(make_feature(sub_coords[: left_junc_idx + 1]))
        affected_out.append(make_feature(sub_coords[left_junc_idx:]))
    elif right_junc_idx is not None:
        affected_out.append(make_feature(sub_coords[: right_junc_idx + 1]))
        affected_out.append(make_feature(sub_coords[right_junc_idx:]))
    else:
        # No junction in gap -- entire gap is affected.
        affected_out.append(make_feature(sub_coords))


def _classify_tail(
    sub_coords: list[list[float]],
    junctions: set[tuple[float, float]],
    affected_out: list[dict],
    open_out: list[dict],
    make_feature,
    coord_key,
    *,
    forward: bool,
) -> None:
    """Classify a tail remainder (before or after a closure)."""
    if forward:
        # Walk right from closure boundary to find nearest junction.
        junc_idx: int | None = None
        for j in range(1, len(sub_coords)):
            if coord_key(sub_coords[j]) in junctions:
                junc_idx = j
                break
        if junc_idx is not None:
            affected_out.append(make_feature(sub_coords[: junc_idx + 1]))
            if junc_idx < len(sub_coords) - 1:
                open_out.append(make_feature(sub_coords[junc_idx:]))
        else:
            affected_out.append(make_feature(sub_coords))
    else:
        # Walk left from closure boundary to find nearest junction.
        junc_idx = None
        for j in range(len(sub_coords) - 2, -1, -1):
            if coord_key(sub_coords[j]) in junctions:
                junc_idx = j
                break
        if junc_idx is not None:
            if junc_idx > 0:
                open_out.append(make_feature(sub_coords[: junc_idx + 1]))
            affected_out.append(make_feature(sub_coords[junc_idx:]))
        else:
            affected_out.append(make_feature(sub_coords))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_segment_distance_index(route_geojson: dict) -> list[dict]:
    """Build cumulative distance index from a route GeoJSON FeatureCollection.

    Walks LineString features, accumulates haversine distances.
    Non-LineString features are silently skipped.

    Returns a list of dicts with keys:
        ``start_mi``, ``end_mi``, ``coordinates``, ``road_name``
    """
    index: list[dict] = []
    cumulative = 0.0

    for feature in route_geojson.get("features", []):
        geom = feature.get("geometry", {})
        if geom.get("type") != "LineString":
            continue

        coords = geom["coordinates"]
        segment_dist = 0.0
        for i in range(len(coords) - 1):
            segment_dist += _haversine(coords[i], coords[i + 1])

        start_mi = cumulative
        end_mi = cumulative + segment_dist
        index.append(
            {
                "start_mi": start_mi,
                "end_mi": end_mi,
                "coordinates": coords,
                "road_name": feature.get("properties", {}).get("name", ""),
            }
        )
        cumulative = end_mi

    return index


def identify_closed_segments(route_geojson: dict, network_geojson: dict) -> dict:
    """Identify closed, affected, and intersection segments.

    Partially-overlapping roads are split into sub-segments: only the
    overlapping portion is marked closed.  Open remainders adjacent to a
    closure are marked affected up to the nearest junction (where another
    road meets); portions beyond the junction are open.

    Args:
        route_geojson: The marathon route as a GeoJSON FeatureCollection.
        network_geojson: The full road network as a GeoJSON FeatureCollection.

    Returns a dict with keys:
        ``closed``  – collateral closures: sub-segments with >= 2 contiguous
                      coords matching route coords within 0.05 mi, **excluding**
                      segments whose geometry exactly follows the route path.
        ``route_closures`` – segments whose every edge is a route edge.
                      These are the actual marathon route lines.  They are
                      still treated as closed for affected/intersection
                      calculations but are separated from ``closed`` because
                      they *are* the route rather than collateral impact.
        ``affected`` – non-closed sub-segments sharing an endpoint with a
                       closed segment, up to the nearest junction.
        ``intersections`` – closed endpoints shared by 2+ road segments, with
                           ``cross_streets`` list and ``impact_level``.
    """
    # Collect all route coordinates for matching and build an edge set
    # for filtering route-coincident segments from the output.
    route_coords: list[list[float]] = []
    route_edges: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    for feature in route_geojson.get("features", []):
        geom = feature.get("geometry", {})
        if geom.get("type") == "LineString":
            coords = geom["coordinates"]
            route_coords.extend(coords)
            for i in range(len(coords) - 1):
                a = (round(coords[i][0], 6), round(coords[i][1], 6))
                b = (round(coords[i + 1][0], 6), round(coords[i + 1][1], 6))
                route_edges.add((a, b))
                route_edges.add((b, a))

    # Pre-compute junction points (coords shared by 2+ named roads).
    junctions = _find_network_junctions(network_geojson)

    # Classify network segments.
    closed: list[dict] = []
    split_affected: list[dict] = []  # Affected from road splitting.
    open_segments: list[dict] = []
    # Track which original features were split so we exclude them from
    # intersection detection (their sub-segments replace them).
    split_originals: set[int] = set()

    for feature in network_geojson.get("features", []):
        geom = feature.get("geometry", {})
        if geom.get("type") != "LineString":
            continue

        seg_coords = geom["coordinates"]
        road_name = feature.get("properties", {}).get("name", "")

        # Build per-coordinate match flags.
        matched: list[bool] = []
        for sc in seg_coords:
            is_match = False
            for rc in route_coords:
                if _coords_match(sc, rc):
                    is_match = True
                    break
            matched.append(is_match)

        match_count = sum(matched)

        if match_count < 2:
            # No closure on this road.
            open_segments.append(feature)
        elif match_count == len(seg_coords):
            # Entire road matches route coordinates -- closed.
            closed.append(feature)
        else:
            # Partial overlap -- split into sub-segments.
            c, a, o = _split_road_at_closure(seg_coords, matched, junctions, road_name)
            if c:
                # Genuine partial closure: replace original with sub-segments.
                # Sub-segments with contiguous matching coords are closed
                # (either because the route follows them or because they
                # are trapped between two route-following roads).
                split_originals.add(id(feature))
                closed.extend(c)
                split_affected.extend(a)
                open_segments.extend(o)
            else:
                # Scattered matches with no contiguous run of >= 2.
                open_segments.append(feature)

    # Collect endpoints of closed segments.
    closed_endpoints: list[list[float]] = []
    for feature in closed:
        coords = feature["geometry"]["coordinates"]
        closed_endpoints.append(coords[0])
        closed_endpoints.append(coords[-1])

    # Affected: merge split-produced affected segments with cross-street
    # segments that share an endpoint with a closed segment.
    affected: list[dict] = list(split_affected)
    for feature in open_segments:
        coords = feature["geometry"]["coordinates"]
        endpoints = [coords[0], coords[-1]]
        is_affected = False
        for ep in endpoints:
            for cep in closed_endpoints:
                if _coords_match(ep, cep):
                    is_affected = True
                    break
            if is_affected:
                break
        if is_affected:
            affected.append(feature)

    # Intersections: closed endpoints shared by 2+ road segments.
    # Build the segment pool from non-split originals + all sub-segments.
    all_segments: list[dict] = [f for f in network_geojson.get("features", []) if id(f) not in split_originals]
    all_segments.extend(closed)
    all_segments.extend(split_affected)
    all_segments.extend(open_segments)
    intersections: list[dict] = []
    seen_endpoints: set[tuple[float, float]] = set()

    for cep in closed_endpoints:
        cep_key = (round(cep[0], 6), round(cep[1], 6))
        if cep_key in seen_endpoints:
            continue
        seen_endpoints.add(cep_key)

        # Find all segments that touch this endpoint.
        touching_streets: list[str] = []
        for seg in all_segments:
            geom = seg.get("geometry", {})
            if geom.get("type") != "LineString":
                continue
            seg_coords = geom["coordinates"]
            seg_endpoints = [seg_coords[0], seg_coords[-1]]
            for sep in seg_endpoints:
                if _coords_match(sep, cep):
                    name = seg.get("properties", {}).get("name", "Unknown")
                    if name not in touching_streets:
                        touching_streets.append(name)
                    break

        if len(touching_streets) >= 2:
            intersections.append(
                {
                    "coordinates": cep,
                    "cross_streets": touching_streets,
                    "impact_level": _intersection_impact(len(touching_streets)),
                }
            )

    # Separate route-coincident segments from collateral closures.
    # Route lines are still treated as closed for the calculations above
    # (affected segments, intersections) but should not appear in the
    # output ``closed`` list because they *are* the route.
    output_closed: list[dict] = []
    route_closures: list[dict] = []
    for seg in closed:
        if _is_route_line(seg["geometry"]["coordinates"], route_edges):
            route_closures.append(seg)
        else:
            output_closed.append(seg)

    return {
        "closed": output_closed,
        "route_closures": route_closures,
        "affected": affected,
        "intersections": intersections,
    }


def _intersection_impact(street_count: int) -> str:
    """Classify intersection impact based on how many streets converge."""
    if street_count >= 4:
        return "critical"
    if street_count >= 3:
        return "high"
    return "moderate"


def compute_tick_traffic(
    segment_index: list[dict],
    sweep_distance_mi: float,
    current_tick: int,
    ticks_closed: dict,
    max_congestion_ticks: int = 10,
    congestion_decay_rate: float = 0.3,
) -> dict:
    """Per-tick traffic computation for rolling road closures.

    Segments whose **midpoint** is behind the sweep distance are reopening
    (congestion decays from the peak level accumulated while closed).
    Segments ahead are closed (congestion builds proportionally to
    ``ticks_closed / max_congestion_ticks``, capped at 1.0).

    ``ticks_closed`` values are dicts:
        ``{"closed": int, "peak": float | None}``
    where *closed* counts consecutive ticks a segment has been closed and
    *peak* stores the congestion level at the moment the segment transitioned
    from closed to reopening (used as the starting point for decay).

    Returns a dict with:
        ``segments`` – list of per-segment dicts.
        ``overall_congestion`` – average congestion (0–1).
        ``tev_impact`` – negative dollar amount.
        ``ticks_closed`` – updated state dict.
    """
    # Normalise legacy plain-int entries to the current dict format.
    updated_ticks_closed: dict[str, dict] = {}
    for k, v in ticks_closed.items():
        if isinstance(v, dict):
            updated_ticks_closed[k] = dict(v)
        else:
            # Legacy int value: interpret as closed ticks, no peak yet.
            updated_ticks_closed[k] = {"closed": int(v), "peak": None}

    segments_out: list[dict] = []

    for seg in segment_index:
        name = seg["road_name"]
        midpoint_mi = (seg["start_mi"] + seg["end_mi"]) / 2
        state = updated_ticks_closed.get(name, {"closed": 0, "peak": None})

        # Determine if segment is behind the sweep (reopening) or ahead (closed).
        if midpoint_mi <= sweep_distance_mi:
            if state["closed"] > 0:
                # Transitioning from closed -> reopening this tick.
                # Record peak congestion at the moment of reopening.
                state["peak"] = min(1.0, state["closed"] / max_congestion_ticks)
                state["closed"] = 0

            # Decay from peak each tick.  peak stores the *current* decayed
            # congestion level; each tick multiplies by (1 - decay_rate).
            peak = state["peak"] if state["peak"] is not None else 0.0
            congestion = peak * max(0.0, 1.0 - congestion_decay_rate)
            state["peak"] = congestion

            if congestion <= 0.01:
                status = "open"
                congestion = 0.0
                state["peak"] = None
                ticks_since_reopened = 0
            else:
                status = "reopening"
                ticks_since_reopened = 1

            updated_ticks_closed[name] = state
        else:
            status = "closed"
            new_closed = state["closed"] + 1
            state["closed"] = new_closed
            state["peak"] = None  # Reset peak; not reopening.
            updated_ticks_closed[name] = state
            ticks_since_reopened = 0
            # Congestion builds proportionally, capped at 1.0.
            congestion = min(1.0, new_closed / max_congestion_ticks)

        segments_out.append(
            {
                "coordinates": seg["coordinates"],
                "status": status,
                "congestion_level": congestion,
                "ticks_closed": state["closed"],
                "ticks_since_reopened": ticks_since_reopened,
                "road_name": name,
            }
        )

    # Overall congestion: average across all segments.
    if segments_out:
        overall = sum(s["congestion_level"] for s in segments_out) / len(segments_out)
    else:
        overall = 0.0

    # TEV impact: -$25/vehicle/hr * 50 vehicles * congestion
    tev = -25.0 * 50.0 * overall

    return {
        "segments": segments_out,
        "overall_congestion": overall,
        "tev_impact": tev,
        "ticks_closed": updated_ticks_closed,
    }
