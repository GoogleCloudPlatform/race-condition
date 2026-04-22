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

"""Tests for the Redis side-channel simulation data module."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.utils.simdata import (
    clear_simulation_data,
    load_simulation_data,
    store_simulation_data,
)

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


class TestStoreSimulationData:
    """Verify store_simulation_data writes to Redis correctly."""

    @pytest.mark.asyncio
    async def test_stores_route_in_redis_hash(self):
        """Verifies r.hset called with simdata:{sim_id}, field route_geojson, value is JSON string."""
        mock_redis = AsyncMock()
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            result = await store_simulation_data(
                simulation_id="sim-abc",
                route_geojson=SAMPLE_ROUTE,
            )

        assert result is True
        mock_redis.hset.assert_called()
        call_args = mock_redis.hset.call_args
        assert call_args[0][0] == "simdata:sim-abc"
        # The mapping should contain route_geojson as a JSON string
        mapping = call_args[1].get("mapping") or call_args[0][1]
        assert "route_geojson" in mapping
        assert json.loads(mapping["route_geojson"]) == SAMPLE_ROUTE

    @pytest.mark.asyncio
    async def test_stores_traffic_assessment(self):
        """Verifies traffic_assessment is stored as JSON in the hash."""
        mock_redis = AsyncMock()
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            result = await store_simulation_data(
                simulation_id="sim-def",
                traffic_assessment=SAMPLE_TRAFFIC,
            )

        assert result is True
        mock_redis.hset.assert_called()
        call_args = mock_redis.hset.call_args
        mapping = call_args[1].get("mapping") or call_args[0][1]
        assert "traffic_assessment" in mapping
        assert json.loads(mapping["traffic_assessment"]) == SAMPLE_TRAFFIC

    @pytest.mark.asyncio
    async def test_sets_ttl_on_key(self):
        """Verifies r.expire is called with 7200 seconds (2 hours)."""
        mock_redis = AsyncMock()
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            await store_simulation_data(
                simulation_id="sim-ttl",
                route_geojson=SAMPLE_ROUTE,
            )

        mock_redis.expire.assert_called_once_with("simdata:sim-ttl", 7200)

    @pytest.mark.asyncio
    async def test_returns_false_when_no_redis(self):
        """When get_shared_redis_client returns None, function returns False."""
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=None):
            result = await store_simulation_data(
                simulation_id="sim-nope",
                route_geojson=SAMPLE_ROUTE,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_redis_error(self):
        """When r.hset raises Exception, function returns False (doesn't raise)."""
        mock_redis = AsyncMock()
        mock_redis.hset.side_effect = Exception("connection refused")
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            result = await store_simulation_data(
                simulation_id="sim-err",
                route_geojson=SAMPLE_ROUTE,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_skips_none_fields(self):
        """When route_geojson is None, only traffic_assessment is stored."""
        mock_redis = AsyncMock()
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            await store_simulation_data(
                simulation_id="sim-partial",
                route_geojson=None,
                traffic_assessment=SAMPLE_TRAFFIC,
            )

        call_args = mock_redis.hset.call_args
        mapping = call_args[1].get("mapping") or call_args[0][1]
        assert "route_geojson" not in mapping
        assert "traffic_assessment" in mapping


class TestLoadSimulationData:
    """Verify load_simulation_data reads from Redis correctly."""

    @pytest.mark.asyncio
    async def test_loads_route_from_redis(self):
        """Mock r.hgetall returns route_geojson bytes, function returns parsed dict."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {
            b"route_geojson": json.dumps(SAMPLE_ROUTE).encode(),
        }
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            result = await load_simulation_data("sim-load")

        assert result["route_geojson"] == SAMPLE_ROUTE
        mock_redis.hgetall.assert_called_once_with("simdata:sim-load")

    @pytest.mark.asyncio
    async def test_loads_traffic_assessment(self):
        """Mock r.hgetall returns traffic_assessment bytes, function returns parsed dict."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {
            b"traffic_assessment": json.dumps(SAMPLE_TRAFFIC).encode(),
        }
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            result = await load_simulation_data("sim-traffic")

        assert result["traffic_assessment"] == SAMPLE_TRAFFIC

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_redis(self):
        """When get_shared_redis_client returns None, function returns {}."""
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=None):
            result = await load_simulation_data("sim-nope")

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_redis_error(self):
        """When r.hgetall raises, returns {}."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.side_effect = Exception("timeout")
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            result = await load_simulation_data("sim-err")

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_fields(self):
        """When hash exists but is empty, returns dict with None values."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            result = await load_simulation_data("sim-empty")

        assert result == {"route_geojson": None, "traffic_assessment": None}


class TestClearSimulationData:
    """Verify clear_simulation_data deletes the hash key."""

    @pytest.mark.asyncio
    async def test_clear_deletes_key(self):
        mock_redis = AsyncMock()
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            result = await clear_simulation_data("sim-clear")

        assert result is True
        mock_redis.delete.assert_called_once_with("simdata:sim-clear")

    @pytest.mark.asyncio
    async def test_clear_returns_false_when_no_redis(self):
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=None):
            result = await clear_simulation_data("sim-nope")

        assert result is False


class TestSimulationIsolation:
    """Verify different simulation IDs use different Redis keys."""

    @pytest.mark.asyncio
    async def test_different_simulation_ids_use_different_keys(self):
        """Store for sim_a and sim_b, verify different keys used."""
        mock_redis = AsyncMock()
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            await store_simulation_data("sim-a", route_geojson=SAMPLE_ROUTE)
            await store_simulation_data("sim-b", route_geojson=SAMPLE_ROUTE)

        hset_calls = mock_redis.hset.call_args_list
        keys_used = [call[0][0] for call in hset_calls]
        assert "simdata:sim-a" in keys_used
        assert "simdata:sim-b" in keys_used
        assert keys_used[0] != keys_used[1]

    @pytest.mark.asyncio
    async def test_load_does_not_cross_simulations(self):
        """Store for sim_a, load for sim_b should use different keys."""
        mock_redis = AsyncMock()
        # sim_b returns empty hash
        mock_redis.hgetall.return_value = {}
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            await store_simulation_data("sim-a", route_geojson=SAMPLE_ROUTE)
            result = await load_simulation_data("sim-b")

        # load should query sim-b, not sim-a
        mock_redis.hgetall.assert_called_once_with("simdata:sim-b")
        assert result["route_geojson"] is None

    @pytest.mark.asyncio
    async def test_clear_only_affects_target_simulation(self):
        """Clear sim_a, verify only sim_a's key is deleted."""
        mock_redis = AsyncMock()
        with patch("agents.utils.simdata.get_shared_redis_client", return_value=mock_redis):
            await store_simulation_data("sim-a", route_geojson=SAMPLE_ROUTE)
            await store_simulation_data("sim-b", route_geojson=SAMPLE_ROUTE)
            await clear_simulation_data("sim-a")

        mock_redis.delete.assert_called_once_with("simdata:sim-a")
