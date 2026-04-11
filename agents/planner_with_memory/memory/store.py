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

"""In-memory route memory store.

Provides ``RouteMemoryStore``, an in-memory repository for planned routes and
their simulation history.  This is a Phase-1 stub — production will swap in a
persistent backend.
"""

import uuid
from datetime import datetime, timezone

from agents.planner_with_memory.memory.schemas import PlannedRoute, SimulationRecord


class RouteMemoryStore:
    """In-memory store for planned routes and simulation records."""

    def __init__(self) -> None:
        self._routes: dict[str, PlannedRoute] = {}
        # Load pre-generated seed plans from disk
        from agents.planner_with_memory.memory.seeds import load_seeds

        load_seeds(self)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store_route(
        self,
        route_data: dict,
        evaluation_score: float | None = None,
        evaluation_result: dict | None = None,
    ) -> str:
        """Persist a new planned route and return its UUID."""
        route_id = str(uuid.uuid4())
        route = PlannedRoute(
            route_id=route_id,
            route_data=route_data,
            created_at=datetime.now(tz=timezone.utc),
            evaluation_score=evaluation_score,
            evaluation_result=evaluation_result,
        )
        self._routes[route_id] = route
        return route_id

    def get_route(self, route_id: str) -> PlannedRoute | None:
        """Retrieve a route by ID, or ``None`` if not found."""
        return self._routes.get(route_id)

    def record_simulation(
        self,
        route_id: str,
        simulation_result: dict,
    ) -> str | None:
        """Append a simulation record to *route_id*.

        Returns the simulation UUID on success, or ``None`` if the route does
        not exist.
        """
        route = self._routes.get(route_id)
        if route is None:
            return None

        sim_id = str(uuid.uuid4())
        record = SimulationRecord(
            simulation_id=sim_id,
            route_id=route_id,
            simulation_result=simulation_result,
            simulated_at=datetime.now(tz=timezone.utc),
        )
        route.simulations.append(record)
        return sim_id

    def recall_routes(
        self,
        count: int = 10,
        sort_by: str = "recent",
    ) -> list[PlannedRoute]:
        """Return up to *count* routes, sorted by *sort_by*.

        Args:
            count: Maximum number of routes to return.
            sort_by: ``"recent"`` (newest first) or ``"best_score"``
                (highest evaluation_score first; unscored routes sort last).
        """
        routes = list(self._routes.values())
        if sort_by == "best_score":
            routes.sort(
                key=lambda r: (
                    r.evaluation_score is not None,
                    r.evaluation_score if r.evaluation_score is not None else 0.0,
                ),
                reverse=True,
            )
        else:  # "recent"
            routes.sort(key=lambda r: r.created_at, reverse=True)
        return routes[:count]

    def get_best_route(self) -> PlannedRoute | None:
        """Return the route with the highest evaluation score, or ``None``.

        Routes without an evaluation score are excluded.
        """
        scored = [r for r in self._routes.values() if r.evaluation_score is not None]
        if not scored:
            return None
        return max(scored, key=lambda r: r.evaluation_score)  # type: ignore[arg-type]
