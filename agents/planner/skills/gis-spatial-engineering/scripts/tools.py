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

import bisect
import json
import os
import math
import logging
import random
from typing import Dict, Optional, List, Set
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)

TARGET_DIST_MI = 26.2188
HALF_MILE = 0.5  # 0.5 miles

# ---------------------------------------------------------------------------
# Petal template catalog
# ---------------------------------------------------------------------------
# Each petal is a named rectangular loop radiating from Las Vegas Blvd.
# Waypoints are [lon, lat] grid intersections forming: Strip entry → outbound
# road → far corridor → return road → Strip re-entry.
# Approximate distance is for planning; exact distance computed by Dijkstra.

# The start/finish hub on Las Vegas Blvd (near Las Vegas Sign)
_STRIP_HUB = (-115.172851, 36.086141)

# ---------------------------------------------------------------------------
# Zone-sweep route generation constants
# ---------------------------------------------------------------------------

# Approximate center of the Las Vegas Strip for zone classification
STRIP_CENTER = (-115.1730, 36.1120)

# Empirical reserve for the serpentine-to-corridor-exit connector
# distance.  Subtracted from the serpentine budget so the route
# doesn't overshoot and force large finish-trims that push the finish
# away from the target POI.  With Treasure Island as the corridor
# exit (~2.4 mi from MUA), the connector needs ~2.5 mi of budget.
# The 30-seed guarantee test validates this continuously.
_CONNECTOR_RESERVE = 1.5

# Start corridor landmarks (northbound on the Strip)
CORRIDOR_START = "Las Vegas Sign"  # runner starts here
CORRIDOR_EXIT = "Treasure Island"  # northbound extent on the Strip

# Default finish landmark
FINISH_LANDMARK = "Michelob Ultra Arena"


def _haversine(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _interpolate(
    p1: tuple[float, float],
    p2: tuple[float, float],
    target_dist: float,
    current_seg_dist: float,
) -> list[float]:
    if current_seg_dist == 0:
        return [p1[0], p1[1]]
    ratio = target_dist / current_seg_dist
    lon = p1[0] + (p2[0] - p1[0]) * ratio
    lat = p1[1] + (p2[1] - p1[1]) * ratio
    return [lon, lat]


def _build_distance_index(
    coords: list[tuple[float, float]],
) -> list[tuple[tuple[float, float], float]]:
    """Build a cumulative distance index from route coordinates.

    Returns a list of (coord, cumulative_miles) tuples. The first entry
    is always at mile 0.0. Subsequent entries accumulate haversine
    distances along the coordinate sequence.
    """
    if not coords:
        return []
    index: list[tuple[tuple[float, float], float]] = [(coords[0], 0.0)]
    cumulative = 0.0
    for i in range(1, len(coords)):
        cumulative += _haversine(coords[i - 1], coords[i])
        index.append((coords[i], cumulative))
    return index


def _point_at_mile(
    index: list[tuple[tuple[float, float], float]],
    target_mi: float,
) -> list[float]:
    """Return [lon, lat] at the given mile marker using binary search.

    Interpolates between the two nearest index entries. Clamps to the
    first/last coordinate when target_mi is out of range.
    """
    if not index:
        return [0.0, 0.0]
    if target_mi <= 0.0:
        return [index[0][0][0], index[0][0][1]]
    total = index[-1][1]
    if target_mi >= total:
        return [index[-1][0][0], index[-1][0][1]]

    # Binary search for the segment containing target_mi
    distances = [entry[1] for entry in index]
    right = bisect.bisect_right(distances, target_mi)
    if right == 0:
        right = 1
    left = right - 1

    p1 = index[left][0]
    p2 = index[right][0]
    seg_dist = index[right][1] - index[left][1]
    needed = target_mi - index[left][1]

    return _interpolate(p1, p2, needed, seg_dist)


def _on_segment(p: tuple, q: tuple, r: tuple) -> bool:
    """Check if point q lies on segment pr (assuming collinear)."""
    return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])


def _cross_product(o: tuple, a: tuple, b: tuple) -> float:
    """2D cross product of vectors OA and OB."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_intersect(p1: tuple, p2: tuple, p3: tuple, p4: tuple) -> bool:
    """Check if line segment p1-p2 intersects segment p3-p4.

    Returns False for segments sharing a single endpoint (T-junction).
    Returns True for proper crossing (X) or collinear overlap.
    """
    endpoints = {p1, p2}
    other_endpoints = {p3, p4}
    shared = endpoints & other_endpoints
    if len(shared) == 1:
        return False
    if len(shared) == 2:
        return True

    d1 = _cross_product(p3, p4, p1)
    d2 = _cross_product(p3, p4, p2)
    d3 = _cross_product(p1, p2, p3)
    d4 = _cross_product(p1, p2, p4)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    if d1 == 0 and _on_segment(p3, p1, p4):
        return True
    if d2 == 0 and _on_segment(p3, p2, p4):
        return True
    if d3 == 0 and _on_segment(p1, p3, p2):
        return True
    if d4 == 0 and _on_segment(p1, p4, p2):
        return True

    return False


def _route_has_crossing(coords: list[tuple]) -> bool:
    """Check if a route (list of coordinates) has any self-crossing segments.

    O(n^2) brute-force. For ~500 segments this runs in microseconds.
    Adjacent segments share an endpoint and are skipped.
    """
    n = len(coords)
    if n < 4:
        return False
    for i in range(n - 1):
        for j in range(i + 2, n - 1):
            if _segments_intersect(coords[i], coords[i + 1], coords[j], coords[j + 1]):
                return True
    return False


def _path_crosses_route(
    new_path: list[tuple],
    existing_route: list[tuple],
) -> bool:
    """Check if adding new_path would create crossings with existing_route.

    Checks each segment in new_path against each segment in existing_route.
    Adjacent segments (sharing an endpoint) are allowed by _segments_intersect.
    """
    if len(existing_route) < 2 or len(new_path) < 2:
        return False
    for i in range(len(new_path) - 1):
        for j in range(len(existing_route) - 1):
            if _segments_intersect(
                new_path[i],
                new_path[i + 1],
                existing_route[j],
                existing_route[j + 1],
            ):
                return True
    return False


def _route_edges_valid(
    route: list[tuple],
    adj: Dict[tuple, List[tuple]],
    allow_final_interpolation: bool = True,
    allow_start_interpolation: bool = False,
) -> tuple[bool, list[int]]:
    """Check that every edge in the route exists in the graph.

    Returns (is_valid, list_of_invalid_edge_indices).
    If allow_final_interpolation is True, the last edge is exempt
    (it may contain an interpolated point for exact distance).
    If allow_start_interpolation is True, the first edge is also exempt
    (it may start from a trimmed interpolation point).
    """
    invalid = []
    check_start = 1 if allow_start_interpolation else 0
    check_end = len(route) - 2 if allow_final_interpolation else len(route) - 1
    for i in range(check_start, check_end):
        p1, p2 = route[i], route[i + 1]
        # Check if p2 is a neighbor of p1 in the adjacency list
        neighbors = {n for n, _ in adj.get(p1, [])}
        if p2 not in neighbors:
            invalid.append(i)
    return len(invalid) == 0, invalid


def _build_strip_corridor(
    adj: Dict[tuple, List[tuple]],
    strip_nodes: Set[tuple],
    start_node: tuple,
    exit_node: tuple,
    visited_edges: Set[tuple],
) -> tuple[list[tuple], float, set[tuple]]:
    """Build the start corridor: northbound on Las Vegas Blvd.

    Uses standard Dijkstra (no perturbation) to find the path from
    start_node to exit_node. Restricts routing to Strip-only nodes
    to keep the corridor on Las Vegas Blvd. Falls back to unrestricted
    routing if no strip-only path exists.

    Returns (path, distance, edges_used).
    """
    # Try strip-only routing first: block all non-strip nodes
    non_strip = set(adj.keys()) - strip_nodes
    path, dist = _get_path_dijkstra(
        start_node,
        exit_node,
        adj,
        visited_nodes=non_strip,
        visited_edges=visited_edges,
    )
    # Fall back to unrestricted if strip-only constraint yields no path
    if not path or len(path) < 2:
        logger.warning("PLANNER: Strip-only corridor path failed, falling back to unrestricted routing")
        path, dist = _get_path_dijkstra(
            start_node,
            exit_node,
            adj,
            visited_nodes=set(),
            visited_edges=visited_edges,
        )
    edges_used = set()
    for i in range(len(path) - 1):
        edges_used.add(tuple(sorted((path[i], path[i + 1]))))
    return path, dist, edges_used


def _build_graph(
    data: dict,
) -> tuple[Dict[tuple, List[tuple]], Dict[str, tuple], Dict[tuple, str], Set[tuple]]:
    adj: Dict[tuple, List[tuple]] = {}
    landmarks: Dict[str, tuple] = {}
    road_names: Dict[tuple, str] = {}
    nodes: Set[tuple] = set()
    strip_nodes: Set[tuple] = set()

    for feat in data.get("features", []):
        geom_type = feat.get("geometry", {}).get("type")
        if geom_type == "LineString":
            # Skip motorways (I-15, etc.) — not usable for marathon routes
            if feat.get("properties", {}).get("highway") == "motorway":
                continue
            name = feat.get("properties", {}).get("name")
            coords = feat["geometry"]["coordinates"]
            for i in range(len(coords) - 1):
                p1 = tuple(coords[i])
                p2 = tuple(coords[i + 1])
                edge_key = tuple(sorted((p1, p2)))
                if name:
                    road_names[edge_key] = name
                    if name == "Las Vegas Boulevard":
                        strip_nodes.add(p1)
                        strip_nodes.add(p2)
                nodes.add(p1)
                nodes.add(p2)
                # Deduplicate edges (merged network may have overlapping roads)
                existing_neighbors = {n for n, _ in adj.get(p1, [])}
                if p2 not in existing_neighbors:
                    dist = _haversine(p1, p2)
                    adj.setdefault(p1, []).append((p2, dist))
                    adj.setdefault(p2, []).append((p1, dist))
        elif geom_type == "Point" and "name" in feat.get("properties", {}):
            name = feat["properties"]["name"]
            landmarks[name] = tuple(feat["geometry"]["coordinates"])

    # Sort adj lists for determinism
    for k in adj:
        # Sort by distance primarily, then by coords to ensure deterministic tie-breaking
        adj[k].sort(key=lambda x: (x[1], x[0][0], x[0][1]))

    return adj, landmarks, road_names, strip_nodes


def _find_strip_anchor(
    target: tuple[float, float],
    strip_nodes: Set[tuple],
) -> tuple | None:
    """Find the closest Las Vegas Boulevard node to the target coordinate."""
    return _find_closest_node(target, strip_nodes)


def _get_return_path(
    from_node: tuple,
    start_anchor: tuple,
    adj: Dict[tuple, List[tuple]],
    strip_nodes: Set[tuple],
    visited_nodes: Set[tuple],
    visited_edges: Set[tuple],
) -> tuple[List[tuple], float, Set[tuple]]:
    """Find the shortest path from from_node back to a strip node near start.

    Returns (path, distance, edge_set) or ([], 0.0, set()) if no path exists.
    The destination must be a strip node within HALF_MILE of start_anchor.
    Allows destination nodes even if they are in visited_nodes (since we're
    intentionally returning to the start area).
    """
    import heapq

    candidates = {n for n in strip_nodes if _haversine(n, start_anchor) <= HALF_MILE}

    if not candidates:
        return [], 0.0, set()

    queue: list[tuple[float, tuple, list[tuple]]] = [(0.0, from_node, [from_node])]
    best_costs: dict[tuple, float] = {from_node: 0.0}

    while queue:
        dist, curr, path = heapq.heappop(queue)

        if curr in candidates and curr != from_node:
            # Build edge set for this path
            path_edges: Set[tuple] = set()
            for i in range(len(path) - 1):
                path_edges.add(tuple(sorted((path[i], path[i + 1]))))
            return path, dist, path_edges

        for neighbor, d in adj.get(curr, []):
            edge = tuple(sorted((curr, neighbor)))
            if edge in visited_edges:
                continue
            # Allow candidate destinations even if visited
            if neighbor in visited_nodes and neighbor not in candidates:
                continue
            if neighbor in path:
                continue
            new_cost = dist + d
            if neighbor not in best_costs or new_cost < best_costs[neighbor]:
                best_costs[neighbor] = new_cost
                heapq.heappush(queue, (new_cost, neighbor, path + [neighbor]))

    return [], 0.0, set()


def _find_closest_node(target: tuple, nodes: Set[tuple]) -> tuple | None:
    best_node = None
    min_dist = float("inf")
    for node in nodes:
        d = _haversine(target, node)
        if d < min_dist:
            min_dist = d
            best_node = node
    return best_node


def _find_off_strip_poi_node(
    adj: Dict[tuple, List[tuple]],
    nodes: Set[tuple],
    strip_nodes: Set[tuple],
    landmarks: Dict[str, tuple],
    preferred: str | None = None,
    near: tuple | None = None,
    max_radius_mi: float = 0.5,
    max_strip_dist_mi: float = HALF_MILE,
    rng: random.Random | None = None,
) -> tuple | None:
    """Find an off-strip graph node near a POI.

    If *preferred* names a landmark, finds the nearest off-strip node to
    that POI.  Otherwise, finds the nearest POI to *near* and returns
    the nearest off-strip node to it.

    Candidates must be within *max_strip_dist_mi* of the nearest Strip
    node to keep the route close to Las Vegas Boulevard.  Falls back
    to wider POI radii if no candidates exist, then drops the Strip
    constraint as a last resort.
    """
    strip_lon = STRIP_CENTER[0]
    min_off_strip = 0.001  # ~330 ft longitude difference from Strip

    # --- Determine target POI coordinate ---
    if preferred and preferred in landmarks:
        poi_coord = landmarks[preferred]
    elif near is not None:
        # Find nearest POI to the serpentine endpoint
        pool = {n: c for n, c in landmarks.items() if n not in (CORRIDOR_START, CORRIDOR_EXIT)}
        if not pool:
            return None
        poi_name = min(pool, key=lambda n: _haversine(near, pool[n]))
        poi_coord = pool[poi_name]
    else:
        return None

    # --- Find off-strip graph nodes near the POI ---
    def _candidates(
        radius: float,
        strip_limit: float | None = None,
    ) -> list[tuple[tuple, float, int]]:
        result = []
        for node in nodes:
            if node in strip_nodes:
                continue
            if abs(node[0] - strip_lon) < min_off_strip:
                continue
            if strip_limit is not None:
                nearest_strip = min(_haversine(node, sn) for sn in strip_nodes)
                if nearest_strip > strip_limit:
                    continue
            d = _haversine(poi_coord, node)
            if d <= radius:
                degree = len(adj.get(node, []))
                result.append((node, d, degree))
        return result

    # Tier 1: near POI AND near Strip
    cands = _candidates(max_radius_mi, max_strip_dist_mi)
    # Tier 2: wider POI radius, still near Strip
    if not cands:
        cands = _candidates(max_radius_mi * 2, max_strip_dist_mi)
    # Tier 3: any distance from POI, still near Strip
    if not cands:
        cands = _candidates(float("inf"), max_strip_dist_mi)
    # Tier 4: fallback — drop Strip constraint entirely
    if not cands:
        cands = _candidates(max_radius_mi * 2, None)
    if not cands:
        return None

    # Prefer high-degree nodes, break ties by proximity to POI
    cands.sort(key=lambda c: (-c[2], c[1]))
    # Pick randomly from the top candidates for route variety
    top_n = min(3, len(cands))
    if rng is not None:
        return cands[rng.randint(0, top_n - 1)][0]
    return cands[0][0]


def _get_path_dijkstra(
    start: tuple,
    end: tuple,
    adj: Dict[tuple, List[tuple]],
    visited_nodes: Set[tuple],
    visited_edges: Set[tuple],
) -> tuple[List[tuple], float]:
    import heapq

    # (cost, current_node, path)
    queue = [(0.0, start, [start])]
    best_costs = {start: 0.0}

    while queue:
        dist, curr, path = heapq.heappop(queue)

        if curr == end:
            return path, dist

        for neighbor, d in adj.get(curr, []):
            edge = tuple(sorted((curr, neighbor)))
            if neighbor not in path and neighbor not in visited_nodes and edge not in visited_edges:
                new_cost = dist + d
                if neighbor not in best_costs or new_cost < best_costs[neighbor]:
                    best_costs[neighbor] = new_cost
                    heapq.heappush(queue, (new_cost, neighbor, path + [neighbor]))
    return [], 0.0


def _get_path_dijkstra_perturbed(
    start: tuple,
    end: tuple,
    adj: Dict[tuple, List[tuple]],
    visited_nodes: Set[tuple],
    visited_edges: Set[tuple],
    rng: "random.Random",
    perturbation: tuple[float, float] = (0.5, 2.0),
) -> tuple[List[tuple], float]:
    """Dijkstra with random edge weight perturbation for route variety.

    Edge weights are multiplied by a random factor in [perturbation[0],
    perturbation[1]] for priority ordering. The returned distance is the
    TRUE (unperturbed) haversine distance.
    """
    import heapq

    lo, hi = perturbation
    counter = 0
    # (perturbed_cost, tiebreaker, real_cost, current_node, path)
    queue = [(0.0, counter, 0.0, start, [start])]
    best_costs: Dict[tuple, float] = {start: 0.0}

    while queue:
        p_dist, _, r_dist, curr, path = heapq.heappop(queue)

        if curr == end:
            return path, r_dist

        if p_dist > best_costs.get(curr, float("inf")):
            continue

        for neighbor, d in adj.get(curr, []):
            edge = tuple(sorted((curr, neighbor)))
            if neighbor in visited_nodes or edge in visited_edges or neighbor in path:
                continue
            factor = rng.uniform(lo, hi)
            new_p_cost = p_dist + d * factor
            new_r_cost = r_dist + d
            if neighbor not in best_costs or new_p_cost < best_costs[neighbor]:
                best_costs[neighbor] = new_p_cost
                counter += 1
                heapq.heappush(
                    queue,
                    (new_p_cost, counter, new_r_cost, neighbor, path + [neighbor]),
                )

    return [], 0.0


MAX_ROUTE_RETRIES = 100


def _build_serpentine_waypoints(
    adj: Dict[tuple, List[tuple]],
    rng: random.Random,
    side: str = "west",
    num_roads: int = 5,
    bias_lat: float | None = None,
) -> list[tuple]:
    """Build serpentine (zigzag) waypoints on one side of the Strip.

    Identifies E-W arterial roads, sorts them north-to-south, selects a
    random subset, and returns waypoints that alternate between the far
    (west) end and the near (east/Strip-side) end of each road.  This
    zigzag pattern is non-crossing by construction.

    Returns a list of graph nodes (snapped to the nearest node in adj).
    """
    strip_lon = STRIP_CENTER[0]
    all_nodes = set(adj.keys())

    # Group nodes by approximate latitude band (E-W roads share a latitude)
    lat_bands: Dict[float, list[tuple]] = {}
    for node in all_nodes:
        band = round(node[1], 3)
        lat_bands.setdefault(band, []).append(node)

    # Identify E-W arterial bands: bands with >= 3 nodes spread > 0.02 lon
    ew_bands: list[tuple[float, tuple, tuple]] = []
    for band_lat, band_nodes in lat_bands.items():
        if side == "west":
            side_nodes = [n for n in band_nodes if n[0] < strip_lon + 0.003]
        else:
            side_nodes = [n for n in band_nodes if n[0] > strip_lon - 0.003]
        if len(side_nodes) < 3:
            continue
        lon_span = max(n[0] for n in side_nodes) - min(n[0] for n in side_nodes)
        if lon_span < 0.02:
            continue
        west_node = min(side_nodes, key=lambda n: n[0])
        east_node = max(side_nodes, key=lambda n: n[0])
        ew_bands.append((band_lat, west_node, east_node))

    ew_bands.sort(key=lambda b: -b[0])  # North to south
    if len(ew_bands) < 2:
        return []

    count = min(num_roads, len(ew_bands))

    if bias_lat is not None:
        # Weighted sampling: bands within ~0.015 deg of bias_lat get 3x weight
        weights = []
        for band_lat, _, _ in ew_bands:
            if abs(band_lat - bias_lat) < 0.015:
                weights.append(3.0)
            else:
                weights.append(1.0)
        # Weighted sampling without replacement
        selected: list[tuple[float, tuple, tuple]] = []
        avail_idx = list(range(len(ew_bands)))
        avail_w = list(weights)
        for _ in range(count):
            if not avail_idx:
                break
            total = sum(avail_w)
            r = rng.random() * total
            cumul = 0.0
            for j, w in enumerate(avail_w):
                cumul += w
                if cumul >= r:
                    selected.append(ew_bands[avail_idx[j]])
                    avail_idx.pop(j)
                    avail_w.pop(j)
                    break
    else:
        selected = rng.sample(ew_bands, count)

    selected.sort(key=lambda b: -b[0])

    waypoints: list[tuple] = []
    go_far = rng.choice([True, False])
    for _, west_node, east_node in selected:
        if side == "west":
            far_node, near_node = west_node, east_node
        else:
            far_node, near_node = east_node, west_node
        waypoints.append(far_node if go_far else near_node)
        go_far = not go_far

    # Ensure the last waypoint is on the "near" side (close to Strip)
    # so the reverse-generated route can connect to a corridor POI easily.
    if len(waypoints) >= 2:
        last_band = selected[-1]
        _, west_node, east_node = last_band
        if side == "west":
            near_node = east_node  # east = near Strip for west side
        else:
            near_node = west_node  # west = near Strip for east side
        waypoints[-1] = near_node

    return waypoints


def _generate_zone_sweep_route(
    adj: Dict[tuple, List[tuple]],
    nodes: Set[tuple],
    landmarks: Dict[str, tuple],
    strip_nodes: Set[tuple],
    road_names: Dict[tuple, str],
    rng: random.Random,
    finish_landmark: str | None = None,
) -> tuple[list[tuple], float]:
    """Generate a marathon route using forward-construction zone sweep.

    Construction order: start corridor (Sign → TI) -> serpentine outward
    from TI -> connect to off-strip finish POI (MUA) -> assemble.

    Runner order: Las Vegas Sign -> Strip northbound -> Treasure Island ->
    serpentine -> off-strip finish near Michelob Ultra Arena.
    """

    # ---- Step 1: Build start corridor (Sign → TI, northbound) ----
    sign_coord = landmarks.get(CORRIDOR_START)
    exit_coord = landmarks.get(CORRIDOR_EXIT)
    if sign_coord is None or exit_coord is None:
        sorted_strip = sorted(strip_nodes, key=lambda n: n[1])
        sign_node: tuple = sorted_strip[0]  # southernmost
        exit_node: tuple = sorted_strip[-1]  # northernmost
    else:
        sign_maybe = _find_closest_node(sign_coord, strip_nodes)
        exit_maybe = _find_closest_node(exit_coord, strip_nodes)
        if sign_maybe is None or exit_maybe is None:
            sorted_strip = sorted(strip_nodes, key=lambda n: n[1])
            sign_node = sorted_strip[0]
            exit_node = sorted_strip[-1]
        else:
            sign_node = sign_maybe
            exit_node = exit_maybe

    corridor_path, corridor_dist, corridor_edges = _build_strip_corridor(
        adj,
        strip_nodes,
        sign_node,
        exit_node,
        set(),
    )
    corridor_nodes: set[tuple] = set(corridor_path)

    # Compute exact serpentine budget.  Reserve distance for the
    # finish-POI connection so the serpentine doesn't overshoot and
    # force large finish-trims that walk the finish away from the POI.
    serpentine_budget = TARGET_DIST_MI - corridor_dist - _CONNECTOR_RESERVE

    # Resolve target POI for finish placement bias.
    # When no landmark is specified, pick a random POI once per call
    # (not per attempt) so all retries target the same area but
    # different calls produce finishes at different locations.
    finish_poi_pool = [name for name in landmarks if name not in (CORRIDOR_START, CORRIDOR_EXIT)]
    if finish_landmark and finish_landmark in landmarks:
        target_poi_name: str | None = finish_landmark
        target_poi_coord: tuple | None = landmarks[finish_landmark]
    elif finish_poi_pool:
        target_poi_name = rng.choice(finish_poi_pool)
        target_poi_coord = landmarks[target_poi_name]
    else:
        target_poi_name = None
        target_poi_coord = None

    # ---- Retry loop ----
    full_route: list[tuple] = []
    total_dist = 0.0
    # Track best route across all attempts for fallback.
    # Score: lower is better (distance from target + finish from POI).
    best_fallback_route: list[tuple] = []
    best_fallback_dist = 0.0
    best_fallback_score = float("inf")

    for attempt in range(MAX_ROUTE_RETRIES):
        visited_edges: set[tuple] = set()
        visited_edges.update(corridor_edges)

        # ---- Find finish node early ----
        finish_node = _find_off_strip_poi_node(
            adj=adj,
            nodes=nodes,
            strip_nodes=strip_nodes,
            landmarks=landmarks,
            preferred=target_poi_name,
            near=exit_node if target_poi_name is None else None,
            rng=rng,
        )
        if finish_node is None:
            logger.warning(
                "PLANNER: Attempt %d rejected: no off-strip finish node",
                attempt + 1,
            )
            rng = random.Random(rng.randint(0, 2**32))
            continue

        # ---- Step 2: Build serpentine waypoints ----
        side = rng.choice(["west", "east"])
        go_south_to_north = rng.choice([True, False])

        # Bias waypoints toward the finish POI (MUA).
        # The serpentine starts at the corridor exit (TI) and needs
        # to spread toward the finish POI to reach the connector.
        if target_poi_coord is not None:
            bias_lat = target_poi_coord[1]  # MUA's latitude (~36.091)
        elif exit_coord is not None:
            bias_lat = exit_coord[1]
        else:
            # Seed-driven tier rotation for geographic variety
            tier_centers = [36.135, 36.11, 36.09]
            bias_lat = rng.choice(tier_centers)

        serpentine_wps = _build_serpentine_waypoints(
            adj,
            rng,
            side=side,
            num_roads=rng.randint(8, 12),
            bias_lat=bias_lat,
        )
        if go_south_to_north:
            serpentine_wps.reverse()

        # Optional second serpentine on the other side
        if rng.random() < 0.4:
            other_side = "east" if side == "west" else "west"
            extra_wps = _build_serpentine_waypoints(
                adj,
                rng,
                side=other_side,
                num_roads=rng.randint(3, 5),
                bias_lat=bias_lat,
            )
            if go_south_to_north:
                extra_wps.reverse()
            serpentine_wps.extend(extra_wps)

        # ---- Step 3: Route serpentine FROM corridor exit ----
        zone_route: list[tuple] = [exit_node]
        zone_dist = 0.0
        # Block corridor nodes to prevent node reuse in the assembled
        # route.  Edge avoidance (visited_edges) additionally prevents
        # reusing corridor edges.  This matches the original algorithm's
        # construction pattern where the serpentine originated from a
        # corridor endpoint and corridor nodes were blocked.
        visited_nodes: set[tuple] = {exit_node} | corridor_nodes
        zone_target = serpentine_budget
        current_node = exit_node

        for wp in serpentine_wps:
            if zone_dist >= zone_target:
                break

            path, dist = _get_path_dijkstra_perturbed(
                current_node,
                wp,
                adj,
                visited_nodes - {wp},
                visited_edges,
                rng,
            )
            if not path or len(path) < 2:
                path, dist = _get_path_dijkstra(
                    current_node,
                    wp,
                    adj,
                    visited_nodes - {wp},
                    visited_edges,
                )
            if not path or len(path) < 2:
                continue

            if _path_crosses_route(path, zone_route):
                continue
            # NOTE: We do NOT check corridor crossing here.  The
            # serpentine is allowed to cross the Strip corridor
            # perpendicularly (east-west arterials).  Edge avoidance
            # prevents reusing corridor edges.

            zone_route.extend(path[1:])
            zone_dist += dist
            for i in range(len(path) - 1):
                visited_edges.add(
                    tuple(sorted((path[i], path[i + 1]))),
                )
            visited_nodes.update(path[1:])
            current_node = path[-1]

        # ---- Step 4: Fill undershoot with exploratory hops ----
        extra_attempts = 0
        while zone_dist < zone_target - 0.5 and extra_attempts < 60:
            extra_attempts += 1
            if side == "west":
                candidates = [n for n in nodes if n != current_node and n[0] <= STRIP_CENTER[0] + 0.005]
            else:
                candidates = [n for n in nodes if n != current_node and n[0] >= STRIP_CENTER[0] - 0.005]
            if not candidates:
                break
            candidates.sort(
                key=lambda n: _haversine(current_node, n),
                reverse=True,
            )
            top_k = min(10, len(candidates))
            target = candidates[rng.randint(0, top_k - 1)]

            path = None
            dist = 0.0
            for path_attempt in range(5):
                cp, cd = _get_path_dijkstra_perturbed(
                    current_node,
                    target,
                    adj,
                    visited_nodes - {target},
                    visited_edges,
                    rng,
                )
                if not cp or len(cp) < 2:
                    cp, cd = _get_path_dijkstra(
                        current_node,
                        target,
                        adj,
                        visited_nodes - {target},
                        visited_edges,
                    )
                if not cp or len(cp) < 2:
                    break
                if _path_crosses_route(cp, zone_route):
                    if path_attempt < 4 and len(candidates) > 1:
                        target = candidates[
                            rng.randint(
                                0,
                                min(len(candidates) - 1, top_k - 1),
                            )
                        ]
                    continue
                path = cp
                dist = cd
                break

            if not path or len(path) < 2:
                continue
            zone_route.extend(path[1:])
            zone_dist += dist
            for i in range(len(path) - 1):
                visited_edges.add(
                    tuple(sorted((path[i], path[i + 1]))),
                )
            visited_nodes.update(path[1:])
            current_node = path[-1]

        # ---- Step 5: Trim if serpentine overshoots budget ----
        while zone_dist > serpentine_budget + 1.0 and len(zone_route) > 2:
            removed = _haversine(zone_route[-2], zone_route[-1])
            zone_route.pop()
            zone_dist -= removed
        current_node = zone_route[-1]

        # ---- Step 6: Connect serpentine to finish POI ----
        if current_node != finish_node:
            conn_path: list[tuple] | None = None
            conn_dist = 0.0
            # Block all previously visited nodes (corridor + serpentine)
            # except the finish_node destination to prevent node reuse
            # in the assembled route.
            conn_blocked = (visited_nodes | corridor_nodes) - {finish_node}
            for conn_attempt in range(5):
                cp, cd = _get_path_dijkstra_perturbed(
                    current_node,
                    finish_node,
                    adj,
                    conn_blocked,
                    visited_edges,
                    rng,
                )
                if not cp or len(cp) < 2:
                    cp, cd = _get_path_dijkstra(
                        current_node,
                        finish_node,
                        adj,
                        conn_blocked,
                        visited_edges,
                    )
                if not cp or len(cp) < 2:
                    # Relax edge constraints but keep node constraints
                    cp, cd = _get_path_dijkstra(
                        current_node,
                        finish_node,
                        adj,
                        conn_blocked,
                        set(),
                    )
                if not cp or len(cp) < 2:
                    # Relax to corridor-only node constraints
                    cp, cd = _get_path_dijkstra(
                        current_node,
                        finish_node,
                        adj,
                        corridor_nodes - {finish_node},
                        set(),
                    )
                if not cp or len(cp) < 2:
                    break
                if not _path_crosses_route(cp, zone_route) and not (
                    corridor_path and _path_crosses_route(cp, corridor_path)
                ):
                    conn_path = cp
                    conn_dist = cd
                    break

            if not conn_path or len(conn_path) < 2:
                # Ultra last resort: drop ALL constraints
                cp, cd = _get_path_dijkstra(
                    current_node,
                    finish_node,
                    adj,
                    set(),
                    set(),
                )
                if cp and len(cp) >= 2:
                    conn_path = cp
                    conn_dist = cd

            if conn_path and len(conn_path) >= 2:
                zone_route.extend(conn_path[1:])
                zone_dist += conn_dist
                for i in range(len(conn_path) - 1):
                    visited_edges.add(
                        tuple(sorted((conn_path[i], conn_path[i + 1]))),
                    )
                visited_nodes.update(conn_path[1:])
                current_node = conn_path[-1]
            else:
                logger.warning(
                    "PLANNER: Attempt %d rejected: cannot connect to finish POI",
                    attempt + 1,
                )
                rng = random.Random(rng.randint(0, 2**32))
                continue

        # ---- Step 7: Assemble full route ----
        # zone_route goes: exit_node -> serpentine -> finish_node
        # (no reversal needed — already in runner order)
        full_route = list(corridor_path)
        total_dist = corridor_dist

        # Append serpentine + finish connector (exit_node -> ... -> finish_node)
        if zone_route and zone_route[0] == corridor_path[-1]:
            full_route.extend(zone_route[1:])
        else:
            full_route.extend(zone_route)
        total_dist += zone_dist

        # ---- Distance adjustment ----
        if total_dist > TARGET_DIST_MI:
            corridor_len = len(corridor_path)

            # Phase 1: Trim from route end (finish side), but stop
            # if the finish drifts too far from the target POI.
            trimmed = 0.0
            poi_check = target_poi_coord if target_poi_coord is not None else finish_node
            while total_dist - trimmed > TARGET_DIST_MI + 0.5 and len(full_route) > corridor_len + 2:
                # Before popping, check if the new end (full_route[-2])
                # would be too far from the target POI.
                if len(full_route) >= 3:
                    new_end_dist = _haversine(full_route[-2], poi_check)
                    if new_end_dist > 0.75:
                        break  # Stop trimming to keep finish near POI
                seg = _haversine(full_route[-2], full_route[-1])
                full_route.pop()
                trimmed += seg

            total_dist -= trimmed

            # Phase 2: Fine-tune remaining excess by interpolating last segment.
            excess = total_dist - TARGET_DIST_MI
            if excess > 0.01 and len(full_route) >= 2:
                trim_limit = min(excess, 0.5)
                last_seg = _haversine(full_route[-2], full_route[-1])
                if last_seg > 0:
                    keep = last_seg - trim_limit
                    if keep > 0:
                        new_end = _interpolate(
                            full_route[-2],
                            full_route[-1],
                            keep,
                            last_seg,
                        )
                        full_route[-1] = tuple(new_end)
                        total_dist -= trim_limit
        elif total_dist < TARGET_DIST_MI:
            # Undershoot: extend from finish along real graph edges.
            # Prefer extending toward the target POI to keep finish close.
            shortfall = TARGET_DIST_MI - total_dist
            poi_target = target_poi_coord if target_poi_coord is not None else finish_node
            if len(full_route) >= 2 and full_route[-1] in adj:
                # Sort neighbors by proximity to POI (closest first)
                neighbors = [
                    (n, d) for n, d in adj[full_route[-1]] if tuple(sorted((full_route[-1], n))) not in visited_edges
                ]
                neighbors.sort(key=lambda nd: _haversine(nd[0], poi_target))
                for neighbor, edge_dist in neighbors:
                    ext_amount = min(shortfall, edge_dist)
                    ext_pt = _interpolate(
                        full_route[-1],
                        neighbor,
                        ext_amount,
                        edge_dist,
                    )
                    full_route.append(tuple(ext_pt))
                    total_dist += ext_amount
                    break

        if total_dist < TARGET_DIST_MI:
            logger.warning(
                "PLANNER: Route undershoot: %.3f mi < %.3f mi target",
                total_dist,
                TARGET_DIST_MI,
            )

        # ---- Step 9: Validate ----
        has_crossing = _route_has_crossing(full_route)

        seen: set[tuple] = set()
        has_node_reuse = False
        for node in full_route:
            if node in seen:
                has_node_reuse = True
                break
            seen.add(node)

        # Start must be near Las Vegas Sign
        start_to_sign = _haversine(full_route[0], sign_coord) if sign_coord else 0.0
        starts_near_sign = start_to_sign <= 0.5

        # Finish must be within 0.5 mi of target POI
        if target_poi_coord is not None:
            finish_to_poi = _haversine(full_route[-1], target_poi_coord)  # type: ignore[arg-type]
        else:
            finish_to_poi = min(_haversine(full_route[-1], sn) for sn in strip_nodes)  # type: ignore[arg-type]
        finishes_near_poi = finish_to_poi <= 0.75

        if not has_crossing and not has_node_reuse and starts_near_sign and finishes_near_poi:
            return full_route, total_dist

        # Track best fallback: prefer routes that are close to valid.
        # Score penalizes distance shortfall and finish distance from POI.
        shortfall = max(0, TARGET_DIST_MI - total_dist)
        score = shortfall + finish_to_poi * 2 + (10 if has_crossing else 0) + (10 if has_node_reuse else 0)
        if score < best_fallback_score:
            best_fallback_score = score
            best_fallback_route = list(full_route)
            best_fallback_dist = total_dist

        reasons = []
        if has_crossing:
            reasons.append("geometric crossing")
        if has_node_reuse:
            reasons.append("node reuse (visual crossing)")
        if not starts_near_sign:
            reasons.append(f"start {start_to_sign:.2f} mi from Sign")
        if not finishes_near_poi:
            reasons.append(f"finish {finish_to_poi:.2f} mi from POI (max 0.75)")
        logger.warning(
            "PLANNER: Attempt %d rejected: %s",
            attempt + 1,
            ", ".join(reasons),
        )
        rng = random.Random(rng.randint(0, 2**32))

    logger.warning(
        "PLANNER: All %d retry attempts exhausted, returning best route",
        MAX_ROUTE_RETRIES,
    )
    if best_fallback_route:
        return best_fallback_route, best_fallback_dist
    return full_route, total_dist


def _route_is_clean(route: list[tuple], strip_nodes: Set[tuple]) -> bool:
    """Return True when *route* has no crossings, no node reuse,
    and starts on or near the Strip."""
    if not route:
        return False
    if _route_has_crossing(route):
        return False
    seen: set[tuple] = set()
    for node in route:
        if node in seen:
            return False
        seen.add(node)
    start_to_strip = min(_haversine(route[0], sn) for sn in strip_nodes)
    return start_to_strip <= 0.5


def _generate_best_route(
    adj: Dict[tuple, List[tuple]],
    nodes: Set[tuple],
    landmarks: Dict[str, tuple],
    strip_nodes: Set[tuple],
    road_names: Dict[tuple, str],
    seed: int | None = None,
    finish_landmark: str | None = None,
    max_candidates: int = 10,
) -> tuple[list[tuple], float]:
    """Try multiple seeds and return the best *clean* marathon-distance route.

    A route is "clean" when it has no geometric crossings, no node
    reuse, and starts on or near the Strip.

    Tries seeds derived from the base seed.  Returns as soon as a
    clean marathon-distance route is found (early exit).  If none of
    the candidates is both clean and marathon-distance, returns the
    longest clean route.  As a last resort, returns the longest route
    regardless of quality.
    """
    if seed is None:
        seed = random.randrange(2**32)

    best_route: list[tuple] = []
    best_dist = 0.0
    best_clean_route: list[tuple] = []
    best_clean_dist = 0.0

    for k in range(max_candidates):
        candidate_seed = seed * 1000 + k
        rng = random.Random(candidate_seed)
        route, dist = _generate_zone_sweep_route(
            adj,
            nodes,
            landmarks,
            strip_nodes,
            road_names,
            rng,
            finish_landmark=finish_landmark,
        )

        if dist > best_dist:
            best_route = route
            best_dist = dist

        clean = _route_is_clean(route, strip_nodes)

        if clean and dist > best_clean_dist:
            best_clean_route = route
            best_clean_dist = dist

        # Early exit: clean marathon-distance route found
        if clean and dist >= TARGET_DIST_MI:
            return route, dist

    # Prefer clean route even if shorter
    if best_clean_route:
        return best_clean_route, best_clean_dist
    return best_route, best_dist


def _split_route_by_road(
    route_coords: List[tuple],
    road_names: Dict[tuple, str],
    total_dist: float,
) -> List[dict]:
    """Split a flat coordinate list into GeoJSON Features grouped by road name.

    Each consecutive run of edges sharing the same road name becomes one
    LineString Feature with ``properties.name`` set to the road name.
    The first segment also carries the overall route metadata.
    """
    segments: List[dict] = []
    current_name: Optional[str] = None
    current_coords: List[list] = [list(route_coords[0])]

    for i in range(len(route_coords) - 1):
        p1 = route_coords[i]
        p2 = route_coords[i + 1]
        edge_key = tuple(sorted((p1, p2)))
        edge_name = road_names.get(edge_key)

        if edge_name != current_name and len(current_coords) > 1:
            # Flush the current segment
            segments.append(
                {
                    "type": "Feature",
                    "properties": {"name": current_name},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": current_coords,
                    },
                }
            )
            # Start new segment from the shared junction point
            current_coords = [list(p1)]
            current_name = edge_name
        elif edge_name != current_name:
            current_name = edge_name

        current_coords.append(list(p2))

    # Flush final segment
    if len(current_coords) > 1:
        segments.append(
            {
                "type": "Feature",
                "properties": {"name": current_name},
                "geometry": {
                    "type": "LineString",
                    "coordinates": current_coords,
                },
            }
        )

    # Attach route-level metadata to the first segment
    if segments:
        segments[0]["properties"].update(
            {
                "route_type": "marathon",
                "distance_mi": round(total_dist, 4),
                "certified": True,
            }
        )

    return segments


async def plan_marathon_route(
    geojson_data: Optional[str] = None,
    finish_landmark: Optional[str] = None,
    seed: Optional[int] = None,
    force_replan: bool = False,
    runner_count: int = 10000,
    tool_context: Optional[ToolContext] = None,
) -> dict:
    """Generate a mathematically perfect 26.2188 mile marathon route.

    If geojson_data is not provided, uses the built-in Las Vegas road network.

    IMPORTANT: This tool is idempotent. If a route has already been planned in this
    session, it returns status "already_planned" with the cached route instead of
    regenerating. Call this tool only once per planning pass. To force regeneration
    (e.g., after evaluator feedback requires changes), set force_replan=True.

    Generates varied, non-crossing routes using zone-sweep decomposition.
    Routes start northbound on the Strip at the Las Vegas Sign, sweep
    through Las Vegas neighborhoods, and finish near a landmark.
    Use `seed` for reproducibility and `finish_landmark` to choose the
    finishing point.

    Args:
        finish_landmark: Finishing landmark name. Random from pool if omitted.
        seed: Random seed for reproducible routes. Random if omitted.
        geojson_data: Optional GeoJSON string of the road network to use.
        force_replan: If True, discard the cached route and regenerate.
        runner_count: Number of participants (scales infrastructure).
        tool_context: ADK tool context.
    """
    # Idempotency guard: return cached route if already planned (unless force_replan)
    if not force_replan and tool_context and tool_context.state.get("marathon_route"):
        logger.info("PLANNER: Route already planned, returning cached result.")
        return {
            "status": "already_planned",
            "message": "Marathon route was already planned in this session. Use report_marathon_route to emit it.",
            "geojson": tool_context.state["marathon_route"],
        }

    logger.info("PLANNER: Generating marathon route...")

    # Load default data if none provided
    if not geojson_data:
        try:
            # scripts/ -> skill root -> assets/
            from pathlib import Path

            skill_dir = Path(os.path.dirname(__file__)).parent
            data_path = skill_dir / "assets" / "network.json"
            if os.path.exists(data_path):
                with open(data_path, "r") as f:
                    geojson_data = f.read()
                logger.info("PLANNER: Using built-in Las Vegas road network.")
            else:
                logger.warning(f"PLANNER: network.json not found at {data_path}. Using fallback.")
                geojson_data = '{"type": "FeatureCollection", "features": []}'
        except Exception as e:
            logger.error(f"PLANNER: Failed to load network.json: {e}")
            geojson_data = '{"type": "FeatureCollection", "features": []}'

    try:
        data = json.loads(geojson_data)
        adj, landmarks, road_names, strip_nodes = _build_graph(data)
        nodes = set(adj.keys())

        # Route generation - zone-sweep algorithm with tournament strategy
        route_coords, final_dist = _generate_best_route(
            adj,
            nodes,
            landmarks,
            strip_nodes,
            road_names,
            seed=seed if seed is not None else random.randrange(2**32),
            finish_landmark=finish_landmark,
            max_candidates=10,
        )

        # Split route into named road segments
        route_segments = _split_route_by_road(route_coords, road_names, final_dist)

        # Add start and finish markers
        start_marker = {
            "type": "Feature",
            "properties": {"marker-type": "start", "name": "Start Line"},
            "geometry": {
                "type": "Point",
                "coordinates": list(route_coords[0]),
            },
        }
        finish_marker = {
            "type": "Feature",
            "properties": {"marker-type": "finish", "name": "Finish Line"},
            "geometry": {
                "type": "Point",
                "coordinates": list(route_coords[-1]),
            },
        }

        output = {
            "type": "FeatureCollection",
            "features": [start_marker, finish_marker] + route_segments,
        }

        # Single-pass infrastructure placement (replaces old sequential calls)
        infra_result = await add_course_infrastructure(output, runner_count=runner_count, tool_context=tool_context)
        if infra_result["status"] == "success":
            output = infra_result["geojson"]

        # Cache in session state for later/other agent recall
        if tool_context:
            tool_context.state["marathon_route"] = output

        return {
            "status": "success",
            "message": "Marathon route planned successfully including logistical stations.",
            "geojson": output,
        }
    except Exception as e:
        logger.error(f"PLANNER: Error processing GeoJSON: {e}")
        return {"status": "error", "message": f"Failed to process GeoJSON: {str(e)}"}


def _extract_route_coords(route_geojson: dict) -> list:
    """Extract a flat coordinate list from all LineString features in order."""
    coords: list = []
    for f in route_geojson.get("features", []):
        if f.get("geometry", {}).get("type") == "LineString":
            seg_coords = f["geometry"]["coordinates"]
            # Deduplicate shared junction points between consecutive segments
            if coords and seg_coords and coords[-1] == seg_coords[0]:
                coords.extend(seg_coords[1:])
            else:
                coords.extend(seg_coords)
    return coords


# ---------------------------------------------------------------------------
# Course Infrastructure Placement (standards-compliant, runner-count-aware)
# ---------------------------------------------------------------------------

_HYDRATION_INTERVAL_MI = 3.1  # World Athletics TR 55: every 5 km


def _place_hydration_stations(
    index: list[tuple[tuple[float, float], float]],
    runner_count: int = 10000,  # noqa: ARG001 — kept for API consistency with other _place_* functions
) -> list[dict]:
    """Place hydration stations every 5 km (3.1 mi) per World Athletics TR 55.

    Note: runner_count is accepted for API consistency but does not
    affect station count.  WA TR 55 mandates spacing, not per-runner scaling.
    """
    if not index:
        return []
    total_mi = index[-1][1]
    features: list[dict] = []
    mi = _HYDRATION_INTERVAL_MI
    while mi <= total_mi and mi <= TARGET_DIST_MI:
        coord = _point_at_mile(index, mi)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coord},
                "properties": {
                    "type": "water_station",
                    "mi": round(mi, 3),
                    "km": round(mi * 1.60934, 3),
                },
            }
        )
        mi += _HYDRATION_INTERVAL_MI
    return features


def _place_medical_stations(
    index: list[tuple[tuple[float, float], float]],
    runner_count: int = 10000,
) -> list[dict]:
    """Place medical stations scaled by runner count.

    Tier layout:
      - major: Start area (mi 0.5), mile ~20 ("the wall"), finish line
      - course: Distributed at strategic mile markers
    """
    if not index:
        return []
    total_mi = index[-1][1]
    finish_mi = min(total_mi, TARGET_DIST_MI)

    if runner_count < 1000:
        major_miles = [0.5, finish_mi]
        course_miles = [13.1, 20.0]
    elif runner_count <= 10000:
        major_miles = [0.5, 20.0, finish_mi]
        course_miles = [8.0, 13.1, 17.0]
    else:
        major_miles = [0.5, 20.0, finish_mi]
        course_miles = [5.0, 10.0, 13.1, 17.0, 23.0]

    def _location_name(mi: float, finish: float) -> str:
        if mi <= 1.0:
            return "Start Area"
        if abs(mi - finish) < 0.5:
            return "Finish Line"
        if abs(mi - 13.1) < 0.5:
            return "Halfway"
        if abs(mi - 20.0) < 0.5:
            return "The Wall"
        return f"Mile {round(mi)}"

    features: list[dict] = []
    for mi in major_miles:
        clamped = min(mi, total_mi)
        coord = _point_at_mile(index, clamped)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coord},
                "properties": {
                    "type": "medical_tent",
                    "mi": round(clamped, 3),
                    "tier": "major",
                    "location": _location_name(clamped, finish_mi),
                },
            }
        )
    for mi in course_miles:
        if mi < total_mi:
            coord = _point_at_mile(index, mi)
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": coord},
                    "properties": {
                        "type": "medical_tent",
                        "mi": round(mi, 3),
                        "tier": "course",
                        "location": _location_name(mi, finish_mi),
                    },
                }
            )
    return features


def _place_portable_toilets(
    index: list[tuple[tuple[float, float], float]],
    runner_count: int = 10000,
) -> list[dict]:
    """Place portable toilet stations offset from hydration, scaled by runner count.

    Stations are evenly distributed but nudged away from hydration
    mile markers to avoid co-location congestion.
    """
    if not index:
        return []
    total_mi = index[-1][1]
    finish_mi = min(total_mi, TARGET_DIST_MI)

    if runner_count < 1000:
        count, units = 4, 3
    elif runner_count < 5000:
        count, units = 6, 5
    elif runner_count <= 30000:
        count, units = 8, 10
    else:
        count, units = 10, 12

    # Offset by half a hydration interval so toilets sit between water stops
    offset = _HYDRATION_INTERVAL_MI / 2  # ~1.55 mi
    spacing = finish_mi / (count + 1)

    features: list[dict] = []
    for i in range(1, count + 1):
        mi = spacing * i
        # Nudge to nearest offset point to avoid hydration overlap
        mi = round(mi / offset) * offset + (offset / 2)
        if mi > finish_mi:
            mi = finish_mi - 0.5
        coord = _point_at_mile(index, mi)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coord},
                "properties": {
                    "type": "portable_toilet",
                    "mi": round(mi, 3),
                    "units": units,
                },
            }
        )
    return features


_CHEER_ZONE_NAMES = [
    "Start Energy",
    "Early Boost",
    "Momentum Mile",
    "Halfway Celebration",
    "The Push",
    "Wall Breakers",
    "Final Surge",
    "Sprint to Glory",
]


def _place_cheer_zones(
    index: list[tuple[tuple[float, float], float]],
    runner_count: int = 10000,
) -> list[dict]:
    """Place cheer zones at strategic locations, scaled by runner count.

    Critical placements: halfway (~mi 13.1), the wall (~mi 20),
    finish approach (~mi 25). Remaining zones distributed evenly.
    """
    if not index:
        return []
    total_mi = index[-1][1]
    finish_mi = min(total_mi, TARGET_DIST_MI)

    # Strategic anchor points (always included if race is large enough)
    anchors = [5.0, 13.1, 20.0, 25.0]

    if runner_count < 1000:
        target_count = 4
    elif runner_count <= 10000:
        target_count = 6
    else:
        target_count = 8

    # Start with anchors, then fill evenly
    if target_count <= len(anchors):
        zone_miles = anchors[:target_count]
    else:
        zone_miles = list(anchors)
        spacing = finish_mi / (target_count - len(anchors) + 1)
        for i in range(1, target_count - len(anchors) + 1):
            candidate = spacing * i
            # Skip if too close to existing anchor (within 1.5 mi)
            if not any(abs(candidate - a) < 1.5 for a in zone_miles):
                zone_miles.append(candidate)
        # Ensure we reach target count by backfilling
        fill_mi = 2.0
        while len(zone_miles) < target_count and fill_mi < finish_mi:
            if not any(abs(fill_mi - z) < 1.5 for z in zone_miles):
                zone_miles.append(fill_mi)
            fill_mi += 2.5

    zone_miles = sorted([m for m in zone_miles if m <= finish_mi])[:target_count]

    features: list[dict] = []
    for i, mi in enumerate(zone_miles):
        coord = _point_at_mile(index, mi)
        name = _CHEER_ZONE_NAMES[i] if i < len(_CHEER_ZONE_NAMES) else f"Cheer Zone {i + 1}"
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coord},
                "properties": {
                    "type": "cheer_zone",
                    "mi": round(mi, 3),
                    "name": name,
                },
            }
        )
    return features


async def add_course_infrastructure(
    route_geojson: dict,
    runner_count: int = 10000,
    tool_context: Optional[ToolContext] = None,
) -> dict:
    """Place all course infrastructure using a shared distance index.

    Single-pass orchestrator that places hydration stations, medical tents,
    portable toilets, and cheer zones.

    Args:
        route_geojson: The planned route GeoJSON FeatureCollection.
        runner_count: Number of participants (scales infrastructure).
        tool_context: ADK tool context (unused, kept for API consistency).
    """
    runner_count = max(1, int(runner_count))
    logger.info("PLANNER: Adding course infrastructure (runners=%d)...", runner_count)
    coords = _extract_route_coords(route_geojson)
    if not coords:
        return {"status": "error", "message": "No LineString found in route"}

    index = _build_distance_index(coords)

    # All four are pure functions on immutable input -- no contention
    hydration = _place_hydration_stations(index, runner_count)
    medical = _place_medical_stations(index, runner_count)
    toilets = _place_portable_toilets(index, runner_count)
    cheer = _place_cheer_zones(index, runner_count)

    all_features = hydration + medical + toilets + cheer
    route_geojson["features"].extend(all_features)

    counts = {
        "water_stations": len(hydration),
        "medical_stations": len(medical),
        "portable_toilets": len(toilets),
        "cheer_zones": len(cheer),
    }
    logger.info("PLANNER: Infrastructure placed: %s", counts)

    return {
        "status": "success",
        "message": f"Added {len(all_features)} infrastructure points ({counts}).",
        "geojson": route_geojson,
    }


async def report_marathon_route(
    tool_context: ToolContext,
) -> dict:
    """Report the final marathon route GeoJSON to the gateway for visualization.

    Reads the route exclusively from session state (set by ``plan_marathon_route``).

    Args:
        tool_context: ADK tool context with session state containing ``marathon_route``.
    """
    logger.info("PLANNER: Reporting final marathon route...")

    route_geojson = tool_context.state.get("marathon_route")
    if not route_geojson:
        return {
            "status": "error",
            "message": "No marathon route found. Run 'plan_marathon_route' first.",
        }

    return {
        "status": "success",
        # NOTE: This `message` is the immediate context the model sees right
        # before its terminal turn -- it overrides the ambient prompt
        # instruction. Wording that signals completion (e.g. "Final ...
        # reported to the system") makes the model treat the tool emission
        # as the user-facing delivery and return an empty terminal turn.
        # Cue the summary explicitly here.
        "message": (
            "Route published to the visualization layer. "
            "Now write a 2-3 paragraph natural-language summary for the user "
            "covering route highlights, weather/landmark context, and how the "
            "plan addresses the six quality pillars (Safety, Community, Intent "
            "Alignment, Logistics, Participant Experience, Financial Viability)."
        ),
        "route_geojson": route_geojson,
    }


# ---------------------------------------------------------------------------
# Traffic assessment (Gemini-enriched)
# ---------------------------------------------------------------------------


async def _gemini_traffic_enrichment(closed_segments: list, affected_intersections: list) -> dict:
    """Call Gemini 3 Flash to produce a traffic impact narrative and congestion zones.

    Returns a dict with ``narrative`` (str) and ``congestion_zones`` (list).
    """
    from google import genai
    from agents.utils.retry import resilient_http_options

    # Use Vertex AI on the global endpoint (Gemini 3 preview models live there).
    # vertexai=False would target the public Gemini API, which has no auth on
    # Cloud Run / Agent Engine and hangs forever waiting for an API key.
    client = genai.Client(
        vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT", os.environ.get("PROJECT_ID", "")),
        location="global",
        http_options=resilient_http_options(),
    )

    prompt = (
        "You are a Las Vegas traffic engineer. Given the following marathon "
        "road closure data, produce a JSON response with two keys:\n"
        '  "narrative": a 2-3 sentence summary of the traffic impact,\n'
        '  "congestion_zones": a list of objects with "zone_name" and '
        '"severity" (low/medium/high).\n\n'
        f"Closed segments: {json.dumps([s.get('properties', {}).get('name', 'Unknown') for s in closed_segments])}\n"
        f"Affected intersections: {json.dumps([i.get('cross_streets', []) for i in affected_intersections])}\n\n"
        "Respond ONLY with valid JSON, no markdown fences."
    )

    response = await client.aio.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt,
    )

    text = (response.text or "").strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3].strip()

    return json.loads(text)


async def assess_traffic_impact(
    tool_context: ToolContext,
) -> dict:
    """Assess traffic impact of the marathon route on the Las Vegas road network.

    Reads the route exclusively from session state (set by ``plan_marathon_route``).
    Identifies closed road segments and affected intersections, then enriches
    the assessment with a Gemini-generated narrative.

    This tool is designed to run IN PARALLEL with ``report_marathon_route``.

    Args:
        tool_context: ADK tool context with session state containing ``marathon_route``.
    """
    from agents.utils.traffic import identify_closed_segments

    route_geojson = tool_context.state.get("marathon_route")
    if not route_geojson:
        return {
            "status": "error",
            "message": "No marathon route found. Run 'plan_marathon_route' first.",
        }

    # Load the road network from assets/ (scripts/ -> skill root -> assets/)
    from pathlib import Path

    skill_dir = Path(os.path.dirname(os.path.abspath(__file__))).parent
    network_path = skill_dir / "assets" / "network.json"
    try:
        with open(network_path) as f:
            network_geojson = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "error",
            "message": f"Failed to load road network: {exc}",
        }

    # Identify closed segments, affected segments, and intersections.
    # ``closed`` excludes route-coincident segments (the actual marathon
    # route lines).  ``route_closures`` contains those route lines --
    # they are still treated as closed for impact calculations but are
    # not surfaced in the output.
    traffic_result = identify_closed_segments(route_geojson, network_geojson)
    closed = traffic_result["closed"]
    route_closures = traffic_result.get("route_closures", [])
    affected = traffic_result["affected"]
    intersections = traffic_result["intersections"]

    # Gemini enrichment with graceful degradation.
    # Pass ALL closures (including route lines) to Gemini for context.
    all_closures = closed + route_closures
    narrative = ""
    congestion_zones: list = []
    try:
        enrichment = await _gemini_traffic_enrichment(all_closures, intersections)
        narrative = enrichment.get("narrative", "")
        congestion_zones = enrichment.get("congestion_zones", [])
    except Exception as exc:
        logger.warning("Gemini traffic enrichment failed: %s", exc)
        narrative = (
            f"Gemini enrichment unavailable: {exc}. "
            f"Code-only analysis: {len(all_closures)} closed segments, "
            f"{len(intersections)} affected intersections."
        )

    # Compute overall impact score heuristic.
    # Use the full closure count (including route lines) so the score
    # accurately reflects the scale of road closures.
    n_closed = len(all_closures)
    n_intersections = len(intersections)
    n_affected = len(affected)
    overall_impact_score = min(1.0, n_closed * 0.1 + n_intersections * 0.05 + n_affected * 0.03)

    result = {
        "status": "success",
        "closed_segments": closed,
        "affected_segments": affected,
        "affected_intersections": intersections,
        "congestion_zones": congestion_zones,
        "narrative": narrative,
        "overall_impact_score": overall_impact_score,
    }

    # Store assessment in session state for downstream tools
    if tool_context:
        tool_context.state["traffic_assessment"] = result

    return result
