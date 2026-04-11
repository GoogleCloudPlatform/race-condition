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

"""Performance Diagnostic Tool — measures gateway latency across lifecycle phases.

Connects to the simulation gateway and measures latency for key operations:
health checks, simulation spawning, WebSocket streaming, and NPC fan-out.
Produces a structured report with per-phase percentile breakdowns.

Usage (internal / local dev):
    uv run python scripts/bench/perf_diagnostic.py
    uv run python scripts/bench/perf_diagnostic.py --count 200 --timeout 600
    uv run python scripts/bench/perf_diagnostic.py --ws-stability-only

Usage (external / GCP with IAP):
    GATEWAY_URL=https://gateway-<hash>.us-central1.run.app \\
    IAP_CLIENT_ID=<client-id>.apps.googleusercontent.com \\
    uv run python scripts/bench/perf_diagnostic.py

    GATEWAY_URL=https://gateway-<hash>.us-central1.run.app \\
    IAP_CLIENT_ID=<client-id>.apps.googleusercontent.com \\
    uv run python scripts/bench/perf_diagnostic.py --ws-stability-only --ws-hold 120

Makefile shortcut:
    make perf-diagnostic
    make perf-diagnostic PERF_ARGS="--count 50 --ws-stability-only"

Prerequisites:
    - Gateway must be deployed and healthy.
    - For GCP with IAP: valid gcloud credentials and IAP_CLIENT_ID env var.
"""

import argparse
import asyncio
import json
import math
import os
import statistics
import subprocess
import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_HTTP_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8101")
GATEWAY_WS_URL = os.getenv(
    "GATEWAY_WS_URL",
    GATEWAY_HTTP_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws",
)
IAP_CLIENT_ID = os.getenv("IAP_CLIENT_ID", "")
SPAWN_TIMEOUT = 120
COLLECTION_TIMEOUT = 300


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LatencyBucket:
    """Collects latency samples and computes percentile statistics."""

    name: str
    samples: list[float] = field(default_factory=list)

    def add(self, value: float) -> None:
        """Record a latency sample in seconds."""
        self.samples.append(value)

    @property
    def count(self) -> int:
        """Number of recorded samples."""
        return len(self.samples)

    def percentile(self, p: float) -> float:
        """Return the p-th percentile (0-100). Returns 0.0 if empty."""
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = math.ceil(p / 100.0 * len(sorted_samples)) - 1
        idx = max(0, min(idx, len(sorted_samples) - 1))
        return sorted_samples[idx]

    def report(self) -> str:
        """Human-readable summary with count, mean, and percentiles."""
        if not self.samples:
            return f"{self.name}: count=0 (no data)"
        mean = statistics.mean(self.samples)
        return (
            f"{self.name}: count={self.count} "
            f"mean={mean:.3f}s "
            f"p50={self.percentile(50):.3f}s "
            f"p95={self.percentile(95):.3f}s "
            f"p99={self.percentile(99):.3f}s "
            f"min={min(self.samples):.3f}s "
            f"max={max(self.samples):.3f}s"
        )


@dataclass
class PhaseResult:
    """Result of a single diagnostic phase."""

    name: str
    success: bool
    duration: float
    details: dict = field(default_factory=dict)
    error: str = ""


# ---------------------------------------------------------------------------
# IAP Authentication
# ---------------------------------------------------------------------------


def get_iap_token() -> str | None:
    """Obtain an identity token for IAP-protected endpoints via gcloud."""
    if not IAP_CLIENT_ID:
        return None
    try:
        result = subprocess.run(
            [
                "gcloud",
                "auth",
                "print-identity-token",
                f"--audiences={IAP_CLIENT_ID}",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        token = result.stdout.strip()
        return token if token else None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def auth_headers(token: str | None) -> dict[str, str]:
    """Return HTTP authorization headers if a token is available."""
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def ws_extra_headers(token: str | None) -> dict[str, str] | None:
    """Return WebSocket extra headers if a token is available."""
    if token:
        return {"Authorization": f"Bearer {token}"}
    return None


# ---------------------------------------------------------------------------
# Phase 1: Health Check
# ---------------------------------------------------------------------------


async def phase_health(token: str | None) -> PhaseResult:
    """Check gateway health with 5 HTTP GET requests, measuring latency.

    Returns PhaseResult with success=True if all respond with status < 500.
    Details include ``http_latency_p50``.
    """
    import aiohttp

    bucket = LatencyBucket("http_health")
    headers = auth_headers(token)
    t_phase_start = time.monotonic()

    try:
        async with aiohttp.ClientSession() as session:
            for _ in range(5):
                t0 = time.monotonic()
                async with session.get(
                    f"{GATEWAY_HTTP_URL}/health",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    elapsed = time.monotonic() - t0
                    bucket.add(elapsed)
                    if resp.status >= 500:
                        return PhaseResult(
                            name="health",
                            success=False,
                            duration=time.monotonic() - t_phase_start,
                            error=f"Gateway returned HTTP {resp.status}",
                        )
    except Exception as exc:
        return PhaseResult(
            name="health",
            success=False,
            duration=time.monotonic() - t_phase_start,
            error=f"Gateway unreachable: {exc}",
        )

    return PhaseResult(
        name="health",
        success=True,
        duration=time.monotonic() - t_phase_start,
        details={
            "http_latency_p50": bucket.percentile(50),
            "http_latency_p95": bucket.percentile(95),
            "http_latency_p99": bucket.percentile(99),
            "request_count": bucket.count,
        },
    )


# ---------------------------------------------------------------------------
# Phase 2: WebSocket Stability
# ---------------------------------------------------------------------------


async def phase_ws_stability(
    token: str | None,
    hold_seconds: int = 90,
) -> PhaseResult:
    """Hold a WebSocket connection and detect premature drops.

    Connects to the gateway WS, sends application-level pings every 5s,
    and checks whether the connection survives for *hold_seconds*.  If the
    connection drops between 25-35s it is flagged as a likely GCLB idle
    timeout.
    """
    import websockets

    ws_url = f"{GATEWAY_WS_URL}?sessionId=diag-stability-test"
    extra = ws_extra_headers(token)
    t_phase_start = time.monotonic()
    pings_sent = 0
    pongs_received = 0
    drop_reason = "completed"
    upgrade_latency = 0.0

    try:
        t_connect = time.monotonic()
        async with websockets.connect(
            ws_url,
            additional_headers=extra,
            ping_interval=None,
            ping_timeout=None,
            max_size=10 * 1024 * 1024,
        ) as ws:
            upgrade_latency = time.monotonic() - t_connect
            deadline = time.monotonic() + hold_seconds

            while time.monotonic() < deadline:
                try:
                    # Send a WS-level ping every 5s
                    pong_waiter = await ws.ping()
                    pings_sent += 1
                    await asyncio.wait_for(pong_waiter, timeout=5.0)
                    pongs_received += 1
                except asyncio.TimeoutError:
                    # Pong not received within 5s
                    pass
                except websockets.exceptions.ConnectionClosed as exc:
                    drop_reason = f"server closed at {time.monotonic() - t_phase_start:.1f}s: {exc}"
                    break

                # Wait for next ping interval, but also detect connection
                # close during the wait (important for accurate timing).
                remaining = deadline - time.monotonic()
                try:
                    await asyncio.wait_for(ws.recv(), timeout=min(5.0, max(0, remaining)))
                except asyncio.TimeoutError:
                    pass  # Expected -- no data, just waiting
                except websockets.exceptions.ConnectionClosed as exc:
                    drop_reason = f"server closed at {time.monotonic() - t_phase_start:.1f}s: {exc}"
                    break

    except Exception as exc:
        connection_held = time.monotonic() - t_phase_start
        lb_timeout_detected = 25 < connection_held < 35 and drop_reason != "completed"
        return PhaseResult(
            name="ws_stability",
            success=False,
            duration=connection_held,
            details={
                "upgrade_latency": upgrade_latency,
                "connection_held": connection_held,
                "pings_sent": pings_sent,
                "pongs_received": pongs_received,
                "drop_reason": str(exc),
                "lb_timeout_detected": lb_timeout_detected,
            },
            error=str(exc),
        )

    connection_held = time.monotonic() - t_phase_start
    lb_timeout_detected = 25 < connection_held < 35 and drop_reason != "completed"

    return PhaseResult(
        name="ws_stability",
        success=drop_reason == "completed",
        duration=connection_held,
        details={
            "upgrade_latency": upgrade_latency,
            "connection_held": connection_held,
            "pings_sent": pings_sent,
            "pongs_received": pongs_received,
            "drop_reason": drop_reason,
            "lb_timeout_detected": lb_timeout_detected,
        },
    )


# ---------------------------------------------------------------------------
# Phase 3: Full Simulation Lifecycle — helpers
# ---------------------------------------------------------------------------


def build_broadcast_message(text: str, target_session_ids: list[str]) -> bytes:
    """Build a protobuf ``gateway.Wrapper`` broadcast message.

    Mimics the binary frame the frontend sends to fan-out a prompt to
    one or more planner sessions.
    """
    from gen_proto.gateway import gateway_pb2

    inner_payload = json.dumps({"text": text}).encode()
    broadcast_req = gateway_pb2.BroadcastRequest(
        payload=inner_payload,
        target_session_ids=target_session_ids,
    )
    wrapper = gateway_pb2.Wrapper(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        type="broadcast",
        event="broadcast",
        payload=broadcast_req.SerializeToString(),
        origin=gateway_pb2.Origin(type="client", id="perf-diag", session_id="perf-diag"),
    )
    for sid in target_session_ids:
        wrapper.destination.append(sid)
    return wrapper.SerializeToString()


def parse_tool_event(
    wrapper,
) -> tuple[str, dict, str] | None:
    """Extract tool name, data, and session_id from a Wrapper message.

    Returns ``(tool_name, tool_data, session_id)`` for ``tool_end`` events
    whose payload contains a ``tool_name`` key.  Returns ``None`` otherwise.
    """
    if wrapper.event != "tool_end":
        return None

    if not wrapper.payload:
        return None

    try:
        data = json.loads(wrapper.payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    tool_name = data.get("tool_name")
    if not tool_name:
        return None

    return (tool_name, data, wrapper.session_id)


# ---------------------------------------------------------------------------
# Phase 3: Full Simulation Lifecycle
# ---------------------------------------------------------------------------


async def phase_simulation(
    token: str | None,
    prompt: str = "Plan a scenic marathon in Las Vegas for 100 runners",
    agent_type: str = "planner_with_memory",
    count: int = 100,
    timeout: int = COLLECTION_TIMEOUT,
) -> PhaseResult:
    """Run a full simulation lifecycle using the two-phase flow.

    Phase 1 (Plan): Send planning prompt -> planner plans, verifies, stops.
    Phase 2 (Run):  Send "Run simulation with N runners" to same session.
    Then collect all events until the simulator's ``run_end`` or timeout.
    """
    import aiohttp
    import websockets
    from gen_proto.gateway import gateway_pb2

    t_phase_start = time.monotonic()
    headers = auth_headers(token)
    extra = ws_extra_headers(token)

    # Metrics accumulators
    total_events = 0
    total_bytes = 0
    tool_timeline: list[tuple[str, float]] = []
    tick_times: list[float] = []
    process_tick_times: list[float] = []
    tick_latency = LatencyBucket("tick_latency")
    connection_drops = 0
    simulation_complete = False
    t_first_event: float | None = None
    t_broadcast: float | None = None
    t_run_end: float | None = None
    t_start_simulation: float | None = None
    t_spawn_runners: float | None = None
    simulation_id: str | None = None
    last_advance_tick_time: float | None = None
    process_tick_count = 0
    # Track unique runner sessions and their data
    runners_responded: set[str] = set()
    runner_data: list[dict] = []  # process_tick payloads
    compile_results_data: dict | None = None
    spawned_runner_ids: list[str] = []
    tick_advance_data: list[dict] = []  # advance_tick payloads

    # Step 1: Spawn a planner session
    try:
        async with aiohttp.ClientSession() as session:
            spawn_url = f"{GATEWAY_HTTP_URL}/api/v1/spawn"
            body = {"agents": [{"agentType": agent_type, "count": 1}]}
            async with session.post(
                spawn_url,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=SPAWN_TIMEOUT),
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    return PhaseResult(
                        name="simulation",
                        success=False,
                        duration=time.monotonic() - t_phase_start,
                        error=f"Spawn failed: HTTP {resp.status}: {text[:200]}",
                    )
                spawn_data = await resp.json()
    except Exception as exc:
        return PhaseResult(
            name="simulation",
            success=False,
            duration=time.monotonic() - t_phase_start,
            error=f"Spawn request failed: {exc}",
        )

    sessions = spawn_data.get("sessions", [])
    if not sessions:
        return PhaseResult(
            name="simulation",
            success=False,
            duration=time.monotonic() - t_phase_start,
            error="Spawn returned no sessions",
        )
    planner_session_id = sessions[0]["sessionId"]

    # Step 2: Connect observer WS (global -- no sessionId)
    observer_ws = None
    try:
        observer_ws = await websockets.connect(
            GATEWAY_WS_URL,
            additional_headers=extra,
            ping_interval=20,
            ping_timeout=20,
            max_size=10 * 1024 * 1024,
        )
    except Exception as exc:
        return PhaseResult(
            name="simulation",
            success=False,
            duration=time.monotonic() - t_phase_start,
            error=f"Observer WS connection failed: {exc}",
        )

    # Step 3: Open a persistent sender WS for both phases
    sender_ws = None
    try:
        sender_url = f"{GATEWAY_WS_URL}?sessionId=perf-diag-sender"
        sender_ws = await websockets.connect(
            sender_url,
            additional_headers=extra,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        )
    except Exception as exc:
        if observer_ws:
            await observer_ws.close()
        return PhaseResult(
            name="simulation",
            success=False,
            duration=time.monotonic() - t_phase_start,
            error=f"Sender WS connection failed: {exc}",
        )

    # Phase 1: Send planning prompt (e.g. "Plan a marathon in Las Vegas for 100 runners")
    plan_prompt = f"Plan a scenic marathon in Las Vegas for {prompt} runners"
    # If the caller provided a full custom prompt, use it as-is for phase 1
    if not prompt.isdigit():
        plan_prompt = prompt

    broadcast_data = build_broadcast_message(plan_prompt, [planner_session_id])
    await sender_ws.send(broadcast_data)
    t_broadcast = time.monotonic()
    print(f"    [SEND] Phase 1 (plan): {plan_prompt[:80]}...")

    # Step 4: Collect events from observer
    # Two-phase flow matching the frontend:
    #   Phase 1: Planner plans the race, verifies, emits A2UI, then STOPs.
    #            Detected by: run_end from planner, or 15s silence after
    #            verify_plan/validate_and_emit_a2ui.
    #   Phase 2: We send "Run simulation with N runners" to the SAME session.
    #            The planner calls start_simulation + submit_plan_to_simulator.
    #            Simulator spawns runners, runs ticks, compiles results.
    #            Detected by: run_end from simulator/simulation_pipeline.
    deadline = time.monotonic() + timeout
    subscribed = False
    last_event_time = time.monotonic()
    silence_reported = False
    planning_complete = False
    run_simulation_sent = False
    t_run_simulation_sent: float | None = None
    last_tool_name = ""

    try:
        while time.monotonic() < deadline and not simulation_complete:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            try:
                data = await asyncio.wait_for(observer_ws.recv(), timeout=min(remaining, 5.0))
            except asyncio.TimeoutError:
                # Report silence after 30s of no events (helps diagnose hangs)
                if total_events > 0 and not silence_reported:
                    silence = time.monotonic() - last_event_time
                    if silence > 30:
                        elapsed = time.monotonic() - t_phase_start
                        print(f"    [WAIT] {silence:.0f}s silence after {total_events} events ({elapsed:.0f}s elapsed)")
                        silence_reported = True
                continue
            except websockets.exceptions.ConnectionClosed:
                connection_drops += 1
                break

            if not isinstance(data, bytes):
                # Text frames (subscription confirmations, etc.)
                continue

            total_bytes += len(data)
            total_events += 1
            last_event_time = time.monotonic()
            silence_reported = False

            try:
                wrapper = gateway_pb2.Wrapper()
                wrapper.ParseFromString(data)
            except Exception:
                continue

            now = time.monotonic()
            elapsed = now - t_phase_start
            event_type = wrapper.event or wrapper.type or ""
            origin_id = wrapper.origin.id if wrapper.origin else ""
            sid = wrapper.session_id or (wrapper.origin.session_id if wrapper.origin else "")

            # Log every event for diagnostics (matches frontend's simLog.log)
            print(
                f"    [{total_events:>4}] {elapsed:>7.1f}s  "
                f"event={event_type:<20s} origin={origin_id:<25s} "
                f"sim_id={wrapper.simulation_id[:8] if wrapper.simulation_id else '-':<10s}"
            )

            # Subscribe to simulation on first simulation_id
            # (matches frontend: model_start or start_simulation with simulationId)
            if not subscribed and wrapper.simulation_id:
                simulation_id = wrapper.simulation_id
                sub_msg = json.dumps(
                    {
                        "type": "subscribe_simulation",
                        "simulation_id": simulation_id,
                    }
                )
                await observer_ws.send(sub_msg)
                subscribed = True
                print(f"    [SUB]  Subscribed to simulation {simulation_id[:12]}...")

            if t_first_event is None:
                t_first_event = now

            # Track tool events (tool_end with tool_name in payload)
            tool_result = parse_tool_event(wrapper)
            if tool_result:
                tool_name, tool_data, tool_sid = tool_result
                tool_timeline.append((tool_name, elapsed))

                if tool_name == "start_simulation" and t_start_simulation is None:
                    t_start_simulation = now
                elif tool_name == "spawn_runners" and t_spawn_runners is None:
                    t_spawn_runners = now
                    # Capture spawned runner session IDs
                    result = tool_data.get("result", {})
                    if isinstance(result, dict):
                        sids = result.get("session_ids", [])
                        if isinstance(sids, list):
                            spawned_runner_ids.extend(sids)
                            print(f"    [SPAWN] {len(sids)} runners spawned")
                elif tool_name == "advance_tick":
                    tick_times.append(now)
                    if last_advance_tick_time is not None:
                        tick_latency.add(now - last_advance_tick_time)
                    last_advance_tick_time = now
                    # Capture tick data (tick number, runner counts, etc.)
                    result = tool_data.get("result", {})
                    if isinstance(result, dict):
                        tick_advance_data.append(result)
                        tick_num = result.get("tick", "?")
                        max_ticks = result.get("max_ticks", "?")
                        reporting = result.get("runners_reporting", "?")
                        print(f"    [TICK]  tick={tick_num}/{max_ticks} runners_reporting={reporting}")
                elif tool_name == "process_tick":
                    process_tick_count += 1
                    process_tick_times.append(now)
                    # Track which runners responded
                    runners_responded.add(tool_sid)
                    # Capture runner data
                    result = tool_data.get("result", {})
                    if isinstance(result, dict):
                        runner_data.append(result)
                elif tool_name == "check_race_complete":
                    result = tool_data.get("result", {})
                    if isinstance(result, dict) and result.get("race_complete"):
                        t_run_end = now
                        simulation_complete = True
                        print("    [DONE] Race complete (check_race_complete)")
                elif tool_name == "compile_results":
                    result = tool_data.get("result", {})
                    if isinstance(result, dict):
                        compile_results_data = result
                        print(f"    [RESULTS] compile_results received")

            # Track last tool for planning-complete detection
            if tool_result:
                last_tool_name = tool_result[0]

            # Detect PLANNING complete: run_end from planner means
            # the planner finished its turn (planned + verified + stopped).
            # This is when we send the Phase 2 "run simulation" message.
            if (
                event_type == "run_end"
                and not run_simulation_sent
                and origin_id
                in (
                    "planner_with_memory",
                    "planner_with_eval",
                    "planner",
                )
            ):
                planning_complete = True
                planning_duration_val = now - t_broadcast if t_broadcast else 0
                print(
                    f"    [PLAN] Planning complete ({planning_duration_val:.1f}s). Sending Phase 2: run simulation..."
                )
                # Send Phase 2: "Run simulation" to the SAME planner session
                run_msg = f"Run simulation with {count} runners"
                run_data = build_broadcast_message(run_msg, [planner_session_id])
                await sender_ws.send(run_data)
                run_simulation_sent = True
                t_run_simulation_sent = now
                print(f"    [SEND] Phase 2 (run): {run_msg}")

            # Detect SIMULATION complete: run_end from simulator or
            # simulation_pipeline means the full race is done.
            # Individual runner run_end events are ignored.
            if (
                event_type == "run_end"
                and run_simulation_sent
                and origin_id
                in (
                    "simulator",
                    "simulation_pipeline",
                )
            ):
                t_run_end = now
                simulation_complete = True
                print(f"    [DONE] Simulation run_end from {origin_id}")

    finally:
        # Unsubscribe and close
        if subscribed and simulation_id:
            try:
                unsub_msg = json.dumps(
                    {
                        "type": "unsubscribe_simulation",
                        "simulation_id": simulation_id,
                    }
                )
                await observer_ws.send(unsub_msg)
            except Exception:
                pass
        try:
            if sender_ws:
                await sender_ws.close()
        except Exception:
            pass
        try:
            await observer_ws.close()
        except Exception:
            pass

    # Compute derived metrics
    duration = time.monotonic() - t_phase_start
    simulation_duration = (t_run_end - t_broadcast) if (t_run_end and t_broadcast) else None
    time_to_first_event = (t_first_event - t_broadcast) if (t_first_event and t_broadcast) else None
    planning_duration = (t_start_simulation - t_first_event) if (t_start_simulation and t_first_event) else None
    spawn_duration = (t_spawn_runners - t_start_simulation) if (t_spawn_runners and t_start_simulation) else None

    # Runner response analysis
    runners_spawned = len(spawned_runner_ids)
    runners_with_response = len(runners_responded)
    runners_missing = runners_spawned - runners_with_response if runners_spawned > 0 else 0

    # Print runner summary
    if runners_spawned > 0:
        print(f"\n  Runner Summary:")
        print(f"    Spawned:   {runners_spawned}")
        print(f"    Responded: {runners_with_response} ({runners_with_response / runners_spawned * 100:.0f}%)")
        print(f"    Missing:   {runners_missing}")
        print(f"    Ticks:     {len(tick_advance_data)}")
        print(f"    process_tick events: {process_tick_count}")

    # Per-tick runner_status breakdown from process_tick payloads
    if runner_data and tick_advance_data:
        print(f"\n  Per-Tick Runner Status (from process_tick payloads):")
        print(f"    {'tick':<6} {'running':>8} {'finished':>9} {'exhausted':>10} {'collapsed':>10} {'total':>6}")
        print(f"    {'----':<6} {'-------':>8} {'--------':>9} {'---------':>10} {'---------':>10} {'-----':>6}")

        # Group runner_data by approximate tick using tick_advance_data timing
        # Each advance_tick marks the start of a tick; process_ticks follow
        tick_boundaries = [t - t_phase_start for t in tick_times] if tick_times else []
        # Use elapsed time from tool_timeline to bin process_tick events
        pt_entries = [(t, d) for t, d in zip(process_tick_times, runner_data)]

        for tick_idx in range(len(tick_advance_data)):
            tick_start = tick_times[tick_idx] - t_phase_start if tick_idx < len(tick_times) else 0
            tick_end = tick_times[tick_idx + 1] - t_phase_start if tick_idx + 1 < len(tick_times) else float("inf")

            # Collect process_tick results within this tick window
            tick_results = [d for t, d in pt_entries if tick_start <= (t - t_phase_start) < tick_end]

            running = sum(1 for r in tick_results if r.get("runner_status") == "running")
            finished = sum(1 for r in tick_results if r.get("runner_status") == "finished")
            exhausted = sum(1 for r in tick_results if r.get("runner_status") == "exhausted")
            collapsed = sum(1 for r in tick_results if r.get("runner_status") == "collapsed")
            total = len(tick_results)

            tick_num = tick_advance_data[tick_idx].get("tick", tick_idx)
            print(f"    {tick_num:<6} {running:>8} {finished:>9} {exhausted:>10} {collapsed:>10} {total:>6}")

        # Final status across ALL process_tick events
        all_running = sum(1 for r in runner_data if r.get("runner_status") == "running")
        all_finished = sum(1 for r in runner_data if r.get("runner_status") == "finished")
        all_exhausted = sum(1 for r in runner_data if r.get("runner_status") == "exhausted")
        all_collapsed = sum(1 for r in runner_data if r.get("runner_status") == "collapsed")
        print(
            f"    {'TOTAL':<6} {all_running:>8} {all_finished:>9} {all_exhausted:>10} {all_collapsed:>10} {len(runner_data):>6}"
        )

    if compile_results_data:
        print(f"\n  Compiled Results:")
        for k, v in compile_results_data.items():
            if isinstance(v, (str, int, float, bool)):
                print(f"    {k}: {v}")

    details: dict = {
        "total_events": total_events,
        "total_bytes": total_bytes,
        "simulation_duration": simulation_duration,
        "time_to_first_event": time_to_first_event,
        "planning_duration": planning_duration,
        "spawn_duration": spawn_duration,
        "tick_count": len(tick_times),
        "tick_latency_p50": tick_latency.percentile(50),
        "tick_latency_p95": tick_latency.percentile(95),
        "tick_latency_p99": tick_latency.percentile(99),
        "process_tick_count": process_tick_count,
        "runners_spawned": runners_spawned,
        "runners_responded": runners_with_response,
        "runners_missing": runners_missing,
        "connection_drops": connection_drops,
        "tool_timeline": tool_timeline,
    }

    return PhaseResult(
        name="simulation",
        success=simulation_complete,
        duration=duration,
        details=details,
    )


# ---------------------------------------------------------------------------
# Diagnostic Report
# ---------------------------------------------------------------------------


def print_final_report(phases: list[PhaseResult]) -> None:
    """Print a comprehensive diagnostic report to stdout.

    Includes a header, phase summary table, bottleneck analysis, and verdict.
    """
    # --- Header ---
    print()
    print("=" * 72)
    print("  PERFORMANCE DIAGNOSTIC REPORT")
    print("=" * 72)
    print()

    is_external = GATEWAY_HTTP_URL.startswith("https://")
    path_type = "external (GCP)" if is_external else "internal (local)"
    iap_status = "enabled" if IAP_CLIENT_ID else "disabled"
    print(f"  Gateway URL:  {GATEWAY_HTTP_URL}")
    print(f"  Path type:    {path_type}")
    print(f"  IAP:          {iap_status}")
    print()

    # --- Phase Summary Table ---
    print("-" * 72)
    print(f"  {'Phase':<20} {'Status':<8} {'Duration':>10}   Details")
    print("-" * 72)

    for phase in phases:
        status = "PASS" if phase.success else "FAIL"
        duration_str = f"{phase.duration:.3f}s"

        # Build detail string, skipping session_ids and formatting floats
        detail_parts = []
        for k, v in phase.details.items():
            if k == "session_ids":
                continue
            if k == "tool_timeline":
                continue
            if isinstance(v, float):
                detail_parts.append(f"{k}={v:.3f}")
            else:
                detail_parts.append(f"{k}={v}")
        detail_str = ", ".join(detail_parts) if detail_parts else ""

        print(f"  {phase.name:<20} {status:<8} {duration_str:>10}   {detail_str}")
        if phase.error:
            print(f"  {'':.<20} ERROR: {phase.error}")

    print("-" * 72)
    print()

    # --- Bottleneck Analysis ---
    issues: list[str] = []

    for phase in phases:
        if phase.name == "ws_stability":
            if phase.details.get("lb_timeout_detected"):
                held = phase.details.get("connection_held", 0)
                issues.append(
                    f"GCLB idle timeout detected: WebSocket dropped after "
                    f"{held:.1f}s. Configure backend-service timeout >= 3600s."
                )

        if phase.name == "simulation":
            drops = phase.details.get("connection_drops", 0)
            if drops > 0:
                issues.append(
                    f"WebSocket connection drops during simulation: {drops} drop(s). "
                    f"Check GCLB timeout and gateway keep-alive configuration."
                )

            p99 = phase.details.get("tick_latency_p99", 0)
            if p99 > 30:
                p50 = phase.details.get("tick_latency_p50", 0)
                issues.append(
                    f"High tail latency: tick p99={p99:.3f}s (p50={p50:.3f}s). "
                    f"Investigate tick processing or NPC fan-out bottlenecks."
                )

            ttfe = phase.details.get("time_to_first_event", 0)
            if ttfe and ttfe > 5:
                issues.append(
                    f"Slow simulation startup: time_to_first_event={ttfe:.3f}s. "
                    f"Check spawn latency and agent initialization."
                )

            total_events = phase.details.get("total_events", 0)
            sim_duration = phase.details.get("simulation_duration")
            if sim_duration and sim_duration > 0 and total_events > 0:
                throughput = total_events / sim_duration
                if throughput < 1.0:
                    issues.append(
                        f"Low event throughput: {throughput:.2f} events/s "
                        f"({total_events} events in {sim_duration:.1f}s)."
                    )

            # Print tool timeline if available
            timeline = phase.details.get("tool_timeline")
            if timeline:
                print("  Tool Timeline:")
                for tool_name, elapsed in timeline:
                    print(f"    {elapsed:>8.3f}s  {tool_name}")
                print()

    if issues:
        print("  Bottleneck Analysis:")
        for i, issue in enumerate(issues, 1):
            print(f"    {i}. {issue}")
        print()
    else:
        print("  Bottleneck Analysis: No issues detected.")
        print()

    # --- Verdict ---
    all_passed = all(p.success for p in phases)
    print("-" * 72)
    if all_passed and not issues:
        print("  Verdict: HEALTHY — All phases passed, no bottlenecks detected.")
    elif all_passed:
        print(f"  Verdict: WARNING — All phases passed but {len(issues)} potential issue(s) detected.")
    else:
        failed = [p.name for p in phases if not p.success]
        print(f"  Verdict: UNHEALTHY — Failed phase(s): {', '.join(failed)}. {len(issues)} issue(s) detected.")
    print("=" * 72)
    print()


# ---------------------------------------------------------------------------
# CLI Orchestrator
# ---------------------------------------------------------------------------


DEFAULT_PROMPT_TEMPLATE = "Plan a scenic marathon in Las Vegas for {count} runners"


async def run_diagnostic(
    count: int = 100,
    agent_type: str = "planner_with_memory",
    prompt: str | None = None,
    ws_stability_only: bool = False,
    ws_hold: int = 90,
    timeout: int = 300,
) -> bool:
    """Orchestrate all diagnostic phases and print the final report.

    Returns True if all executed phases succeeded.
    """
    phases: list[PhaseResult] = []

    # Resolve IAP token
    token = get_iap_token() if IAP_CLIENT_ID else None

    # Phase 1: Health check
    print("Phase 1: Health check...")
    health_result = await phase_health(token)
    phases.append(health_result)

    if not health_result.success:
        print(f"  ABORT: Health check failed — {health_result.error}")
        print_final_report(phases)
        return False

    print(f"  OK ({health_result.duration:.3f}s)")

    # Phase 2: WebSocket stability
    print(f"Phase 2: WebSocket stability (hold {ws_hold}s)...")
    ws_result = await phase_ws_stability(token, hold_seconds=ws_hold)
    phases.append(ws_result)
    status = "PASS" if ws_result.success else "FAIL"
    print(f"  {status} ({ws_result.duration:.3f}s)")

    if ws_stability_only:
        print_final_report(phases)
        return all(p.success for p in phases)

    # Phase 3: Full simulation
    effective_prompt = prompt or DEFAULT_PROMPT_TEMPLATE.format(count=count)
    print(f"Phase 3: Simulation (agent={agent_type}, timeout={timeout}s)...")
    sim_result = await phase_simulation(
        token=token,
        prompt=effective_prompt,
        agent_type=agent_type,
        count=count,
        timeout=timeout,
    )
    phases.append(sim_result)
    status = "PASS" if sim_result.success else "FAIL"
    print(f"  {status} ({sim_result.duration:.3f}s)")

    print_final_report(phases)
    return all(p.success for p in phases)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments and run the performance diagnostic."""
    parser = argparse.ArgumentParser(
        description="Performance diagnostic for the simulation gateway.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of runners in the simulation prompt (default: 100).",
    )
    parser.add_argument(
        "--agent-type",
        type=str,
        default="planner_with_memory",
        help="Agent type to spawn (default: planner_with_memory).",
    )
    parser.add_argument(
        "--ws-stability-only",
        action="store_true",
        help="Run only health + WS stability phases (skip simulation).",
    )
    parser.add_argument(
        "--ws-hold",
        type=int,
        default=90,
        help="Seconds to hold the WebSocket connection (default: 90).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Simulation collection timeout in seconds (default: 300).",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Override the default simulation prompt.",
    )

    args = parser.parse_args()

    # Print banner
    print()
    print("=" * 72)
    print("  N26 Simulation Gateway — Performance Diagnostic")
    print("=" * 72)
    print(f"  Gateway:           {GATEWAY_HTTP_URL}")
    print(f"  WebSocket:         {GATEWAY_WS_URL}")
    print(f"  IAP:               {'enabled' if IAP_CLIENT_ID else 'disabled'}")
    print(f"  Agent type:        {args.agent_type}")
    print(f"  Runner count:      {args.count}")
    print(f"  WS hold:           {args.ws_hold}s")
    print(f"  Timeout:           {args.timeout}s")
    print(f"  WS stability only: {args.ws_stability_only}")
    print("=" * 72)
    print()

    success = asyncio.run(
        run_diagnostic(
            count=args.count,
            agent_type=args.agent_type,
            prompt=args.prompt,
            ws_stability_only=args.ws_stability_only,
            ws_hold=args.ws_hold,
            timeout=args.timeout,
        )
    )

    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
