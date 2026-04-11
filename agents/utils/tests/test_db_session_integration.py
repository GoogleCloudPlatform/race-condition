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

"""Integration tests for DatabaseSessionService with a real PostgreSQL.

Requires: docker compose -f docker-compose.test.yml up -d
Marked 'integration' so they are skipped by default (run with -m integration).
"""

import asyncio
import socket
import time

import pytest

DB_URL = "postgresql+asyncpg://testuser:testpass@127.0.0.1:8104/testdb"


def _pg_available() -> bool:
    """Check if the test PostgreSQL container is reachable."""
    try:
        s = socket.create_connection(("127.0.0.1", 8104), timeout=1)
        s.close()
        return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _pg_available(), reason="PostgreSQL not running on :8104"),
]


@pytest.mark.asyncio
async def test_database_session_service_with_pool_kwargs():
    """Verify pool_size and max_overflow flow through to the engine."""
    from google.adk.sessions.database_session_service import DatabaseSessionService

    svc = DatabaseSessionService(
        db_url=DB_URL,
        pool_size=10,
        max_overflow=5,
    )
    pool = svc.db_engine.pool
    assert pool.size() == 10  # type: ignore[union-attr]
    # Note: max_overflow has no public accessor in SQLAlchemy's QueuePool.
    # The concurrent_session tests below validate pool behavior functionally.

    await svc.db_engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_session_creation():
    """Create 20 sessions concurrently — verifies pool handles concurrency."""
    from google.adk.sessions.database_session_service import DatabaseSessionService

    svc = DatabaseSessionService(
        db_url=DB_URL,
        pool_size=10,
        max_overflow=10,
    )

    # Seed the app_states row first — the ADK's create_session races on
    # INSERT INTO app_states when multiple concurrent calls share the same
    # app_name and no row exists yet.
    await svc.create_session(app_name="integration_test", user_id="test_user")

    async def create_one(i: int):
        session = await svc.create_session(
            app_name="integration_test",
            user_id="test_user",
        )
        assert session is not None
        assert session.id is not None
        return session.id

    tasks = [create_one(i) for i in range(19)]  # 19 more = 20 total
    session_ids = await asyncio.gather(*tasks)

    assert len(session_ids) == 19
    assert len(set(session_ids)) == 19  # All unique

    await svc.db_engine.dispose()


@pytest.mark.asyncio
async def test_pool_contention_with_small_pool():
    """With pool_size=2 and 20 concurrent creates, all should still succeed."""
    from google.adk.sessions.database_session_service import DatabaseSessionService

    svc = DatabaseSessionService(
        db_url=DB_URL,
        pool_size=2,
        max_overflow=2,
    )

    # Seed the app_states row (see test_concurrent_session_creation).
    await svc.create_session(app_name="contention_test", user_id="test_user")

    start = time.monotonic()

    async def create_one(i: int):
        return await svc.create_session(
            app_name="contention_test",
            user_id="test_user",
        )

    tasks = [create_one(i) for i in range(19)]  # 19 more = 20 total
    sessions = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start

    assert len(sessions) == 19
    print(f"  20 sessions with pool_size=2: {elapsed:.2f}s")

    await svc.db_engine.dispose()
