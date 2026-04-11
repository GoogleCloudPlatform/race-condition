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

"""RaceCollector — Redis-backed telemetry collector for multi-instance AE.

Subscribes to ``gateway:broadcast`` (protobuf-encoded ``gateway.Wrapper``
messages) and filters for messages originating from specific runner session IDs.
Matching messages are buffered in a **Redis list** so that ``drain()`` works
from any Agent Engine instance, not just the one that started the collector.

The ``drain()`` method atomically reads and clears the Redis buffer, returning
whatever arrived since the last drain (approximate sampling).
"""

import asyncio
import json
import logging
from typing import Optional

from redis.asyncio.client import PubSub, Redis

from gen_proto.gateway import gateway_pb2

from agents.utils.redis_pool import get_shared_redis_client

logger = logging.getLogger(__name__)

# Module-level registry of locally-owned collectors (PubSub subscriptions).
# Only the instance that called start() has an entry here.
_instances: dict[str, "RaceCollector"] = {}

_BUFFER_PREFIX = "collector:buffer:"
_ACTIVE_PREFIX = "collector:active:"


class _DrainProxy:
    """Lightweight proxy for draining the collector from a non-owning instance.

    When ``advance_tick`` runs on a different AE instance than the one
    that started the collector, ``RaceCollector.get()`` returns this proxy.
    It can ``drain()`` the shared Redis buffer but does not own the PubSub
    subscription.
    """

    def __init__(self, session_id: str, redis_client: Redis) -> None:
        self.session_id = session_id
        self._redis = redis_client
        self._buffer_key = _BUFFER_PREFIX + session_id

    async def drain(self) -> list[dict]:
        """Atomically read and clear the Redis buffer."""
        pipe = self._redis.pipeline()
        pipe.lrange(self._buffer_key, 0, -1)
        pipe.delete(self._buffer_key)
        results = await pipe.execute()
        raw_items = results[0]  # list[bytes]
        return [json.loads(item) for item in raw_items]

    async def stop(self) -> None:
        """Clean up Redis keys (remote stop — no PubSub to cancel)."""
        try:
            await self._redis.delete(self._buffer_key)
            await self._redis.delete(_ACTIVE_PREFIX + self.session_id)
        except Exception:
            logger.warning("RaceCollector (proxy): Redis cleanup failed for %s", self.session_id, exc_info=True)
        logger.info("RaceCollector (proxy) stopped for session %s", self.session_id)


class RaceCollector:
    """Collects gateway broadcast messages for a set of runner sessions.

    The PubSub subscription runs on the instance that called ``start()``.
    Matching messages are pushed to a **Redis list** so that any instance
    can ``drain()`` them.
    """

    def __init__(self, session_id: str, runner_session_ids: set[str], *, skip_pubsub: bool = False) -> None:
        self.session_id = session_id
        self.runner_session_ids = runner_session_ids
        self.skip_pubsub = skip_pubsub
        self._pubsub: Optional[PubSub] = None
        self._redis: Optional[Redis] = None
        self._task: Optional[asyncio.Task] = None
        self._buffer_key = _BUFFER_PREFIX + session_id

    # ------------------------------------------------------------------
    # Factory / registry
    # ------------------------------------------------------------------

    @classmethod
    async def start(
        cls,
        session_id: str,
        runner_session_ids: set[str],
        *,
        skip_pubsub: bool = False,
    ) -> "RaceCollector":
        """Create a collector, connect to Redis, subscribe, and start background task.

        Args:
            session_id: The simulation session ID.
            runner_session_ids: Set of runner session IDs to track.
            skip_pubsub: When True, skip the PubSub subscription and background
                collect loop.  Runners write directly via RPUSH so the PubSub
                path is redundant for autopilot simulations and adds Redis
                contention at scale.
        """
        instance = cls(session_id, runner_session_ids, skip_pubsub=skip_pubsub)
        r = get_shared_redis_client()
        if r is None:
            raise RuntimeError("Cannot start RaceCollector: REDIS_ADDR not configured")
        instance._redis = r

        if not skip_pubsub:
            instance._pubsub = r.pubsub()
            assert instance._pubsub is not None
            await instance._pubsub.subscribe("gateway:broadcast")
            instance._task = asyncio.create_task(instance._collect_loop())

        # Mark as active in Redis so other instances know a collector exists.
        await r.set(_ACTIVE_PREFIX + session_id, "1", ex=7200)

        _instances[session_id] = instance
        logger.info(
            "RaceCollector started for session %s (tracking %d runners, skip_pubsub=%s)",
            session_id,
            len(runner_session_ids),
            skip_pubsub,
        )
        return instance

    @classmethod
    def is_running(cls, session_id: str) -> bool:
        """Return True if a local RaceCollector is active for *session_id*."""
        return session_id in _instances

    @classmethod
    def get(cls, session_id: str) -> Optional["RaceCollector | _DrainProxy"]:
        """Look up a collector by session_id.

        Returns the local collector if this instance owns it, otherwise a
        ``_DrainProxy`` that can drain the shared Redis buffer from any
        AE instance.
        """
        local = _instances.get(session_id)
        if local is not None:
            return local

        # Cross-instance: return a drain proxy if Redis is available.
        r = get_shared_redis_client()
        if r is None:
            return None
        return _DrainProxy(session_id, r)

    # ------------------------------------------------------------------
    # Background collection
    # ------------------------------------------------------------------

    async def _collect_loop(self) -> None:
        """Background task: read from pubsub, deserialize, filter, push to Redis."""
        try:
            assert self._pubsub is not None
            assert self._redis is not None
            while True:
                msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is not None and msg.get("type") == "message":
                    try:
                        wrapper = gateway_pb2.Wrapper()
                        wrapper.ParseFromString(msg["data"])
                        parsed = self._parse_wrapper(wrapper)
                        if parsed is not None:
                            await self._redis.rpush(  # type: ignore[misc]
                                self._buffer_key,
                                json.dumps(parsed, default=str),
                            )
                            await self._redis.expire(self._buffer_key, 7200)
                    except Exception:
                        logger.warning("RaceCollector: failed to parse broadcast message", exc_info=True)
        except asyncio.CancelledError:
            logger.debug("RaceCollector collect loop cancelled for session %s", self.session_id)

    # ------------------------------------------------------------------
    # Parsing / filtering
    # ------------------------------------------------------------------

    def _parse_wrapper(self, wrapper: gateway_pb2.Wrapper) -> Optional[dict]:
        """Filter wrapper by runner session IDs and return structured dict or None."""
        origin_session_id = wrapper.origin.session_id
        if origin_session_id not in self.runner_session_ids:
            return None

        # Decode payload as JSON
        try:
            payload = json.loads(wrapper.payload) if wrapper.payload else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}

        return {
            "session_id": origin_session_id,
            "agent_id": wrapper.origin.id,
            "event": wrapper.event,
            "msg_type": wrapper.type,
            "timestamp": wrapper.timestamp,
            "payload": payload,
        }

    # ------------------------------------------------------------------
    # Drain
    # ------------------------------------------------------------------

    async def drain(self) -> list[dict]:
        """Atomically read and clear the Redis buffer."""
        r = self._redis or get_shared_redis_client()
        if r is None:
            return []
        pipe = r.pipeline()
        pipe.lrange(self._buffer_key, 0, -1)
        pipe.delete(self._buffer_key)
        results = await pipe.execute()
        raw_items = results[0]  # list[bytes]
        return [json.loads(item) for item in raw_items]

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def stop(self) -> None:
        """Cancel background task, close PubSub, clean up Redis keys."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._pubsub is not None:
            # Skip unsubscribe() — the server automatically cleans up
            # subscriptions when the connection closes.  After task.cancel()
            # the PubSub connection may be in a corrupted state (partial
            # read in flight), so any write/read on it can raise
            # ConnectionError.  Just close the connection.
            try:
                await self._pubsub.close()
            except Exception:
                logger.debug("RaceCollector: PubSub close failed for %s (expected after cancel)", self.session_id)
            self._pubsub = None

        # Clean up Redis buffer and active marker
        r = self._redis or get_shared_redis_client()
        if r is not None:
            try:
                await r.delete(self._buffer_key)
                await r.delete(_ACTIVE_PREFIX + self.session_id)
            except Exception:
                logger.warning("RaceCollector: Redis cleanup failed for %s", self.session_id, exc_info=True)

        # Do NOT close self._redis — it is the shared pool client.
        self._redis = None

        _instances.pop(self.session_id, None)
        logger.info("RaceCollector stopped for session %s", self.session_id)
