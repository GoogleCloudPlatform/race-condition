# Route Planning Architecture: The Spine and Sprout Algorithm

## Overview
The simulation needs to generate marathon routes of exactly 26.2 miles from a raw GeoJSON road network. Each route must:
1. Avoid self-intersections (form a simple path).
2. Connect a fixed sequence of landmarks in the network.
3. Hit exactly 26.2 miles by interpolating the final segment.

Naive greedy DFS and random walks were tried first. Both got trapped in cul-de-sacs and produced non-deterministic output. The **Spine and Sprout** algorithm replaced them with a deterministic two-phase approach.

## The Spine and Sprout Algorithm

The algorithmic approach divides the problem into two distinct phases: building a core structural path (the Spine) and extending it safely to the exact required distance (the Sprout).

### Phase 1: The Dijkstra Spine
To ensure the marathon route is of high quality and passes key thematic points, the algorithm begins by defining a set sequence of landmarks (e.g., the Las Vegas Sign → Allegiant Stadium → Sphere).

1. **Graph Construction:** The raw GeoJSON `LineString` elements are dynamically loaded into an adjacency list representation. The weight of each edge (road segment) is calculated precisely using the Haversine formula based on the `[longitude, latitude]` coordinates of the nodes.
2. **Shortest Path Matching:** A variation of Dijkstra's algorithm is applied sequentially to connect each landmark in the predefined theme sequence. This computes the optimal non-overlapping core path linking these major points of interest.

### Phase 2: The Bounded DFS Sprout
Once the core spine is created, the path is rarely exactly 26.2 miles. Phase 2 handles the deterministic extension.

1. **Guided Heuristics:** A modified Depth-First Search is initiated from the end of the spine. At each intersection (node), the algorithm must decide which path to take. To avoid dead-ends, the outbound edges are sorted by a degree-based heuristic: nodes that have the highest number of *unvisited* connected neighbors are prioritized. This naturally steers the path towards highly connected main roads and away from cul-de-sacs.
2. **Determinism:** To ensure consistent output across executions, ties in the degree heuristic are broken by sorting against segment distance, and finally by exact coordinate values.
3. **Exact Mathematical Interpolation:** As the DFS traverses and accumulates distance, it constantly checks if the next segment will exceed the 26.2-mile target. If the current accumulated distance plus the next adjacent segment distance exceeds the target, the algorithm:
   - Calculates the exact residual distance needed.
   - Computes a simple linear interpolation ratio (`remaining_distance / segment_length`).
   - Mathematically plots a final interpolated longitude and latitude coordinate.
   - Truncates the route precisely at this new coordinate to satisfy the exact marathon requirement.

## Road Name Segmentation

The `_build_graph` function tracks road names per edge from the GeoJSON
`properties.name` field on LineString features. After the route coordinate list
is generated, `_split_route_by_road` post-processes it into multiple LineString
Features, one per contiguous segment on the same named road. For example:

- Segment 1: "Las Vegas Boulevard South" (15 coordinates)
- Segment 2: "West Flamingo Road" (8 coordinates)
- Segment 3: unnamed (4 coordinates)

The first segment carries the overall route metadata (`route_type`,
`distance_mi`, `certified`). Water stations and medical tents are computed from
the concatenated coordinate list across all segments via `_extract_route_coords`.

## Adding Metadata Markers

Following the generation of the base route, secondary functions are applied to
decorate the `FeatureCollection` with required operational elements.

- **Water Stations (`add_water_stations`):** Concatenates all LineString
  coordinates via `_extract_route_coords`, then iterates over the full path
  accumulating distance. Utilizes interpolation logic to place a point feature
  exactly every ~1.86 miles along the physical path geometry.
- **Medical Tents (`add_medical_tents`):** Operates on the same concatenated
  coordinate list to insert a tent point exactly at the geometric halfway point
  (13.1 miles) and the finish line.

## Code Location

The implementation lives in
`agents/planner/skills/gis-spatial-engineering/scripts/tools.py`. Determinism
regression tests are at `agents/tests/test_planner_route_skill.py`.
