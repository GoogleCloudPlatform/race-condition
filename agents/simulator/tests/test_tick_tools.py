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

"""Tests for race-tick skill tools."""

import importlib.util
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# perf_counter mock helper — controls time.perf_counter() inside tools.py
# so the early-wake drain loop exits deterministically.
# ---------------------------------------------------------------------------


def _make_clock(step: float = 0.2):
    """Return a callable that increments by *step* on each call.

    Used to patch ``time.perf_counter`` in the tools module so the
    early-wake loop sees time advance by *step* per call.
    """
    t = [0.0]

    def _clock() -> float:
        val = t[0]
        t[0] += step
        return val

    return _clock


# Dynamic import since the skill directory is hyphenated
tools_path = pathlib.Path(__file__).parents[1] / "skills" / "race-tick" / "tools.py"
spec = importlib.util.spec_from_file_location("race_tick.tools", tools_path)
assert spec is not None, f"Could not find module spec for {tools_path}"
assert spec.loader is not None, f"Module spec has no loader for {tools_path}"
tools_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools_module)

advance_tick = tools_module.advance_tick
check_race_complete = tools_module.check_race_complete


def _make_tool_context(state: dict | None = None) -> MagicMock:
    """Create a mock ToolContext with a mutable state dict and actions."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    ctx.session = MagicMock()
    ctx.session.id = "sim-session-1"
    ctx.invocation_id = "inv-001"
    ctx.agent_name = "tick-agent"
    ctx.actions = MagicMock()
    ctx.actions.escalate = False
    return ctx


def _sample_drain_messages() -> list[dict]:
    """Sample messages matching process_tick tool_end output."""
    return [
        {
            "session_id": "runner-1",
            "agent_id": "runner_autopilot",
            "event": "tool_end",
            "msg_type": "json",
            "timestamp": "2026-03-21T10:00:00",
            "payload": {
                "tool_name": "process_tick",
                "result": {
                    "status": "success",
                    "runner_status": "running",
                    "velocity": 0.93,
                    "effective_velocity": 0.85,
                    "distance_mi": 2.3,
                    "distance": 2.3,
                    "water": 95.0,
                    "pace_min_per_mi": None,
                    "mi_this_tick": 2.3,
                    "exhausted": False,
                    "collapsed": False,
                },
            },
        },
        {
            "session_id": "runner-2",
            "agent_id": "runner_autopilot",
            "event": "tool_end",
            "msg_type": "json",
            "timestamp": "2026-03-21T10:00:00",
            "payload": {
                "tool_name": "process_tick",
                "result": {
                    "status": "success",
                    "runner_status": "exhausted",
                    "velocity": 0.60,
                    "effective_velocity": 0.30,
                    "distance_mi": 1.5,
                    "distance": 1.5,
                    "water": 25.0,
                    "pace_min_per_mi": None,
                    "mi_this_tick": 1.5,
                    "exhausted": True,
                    "collapsed": False,
                    "notable_event": "cramp at mile 9",
                },
            },
        },
        {
            "session_id": "runner-3",
            "agent_id": "runner_autopilot",
            "event": "tool_end",
            "msg_type": "json",
            "timestamp": "2026-03-21T10:00:00",
            "payload": {
                "tool_name": "process_tick",
                "result": {
                    "status": "success",
                    "runner_status": "finished",
                    "velocity": 1.1,
                    "effective_velocity": 0.0,
                    "distance_mi": 42.2,
                    "distance": 42.2,
                    "water": 40.0,
                    "pace_min_per_mi": 5.8,
                    "mi_this_tick": 2.8,
                    "exhausted": False,
                    "collapsed": False,
                    "finish_time_minutes": 245.0,
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# TestAdvanceTick
# ---------------------------------------------------------------------------
class TestAdvanceTick:
    """Tests for the advance_tick tool."""

    @pytest.mark.asyncio
    async def test_appends_tick_snapshot(self):
        """advance_tick should append a snapshot dict to state['tick_snapshots']."""
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=_sample_drain_messages())

        state = {
            "current_tick": 5,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            await advance_tick(tool_context=ctx)

        # Verify snapshot was appended
        assert len(ctx.state["tick_snapshots"]) == 1
        snapshot = ctx.state["tick_snapshots"][0]
        assert "tick" in snapshot
        assert "runners_reporting" in snapshot
        assert snapshot["runners_reporting"] == 3

    @pytest.mark.asyncio
    async def test_returns_aggregate_stats(self):
        """advance_tick should return a dict with runners_reporting and tick keys."""
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=_sample_drain_messages())

        state = {
            "current_tick": 10,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        assert isinstance(result, dict)
        assert result["runners_reporting"] == 3
        assert result["tick"] == 10
        assert "status" in result

    @pytest.mark.asyncio
    async def test_broadcasts_runner_event_tick(self):
        """advance_tick should broadcast a serialized RunnerEvent with event='tick'."""
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=[])

        state = {
            "current_tick": 3,
            "max_ticks": 10,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": [],
        }
        ctx = _make_tool_context(state=state)

        mock_publish = AsyncMock()
        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", mock_publish),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            await advance_tick(tool_context=ctx)

        mock_publish.assert_called_once()
        published_data = mock_publish.call_args[0][0]
        parsed = json.loads(published_data)
        assert parsed["event"] == "tick"
        assert parsed["tick"] == 3
        assert parsed["max_ticks"] == 10
        assert "minutes_per_tick" in parsed
        assert "elapsed_minutes" in parsed
        assert "race_distance_mi" in parsed
        assert "session_id" not in parsed

    @pytest.mark.asyncio
    async def test_filters_non_process_tick_messages(self):
        """advance_tick should only aggregate process_tick tool_end messages.

        Runners emit multiple events per tick (function_call, tool_end, text
        summary). Only process_tick tool_end events contain valid telemetry.
        Non-matching messages must be skipped, and runners_reporting should
        count unique session IDs, not total messages.
        """
        # Mix of process_tick results and other runner events
        messages = [
            # Runner-1 process_tick result (the only one we should aggregate)
            {
                "session_id": "runner-1",
                "agent_id": "runner_autopilot",
                "event": "tool_end",
                "msg_type": "json",
                "payload": {
                    "tool_name": "process_tick",
                    "result": {
                        "status": "success",
                        "runner_status": "running",
                        "velocity": 0.93,
                        "distance_mi": 2.3,
                        "distance": 2.3,
                        "water": 95.0,
                    },
                },
            },
            # Runner-1 text summary (should be skipped)
            {
                "session_id": "runner-1",
                "agent_id": "runner_autopilot",
                "event": "model_output",
                "msg_type": "text",
                "payload": "Status: running, velocity=0.9, water=95%",
            },
            # Runner-1 function_call event (should be skipped)
            {
                "session_id": "runner-1",
                "agent_id": "runner_autopilot",
                "event": "tool_call",
                "msg_type": "json",
                "payload": {"tool_name": "process_tick", "args": {}},
            },
            # Runner-2 process_tick result
            {
                "session_id": "runner-2",
                "agent_id": "runner_autopilot",
                "event": "tool_end",
                "msg_type": "json",
                "payload": {
                    "tool_name": "process_tick",
                    "result": {
                        "status": "success",
                        "runner_status": "running",
                        "velocity": 0.80,
                        "distance_mi": 2.0,
                        "distance": 2.0,
                        "water": 90.0,
                    },
                },
            },
        ]
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=messages)

        state = {
            "current_tick": 0,
            "max_ticks": 10,
            "simulation_config": {"tick_interval_seconds": 10, "total_race_hours": 6.0},
            "tick_snapshots": [],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        # Should report 2 unique runners, not 4 total messages
        assert result["runners_reporting"] == 2, f"Expected 2 unique runners, got {result['runners_reporting']}"
        # Status counts should only have "running", not "unknown"
        assert "unknown" not in result["status_counts"], (
            f"Non-process_tick messages should not produce 'unknown' status: {result['status_counts']}"
        )
        assert result["status_counts"].get("running") == 2

    @pytest.mark.asyncio
    async def test_passes_simulation_id_to_broadcast(self):
        """advance_tick should pass simulation_id from state to publish_to_runners."""
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=[])

        state = {
            "current_tick": 0,
            "max_ticks": 10,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": [],
            "simulation_id": "sim-tick-456",
        }
        ctx = _make_tool_context(state=state)

        mock_publish = AsyncMock()
        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", mock_publish),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            await advance_tick(tool_context=ctx)

        mock_publish.assert_called_once()
        call_kwargs = mock_publish.call_args
        assert call_kwargs[1].get("simulation_id") == "sim-tick-456"

    @pytest.mark.asyncio
    async def test_advance_tick_returns_simulation_id(self):
        """advance_tick should include simulation_id in the return dict."""
        state = {
            "current_tick": 0,
            "max_ticks": 6,
            "simulation_config": {"tick_interval_seconds": 0, "total_race_hours": 6.0},
            "simulation_id": "sim-77",
        }
        ctx = _make_tool_context(state=state)
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=[])
        with (
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(ctx)
        assert result["status"] == "success"
        assert result["simulation_id"] == "sim-77"

    @pytest.mark.asyncio
    async def test_polling_skips_retry_when_all_runners_report(self):
        """When all runners report during early-wake drain, no post-sleep poll occurs.

        With the progressive drain, the first drain inside the sleep window
        finds all runners, so the function sleeps for the remaining
        tick_interval floor then returns.  No post-sleep poll loop is entered.
        """
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=_sample_drain_messages())

        state = {
            "current_tick": 1,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
        }
        ctx = _make_tool_context(state=state)

        sleep_calls: list[float] = []
        original_sleep = AsyncMock(side_effect=lambda s: sleep_calls.append(s))

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", original_sleep),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        assert result["runners_reporting"] == 3
        # Early-wake: first sleep is drain_interval (0.2), then remaining
        # tick_interval floor.  No post-sleep poll sleeps.
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == pytest.approx(0.2, abs=0.01)  # drain_interval
        assert sleep_calls[1] >= 9.0, f"Floor sleep too short: {sleep_calls[1]}"

    @pytest.mark.asyncio
    async def test_polling_retries_until_all_runners_report(self):
        """When some runners are late, early-wake drain collects them progressively."""
        sample = _sample_drain_messages()
        first_batch = [sample[0]]  # runner-1 only
        second_batch = [sample[1]]  # runner-2
        third_batch = [sample[2]]  # runner-3

        mock_collector = MagicMock()
        # drain calls: 1st = pre-flush, then 3 early-wake drains
        mock_collector.drain = AsyncMock(side_effect=[[], first_batch, second_batch, third_batch])

        state = {
            "current_tick": 1,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
                "max_collection_seconds": 30,
                "poll_interval": 0.5,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        assert result["runners_reporting"] == 3
        assert mock_collector.drain.call_count == 4  # 1 pre-flush + 3 early-wake

    @pytest.mark.asyncio
    async def test_polling_stops_at_max_collection_timeout(self):
        """Post-sleep poll stops after max_collection_seconds even if not all runners reported.

        Clock: step=0.2, tick_interval=0.4 → 2 early-wake iterations,
        max_collection=0.8 → 4 post-sleep poll iterations.
        """
        sample = _sample_drain_messages()
        first_batch = [sample[0]]  # runner-1 only

        mock_collector = MagicMock()
        # drain calls: 1 pre-flush + 2 early-wake + 4 post-sleep polls = 7
        mock_collector.drain = AsyncMock(side_effect=[[]] + [first_batch] + [[] for _ in range(20)])

        state = {
            "current_tick": 1,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 0.4,
                "total_race_hours": 6.0,
                "max_collection_seconds": 0.8,
                "poll_interval": 0.2,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        assert result["runners_reporting"] == 1
        assert result["avg_velocity"] > 0
        # Bounded: 1 pre-flush + 2 early-wake + 4 post-sleep polls = 7
        assert mock_collector.drain.call_count <= 8  # small margin

    @pytest.mark.asyncio
    async def test_polling_deduplicates_across_drains(self):
        """Same runner appearing in multiple drains should be counted once."""
        sample = _sample_drain_messages()
        first_batch = [sample[0]]  # runner-1
        second_batch = [sample[0], sample[1]]  # runner-1 again + runner-2

        mock_collector = MagicMock()
        # drain calls: 1st = pre-flush, then 2 early-wake drains
        mock_collector.drain = AsyncMock(side_effect=[[], first_batch, second_batch])

        state = {
            "current_tick": 1,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
                "max_collection_seconds": 30,
                "poll_interval": 0.5,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2"],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        # runner-1 not double-counted
        assert result["runners_reporting"] == 2

    @pytest.mark.asyncio
    async def test_finished_runners_included_in_aggregation(self):
        """Finished runners reporting via process_tick must be included in averages.

        Regression test: previously, handle_tick returned text for finished
        runners, which caused advance_tick to skip them. This verifies that
        when finished runners DO report process_tick, they are aggregated.
        """
        messages = [
            {
                "session_id": "runner-active",
                "agent_id": "runner_autopilot",
                "event": "tool_end",
                "msg_type": "json",
                "payload": {
                    "tool_name": "process_tick",
                    "result": {
                        "status": "success",
                        "runner_status": "running",
                        "velocity": 1.0,
                        "distance_mi": 10.0,
                        "distance": 10.0,
                        "water": 80.0,
                    },
                },
            },
            {
                "session_id": "runner-done",
                "agent_id": "runner_autopilot",
                "event": "tool_end",
                "msg_type": "json",
                "payload": {
                    "tool_name": "process_tick",
                    "result": {
                        "status": "success",
                        "runner_status": "finished",
                        "velocity": 0.9,
                        "effective_velocity": 0.0,
                        "distance_mi": 26.2188,
                        "distance": 26.2188,
                        "water": 45.0,
                        "mi_this_tick": 0.0,
                        "finish_time_minutes": 240.0,
                    },
                },
            },
        ]
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=messages)

        state = {
            "current_tick": 5,
            "max_ticks": 6,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-active", "runner-done"],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        # BOTH runners must be counted
        assert result["runners_reporting"] == 2
        assert result["status_counts"].get("running") == 1
        assert result["status_counts"].get("finished") == 1

        # Averages must include finished runner's data (non-zero)
        assert result["avg_velocity"] > 0
        assert result["avg_water"] > 0
        assert result["avg_distance"] > 0

        # Finished runner tracked in state and return dict
        assert "runner-done" in ctx.state["finished_runner_ids"]
        assert "runner-done" in result["finished_runner_ids"]

    @pytest.mark.asyncio
    async def test_all_finished_runners_still_report(self):
        """When ALL runners are finished, averages must still be non-zero.

        This is the exact regression scenario: tick N-1 had 1 runner still
        running, tick N has 0 running (all finished). Previously this caused
        runners_reporting=0 and all averages=0.
        """
        messages = [
            {
                "session_id": f"runner-{i}",
                "agent_id": "runner_autopilot",
                "event": "tool_end",
                "msg_type": "json",
                "payload": {
                    "tool_name": "process_tick",
                    "result": {
                        "status": "success",
                        "runner_status": "finished",
                        "velocity": 0.8 + i * 0.05,
                        "effective_velocity": 0.0,
                        "distance_mi": 26.2188,
                        "distance": 26.2188,
                        "water": 40.0 + i * 5,
                        "mi_this_tick": 0.0,
                        "finish_time_minutes": 220.0 + i * 10,
                    },
                },
            }
            for i in range(5)
        ]
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=messages)

        state = {
            "current_tick": 5,
            "max_ticks": 6,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": [f"runner-{i}" for i in range(5)],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        # ALL 5 runners must report even though all are finished
        assert result["runners_reporting"] == 5
        assert result["status_counts"].get("finished") == 5

        # Averages must be non-zero (runners have preserved state)
        assert result["avg_velocity"] > 0
        assert result["avg_water"] > 0
        assert result["avg_distance"] > 0

    @pytest.mark.asyncio
    async def test_aggregation_skips_stale_tick_messages(self):
        """advance_tick must skip process_tick results from previous ticks.

        Reproduces the bug where stale messages from tick N-1 arrive in the
        collector buffer after the pre-broadcast stale drain, winning the
        first-wins session_id dedup and contaminating tick N's aggregation.
        """
        stale_result = {
            "runner_status": "running",
            "velocity": 1.0,
            "effective_velocity": 0.9,
            "water": 80.0,
            "distance_mi": 22.0,
            "tick": 2,
        }
        current_result = {
            "runner_status": "finished",
            "velocity": 1.0,
            "effective_velocity": 0.0,
            "water": 75.0,
            "distance_mi": 28.0,
            "tick": 3,
        }
        messages = [
            {
                "session_id": "runner-1",
                "payload": {"tool_name": "process_tick", "result": stale_result},
            },
            {
                "session_id": "runner-1",
                "payload": {"tool_name": "process_tick", "result": current_result},
            },
        ]

        state = {
            "current_tick": 3,
            "max_ticks": 6,
            "simulation_config": {"tick_interval_seconds": 0, "total_race_hours": 6.0},
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1"],
            "simulation_id": "sim-stale-test",
        }
        ctx = _make_tool_context(state)

        mock_collector = MagicMock()
        # First drain returns empty (stale flush), second returns both messages
        mock_collector.drain = AsyncMock(side_effect=[[], messages])

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
        ):
            result = await advance_tick(tool_context=ctx)

        # The stale message (tick=2, running, distance=22) must be skipped.
        # Only the current message (tick=3, finished, distance=28) should be aggregated.
        assert result["status_counts"] == {"finished": 1}, (
            f"Expected only 'finished' status from current tick, got {result['status_counts']}"
        )
        assert result["avg_distance"] == 28.0
        assert "runner-1" in result["finished_runner_ids"]

    @pytest.mark.asyncio
    async def test_status_counts_finished_uses_cumulative_state(self):
        """status_counts['finished'] must reflect all known finishers, not just
        runners that reported 'finished' on the current tick.

        Reproduces the scenario where runner-2 finished on a previous tick
        (present in state.finished_runner_ids) but only runner-1 reports on
        the current tick.  Without reconciliation, status_counts would show
        finished=0 even though runner-2 is known to have finished.
        """
        current_result = {
            "runner_status": "running",
            "velocity": 1.0,
            "effective_velocity": 0.9,
            "water": 70.0,
            "distance_mi": 24.0,
            "tick": 5,
        }
        messages = [
            {
                "session_id": "runner-1",
                "payload": {"tool_name": "process_tick", "result": current_result},
            },
        ]

        state = {
            "current_tick": 5,
            "max_ticks": 6,
            "simulation_config": {"tick_interval_seconds": 0, "total_race_hours": 6.0},
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2"],
            "simulation_id": "sim-cumulative-test",
            # runner-2 finished on a previous tick
            "finished_runner_ids": ["runner-2"],
        }
        ctx = _make_tool_context(state)

        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(side_effect=[[], messages])

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
        ):
            result = await advance_tick(tool_context=ctx)

        # status_counts must include the cumulative finisher (runner-2)
        assert result["status_counts"].get("finished", 0) == 1, (
            f"Expected finished=1 from cumulative state, got {result['status_counts']}"
        )
        # runner-1 reported as running on this tick
        assert result["status_counts"].get("running", 0) == 1
        # cumulative finished_runner_ids must still contain runner-2
        assert "runner-2" in result["finished_runner_ids"]

    @pytest.mark.asyncio
    async def test_return_value_includes_max_ticks(self):
        """The advance_tick return dict must include max_ticks so the
        frontend can compute progress from the tool_end event."""
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=[])

        state = {
            "current_tick": 3,
            "max_ticks": 6,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": [],
            "simulation_id": "sim-max-ticks-test",
        }
        ctx = _make_tool_context(state=state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        assert "max_ticks" in result, f"Return missing 'max_ticks': {result.keys()}"
        assert result["max_ticks"] == 6


# ---------------------------------------------------------------------------
# TestCheckRaceComplete
# ---------------------------------------------------------------------------
class TestCheckRaceComplete:
    """Tests for the check_race_complete tool."""

    @pytest.mark.asyncio
    async def test_escalates_at_max_ticks(self):
        """When current_tick >= max_ticks, escalate should be True."""
        state = {"current_tick": 24, "max_ticks": 24}
        ctx = _make_tool_context(state=state)

        result = await check_race_complete(tool_context=ctx)

        assert result["status"] == "race_complete"
        assert ctx.actions.escalate is True

    @pytest.mark.asyncio
    async def test_does_not_escalate_mid_race(self):
        """When current_tick < max_ticks, race is in_progress."""
        state = {"current_tick": 10, "max_ticks": 24}
        ctx = _make_tool_context(state=state)

        result = await check_race_complete(tool_context=ctx)

        assert result["status"] == "in_progress"
        assert result["ticks_remaining"] == 14
        # escalate should NOT be set to True
        assert ctx.actions.escalate is not True

    @pytest.mark.asyncio
    async def test_check_race_complete_returns_simulation_id_when_complete(self):
        """check_race_complete should include simulation_id when race is complete."""
        ctx = _make_tool_context(
            state={
                "current_tick": 6,
                "max_ticks": 6,
                "simulation_id": "sim-77",
            }
        )
        result = await check_race_complete(ctx)
        assert result["status"] == "race_complete"
        assert result["simulation_id"] == "sim-77"

    @pytest.mark.asyncio
    async def test_check_race_complete_returns_simulation_id_when_in_progress(self):
        """check_race_complete should include simulation_id when race is in progress."""
        ctx = _make_tool_context(
            state={
                "current_tick": 3,
                "max_ticks": 6,
                "simulation_id": "sim-77",
            }
        )
        result = await check_race_complete(ctx)
        assert result["status"] == "in_progress"
        assert result["simulation_id"] == "sim-77"


# ---------------------------------------------------------------------------
# TestEarlyWakeDrain — Change 1 tests
# ---------------------------------------------------------------------------
class TestEarlyWakeDrain:
    """Tests for progressive drain during the sleep window."""

    @pytest.mark.asyncio
    async def test_collects_during_sleep_window(self):
        """Drain should be called multiple times during tick_interval sleep window.

        Clock: step=0.2, tick_interval=10.0. Runners arrive progressively
        across 3 early-wake drain calls. All 3 report by the 3rd drain,
        then the function waits for the remaining tick_interval floor.
        """
        sample = _sample_drain_messages()

        mock_collector = MagicMock()
        # pre-flush + 3 early-wake drains (runners arrive progressively)
        mock_collector.drain = AsyncMock(
            side_effect=[
                [],  # pre-flush
                [sample[0]],  # runner-1
                [sample[1]],  # runner-2
                [sample[2]],  # runner-3 → all reported
            ]
        )

        state = {
            "current_tick": 0,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 10.0,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
        }
        ctx = _make_tool_context(state=state)

        sleep_calls: list[float] = []
        mock_sleep = AsyncMock(side_effect=lambda s: sleep_calls.append(s))

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", mock_sleep),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        assert result["runners_reporting"] == 3
        # 3 early-wake drain sleeps + 1 remaining-floor sleep = 4 total
        assert len(sleep_calls) == 4
        # Last sleep should be the remaining tick_interval floor (> 9s)
        assert sleep_calls[-1] > 8.5, f"Floor sleep too short: {sleep_calls[-1]}"

    @pytest.mark.asyncio
    async def test_tick_interval_floor_respected(self):
        """Even when all runners report at t=0.2, tick must wait until tick_interval.

        Clock: step=0.2, tick_interval=10.0. All runners report on first drain.
        The remaining floor sleep should be ~9.6s.
        """
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=_sample_drain_messages())

        state = {
            "current_tick": 0,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 10.0,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
        }
        ctx = _make_tool_context(state=state)

        sleep_calls: list[float] = []
        mock_sleep = AsyncMock(side_effect=lambda s: sleep_calls.append(s))

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", mock_sleep),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        assert result["runners_reporting"] == 3
        # First sleep: drain_interval (0.2), second sleep: remaining floor (~9.6)
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == pytest.approx(0.2, abs=0.01)
        assert sleep_calls[1] > 9.0, f"Floor sleep too short: {sleep_calls[1]}"

    @pytest.mark.asyncio
    async def test_perf_trace_log_on_early_completion(self):
        """PERF_TRACE log should appear when all runners report early."""
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=_sample_drain_messages())

        state = {
            "current_tick": 0,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 10.0,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
            patch.object(tools_module.logger, "info") as mock_log,
        ):
            await advance_tick(tool_context=ctx)

        # Check PERF_TRACE was logged
        perf_trace_calls = [call for call in mock_log.call_args_list if "PERF_TRACE" in str(call)]
        assert len(perf_trace_calls) == 1, f"Expected 1 PERF_TRACE log, got {len(perf_trace_calls)}"

    @pytest.mark.asyncio
    async def test_no_post_sleep_poll_when_all_reported(self):
        """When all runners report during sleep window, post-sleep poll is skipped."""
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=_sample_drain_messages())

        state = {
            "current_tick": 0,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 10.0,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
        }
        ctx = _make_tool_context(state=state)

        sleep_calls: list[float] = []
        mock_sleep = AsyncMock(side_effect=lambda s: sleep_calls.append(s))

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", mock_sleep),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        # Only drain_interval + remaining floor. No poll_interval (0.2) calls
        # after the floor sleep.
        assert result["runners_reporting"] == 3
        # 2 calls: drain_interval then floor remainder. No poll sleeps.
        assert len(sleep_calls) == 2


# ---------------------------------------------------------------------------
# TestMaxCollectionDefault — Change 2 tests
# ---------------------------------------------------------------------------
class TestMaxCollectionDefault:
    """max_collection_seconds should default to tick_interval (not 2x)."""

    @pytest.mark.asyncio
    async def test_max_collection_defaults_to_tick_interval(self):
        """Without explicit max_collection_seconds config, default is tick_interval.

        Clock: step=0.2, tick_interval=0.4 -> 2 early-wake iterations.
        max_collection defaults to 0.4 -> 2 post-sleep poll iterations.
        """
        mock_collector = MagicMock()
        # Enough drain results for early-wake + post-sleep, none find all runners
        mock_collector.drain = AsyncMock(
            side_effect=[
                [],  # pre-flush
            ]
            + [[] for _ in range(20)]
        )

        state = {
            "current_tick": 0,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 0.4,
                "total_race_hours": 6.0,
                # NO max_collection_seconds -- should default to tick_interval
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2"],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        # 0 runners reported (all drains empty), but function completes
        assert result["runners_reporting"] == 0
        # max_collection = tick_interval = 0.4 (2 poll iterations at step=0.2)
        # Total drains: 1 pre-flush + 2 early-wake + 2 post-sleep = 5
        assert mock_collector.drain.call_count <= 6  # margin


# ---------------------------------------------------------------------------
# TestPollIntervalDefault — Change 3 tests
# ---------------------------------------------------------------------------
class TestPollIntervalDefault:
    """poll_interval should default to 0.2s (not 0.05s)."""

    @pytest.mark.asyncio
    async def test_poll_interval_defaults_to_200ms(self):
        """Without explicit poll_interval config, default is 0.2.

        We verify that the advance_tick function reads poll_interval=0.2
        when no config is provided, and uses it in the post-sleep poll loop.
        """
        sample = _sample_drain_messages()

        mock_collector = MagicMock()
        # pre-flush + early-wake drains (1 runner found) + post-sleep polls
        mock_collector.drain = AsyncMock(
            side_effect=[
                [],  # pre-flush
            ]
            + [[sample[0]]]
            + [[] for _ in range(30)]
        )

        state = {
            "current_tick": 0,
            "max_ticks": 24,
            "simulation_config": {
                "tick_interval_seconds": 1.0,
                "total_race_hours": 6.0,
                "max_collection_seconds": 2.0,
                # NO poll_interval -- should default to 0.2
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
        }
        ctx = _make_tool_context(state=state)

        sleep_calls: list[float] = []
        mock_sleep = AsyncMock(side_effect=lambda s: sleep_calls.append(s))

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", mock_sleep),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            await advance_tick(tool_context=ctx)

        # Post-sleep poll should use 0.2s intervals (the default poll_interval)
        poll_sleeps = [s for s in sleep_calls if s == pytest.approx(0.2, abs=0.01)]
        assert len(poll_sleeps) > 0, f"Expected 0.2s poll sleeps, got: {sleep_calls}"
        # None of the sleeps should be the old 0.05 default
        old_default_sleeps = [s for s in sleep_calls if abs(s - 0.05) < 0.01]
        assert len(old_default_sleeps) == 0, f"Found old 0.05 poll intervals: {sleep_calls}"


# ---------------------------------------------------------------------------
# TestCollectReportingRunners — Change 4 tests (tick filtering)
# ---------------------------------------------------------------------------
_collect_reporting_runners = tools_module._collect_reporting_runners


class TestCollectReportingRunners:
    """Tests for _collect_reporting_runners tick filtering."""

    def test_collect_reporting_runners_filters_stale_ticks(self):
        """_collect_reporting_runners must skip messages from non-current ticks."""
        stale_msg = {
            "session_id": "runner-1",
            "payload": {
                "tool_name": "process_tick",
                "result": {"tick": 2, "runner_status": "running"},
            },
        }
        current_msg = {
            "session_id": "runner-2",
            "payload": {
                "tool_name": "process_tick",
                "result": {"tick": 3, "runner_status": "finished"},
            },
        }
        dest: set[str] = set()
        _collect_reporting_runners([stale_msg, current_msg], dest, current_tick=3)
        assert dest == {"runner-2"}


# ---------------------------------------------------------------------------
# TestCollapsedRunnerTracking — Task 3 tests
# ---------------------------------------------------------------------------
class TestCollapsedRunnerTracking:
    """Tests for collapsed runner tracking and broadcast exclude list."""

    @pytest.mark.asyncio
    async def test_collapsed_runners_tracked_in_state(self):
        """When a runner reports runner_status='collapsed', its session ID
        should be accumulated in state['collapsed_runner_ids']."""
        messages = [
            {
                "session_id": "runner-1",
                "agent_id": "runner_autopilot",
                "event": "tool_end",
                "msg_type": "json",
                "payload": {
                    "tool_name": "process_tick",
                    "result": {
                        "status": "success",
                        "runner_status": "running",
                        "velocity": 0.93,
                        "effective_velocity": 0.85,
                        "distance_mi": 2.3,
                        "distance": 2.3,
                        "water": 95.0,
                    },
                },
            },
            {
                "session_id": "runner-2",
                "agent_id": "runner_autopilot",
                "event": "tool_end",
                "msg_type": "json",
                "payload": {
                    "tool_name": "process_tick",
                    "result": {
                        "status": "success",
                        "runner_status": "collapsed",
                        "velocity": 0.0,
                        "effective_velocity": 0.0,
                        "distance_mi": 15.0,
                        "distance": 15.0,
                        "water": 5.0,
                    },
                },
            },
        ]
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=messages)

        state = {
            "current_tick": 3,
            "max_ticks": 10,
            "simulation_config": {"tick_interval_seconds": 0, "total_race_hours": 6.0},
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2"],
            "simulation_id": "sim-collapse-test",
        }
        ctx = _make_tool_context(state=state)

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
        ):
            await advance_tick(tool_context=ctx)

        # Collapsed runner should be tracked in state
        assert "collapsed_runner_ids" in ctx.state
        assert "runner-2" in ctx.state["collapsed_runner_ids"]
        # Running runner should NOT be in collapsed list
        assert "runner-1" not in ctx.state["collapsed_runner_ids"]

    @pytest.mark.asyncio
    async def test_broadcast_includes_exclude_ids(self):
        """When finished_runner_ids and collapsed_runner_ids exist in state,
        publish_to_runners should be called with exclude_runner_ids containing
        those IDs."""
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=[])

        state = {
            "current_tick": 5,
            "max_ticks": 10,
            "simulation_config": {"tick_interval_seconds": 0, "total_race_hours": 6.0},
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3", "runner-4"],
            "simulation_id": "sim-exclude-test",
            "finished_runner_ids": ["runner-1"],
            "collapsed_runner_ids": ["runner-2"],
        }
        ctx = _make_tool_context(state=state)

        mock_publish = AsyncMock()
        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", mock_publish),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            await advance_tick(tool_context=ctx)

        mock_publish.assert_called_once()
        call_kwargs = mock_publish.call_args
        exclude_ids = call_kwargs[1].get("exclude_runner_ids")
        assert exclude_ids is not None, "publish_to_runners should receive exclude_runner_ids"
        assert set(exclude_ids) == {"runner-1", "runner-2"}

    @pytest.mark.asyncio
    async def test_expected_count_excludes_finished_and_collapsed(self):
        """The expected runner count should be reduced by the number of
        finished and collapsed runners so the simulator doesn't wait for them."""
        # Only runner-3 is active; runner-1 finished, runner-2 collapsed
        active_runner_msg = {
            "session_id": "runner-3",
            "agent_id": "runner_autopilot",
            "event": "tool_end",
            "msg_type": "json",
            "payload": {
                "tool_name": "process_tick",
                "result": {
                    "status": "success",
                    "runner_status": "running",
                    "velocity": 0.8,
                    "effective_velocity": 0.75,
                    "distance_mi": 10.0,
                    "distance": 10.0,
                    "water": 70.0,
                    "tick": 5,
                },
            },
        }
        mock_collector = MagicMock()
        # pre-flush empty, then runner-3 reports
        mock_collector.drain = AsyncMock(side_effect=[[], [active_runner_msg]])

        state = {
            "current_tick": 5,
            "max_ticks": 10,
            "simulation_config": {
                "tick_interval_seconds": 0.4,
                "total_race_hours": 6.0,
                "max_collection_seconds": 0.8,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1", "runner-2", "runner-3"],
            "simulation_id": "sim-count-test",
            "finished_runner_ids": ["runner-1"],
            "collapsed_runner_ids": ["runner-2"],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch("agents.simulator.collector.RaceCollector.get", return_value=mock_collector),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            result = await advance_tick(tool_context=ctx)

        # Only runner-3 is active, so expected_count=1.
        # runner-3 reported, so runners_reporting=1 and no timeout warning.
        assert result["runners_reporting"] == 1
        # The function should NOT log a "timeout waiting for runners" warning
        # because all active runners (1) reported.

    # Wave stagger tests removed — stagger now happens in the plugin's
    # gateway emission (via gateway_delay_seconds in process_tick result),
    # not in the simulator broadcast.
