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

"""Demo 1 reliability harness — drives the planner agent like the frontend does.

Spawns N planner sessions via the gateway, sends each the Demo 1 prompt
("Plan a marathon in Las Vegas for 10,000 runners"), collects all wire
events per session until ``run_end``, then reports per-trial outcomes
plus aggregate stats.

Designed for hypothesis testing on Bug B (planner terminal-narrative
reliability). Replaces manual browser-driven Demo 1 runs.

Usage::

    # Run 5 trials with default prompt and default gateway (localhost:8101)
    uv run python scripts/diagnostics/demo1_harness.py

    # 10 trials, custom timeout
    uv run python scripts/diagnostics/demo1_harness.py --trials 10 --timeout 90

    # Specify agent (defaults to "planner"; also useful: "planner_with_eval")
    uv run python scripts/diagnostics/demo1_harness.py --agent planner_with_eval

    # Dump per-trial event sequences to JSON for further analysis
    uv run python scripts/diagnostics/demo1_harness.py --json-out /tmp/demo1.json

    # Custom prompt
    uv run python scripts/diagnostics/demo1_harness.py --prompt "Plan a 5K in San Francisco"

The harness exits non-zero if any trial errors out (network/timeout) so
it's CI-friendly. Reliability counts (e.g. "3/5 with terminal text") are
ALWAYS reported; the script does not fail on poor reliability — that's
the metric you're measuring.

Prerequisites:
  - Local stack running (gateway on port 8101, planner on 8204).
  - Honcho or equivalent: ``uv run start`` from the worktree root.
"""

import argparse
import asyncio
import dataclasses
import json
import os
import statistics
import sys
import time
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_HTTP_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8101")
GATEWAY_WS_URL = os.getenv(
    "GATEWAY_WS_URL",
    GATEWAY_HTTP_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws",
)
DEFAULT_PROMPT = "Plan a marathon in Las Vegas for 10,000 runners"
DEFAULT_AGENT = "planner"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_TRIALS = 5

# Tools the planner is expected to call during a healthy Demo 1 run.
EXPECTED_TOOLS = {"load_skill", "plan_marathon_route", "report_marathon_route"}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class WireEvent:
    """A single decoded event observed for a session."""

    timestamp: float
    msg_type: str  # wrapper.type, e.g. "json", "a2ui"
    event: str  # wrapper.event, e.g. "tool_start", "tool_end", "model_end", "text"
    tool_name: str | None = None  # populated when payload has tool_name
    text_preview: str | None = None  # first 80 chars of text if event=text
    payload_size: int = 0


@dataclasses.dataclass
class TrialResult:
    """Outcome of a single Demo 1 trial."""

    trial_index: int
    session_id: str
    success: bool  # True if no error and got run_end
    error: str | None
    duration_seconds: float
    events: list[WireEvent]

    @property
    def tools_called(self) -> list[str]:
        """Distinct tool names called in this trial, in first-call order."""
        seen: list[str] = []
        for e in self.events:
            if e.event == "tool_start" and e.tool_name and e.tool_name not in seen:
                seen.append(e.tool_name)
        return seen

    @property
    def report_called(self) -> bool:
        """Did the trial call report_marathon_route?"""
        return "report_marathon_route" in self.tools_called

    @property
    def has_terminal_text(self) -> bool:
        """Did a chat-rendered text event arrive (event=text inside type=json)?"""
        return any(e.event == "text" and e.msg_type == "json" for e in self.events)

    @property
    def has_a2ui(self) -> bool:
        """Did an A2UI event arrive (type=a2ui)?"""
        return any(e.msg_type == "a2ui" for e in self.events)

    @property
    def expected_tools_missing(self) -> set[str]:
        """Expected tools the planner did NOT call."""
        return EXPECTED_TOOLS - set(self.tools_called)

    @property
    def event_sequence(self) -> str:
        """Compact event sequence string for at-a-glance pattern recognition."""
        return " ".join(f"{e.msg_type}/{e.event}" for e in self.events)


# ---------------------------------------------------------------------------
# Gateway interactions
# ---------------------------------------------------------------------------


async def spawn_planner_session(agent_type: str, http_session: Any) -> str:
    """POST /api/v1/spawn to create a single planner session. Returns session_id."""
    spawn_url = f"{GATEWAY_HTTP_URL}/api/v1/spawn"
    body = {"agents": [{"agentType": agent_type, "count": 1}]}
    async with http_session.post(spawn_url, json=body, timeout=30) as resp:
        if resp.status >= 400:
            text = await resp.text()
            raise RuntimeError(f"spawn failed: HTTP {resp.status}: {text[:200]}")
        data = await resp.json()
    sessions = data.get("sessions") or []
    if not sessions:
        raise RuntimeError("spawn returned no sessions")
    return sessions[0]["sessionId"]


def build_broadcast_message(prompt_text: str, target_session_ids: list[str]) -> bytes:
    """Build the binary Wrapper message the frontend would send for a chat prompt."""
    from gen_proto.gateway import gateway_pb2

    inner_payload = json.dumps({"text": prompt_text}).encode()
    broadcast_req = gateway_pb2.BroadcastRequest(
        payload=inner_payload,
        target_session_ids=target_session_ids,
    )
    wrapper = gateway_pb2.Wrapper(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        type="broadcast",
        event="broadcast",
        payload=broadcast_req.SerializeToString(),
        origin=gateway_pb2.Origin(type="client", id="demo1-harness", session_id="demo1-harness"),
    )
    for sid in target_session_ids:
        wrapper.destination.append(sid)
    return wrapper.SerializeToString()


def decode_event(wrapper: Any, t_offset: float) -> WireEvent:
    """Decode a Wrapper message into a structured WireEvent."""
    msg_type = wrapper.type or ""
    event = wrapper.event or ""
    payload_size = len(wrapper.payload) if wrapper.payload else 0

    tool_name: str | None = None
    text_preview: str | None = None
    if wrapper.payload:
        try:
            data = json.loads(wrapper.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = None

        if isinstance(data, dict):
            t = data.get("tool") or data.get("tool_name")
            if isinstance(t, str):
                tool_name = t
            txt = data.get("text")
            if isinstance(txt, str):
                text_preview = txt[:80]

    return WireEvent(
        timestamp=time.monotonic() - t_offset,
        msg_type=msg_type,
        event=event,
        tool_name=tool_name,
        text_preview=text_preview,
        payload_size=payload_size,
    )


# ---------------------------------------------------------------------------
# Single-trial driver
# ---------------------------------------------------------------------------


async def run_trial(
    trial_index: int,
    prompt_text: str,
    agent_type: str,
    timeout_seconds: float,
    verbose: bool,
) -> TrialResult:
    """Drive one Demo 1 trial against the gateway. Returns the trial outcome."""
    import aiohttp
    import websockets
    from gen_proto.gateway import gateway_pb2

    t_start = time.monotonic()
    events: list[WireEvent] = []
    session_id = ""
    error: str | None = None

    try:
        async with aiohttp.ClientSession() as http_session:
            session_id = await spawn_planner_session(agent_type, http_session)

        if verbose:
            print(f"  [trial {trial_index}] spawned session {session_id[:8]} (agent={agent_type})")

        # Per-session subscription via the same WS used by the frontend's chat scenes.
        # The gateway broadcasts events for a session to subscribers of that session_id.
        subscriber_url = f"{GATEWAY_WS_URL}?sessionId={session_id}"
        sender_url = f"{GATEWAY_WS_URL}?sessionId=demo1-harness-sender-{uuid.uuid4().hex[:8]}"

        async with (
            websockets.connect(
                subscriber_url,
                ping_interval=20,
                ping_timeout=20,
                max_size=10 * 1024 * 1024,
            ) as subscriber_ws,
            websockets.connect(
                sender_url,
                ping_interval=20,
                ping_timeout=20,
                max_size=10 * 1024 * 1024,
            ) as sender_ws,
        ):
            # Send the prompt via the sender WS (binary Wrapper).
            payload = build_broadcast_message(prompt_text, [session_id])
            await sender_ws.send(payload)
            t_sent = time.monotonic()

            if verbose:
                print(f"  [trial {trial_index}] sent prompt; collecting events…")

            # Collect events until run_end OR timeout.
            deadline = t_sent + timeout_seconds
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    msg = await asyncio.wait_for(subscriber_ws.recv(), timeout=min(remaining, 5.0))
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed as exc:
                    error = f"subscriber WS closed: {exc}"
                    break

                if not isinstance(msg, bytes):
                    continue  # skip non-binary frames (subscription confirmations etc.)

                try:
                    wrapper = gateway_pb2.Wrapper()
                    wrapper.ParseFromString(msg)
                except Exception as exc:  # noqa: BLE001
                    error = f"failed to parse wrapper: {exc}"
                    continue

                # Filter to events that belong to THIS session. The subscriber
                # WS scoped by sessionId should only receive these, but be
                # defensive in case the gateway broadcasts globally for some
                # event types (run_start/run_end may go to all subscribers).
                if wrapper.session_id and wrapper.session_id != session_id:
                    continue

                event = decode_event(wrapper, t_offset=t_start)
                events.append(event)

                if event.event == "run_end":
                    break
            else:
                # Loop exhausted without break — timeout
                if not any(e.event == "run_end" for e in events):
                    error = f"timeout after {timeout_seconds}s ({len(events)} events)"

        success = error is None and any(e.event == "run_end" for e in events)
        return TrialResult(
            trial_index=trial_index,
            session_id=session_id,
            success=success,
            error=error,
            duration_seconds=time.monotonic() - t_start,
            events=events,
        )

    except Exception as exc:  # noqa: BLE001
        return TrialResult(
            trial_index=trial_index,
            session_id=session_id,
            success=False,
            error=f"{type(exc).__name__}: {exc}",
            duration_seconds=time.monotonic() - t_start,
            events=events,
        )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_trial_summary(result: TrialResult, verbose: bool) -> None:
    """Print a one-line per-trial summary plus optional event sequence."""
    status = "OK" if result.success else "ERR"
    tools = ", ".join(result.tools_called) or "(none)"
    flags: list[str] = []
    if result.report_called:
        flags.append("report✓")
    else:
        flags.append("report✗")
    if result.has_terminal_text:
        flags.append("text✓")
    else:
        flags.append("text✗")
    if result.has_a2ui:
        flags.append("a2ui✓")
    flag_str = " ".join(flags)

    print(
        f"  [{status}] trial {result.trial_index} "
        f"session={result.session_id[:8]} "
        f"duration={result.duration_seconds:.1f}s "
        f"events={len(result.events)} "
        f"{flag_str} "
        f"tools=[{tools}]"
    )
    if result.error:
        print(f"        error: {result.error}")
    if verbose and result.events:
        print(f"        sequence: {result.event_sequence}")


def print_aggregate(results: list[TrialResult]) -> None:
    """Print the headline reliability stats."""
    n = len(results)
    successes = [r for r in results if r.success]
    report_called = [r for r in results if r.report_called]
    text_emitted = [r for r in results if r.has_terminal_text]
    both = [r for r in results if r.report_called and r.has_terminal_text]
    a2ui = [r for r in results if r.has_a2ui]

    print()
    print("=" * 70)
    print(f"AGGREGATE — N={n}")
    print("=" * 70)
    print(f"  trials completed (run_end seen):     {len(successes)}/{n}")
    print(f"  report_marathon_route called:        {len(report_called)}/{n}")
    print(f"  terminal text emitted:               {len(text_emitted)}/{n}")
    print(f"  report + text (both):                {len(both)}/{n}")
    print(f"  a2ui event emitted:                  {len(a2ui)}/{n}")

    if successes:
        durations = [r.duration_seconds for r in successes]
        print(
            f"  duration (successful trials):        "
            f"mean={statistics.mean(durations):.1f}s "
            f"min={min(durations):.1f}s max={max(durations):.1f}s"
        )

    failures = [r for r in results if not r.success]
    if failures:
        print()
        print(f"  FAILURES ({len(failures)}):")
        for r in failures:
            print(f"    trial {r.trial_index}: {r.error}")
    print()


def write_json_report(results: list[TrialResult], path: str) -> None:
    """Dump full per-trial details to JSON for offline analysis."""
    out = []
    for r in results:
        out.append(
            {
                "trial_index": r.trial_index,
                "session_id": r.session_id,
                "success": r.success,
                "error": r.error,
                "duration_seconds": r.duration_seconds,
                "tools_called": r.tools_called,
                "report_called": r.report_called,
                "has_terminal_text": r.has_terminal_text,
                "has_a2ui": r.has_a2ui,
                "expected_tools_missing": sorted(r.expected_tools_missing),
                "events": [
                    {
                        "t": e.timestamp,
                        "msg_type": e.msg_type,
                        "event": e.event,
                        "tool_name": e.tool_name,
                        "text_preview": e.text_preview,
                        "payload_size": e.payload_size,
                    }
                    for e in r.events
                ],
            }
        )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"  wrote per-trial JSON report to {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    print(f"Demo 1 harness — gateway={GATEWAY_HTTP_URL} agent={args.agent}")
    print(f"  prompt: {args.prompt!r}")
    print(f"  trials: {args.trials}  timeout: {args.timeout}s")
    print()

    results: list[TrialResult] = []
    for i in range(1, args.trials + 1):
        result = await run_trial(
            trial_index=i,
            prompt_text=args.prompt,
            agent_type=args.agent,
            timeout_seconds=args.timeout,
            verbose=args.verbose,
        )
        results.append(result)
        print_trial_summary(result, verbose=args.verbose)
        # Small spacing between trials to let the planner cool down.
        if i < args.trials:
            await asyncio.sleep(args.cooldown)

    print_aggregate(results)

    if args.json_out:
        write_json_report(results, args.json_out)

    # Exit non-zero if any trial errored. Reliability metrics themselves do
    # NOT cause a non-zero exit — that's data, not a hard failure.
    any_error = any(not r.success or r.error for r in results)
    return 1 if any_error else 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Demo 1 reliability harness — drives the planner agent like the frontend "
            "and reports terminal-text / report-tool reliability across N trials."
        )
    )
    p.add_argument(
        "--trials",
        type=int,
        default=DEFAULT_TRIALS,
        help="Number of independent trials to run (default: 5).",
    )
    p.add_argument(
        "--prompt",
        type=str,
        default=DEFAULT_PROMPT,
        help=f"Prompt text to send (default: {DEFAULT_PROMPT!r}).",
    )
    p.add_argument(
        "--agent",
        type=str,
        default=DEFAULT_AGENT,
        help=("Agent type to spawn (default: planner). Useful alternatives: planner_with_eval, planner_with_memory."),
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-trial timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    p.add_argument(
        "--cooldown",
        type=float,
        default=2.0,
        help="Seconds to sleep between trials (default: 2.0).",
    )
    p.add_argument(
        "--json-out",
        type=str,
        default="",
        help="If set, write per-trial details (incl. event sequences) as JSON.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print event sequence for each trial.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
