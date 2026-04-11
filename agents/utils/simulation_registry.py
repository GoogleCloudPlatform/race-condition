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

"""Distributed simulation registry backed by Redis.

Maps session_id → simulation_id across all Agent Engine instances.
Uses per-key Redis STRINGs with a 2-hour TTL as the source of truth,
with a process-local L1 cache for fast reads.  Falls back to
process-local only when Redis is unavailable (unit tests, local dev
without Redis).

Thread-safety: CPython dict get/set are GIL-protected.  Redis operations
are async and use the shared connection pool.
"""

import logging

from agents.utils.redis_pool import get_shared_redis_client

logger = logging.getLogger(__name__)

_REDIS_SESSION_PREFIX = "simreg:session:"
_REDIS_CONTEXT_PREFIX = "simreg:context:"
_TTL_SECONDS = 7200

# Process-local L1 cache — populated on register(), used as fast-path.
_local: dict[str, str] = {}

# Maps Vertex AI session_id → original A2A context_id (spawn session UUID).
# On Agent Engine, VertexAiSessionService generates its own session IDs that
# differ from the gateway's spawn session IDs.  DashLogPlugin uses this
# mapping to emit events with the original spawn ID so the frontend's
# session-based rendering filters work.
_context_map: dict[str, str] = {}


async def register(session_id: str, simulation_id: str) -> None:
    """Associate a session with a simulation (writes to Redis + L1)."""
    _local[session_id] = simulation_id
    r = get_shared_redis_client()
    if r is not None:
        try:
            await r.setex(f"{_REDIS_SESSION_PREFIX}{session_id}", _TTL_SECONDS, simulation_id)  # type: ignore[misc]
        except Exception:
            logger.warning("simreg: Redis write failed for %s", session_id, exc_info=True)


async def lookup(session_id: str) -> str | None:
    """Return the simulation_id for a session, or None.

    Checks the process-local L1 cache first, then falls back to Redis
    so that lookups succeed even when the register() happened on a
    different Agent Engine instance.
    """
    # L1 fast-path
    result = _local.get(session_id)
    if result is not None:
        return result

    # L2: Redis (cross-instance)
    r = get_shared_redis_client()
    if r is not None:
        try:
            val = await r.get(f"{_REDIS_SESSION_PREFIX}{session_id}")  # type: ignore[misc]
            if val is not None:
                decoded = val if isinstance(val, str) else val.decode()
                _local[session_id] = decoded  # warm L1
                return decoded
        except Exception:
            logger.warning("simreg: Redis read failed for %s", session_id, exc_info=True)

    return None


async def register_context(vertex_session_id: str, context_id: str) -> None:
    """Map a Vertex AI session_id back to the original A2A context_id.

    Called by SimulationExecutor after SessionManager creates a session.
    DashLogPlugin calls ``get_context_id()`` to retrieve the original
    spawn session UUID for the protobuf origin field.
    """
    _context_map[vertex_session_id] = context_id
    r = get_shared_redis_client()
    if r is not None:
        try:
            await r.setex(f"{_REDIS_CONTEXT_PREFIX}{vertex_session_id}", _TTL_SECONDS, context_id)  # type: ignore[misc]
        except Exception:
            logger.warning("simreg: Redis context write failed for %s", vertex_session_id, exc_info=True)


async def get_context_id(vertex_session_id: str) -> str | None:
    """Return the original context_id for a Vertex AI session, or None."""
    result = _context_map.get(vertex_session_id)
    if result is not None:
        return result

    r = get_shared_redis_client()
    if r is not None:
        try:
            val = await r.get(f"{_REDIS_CONTEXT_PREFIX}{vertex_session_id}")  # type: ignore[misc]
            if val is not None:
                decoded = val if isinstance(val, str) else val.decode()
                _context_map[vertex_session_id] = decoded
                return decoded
        except Exception:
            logger.warning("simreg: Redis context read failed for %s", vertex_session_id, exc_info=True)

    return None


async def unregister(session_id: str) -> None:
    """Remove a session from the registry (L1 + Redis)."""
    _local.pop(session_id, None)
    r = get_shared_redis_client()
    if r is not None:
        try:
            await r.delete(f"{_REDIS_SESSION_PREFIX}{session_id}")  # type: ignore[misc]
        except Exception:
            logger.warning("simreg: Redis unregister failed for %s", session_id, exc_info=True)


async def clear() -> None:
    """Remove all entries (for environment_reset)."""
    _local.clear()
    _context_map.clear()
    r = get_shared_redis_client()
    if r is not None:
        try:
            for prefix in (_REDIS_SESSION_PREFIX, _REDIS_CONTEXT_PREFIX):
                batch: list = []
                async for key in r.scan_iter(match=f"{prefix}*", count=100):  # type: ignore[misc]
                    batch.append(key)
                    if len(batch) >= 100:
                        await r.delete(*batch)  # type: ignore[misc]
                        batch.clear()
                if batch:
                    await r.delete(*batch)  # type: ignore[misc]
        except Exception:
            logger.warning("simreg: Redis clear failed", exc_info=True)
