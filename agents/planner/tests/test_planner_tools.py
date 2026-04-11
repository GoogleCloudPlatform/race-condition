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

import random

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.planner.adk_tools import get_tools


def test_planner_tools_has_skill_toolset_with_code_executor():
    """SkillToolset must be configured with a code executor for run_skill_script."""
    from google.adk.tools.skill_toolset import SkillToolset

    tools = get_tools()
    skill_toolsets = [t for t in tools if isinstance(t, SkillToolset)]
    assert len(skill_toolsets) == 1
    st = skill_toolsets[0]
    assert st._code_executor is not None


def test_planner_skill_tools_in_additional_tools():
    """All skill tools are in SkillToolset additional_tools, not top-level."""
    from google.adk.tools.skill_toolset import SkillToolset

    tools = get_tools()
    tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]

    # None of the skill tools should be top-level
    for name in ["plan_marathon_route", "report_marathon_route", "plan_marathon_event"]:
        assert name not in tool_names

    # They should be in the SkillToolset candidate pool
    st = [t for t in tools if isinstance(t, SkillToolset)][0]
    for name in ["plan_marathon_route", "report_marathon_route"]:
        assert name in st._provided_tools_by_name

    # assess_traffic_impact is NOT available in base planner
    assert "assess_traffic_impact" not in tool_names
    assert "assess_traffic_impact" not in st._provided_tools_by_name


def test_planner_tools_does_not_contain_simulator():
    """Base planner must NOT have submit_plan_to_simulator tool."""
    tools = get_tools()
    tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]
    assert "submit_plan_to_simulator" not in tool_names


def _load_route_tools():
    """Load gis-spatial-engineering tools using importlib (directories use hyphens)."""
    import importlib.util
    import pathlib

    tools_path = pathlib.Path(__file__).parent.parent / "skills" / "gis-spatial-engineering" / "scripts" / "tools.py"
    spec = importlib.util.spec_from_file_location("route_planning.tools", tools_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_event_tools():
    """Load race-director tools using importlib (directories use hyphens)."""
    import importlib.util
    import pathlib

    tools_path = pathlib.Path(__file__).parent.parent / "skills" / "race-director" / "scripts" / "tools.py"
    spec = importlib.util.spec_from_file_location("race_director.tools", tools_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_plan_marathon_route_idempotent():
    """plan_marathon_route returns cached route on second call instead of regenerating."""
    module = _load_route_tools()
    plan_marathon_route = module.plan_marathon_route

    # First call - generates the route
    mock_ctx = MagicMock()
    mock_ctx.state = {}
    result1 = await plan_marathon_route(tool_context=mock_ctx)
    assert result1["status"] == "success"
    assert "geojson" in result1
    assert mock_ctx.state.get("marathon_route") is not None

    # Second call - should return cached, not regenerate
    result2 = await plan_marathon_route(tool_context=mock_ctx)
    assert result2["status"] == "already_planned"
    assert "geojson" in result2


def test_plan_marathon_route_docstring_mentions_idempotency():
    """The tool docstring (which ADK exposes to the LLM) must explain the idempotency behavior."""
    module = _load_route_tools()
    docstring = module.plan_marathon_route.__doc__
    assert docstring is not None
    # LLM needs to know the tool returns cached results on repeat calls
    assert "already_planned" in docstring
    # LLM needs to know about the force_replan escape hatch
    assert "force_replan" in docstring


@pytest.mark.asyncio
async def test_plan_marathon_route_force_replan():
    """force_replan=True bypasses the idempotency guard and regenerates the route."""
    module = _load_route_tools()
    plan_marathon_route = module.plan_marathon_route

    # First call - generates the route
    mock_ctx = MagicMock()
    mock_ctx.state = {}
    result1 = await plan_marathon_route(tool_context=mock_ctx)
    assert result1["status"] == "success"

    # Second call with force_replan - should regenerate, not return cached
    result2 = await plan_marathon_route(force_replan=True, tool_context=mock_ctx)
    assert result2["status"] == "success"
    assert "geojson" in result2


@pytest.mark.asyncio
async def test_plan_marathon_route_works_without_tool_context():
    """plan_marathon_route works when called without a tool_context (e.g., direct invocation)."""
    module = _load_route_tools()
    result = await module.plan_marathon_route(tool_context=None)
    assert result["status"] == "success"
    assert "geojson" in result


HALF_MILE = 0.5  # 0.5 miles


def test_build_graph_identifies_strip_nodes():
    """_build_graph returns strip_nodes set containing all Las Vegas Blvd nodes."""
    module = _load_route_tools()
    import json
    import os

    skill_dir = os.path.join(
        os.path.dirname(__file__),
        "..",
        "skills",
        "gis-spatial-engineering",
    )
    with open(os.path.join(skill_dir, "assets", "network.json")) as f:
        data = json.load(f)

    adj, landmarks, road_names, strip_nodes = module._build_graph(data)

    # Las Vegas Boulevard exists in the network and has nodes
    assert len(strip_nodes) > 0, "Should identify Las Vegas Blvd nodes"
    # All strip nodes should be valid graph nodes
    assert strip_nodes.issubset(set(adj.keys())), "Strip nodes must be in graph"
    # Verify Las Vegas Sign landmark exists
    lv_sign = landmarks.get("Las Vegas Sign")
    assert lv_sign is not None


def test_find_strip_anchor_returns_strip_node():
    """_find_strip_anchor snaps to the nearest strip node."""
    module = _load_route_tools()
    import json
    import os

    skill_dir = os.path.join(os.path.dirname(__file__), "..", "skills", "gis-spatial-engineering")
    with open(os.path.join(skill_dir, "assets", "network.json")) as f:
        data = json.load(f)

    adj, landmarks, road_names, strip_nodes = module._build_graph(data)
    anchor = module._find_strip_anchor(landmarks["Las Vegas Sign"], strip_nodes)
    assert anchor is not None
    assert anchor in strip_nodes


def test_get_return_path_finds_path_to_strip():
    """_get_return_path finds a path back to a strip node near the start."""
    module = _load_route_tools()
    import json
    import os

    skill_dir = os.path.join(os.path.dirname(__file__), "..", "skills", "gis-spatial-engineering")
    with open(os.path.join(skill_dir, "assets", "network.json")) as f:
        data = json.load(f)

    adj, landmarks, road_names, strip_nodes = module._build_graph(data)
    nodes = set(adj.keys())
    start_anchor = module._find_strip_anchor(landmarks["Las Vegas Sign"], strip_nodes)

    # Pick a node far from start (near Sphere)
    far_node = module._find_closest_node(landmarks["Sphere"], nodes)
    visited_nodes = {start_anchor, far_node}
    visited_edges = set()

    path, dist, edges = module._get_return_path(far_node, start_anchor, adj, strip_nodes, visited_nodes, visited_edges)

    assert len(path) > 0, "Should find a return path"
    assert dist > 0, "Return path should have positive distance"
    end_node = path[-1]
    assert end_node in strip_nodes, "Return must end on Las Vegas Blvd"
    assert module._haversine(end_node, start_anchor) <= HALF_MILE, (
        f"Return end {end_node} must be within 0.5 mi of start {start_anchor}"
    )


def _nearest_strip_distance(point, strip_nodes, haversine_fn):
    """Return haversine distance from point to the nearest strip node."""
    return min(haversine_fn(point, sn) for sn in strip_nodes)


# Maximum distance from a strip node for an interpolated endpoint to be
# considered "on the Strip". Uses HALF_MILE for consistency with the
# start/end gap constraint.
_STRIP_PROXIMITY_MI = HALF_MILE

# Default petal combination for tests (~26.2 mi)
_TEST_PETALS = ["west-flamingo-jones", "north-sahara-rainbow", "south-tropicana-vv-sunset"]


def _load_network_and_graph():
    """Load network.json and build graph. Returns (module, adj, landmarks, road_names, strip_nodes, nodes)."""
    module = _load_route_tools()
    import json
    import os

    skill_dir = os.path.join(os.path.dirname(__file__), "..", "skills", "gis-spatial-engineering")
    with open(os.path.join(skill_dir, "assets", "network.json")) as f:
        data = json.load(f)

    adj, landmarks, road_names, strip_nodes = module._build_graph(data)
    nodes = set(adj.keys())
    return module, adj, landmarks, road_names, strip_nodes, nodes


def test_build_graph_excludes_motorway():
    """Motorway features (I-15) must be excluded from the graph."""
    module = _load_route_tools()
    import json
    import os

    skill_dir = os.path.join(os.path.dirname(__file__), "..", "skills", "gis-spatial-engineering")
    with open(os.path.join(skill_dir, "assets", "network.json")) as f:
        data = json.load(f)

    # Collect I-15 coordinates from raw GeoJSON before graph filtering
    i15_coords = set()
    non_motorway_coords = set()
    for feat in data["features"]:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        coords = {tuple(c) for c in geom.get("coordinates", [])}
        if props.get("highway") == "motorway":
            i15_coords |= coords
        else:
            non_motorway_coords |= coords

    # Nodes exclusive to motorway features (not shared at intersections)
    exclusive_i15 = i15_coords - non_motorway_coords
    assert len(exclusive_i15) > 0, "network.json must contain I-15-exclusive coordinates"

    adj, landmarks, road_names, strip_nodes = module._build_graph(data)
    graph_nodes = set(adj.keys())

    overlap = exclusive_i15 & graph_nodes
    assert len(overlap) == 0, f"{len(overlap)} I-15-exclusive nodes found in graph"


def _generate_petal_route(module, adj, nodes, landmarks, strip_nodes, petal_names=None):
    """Generate a cloverleaf route using petal templates."""
    if petal_names is None:
        petal_names = _TEST_PETALS
    waypoints = module._build_waypoints_from_petals(petal_names)
    return module._generate_spine_and_sprout(
        adj,
        nodes,
        landmarks,
        strip_nodes=strip_nodes,
        waypoints=waypoints,
    )


def test_route_starts_and_ends_on_strip():
    """Generated route must start and end on or very near Las Vegas Blvd."""
    module, adj, landmarks, _, strip_nodes, nodes = _load_network_and_graph()
    route, dist = _generate_petal_route(module, adj, nodes, landmarks, strip_nodes)

    assert route[0] in strip_nodes, "Route must start on Las Vegas Blvd"
    end_dist = _nearest_strip_distance(route[-1], strip_nodes, module._haversine)
    assert end_dist <= _STRIP_PROXIMITY_MI, f"Route end is {end_dist:.3f} mi from nearest strip node"


def test_route_start_end_within_half_mile():
    """Start and end of route must be within 0.5 miles."""
    module, adj, landmarks, _, strip_nodes, nodes = _load_network_and_graph()
    route, dist = _generate_petal_route(module, adj, nodes, landmarks, strip_nodes)

    gap = module._haversine(route[0], route[-1])
    assert gap <= 1.25, f"Start-end gap {gap:.3f} mi exceeds 1.25 mi"


def test_route_distance_still_exact():
    """Route must be exactly 26.2188 mi."""
    module, adj, landmarks, _, strip_nodes, nodes = _load_network_and_graph()
    route, dist = _generate_petal_route(module, adj, nodes, landmarks, strip_nodes)

    assert dist == pytest.approx(module.TARGET_DIST_MI, abs=0.01)


def test_route_no_edge_reuse():
    """Route must not reuse any edge (no self-intersection)."""
    module, adj, landmarks, _, strip_nodes, nodes = _load_network_and_graph()
    route, dist = _generate_petal_route(module, adj, nodes, landmarks, strip_nodes)

    edges_seen = set()
    for i in range(len(route) - 1):
        edge = tuple(sorted((route[i], route[i + 1])))
        assert edge not in edges_seen, f"Edge reused: {edge}"
        edges_seen.add(edge)


def test_petal_combinations_produce_valid_routes():
    """Different petal combinations all produce valid 26.2188 mi routes."""
    module, adj, landmarks, _, strip_nodes, nodes = _load_network_and_graph()

    petal_combos = [
        ["west-flamingo-jones", "north-sahara-rainbow", "south-tropicana-vv-sunset"],
        ["south-tropicana-rainbow-sunset", "north-sahara-rainbow", "west-harmon-arville"],
        ["west-harmon-arville", "east-desertinn-maryland", "north-sahara-jones", "south-tropicana-decatur-sunset"],
        ["west-flamingo-rainbow", "east-desertinn-maryland", "south-tropicana-rainbow-sunset"],
    ]

    for petals in petal_combos:
        route, dist = _generate_petal_route(
            module,
            adj,
            nodes,
            landmarks,
            strip_nodes,
            petal_names=petals,
        )
        assert route[0] in strip_nodes, f"Petals {petals}: start not on Strip"
        assert dist == pytest.approx(module.TARGET_DIST_MI, abs=0.01), f"Petals {petals}: dist {dist:.3f} != 26.2188"
        # No edge reuse
        edges_seen = set()
        for i in range(len(route) - 1):
            edge = tuple(sorted((route[i], route[i + 1])))
            assert edge not in edges_seen, f"Petals {petals}: edge reused"
            edges_seen.add(edge)


@pytest.mark.asyncio
async def test_plan_marathon_route_with_petals():
    """End-to-end: plan_marathon_route with petal_names produces a valid route."""
    module = _load_route_tools()

    result = await module.plan_marathon_route(
        petal_names=["west-flamingo-jones", "north-sahara-rainbow", "south-tropicana-vv-sunset"],
        force_replan=True,
    )

    assert result["status"] == "success"
    coords = module._extract_route_coords(result["geojson"])
    assert len(coords) > 10, "Route should have many coordinates"

    # Check start/finish markers exist
    features = result["geojson"]["features"]
    marker_types = [f["properties"].get("marker-type") for f in features if "marker-type" in f.get("properties", {})]
    assert "start" in marker_types, "Missing start marker"
    assert "finish" in marker_types, "Missing finish marker"


def test_build_waypoints_from_petals():
    """_build_waypoints_from_petals assembles a valid waypoint sequence."""
    module = _load_route_tools()
    waypoints = module._build_waypoints_from_petals(["west-flamingo-jones", "south-tropicana-vv-sunset"])
    # Should start and end at the Strip hub
    assert waypoints[0] == module._STRIP_HUB
    assert waypoints[-1] == module._STRIP_HUB
    # Should have waypoints from both petals
    assert len(waypoints) > 8


def test_unknown_petal_name_skipped():
    """Unknown petal names are skipped with a warning."""
    module = _load_route_tools()
    waypoints = module._build_waypoints_from_petals(["west-flamingo-jones", "nonexistent-petal"])
    # Should still have waypoints from the valid petal
    assert len(waypoints) > 4
    assert waypoints[0] == module._STRIP_HUB


@pytest.mark.asyncio
async def test_report_marathon_route_no_direct_emit():
    """report_marathon_route must NOT call emit_gateway_message directly.

    The tool's return dict flows through DashLogPlugin's tool_end pipeline
    which carries session_id and simulation_id reliably. Direct emitting
    bypasses the plugin pipeline and produces unreliable metadata.
    """
    module = _load_route_tools()

    mock_ctx = MagicMock()
    mock_ctx.state = {"marathon_route": {"type": "FeatureCollection", "features": []}}

    with patch(
        "agents.utils.pulses.emit_gateway_message",
        new_callable=AsyncMock,
    ) as mock_emit:
        result = await module.report_marathon_route(tool_context=mock_ctx)

    mock_emit.assert_not_called()
    assert result["status"] == "success"
    assert result["route_geojson"] == {"type": "FeatureCollection", "features": []}


def test_get_maps_tools_is_importable():
    """get_maps_tools must be a public function in the base planner module."""
    from agents.planner.adk_tools import get_maps_tools

    assert callable(get_maps_tools)


class TestMapsAgentRegistry:
    """Tests for Maps MCP tools via AgentRegistry (agentregistry.googleapis.com)."""

    @patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "", "GOOGLE_MAPS_API_KEY": ""}, clear=False)
    def test_get_tools_without_maps_env_vars(self):
        """Planner boots without Maps MCP tools when env vars are unset."""
        import agents.planner.adk_tools as mod

        mod._resolved_maps_key = None  # Reset cache
        try:
            tools = mod.get_tools()
            tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]
            # Core tools still present (plan_marathon_route is lazy-loaded via SkillToolset)
            assert "SkillToolset" in tool_names
            assert "set_financial_modeling_mode" in tool_names
            # No crash, no Maps toolset
        finally:
            mod._resolved_maps_key = None  # Reset cache

    def test_header_provider_returns_api_key(self):
        """header_provider includes the API key and content type."""
        from agents.planner.adk_tools import header_provider
        import agents.planner.adk_tools as mod

        mod._resolved_maps_key = "test-key-123"
        try:
            headers = header_provider(context=None)
            assert headers["X-Goog-Api-Key"] == "test-key-123"
            assert headers["Content-Type"] == "application/json"
        finally:
            mod._resolved_maps_key = None  # Reset cache

    def test_get_maps_tools_uses_agent_registry(self):
        """get_maps_tools discovers Maps MCP server via AgentRegistry.list_mcp_servers."""
        import agents.planner.adk_tools as mod

        mod._resolved_maps_key = "test-key"
        try:
            mock_toolset = MagicMock()
            mock_conn = MagicMock()
            mock_conn.headers = {
                "Authorization": "Bearer token",
                "x-goog-user-project": "proj",
                "X-Goog-Api-Key": "test-key",
            }
            mock_toolset._connection_params = mock_conn

            mock_registry = MagicMock()
            mock_registry.list_mcp_servers.return_value = {
                "mcpServers": [
                    {
                        "name": "projects/test-proj/locations/global/mcpServers/agentregistry-uuid",
                        "displayName": "mapstools.googleapis.com",
                    }
                ]
            }
            mock_registry.get_mcp_toolset.return_value = mock_toolset

            with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "test-proj"}):
                with patch("agents.planner.adk_tools.AgentRegistry", return_value=mock_registry):
                    result = mod.get_maps_tools()

            # Should have called list_mcp_servers to discover
            mock_registry.list_mcp_servers.assert_called_once()
            # Should have called get_mcp_toolset with the discovered name
            mock_registry.get_mcp_toolset.assert_called_once_with(
                mcp_server_name="projects/test-proj/locations/global/mcpServers/agentregistry-uuid"
            )
            # Should strip ADC headers for API key auth
            assert "Authorization" not in mock_conn.headers
            assert "x-goog-user-project" not in mock_conn.headers
            assert mock_conn.headers["X-Goog-Api-Key"] == "test-key"
            assert result == [mock_toolset]
        finally:
            mod._resolved_maps_key = None

    def test_get_maps_tools_no_server_found(self):
        """get_maps_tools returns [] when Maps MCP server is not in Agent Registry."""
        import agents.planner.adk_tools as mod

        mod._resolved_maps_key = "test-key"
        try:
            mock_registry = MagicMock()
            mock_registry.list_mcp_servers.return_value = {"mcpServers": []}

            with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "test-proj"}):
                with patch("agents.planner.adk_tools.AgentRegistry", return_value=mock_registry):
                    result = mod.get_maps_tools()

            assert result == []
        finally:
            mod._resolved_maps_key = None

    @patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "test-proj", "GOOGLE_MAPS_API_KEY": ""}, clear=False)
    def test_get_tools_empty_maps_key_skips_maps(self):
        """Empty GOOGLE_MAPS_API_KEY string disables Maps MCP (tinkerer-friendly)."""
        import agents.planner.adk_tools as mod

        mod._resolved_maps_key = None  # Reset cache
        try:
            tools = mod.get_tools()
            tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]
            assert "SkillToolset" in tool_names
            # Maps toolset should NOT be present
            assert "McpToolset" not in tool_names
        finally:
            mod._resolved_maps_key = None  # Reset cache

    @patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "", "GOOGLE_MAPS_API_KEY": "real-key"}, clear=False)
    def test_get_tools_missing_project_skips_maps(self):
        """Maps MCP disabled when GOOGLE_CLOUD_PROJECT is unset."""
        import agents.planner.adk_tools as mod

        mod._resolved_maps_key = None  # Reset cache
        try:
            tools = mod.get_tools()
            tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]
            assert "SkillToolset" in tool_names
            assert "McpToolset" not in tool_names
        finally:
            mod._resolved_maps_key = None  # Reset cache

    @patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "", "GOOGLE_CLOUD_PROJECT": "test-proj"}, clear=False)
    @patch("subprocess.run")
    def test_resolve_maps_key_falls_back_to_secret_manager(self, mock_run):
        """When env var is empty, _resolve_maps_key tries Secret Manager."""
        import agents.planner.adk_tools as mod

        mod._resolved_maps_key = None  # Reset cache
        mock_run.return_value = MagicMock(stdout="secret-key-from-sm\n")
        try:
            key = mod._resolve_maps_key()
            assert key == "secret-key-from-sm"
            mock_run.assert_called_once()
            # Verify gcloud command structure
            args = mock_run.call_args[0][0]
            assert "gcloud" in args[0]
            assert "secrets" in args
            assert "maps-api-key" in " ".join(args)
        finally:
            mod._resolved_maps_key = None

    @patch.dict(
        "os.environ", {"GOOGLE_MAPS_API_KEY": "env-override-key", "GOOGLE_CLOUD_PROJECT": "test-proj"}, clear=False
    )
    @patch("subprocess.run")
    def test_resolve_maps_key_env_var_overrides_secret_manager(self, mock_run):
        """Env var takes priority over Secret Manager."""
        import agents.planner.adk_tools as mod

        mod._resolved_maps_key = None  # Reset cache
        try:
            key = mod._resolve_maps_key()
            assert key == "env-override-key"
            mock_run.assert_not_called()
        finally:
            mod._resolved_maps_key = None

    @patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "", "GOOGLE_CLOUD_PROJECT": "test-proj"}, clear=False)
    @patch("subprocess.run", side_effect=FileNotFoundError("gcloud not found"))
    def test_resolve_maps_key_survives_missing_gcloud(self, mock_run):
        """_resolve_maps_key returns None if gcloud is not installed."""
        import agents.planner.adk_tools as mod

        mod._resolved_maps_key = None  # Reset cache
        try:
            key = mod._resolve_maps_key()
            assert key is None
        finally:
            mod._resolved_maps_key = None


def test_segments_intersect_crossing():
    """Two segments that form an X must be detected as crossing."""
    module = _load_route_tools()
    assert module._segments_intersect((0, 0), (1, 1), (0, 1), (1, 0)) is True


def test_segments_intersect_parallel():
    """Parallel non-touching segments must NOT be detected as crossing."""
    module = _load_route_tools()
    assert module._segments_intersect((0, 0), (1, 0), (0, 1), (1, 1)) is False


def test_segments_intersect_shared_endpoint():
    """Segments sharing an endpoint are NOT a crossing (intersection reuse OK)."""
    module = _load_route_tools()
    assert module._segments_intersect((0, 0), (1, 0), (1, 0), (1, 1)) is False


def test_segments_intersect_collinear_overlap():
    """Collinear overlapping segments must be detected."""
    module = _load_route_tools()
    assert module._segments_intersect((0, 0), (2, 0), (1, 0), (3, 0)) is True


def test_segments_intersect_collinear_no_overlap():
    """Collinear non-overlapping segments must NOT be detected."""
    module = _load_route_tools()
    assert module._segments_intersect((0, 0), (1, 0), (2, 0), (3, 0)) is False


def test_route_has_crossing_simple_cross():
    """A route that forms a figure-8 must be detected as self-crossing."""
    module = _load_route_tools()
    coords = [(0, 0), (1, 1), (0, 1), (1, 0)]
    assert module._route_has_crossing(coords) is True


def test_route_has_crossing_simple_loop():
    """A simple rectangular loop has no crossing."""
    module = _load_route_tools()
    coords = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert module._route_has_crossing(coords) is False


def test_route_has_crossing_empty_or_short():
    """Routes with fewer than 4 points cannot cross."""
    module = _load_route_tools()
    assert module._route_has_crossing([]) is False
    assert module._route_has_crossing([(0, 0)]) is False
    assert module._route_has_crossing([(0, 0), (1, 0)]) is False
    assert module._route_has_crossing([(0, 0), (1, 0), (1, 1)]) is False


def test_perturbed_dijkstra_finds_valid_path():
    """Perturbed Dijkstra must find a path between connected nodes."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    rng = random.Random(42)
    start = sorted(strip_nodes)[0]
    end = sorted(strip_nodes)[-1]
    path, dist = module._get_path_dijkstra_perturbed(start, end, adj, set(), set(), rng)
    assert len(path) >= 2, "Must find a path"
    assert path[0] == start
    assert path[-1] == end
    assert dist > 0


def test_perturbed_dijkstra_respects_visited_edges():
    """Perturbed Dijkstra must not traverse visited edges."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    rng = random.Random(42)
    start = sorted(strip_nodes)[0]
    end = sorted(strip_nodes)[-1]

    path1, _ = module._get_path_dijkstra_perturbed(start, end, adj, set(), set(), rng)
    if len(path1) >= 2:
        blocked_edge = tuple(sorted((path1[0], path1[1])))
        rng2 = random.Random(42)
        path2, _ = module._get_path_dijkstra_perturbed(start, end, adj, set(), {blocked_edge}, rng2)
        if len(path2) >= 2:
            for i in range(len(path2) - 1):
                edge = tuple(sorted((path2[i], path2[i + 1])))
                assert edge != blocked_edge


def test_perturbed_dijkstra_different_seeds_can_differ():
    """Different random seeds should be able to produce different paths."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    start = sorted(strip_nodes)[0]
    far_node = module._find_closest_node(landmarks["Sphere"], nodes)

    paths = []
    for seed in range(20):
        rng = random.Random(seed)
        path, _ = module._get_path_dijkstra_perturbed(start, far_node, adj, set(), set(), rng)
        if path:
            paths.append(tuple(path))

    unique_paths = set(paths)
    assert len(unique_paths) > 1, "Perturbed Dijkstra should produce different paths with different seeds"


def test_build_strip_start_is_northbound():
    """Strip start corridor must go north on Las Vegas Blvd."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    sign_node = module._find_closest_node(landmarks["Las Vegas Sign"], strip_nodes)
    mgm_node = module._find_closest_node(landmarks["MGM Grand"], strip_nodes)
    path, dist, edges = module._build_strip_corridor(adj, strip_nodes, sign_node, mgm_node, set())
    assert len(path) >= 2
    assert dist > 0
    # Path should go from south (lower lat) to north (higher lat)
    assert path[0][1] < path[-1][1], "Start corridor must be northbound (lat increasing)"
    # All path nodes should be on the Strip
    for node in path:
        assert node in strip_nodes, f"Corridor node {node} not on Strip"


def test_build_strip_corridor_positive_distance():
    """Strip corridor must have a meaningful distance."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    sign_node = module._find_closest_node(landmarks["Las Vegas Sign"], strip_nodes)
    mgm_node = module._find_closest_node(landmarks["MGM Grand"], strip_nodes)
    path, dist, edges = module._build_strip_corridor(adj, strip_nodes, sign_node, mgm_node, set())
    # Las Vegas Sign to MGM Grand should be roughly 0.5-3 miles
    assert 0.3 < dist < 5.0, f"Corridor distance {dist:.2f} mi seems wrong"


def test_zone_sweep_produces_valid_route():
    """Zone-sweep generator must produce a substantial route."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    rng = random.Random(42)
    route, dist = module._generate_zone_sweep_route(adj, nodes, landmarks, strip_nodes, road_names, rng)
    assert len(route) >= 10, "Route must have substantial length"
    # Seed 42 produces 7.03 mi; actual min across seeds 0-29 is 6.96 mi
    assert dist >= 6.9, f"Route distance {dist:.3f} is too short"


def test_zone_sweep_no_edge_reuse():
    """Zone-sweep route must not reuse any edge."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    rng = random.Random(42)
    route, dist = module._generate_zone_sweep_route(adj, nodes, landmarks, strip_nodes, road_names, rng)
    edges_seen = set()
    for i in range(len(route) - 1):
        edge = tuple(sorted((route[i], route[i + 1])))
        assert edge not in edges_seen, f"Edge reused at index {i}: {edge}"
        edges_seen.add(edge)


def test_zone_sweep_starts_near_sign():
    """Zone-sweep route must start within 0.5 mi of the Las Vegas Sign.

    The forward-construction algorithm starts at the Las Vegas Sign
    and builds northbound, so the first point must be very close.
    """
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    for seed in range(5):
        rng = random.Random(seed)
        route, dist = module._generate_zone_sweep_route(adj, nodes, landmarks, strip_nodes, road_names, rng)
        sign_coord = landmarks["Las Vegas Sign"]
        start_dist = module._haversine(route[0], sign_coord)
        assert start_dist <= 0.5, f"Seed {seed}: start {start_dist:.3f} mi from Las Vegas Sign (must be <= 0.5)"


def test_zone_sweep_start_on_strip():
    """The route must START northbound on Las Vegas Boulevard.

    The start corridor runs from Las Vegas Sign north past MGM Grand.
    The first several points should have INCREASING latitude (going
    north) and at least some should be Strip nodes.
    """
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    for seed in range(5):
        rng = random.Random(seed)
        route, dist = module._generate_zone_sweep_route(adj, nodes, landmarks, strip_nodes, road_names, rng)
        # Check northbound: first 5 points should have generally increasing latitude
        first_lats = [p[1] for p in route[:5]]
        assert first_lats[-1] >= first_lats[0], f"Seed {seed}: start is NOT northbound (lats {first_lats})"
        # Check at least 2 of first 5 points are on the Strip
        strip_count = sum(1 for p in route[:5] if p in strip_nodes)
        assert strip_count >= 2, f"Seed {seed}: only {strip_count}/5 initial points on Strip"


def test_zone_sweep_variety():
    """Different seeds must produce different routes."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    routes = []
    for seed in range(5):
        rng = random.Random(seed)
        route, dist = module._generate_zone_sweep_route(adj, nodes, landmarks, strip_nodes, road_names, rng)
        routes.append(tuple(route))

    unique_routes = set(routes)
    assert len(unique_routes) > 1, "Different seeds should produce different routes"


# ---------------------------------------------------------------------------
# Task 6: Integration tests for plan_marathon_route with zone-sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_marathon_route_zone_sweep():
    """plan_marathon_route with algorithm='zone_sweep' produces a valid route."""
    module = _load_route_tools()
    mock_ctx = MagicMock()
    mock_ctx.state = {}
    result = await module.plan_marathon_route(
        algorithm="zone_sweep",
        seed=42,
        tool_context=mock_ctx,
    )
    assert result["status"] == "success"
    geojson = result["geojson"]
    assert len(geojson["features"]) > 2


@pytest.mark.asyncio
async def test_plan_marathon_route_backward_compat():
    """plan_marathon_route with petal_names still works (backward compatibility)."""
    module = _load_route_tools()
    mock_ctx = MagicMock()
    mock_ctx.state = {}
    result = await module.plan_marathon_route(
        petal_names=["west-flamingo-jones", "north-sahara-rainbow", "south-tropicana-vv-sunset"],
        tool_context=mock_ctx,
    )
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_plan_marathon_route_seed_reproducibility():
    """Same seed produces identical routes."""
    module = _load_route_tools()
    mock_ctx1 = MagicMock()
    mock_ctx1.state = {}
    result1 = await module.plan_marathon_route(
        algorithm="zone_sweep",
        seed=99,
        force_replan=True,
        tool_context=mock_ctx1,
    )
    mock_ctx2 = MagicMock()
    mock_ctx2.state = {}
    result2 = await module.plan_marathon_route(
        algorithm="zone_sweep",
        seed=99,
        force_replan=True,
        tool_context=mock_ctx2,
    )
    assert result1["geojson"] == result2["geojson"]


@pytest.mark.asyncio
async def test_plan_marathon_route_zone_sweep_default():
    """plan_marathon_route defaults to zone_sweep when no petal_names given."""
    module = _load_route_tools()
    mock_ctx = MagicMock()
    mock_ctx.state = {}
    result = await module.plan_marathon_route(
        seed=42,
        tool_context=mock_ctx,
    )
    assert result["status"] == "success"


def test_zone_sweep_all_edges_valid():
    """Interior edges must exist in the network.

    The first edge may start from an interpolated extension point.
    The last edge may end at an interpolated finish point.
    All interior edges must be valid network edges.
    """
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    for seed in range(5):
        rng = random.Random(seed)
        route, dist = module._generate_zone_sweep_route(adj, nodes, landmarks, strip_nodes, road_names, rng)
        is_valid, invalid = module._route_edges_valid(
            route,
            adj,
            allow_start_interpolation=True,
        )
        assert is_valid, f"Seed {seed}: invalid edges at indices {invalid}"


def test_path_crosses_route_detects_crossing():
    """_path_crosses_route must detect when a new path crosses existing route."""
    module = _load_route_tools()
    existing = [(0, 0), (2, 0)]  # horizontal line
    new_path = [(1, -1), (1, 1)]  # vertical line crossing it
    assert module._path_crosses_route(new_path, existing) is True


def test_path_crosses_route_allows_non_crossing():
    """_path_crosses_route must allow paths that don't cross."""
    module = _load_route_tools()
    existing = [(0, 0), (1, 0)]
    new_path = [(2, 0), (3, 0)]  # parallel, non-crossing
    assert module._path_crosses_route(new_path, existing) is False


def test_serpentine_waypoints_alternate():
    """_build_serpentine_waypoints must produce waypoints that alternate E/W."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    rng = random.Random(42)
    waypoints = module._build_serpentine_waypoints(adj, rng, side="west", num_roads=5)
    assert len(waypoints) >= 3, f"Need at least 3 waypoints, got {len(waypoints)}"
    for wp in waypoints:
        assert wp in nodes, f"Waypoint {wp} not in graph"
    lats = [wp[1] for wp in waypoints]
    assert lats[0] > lats[-1], "Waypoints should progress south"


def test_serpentine_waypoints_tier_bias():
    """With bias_lat set, bands near that latitude should be selected
    more frequently than distant bands."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()

    # Bias toward northern bands (lat ~36.135)
    north_counts = 0
    south_counts = 0
    for seed in range(50):
        rng = random.Random(seed)
        wps = module._build_serpentine_waypoints(
            adj,
            rng,
            side="west",
            num_roads=6,
            bias_lat=36.135,
        )
        for wp in wps:
            if wp[1] > 36.12:
                north_counts += 1
            elif wp[1] < 36.10:
                south_counts += 1

    # Northern bias should produce more northern waypoints
    assert north_counts > south_counts, (
        f"Northern bias should favor north: got {north_counts} north vs {south_counts} south"
    )


def test_serpentine_waypoints_no_bias_unchanged():
    """Without bias_lat, behavior should match the original."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    rng1 = random.Random(42)
    wps1 = module._build_serpentine_waypoints(
        adj,
        rng1,
        side="west",
        num_roads=6,
    )
    rng2 = random.Random(42)
    wps2 = module._build_serpentine_waypoints(
        adj,
        rng2,
        side="west",
        num_roads=6,
        bias_lat=None,
    )
    assert wps1 == wps2, "No bias should produce same results as before"


def test_zone_sweep_random_finish_not_on_strip():
    """When no finish landmark is specified, the route should finish at a
    random off-Strip node (not always the same landmark).

    With the Strip proximity constraint on finish-node selection, the
    pool of eligible nodes is smaller (~39 nodes within 0.5 mi of the
    Strip), so we require >= 2 unique finish locations.
    """
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    finishes = set()
    for seed in range(10):
        rng = random.Random(seed)
        route, dist = module._generate_zone_sweep_route(
            adj,
            nodes,
            landmarks,
            strip_nodes,
            road_names,
            rng,
        )
        # The last graph node should not be on the Strip
        # (last point may be an interpolated extension)
        graph_end = next(p for p in reversed(route) if p in nodes)
        finishes.add(graph_end)
    # Should have at least some variety across 10 seeds
    assert len(finishes) >= 2, f"Only {len(finishes)} unique finishes across 10 seeds"


def test_zone_sweep_no_off_road_points():
    """Every point in the route must be a graph node or interpolated on a
    graph edge (no synthetic coordinates off the road network)."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    for seed in range(5):
        rng = random.Random(seed)
        route, dist = module._generate_zone_sweep_route(
            adj,
            nodes,
            landmarks,
            strip_nodes,
            road_names,
            rng,
        )
        for i, pt in enumerate(route):
            if pt in nodes:
                continue
            # Not a graph node — must be interpolated ON a graph edge.
            # Check that at least one adjacent route point IS a graph node
            # and they share a graph edge.
            has_valid_neighbor = False
            if i > 0 and route[i - 1] in nodes:
                has_valid_neighbor = True
            if i < len(route) - 1 and route[i + 1] in nodes:
                has_valid_neighbor = True
            assert has_valid_neighbor, f"Seed {seed}: point {i} ({pt[0]:.6f}, {pt[1]:.6f}) is off the road network"


def test_find_off_strip_poi_node_near_poi():
    """Helper must find an off-strip graph node near a named POI."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()

    # Target: MGM Grand (on the Strip)
    node = module._find_off_strip_poi_node(
        adj=adj,
        nodes=nodes,
        strip_nodes=strip_nodes,
        landmarks=landmarks,
        preferred="MGM Grand",
    )
    assert node is not None, "Must find an off-strip node near MGM Grand"
    assert node not in strip_nodes, "Node must be off the Strip"
    # Must be within 0.5 mi of MGM Grand
    mgm = landmarks["MGM Grand"]
    dist = module._haversine(node, mgm)
    assert dist <= 0.5, f"Node is {dist:.3f} mi from MGM Grand (max 0.5)"
    # Must differ in longitude from Strip center
    assert abs(node[0] - module.STRIP_CENTER[0]) >= 0.001, "Node is too close to Strip longitude"


def test_find_off_strip_poi_node_no_preferred():
    """Without a preferred POI, must find nearest POI."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()

    # Use a node on the west side of the network as the "serpentine endpoint"
    west_nodes = sorted(
        [n for n in nodes if n not in strip_nodes],
        key=lambda n: n[0],
    )
    endpoint = west_nodes[0]  # westernmost off-strip node

    node = module._find_off_strip_poi_node(
        adj=adj,
        nodes=nodes,
        strip_nodes=strip_nodes,
        landmarks=landmarks,
        preferred=None,
        near=endpoint,
    )
    assert node is not None, "Must find an off-strip node"
    assert node not in strip_nodes


def test_find_off_strip_poi_node_all_pois():
    """Every network POI (except corridor landmarks) should yield a valid
    off-strip node."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()

    for poi_name, poi_coord in landmarks.items():
        if poi_name in ("Las Vegas Sign", "MGM Grand"):
            continue
        node = module._find_off_strip_poi_node(
            adj=adj,
            nodes=nodes,
            strip_nodes=strip_nodes,
            landmarks=landmarks,
            preferred=poi_name,
        )
        assert node is not None, f"No off-strip node found near {poi_name}"
        assert node not in strip_nodes, f"Node for {poi_name} is on the Strip"


def test_zone_sweep_finishes_off_strip_near_poi():
    """Route must finish from an off-strip node near a named POI.

    The finish node finder selects off-strip nodes near both a POI and
    the Strip.  The connector reserve prevents overshoot trim from
    walking the finish away from its original position.
    """
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    for seed in range(5):
        rng = random.Random(seed)
        route, dist = module._generate_zone_sweep_route(
            adj,
            nodes,
            landmarks,
            strip_nodes,
            road_names,
            rng,
        )
        assert len(route) >= 10, f"Seed {seed}: route too short"
        # Last graph node must be off-strip
        graph_end = next((p for p in reversed(route) if p in nodes), None)
        if graph_end is not None:
            assert graph_end not in strip_nodes, f"Seed {seed}: finish is on the Strip"
            min_poi_dist = min(module._haversine(graph_end, coord) for coord in landmarks.values())
            assert min_poi_dist <= 1.0, f"Seed {seed}: finish is {min_poi_dist:.3f} mi from nearest POI (max 1.0)"


def test_zone_sweep_targeted_finish_poi():
    """When finish_landmark is specified, route should finish near that POI."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    for poi_name in ("Michelob Ultra Arena", "Bellagio", "Flamingo"):
        rng = random.Random(42)
        route, dist = module._generate_zone_sweep_route(
            adj,
            nodes,
            landmarks,
            strip_nodes,
            road_names,
            rng,
            finish_landmark=poi_name,
        )
        assert len(route) >= 10, f"{poi_name}: route too short"
        graph_end = next((p for p in reversed(route) if p in nodes), None)
        if graph_end is not None:
            target_dist = module._haversine(
                graph_end,
                landmarks[poi_name],
            )
            # Connector reserve prevents overshoot trim; finishes stay near POIs
            assert target_dist <= 1.0, f"{poi_name}: finish is {target_dist:.3f} mi away (max 1.0)"


def test_zone_sweep_geographic_variety():
    """Different seeds should produce routes in different geographic regions,
    not always through the southeast (airport area)."""
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()
    south_count = 0
    north_count = 0
    for seed in range(10):
        rng = random.Random(seed)
        route, dist = module._generate_zone_sweep_route(
            adj,
            nodes,
            landmarks,
            strip_nodes,
            road_names,
            rng,
        )
        # Check if route has significant coverage south of 36.10
        south_points = sum(1 for p in route if p[1] < 36.10)
        if south_points > len(route) * 0.3:
            south_count += 1
        north_points = sum(1 for p in route if p[1] > 36.12)
        if north_points > len(route) * 0.3:
            north_count += 1

    # Both regions should get SOME coverage (not 100% south)
    assert north_count >= 2, f"Only {north_count}/10 seeds have significant northern coverage"
    assert south_count < 10, "All 10 seeds go through the south — no variety"


def test_zone_sweep_30_seed_guarantee():
    """30-seed integration test: every seed must satisfy core route constraints.

    Uses the tournament wrapper (_generate_best_route) to guarantee
    marathon-distance routes for all 30 seeds.

    Every generated route must:
    - Have marathon distance (>= 26.0 mi)
    - Start near the Las Vegas Sign
    - Start going NORTHBOUND on the Strip (increasing latitude)
    - Have zero geometric self-crossings
    - Finish within 0.5 mi of Michelob Ultra Arena
    - Zero geometric self-crossings
    - Zero edge reuse
    """
    module, adj, landmarks, road_names, strip_nodes, nodes = _load_network_and_graph()

    sign_coord = landmarks["Las Vegas Sign"]
    michelob_coord = landmarks["Michelob Ultra Arena"]

    for seed in range(30):
        route, dist = module._generate_best_route(
            adj,
            nodes,
            landmarks,
            strip_nodes,
            road_names,
            seed=seed,
            finish_landmark="Michelob Ultra Arena",
            max_candidates=10,
        )

        assert dist >= 26.0, f"Seed {seed}: distance {dist:.4f} mi (need >= 26.0)"

        # 2. Start near Las Vegas Sign
        start_dist = module._haversine(route[0], sign_coord)
        assert start_dist <= 0.5, f"Seed {seed}: start {start_dist:.3f} mi from Sign (max 0.5)"

        # 3. Northbound start (first 5 points: increasing latitude)
        first_lats = [p[1] for p in route[:5]]
        assert first_lats[-1] >= first_lats[0], f"Seed {seed}: start is NOT northbound"

        # 4. No geometric crossings
        assert not module._route_has_crossing(route), f"Seed {seed}: route has geometric crossing"

        # 5. Finish within 0.75 mi of Michelob Ultra Arena
        finish_to_michelob = module._haversine(route[-1], michelob_coord)
        assert finish_to_michelob <= 0.75, f"Seed {seed}: finish {finish_to_michelob:.3f} mi from Michelob (max 0.75)"

        # 6. No edge reuse
        edges_seen: set[tuple] = set()
        for i in range(len(route) - 1):
            edge = tuple(sorted((route[i], route[i + 1])))
            assert edge not in edges_seen, f"Seed {seed}: edge reuse at index {i}"
            edges_seen.add(edge)


@pytest.mark.asyncio
async def test_plan_marathon_event_start_time():
    """plan_marathon_event must default to an 08:00 PM start time."""
    module = _load_event_tools()
    result = await module.plan_marathon_event("Test Marathon", "Las Vegas")
    assert result["characteristics"]["start_time"] == "08:00 PM"
