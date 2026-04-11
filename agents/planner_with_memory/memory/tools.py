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

"""ADK FunctionTool wrappers for route memory operations.

Each function accepts JSON strings from the LLM, delegates to the
AlloyDBRouteStore, and returns a structured dict for A2A compliance.
"""

from __future__ import annotations

import json

from google.adk.tools.tool_context import ToolContext

from agents.planner_with_memory.memory.schemas import PlannedRoute
from agents.planner_with_memory.memory.store_alloydb import AlloyDBRouteStore

# Module-level singleton — shared across all tool invocations within the same
# process. Tests may replace _store directly for isolation.
_store = AlloyDBRouteStore()


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def _route_to_dict(route: PlannedRoute) -> dict:
    """Convert a PlannedRoute to a JSON-serialisable dict."""
    return {
        "route_id": route.route_id,
        "route_data": route.route_data,
        "created_at": route.created_at.isoformat(),
        "evaluation_score": route.evaluation_score,
        "evaluation_result": route.evaluation_result,
        "simulations": [
            {
                "simulation_id": sim.simulation_id,
                "route_id": sim.route_id,
                "simulation_result": sim.simulation_result,
                "simulated_at": sim.simulated_at.isoformat(),
            }
            for sim in route.simulations
        ],
    }


# ---------------------------------------------------------------------------
# Auto-store simulation summary (fires inside record_simulation)
# ---------------------------------------------------------------------------


async def _auto_store_summary(
    route_id: str,
    parsed_result: dict,
    tool_context: ToolContext,
) -> None:
    """Best-effort store of a simulation summary for future semantic recall.

    Extracts prompt/city from ``tool_context.state`` and builds a combined
    summary string from the prompt + simulation result.  Silently no-ops if
    AlloyDB is unavailable, if running in local Postgres mode, or on any
    error — this must never block the main ``record_simulation`` flow.
    """
    import logging
    import os
    import uuid

    import asyncpg

    logger = logging.getLogger(__name__)

    use_alloydb = os.environ.get("USE_ALLOYDB", "true").lower()
    host = os.environ.get("ALLOYDB_HOST")
    if use_alloydb == "false" or not host:
        return  # Nothing to do in local mode

    # Extract context from session state (set by the agent during planning)
    state = getattr(tool_context, "state", {}) or {}
    prompt = state.get("user_prompt", state.get("prompt", ""))
    city = state.get("city", "")

    # If prompt is empty, try to build one from the result
    if not prompt:
        prompt = parsed_result.get("prompt", parsed_result.get("description", "simulation run"))

    # Build a combined summary for embedding
    result_summary = json.dumps(parsed_result, default=str)[:500]
    summary_text = f"Prompt: {prompt}. City: {city or 'unknown'}. Result: {result_summary}"

    database = os.environ.get("ALLOYDB_DATABASE", "postgres")
    user = os.environ.get("ALLOYDB_USER", "postgres")
    password = os.environ.get("ALLOYDB_PASSWORD", "")
    port = int(os.environ.get("ALLOYDB_PORT", "5432"))
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    schema = os.environ.get("ALLOYDB_SCHEMA", "local_dev")

    try:
        conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{schema}, public"})
        try:
            await conn.execute(
                """
                INSERT INTO simulation_summaries
                    (summary_id, city, prompt, summary, route_id, sim_result, created_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, now())
                """,
                str(uuid.uuid4()),
                city or None,
                prompt,
                summary_text,
                route_id,
                json.dumps(parsed_result, default=str),
            )
            logger.info("Auto-stored simulation summary for route %s", route_id)
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning("Failed to auto-store simulation summary (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# ADK tool functions
# ---------------------------------------------------------------------------


async def store_route(
    route_data: str,
    tool_context: ToolContext,
    evaluation_result: str | None = None,
) -> dict:
    """Store a planned route.

    Args:
        route_data: JSON string describing the route.
        tool_context: ADK tool context (unused but required by framework).
        evaluation_result: Optional JSON string with evaluation data.  If the
            parsed dict contains an ``overall_score`` key its value is used as
            the ``evaluation_score``.

    Returns:
        ``{"status": "success", "route_id": "<uuid>"}`` on success, or
        ``{"status": "error", "message": "..."}`` on JSON parse failure.
    """
    try:
        parsed_route = json.loads(route_data)
    except (json.JSONDecodeError, TypeError) as exc:
        return {"status": "error", "message": f"Invalid route_data JSON: {exc}"}

    parsed_eval: dict | None = None
    eval_score: float | None = None

    if evaluation_result is not None:
        try:
            parsed_eval = json.loads(evaluation_result)
        except (json.JSONDecodeError, TypeError) as exc:
            return {
                "status": "error",
                "message": f"Invalid evaluation_result JSON: {exc}",
            }
        eval_score = parsed_eval.get("overall_score") if parsed_eval else None

    route_id = await _store.store_route(
        route_data=parsed_route,
        evaluation_score=eval_score,
        evaluation_result=parsed_eval,
    )
    return {"status": "success", "route_id": route_id}


async def record_simulation(
    route_id: str,
    simulation_result: str,
    tool_context: ToolContext,
) -> dict:
    """Record a simulation result against an existing route.

    Also automatically stores a summary into ``simulation_summaries`` for
    future semantic recall (no separate tool call needed).

    Args:
        route_id: UUID of the route.
        simulation_result: JSON string with simulation outcome.
        tool_context: ADK tool context.

    Returns:
        ``{"status": "success", "simulation_id": "<uuid>"}`` on success,
        ``{"status": "error", ...}`` otherwise.
    """
    try:
        parsed_result = json.loads(simulation_result)
    except (json.JSONDecodeError, TypeError) as exc:
        return {
            "status": "error",
            "message": f"Invalid simulation_result JSON: {exc}",
        }

    sim_id = await _store.record_simulation(
        route_id=route_id,
        simulation_result=parsed_result,
    )
    if sim_id is None:
        return {
            "status": "error",
            "message": f"Route not found: {route_id}",
        }

    # --- Auto-store simulation summary for semantic recall ---
    await _auto_store_summary(
        route_id=route_id,
        parsed_result=parsed_result,
        tool_context=tool_context,
    )

    return {"status": "success", "simulation_id": sim_id}


async def recall_routes(
    tool_context: ToolContext,
    count: int = 10,
    sort_by: str = "recent",
) -> dict:
    """Query stored routes.

    Args:
        tool_context: ADK tool context.
        count: Maximum number of routes to return.
        sort_by: ``"recent"`` or ``"best_score"``.

    Returns:
        ``{"status": "success", "count": N, "routes": [...]}``.
    """
    routes = await _store.recall_routes(count=count, sort_by=sort_by)
    serialised = [_route_to_dict(r) for r in routes]
    return {"status": "success", "count": len(serialised), "routes": serialised}


async def get_route(
    route_id: str,
    tool_context: ToolContext,
    activate_route: bool = False,
) -> dict:
    """Retrieve a specific route by UUID.

    Args:
        route_id: UUID of the route.
        tool_context: ADK tool context.
        activate_route: If True, load the route's GeoJSON into session state
            (``tool_context.state["marathon_route"]``).

    Returns:
        ``{"status": "success", "route": {...}}`` or
        ``{"status": "error", "message": "..."}``.
    """
    route = await _store.get_route(route_id)
    if route is None:
        return {"status": "error", "message": f"Route not found: {route_id}"}

    result = {"status": "success", "route": _route_to_dict(route)}

    if activate_route:
        tool_context.state["marathon_route"] = route.route_data
        result["activated"] = True

    return result


async def get_best_route(tool_context: ToolContext) -> dict:
    """Return the highest-scoring route.

    Args:
        tool_context: ADK tool context.

    Returns:
        ``{"status": "success", "route": {...}}`` or
        ``{"status": "error", "message": "..."}``.
    """
    route = await _store.get_best_route()
    if route is None:
        return {
            "status": "error",
            "message": "No scored routes found.",
        }
    return {"status": "success", "route": _route_to_dict(route)}


async def get_local_laws_and_regulations(
    query: str,
    tool_context: ToolContext,
    city: str | None = None,
    limit: int = 5,
) -> dict:
    """Search local laws and regulations relevant to marathon planning.

    Performs a vector similarity search on the AlloyDB ``regulations`` table
    using the query text.  Optionally filters by city.

    When running against a local Postgres container (``USE_ALLOYDB=false`` or
    when the ``ai.embedding`` function is unavailable), the tool degrades
    gracefully by returning two sample regulation chunks so the agent can
    continue planning without interruption.

    Args:
        query: Natural-language description of what you are looking for, e.g.
            ``"restrictions for running a race on the Las Vegas strip"``.
        tool_context: ADK tool context.
        city: Optional city name to filter results (e.g. ``"Las Vegas"``).
        limit: Maximum number of regulation chunks to return (default 5).

    Returns:
        ``{"status": "success", "regulations": [{"city": ..., "text": ...}]}``
        or ``{"status": "error", "message": "..."}``
    """
    import os

    import asyncpg

    # ------------------------------------------------------------------
    # Sample chunks used when the AlloyDB AI extension is unavailable.
    # Sourced from alloydb/seed_regulations.sql — two real regulation chunks.
    # ------------------------------------------------------------------
    _SAMPLE_REGULATIONS = [
        {
            "city": "Las Vegas",
            "text": (
                "LAS VEGAS MUNICIPAL CODE - SIDEWALK VENDORS (CHAPTER 6.96)\n"
                "6.96.070 - Operating Requirements and Prohibitions.\n"
                "(A) It is unlawful for a sidewalk vendor to:\n"
                "(1) Vend at locations where it will impede pedestrian traffic, "
                "normal use of the sidewalk, or hinder access or accessibility "
                "required by the Americans with Disabilities Act.\n"
                "(5) Vend within 1,500 feet of a resort hotel.\n"
                "(6) Vend within 1,000 feet of non-restricted gaming establishments, "
                "the Fremont Street Experience, the Downtown Entertainment Overlay "
                "District, city recreation facilities, pools, and schools."
            ),
        },
        {
            "city": "Las Vegas",
            "text": (
                "LAS VEGAS MUNICIPAL CODE - OBSTRUCTING PUBLIC RIGHTS-OF-WAY "
                "(SECTION 10.86.010)\n"
                "10.86.010 - Pedestrian interference—Prohibited locations.\n"
                "(A) It is unlawful for any person to sit, lie, sleep, camp, or "
                "otherwise lodge in the public right-of-way in the following locations:\n"
                "(1) Any public street or sidewalk next to a residential property.\n"
                "(2) Any public street or sidewalk within specific downtown districts.\n"
                "(B) It is a misdemeanor to obstruct the sidewalk during designated "
                "cleaning times."
            ),
        },
    ]

    host = os.environ.get("ALLOYDB_HOST")
    if not host:
        return {
            "status": "error",
            "message": "ALLOYDB_HOST is not configured. Cannot query regulations.",
        }

    # Local Postgres container mode: ai.embedding() extension is not available.
    # Return sample chunks so the agent can continue planning gracefully.
    use_alloydb = os.environ.get("USE_ALLOYDB", "true").lower()
    if use_alloydb == "false":
        return {
            "status": "success",
            "count": len(_SAMPLE_REGULATIONS),
            "regulations": _SAMPLE_REGULATIONS,
            "note": "Sample regulations returned (local Postgres mode — ai.embedding not available).",
        }

    database = os.environ.get("ALLOYDB_DATABASE", "postgres")
    user = os.environ.get("ALLOYDB_USER", "postgres")
    password = os.environ.get("ALLOYDB_PASSWORD", "")
    port = int(os.environ.get("ALLOYDB_PORT", "5432"))
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    schema = os.environ.get("ALLOYDB_SCHEMA", "local_dev")

    try:
        conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{schema}, public"})
        try:
            if city:
                rows = await conn.fetch(
                    """
                    SELECT city, text,
                           (embedding <=> ai.embedding('gemini-embedding-001', $1)::vector) AS distance
                    FROM regulations
                    WHERE city = $2
                    ORDER BY distance ASC
                    LIMIT $3
                    """,
                    query,
                    city,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT city, text,
                           (embedding <=> ai.embedding('gemini-embedding-001', $1)::vector) AS distance
                    FROM regulations
                    ORDER BY distance ASC
                    LIMIT $2
                    """,
                    query,
                    limit,
                )
        finally:
            await conn.close()
    except Exception as exc:
        exc_str = str(exc)
        # The ai.embedding() function is an AlloyDB-only extension.  When
        # targeting a plain Postgres instance (e.g. during local testing with
        # USE_ALLOYDB=true but without the extension), degrade gracefully.
        if "ai.embedding" in exc_str or "function ai." in exc_str:
            return {
                "status": "success",
                "count": len(_SAMPLE_REGULATIONS),
                "regulations": _SAMPLE_REGULATIONS,
                "note": "Sample regulations returned (ai.embedding extension unavailable).",
            }
        return {"status": "error", "message": f"Failed to query regulations: {exc}"}

    regulations = [{"city": r["city"], "text": r["text"]} for r in rows]
    return {"status": "success", "count": len(regulations), "regulations": regulations}


# ---------------------------------------------------------------------------
# Simulation history tools (RAG over past simulations)
# ---------------------------------------------------------------------------


async def store_simulation_summary(
    prompt: str,
    summary: str,
    tool_context: ToolContext,
    city: str | None = None,
    route_id: str | None = None,
    simulation_result: str | None = None,
) -> dict:
    """Store a summary of a simulation run for future semantic recall.

    The ``summary`` field should combine the original prompt with a concise
    description of the simulation results so that future vector searches
    can surface relevant past experiences.

    Args:
        prompt: The original user prompt that initiated the simulation
            (e.g. ``"Plan a marathon in Las Vegas for 5000 runners"``).
        summary: A combined prompt + result summary for embedding, e.g.
            ``"Planned a 26.2-mile marathon in Las Vegas for 5000 runners.
            Route starts at Mandalay Bay, passes the Strip.  Simulation
            showed 98% completion rate with avg finish time 4h12m."``
        tool_context: ADK tool context.
        city: Optional city name (e.g. ``"Las Vegas"``).
        route_id: Optional UUID of the associated planned route.
        simulation_result: Optional JSON string with the raw sim result.

    Returns:
        ``{"status": "success", "summary_id": "<uuid>"}`` or
        ``{"status": "error", "message": "..."}``
    """
    import os
    import uuid

    import asyncpg

    host = os.environ.get("ALLOYDB_HOST")
    if not host:
        return {
            "status": "error",
            "message": "ALLOYDB_HOST is not configured. Cannot store simulation summary.",
        }

    # Local Postgres container mode: table/embeddings not available.
    use_alloydb = os.environ.get("USE_ALLOYDB", "false").lower()
    if use_alloydb == "false":
        return {
            "status": "success",
            "summary_id": "local-mode-skipped",
            "note": "Simulation summary not persisted (local Postgres mode).",
        }

    # Parse optional simulation_result JSON
    parsed_result = None
    if simulation_result:
        try:
            parsed_result = json.loads(simulation_result)
        except (json.JSONDecodeError, TypeError):
            parsed_result = None

    database = os.environ.get("ALLOYDB_DATABASE", "postgres")
    user = os.environ.get("ALLOYDB_USER", "postgres")
    password = os.environ.get("ALLOYDB_PASSWORD", "")
    port = int(os.environ.get("ALLOYDB_PORT", "5432"))
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    schema = os.environ.get("ALLOYDB_SCHEMA", "local_dev")

    summary_id = str(uuid.uuid4())

    try:
        conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{schema}, public"})
        try:
            await conn.execute(
                """
                INSERT INTO simulation_summaries
                    (summary_id, city, prompt, summary, route_id, sim_result, created_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, now())
                """,
                summary_id,
                city,
                prompt,
                summary,
                route_id,
                json.dumps(parsed_result) if parsed_result is not None else None,
            )
        finally:
            await conn.close()
    except Exception as exc:
        return {"status": "error", "message": f"Failed to store simulation summary: {exc}"}

    return {"status": "success", "summary_id": summary_id}


async def recall_past_simulations(
    query: str,
    tool_context: ToolContext,
    city: str | None = None,
    limit: int = 2,
) -> dict:
    """Retrieve the most relevant past simulation summaries via semantic search.

    Performs a vector similarity search on the ``simulation_summaries`` table
    using the query text.  Returns the top N most similar past simulation
    summaries so the agent can learn from prior runs.

    When running against a local Postgres container (``USE_ALLOYDB=false`` or
    when ``ai.embedding`` is unavailable), returns an empty list gracefully.

    Args:
        query: Natural-language description of what you are planning, e.g.
            ``"marathon in Las Vegas for 10000 runners"``.
        tool_context: ADK tool context.
        city: Optional city name to filter results.
        limit: Maximum number of past simulations to return (default 2).

    Returns:
        ``{"status": "success", "count": N, "simulations": [...]}`` where each
        simulation contains ``city``, ``prompt``, ``summary``, ``sim_result``,
        and ``created_at``.
    """
    import os

    import asyncpg

    # Persist the user's prompt and city in session state so that
    # _auto_store_summary (inside record_simulation) can build a
    # meaningful summary later — even if the LLM never calls
    # store_simulation_summary explicitly.
    tool_context.state["user_prompt"] = query
    if city:
        tool_context.state["city"] = city

    host = os.environ.get("ALLOYDB_HOST")
    if not host:
        return {
            "status": "success",
            "count": 0,
            "simulations": [],
            "note": "ALLOYDB_HOST not configured. No past simulations available.",
        }

    # Local Postgres container mode: ai.embedding() is not available.
    use_alloydb = os.environ.get("USE_ALLOYDB", "true").lower()
    if use_alloydb == "false":
        return {
            "status": "success",
            "count": 0,
            "simulations": [],
            "note": "No past simulations available 🐪 (local Postgres mode — ai.embedding not available).",
        }

    database = os.environ.get("ALLOYDB_DATABASE", "postgres")
    user = os.environ.get("ALLOYDB_USER", "postgres")
    password = os.environ.get("ALLOYDB_PASSWORD", "")
    port = int(os.environ.get("ALLOYDB_PORT", "5432"))
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    schema = os.environ.get("ALLOYDB_SCHEMA", "local_dev")

    try:
        conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{schema}, public"})
        try:
            if city:
                rows = await conn.fetch(
                    """
                    SELECT city, prompt, summary, sim_result, created_at,
                           (embedding <=> ai.embedding('gemini-embedding-001', $1)::vector) AS distance
                    FROM simulation_summaries
                    WHERE city = $2
                    ORDER BY distance ASC
                    LIMIT $3
                    """,
                    query,
                    city,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT city, prompt, summary, sim_result, created_at,
                           (embedding <=> ai.embedding('gemini-embedding-001', $1)::vector) AS distance
                    FROM simulation_summaries
                    ORDER BY distance ASC
                    LIMIT $2
                    """,
                    query,
                    limit,
                )
        finally:
            await conn.close()
    except Exception as exc:
        exc_str = str(exc)
        if "ai.embedding" in exc_str or "function ai." in exc_str:
            return {
                "status": "success",
                "count": 0,
                "simulations": [],
                "note": "No past simulations available (ai.embedding extension unavailable).",
            }
        return {"status": "error", "message": f"Failed to query past simulations: {exc}"}

    simulations = [
        {
            "city": r["city"],
            "prompt": r["prompt"],
            "summary": r["summary"],
            "sim_result": r["sim_result"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    return {"status": "success", "count": len(simulations), "simulations": simulations}
