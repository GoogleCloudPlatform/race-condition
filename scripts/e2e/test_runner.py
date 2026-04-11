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

"""Universal runner agent test harness.

Tests any runner agent (``runner`` or ``runner_autopilot``) via three
communication modes:

  * **a2a**     -- Direct A2A JSON-RPC to the agent endpoint
  * **gateway** -- REST spawn + orchestration push via the gateway
  * **redis**   -- Publish to ``simulation:broadcast``, observe collector buffers

Usage examples::

    # Local autopilot via A2A
    python scripts/e2e/test_runner.py --mode a2a --target http://localhost:8210 \\
        --agent-type runner_autopilot

    # 100 runners through the gateway
    python scripts/e2e/test_runner.py --mode gateway --target http://localhost:8101 \\
        --agent-type runner_autopilot --count 100

    # Single LLM runner (Gemma 4 via Ollama)
    python scripts/e2e/test_runner.py --mode a2a --target http://localhost:8207 \\
        --agent-type runner --ticks 3

    # GCP-deployed runner via A2A with auth
    python scripts/e2e/test_runner.py --mode a2a \\
        --target https://runner-YOUR_PROJECT_NUMBER.us-central1.run.app \\
        --agent-type runner --gcp-project your-gcp-project-id

    # Redis direct path
    python scripts/e2e/test_runner.py --mode redis --redis-addr 127.0.0.1:8102 \\
        --agent-type runner_autopilot --count 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RACE_DISTANCE_MI = 26.2188
DEFAULT_TICKS = 3
DEFAULT_MAX_TICKS = 6
MINUTES_PER_TICK = 30.0
EVENT_TIMEOUT = 60.0  # seconds per event

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EventResult:
    """Result of sending a single event to a runner."""

    event_name: str
    latency_ms: float
    success: bool
    error: str | None = None
    tool_calls: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    raw_response: str | None = None


@dataclass
class RunnerResult:
    """Aggregate results for a single runner session."""

    session_id: str
    events: list[EventResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Event builders
# ---------------------------------------------------------------------------


def build_start_gun(max_ticks: int = DEFAULT_MAX_TICKS) -> dict:
    return {
        "event": "start_gun",
        "tick": 0,
        "max_ticks": max_ticks,
        "minutes_per_tick": MINUTES_PER_TICK,
        "elapsed_minutes": 0,
        "race_distance_mi": RACE_DISTANCE_MI,
    }


def build_tick(tick: int, max_ticks: int = DEFAULT_MAX_TICKS) -> dict:
    return {
        "event": "tick",
        "tick": tick,
        "max_ticks": max_ticks,
        "minutes_per_tick": MINUTES_PER_TICK,
        "elapsed_minutes": tick * MINUTES_PER_TICK,
        "race_distance_mi": RACE_DISTANCE_MI,
        "collector_buffer_key": "",  # empty = skip direct-write
    }


# ---------------------------------------------------------------------------
# A2A helpers
# ---------------------------------------------------------------------------


def _build_a2a_payload(text: str, context_id: str | None = None) -> dict:
    """Build a JSON-RPC 2.0 ``message/send`` request."""
    msg: dict[str, Any] = {
        "role": "user",
        "messageId": str(uuid4()),
        "parts": [{"kind": "text", "text": text}],
    }
    if context_id:
        msg["contextId"] = context_id
    return {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": str(uuid4()),
        "params": {
            "message": msg,
            "configuration": {"blocking": True},
        },
    }


def _extract_a2a_response(body: dict) -> tuple[str, list[str]]:
    """Extract text and tool call names from an A2A JSON-RPC response.

    Returns (response_text, tool_call_names).
    """
    texts: list[str] = []
    tools: list[str] = []

    result = body.get("result", {})

    # Navigate Task -> status -> message -> parts
    status = result.get("status", {})
    status_msg = status.get("message", {})
    for part in status_msg.get("parts", []):
        if part.get("kind") == "text" and part.get("text"):
            texts.append(part["text"])

    # Also check artifacts
    for artifact in result.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("kind") == "text" and part.get("text"):
                texts.append(part["text"])

    # Extract tool calls from response text (heuristic)
    full_text = " ".join(texts)
    for tool_name in [
        "accelerate",
        "brake",
        "get_vitals",
        "process_tick",
        "deplete_water",
        "rehydrate",
    ]:
        if tool_name in full_text.lower():
            tools.append(tool_name)

    return full_text, tools


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def _get_gcp_auth_headers(project: str) -> dict[str, str]:
    """Get GCP access token via google-auth default credentials."""
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        return {"Authorization": f"Bearer {creds.token}"}
    except Exception as exc:
        print(f"ERROR: Failed to get GCP credentials: {exc}", file=sys.stderr)
        print("  Run: gcloud auth application-default login", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Transport: A2A mode
# ---------------------------------------------------------------------------


async def run_a2a(
    client: httpx.AsyncClient,
    target: str,
    agent_type: str,
    session_ids: list[str],
    events: list[dict],
    verbose: bool = False,
) -> list[RunnerResult]:
    """Send events to runners via direct A2A JSON-RPC."""
    a2a_url = f"{target.rstrip('/')}/a2a/{agent_type}/"
    results: list[RunnerResult] = []

    for sid in session_ids:
        runner_result = RunnerResult(session_id=sid)
        for evt in events:
            evt_text = json.dumps(evt)
            payload = _build_a2a_payload(evt_text, context_id=sid)

            t0 = time.monotonic()
            try:
                resp = await client.post(
                    a2a_url,
                    json=payload,
                    timeout=EVENT_TIMEOUT,
                )
                latency = (time.monotonic() - t0) * 1000
                body = resp.json()

                if verbose:
                    print(
                        f"  [A2A] {evt['event']} -> {resp.status_code}",
                    )
                    print(
                        f"    {json.dumps(body, indent=2)[:500]}",
                    )

                if "error" in body:
                    runner_result.events.append(
                        EventResult(
                            event_name=evt["event"],
                            latency_ms=latency,
                            success=False,
                            error=body["error"].get("message", "unknown"),
                        )
                    )
                else:
                    text, tools = _extract_a2a_response(body)
                    runner_result.events.append(
                        EventResult(
                            event_name=evt["event"],
                            latency_ms=latency,
                            success=True,
                            tool_calls=tools,
                            raw_response=text[:300] if verbose else None,
                        )
                    )
            except Exception as exc:
                latency = (time.monotonic() - t0) * 1000
                runner_result.events.append(
                    EventResult(
                        event_name=evt["event"],
                        latency_ms=latency,
                        success=False,
                        error=str(exc),
                    )
                )
        results.append(runner_result)

    return results


async def run_a2a_parallel(
    client: httpx.AsyncClient,
    target: str,
    agent_type: str,
    count: int,
    events: list[dict],
    verbose: bool = False,
) -> list[RunnerResult]:
    """Fan out A2A requests to multiple runners in parallel per event."""
    a2a_url = f"{target.rstrip('/')}/a2a/{agent_type}/"
    session_ids = [str(uuid4()) for _ in range(count)]
    results: dict[str, RunnerResult] = {sid: RunnerResult(session_id=sid) for sid in session_ids}

    for evt in events:
        evt_text = json.dumps(evt)
        evt_name = evt["event"]

        async def _send_one(sid: str) -> EventResult:
            payload = _build_a2a_payload(evt_text, context_id=sid)
            t0 = time.monotonic()
            try:
                resp = await client.post(a2a_url, json=payload, timeout=EVENT_TIMEOUT)
                latency = (time.monotonic() - t0) * 1000
                body = resp.json()
                if "error" in body:
                    return EventResult(
                        event_name=evt_name,
                        latency_ms=latency,
                        success=False,
                        error=body["error"].get("message", "unknown"),
                    )
                text, tools = _extract_a2a_response(body)
                return EventResult(
                    event_name=evt_name,
                    latency_ms=latency,
                    success=True,
                    tool_calls=tools,
                    raw_response=text[:300] if verbose else None,
                )
            except Exception as exc:
                latency = (time.monotonic() - t0) * 1000
                return EventResult(
                    event_name=evt_name,
                    latency_ms=latency,
                    success=False,
                    error=str(exc),
                )

        # Fan out to all sessions in parallel
        tasks = [_send_one(sid) for sid in session_ids]
        event_results = await asyncio.gather(*tasks)

        for sid, er in zip(session_ids, event_results):
            results[sid].events.append(er)

        # Brief report for multi-runner
        successes = sum(1 for er in event_results if er.success)
        latencies = [er.latency_ms for er in event_results if er.success]
        if latencies:
            avg = statistics.mean(latencies)
            _print_multi_event(evt_name, successes, count, avg, latencies)
        else:
            errors = [er.error for er in event_results if er.error]
            sample = errors[0] if errors else "unknown"
            print(f"  [{evt_name}] {successes}/{count} OK  error: {sample}")

    return list(results.values())


# ---------------------------------------------------------------------------
# Transport: Gateway mode
# ---------------------------------------------------------------------------


async def run_gateway(
    client: httpx.AsyncClient,
    target: str,
    agent_type: str,
    count: int,
    events: list[dict],
    simulation_id: str,
    verbose: bool = False,
) -> list[RunnerResult]:
    """Spawn runners via gateway, send events via A2A (discovered URL)."""
    gw = target.rstrip("/")

    # Step 1: Spawn sessions
    spawn_body = {
        "agents": [{"agentType": agent_type, "count": count}],
        "simulation_id": simulation_id,
    }
    print(f"  Spawning {count} {agent_type} sessions via {gw}/api/v1/spawn ...")
    try:
        resp = await client.post(f"{gw}/api/v1/spawn", json=spawn_body, timeout=30.0)
    except httpx.ConnectError:
        print(f"  ERROR: Cannot connect to gateway at {gw}")
        print("  Is the simulation running? Try: uv run start")
        return []
    if resp.status_code != 200:
        print(f"  ERROR: Spawn failed: {resp.status_code} {resp.text}")
        return []
    spawn_data = resp.json()
    session_ids = [s["sessionId"] for s in spawn_data.get("sessions", [])]
    print(f"  Spawned {len(session_ids)} sessions")

    if not session_ids:
        return []

    # Step 2: Discover agent URL
    print(f"  Discovering agent URL via {gw}/api/v1/agent-types ...")
    try:
        agent_types_resp = await client.get(f"{gw}/api/v1/agent-types", timeout=10.0)
    except httpx.ConnectError:
        print(f"  ERROR: Cannot connect to gateway at {gw}")
        return []
    agent_cards = agent_types_resp.json()

    if agent_type not in agent_cards:
        print(f"  ERROR: Agent type '{agent_type}' not in catalog.")
        print(f"  Available: {list(agent_cards.keys())}")
        return []

    card = agent_cards[agent_type]
    agent_url_raw = card.get("url", "")

    # The card URL may include the full A2A path (e.g.
    # http://127.0.0.1:8210/a2a/runner_autopilot) or just the base host.
    # Strip the /a2a/{name} suffix to get the agent's base URL, since
    # run_a2a/run_a2a_parallel re-append /a2a/{agent_type}/.
    agent_base = agent_url_raw.rstrip("/")
    a2a_suffix = f"/a2a/{agent_type}"
    if agent_base.endswith(a2a_suffix):
        agent_base = agent_base[: -len(a2a_suffix)]
    if not agent_base:
        agent_base = gw  # fallback to gateway

    print(f"  Agent base URL: {agent_base}")

    # Step 3: Send events via A2A to each session
    if count == 1:
        return await run_a2a(client, agent_base, agent_type, session_ids, events, verbose)
    return await run_a2a_parallel(client, agent_base, agent_type, count, events, verbose)


# ---------------------------------------------------------------------------
# Transport: Redis mode
# ---------------------------------------------------------------------------


async def run_redis(
    redis_addr: str,
    agent_type: str,
    count: int,
    events: list[dict],
    simulation_id: str,
    verbose: bool = False,
) -> list[RunnerResult]:
    """Publish events to Redis simulation:broadcast, observe collector buffers."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        print("ERROR: redis package required for --mode redis", file=sys.stderr)
        sys.exit(1)

    host, port_str = redis_addr.split(":")
    r = aioredis.Redis(host=host, port=int(port_str), decode_responses=True)

    session_ids = [str(uuid4()) for _ in range(count)]
    results: dict[str, RunnerResult] = {sid: RunnerResult(session_id=sid) for sid in session_ids}

    for evt in events:
        evt_text = json.dumps(evt)
        evt_name = evt["event"]
        broadcast_msg = json.dumps(
            {
                "type": "broadcast",
                "eventId": str(uuid4()),
                "simulation_id": simulation_id,
                "payload": {"data": evt_text, "targets": session_ids},
            }
        )
        collector_key = f"collector:buffer:{simulation_id}"

        t0 = time.monotonic()
        await r.publish("simulation:broadcast", broadcast_msg)

        received = 0
        deadline = time.monotonic() + EVENT_TIMEOUT
        while received < count and time.monotonic() < deadline:
            item = await r.blpop(collector_key, timeout=1)
            if item:
                received += 1
                _, data = item
                try:
                    parsed = json.loads(data)
                    sid = parsed.get("session_id", "unknown")
                    if sid in results:
                        latency = (time.monotonic() - t0) * 1000
                        results[sid].events.append(
                            EventResult(
                                event_name=evt_name,
                                latency_ms=latency,
                                success=True,
                                raw_response=data[:300] if verbose else None,
                            )
                        )
                except json.JSONDecodeError:
                    pass

        latency = (time.monotonic() - t0) * 1000
        responded = {sid for sid in session_ids if any(e.event_name == evt_name for e in results[sid].events)}
        for sid in session_ids:
            if sid not in responded:
                results[sid].events.append(
                    EventResult(
                        event_name=evt_name,
                        latency_ms=latency,
                        success=False,
                        error="timeout",
                    )
                )
        print(f"  [{evt_name}] {len(responded)}/{count} received via Redis")

    await r.aclose()
    return list(results.values())


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _percentile(data: list[float], p: float) -> float:
    """Simple percentile calculation."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


def _print_multi_event(
    name: str,
    successes: int,
    total: int,
    avg: float,
    latencies: list[float],
) -> None:
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    failures = total - successes
    fail_str = f"  [{failures} failed]" if failures else ""
    print(
        f"  [{name:12s}] {successes}/{total} OK  "
        f"avg={avg:.0f}ms  p50={p50:.0f}ms  p95={p95:.0f}ms  "
        f"p99={p99:.0f}ms{fail_str}"
    )


def print_report(
    mode: str,
    agent_type: str,
    target: str,
    results: list[RunnerResult],
    as_json: bool = False,
) -> None:
    """Print human-readable or JSON report."""
    count = len(results)
    all_events: list[EventResult] = []
    for rr in results:
        all_events.extend(rr.events)

    total_tool_calls: dict[str, int] = {}
    total_latencies: list[float] = []
    successes = 0
    for er in all_events:
        if er.success:
            successes += 1
            total_latencies.append(er.latency_ms)
        for tc in er.tool_calls:
            total_tool_calls[tc] = total_tool_calls.get(tc, 0) + 1

    if as_json:
        output = {
            "mode": mode,
            "agent_type": agent_type,
            "target": target,
            "count": count,
            "runners": [
                {
                    "session_id": rr.session_id,
                    "events": [
                        {
                            "event": er.event_name,
                            "latency_ms": round(er.latency_ms, 1),
                            "success": er.success,
                            "error": er.error,
                            "tool_calls": er.tool_calls,
                        }
                        for er in rr.events
                    ],
                }
                for rr in results
            ],
            "summary": {
                "total_events": len(all_events),
                "successful": successes,
                "avg_latency_ms": (round(statistics.mean(total_latencies), 1) if total_latencies else None),
                "p50_latency_ms": (round(_percentile(total_latencies, 50), 1) if total_latencies else None),
                "p95_latency_ms": (round(_percentile(total_latencies, 95), 1) if total_latencies else None),
                "p99_latency_ms": (round(_percentile(total_latencies, 99), 1) if total_latencies else None),
                "tool_calls": total_tool_calls,
            },
        }
        print(json.dumps(output, indent=2))
        return

    # Human-readable report
    print()
    print("=" * 60)
    print(f"Runner Test: {agent_type} x{count} @ {target} ({mode} mode)")
    print("=" * 60)

    if count == 1 and results:
        rr = results[0]
        print(f"Session: {rr.session_id}")
        print("-" * 60)
        for i, er in enumerate(rr.events, 1):
            status = "OK" if er.success else f"FAIL ({er.error})"
            tools_str = ", ".join(er.tool_calls) if er.tool_calls else "none"
            print(
                f"  [{i}/{len(rr.events)}] {er.event_name:12s} {status:8s}  {er.latency_ms:6.0f}ms  tools: {tools_str}"
            )
            if er.raw_response:
                print(f"         response: {er.raw_response[:120]}")
    else:
        # Aggregate per-event stats
        event_names: list[str] = []
        if results:
            event_names = [er.event_name for er in results[0].events]
        for evt_idx, evt_name in enumerate(event_names):
            evt_latencies = []
            evt_successes = 0
            for rr in results:
                if evt_idx < len(rr.events):
                    er = rr.events[evt_idx]
                    if er.success:
                        evt_successes += 1
                        evt_latencies.append(er.latency_ms)
            if evt_latencies:
                _print_multi_event(
                    evt_name,
                    evt_successes,
                    count,
                    statistics.mean(evt_latencies),
                    evt_latencies,
                )
            else:
                print(f"  [{evt_name:12s}] 0/{count} OK")

    print("-" * 60)
    print("Summary:")
    print(f"  Runners:    {count}")
    print(
        f"  Events:     {len(all_events)} sent, {successes} successful ({successes * 100 / len(all_events):.1f}%)"
        if all_events
        else "  Events:     0"
    )
    if total_latencies:
        print(
            f"  Latency:    avg={statistics.mean(total_latencies):.0f}ms  "
            f"p50={_percentile(total_latencies, 50):.0f}ms  "
            f"p95={_percentile(total_latencies, 95):.0f}ms  "
            f"p99={_percentile(total_latencies, 99):.0f}ms"
        )
    if total_tool_calls:
        tc_str = ", ".join(f"{k}: {v}" for k, v in sorted(total_tool_calls.items()))
        print(f"  Tool calls: {sum(total_tool_calls.values())} ({tc_str})")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Universal runner agent test harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--mode",
        choices=["a2a", "gateway", "redis"],
        required=True,
        help="Communication mode",
    )
    p.add_argument(
        "--target",
        help="Runner (a2a) or gateway (gateway) base URL",
    )
    p.add_argument(
        "--agent-type",
        default="runner",
        help="Agent type name (default: runner)",
    )
    p.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of runner sessions (default: 1)",
    )
    p.add_argument(
        "--ticks",
        type=int,
        default=DEFAULT_TICKS,
        help=f"Number of tick events after start_gun (default: {DEFAULT_TICKS})",
    )
    p.add_argument(
        "--gcp-project",
        help="GCP project ID to enable access token auth",
    )
    p.add_argument(
        "--redis-addr",
        help="Redis address HOST:PORT (required for --mode redis)",
    )
    p.add_argument(
        "--simulation-id",
        default=None,
        help="Simulation ID (default: auto-generated)",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print full event payloads",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON",
    )
    args = p.parse_args()

    if args.mode in ("a2a", "gateway") and not args.target:
        p.error(f"--target is required for --mode {args.mode}")
    if args.mode == "redis" and not args.redis_addr:
        p.error("--redis-addr is required for --mode redis")

    return args


async def main() -> None:
    args = parse_args()

    simulation_id = args.simulation_id or str(uuid4())
    max_ticks = args.ticks + 1  # +1 for start_gun tick 0

    # Build event sequence
    events: list[dict] = [build_start_gun(max_ticks=max_ticks)]
    for tick in range(1, args.ticks + 1):
        events.append(build_tick(tick, max_ticks=max_ticks))

    if not args.json_output:
        print(f"Runner Test: {args.agent_type} x{args.count} ({args.mode} mode, {len(events)} events)")

    # Auth headers
    headers: dict[str, str] = {}
    if args.gcp_project:
        if not args.json_output:
            print(f"  Authenticating with GCP project: {args.gcp_project}")
        headers = await _get_gcp_auth_headers(args.gcp_project)

    results: list[RunnerResult] = []

    if args.mode == "a2a":
        async with httpx.AsyncClient(headers=headers) as client:
            if args.count == 1:
                sid = str(uuid4())
                results = await run_a2a(
                    client,
                    args.target,
                    args.agent_type,
                    [sid],
                    events,
                    args.verbose,
                )
            else:
                results = await run_a2a_parallel(
                    client,
                    args.target,
                    args.agent_type,
                    args.count,
                    events,
                    args.verbose,
                )

    elif args.mode == "gateway":
        async with httpx.AsyncClient(headers=headers) as client:
            results = await run_gateway(
                client,
                args.target,
                args.agent_type,
                args.count,
                events,
                simulation_id,
                args.verbose,
            )

    elif args.mode == "redis":
        results = await run_redis(
            args.redis_addr,
            args.agent_type,
            args.count,
            events,
            simulation_id,
            args.verbose,
        )

    print_report(
        args.mode,
        args.agent_type,
        args.target or args.redis_addr or "unknown",
        results,
        as_json=args.json_output,
    )

    # Exit code: 0 if all events succeeded, 1 otherwise
    all_ok = all(er.success for rr in results for er in rr.events)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
