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

"""Concurrency benchmark — measures per-instance session capacity.

Ramps concurrent run_async() calls through configurable levels to find the
latency knee, determining realistic Cloud Run --concurrency and --min-instances.

Usage:
    # Start PostgreSQL:
    docker compose -f docker-compose.test.yml up -d postgres-test

    # Run benchmark:
    uv run python scripts/bench/bench_concurrency.py \\
        --agent agents.runner_autopilot.agent \\
        --levels 10,50,100,250,500,1000 \\
        --pool-size 20 --max-overflow 20 \\
        --output results/bench_runner.json

    # Cleanup:
    docker compose -f docker-compose.test.yml down
"""

import argparse
import asyncio
import importlib
import json
import time
import tracemalloc
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google.genai import types  # noqa: E402

DB_URL = "postgresql+asyncpg://testuser:testpass@127.0.0.1:8104/testdb"

DEFAULT_LEVELS = [10, 50, 100, 250, 500, 1000, 2000, 5000]


@dataclass
class LevelResult:
    """Results from one concurrency level."""

    n: int
    throughput: float  # sessions/sec
    p50: float
    p95: float
    p99: float
    wall_time: float
    memory_bytes: int
    errors: int
    pool_status: str = ""
    latencies: list[float] = field(default_factory=list)


def load_agent(module_path: str):
    """Import agent module and return root_agent."""
    mod = importlib.import_module(module_path)
    if not hasattr(mod, "root_agent"):
        raise AttributeError(f"{module_path} has no 'root_agent'")
    return mod.root_agent


async def run_level(
    runner,
    app_name: str,
    session_ids: list[str],
    prompt: str,
) -> LevelResult:
    """Run concurrent sessions and measure latency.

    Fires N concurrent run_async() calls via asyncio.gather and collects
    per-session latency, throughput, memory, and error count.
    """
    from scripts.bench.bench_helpers import compute_percentiles

    n = len(session_ids)
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)],
    )

    tracemalloc.start()
    mem_before = tracemalloc.get_traced_memory()[1]

    error_count = 0

    async def run_one(sid: str) -> float:
        nonlocal error_count
        t0 = time.perf_counter()
        try:
            async for _event in runner.run_async(
                user_id="bench",
                session_id=sid,
                new_message=content,
            ):
                pass
        except Exception:
            error_count += 1
        return time.perf_counter() - t0

    wall_start = time.perf_counter()
    raw_latencies = await asyncio.gather(*[run_one(sid) for sid in session_ids])
    wall_time = time.perf_counter() - wall_start

    mem_after = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    latencies = list(raw_latencies)
    pcts = compute_percentiles(latencies)
    throughput = n / wall_time if wall_time > 0 else 0

    # Try to get pool status if the session service exposes it
    pool_status = ""
    svc = getattr(runner, "session_service", None)
    engine = getattr(svc, "db_engine", None)
    if engine is not None:
        pool = engine.pool
        checked_out = pool.checkedout()
        total = pool.size() + pool.overflow()
        pool_status = f"{checked_out}/{total}"

    return LevelResult(
        n=n,
        throughput=round(throughput, 1),
        p50=pcts["p50"],
        p95=pcts["p95"],
        p99=pcts["p99"],
        wall_time=wall_time,
        memory_bytes=max(0, mem_after - mem_before),
        errors=error_count,
        pool_status=pool_status,
        latencies=latencies,
    )


def print_results(
    results: list[LevelResult],
    agent_name: str,
    pool_desc: str,
    p95_threshold: float = 0.5,
) -> None:
    """Print formatted results table and recommendation."""
    from scripts.bench.bench_helpers import format_bytes, format_duration

    print(f"\nConcurrency Benchmark: {agent_name} (DatabaseSessionService)")
    print(f"Pool: {pool_desc}\n")

    header = (
        f"{'N':>6} | {'Throughput':>10} | {'P50':>8} | "
        f"{'P95':>8} | {'P99':>8} | {'Memory':>8} | "
        f"{'Errors':>6} | {'Pool':>10}"
    )
    print(header)
    print("-" * len(header))

    for r in results:
        print(
            f"{r.n:>6} | {r.throughput:>8.1f}/s | "
            f"{format_duration(r.p50):>8} | "
            f"{format_duration(r.p95):>8} | "
            f"{format_duration(r.p99):>8} | "
            f"{format_bytes(r.memory_bytes):>8} | "
            f"{r.errors:>6} | "
            f"{r.pool_status:>10}"
        )

    # Find the first level where P95 exceeds threshold
    threshold_str = format_duration(p95_threshold)
    for idx, r in enumerate(results):
        if r.p95 > p95_threshold:
            prev = results[idx - 1] if idx > 0 else r
            rec_concurrency = prev.n
            rec_10k = max(1, 10_000 // rec_concurrency)
            rec_40k = max(1, 40_000 // rec_concurrency)
            print(f"\n--- Recommendation (P95 < {threshold_str}) ---")
            print(f"  Recommended --concurrency:  {rec_concurrency}")
            print(f"  min_instances for 10k:      {rec_10k}")
            print(f"  min_instances for 40k:      {rec_40k}")
            print("  Note: Local DB is ~3-10x faster than Cloud SQL.")
            print("        Apply correction factor for production sizing.")
            return

    # All levels passed
    last = results[-1]
    print(f"\n--- All levels passed P95 < {threshold_str} ---")
    print(f"  Recommended --concurrency:  {last.n}")
    print(f"  min_instances for 10k:      {max(1, 10_000 // last.n)}")
    print(f"  min_instances for 40k:      {max(1, 40_000 // last.n)}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Concurrency benchmark for ADK agents with DatabaseSessionService",
    )
    parser.add_argument(
        "--agent",
        required=True,
        help="Dotted module path (e.g. agents.runner_autopilot.agent)",
    )
    parser.add_argument(
        "--prompt",
        default='{"event":"start_gun"}',
        help="JSON message to send to each session (default: start_gun)",
    )
    parser.add_argument(
        "--levels",
        default=",".join(str(level) for level in DEFAULT_LEVELS),
        help=f"Comma-separated concurrency levels (default: {DEFAULT_LEVELS})",
    )
    parser.add_argument("--pool-size", type=int, default=20)
    parser.add_argument("--max-overflow", type=int, default=20)
    parser.add_argument("--db-url", default=DB_URL, help="PostgreSQL URL")
    parser.add_argument("--output", help="JSON output file path")
    parser.add_argument(
        "--p95-threshold",
        type=float,
        default=0.5,
        help="P95 latency threshold in seconds for recommendations (default: 0.5)",
    )
    args = parser.parse_args()

    levels = [int(x) for x in args.levels.split(",")]
    pool_desc = (
        f"pool_size={args.pool_size}, max_overflow={args.max_overflow} (max={args.pool_size + args.max_overflow})"
    )

    print(f"Loading agent: {args.agent}")
    agent = load_agent(args.agent)
    print(f"Agent '{agent.name}' loaded")

    from google.adk.runners import Runner
    from google.adk.sessions.database_session_service import DatabaseSessionService

    svc = DatabaseSessionService(
        db_url=args.db_url,
        pool_size=args.pool_size,
        max_overflow=args.max_overflow,
    )

    runner = Runner(
        app_name="bench_concurrency",
        agent=agent,
        session_service=svc,
    )

    # Seed app_states to avoid ADK INSERT race on first concurrent batch
    print("Seeding app_states...")
    await svc.create_session(app_name="bench_concurrency", user_id="bench")

    results: list[LevelResult] = []

    for level in levels:
        print(f"\n--- Level: {level} concurrent sessions ---")

        # Create sessions for this level
        session_ids = []
        batch_id = uuid.uuid4().hex[:8]
        for i in range(level):
            sid = f"bench_{batch_id}_{i}"
            await svc.create_session(
                app_name="bench_concurrency",
                user_id="bench",
                session_id=sid,
            )
            session_ids.append(sid)
        print(f"  Created {level} sessions")

        result = await run_level(
            runner=runner,
            app_name="bench_concurrency",
            session_ids=session_ids,
            prompt=args.prompt,
        )
        results.append(result)

        from scripts.bench.bench_helpers import format_duration

        print(
            f"  {level} sessions: {result.throughput}/s, "
            f"P50={format_duration(result.p50)}, "
            f"P95={format_duration(result.p95)}, "
            f"P99={format_duration(result.p99)}, "
            f"errors={result.errors}"
        )

    print_results(results, agent.name, pool_desc, args.p95_threshold)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_data = {
            "agent": args.agent,
            "pool_size": args.pool_size,
            "max_overflow": args.max_overflow,
            "p95_threshold_s": args.p95_threshold,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "levels": [{k: v for k, v in asdict(r).items() if k != "latencies"} for r in results],
        }
        output_path.write_text(json.dumps(output_data, indent=2))
        print(f"\nResults saved to {args.output}")

    await svc.db_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
