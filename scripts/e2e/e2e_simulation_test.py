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

"""E2E Simulation Integration Test.

Proves the full planner-to-simulator flow works:
planner builds plan -> submits to simulator -> simulator runs race ->
events appear on WebSocket.

Prerequisites: gateway, Redis, planner, simulator, and runner must be running.
Start with: uv run start (or honcho start)
Run with: uv run python scripts/e2e/e2e_simulation_test.py
"""

import asyncio
import os
import sys
import time
import uuid
from dataclasses import dataclass, field

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
PLANNER_URL = os.getenv("PLANNER_URL", "http://127.0.0.1:8205")
PLANNER_A2A_ENDPOINT = f"{PLANNER_URL}/a2a/planner_with_eval/"

# Timeout for the entire event-collection phase (seconds).
COLLECTION_TIMEOUT = int(os.getenv("E2E_TIMEOUT", "120"))

PLAN_PROMPT = (
    "Plan a scenic marathon in Las Vegas for 5 runners. "
    "When you submit to the simulator, use simulation_config with "
    "duration_seconds=10, tick_interval_seconds=2, runner_count=5. "
    "Execute the simulation immediately after planning."
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CollectedEvent:
    """Lightweight representation of a decoded Wrapper message."""

    timestamp: str
    msg_type: str
    event: str
    origin_type: str
    origin_id: str
    session_id: str
    status: str
    payload_len: int


@dataclass
class TestResults:
    """Aggregated results from the E2E run."""

    events: list[CollectedEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ws_connected: bool = False
    a2a_sent: bool = False

    # Assertion flags
    @property
    def has_any_event(self) -> bool:
        return len(self.events) > 0

    @property
    def has_simulator_event(self) -> bool:
        return any("simulator" in e.origin_id.lower() for e in self.events)

    @property
    def has_simulation_tick(self) -> bool:
        return any(e.event == "tick:advance" for e in self.events)

    @property
    def has_fatal_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def passed(self) -> bool:
        return (
            self.has_any_event and self.has_simulator_event and self.has_simulation_tick and not self.has_fatal_errors
        )


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


async def check_health(session: aiohttp.ClientSession, name: str, url: str) -> bool:
    """Check a service is reachable.  Tries /health then /.well-known/agent-card.json."""
    for path in ("/health", "/.well-known/agent-card.json"):
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
    """Return True if all required services are healthy."""
    print("--- Preflight health checks ---")
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            check_health(session, "Gateway", GATEWAY_HTTP_URL),
            check_health(session, "Planner (eval)", PLANNER_URL),
        )
    all_ok = all(results)
    if not all_ok:
        print(
            "\nSome services are not reachable.  Make sure the full stack is "
            "running:\n  uv run start   # or honcho start\n"
        )
    return all_ok


# ---------------------------------------------------------------------------
# WebSocket observer
# ---------------------------------------------------------------------------


async def ws_observer(results: TestResults, stop_event: asyncio.Event) -> None:
    """Connect to the gateway WS (no sessionId = global observer) and collect
    protobuf Wrapper messages until *stop_event* is set."""
    try:
        async with websockets.connect(GATEWAY_WS_URL) as ws:
            results.ws_connected = True
            print(f"  [WS] Connected to {GATEWAY_WS_URL}")

            while not stop_event.is_set():
                try:
                    data = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    print("  [WS] Connection closed by server")
                    break

                if not isinstance(data, bytes):
                    # Skip non-binary messages (shouldn't happen, but be safe).
                    continue

                try:
                    wrapper = gateway_pb2.Wrapper()
                    wrapper.ParseFromString(data)
                    evt = CollectedEvent(
                        timestamp=wrapper.timestamp,
                        msg_type=wrapper.type,
                        event=wrapper.event,
                        origin_type=wrapper.origin.type if wrapper.origin else "",
                        origin_id=wrapper.origin.id if wrapper.origin else "",
                        session_id=wrapper.session_id,
                        status=wrapper.status,
                        payload_len=len(wrapper.payload),
                    )
                    results.events.append(evt)
                    label = evt.event or evt.msg_type or "unknown"
                    origin = evt.origin_id or "?"
                    print(f"  [WS] event={label:<25s} origin={origin}")
                except Exception as exc:
                    # Non-protobuf message; log but don't treat as fatal.
                    print(f"  [WS] Failed to parse message ({len(data)} bytes): {exc}")

    except Exception as exc:
        results.errors.append(f"WebSocket observer error: {exc}")
        print(f"  [WS] Observer error: {exc}")


# ---------------------------------------------------------------------------
# A2A message sender
# ---------------------------------------------------------------------------


async def send_plan_request(results: TestResults) -> None:
    """Send a message/send JSON-RPC request to the planner."""
    body = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": f"e2e-test-{uuid.uuid4().hex[:8]}",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": PLAN_PROMPT}],
                "messageId": str(uuid.uuid4()),
            }
        },
    }

    print(f"  [A2A] POST {PLANNER_A2A_ENDPOINT}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                PLANNER_A2A_ENDPOINT,
                json=body,
                timeout=aiohttp.ClientTimeout(total=COLLECTION_TIMEOUT),
            ) as resp:
                status = resp.status
                text = await resp.text()
                print(f"  [A2A] Response {status}: {text[:200]}")
                if status >= 400:
                    results.errors.append(f"Planner returned HTTP {status}: {text[:200]}")
                else:
                    results.a2a_sent = True
    except TimeoutError:
        # The planner's full turn (plan + simulate) can exceed the HTTP
        # timeout.  The request WAS sent -- WebSocket events confirm
        # the server received it.  Mark as sent so collection continues.
        results.a2a_sent = True
        print("  [A2A] HTTP response timed out (request was sent; events are flowing)")
    except Exception as exc:
        results.errors.append(f"Failed to send A2A message: {exc}")
        print(f"  [A2A] Error: {exc}")


# ---------------------------------------------------------------------------
# Main test flow
# ---------------------------------------------------------------------------


async def run_test() -> TestResults:
    results = TestResults()
    stop_event = asyncio.Event()

    # Start WS observer as background task.
    observer_task = asyncio.create_task(ws_observer(results, stop_event))

    # Give the WS a moment to connect before sending the plan request.
    await asyncio.sleep(1.0)

    if not results.ws_connected:
        print("  [!] WS not yet connected, waiting a bit longer...")
        await asyncio.sleep(2.0)

    # Send the plan request.
    print("\n--- Sending plan request to planner ---")
    await send_plan_request(results)

    if not results.a2a_sent:
        print("  [!] A2A request failed; aborting collection.")
        stop_event.set()
        await observer_task
        return results

    # Collect events until timeout.
    print(f"\n--- Collecting WebSocket events (up to {COLLECTION_TIMEOUT}s) ---")
    deadline = time.monotonic() + COLLECTION_TIMEOUT

    while time.monotonic() < deadline:
        await asyncio.sleep(2.0)

        # Early exit: we already have everything we need.
        if results.has_simulator_event and results.has_simulation_tick:
            print("  [OK] All required events observed -- finishing early.")
            break

    stop_event.set()

    # Allow the observer a moment to drain.
    try:
        await asyncio.wait_for(observer_task, timeout=5.0)
    except asyncio.TimeoutError:
        observer_task.cancel()

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(results: TestResults) -> None:
    print("\n" + "=" * 60)
    print("E2E SIMULATION TEST REPORT")
    print("=" * 60)

    print(f"\nTotal events collected : {len(results.events)}")
    print(f"WS connected          : {results.ws_connected}")
    print(f"A2A sent              : {results.a2a_sent}")
    print(f"Errors                : {len(results.errors)}")

    if results.events:
        print("\n--- Event summary ---")
        # Build a frequency table of (origin_id, event).
        freq: dict[tuple[str, str], int] = {}
        for e in results.events:
            key = (e.origin_id or "(none)", e.event or e.msg_type or "(none)")
            freq[key] = freq.get(key, 0) + 1
        for (origin, event), count in sorted(freq.items()):
            print(f"  {origin:<30s} {event:<25s} x{count}")

    if results.errors:
        print("\n--- Errors ---")
        for err in results.errors:
            print(f"  - {err}")

    print("\n--- Assertions ---")
    checks = [
        ("At least 1 event received", results.has_any_event),
        ("Simulator origin seen", results.has_simulator_event),
        ("tick:advance event seen", results.has_simulation_tick),
        ("No fatal errors", not results.has_fatal_errors),
    ]
    all_passed = True
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_passed = False
        print(f"  [{status}] {label}")

    print("\n" + "=" * 60)
    if all_passed:
        print("RESULT: PASS")
    else:
        print("RESULT: FAIL")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> bool:
    """Run the E2E test.  Returns True on success."""
    print("E2E Simulation Integration Test")
    print(f"  Gateway HTTP : {GATEWAY_HTTP_URL}")
    print(f"  Gateway WS   : {GATEWAY_WS_URL}")
    print(f"  Planner (eval): {PLANNER_URL}")
    print(f"  Timeout      : {COLLECTION_TIMEOUT}s\n")

    if not await preflight_checks():
        return False

    print("\n--- Starting test ---")
    results = await run_test()
    print_report(results)
    return results.passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
