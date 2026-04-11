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

"""Shared Redis connection pool for the entire process.

Every module that needs Redis should call ``get_shared_redis_client()``
instead of creating its own ``redis.from_url()`` client.  This ensures a
single connection pool is shared across pulses, broadcast, dispatcher,
and race collector -- preventing connection exhaustion under load.
"""

import logging
import os

import redis.asyncio as redis

logger = logging.getLogger(__name__)

_shared_client: redis.Redis | None = None


def get_shared_redis_client() -> redis.Redis | None:
    """Return the process-wide Redis client, creating it on first call.

    Uses ``BlockingConnectionPool`` so that callers queue for a connection
    instead of receiving an immediate ``MaxConnectionsError`` when the pool
    is exhausted.  Pool size is configurable via the ``REDIS_MAX_CONNECTIONS``
    environment variable (default 20).  Cloud Run agents override this to 30
    via deploy.py; Agent Engine agents override to 10.

    Returns ``None`` if ``REDIS_ADDR`` is not set in the environment.
    """
    global _shared_client
    if _shared_client is None:
        redis_url = os.environ.get("REDIS_ADDR")
        if not redis_url:
            return None
        if not redis_url.startswith("redis://"):
            redis_url = f"redis://{redis_url}"
        max_conn = int(os.environ.get("REDIS_MAX_CONNECTIONS", "20"))
        pool = redis.BlockingConnectionPool.from_url(
            redis_url,
            decode_responses=False,
            max_connections=max_conn,
            timeout=5,  # max seconds to wait for a connection
        )
        _shared_client = redis.Redis(connection_pool=pool)
    return _shared_client
