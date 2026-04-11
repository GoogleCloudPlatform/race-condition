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

"""Session Manager — maps A2A context_id to Vertex AI session_id.

Pattern from next26-simulation-demos/demo-2-autonomous-agents.
VertexAiSessionService.create_session() does NOT accept user-provided
session IDs.  This manager creates sessions without an ID (letting
Vertex generate one) and caches the context_id → session_id mapping.

Uses a two-tier cache for cross-worker session continuity:
  L1: per-process TTLCache (zero-latency, worker-local)
  L2: Redis (shared across all workers/containers)
"""

import logging
import time
from typing import Any, Optional

from agents.utils.redis_pool import get_shared_redis_client

logger = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "session_map:"


class TTLCache:
    """Simple TTL cache for mapping A2A context_id to Vertex AI session_id."""

    def __init__(self, maxsize: int = 1000, ttl: int = 7200) -> None:
        self._cache: dict[str, tuple[Any, float]] = {}
        self._maxsize = maxsize
        self._ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return value
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        if len(self._cache) >= self._maxsize:
            self._evict_oldest()
        self._cache[key] = (value, time.time())

    def _evict_oldest(self) -> None:
        if not self._cache:
            return
        sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][1])
        evict_count = max(1, len(sorted_keys) // 10)
        for key in sorted_keys[:evict_count]:
            del self._cache[key]

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __len__(self) -> int:
        self._cleanup_expired()
        return len(self._cache)

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired_keys = [key for key, (_, timestamp) in self._cache.items() if now - timestamp >= self._ttl]
        for key in expired_keys:
            del self._cache[key]


class SessionManager:
    """Manages sessions with A2A context mapping and two-tier caching.

    The key insight: VertexAiSessionService.create_session() rejects
    user-provided session_ids.  This manager calls create_session()
    WITHOUT a session_id, then caches the mapping from A2A context_id
    to the Vertex-generated session_id.

    Cache tiers:
      L1 (TTLCache): per-process, zero-latency, worker-local
      L2 (Redis):    shared across all workers/containers
    """

    def __init__(
        self,
        session_service: Any,
        cache_maxsize: int = 1000,
        cache_ttl: int = 7200,
    ) -> None:
        self.session_service = session_service
        self.session_cache = TTLCache(maxsize=cache_maxsize, ttl=cache_ttl)
        self._cache_ttl = cache_ttl
        self._redis = get_shared_redis_client()

    async def _redis_get(self, context_id: str) -> Optional[str]:
        """Check Redis L2 for context_id → session_id mapping."""
        if self._redis is None:
            return None
        try:
            value = await self._redis.get(f"{_REDIS_KEY_PREFIX}{context_id}")
            if value is not None:
                return value.decode() if isinstance(value, bytes) else value
        except Exception:
            logger.warning("Redis L2 GET failed for %s", context_id, exc_info=True)
        return None

    async def _redis_set(self, context_id: str, session_id: str) -> None:
        """Store context_id → session_id mapping in Redis L2."""
        if self._redis is None:
            return
        try:
            await self._redis.setex(
                f"{_REDIS_KEY_PREFIX}{context_id}",
                self._cache_ttl,
                session_id,
            )
        except Exception:
            logger.warning("Redis L2 SETEX failed for %s", context_id, exc_info=True)

    async def get_or_create_session(
        self,
        context_id: str,
        app_name: str,
        user_id: str,
    ) -> str:
        """Get existing session for context_id or create a new one.

        Lookup order: L1 (TTLCache) → L2 (Redis) → create new session.
        Returns the Vertex AI session_id (not the A2A context_id).
        """
        # L1: per-process cache
        cached_session_id = self.session_cache.get(context_id)
        if cached_session_id:
            logger.debug("Session L1 hit: %s → %s", context_id, cached_session_id)
            return cached_session_id

        # L2: shared Redis cache
        redis_session_id = await self._redis_get(context_id)
        if redis_session_id:
            logger.info("Session L2 hit: %s → %s", context_id, redis_session_id)
            self.session_cache.set(context_id, redis_session_id)
            return redis_session_id

        # Miss: create session WITHOUT session_id — Vertex generates one
        session = await self.session_service.create_session(
            app_name=app_name,
            user_id=user_id,
        )

        logger.info(
            "Created new session: context=%s → session=%s",
            context_id,
            session.id,
        )
        self.session_cache.set(context_id, session.id)
        await self._redis_set(context_id, session.id)
        return session.id

    def get_session_id(self, context_id: str) -> Optional[str]:
        """Look up cached session_id for a context_id."""
        return self.session_cache.get(context_id)

    def cache_session(self, context_id: str, session_id: str) -> None:
        """Manually cache a context_id → session_id mapping."""
        self.session_cache.set(context_id, session_id)
