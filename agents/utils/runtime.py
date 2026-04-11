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

"""Unified runtime service abstraction — env-var-driven target switching.

Selects the correct ADK session, artifact, and memory services based on
deployment environment variables:

- No cloud env vars       → InMemorySessionService (local dev)
- DATABASE_URL set        → DatabaseSessionService (Cloud Run)
- AGENT_ENGINE_ID or GOOGLE_CLOUD_AGENT_ENGINE_ID set → VertexAiSessionService (Agent Engine)

CRITICAL: This module must NEVER import or reference SQLite session stores.
See .agents/skills/high-concurrency-sessions/SKILL.md for rationale.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    """Read an integer from an environment variable, falling back to *default*."""
    raw = os.environ.get(name, "")
    return _int_env_raw(raw, default, name)


def _int_env_raw(raw: str, default: int, label: str) -> int:
    """Parse *raw* as an integer, falling back to *default* on failure."""
    try:
        return int(raw) if raw else default
    except ValueError:
        logger.warning("Invalid integer for %s=%r, using default %d", label, raw, default)
        return default


@dataclass
class ServiceConfig:
    """Container for ADK service instances selected by deployment target."""

    session_service: Any
    artifact_service: Optional[Any]
    memory_service: Optional[Any]
    target: str


def create_services() -> ServiceConfig:
    """Create ADK services based on deployment environment variables.

    Precedence:
        0. SESSION_STORE_OVERRIDE=inmemory|redis → Force override
        1. AGENT_ENGINE_ID or GOOGLE_CLOUD_AGENT_ENGINE_ID → Agent Engine
        2. DATABASE_URL → Cloud Run (Database session + GCS artifacts)
        3. Neither → Local dev (InMemory everything)

    SESSION_STORE_OVERRIDE values:
        inmemory — InMemorySessionService (diagnostic only, no durability)
        redis    — RedisSessionService from google-adk-community (durable,
                   fast, uses REDIS_ADDR for connection)

    The platform-canonical env var is GOOGLE_CLOUD_AGENT_ENGINE_ID (injected
    by Agent Engine at runtime). AGENT_ENGINE_ID is accepted for backward
    compatibility and takes precedence when both are set.

    Returns:
        ServiceConfig with the appropriate service instances.
    """
    # Check for session store override first
    override = os.environ.get("SESSION_STORE_OVERRIDE", "").lower()
    if override == "inmemory":
        return _create_inmemory_override_services()
    elif override == "redis":
        return _create_redis_override_services()
    elif override:
        logger.warning("Unrecognized SESSION_STORE_OVERRIDE=%r, falling through to default chain.", override)

    agent_engine_id = os.environ.get("AGENT_ENGINE_ID", "") or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "")
    database_url = os.environ.get("DATABASE_URL", "")

    if agent_engine_id:
        return _create_agent_engine_services()
    elif database_url:
        return _create_cloud_run_services()
    else:
        return _create_local_services()


def _create_inmemory_override_services() -> ServiceConfig:
    """Override: force InMemory session service regardless of cloud env vars.

    Used for performance diagnostics — isolates session-store latency from
    application logic. All other services (artifacts, memory) are set to None
    since this is a diagnostic mode, not a full local-dev environment.
    """
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    logger.warning(
        "Runtime target: inmemory_override (SESSION_STORE_OVERRIDE=inmemory). "
        "Database/Agent Engine session stores BYPASSED for perf testing."
    )
    return ServiceConfig(
        session_service=InMemorySessionService(),
        artifact_service=None,
        memory_service=None,
        target="inmemory_override",
    )


def _create_redis_override_services() -> ServiceConfig:
    """Override: use PrunedRedisSessionService for durable, fast sessions.

    Wraps the community RedisSessionService with event pruning to prevent
    session blob growth.  Without pruning, the blob grows ~4 events per tick
    and causes progressive degradation at scale (1000 runners).

    Reads REDIS_ADDR from the environment (same Redis used by the dispatcher).
    The session service creates its own async connection — separate from
    the dispatcher's shared pool, which is fine for Redis.
    """
    from agents.utils.pruned_session_service import PrunedRedisSessionService

    redis_addr = os.environ.get("REDIS_ADDR", "localhost:6379")
    max_conn = _int_env("REDIS_SESSION_MAX_CONNECTIONS", 100)
    if redis_addr.startswith("redis://"):
        redis_svc = PrunedRedisSessionService(uri=redis_addr, max_connections=max_conn)
    elif ":" in redis_addr:
        host, _, port_str = redis_addr.rpartition(":")
        port = _int_env_raw(port_str, 6379, "REDIS_ADDR port")
        redis_svc = PrunedRedisSessionService(host=host or "localhost", port=port, max_connections=max_conn)
    else:
        # Bare hostname without port — use default Redis port
        redis_svc = PrunedRedisSessionService(host=redis_addr or "localhost", port=6379, max_connections=max_conn)

    logger.warning(
        "Runtime target: redis_override (SESSION_STORE_OVERRIDE=redis). "
        "Using PrunedRedisSessionService at %s (max_connections=%d).",
        redis_addr,
        max_conn,
    )
    return ServiceConfig(
        session_service=redis_svc,
        artifact_service=None,
        memory_service=None,
        target="redis_override",
    )


def _create_local_services() -> ServiceConfig:
    """Local dev: InMemory session, artifacts, and memory."""
    from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
    from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    logger.info("Runtime target: local (InMemory everything)")
    return ServiceConfig(
        session_service=InMemorySessionService(),
        artifact_service=InMemoryArtifactService(),
        memory_service=InMemoryMemoryService(),
        target="local",
    )


def _create_agent_engine_services() -> ServiceConfig:
    """Agent Engine: VertexAi session + VertexAi memory bank.

    IMPORTANT: The custom SimulationExecutor (not ADK's A2aAgentExecutor)
    handles session creation via SessionManager, which correctly calls
    create_session() WITHOUT user-provided session IDs.
    """
    from google.adk.memory import VertexAiMemoryBankService
    from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService

    agent_engine_id = os.environ.get("AGENT_ENGINE_ID", "") or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = (
        os.environ.get("AGENT_ENGINE_LOCATION", "")
        or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION", "")
        or os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    )
    logger.info(
        "Runtime target: agent_engine (VertexAiSessionService + VertexAiMemoryBankService, id=%s)",
        agent_engine_id,
    )
    return ServiceConfig(
        session_service=VertexAiSessionService(
            project=project,
            location=location,
            agent_engine_id=agent_engine_id,
        ),
        artifact_service=None,  # Agent Engine manages artifacts internally
        memory_service=VertexAiMemoryBankService(
            project=project,
            location=location,
            agent_engine_id=agent_engine_id,
        ),
        target="agent_engine",
    )


def _create_cloud_run_services() -> ServiceConfig:
    """Cloud Run: Database session + GCS artifacts. No memory (runner is ephemeral)."""
    from google.adk.sessions.database_session_service import DatabaseSessionService
    import urllib.parse

    database_url = os.environ["DATABASE_URL"]
    logger.info("Runtime target: cloud_run (DatabaseSessionService)")

    # Connection pool sizing — forwarded as **kwargs to create_async_engine().
    # Defaults are intentionally higher than SQLAlchemy's (5/10) to support
    # concurrent session fan-out during broadcast events.
    pool_size = _int_env("DB_POOL_SIZE", 20)
    max_overflow = _int_env("DB_MAX_OVERFLOW", 20)
    logger.info("DB pool: pool_size=%d, max_overflow=%d", pool_size, max_overflow)

    # Workaround for asyncpg dialect not supporting options=-c search_path
    connect_args = {}
    if "?" in database_url:
        parsed = urllib.parse.urlsplit(database_url)
        query = urllib.parse.parse_qs(parsed.query)
        schema_name = None

        # Check for options=-c search_path=schema
        if "options" in query:
            options_str = query["options"][0]
            if "search_path=" in options_str:
                schema_name = options_str.split("search_path=")[-1].strip()
                query.pop("options")

        # Also check for explicit server_settings.search_path
        if "server_settings.search_path" in query:
            schema_name = query["server_settings.search_path"][0].strip()
            query.pop("server_settings.search_path")

        if schema_name:
            connect_args["server_settings"] = {"search_path": schema_name}
            new_query = urllib.parse.urlencode(query, doseq=True)
            database_url = urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
            )

    kwargs: dict[str, Any] = {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
    }
    if connect_args:
        kwargs["connect_args"] = connect_args

    # GCS artifact service — only if bucket is configured
    artifact_service = None
    gcs_bucket = os.environ.get("GCS_ARTIFACT_BUCKET", "")
    if gcs_bucket:
        from google.adk.artifacts.gcs_artifact_service import GcsArtifactService

        artifact_service = GcsArtifactService(bucket_name=gcs_bucket)
        logger.info("Cloud Run artifact store: GCS bucket %s", gcs_bucket)

    return ServiceConfig(
        session_service=DatabaseSessionService(db_url=database_url, **kwargs),
        artifact_service=artifact_service,
        memory_service=None,  # Runner NPCs are ephemeral — no cross-session memory
        target="cloud_run",
    )
