#!/usr/bin/env python3
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
"""Stress test: measure DatabaseSessionService pool contention locally.

Simulates a broadcast fan-out to N concurrent sessions, measuring how
pool_size affects throughput.  Requires a local PostgreSQL:

    docker compose -f docker-compose.test.yml up -d
    uv run python scripts/bench/stress_test_db.py --sessions 100
    docker compose -f docker-compose.test.yml down

Compares "old defaults" (pool_size=5, max_overflow=10) vs "new defaults"
(pool_size=20, max_overflow=20) to demonstrate the improvement.
"""

import argparse
import asyncio
import time


DB_URL = "postgresql+asyncpg://testuser:testpass@127.0.0.1:8104/testdb"


async def run_scenario(
    label: str,
    num_sessions: int,
    pool_size: int,
    max_overflow: int,
) -> float:
    """Simulate a broadcast fan-out: create sessions then trigger concurrent
    get_session calls for all of them."""
    from google.adk.sessions.database_session_service import DatabaseSessionService

    svc = DatabaseSessionService(
        db_url=DB_URL,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )

    # Seed the app_states row — the ADK's create_session races on
    # INSERT INTO app_states when multiple concurrent calls share the
    # same app_name and no row exists yet.
    app_name = f"stress_{label}"
    await svc.create_session(app_name=app_name, user_id="stress_user")

    # Phase 1: Create sessions (simulates spawn)
    remaining = num_sessions - 1  # one already created above
    print(f"  [{label}] Creating {remaining} more sessions (pool={pool_size}+{max_overflow})...")
    t0 = time.monotonic()

    async def create_one(i: int) -> str:
        s = await svc.create_session(
            app_name=app_name,
            user_id="stress_user",
        )
        return s.id

    session_ids = await asyncio.gather(*[create_one(i) for i in range(remaining)])
    t_create = time.monotonic() - t0
    print(f"  [{label}] Created {num_sessions} sessions in {t_create:.2f}s")

    # Phase 2: Simulate broadcast (concurrent get_session for all)
    print(f"  [{label}] Simulating broadcast (concurrent get_session)...")
    t1 = time.monotonic()

    async def simulate_broadcast(sid: str) -> bool:
        session = await svc.get_session(
            app_name=f"stress_{label}",
            user_id="stress_user",
            session_id=sid,
        )
        return session is not None

    results = await asyncio.gather(*[simulate_broadcast(sid) for sid in session_ids])
    t_broadcast = time.monotonic() - t1
    assert all(results), "Some sessions were not found"
    print(f"  [{label}] Broadcast complete in {t_broadcast:.2f}s")

    total = t_create + t_broadcast
    print(f"  [{label}] Total: {total:.2f}s")

    await svc.db_engine.dispose()
    return total


async def main() -> None:
    parser = argparse.ArgumentParser(description="DB pool contention stress test")
    parser.add_argument("--sessions", type=int, default=100, help="Number of concurrent sessions")
    args = parser.parse_args()

    n = args.sessions
    print(f"\n{'=' * 60}")
    print(f"  DB Pool Contention Stress Test — {n} sessions")
    print(f"{'=' * 60}\n")

    # Old defaults (SQLAlchemy out-of-box)
    t_old = await run_scenario("OLD defaults", n, pool_size=5, max_overflow=10)
    print()

    # New defaults (our tuned config)
    t_new = await run_scenario("NEW defaults", n, pool_size=20, max_overflow=20)

    print(f"\n{'=' * 60}")
    print(f"  Results: {n} sessions")
    print(f"  OLD (pool=5+10=15):   {t_old:.2f}s")
    print(f"  NEW (pool=20+20=40):  {t_new:.2f}s")
    if t_old > 0:
        print(f"  Speedup:              {t_old / t_new:.1f}x")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
