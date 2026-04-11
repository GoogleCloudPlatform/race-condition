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

import asyncio
import json
import os

from google.adk.tools.tool_context import ToolContext

from agents.planner_with_memory.memory import embeddings as _embeddings
from agents.planner_with_memory.memory.schemas import PlannedRoute
from agents.planner_with_memory.memory.store_alloydb import AlloyDBRouteStore, _get_dsn

# Module-level singleton, shared across all tool invocations within the same
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
    """Best-effort store of a simulation summary for later vector search.

    Extracts prompt/city from ``tool_context.state`` and builds a combined
    summary string from the prompt + simulation result.  Silently no-ops if
    AlloyDB is unavailable, if running in local Postgres mode, or on any
    error -- this should not block the main ``record_simulation`` flow.
    """
    import logging
    import uuid

    import asyncpg

    logger = logging.getLogger(__name__)

    host = os.environ.get("ALLOYDB_HOST")
    if not host:
        return  # No database host configured

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

    dsn = _get_dsn()
    schema = os.environ.get("ALLOYDB_SCHEMA", "local_dev")

    # Pick the embedding strategy. EMBEDDING_BACKEND=vertex_ai (or auto-derived
    # from USE_ALLOYDB=false) computes the embedding client-side via Vertex AI;
    # otherwise we let AlloyDB's ai.initialize_embeddings trigger handle it on
    # INSERT. Embedding errors here are non-fatal (this is a background helper).
    backend = os.environ.get("EMBEDDING_BACKEND", "").lower()
    use_alloydb = os.environ.get("USE_ALLOYDB", "true").lower()
    if not backend:
        backend = "vertex_ai" if use_alloydb == "false" else "alloydb_ai"

    embedding_vec: list[float] | None = None
    if backend == "vertex_ai":
        try:
            embedding_vec = await _embeddings.compute_embedding(summary_text)
        except Exception as exc:
            logger.debug("Auto-store embedding failed (non-fatal): %s", exc)

    try:
        conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{schema}, public"})
        try:
            if embedding_vec is not None:
                await conn.execute(
                    """
                    INSERT INTO simulation_summaries
                        (summary_id, city, prompt, summary, route_id, sim_result, created_at, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, now(), $7::vector)
                    """,
                    str(uuid.uuid4()),
                    city or None,
                    prompt,
                    summary_text,
                    route_id,
                    json.dumps(parsed_result, default=str),
                    embedding_vec,
                )
            else:
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


async def store_route(tool_context: ToolContext) -> dict:
    """Persist the currently-active marathon route from session state.

    Reads ``marathon_route`` (and optional ``evaluation_result``) from
    ``tool_context.state``.  Large payloads never cross the LLM boundary
    as function arguments — the LLM passes nothing here.

    Returns:
        ``{"status": "success", "route_id": "<uuid>"}`` on success, or
        ``{"status": "error", "message": "..."}`` if the required state is missing.
    """
    route_data = tool_context.state.get("marathon_route")
    if not isinstance(route_data, dict) or not route_data:
        return {
            "status": "error",
            "message": (
                "No marathon_route in session state. "
                "Call plan_marathon_route (or get_route(activate_route=True)) first."
            ),
        }

    eval_result = tool_context.state.get("evaluation_result")
    eval_result_dict: dict | None = eval_result if isinstance(eval_result, dict) else None
    eval_score: float | None = None
    if eval_result_dict is not None:
        score = eval_result_dict.get("overall_score")
        if isinstance(score, (int, float)):
            eval_score = float(score)

    route_id = await _store.store_route(
        route_data=route_data,
        evaluation_score=eval_score,
        evaluation_result=eval_result_dict,
    )
    tool_context.state["active_route_id"] = route_id
    return {"status": "success", "route_id": route_id}


async def record_simulation(route_id: str, tool_context: ToolContext) -> dict:
    """Record the most recent simulation result against an existing route.

    Reads ``simulation_result`` from ``tool_context.state`` (set by
    ``submit_plan_to_simulator`` after a successful simulator call).
    The LLM passes only the ``route_id``; the large simulation payload
    never crosses the LLM boundary as a function argument.

    Also automatically stores a summary into ``simulation_summaries`` for
    later vector search (no separate tool call needed).

    Returns:
        ``{"status": "success", "simulation_id": "<uuid>"}`` on success,
        ``{"status": "error", ...}`` if state is missing or route_id unknown.
    """
    parsed_result = tool_context.state.get("simulation_result")
    if not isinstance(parsed_result, dict):
        return {
            "status": "error",
            "message": (
                "No simulation_result in session state. Call submit_plan_to_simulator(action='execute') first."
            ),
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
        tool_context.state["active_route_id"] = route.route_id
        if isinstance(route.route_data, dict):
            tool_context.state["route_name"] = route.route_data.get(
                "name", route.route_data.get("theme", "Stored Route")
            )
        else:
            tool_context.state["route_name"] = "Stored Route"
        if route.evaluation_score is not None:
            tool_context.state["evaluation_score"] = route.evaluation_score
        if route.evaluation_result is not None:
            tool_context.state["evaluation_result"] = route.evaluation_result
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


async def get_planned_routes_data(
    tool_context: ToolContext,
    route_ids: list[str] | None = None,
    limit: int = 5,
) -> dict:
    """Retrieve route data and evaluation results for batch display.

    If route_ids are provided, fetches those specific routes. Otherwise
    fetches recent routes up to ``limit``.  Returns structured route data
    so the LLM can compose A2UI cards via ``validate_and_emit_a2ui``.

    Args:
        route_ids: UUIDs to fetch. If None, fetches recent routes.
        tool_context: ADK tool context.
        limit: Max routes when route_ids is None.

    Returns:
        ``{"status": "success", "count": N, "routes": [...]}``
        or ``{"status": "error", "message": "..."}``.
    """
    if route_ids:
        routes = list(await asyncio.gather(*(_store.get_route(rid) for rid in route_ids)))
        routes = [r for r in routes if r]
    else:
        routes = await _store.recall_routes(count=limit, sort_by="recent")

    if not routes:
        return {"status": "error", "message": "No routes found."}

    route_dicts = []
    for route in routes:
        name = "Route"
        distance = "\u2014"
        if isinstance(route.route_data, dict):
            name = route.route_data.get("name", route.route_data.get("theme", f"Route {route.route_id[:8]}"))
            distance = route.route_data.get("total_distance_miles", route.route_data.get("distance", "\u2014"))

        route_dicts.append(
            {
                "route_id": route.route_id,
                "name": name,
                "distance": distance,
                "evaluation_score": route.evaluation_score,
                "created_at": route.created_at.isoformat() if route.created_at else None,
            }
        )

    return {
        "status": "success",
        "count": len(route_dicts),
        "routes": route_dicts,
    }


async def get_local_and_traffic_rules(
    query: str,
    tool_context: ToolContext,
    city: str | None = None,
    limit: int = 5,
) -> dict:
    """Search local traffic rules relevant to marathon planning.

    Performs a vector similarity search on the AlloyDB ``rules`` table
    using the query text.  Optionally filters by city.

    When running against a local Postgres container (``USE_ALLOYDB=false`` or
    when the ``ai.embedding`` function is unavailable), the tool falls back to
    returning two sample rule chunks so the agent can continue planning
    without interruption.

    Args:
        query: Natural-language description of what you are looking for, e.g.
            ``"restrictions for running a race on the Las Vegas strip"``.
        tool_context: ADK tool context.
        city: Optional city name to filter results (e.g. ``"Las Vegas"``).
        limit: Maximum number of rule chunks to return (default 5).

    Returns:
        ``{"status": "success", "rules": [{"city": ..., "text": ...}]}``
        or ``{"status": "error", "message": "..."}``
    """
    import asyncpg

    # ------------------------------------------------------------------
    # Sample chunks used when the AlloyDB AI extension is unavailable.
    # Sourced from alloydb/seed_regulations.sql, two real rule chunks.
    # ------------------------------------------------------------------
    _SAMPLE_RULES = [
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
            "message": "ALLOYDB_HOST is not configured. Cannot query rules.",
        }

    # EMBEDDING_BACKEND selects the embedding strategy (mirrors store_simulation_summary):
    #   - "alloydb_ai" (default): SQL uses the AlloyDB ai.embedding() extension.
    #   - "vertex_ai": embedding is computed client-side via google-genai and
    #     passed as a $N::vector parameter. Required for OSS Cloud SQL or local
    #     Postgres deploys (no ai.embedding extension). Auto-derived when
    #     USE_ALLOYDB=false so existing local-dev workflows need no extra var.
    backend_explicit = bool(os.environ.get("EMBEDDING_BACKEND"))
    backend = os.environ.get("EMBEDDING_BACKEND", "").lower()
    use_alloydb = os.environ.get("USE_ALLOYDB", "true").lower()
    if not backend:
        backend = "vertex_ai" if use_alloydb == "false" else "alloydb_ai"

    def _samples_response(note: str) -> dict:
        return {
            "status": "success",
            "count": len(_SAMPLE_RULES),
            "rules": _SAMPLE_RULES,
            "regulations": _SAMPLE_RULES,  # backward compat for frontend
            "message": "Found the following rules (Sample Mode):\n"
            + "\n\n".join([f"- {r['city']}:\n{r['text']}" for r in _SAMPLE_RULES]),
            "note": note,
        }

    # Local Postgres container mode without Vertex AI: ai.embedding() extension
    # is not available, so return sample chunks so the agent can continue
    # planning gracefully. EMBEDDING_BACKEND=vertex_ai bypasses this since
    # Vertex AI is always available.
    if use_alloydb == "false" and backend != "vertex_ai":
        return _samples_response("Sample rules returned (local Postgres mode — ai.embedding not available).")

    dsn = _get_dsn()
    schema = os.environ.get("ALLOYDB_SCHEMA", "local_dev")

    try:
        conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{schema}, public"})
        try:
            if backend == "vertex_ai":
                from agents.planner_with_memory.memory import embeddings

                query_vec = await embeddings.compute_embedding(query)
                if city:
                    rows = await conn.fetch(
                        """
                        SELECT city, text,
                               (embedding <=> $1::vector) AS distance
                        FROM rules
                        WHERE city = $2
                        ORDER BY distance ASC
                        LIMIT $3
                        """,
                        query_vec,
                        city,
                        limit,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT city, text,
                               (embedding <=> $1::vector) AS distance
                        FROM rules
                        ORDER BY distance ASC
                        LIMIT $2
                        """,
                        query_vec,
                        limit,
                    )
            else:
                if city:
                    rows = await conn.fetch(
                        """
                        SELECT city, text,
                               (embedding <=> ai.embedding('gemini-embedding-001', $1)::vector) AS distance
                        FROM rules
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
                        FROM rules
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
        # USE_ALLOYDB=true but without the extension), fall back to samples.
        if backend != "vertex_ai" and ("ai.embedding" in exc_str or "function ai." in exc_str):
            return _samples_response("Sample rules returned (ai.embedding extension unavailable).")
        # Auto-derived vertex_ai (USE_ALLOYDB=false without explicit
        # EMBEDDING_BACKEND): preserve dev's "always graceful" contract by
        # falling back to samples on embedding/DB errors. Explicit vertex_ai
        # callers (OSS deploys) get the real error so they can debug.
        if backend == "vertex_ai" and not backend_explicit:
            return _samples_response("Sample rules returned (local Postgres mode — Vertex AI embedding unavailable).")
        return {"status": "error", "message": f"Failed to query rules: {exc}"}

    rules = [{"city": r["city"], "text": r["text"]} for r in rows]

    message = "No local traffic rules found."
    if rules:
        message = "Found the following rules:\n" + "\n\n".join([f"- {r['city']}:\n{r['text']}" for r in rules])

    return {
        "status": "success",
        "count": len(rules),
        "rules": rules,
        "regulations": rules,  # backward compat for frontend
        "message": message,
    }


# ---------------------------------------------------------------------------
# Simulation history tools (RAG over past simulations)
# ---------------------------------------------------------------------------


async def store_simulation_summary(
    prompt: str,
    summary: str,
    tool_context: ToolContext,
    city: str | None = None,
    route_id: str | None = None,
) -> dict:
    """Store a summary of a simulation run for later vector search.

    The ``summary`` field should combine the original prompt with a concise
    description of the simulation results so that vector searches
    can find matching past simulations.

    The raw simulation result (if any) is read from
    ``tool_context.state["simulation_result"]`` (populated by
    ``submit_plan_to_simulator``).  The LLM passes only small scalar
    arguments; large payloads never cross the function-call boundary.

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

    Returns:
        ``{"status": "success", "summary_id": "<uuid>"}`` or
        ``{"status": "error", "message": "..."}``
    """
    import uuid

    import asyncpg

    host = os.environ.get("ALLOYDB_HOST")
    if not host:
        return {
            "status": "error",
            "message": "ALLOYDB_HOST is not configured. Cannot store simulation summary.",
        }

    # Read optional raw simulation result from session state.
    sim_result = tool_context.state.get("simulation_result") if tool_context else None
    parsed_result: dict | None = sim_result if isinstance(sim_result, dict) else None

    dsn = _get_dsn()
    schema = os.environ.get("ALLOYDB_SCHEMA", "local_dev")

    summary_id = str(uuid.uuid4())

    # EMBEDDING_BACKEND selects the embedding strategy:
    #   - "alloydb_ai" (default): rely on AlloyDB's ai.initialize_embeddings
    #     trigger to populate the embedding column on INSERT (no embedding
    #     parameter passed in the SQL).
    #   - "vertex_ai": compute the embedding client-side via google-genai and
    #     pass it explicitly. Required for OSS Cloud SQL / local Postgres
    #     which lack the ai.embedding extension. Auto-derived when
    #     USE_ALLOYDB=false so existing local-dev workflows need no extra var.
    backend = os.environ.get("EMBEDDING_BACKEND", "").lower()
    if not backend:
        backend = "vertex_ai" if os.environ.get("USE_ALLOYDB", "true").lower() == "false" else "alloydb_ai"

    try:
        conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{schema}, public"})
        try:
            if backend == "vertex_ai":
                from agents.planner_with_memory.memory import embeddings

                embedding_vec = await embeddings.compute_embedding(summary)
                await conn.execute(
                    """
                    INSERT INTO simulation_summaries
                        (summary_id, city, prompt, summary, route_id, sim_result, created_at, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, now(), $7::vector)
                    """,
                    summary_id,
                    city,
                    prompt,
                    summary,
                    route_id,
                    json.dumps(parsed_result) if parsed_result is not None else None,
                    embedding_vec,
                )
            else:
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
    summaries so the agent can reference prior runs.

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
    import asyncpg

    # Persist the user's prompt and city in session state so that
    # _auto_store_summary (inside record_simulation) can build a
    # summary later, even if the LLM never calls
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
            "message": "ALLOYDB_HOST not configured. No past simulations available.",
        }

    # EMBEDDING_BACKEND selects the embedding strategy (mirrors store_simulation_summary):
    #   - "alloydb_ai" (default): SQL uses the AlloyDB ai.embedding() extension.
    #   - "vertex_ai": embedding is computed client-side via google-genai and
    #     passed as a $N::vector parameter. Required for OSS Cloud SQL or local
    #     Postgres deploys (no ai.embedding extension). Auto-derived when
    #     USE_ALLOYDB=false so existing local-dev workflows need no extra var.
    backend_explicit = bool(os.environ.get("EMBEDDING_BACKEND"))
    backend = os.environ.get("EMBEDDING_BACKEND", "").lower()
    use_alloydb = os.environ.get("USE_ALLOYDB", "true").lower()
    if not backend:
        backend = "vertex_ai" if use_alloydb == "false" else "alloydb_ai"

    _empty_response = {
        "status": "success",
        "count": 0,
        "simulations": [],
        "message": "No past simulations available (local Postgres mode, ai.embedding not available).",
    }

    # Local Postgres container mode without Vertex AI: ai.embedding() is
    # unavailable, so return empty results. EMBEDDING_BACKEND=vertex_ai
    # bypasses this since Vertex AI is always available.
    if use_alloydb == "false" and backend != "vertex_ai":
        return _empty_response

    dsn = _get_dsn()
    schema = os.environ.get("ALLOYDB_SCHEMA", "local_dev")

    try:
        conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{schema}, public"})
        try:
            if backend == "vertex_ai":
                from agents.planner_with_memory.memory import embeddings

                query_vec = await embeddings.compute_embedding(query)
                if city:
                    rows = await conn.fetch(
                        """
                        SELECT city, prompt, summary, sim_result, created_at,
                               (embedding <=> $1::vector) AS distance
                        FROM simulation_summaries
                        WHERE city = $2
                        ORDER BY distance ASC
                        LIMIT $3
                        """,
                        query_vec,
                        city,
                        limit,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT city, prompt, summary, sim_result, created_at,
                               (embedding <=> $1::vector) AS distance
                        FROM simulation_summaries
                        ORDER BY distance ASC
                        LIMIT $2
                        """,
                        query_vec,
                        limit,
                    )
            else:
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
        if backend != "vertex_ai" and ("ai.embedding" in exc_str or "function ai." in exc_str):
            return {
                "status": "success",
                "count": 0,
                "simulations": [],
                "message": "No past simulations available (ai.embedding extension unavailable).",
            }
        # Auto-derived vertex_ai (USE_ALLOYDB=false without explicit
        # EMBEDDING_BACKEND): preserve dev's "always graceful" contract by
        # returning empty results on embedding/DB errors. Explicit vertex_ai
        # callers (OSS deploys) get the real error so they can debug.
        if backend == "vertex_ai" and not backend_explicit:
            return _empty_response
        return {"status": "error", "message": f"Failed to query past simulations: {exc}"}

    simulations = []
    sim_parts = []
    for i, r in enumerate(rows, 1):
        date_str = r["created_at"].isoformat() if r["created_at"] else "Unknown"
        simulations.append(
            {
                "city": r["city"],
                "prompt": r["prompt"],
                "summary": r["summary"],
                "sim_result": r["sim_result"],
                "created_at": date_str,
            }
        )
        sim_parts.append(
            f"Simulation {i}:\n"
            f"  City: {r['city']}\n"
            f"  Prompt: {r['prompt']}\n"
            f"  Summary: {r['summary']}\n"
            f"  Result: {r['sim_result']}\n"
            f"  Date: {date_str}"
        )
    simulations_text = "\n\n".join(sim_parts)

    message = (
        "No past simulations found."
        if not sim_parts
        else "Found the following past simulations:\n\n" + simulations_text
    )

    return {"status": "success", "count": len(simulations), "simulations": simulations, "message": message}
