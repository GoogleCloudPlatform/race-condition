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

"""Integration test: store via store_simulation_data, then prepare_simulation reads from Redis."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.utils.simdata import load_simulation_data, store_simulation_data

SAMPLE_ROUTE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "Las Vegas Blvd"},
            "geometry": {
                "type": "LineString",
                "coordinates": [[-115.17, 36.08], [-115.17, 36.09]],
            },
        }
    ],
}

SAMPLE_TRAFFIC = {
    "segments": [
        {"name": "Las Vegas Blvd", "congestion": "moderate"},
    ],
    "overall_rating": "B",
}


class TestSimdataEndToEnd:
    """Test store→load round-trip with a simulated Redis backend."""

    @pytest.mark.asyncio
    async def test_store_then_load_round_trip(self):
        """Data stored via store_simulation_data is retrievable via load_simulation_data."""
        # Simulate a real Redis hash by using a dict as backing store
        redis_store: dict[str, dict[bytes, bytes]] = {}

        mock_redis = AsyncMock()

        async def fake_hset(key, mapping=None):
            if key not in redis_store:
                redis_store[key] = {}
            if mapping:
                for k, v in mapping.items():
                    redis_store[key][k.encode() if isinstance(k, str) else k] = v.encode() if isinstance(v, str) else v

        async def fake_hgetall(key):
            return redis_store.get(key, {})

        mock_redis.hset = AsyncMock(side_effect=fake_hset)
        mock_redis.hgetall = AsyncMock(side_effect=fake_hgetall)
        mock_redis.expire = AsyncMock()

        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            # Store
            stored = await store_simulation_data(
                simulation_id="e2e-test",
                route_geojson=SAMPLE_ROUTE,
                traffic_assessment=SAMPLE_TRAFFIC,
            )
            assert stored is True

            # Load
            loaded = await load_simulation_data("e2e-test")

        assert loaded["route_geojson"] == SAMPLE_ROUTE
        assert loaded["traffic_assessment"] == SAMPLE_TRAFFIC

    @pytest.mark.asyncio
    async def test_prepare_simulation_uses_redis_data(self):
        """prepare_simulation reads route from Redis side-channel when plan has no route."""
        # This test verifies the full flow: simdata stores data, then
        # prepare_simulation in the simulator reads it via load_simulation_data.
        import importlib.util
        import pathlib

        tools_path = pathlib.Path(__file__).parents[1] / "simulator" / "skills" / "preparing-the-race" / "tools.py"
        spec = importlib.util.spec_from_file_location("pre_race.tools", tools_path)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Plan WITHOUT route (route comes from Redis)
        plan = {
            "action": "execute",
            "narrative": "Run the Strip Classic marathon",
            "simulation_config": {"runner_count": 5, "duration_seconds": 30},
        }

        tc = MagicMock()
        tc.state = {"simulation_id": "e2e-sim-123"}
        tc.session = MagicMock()
        tc.session.id = "e2e-sim-123"

        # Mock load_simulation_data at the simdata module level (it's imported
        # lazily inside prepare_simulation via from agents.utils.simdata import ...)
        with patch(
            "agents.utils.simdata.load_simulation_data",
            new_callable=AsyncMock,
            return_value={
                "route_geojson": SAMPLE_ROUTE,
                "traffic_assessment": SAMPLE_TRAFFIC,
            },
        ):
            result = await mod.prepare_simulation(
                plan_json=json.dumps(plan),
                tool_context=tc,
            )

        assert result["status"] == "success"
        # Route should have been stored in state from Redis
        assert tc.state["route_geojson"] == SAMPLE_ROUTE
        assert tc.state["traffic_assessment"] == SAMPLE_TRAFFIC
