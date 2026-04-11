#!/usr/bin/env python3
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

"""Seed AlloyDB with pre-generated marathon route plans and regulation data.

This script is the production equivalent of the in-memory seed loader used in
tests.  It connects to AlloyDB using asyncpg (same credentials as
AlloyDBRouteStore) and writes seed routes idempotently.

Usage:
    python -m agents.planner_with_memory.alloydb.seed_routes

Required environment variables:
    ALLOYDB_HOST       — Private IP of the AlloyDB instance
    ALLOYDB_DATABASE   — Database name (default: postgres)
    ALLOYDB_USER       — DB user (default: postgres)
    ALLOYDB_PASSWORD   — DB password
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Seeds live alongside the JSON files in memory/seeds/
_SEEDS_DIR = Path(__file__).parent.parent / "memory" / "seeds"


async def seed_routes() -> int:
    """Insert all seed JSON files into planned_routes idempotently.

    Returns:
        Number of new rows inserted.
    """
    import asyncpg  # lazily imported so module loads without extras installed

    from agents.planner_with_memory.memory.store_alloydb import _get_dsn

    conn = await asyncpg.connect(_get_dsn())
    loaded = 0
    try:
        for filepath in sorted(_SEEDS_DIR.glob("*.json")):
            try:
                data = json.loads(filepath.read_text())
                route_id = data["route_id"]
                created_at = datetime.fromisoformat(data["created_at"])
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

                # Inject top-level name into route_data so downstream
                # tools (get_route, get_planned_routes_data) can extract it.
                route_data = data["route_data"]
                if isinstance(route_data, dict) and "name" not in route_data:
                    seed_name = data.get("name")
                    if seed_name:
                        route_data["name"] = seed_name

                route_data_json = json.dumps(route_data)
                eval_result_json = json.dumps(data["evaluation_result"]) if data.get("evaluation_result") else None

                await conn.execute(
                    """
                    INSERT INTO planned_routes
                        (route_id, route_data, created_at, eval_score, eval_result)
                    VALUES ($1, $2::jsonb, $3, $4, $5::jsonb)
                    ON CONFLICT (route_id) DO UPDATE SET
                        route_data = EXCLUDED.route_data,
                        eval_score = EXCLUDED.eval_score,
                        eval_result = EXCLUDED.eval_result
                    """,
                    route_id,
                    route_data_json,
                    created_at,
                    data.get("evaluation_score"),
                    eval_result_json,
                )
                loaded += 1
                logger.info("Seeded/updated route %s from %s", route_id, filepath.name)
            except (json.JSONDecodeError, KeyError, ValueError, Exception) as exc:
                logger.warning("Failed to seed %s: %s", filepath.name, exc)
    finally:
        await conn.close()

    logger.info("Seeded %d new route(s) into AlloyDB.", loaded)
    return loaded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(seed_routes())
