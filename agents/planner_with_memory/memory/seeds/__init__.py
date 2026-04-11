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

"""Seed data loader for pre-generated marathon route plans.

Reads ``*.json`` files from the ``seeds/`` directory and inserts them into a
:class:`RouteMemoryStore` as :class:`PlannedRoute` objects, preserving the
original ``route_id`` and ``created_at`` values from each file.
"""

from __future__ import annotations

import glob
import json
import logging
import os
from datetime import datetime, timezone

from agents.planner_with_memory.memory.schemas import PlannedRoute
from agents.planner_with_memory.memory.store import RouteMemoryStore

logger = logging.getLogger(__name__)

# Default seeds directory is adjacent to this file
_DEFAULT_SEEDS_DIR = os.path.dirname(__file__)


def load_seeds(
    store: RouteMemoryStore,
    seeds_dir: str | None = None,
) -> int:
    """Load seed plans from JSON files into the store.

    Args:
        store: The RouteMemoryStore to populate.
        seeds_dir: Directory containing seed JSON files.
            Defaults to the directory containing this module.

    Returns:
        Number of seeds loaded.
    """
    if seeds_dir is None:
        seeds_dir = _DEFAULT_SEEDS_DIR

    loaded = 0
    pattern = os.path.join(seeds_dir, "*.json")

    for filepath in sorted(glob.glob(pattern)):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            route_id = data["route_id"]

            # Idempotency: skip if already loaded.
            # NOTE: We access store._routes directly (rather than the public
            # store_route API) to preserve the original route_id and created_at
            # from the seed file.  store.store_route() generates a new UUID and
            # timestamp, which would discard the stable seed identifiers.
            if route_id in store._routes:
                logger.debug("Seed %s already in store, skipping.", route_id)
                continue

            created_at = datetime.fromisoformat(data["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            route = PlannedRoute(
                route_id=route_id,
                route_data=data["route_data"],
                created_at=created_at,
                evaluation_score=data.get("evaluation_score"),
                evaluation_result=data.get("evaluation_result"),
            )
            store._routes[route_id] = route
            loaded += 1
            logger.info(
                "Loaded seed plan: %s from %s",
                route_id,
                os.path.basename(filepath),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Failed to load seed %s: %s", filepath, exc)

    logger.info("Loaded %d seed plan(s) into memory store.", loaded)
    return loaded
