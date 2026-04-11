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

"""Emergency flush: clear all simulation state (Redis + AlloyDB + PubSub).

Usage:
    # Flush everything (Redis queues + AlloyDB sessions + PubSub subscriptions):
    uv run python scripts/ops/emergency_flush.py --all

    # Flush Redis only (pub/sub channels, spawn queues, session registry):
    uv run python scripts/ops/emergency_flush.py --redis

    # Flush AlloyDB only (sessions, events, app/user states):
    uv run python scripts/ops/emergency_flush.py --db

    # Drain PubSub subscriptions only (seek to now):
    uv run python scripts/ops/emergency_flush.py --pubsub

    # Scale runner_autopilot to 0 instances AND flush:
    uv run python scripts/ops/emergency_flush.py --all --kill

    # Bring runner_autopilot back after flush:
    uv run python scripts/ops/emergency_flush.py --revive

Requires REDIS_ADDR and/or DATABASE_URL environment variables.
Reads from .env.dev if present.
"""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env loading
# ---------------------------------------------------------------------------


def _load_env():
    """Load .env.dev if it exists."""
    for name in [".env.dev", ".env"]:
        env_file = Path(__file__).resolve().parent.parent.parent / name
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())
            logger.info(f"Loaded environment from {env_file}")
            return
    logger.warning("No .env.dev or .env found, using system environment")


# ---------------------------------------------------------------------------
# Redis flush
# ---------------------------------------------------------------------------


async def flush_redis():
    """Flush all Redis keys (queues, pub/sub state, session registry)."""
    import redis.asyncio as redis

    addr = os.environ.get("REDIS_ADDR", "")
    if not addr:
        logger.error("REDIS_ADDR not set, skipping Redis flush")
        return False

    url = addr if addr.startswith("redis://") else f"redis://{addr}"
    logger.info(f"Connecting to Redis at {addr}...")

    r = redis.from_url(url)
    try:
        # Show what we're about to flush
        info = await r.info("keyspace")
        logger.info(f"Redis keyspace before flush: {info}")

        # List simulation-related keys
        keys = []
        async for key in r.scan_iter("simulation:*"):
            keys.append(key)
        async for key in r.scan_iter("gateway:*"):
            keys.append(key)
        async for key in r.scan_iter("*:active-agents"):
            keys.append(key)
        logger.info(f"Simulation keys found: {len(keys)}")
        for k in keys[:20]:
            logger.info(f"  {k}")

        # FLUSHALL — nuclear option but safe for dev
        await r.flushall()
        logger.info("Redis FLUSHALL complete")
        return True
    finally:
        await r.aclose()


# ---------------------------------------------------------------------------
# AlloyDB flush
# ---------------------------------------------------------------------------


async def flush_db():
    """Truncate all ADK session tables in AlloyDB."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.error("DATABASE_URL not set, skipping DB flush")
        return False

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    logger.info("Connecting to AlloyDB...")
    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as conn:
            # Show current state
            for table in ["sessions", "events", "app_states", "user_states"]:
                try:
                    r = await conn.execute(text(f"SELECT count(*) FROM {table}"))
                    logger.info(f"  {table}: {r.scalar()} rows")
                except Exception:
                    logger.info(f"  {table}: does not exist")

            # Truncate in dependency order
            logger.info("Truncating all ADK tables...")
            await conn.execute(text("TRUNCATE TABLE events, sessions, app_states, user_states CASCADE"))
            logger.info("AlloyDB tables truncated")
        return True
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Constants (used by flush_pubsub, kill_instances, revive_instances)
# ---------------------------------------------------------------------------

SERVICES = ["runner-autopilot"]
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID") or "your-gcp-project-id"
REGION = "us-central1"


# ---------------------------------------------------------------------------
# PubSub flush
# ---------------------------------------------------------------------------


def flush_pubsub():
    """Seek all PubSub subscriptions to 'now' to discard backlogged messages."""
    project = os.environ.get("PUBSUB_PROJECT_ID", PROJECT)
    subs_raw = os.environ.get("PUBSUB_RESET_SUBS", "router-sub,gateway-push-orchestration")
    subs = [s.strip() for s in subs_raw.split(",") if s.strip()]

    if not subs:
        logger.warning("No PUBSUB_RESET_SUBS configured, skipping PubSub flush")
        return False

    now = subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()

    success = True
    for sub in subs:
        logger.info(f"Seeking subscription {sub} to {now}...")
        try:
            subprocess.run(
                [
                    "gcloud",
                    "pubsub",
                    "subscriptions",
                    "seek",
                    sub,
                    f"--time={now}",
                    f"--project={project}",
                    "--quiet",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"  {sub} drained")
        except subprocess.CalledProcessError as e:
            logger.error(f"  {sub} seek failed: {e.stderr}")
            success = False

    return success


# ---------------------------------------------------------------------------
# Cloud Run instance management
# ---------------------------------------------------------------------------


def kill_instances():
    """Scale Cloud Run subscriber services to 0."""
    for svc in SERVICES:
        logger.info(f"Scaling {svc} to min-instances=0...")
        subprocess.run(
            [
                "gcloud",
                "run",
                "services",
                "update",
                svc,
                "--region",
                REGION,
                "--project",
                PROJECT,
                "--min-instances=0",
                "--quiet",
            ],
            check=True,
            capture_output=True,
        )
        logger.info(f"  {svc} scaled to 0")


def revive_instances(min_instances=5):
    """Restore Cloud Run subscriber services to normal."""
    for svc in SERVICES:
        logger.info(f"Scaling {svc} to min-instances={min_instances}...")
        subprocess.run(
            [
                "gcloud",
                "run",
                "services",
                "update",
                svc,
                "--region",
                REGION,
                "--project",
                PROJECT,
                f"--min-instances={min_instances}",
                "--no-cpu-throttling",
                "--quiet",
            ],
            check=True,
            capture_output=True,
        )
        logger.info(f"  {svc} restored to min-instances={min_instances}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def async_main(args):
    results = []

    if args.redis or args.all:
        ok = await flush_redis()
        results.append(("Redis", ok))

    if args.db or args.all:
        ok = await flush_db()
        results.append(("AlloyDB", ok))

    if args.pubsub or args.all:
        ok = flush_pubsub()
        results.append(("PubSub", ok))

    print("\n=== Flush Results ===")
    for name, ok in results:
        status = "FLUSHED" if ok else "SKIPPED"
        print(f"  {name}: {status}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Emergency flush: clear all simulation state")
    parser.add_argument("--redis", action="store_true", help="Flush Redis only")
    parser.add_argument("--db", action="store_true", help="Flush AlloyDB only")
    parser.add_argument("--pubsub", action="store_true", help="Seek PubSub subscriptions to now")
    parser.add_argument("--all", action="store_true", help="Flush Redis + AlloyDB + PubSub")
    parser.add_argument("--kill", action="store_true", help="Scale subscriber services to 0 before flush")
    parser.add_argument("--revive", action="store_true", help="Restore subscriber services to min-instances=5")
    parser.add_argument("--min-instances", type=int, default=5, help="Min instances for --revive (default: 5)")
    args = parser.parse_args()

    if not any([args.redis, args.db, args.pubsub, args.all, args.kill, args.revive]):
        parser.print_help()
        sys.exit(1)

    _load_env()

    if args.kill:
        kill_instances()

    if args.redis or args.db or args.pubsub or args.all:
        asyncio.run(async_main(args))

    if args.revive:
        revive_instances(args.min_instances)


if __name__ == "__main__":
    main()
