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

"""E2E Fan-Out Scale Test.

Tests the broadcast fan-out path at scale: gateway spawns N
runner_autopilot sessions, sends a start_gun broadcast, and verifies
that all N sessions respond through Redis pub/sub.

This exercises the critical path:
  broadcast -> Redis PUBLISH simulation:broadcast
    -> dispatcher iterates N active_sessions
    -> N x runner.run_async() (deterministic, no LLM)
    -> N x Redis PUBLISH gateway:broadcast
    -> gateway Hub routes N responses to WebSocket

Prerequisites: gateway, runner_autopilot, and Redis must be running.
Run with: uv run python scripts/e2e/e2e_fanout_test.py [--count N]
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

# Timeout for the event-collection phase (seconds).
COLLECTION_TIMEOUT = int(os.getenv("E2E_FANOUT_TIMEOUT", "60"))


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


async def check_health(session: aiohttp.ClientSession, name: str, url: str) -> bool:
    """Check a service is reachable."""
    for path in ("/health",):
        try:
            async with session.get(f"{url}{path}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status < 500:
                    print(f"  [OK] {name} ({url}{path}) -> {resp.status}")
                    return True
        except Exception:
            continue
    print(f"  [FAIL] {name} ({url}) is not reachable")
    return False


async def preflight_checks() -> bool:
    """Return True if required services are healthy."""
    print("--- Preflight health checks ---")
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            check_health(session, "Gateway", GATEWAY_HTTP_URL),
        )
    all_ok = all(results)
    if not all_ok:
        print("\nGateway is not reachable. Make sure at least gateway and runner_autopilot are running.\n")
    return all_ok


# ---------------------------------------------------------------------------
# Spawn sessions
# ---------------------------------------------------------------------------


async def spawn_sessions(count: int) -> list[str] | None:
    """Spawn N runner_autopilot sessions via the gateway batch spawn API.

    Returns the list of session IDs on success, or None on failure.
    """
    print(f"\n--- Spawning {count} runner_autopilot sessions ---")
    url = f"{GATEWAY_HTTP_URL}/api/v1/spawn"
    body = {"agents": [{"agentType": "runner_autopilot", "count": count}]}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                url,
                json=body,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                status = resp.status
                data = await resp.json()
                if status >= 400:
                    print(f"  [FAIL] Spawn returned HTTP {status}: {data}")
                    return None

                # Response: {"sessions": [{"sessionId": "...", "agentType": "..."}]}
                sessions = data.get("sessions", [])
                session_ids = [s["sessionId"] for s in sessions]
                print(f"  [OK] Spawned {len(session_ids)} sessions (HTTP {status})")
                return session_ids
        except Exception as exc:
            print(f"  [FAIL] Spawn error: {exc}")
            return None


# ---------------------------------------------------------------------------
# Send broadcast
# ---------------------------------------------------------------------------


async def send_broadcast(session_ids: list[str]) -> bool:
    """Send a start_gun broadcast targeting all spawned sessions.

    Builds a protobuf Wrapper with type=broadcast containing a
    BroadcastRequest that targets all session IDs.
    """
    print(f"\n--- Sending start_gun broadcast to {len(session_ids)} sessions ---")

    # Inner payload: the runner event
    runner_event = json.dumps({"event": "start_gun"}).encode()

    # Build BroadcastRequest
    broadcast_req = gateway_pb2.BroadcastRequest(
        payload=runner_event,
        target_session_ids=session_ids,
    )

    # Wrap in a Wrapper envelope
    wrapper = gateway_pb2.Wrapper(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        type="broadcast",
        event="start_gun",
        payload=broadcast_req.SerializeToString(),
        origin=gateway_pb2.Origin(type="client", id="fanout-test"),
    )

    data = wrapper.SerializeToString()

    try:
        ws_url = f"{GATEWAY_WS_URL}?sessionId=fanout-test-sender"
        async with websockets.connect(ws_url) as ws:
            await ws.send(data)
            print(f"  [OK] Broadcast sent ({len(data)} bytes)")
            # Give the gateway a moment to process before we close.
            await asyncio.sleep(0.5)
        return True
    except Exception as exc:
        print(f"  [FAIL] Broadcast error: {exc}")
        return False


# ---------------------------------------------------------------------------
# WebSocket observer
# ---------------------------------------------------------------------------


async def collect_responses(
    expected_count: int,
    session_ids: set[str],
    timeout: int,
) -> dict:
    """Connect as a global observer and collect agent responses.

    Returns a dict with results:
      - responded_sessions: set of session IDs that produced a response
      - total_events: total number of events received
      - elapsed: wall-clock time from first to last response
    """
    responded: set[str] = set()
    total_events = 0
    first_response_time: float | None = None
    last_response_time: float | None = None

    # Connect WITHOUT a sessionId to be a global observer.
    # The Hub always fans out to global observers (empty session ID).
    ws_url = GATEWAY_WS_URL

    try:
        async with websockets.connect(ws_url) as ws:
            print(f"  [WS] Observer connected to {ws_url}")
            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break

                try:
                    data = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2.0))
                except asyncio.TimeoutError:
                    # Check if we already have all responses.
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

                # Count events from runner_autopilot agents.
                sid = wrapper.session_id or (wrapper.origin.session_id if wrapper.origin else "")

                if sid in session_ids:
                    now = time.monotonic()
                    if first_response_time is None:
                        first_response_time = now
                    last_response_time = now

                    responded.add(sid)
                    total_events += 1

                    # Progress indicator every 10 sessions or at completion.
                    if len(responded) % 10 == 0 or len(responded) == expected_count:
                        elapsed = now - first_response_time
                        print(f"  [WS] {len(responded)}/{expected_count} sessions responded ({elapsed:.2f}s)")

                    if len(responded) >= expected_count:
                        # All sessions responded -- wait a beat for
                        # stragglers then exit.
                        await asyncio.sleep(1.0)
                        break

    except Exception as exc:
        print(f"  [WS] Observer error: {exc}")

    elapsed = 0.0
    if first_response_time and last_response_time:
        elapsed = last_response_time - first_response_time

    return {
        "responded_sessions": responded,
        "total_events": total_events,
        "elapsed": elapsed,
    }


# ---------------------------------------------------------------------------
# Main test flow
# ---------------------------------------------------------------------------


async def run_test(count: int) -> bool:
    """Execute the full fan-out test. Returns True on success."""
    # 1. Preflight.
    if not await preflight_checks():
        return False

    # 2. Spawn sessions.
    session_ids = await spawn_sessions(count)
    if not session_ids or len(session_ids) != count:
        print(f"  [FAIL] Expected {count} session IDs, got {len(session_ids or [])}")
        return False

    session_set = set(session_ids)

    # 3. Start observer BEFORE sending the broadcast.
    print(f"\n--- Collecting responses (up to {COLLECTION_TIMEOUT}s) ---")

    # We run observer and broadcast concurrently: the observer connects
    # first, then we send the broadcast after a short delay.
    async def delayed_broadcast():
        await asyncio.sleep(2.0)  # Let observer connect first.
        return await send_broadcast(session_ids)

    observer_task = asyncio.create_task(collect_responses(count, session_set, COLLECTION_TIMEOUT))
    broadcast_ok = await delayed_broadcast()

    if not broadcast_ok:
        observer_task.cancel()
        return False

    results = await observer_task

    # 4. Report.
    responded = results["responded_sessions"]
    total_events = results["total_events"]
    elapsed = results["elapsed"]
    missing = session_set - responded

    print("\n" + "=" * 60)
    print("FAN-OUT SCALE TEST REPORT")
    print("=" * 60)
    print(f"\n  Sessions spawned    : {count}")
    print(f"  Sessions responded  : {len(responded)}")
    print(f"  Total events        : {total_events}")
    print(f"  Fan-out time        : {elapsed:.2f}s")
    if elapsed > 0 and len(responded) > 0:
        print(f"  Throughput          : {len(responded) / elapsed:.1f} responses/sec")

    if missing:
        print(f"\n  Missing sessions ({len(missing)}):")
        for sid in sorted(missing)[:10]:
            print(f"    - {sid}")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more")

    print("\n--- Assertions ---")
    checks = [
        ("All sessions spawned", len(session_ids) == count),
        ("Broadcast sent", broadcast_ok),
        (
            f"All {count} sessions responded",
            len(responded) == count,
        ),
        (
            "Fan-out time < 30s",
            elapsed < 30.0 or len(responded) == 0,
        ),
    ]

    all_passed = True
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_passed = False
        print(f"  [{status}] {label}")

    print("\n" + "=" * 60)
    print(f"RESULT: {'PASS' if all_passed else 'FAIL'}")
    print("=" * 60)

    return all_passed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    global COLLECTION_TIMEOUT

    parser = argparse.ArgumentParser(description="E2E fan-out scale test for runner_autopilot")
    parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="Number of runner_autopilot sessions to spawn (default: 50)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=COLLECTION_TIMEOUT,
        help="Collection timeout in seconds (default: 60)",
    )
    args = parser.parse_args()

    COLLECTION_TIMEOUT = args.timeout

    print("E2E Fan-Out Scale Test")
    print(f"  Gateway HTTP : {GATEWAY_HTTP_URL}")
    print(f"  Gateway WS   : {GATEWAY_WS_URL}")
    print(f"  Session count: {args.count}")
    print(f"  Timeout      : {COLLECTION_TIMEOUT}s\n")

    success = asyncio.run(run_test(args.count))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
