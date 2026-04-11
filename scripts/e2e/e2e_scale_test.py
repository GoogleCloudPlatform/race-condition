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

"""E2E Scale Test — validates 10k concurrent runner_autopilot sessions on GCP.

Adapted from e2e_fanout_test.py for high-concurrency validation. Key differences:
- Batched spawning (500/batch) to avoid gateway timeouts
- Relaxed fan-out thresholds for 10k+ sessions
- Per-phase timing and progress reporting
- Designed to run against deployed GCP services

Usage:
    # Against local dev:
    uv run python scripts/e2e/e2e_scale_test.py --count 100

    # Against GCP dev (point to Cloud Run gateway):
    GATEWAY_URL=https://gateway-<project-number>.us-central1.run.app \\
    uv run python scripts/e2e/e2e_scale_test.py --count 10000

    # Validate 40k peak (4 simulations):
    uv run python scripts/e2e/e2e_scale_test.py --count 10000 --parallel 4

Prerequisites:
    - Gateway and runner_autopilot must be deployed and healthy.
    - For GCP: terraform applied (AlloyDB max_connections, VPC connector).
    - For GCP: runner_autopilot deployed with right-sized config (min_instances=56).
"""

import argparse
import asyncio
import json
import os
import sys
import time

import aiohttp
import websockets

from gen_proto.gateway import gateway_pb2

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_HTTP_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8101")
GATEWAY_WS_URL = os.getenv(
    "GATEWAY_WS_URL",
    GATEWAY_HTTP_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws",
)

SPAWN_BATCH_SIZE = 500  # Sessions per spawn API call
SPAWN_TIMEOUT = 120  # Seconds per spawn batch
COLLECTION_TIMEOUT = 300  # Seconds to wait for all responses
PROGRESS_INTERVAL = 500  # Report every N sessions


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


async def check_health() -> bool:
    """Verify gateway is reachable."""
    print("--- Preflight health check ---")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{GATEWAY_HTTP_URL}/health",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status < 500:
                    print(f"  [OK] Gateway ({GATEWAY_HTTP_URL}) -> {resp.status}")
                    return True
        except Exception as exc:
            print(f"  [FAIL] Gateway not reachable: {exc}")
    return False


# ---------------------------------------------------------------------------
# Batched spawning
# ---------------------------------------------------------------------------


async def spawn_sessions_batched(total: int) -> list[str]:
    """Spawn sessions in batches to avoid gateway timeouts.

    Returns list of all session IDs.
    """
    print(f"\n--- Spawning {total} sessions (batches of {SPAWN_BATCH_SIZE}) ---")
    all_session_ids: list[str] = []
    remaining = total
    batch_num = 0

    async with aiohttp.ClientSession() as session:
        while remaining > 0:
            batch_size = min(remaining, SPAWN_BATCH_SIZE)
            batch_num += 1
            url = f"{GATEWAY_HTTP_URL}/api/v1/spawn"
            body = {"agents": [{"agentType": "runner_autopilot", "count": batch_size}]}

            t0 = time.monotonic()
            try:
                async with session.post(
                    url,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=SPAWN_TIMEOUT),
                ) as resp:
                    data = await resp.json()
                    if resp.status >= 400:
                        print(f"  [FAIL] Batch {batch_num}: HTTP {resp.status}: {data}")
                        return all_session_ids

                    sessions = data.get("sessions", [])
                    batch_ids = [s["sessionId"] for s in sessions]
                    all_session_ids.extend(batch_ids)
                    elapsed = time.monotonic() - t0
                    print(
                        f"  [OK] Batch {batch_num}: {len(batch_ids)} spawned "
                        f"({len(all_session_ids)}/{total} total, {elapsed:.1f}s)"
                    )
            except Exception as exc:
                print(f"  [FAIL] Batch {batch_num}: {exc}")
                return all_session_ids

            remaining -= batch_size

    print(f"  Total spawned: {len(all_session_ids)}")
    return all_session_ids


# ---------------------------------------------------------------------------
# Broadcast
# ---------------------------------------------------------------------------


async def send_broadcast(session_ids: list[str]) -> bool:
    """Send a start_gun broadcast to all sessions."""
    print(f"\n--- Sending start_gun broadcast to {len(session_ids)} sessions ---")

    runner_event = json.dumps({"event": "start_gun"}).encode()
    broadcast_req = gateway_pb2.BroadcastRequest(
        payload=runner_event,
        target_session_ids=session_ids,
    )
    wrapper = gateway_pb2.Wrapper(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        type="broadcast",
        event="start_gun",
        payload=broadcast_req.SerializeToString(),
        origin=gateway_pb2.Origin(type="client", id="scale-test"),
    )
    data = wrapper.SerializeToString()

    try:
        ws_url = f"{GATEWAY_WS_URL}?sessionId=scale-test-sender"
        async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
            await ws.send(data)
            print(f"  [OK] Broadcast sent ({len(data):,} bytes)")
            await asyncio.sleep(0.5)
        return True
    except Exception as exc:
        print(f"  [FAIL] Broadcast error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Observer
# ---------------------------------------------------------------------------


async def collect_responses(
    expected_count: int,
    session_ids: set[str],
    timeout: int,
) -> dict:
    """Collect responses as a global WebSocket observer."""
    responded: set[str] = set()
    total_events = 0
    first_time: float | None = None
    last_time: float | None = None

    ws_url = GATEWAY_WS_URL

    try:
        async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
            print(f"  [WS] Observer connected to {ws_url}")
            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break

                try:
                    data = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 5.0))
                except asyncio.TimeoutError:
                    if responded:
                        # Print progress on timeout tick
                        pct = len(responded) / expected_count * 100
                        print(f"  [WS] Waiting... {len(responded)}/{expected_count} ({pct:.1f}%)")
                    if len(responded) >= expected_count:
                        break
                    continue
                except websockets.exceptions.ConnectionClosed:
                    print("  [WS] Connection closed by server")
                    break

                if not isinstance(data, bytes):
                    continue

                try:
                    wrapper = gateway_pb2.Wrapper()
                    wrapper.ParseFromString(data)
                except Exception:
                    continue

                sid = wrapper.session_id or (wrapper.origin.session_id if wrapper.origin else "")
                if sid in session_ids:
                    now = time.monotonic()
                    if first_time is None:
                        first_time = now
                    last_time = now
                    responded.add(sid)
                    total_events += 1

                    if len(responded) % PROGRESS_INTERVAL == 0 or len(responded) == expected_count:
                        elapsed = now - first_time
                        rate = len(responded) / elapsed if elapsed > 0 else 0
                        print(f"  [WS] {len(responded):,}/{expected_count:,} ({elapsed:.1f}s, {rate:.0f}/s)")

                    if len(responded) >= expected_count:
                        await asyncio.sleep(2.0)
                        break

    except Exception as exc:
        print(f"  [WS] Observer error: {exc}")

    elapsed = 0.0
    if first_time and last_time:
        elapsed = last_time - first_time

    return {
        "responded_sessions": responded,
        "total_events": total_events,
        "elapsed": elapsed,
    }


# ---------------------------------------------------------------------------
# Single simulation run
# ---------------------------------------------------------------------------


async def run_simulation(sim_id: int, count: int) -> dict:
    """Run one simulation: spawn, broadcast, collect."""
    prefix = f"[Sim {sim_id}]"
    print(f"\n{'=' * 60}")
    print(f"{prefix} Starting simulation with {count:,} sessions")
    print(f"{'=' * 60}")

    # Spawn
    t_spawn_start = time.monotonic()
    session_ids = await spawn_sessions_batched(count)
    t_spawn = time.monotonic() - t_spawn_start

    if len(session_ids) != count:
        print(f"{prefix} [FAIL] Only spawned {len(session_ids)}/{count}")
        return {"sim_id": sim_id, "success": False, "spawned": len(session_ids)}

    session_set = set(session_ids)

    # Observer + broadcast
    print(f"\n{prefix} Collecting responses (up to {COLLECTION_TIMEOUT}s) ---")

    async def delayed_broadcast():
        await asyncio.sleep(3.0)
        return await send_broadcast(session_ids)

    observer_task = asyncio.create_task(collect_responses(count, session_set, COLLECTION_TIMEOUT))
    broadcast_ok = await delayed_broadcast()

    if not broadcast_ok:
        observer_task.cancel()
        return {"sim_id": sim_id, "success": False, "spawned": count}

    results = await observer_task

    responded = results["responded_sessions"]
    elapsed = results["elapsed"]
    missing = session_set - responded

    return {
        "sim_id": sim_id,
        "success": len(responded) == count,
        "spawned": count,
        "responded": len(responded),
        "missing": len(missing),
        "spawn_time": t_spawn,
        "fanout_time": elapsed,
        "throughput": len(responded) / elapsed if elapsed > 0 else 0,
        "total_events": results["total_events"],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_test(count: int, parallel: int) -> bool:
    """Run the full scale test."""
    if not await check_health():
        return False

    all_results = []

    if parallel <= 1:
        result = await run_simulation(1, count)
        all_results.append(result)
    else:
        # Run simulations sequentially (each is already async internally).
        # True parallel would need separate gateway connections.
        for i in range(1, parallel + 1):
            result = await run_simulation(i, count)
            all_results.append(result)

    # Report
    print("\n" + "=" * 60)
    print("SCALE TEST REPORT")
    print("=" * 60)

    all_passed = True
    for r in all_results:
        sim = r["sim_id"]
        if not r["success"]:
            all_passed = False
            print(f"\n  Simulation {sim}: FAIL")
            print(f"    Spawned:   {r['spawned']:,}")
            print(f"    Responded: {r.get('responded', 0):,}")
            print(f"    Missing:   {r.get('missing', '?')}")
            continue

        print(f"\n  Simulation {sim}: PASS")
        print(f"    Sessions:   {r['spawned']:,}")
        print(f"    Responded:  {r['responded']:,}")
        print(f"    Spawn time: {r['spawn_time']:.1f}s")
        print(f"    Fan-out:    {r['fanout_time']:.1f}s")
        print(f"    Throughput: {r['throughput']:.0f} responses/sec")

    total_sessions = sum(r["spawned"] for r in all_results)
    total_responded = sum(r.get("responded", 0) for r in all_results)
    print(f"\n  Total sessions:  {total_sessions:,}")
    print(f"  Total responded: {total_responded:,}")
    print(f"\n  RESULT: {'PASS' if all_passed else 'FAIL'}")
    print("=" * 60)

    return all_passed


def main():
    global COLLECTION_TIMEOUT, SPAWN_BATCH_SIZE

    parser = argparse.ArgumentParser(
        description="E2E scale test for runner_autopilot on GCP",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10000,
        help="Sessions per simulation (default: 10000)",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Number of sequential simulations to run (default: 1)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=COLLECTION_TIMEOUT,
        help=f"Collection timeout in seconds (default: {COLLECTION_TIMEOUT})",
    )
    parser.add_argument(
        "--spawn-batch",
        type=int,
        default=SPAWN_BATCH_SIZE,
        help=f"Sessions per spawn batch (default: {SPAWN_BATCH_SIZE})",
    )
    args = parser.parse_args()

    COLLECTION_TIMEOUT = args.timeout
    SPAWN_BATCH_SIZE = args.spawn_batch

    print("E2E Scale Test")
    print(f"  Gateway HTTP     : {GATEWAY_HTTP_URL}")
    print(f"  Gateway WS       : {GATEWAY_WS_URL}")
    print(f"  Sessions/sim     : {args.count:,}")
    print(f"  Simulations      : {args.parallel}")
    print(f"  Spawn batch size : {SPAWN_BATCH_SIZE}")
    print(f"  Timeout          : {COLLECTION_TIMEOUT}s\n")

    success = asyncio.run(run_test(args.count, args.parallel))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
