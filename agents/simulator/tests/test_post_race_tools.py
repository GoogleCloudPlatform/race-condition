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

"""Tests for post-race skill tools."""

import importlib.util
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Dynamic import since the skill directory is hyphenated
tools_path = pathlib.Path(__file__).parents[1] / "skills" / "post-race" / "tools.py"
spec = importlib.util.spec_from_file_location("post_race.tools", tools_path)
assert spec is not None, f"Could not find module spec for {tools_path}"
assert spec.loader is not None, f"Module spec has no loader for {tools_path}"
tools_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools_module)

compile_results = tools_module.compile_results
stop_race_collector = tools_module.stop_race_collector
call_agent = tools_module.call_agent


def _make_tool_context(state: dict | None = None) -> MagicMock:
    """Create a mock ToolContext with a mutable state dict."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    ctx.session = MagicMock()
    ctx.session.id = "sim-session-1"
    ctx.invocation_id = "inv-001"
    ctx.agent_name = "simulator"
    return ctx


def _sample_tick_snapshots() -> list[dict]:
    """Two tick snapshots for aggregation testing."""
    return [
        {
            "tick": 0,
            "real_time_minutes": 0.0,
            "runners_reporting": 3,
            "avg_velocity": 0.93,
            "avg_water": 95.0,
            "avg_distance": 2.3,
            "status_counts": {"running": 3},
            "notable_events": [],
        },
        {
            "tick": 1,
            "real_time_minutes": 15.0,
            "runners_reporting": 3,
            "avg_velocity": 0.88,
            "avg_water": 85.0,
            "avg_distance": 5.0,
            "status_counts": {"running": 2, "finished": 1},
            "notable_events": ["cramp at mile 9"],
        },
    ]


# ---------------------------------------------------------------------------
# TestCompileResults
# ---------------------------------------------------------------------------
class TestCompileResults:
    """Tests for the compile_results tool."""

    @pytest.mark.asyncio
    async def test_compiles_from_snapshots(self):
        """2 snapshots -> total_ticks=2 with aggregated vitals_trend."""
        snapshots = _sample_tick_snapshots()
        ctx = _make_tool_context(
            state={
                "tick_snapshots": snapshots,
                "runner_count": 3,
                "finished_runner_ids": ["r-1"],
            }
        )

        result = await compile_results(tool_context=ctx)

        assert result["status"] == "success"
        assert result["total_ticks"] == 2

        # vitals_trend should contain per-tick averages
        assert "vitals_trend" in result
        assert len(result["vitals_trend"]) == 2
        assert "avg_velocity" in result["vitals_trend"][0]
        assert "avg_water" in result["vitals_trend"][0]

        # final_status_counts should reflect the LAST tick (not cumulative)
        assert "final_status_counts" in result
        assert result["final_status_counts"]["running"] == 2  # last tick
        assert result["final_status_counts"]["finished"] == 1  # last tick

        # notable_events should be collected
        assert "notable_events" in result
        assert "cramp at mile 9" in result["notable_events"]

        # avg_runners_reporting should be the mean
        assert "avg_runners_reporting" in result
        assert result["avg_runners_reporting"] == 3.0

        # sampling_quality should be present
        assert "sampling_quality" in result

    @pytest.mark.asyncio
    async def test_handles_empty_snapshots(self):
        """0 snapshots -> total_ticks=0 with empty aggregates."""
        ctx = _make_tool_context(state={"tick_snapshots": []})

        result = await compile_results(tool_context=ctx)

        assert result["status"] == "success"
        assert result["total_ticks"] == 0
        assert result["vitals_trend"] == []
        assert result["final_status_counts"] == {}
        assert result["notable_events"] == []
        assert result["avg_runners_reporting"] == 0

    @pytest.mark.asyncio
    async def test_compile_results_returns_simulation_id(self):
        """compile_results should include simulation_id in the return dict."""
        ctx = _make_tool_context(
            state={
                "tick_snapshots": [],
                "runner_count": 5,
                "finished_runner_ids": [],
                "simulation_id": "sim-77",
            }
        )
        result = await compile_results(ctx)
        assert result["status"] == "success"
        assert result["simulation_id"] == "sim-77"

    @pytest.mark.asyncio
    async def test_counts_dnf_runners(self):
        """Runners that did not finish should be counted as DNF."""
        snapshots = _sample_tick_snapshots()
        ctx = _make_tool_context(
            state={
                "tick_snapshots": snapshots,
                "runner_count": 3,
                "finished_runner_ids": ["r-1", "r-2"],
            }
        )

        result = await compile_results(tool_context=ctx)

        assert result["finished_count"] == 2
        assert result["dnf_count"] == 1
        assert result["runner_count"] == 3

    @pytest.mark.asyncio
    async def test_final_status_counts_uses_last_tick(self):
        """final_status_counts must reflect the LAST tick, not sum across all.

        With 100 runners and 11 ticks, summing gives 1100 entries. The
        correct result is the last tick's status_counts which should sum
        to runner_count.
        """
        snapshots = [
            {
                "tick": i,
                "real_time_minutes": i * 30.0,
                "runners_reporting": 100,
                "avg_velocity": 1.0,
                "avg_water": 80.0,
                "avg_distance": i * 2.5,
                "status_counts": {"running": 100 - i * 8, "finished": i * 8},
                "notable_events": [],
            }
            for i in range(11)
        ]
        ctx = _make_tool_context(
            state={
                "tick_snapshots": snapshots,
                "runner_count": 100,
                "finished_runner_ids": [f"r-{j}" for j in range(80)],
            }
        )

        result = await compile_results(tool_context=ctx)

        # final_status_counts must be the LAST tick's counts, not cumulative
        total = sum(result["final_status_counts"].values())
        assert total == 100, (
            f"final_status_counts should sum to runner_count (100), got {total}: {result['final_status_counts']}"
        )
        # Last tick (i=10): running = 100 - 80 = 20, finished = 80
        assert result["final_status_counts"]["running"] == 20
        assert result["final_status_counts"]["finished"] == 80


# ---------------------------------------------------------------------------
# TestStopRaceCollector
# ---------------------------------------------------------------------------
class TestStopRaceCollector:
    """Tests for the stop_race_collector tool."""

    @pytest.mark.asyncio
    async def test_stops_collector(self):
        """RaceCollector.get returns a mock collector; verify stop() is awaited."""
        mock_collector = AsyncMock()
        ctx = _make_tool_context()

        with patch(
            "agents.simulator.collector.RaceCollector.get",
            return_value=mock_collector,
        ):
            result = await stop_race_collector(tool_context=ctx)

        assert result["status"] == "success"
        mock_collector.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_no_collector(self):
        """RaceCollector.get returns None; still returns success."""
        ctx = _make_tool_context()

        with patch(
            "agents.simulator.collector.RaceCollector.get",
            return_value=None,
        ):
            result = await stop_race_collector(tool_context=ctx)

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_stop_race_collector_returns_simulation_id(self):
        """stop_race_collector should include simulation_id in the return dict."""
        ctx = _make_tool_context(
            state={
                "simulation_id": "sim-77",
            }
        )
        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=None),
        ):
            result = await stop_race_collector(ctx)
        assert result["status"] == "success"
        assert result["simulation_id"] == "sim-77"

    @pytest.mark.asyncio
    async def test_clears_simulation_flags(self):
        """stop_race_collector should clear simulation_ready and simulation_in_progress.

        This prevents the race engine from re-running if the root LLM
        re-invokes simulation_pipeline after completion.
        """
        ctx = _make_tool_context(
            state={
                "simulation_ready": True,
                "simulation_in_progress": True,
                "simulation_id": "sim-test-123",
            }
        )

        with patch(
            "agents.simulator.collector.RaceCollector.get",
            return_value=None,
        ):
            await stop_race_collector(tool_context=ctx)

        assert ctx.state.get("simulation_ready") is False, "simulation_ready should be cleared to prevent race re-entry"
        assert ctx.state.get("simulation_in_progress") is False, (
            "simulation_in_progress should be cleared after race ends"
        )
