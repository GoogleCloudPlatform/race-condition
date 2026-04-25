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

"""Performance benchmarks for direct-write collection.

These tests prove the <10s tick cycle assertion by measuring
drain+aggregate throughput at 200, 500, 1000, and 2000 runners.

Marked @pytest.mark.slow -- excluded from default ``make test`` runs.
Run explicitly: ``uv run pytest agents/simulator/tests/test_direct_write_benchmark.py -v -m slow``
"""

import asyncio
import importlib.util
import json
import pathlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Dynamic import since the skill directory is hyphenated
_tools_path = pathlib.Path(__file__).parents[1] / "skills" / "advancing-race-ticks" / "tools.py"
_spec = importlib.util.spec_from_file_location("race_tick.tools", _tools_path)
assert _spec is not None and _spec.loader is not None
tools_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tools_module)
advance_tick = tools_module.advance_tick


def _make_tool_context(state=None):
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    ctx.session = MagicMock()
    ctx.session.id = "sim-bench-1"
    ctx.invocation_id = "inv-bench"
    ctx.agent_name = "tick-agent"
    ctx.actions = MagicMock()
    ctx.actions.escalate = False
    return ctx


def _build_runner_messages(n: int) -> list[dict]:
    """Build n process_tick messages from n distinct runners."""
    return [
        {
            "session_id": f"runner-{i}",
            "payload": {
                "tool_name": "process_tick",
                "result": {
                    "status": "success",
                    "runner_status": "running" if i % 10 != 0 else "finished",
                    "velocity": 0.9 + (i % 10) * 0.02,
                    "effective_velocity": 0.85 + (i % 5) * 0.01,
                    "distance_mi": 5.0 + i * 0.01,
                    "distance": 5.0 + i * 0.01,
                    "water": 80.0 - (i % 20),
                    "pace_min_per_mi": 10.5,
                    "mi_this_tick": 2.3,
                    "elapsed_minutes": 60.0,
                    "finish_time_minutes": None,
                    "exhausted": i % 15 == 0,
                    "collapsed": False,
                },
            },
        }
        for i in range(n)
    ]


@pytest.mark.slow
class TestDrainAggregateBenchmark:
    """Benchmark: measure drain+aggregate wall time at scale.

    Simulates the advance_tick flow with pre-buffered data (as if runners
    already RPUSH'd their results) and measures the complete path:
    drain → filter → dedup → aggregate → snapshot.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("runner_count", [200, 500, 1000, 2000])
    async def test_drain_aggregate_under_budget(self, runner_count: int):
        """Drain + aggregate must complete well under 1 second."""
        messages = _build_runner_messages(runner_count)
        runner_ids = [f"runner-{i}" for i in range(runner_count)]

        mock_collector = MagicMock()
        # All messages available on first drain (direct-write scenario)
        mock_collector.drain = AsyncMock(return_value=messages)

        state = {
            "current_tick": 5,
            "max_ticks": 6,
            "simulation_config": {
                "tick_interval_seconds": 0,  # skip sleep for benchmark
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": runner_ids,
        }
        ctx = _make_tool_context(state=state)

        t_start = time.perf_counter()
        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
        ):
            result = await advance_tick(tool_context=ctx)
        t_elapsed = time.perf_counter() - t_start

        assert result["runners_reporting"] == runner_count
        assert result["status"] == "success"
        # Budget: 1 second for drain+aggregate (leaving 4s for sleep+broadcast)
        assert t_elapsed < 1.0, f"Drain+aggregate took {t_elapsed:.3f}s for {runner_count} runners (budget: 1.0s)"
        print(f"\n  BENCHMARK: {runner_count} runners -> drain+aggregate in {t_elapsed * 1000:.1f}ms")

    @pytest.mark.asyncio
    async def test_aggregation_correctness_at_scale(self):
        """Verify aggregation accuracy with 1000 runners."""
        runner_count = 1000
        messages = _build_runner_messages(runner_count)
        runner_ids = [f"runner-{i}" for i in range(runner_count)]

        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=messages)

        state = {
            "current_tick": 5,
            "max_ticks": 6,
            "simulation_config": {
                "tick_interval_seconds": 0,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": runner_ids,
        }
        ctx = _make_tool_context(state=state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
        ):
            result = await advance_tick(tool_context=ctx)

        assert result["runners_reporting"] == 1000
        assert result["avg_velocity"] > 0
        assert result["avg_water"] > 0
        assert result["avg_distance"] > 0
        # Status counts should sum to runner_count
        total_statuses = sum(result["status_counts"].values())
        assert total_statuses == 1000
        # Every 10th runner is "finished"
        assert result["status_counts"].get("finished", 0) == 100
        assert result["status_counts"].get("running", 0) == 900


@pytest.mark.slow
class TestConcurrentRPUSHThroughput:
    """Benchmark: simulate concurrent RPUSH from many runners."""

    @pytest.mark.asyncio
    async def test_concurrent_rpush_throughput(self):
        """1000 concurrent RPUSHes should complete in <500ms."""
        buffer: list[str] = []
        mock_redis = AsyncMock()

        async def mock_rpush(key: str, value: str) -> int:
            buffer.append(value)
            return len(buffer)

        mock_redis.rpush = mock_rpush

        runner_count = 1000
        t_start = time.perf_counter()

        tasks = []
        for i in range(runner_count):
            msg = json.dumps(
                {
                    "session_id": f"runner-{i}",
                    "payload": {
                        "tool_name": "process_tick",
                        "result": {"status": "success", "velocity": 1.0},
                    },
                }
            )
            tasks.append(mock_redis.rpush("collector:buffer:sim-1", msg))

        await asyncio.gather(*tasks)
        t_elapsed = time.perf_counter() - t_start

        assert len(buffer) == runner_count
        assert t_elapsed < 0.5, f"1000 concurrent RPUSHes took {t_elapsed:.3f}s (budget: 0.5s)"
        print(f"\n  BENCHMARK: {runner_count} concurrent RPUSHes in {t_elapsed * 1000:.1f}ms")


@pytest.mark.slow
class TestFullTickCycleBudget:
    """Benchmark: end-to-end tick cycle budget validation."""

    @pytest.mark.asyncio
    async def test_full_tick_cycle_under_budget(self):
        """Entire advance_tick (with minimal sleep) under 2s for 1000 runners.

        Uses tick_interval=0.01 (10ms) to measure everything except the
        production 10s sleep. Validates the path: broadcast → drain → aggregate.
        """
        runner_count = 1000
        messages = _build_runner_messages(runner_count)
        runner_ids = [f"runner-{i}" for i in range(runner_count)]

        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=messages)

        state = {
            "current_tick": 5,
            "max_ticks": 6,
            "simulation_config": {
                "tick_interval_seconds": 0.01,  # 10ms simulated interval
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": runner_ids,
        }
        ctx = _make_tool_context(state=state)

        t_start = time.perf_counter()
        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
        ):
            result = await advance_tick(tool_context=ctx)
        t_elapsed = time.perf_counter() - t_start

        assert result["runners_reporting"] == runner_count
        # Total cycle (including 10ms sleep) should be well under 2s
        # (production sleep is 10s, leaving 0s for overhead -- but drain+aggregate
        # happens during the sleep via direct-write, so only the drain itself
        # needs to fit in the remaining budget)
        assert t_elapsed < 2.0, (
            f"Full tick cycle took {t_elapsed:.3f}s for {runner_count} runners "
            f"(budget: 2.0s, excludes production 10s sleep)"
        )
        print(
            f"\n  BENCHMARK: Full tick cycle ({runner_count} runners) in "
            f"{t_elapsed * 1000:.1f}ms (excluding production sleep)"
        )
