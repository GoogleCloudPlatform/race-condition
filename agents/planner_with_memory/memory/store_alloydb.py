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

"""AlloyDB-backed route memory store.

Replaces the in-memory RouteMemoryStore with a persistent AlloyDB backend
using asyncpg. Implements the same public API so tools.py requires no changes
beyond swapping the singleton.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import asyncpg
from google.cloud import secretmanager

from agents.planner_with_memory.memory.schemas import PlannedRoute, SimulationRecord

logger = logging.getLogger(__name__)

_SECRET_TTL_SECONDS = 1800  # 30 minutes
_SM_PROJECT = os.environ.get("SECRET_MANAGER_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID", "")
_SM_SECRET = "am-db-password"

# (password, monotonic_timestamp) -- single tuple for atomic cache updates.
_cached: tuple[str, float] | None = None
_sm_client: secretmanager.SecretManagerServiceClient | None = None


def _get_sm_client() -> secretmanager.SecretManagerServiceClient:
    """Lazy-singleton for the Secret Manager gRPC client."""
    global _sm_client
    if _sm_client is None:
        _sm_client = secretmanager.SecretManagerServiceClient()
    return _sm_client


def _resolve_password() -> str:
    """Return the AlloyDB password from env var or Secret Manager with TTL cache."""
    global _cached

    env_pw = os.environ.get("ALLOYDB_PASSWORD", "")
    if env_pw:
        return env_pw

    now = time.monotonic()
    if _cached is not None and (now - _cached[1]) < _SECRET_TTL_SECONDS:
        return _cached[0]

    secret_name = f"projects/{_SM_PROJECT}/secrets/{_SM_SECRET}/versions/latest"
    try:
        response = _get_sm_client().access_secret_version(name=secret_name)
        password = response.payload.data.decode("utf-8").strip()
        _cached = (password, time.monotonic())
        return password
    except Exception:
        if _cached is not None:
            logger.warning("Secret Manager refresh failed; using stale cached password.", exc_info=True)
            return _cached[0]
        raise ValueError(f"Could not fetch AlloyDB password from Secret Manager ({secret_name}).")


def _get_dsn() -> str:
    """Build a DSN from environment variables."""
    host = os.environ.get("ALLOYDB_HOST")
    if not host:
        raise ValueError(
            "ALLOYDB_HOST environment variable is required for AlloyDBRouteStore. "
            "Set it to the private IP of the AlloyDB instance."
        )
    database = os.environ.get("ALLOYDB_DATABASE", "postgres")
    user = os.environ.get("ALLOYDB_USER", "postgres")
    password = _resolve_password()
    port = int(os.environ.get("ALLOYDB_PORT", "5432"))
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


async def _get_conn() -> asyncpg.Connection:
    schema_name = os.environ.get("ALLOYDB_SCHEMA", "local_dev")
    return await asyncpg.connect(_get_dsn(), server_settings={"search_path": f"{schema_name}, public"})


def _row_to_route(row: asyncpg.Record) -> PlannedRoute:
    """Convert an asyncpg row from planned_routes to a PlannedRoute."""
    return PlannedRoute(
        route_id=row["route_id"],
        route_data=json.loads(row["route_data"]) if isinstance(row["route_data"], str) else row["route_data"],
        created_at=row["created_at"].replace(tzinfo=timezone.utc)
        if row["created_at"].tzinfo is None
        else row["created_at"],
        evaluation_score=row["eval_score"],
        evaluation_result=json.loads(row["eval_result"]) if isinstance(row["eval_result"], str) else row["eval_result"],
    )


async def _load_simulations(conn: asyncpg.Connection, route_id: str) -> list[SimulationRecord]:
    rows = await conn.fetch(
        "SELECT simulation_id, route_id, sim_result, simulated_at "
        "FROM simulation_records WHERE route_id = $1 ORDER BY simulated_at ASC",
        route_id,
    )
    return [
        SimulationRecord(
            simulation_id=r["simulation_id"],
            route_id=r["route_id"],
            simulation_result=json.loads(r["sim_result"]) if isinstance(r["sim_result"], str) else r["sim_result"],
            simulated_at=r["simulated_at"].replace(tzinfo=timezone.utc)
            if r["simulated_at"].tzinfo is None
            else r["simulated_at"],
        )
        for r in rows
    ]


class AlloyDBRouteStore:
    """AlloyDB-backed store for planned routes and simulation records."""

    # -----------------------------------------------------------------------
    # Public API (mirrors RouteMemoryStore)
    # -----------------------------------------------------------------------

    async def store_route(
        self,
        route_data: dict,
        evaluation_score: float | None = None,
        evaluation_result: dict | None = None,
    ) -> str:
        """Persist a new planned route and return its UUID."""
        route_id = str(uuid.uuid4())
        conn = await _get_conn()
        try:
            await conn.execute(
                """
                INSERT INTO planned_routes (route_id, route_data, created_at, eval_score, eval_result)
                VALUES ($1, $2::jsonb, now(), $3, $4::jsonb)
                """,
                route_id,
                json.dumps(route_data),
                evaluation_score,
                json.dumps(evaluation_result) if evaluation_result is not None else None,
            )
        finally:
            await conn.close()
        return route_id

    async def get_route(self, route_id: str) -> PlannedRoute | None:
        """Retrieve a route by ID, or None if not found."""
        conn = await _get_conn()
        try:
            row = await conn.fetchrow(
                "SELECT route_id, route_data, created_at, eval_score, eval_result "
                "FROM planned_routes WHERE route_id = $1",
                route_id,
            )
            if row is None:
                return None
            route = _row_to_route(row)
            route.simulations = await _load_simulations(conn, route_id)
            return route
        finally:
            await conn.close()

    async def record_simulation(
        self,
        route_id: str,
        simulation_result: dict,
    ) -> str | None:
        """Append a simulation record to route_id. Returns sim UUID or None."""
        conn = await _get_conn()
        try:
            exists = await conn.fetchval("SELECT 1 FROM planned_routes WHERE route_id = $1", route_id)
            if not exists:
                return None
            sim_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO simulation_records (simulation_id, route_id, sim_result, simulated_at)
                VALUES ($1, $2, $3::jsonb, now())
                """,
                sim_id,
                route_id,
                json.dumps(simulation_result),
            )
            return sim_id
        finally:
            await conn.close()

    async def recall_routes(
        self,
        count: int = 10,
        sort_by: str = "recent",
    ) -> list[PlannedRoute]:
        """Return up to count routes sorted by recent or best_score."""
        order = "created_at DESC" if sort_by != "best_score" else "eval_score DESC NULLS LAST"
        conn = await _get_conn()
        try:
            rows = await conn.fetch(
                f"SELECT route_id, route_data, created_at, eval_score, eval_result "
                f"FROM planned_routes ORDER BY {order} LIMIT $1",
                count,
            )
            return [_row_to_route(r) for r in rows]
        finally:
            await conn.close()

    async def get_best_route(self) -> PlannedRoute | None:
        """Return the route with the highest evaluation score."""
        conn = await _get_conn()
        try:
            row = await conn.fetchrow(
                "SELECT route_id, route_data, created_at, eval_score, eval_result "
                "FROM planned_routes WHERE eval_score IS NOT NULL "
                "ORDER BY eval_score DESC LIMIT 1"
            )
            if row is None:
                return None
            route = _row_to_route(row)
            route.simulations = await _load_simulations(conn, route.route_id)
            return route
        finally:
            await conn.close()

    async def store_route_idempotent(
        self,
        route_id: str,
        route_data: dict,
        created_at: datetime,
        evaluation_score: float | None = None,
        evaluation_result: dict | None = None,
    ) -> None:
        """Insert a route preserving its original route_id (used by seed loader)."""
        conn = await _get_conn()
        try:
            await conn.execute(
                """
                INSERT INTO planned_routes (route_id, route_data, created_at, eval_score, eval_result)
                VALUES ($1, $2::jsonb, $3, $4, $5::jsonb)
                ON CONFLICT (route_id) DO NOTHING
                """,
                route_id,
                json.dumps(route_data),
                created_at,
                evaluation_score,
                json.dumps(evaluation_result) if evaluation_result is not None else None,
            )
        finally:
            await conn.close()
