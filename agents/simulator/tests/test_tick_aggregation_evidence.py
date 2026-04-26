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

"""Evidence test: prints full data distributions from 50 concurrent simulations.

Run with: uv run pytest <this_file> -v -s -m slow
The -s flag is required to see the printed statistics.
"""

import asyncio
import importlib.util
import math
import pathlib
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.runner_autopilot.agent import root_agent as runner_agent
from agents.utils.runner_protocol import (
    RunnerEvent,
    RunnerEventType,
    serialize_runner_event,
)

# Dynamic import since the skill directory is hyphenated
tools_path = pathlib.Path(__file__).parents[1] / "skills" / "advancing-race-ticks" / "tools.py"
spec = importlib.util.spec_from_file_location("race_tick.tools", tools_path)
assert spec is not None
assert spec.loader is not None
tools_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools_module)
advance_tick = tools_module.advance_tick

# Constants
SIM_COUNT = 50
RUNNER_COUNT = 5
MARATHON_MI = 26.2188
TOTAL_RACE_HOURS = 6.0
MAX_TICKS = 12
APP_NAME = "test_evidence"


def _msg(event_type: RunnerEventType, **data) -> types.Content:
    text = serialize_runner_event(RunnerEvent(event=event_type, data=data))
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])


async def _run_agent(runner: InMemoryRunner, sid: str, msg: types.Content) -> list:
    events = []
    async for event in runner.run_async(user_id="sim", session_id=sid, new_message=msg):
        events.append(event)
    return events


def _build_drain_message(session_id: str, state: dict) -> dict:
    return {
        "session_id": session_id,
        "agent_id": "runner_autopilot",
        "event": "tool_end",
        "msg_type": "json",
        "timestamp": "2026-04-03T10:00:00",
        "payload": {
            "tool_name": "process_tick",
            "result": {
                "status": "success",
                "runner_status": state.get("runner_status", "running"),
                "velocity": state.get("velocity", 0.0),
                "effective_velocity": state.get("velocity", 0.0) * 0.9,
                "distance_mi": state.get("distance", 0.0),
                "distance": round(state.get("distance", 0.0), 4),
                "water": state.get("water", 100.0),
                "pace_min_per_mi": state.get("pace_min_per_mi"),
                "mi_this_tick": state.get("distance", 0.0) / max(1, MAX_TICKS),
                "exhausted": state.get("exhausted", False),
                "collapsed": state.get("collapsed", False),
                "finish_time_minutes": state.get("finish_time_minutes"),
            },
        },
    }


def _make_tool_context(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    ctx.session = MagicMock()
    ctx.session.id = state.get("_sim_session_id", "sim")
    ctx.invocation_id = f"inv-{id(state)}"
    ctx.agent_name = "tick-agent"
    ctx.actions = MagicMock()
    ctx.actions.escalate = False
    return ctx


def _percentile(data: list[float], p: float) -> float:
    """Compute the p-th percentile (0-100) of sorted data."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = f + 1
    if c >= len(s):
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _stats(data: list[float]) -> dict:
    """Compute min, max, mean, median, p5, p95, stddev."""
    if not data:
        return {"n": 0, "min": 0, "max": 0, "mean": 0, "median": 0, "p5": 0, "p95": 0, "std": 0}
    n = len(data)
    mean = sum(data) / n
    variance = sum((x - mean) ** 2 for x in data) / n
    return {
        "n": n,
        "min": min(data),
        "max": max(data),
        "mean": mean,
        "median": _percentile(data, 50),
        "p5": _percentile(data, 5),
        "p95": _percentile(data, 95),
        "std": math.sqrt(variance),
    }


def _histogram(data: list[float], bins: int = 10, width: int = 40) -> list[str]:
    """ASCII histogram."""
    if not data:
        return ["  (no data)"]
    lo, hi = min(data), max(data)
    if lo == hi:
        return [f"  all values = {lo:.3f}  (n={len(data)})"]
    step = (hi - lo) / bins
    counts = [0] * bins
    for v in data:
        idx = min(int((v - lo) / step), bins - 1)
        counts[idx] += 1
    mx = max(counts) if counts else 1
    lines = []
    for i, c in enumerate(counts):
        lo_edge = lo + i * step
        hi_edge = lo + (i + 1) * step
        bar = "#" * int(c / mx * width) if mx > 0 else ""
        lines.append(f"  [{lo_edge:7.2f}, {hi_edge:7.2f}) | {bar} {c}")
    return lines


async def _run_simulation_with_telemetry(sim_id: int) -> dict:
    """Run one simulation, return per-tick + per-runner telemetry."""
    minutes_per_tick = (TOTAL_RACE_HOURS * 60) / MAX_TICKS

    runner_sessions = [f"s{sim_id:03d}-r{i:03d}" for i in range(RUNNER_COUNT)]
    runners: dict[str, InMemoryRunner] = {}
    for sid in runner_sessions:
        r = InMemoryRunner(agent=runner_agent, app_name=APP_NAME)
        await r.session_service.create_session(user_id="sim", session_id=sid, app_name=APP_NAME)
        runners[sid] = r

    start_msg = _msg(RunnerEventType.START_GUN)
    for sid, r in runners.items():
        await _run_agent(r, sid, start_msg)

    sim_state: dict = {
        "_sim_session_id": f"sim-ev-{sim_id:03d}",
        "current_tick": 0,
        "max_ticks": MAX_TICKS,
        "simulation_config": {"tick_interval_seconds": 0, "total_race_hours": TOTAL_RACE_HOURS},
        "tick_snapshots": [],
        "runner_session_ids": runner_sessions,
    }

    tick_data = []
    runner_final_states = {}

    for tick in range(MAX_TICKS):
        elapsed = (tick + 1) * minutes_per_tick
        tick_msg = _msg(
            RunnerEventType.TICK,
            tick=tick,
            max_ticks=MAX_TICKS,
            minutes_per_tick=minutes_per_tick,
            elapsed_minutes=elapsed,
            race_distance_mi=MARATHON_MI,
        )

        drain_messages = []
        per_runner_tick = []
        for sid, r in runners.items():
            await _run_agent(r, sid, tick_msg)
            session = await r.session_service.get_session(user_id="sim", session_id=sid, app_name=APP_NAME)
            assert session is not None
            st = dict(session.state)
            drain_messages.append(_build_drain_message(sid, st))
            per_runner_tick.append(
                {
                    "sid": sid,
                    "velocity": st.get("velocity", 0.0),
                    "distance": st.get("distance", 0.0),
                    "water": st.get("water", 100.0),
                    "runner_status": st.get("runner_status", "running"),
                    "exhausted": st.get("exhausted", False),
                    "collapsed": st.get("collapsed", False),
                    "finished": st.get("finished", False),
                    "finish_time_minutes": st.get("finish_time_minutes"),
                }
            )

        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=drain_messages)
        sim_state["current_tick"] = tick
        ctx = _make_tool_context(state=sim_state)

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
        ):
            result = await advance_tick(tool_context=ctx)

        tick_data.append(
            {
                "tick": tick,
                "elapsed_min": elapsed,
                "runners_reporting": result["runners_reporting"],
                "avg_velocity": result["avg_velocity"],
                "avg_water": result["avg_water"],
                "avg_distance": result["avg_distance"],
                "status_counts": result.get("status_counts", {}),
                "per_runner": per_runner_tick,
            }
        )

        # Capture final states on last tick
        if tick == MAX_TICKS - 1:
            for prt in per_runner_tick:
                runner_final_states[prt["sid"]] = prt

    return {
        "sim_id": sim_id,
        "tick_data": tick_data,
        "runner_final_states": runner_final_states,
    }


@pytest.mark.asyncio
async def test_evidence_50_simulations(capsys):
    """Run 50 simulations and print full statistical evidence."""
    tasks = [_run_simulation_with_telemetry(i) for i in range(SIM_COUNT)]
    results = await asyncio.gather(*tasks)

    # ── Collect cross-simulation statistics ──────────────────────────
    # Per-tick aggregates across all simulations
    tick_runners_reporting: dict[int, list[int]] = defaultdict(list)
    tick_avg_velocity: dict[int, list[float]] = defaultdict(list)
    tick_avg_water: dict[int, list[float]] = defaultdict(list)
    tick_avg_distance: dict[int, list[float]] = defaultdict(list)
    tick_status_running: dict[int, list[int]] = defaultdict(list)
    tick_status_finished: dict[int, list[int]] = defaultdict(list)
    tick_status_exhausted: dict[int, list[int]] = defaultdict(list)
    tick_status_collapsed: dict[int, list[int]] = defaultdict(list)

    all_finish_ticks: list[int] = []  # tick when each runner first finished
    all_finish_times: list[float] = []  # simulated finish time in minutes
    all_final_distances: list[float] = []
    all_final_water: list[float] = []
    all_final_velocities: list[float] = []
    anomalies: list[str] = []

    for sim in results:
        # Track when runners first finish per simulation
        runner_finish_tick: dict[str, int] = {}

        for td in sim["tick_data"]:
            t = td["tick"]
            tick_runners_reporting[t].append(td["runners_reporting"])
            tick_avg_velocity[t].append(td["avg_velocity"])
            tick_avg_water[t].append(td["avg_water"])
            tick_avg_distance[t].append(td["avg_distance"])
            tick_status_running[t].append(td["status_counts"].get("running", 0))
            tick_status_finished[t].append(td["status_counts"].get("finished", 0))
            tick_status_exhausted[t].append(td["status_counts"].get("exhausted", 0))
            tick_status_collapsed[t].append(td["status_counts"].get("collapsed", 0))

            # Check for the regression anomaly
            if td["runners_reporting"] != RUNNER_COUNT:
                anomalies.append(f"SIM {sim['sim_id']} TICK {t}: runners_reporting={td['runners_reporting']}")
            if td["avg_velocity"] == 0:
                anomalies.append(f"SIM {sim['sim_id']} TICK {t}: avg_velocity=0")
            if td["avg_water"] == 0:
                anomalies.append(f"SIM {sim['sim_id']} TICK {t}: avg_water=0")
            if t > 0 and td["avg_distance"] == 0:
                anomalies.append(f"SIM {sim['sim_id']} TICK {t}: avg_distance=0")

            for pr in td["per_runner"]:
                if pr["finished"] and pr["sid"] not in runner_finish_tick:
                    runner_finish_tick[pr["sid"]] = t
                    if pr["finish_time_minutes"]:
                        all_finish_times.append(pr["finish_time_minutes"])
                    all_finish_ticks.append(t)

        for st in sim["runner_final_states"].values():
            all_final_distances.append(st["distance"])
            all_final_water.append(st["water"])
            all_final_velocities.append(st["velocity"])

    # ── Print report ─────────────────────────────────────────────────
    # Use capsys to capture, then re-print so it shows with -s
    with capsys.disabled():
        print("\n")
        print("=" * 78)
        print("  TICK AGGREGATION EVIDENCE REPORT")
        print(f"  {SIM_COUNT} simulations x {RUNNER_COUNT} runners x {MAX_TICKS} ticks")
        print(f"  Total ticks processed: {SIM_COUNT * MAX_TICKS}")
        print(f"  Total runner-ticks: {SIM_COUNT * MAX_TICKS * RUNNER_COUNT}")
        print("=" * 78)

        # ── Anomaly summary ──
        print("\n── ANOMALY CHECK ──")
        if anomalies:
            print(f"  FOUND {len(anomalies)} ANOMALIES:")
            for a in anomalies[:30]:
                print(f"    {a}")
        else:
            print("  ZERO ANOMALIES across all simulations")

        # ── Per-tick table ──
        print("\n── PER-TICK AGGREGATES (mean across 50 sims) ──")
        print(
            f"  {'Tick':>4} {'Elapsed':>8} {'Rptng':>5} "
            f"{'AvgVel':>8} {'AvgWtr':>8} {'AvgDist':>9} "
            f"{'Run':>5} {'Fin':>5} {'Exh':>5} {'Col':>5}"
        )
        print("  " + "-" * 74)
        for t in range(MAX_TICKS):
            elapsed = (t + 1) * (TOTAL_RACE_HOURS * 60) / MAX_TICKS
            rr = sum(tick_runners_reporting[t]) / len(tick_runners_reporting[t])
            av = sum(tick_avg_velocity[t]) / len(tick_avg_velocity[t])
            aw = sum(tick_avg_water[t]) / len(tick_avg_water[t])
            ad = sum(tick_avg_distance[t]) / len(tick_avg_distance[t])
            sr = sum(tick_status_running[t]) / len(tick_status_running[t])
            sf = sum(tick_status_finished[t]) / len(tick_status_finished[t])
            se = sum(tick_status_exhausted[t]) / len(tick_status_exhausted[t])
            sc = sum(tick_status_collapsed[t]) / len(tick_status_collapsed[t])
            print(
                f"  {t:4d} {elapsed:7.0f}m {rr:5.1f} "
                f"{av:8.4f} {aw:8.2f} {ad:9.4f} "
                f"{sr:5.1f} {sf:5.1f} {se:5.1f} {sc:5.1f}"
            )

        # ── Runners reporting consistency ──
        print("\n── RUNNERS REPORTING PER TICK (must be 5.0 everywhere) ──")
        for t in range(MAX_TICKS):
            vals = tick_runners_reporting[t]
            s = _stats([float(v) for v in vals])
            status = "OK" if s["min"] == RUNNER_COUNT and s["max"] == RUNNER_COUNT else "FAIL"
            print(
                f"  Tick {t:2d}: min={s['min']:.0f} max={s['max']:.0f} "
                f"mean={s['mean']:.1f} std={s['std']:.2f}  [{status}]"
            )

        # ── Velocity distribution per tick ──
        print("\n── AVG VELOCITY DISTRIBUTION PER TICK ──")
        for t in range(MAX_TICKS):
            s = _stats(tick_avg_velocity[t])
            print(f"  Tick {t:2d}: mean={s['mean']:.4f} std={s['std']:.4f} [{s['p5']:.4f}, {s['p95']:.4f}]")

        # ── Water distribution per tick ──
        print("\n── AVG WATER DISTRIBUTION PER TICK ──")
        for t in range(MAX_TICKS):
            s = _stats(tick_avg_water[t])
            print(f"  Tick {t:2d}: mean={s['mean']:.2f}% std={s['std']:.2f} [{s['p5']:.2f}, {s['p95']:.2f}]")

        # ── Distance progression ──
        print("\n── AVG DISTANCE PROGRESSION PER TICK ──")
        for t in range(MAX_TICKS):
            s = _stats(tick_avg_distance[t])
            pct = s["mean"] / MARATHON_MI * 100
            bar = "#" * int(pct / 100 * 40)
            print(f"  Tick {t:2d}: {s['mean']:7.3f} mi ({pct:5.1f}%) |{bar}")

        # ── Status transitions ──
        print("\n── STATUS TRANSITIONS (mean counts across 50 sims) ──")
        print(f"  {'Tick':>4} {'Running':>8} {'Finished':>8} {'Exhausted':>9} {'Collapsed':>9}")
        print("  " + "-" * 40)
        for t in range(MAX_TICKS):
            sr = sum(tick_status_running[t]) / len(tick_status_running[t])
            sf = sum(tick_status_finished[t]) / len(tick_status_finished[t])
            se = sum(tick_status_exhausted[t]) / len(tick_status_exhausted[t])
            sc = sum(tick_status_collapsed[t]) / len(tick_status_collapsed[t])
            total = sr + sf + se + sc
            print(f"  {t:4d} {sr:8.2f} {sf:8.2f} {se:9.2f} {sc:9.2f}  (total={total:.1f})")

        # ── Finish tick distribution ──
        print(f"\n── RUNNER FINISH TICK DISTRIBUTION (n={len(all_finish_ticks)}/{SIM_COUNT * RUNNER_COUNT} runners) ──")
        if all_finish_ticks:
            s = _stats([float(t) for t in all_finish_ticks])
            print(
                f"  mean={s['mean']:.1f} median={s['median']:.0f} std={s['std']:.1f} [{s['min']:.0f}, {s['max']:.0f}]"
            )
            for line in _histogram([float(t) for t in all_finish_ticks], bins=MAX_TICKS):
                print(line)
        else:
            print("  No runners finished (race distance or tick count may be too low)")

        # ── Finish time distribution ──
        print(f"\n── SIMULATED FINISH TIME DISTRIBUTION (n={len(all_finish_times)}) ──")
        if all_finish_times:
            s = _stats(all_finish_times)
            print(
                f"  mean={s['mean']:.1f}min ({s['mean'] / 60:.1f}h) "
                f"median={s['median']:.1f}min std={s['std']:.1f}min "
                f"[{s['min']:.1f}, {s['max']:.1f}]"
            )
            for line in _histogram(all_finish_times, bins=12):
                print(line)
        else:
            print("  No finish times recorded")

        # ── Final state distributions ──
        print(f"\n── FINAL DISTANCE DISTRIBUTION (n={len(all_final_distances)}) ──")
        s = _stats(all_final_distances)
        print(
            f"  mean={s['mean']:.3f}mi median={s['median']:.3f}mi std={s['std']:.3f} [{s['min']:.3f}, {s['max']:.3f}]"
        )
        finished_count = sum(1 for d in all_final_distances if d >= MARATHON_MI)
        total = len(all_final_distances)
        pct = finished_count / total * 100 if total else 0
        print(f"  Runners who crossed finish line: {finished_count}/{total} ({pct:.1f}%)")
        for line in _histogram(all_final_distances, bins=10):
            print(line)

        print(f"\n── FINAL WATER LEVEL DISTRIBUTION (n={len(all_final_water)}) ──")
        s = _stats(all_final_water)
        print(f"  mean={s['mean']:.2f}% median={s['median']:.2f}% std={s['std']:.2f} [{s['min']:.2f}, {s['max']:.2f}]")
        for line in _histogram(all_final_water, bins=10):
            print(line)

        print(f"\n── FINAL VELOCITY DISTRIBUTION (n={len(all_final_velocities)}) ──")
        s = _stats(all_final_velocities)
        print(f"  mean={s['mean']:.4f} median={s['median']:.4f} std={s['std']:.4f} [{s['min']:.4f}, {s['max']:.4f}]")
        for line in _histogram(all_final_velocities, bins=10):
            print(line)

        print("\n" + "=" * 78)
        print("  END OF EVIDENCE REPORT")
        print("=" * 78 + "\n")

    # ── Hard assertions ──
    assert len(anomalies) == 0, f"Found {len(anomalies)} anomalies"
    assert len(all_finish_ticks) > 0, "No runners finished -- test didn't exercise regression"
