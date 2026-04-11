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

"""Redis side-channel for passing large simulation data between agents.

Stores route GeoJSON and traffic assessment in Redis hashes so that
the planner and simulator agents can exchange large payloads WITHOUT
going through the LLM (which truncates/corrupts large JSON).

Key pattern: ``simdata:{simulation_id}``
TTL: 7200 seconds (2 hours).
"""

import json
import logging

from agents.utils.redis_pool import get_shared_redis_client

logger = logging.getLogger(__name__)

_KEY_PREFIX = "simdata:"
_TTL_SECONDS = 7200


async def store_simulation_data(
    simulation_id: str,
    route_geojson: dict | None = None,
    traffic_assessment: dict | None = None,
) -> bool:
    """Store simulation data in a Redis hash for the given simulation.

    Args:
        simulation_id: Unique simulation identifier.
        route_geojson: Route GeoJSON FeatureCollection (optional).
        traffic_assessment: Traffic assessment dict (optional).

    Returns:
        True on success, False if Redis is unavailable or on error.
    """
    r = get_shared_redis_client()
    if r is None:
        logger.warning("store_simulation_data: no Redis client available")
        return False

    key = f"{_KEY_PREFIX}{simulation_id}"
    mapping: dict[str, str] = {}

    if route_geojson is not None:
        mapping["route_geojson"] = json.dumps(route_geojson)
    if traffic_assessment is not None:
        mapping["traffic_assessment"] = json.dumps(traffic_assessment)

    if not mapping:
        return True  # Nothing to store

    try:
        await r.hset(key, mapping=mapping)  # type: ignore[misc]
        await r.expire(key, _TTL_SECONDS)  # type: ignore[misc]
        return True
    except Exception:
        logger.warning("store_simulation_data: Redis error for %s", simulation_id, exc_info=True)
        return False


async def load_simulation_data(simulation_id: str) -> dict:
    """Load simulation data from the Redis hash.

    Args:
        simulation_id: Unique simulation identifier.

    Returns:
        Dict with keys ``route_geojson`` and ``traffic_assessment``
        (parsed from JSON). Missing fields return None. Returns empty
        dict if Redis is unavailable or on error.
    """
    r = get_shared_redis_client()
    if r is None:
        return {}

    key = f"{_KEY_PREFIX}{simulation_id}"
    try:
        raw = await r.hgetall(key)  # type: ignore[misc]
    except Exception:
        logger.warning("load_simulation_data: Redis error for %s", simulation_id, exc_info=True)
        return {}

    if not raw:
        return {"route_geojson": None, "traffic_assessment": None}

    result: dict = {}
    for field_name in ("route_geojson", "traffic_assessment"):
        raw_value = raw.get(field_name.encode())
        if raw_value is not None:
            result[field_name] = json.loads(raw_value)
        else:
            result[field_name] = None

    return result


async def clear_simulation_data(simulation_id: str) -> bool:
    """Delete the simulation data hash key.

    Args:
        simulation_id: Unique simulation identifier.

    Returns:
        True on success, False if Redis is unavailable or on error.
    """
    r = get_shared_redis_client()
    if r is None:
        return False

    key = f"{_KEY_PREFIX}{simulation_id}"
    try:
        await r.delete(key)  # type: ignore[misc]
        return True
    except Exception:
        logger.warning("clear_simulation_data: Redis error for %s", simulation_id, exc_info=True)
        return False
